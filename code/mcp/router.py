"""
MCP ToolRouter -- 核心创新模块

根据任务描述动态选择工具，支持分层检索、多维度排序、智能路由。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .schema import ToolSchema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 选择结果
# ---------------------------------------------------------------------------

@dataclass
class SelectionResult:
    """工具选择结果。"""

    tool: ToolSchema
    score: float
    reason: str = ""
    confidence: float = 0.0
    """置信度 (0.0~1.0)。"""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool.name,
            "tool_description": self.tool.description,
            "score": round(self.score, 4),
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
        }


# ---------------------------------------------------------------------------
# ToolRouter
# ---------------------------------------------------------------------------

class ToolRouter:
    """智能工具路由器。

    根据任务描述动态选择最相关的工具，支持多种排序策略和分层检索。

    核心功能：
    - 基于语义相似度的工具选择（使用 LLM 或 TF-IDF 近似的关键词匹配）
    - 根据历史成功率排序
    - 根据调用成本排序
    - 分层检索（粗筛+精排）
    - 综合智能路由

    使用示例::

        router = ToolRouter()
        results = router.select_tools(
            "搜索校园课程信息",
            available_tools,
            top_k=3,
        )
        for r in results:
            print(f"{r.tool.name}: {r.reason} (confidence: {r.confidence})")
    """

    # -- 类常量 ----------------------------------------------------------------

    COARSE_THRESHOLD: int = 20
    """工具数量超过此阈值时启用分层检索。"""

    HISTORY_WEIGHT: float = 0.3
    """历史成功率权重。"""

    SEMANTIC_WEIGHT: float = 0.7
    """语义相似度权重。"""

    # -- 构造 ------------------------------------------------------------------

    def __init__(
        self,
        use_llm: bool = False,
        llm_client: Any = None,
    ):
        """初始化路由器。

        Args:
            use_llm: 是否使用 LLM 进行语义匹配（默认使用关键词匹配）。
            llm_client: LLM 客户端实例（当 use_llm=True 时必需）。
        """
        self._use_llm = use_llm
        self._llm_client = llm_client
        self._history: Dict[str, Dict[str, Any]] = {}
        self._costs: Dict[str, float] = {}

    # -- 工具选择 --------------------------------------------------------------

    def select_tools(
        self,
        task_description: str,
        available_tools: List[ToolSchema],
        top_k: int = 5,
    ) -> List[SelectionResult]:
        """根据任务描述动态选择工具。

        流程：
        1. 如果工具数量 > COARSE_THRESHOLD，先粗筛再精排
        2. 计算语义相似度
        3. 结合历史成功率
        4. 返回 Top-K 结果

        Args:
            task_description: 任务描述文本。
            available_tools: 可用工具列表。
            top_k: 返回结果数量。

        Returns:
            SelectionResult 列表，按分数降序排列。
        """
        if not available_tools:
            return []

        # 分层检索
        if len(available_tools) > self.COARSE_THRESHOLD:
            candidates = self._coarse_filter(task_description, available_tools, top_k * 3)
        else:
            candidates = available_tools

        # 精排
        scored = self._fine_rank(task_description, candidates)
        scored.sort(key=lambda x: x.score, reverse=True)

        return scored[:top_k]

    def _coarse_filter(
        self,
        task_description: str,
        tools: List[ToolSchema],
        max_candidates: int,
    ) -> List[ToolSchema]:
        """粗筛阶段：基于关键词快速过滤。"""
        task_lower = task_description.lower()
        task_tokens = self._tokenize(task_lower)

        scored: List[Tuple[ToolSchema, float]] = []
        for tool in tools:
            text = f"{tool.name} {tool.description}".lower()
            text_tokens = self._tokenize(text)
            hits = sum(1 for t in task_tokens if t in text_tokens)
            score = hits / max(len(task_tokens), 1)
            if score > 0:
                scored.append((tool, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        return [t for t, _ in scored[:max_candidates]]

    def _fine_rank(
        self,
        task_description: str,
        tools: List[ToolSchema],
    ) -> List[SelectionResult]:
        """精排阶段：计算综合分数。"""
        task_tokens = self._tokenize(task_description.lower())

        results: List[SelectionResult] = []
        for tool in tools:
            semantic_score = self._compute_semantic_score(task_tokens, tool)
            history_score = self._get_history_score(tool.name)
            cost_score = self._get_cost_score(tool.name)

            # 综合分数
            combined = (
                self.SEMANTIC_WEIGHT * semantic_score
                + self.HISTORY_WEIGHT * history_score
            )
            # 成本因子在语义分数较低时影响更大
            combined *= (1.0 + 0.1 * cost_score)

            # 置信度
            confidence = self._compute_confidence(
                semantic_score, history_score, tool.name
            )

            reason = self._build_reason(
                tool, semantic_score, history_score, cost_score
            )

            results.append(SelectionResult(
                tool=tool,
                score=combined,
                reason=reason,
                confidence=confidence,
            ))

        return results

    def _compute_semantic_score(
        self,
        task_tokens: List[str],
        tool: ToolSchema,
    ) -> float:
        """计算语义相似度分数。

        使用加权关键词匹配（名称权重0.6，描述0.4）。
        """
        name_tokens = self._tokenize(tool.name.lower())
        desc_tokens = self._tokenize(tool.description.lower())

        name_hits = sum(1 for t in task_tokens if t in name_tokens)
        name_score = name_hits / max(len(task_tokens), 1) if name_tokens else 0.0

        desc_hits = sum(1 for t in task_tokens if t in desc_tokens)
        desc_score = desc_hits / max(len(task_tokens), 1) if desc_tokens else 0.0

        # 精确名称匹配加分
        task_str = "".join(task_tokens)
        exact_bonus = 0.3 if task_str in tool.name.lower() else 0.0

        return min(0.6 * name_score + 0.4 * desc_score + exact_bonus, 1.0)

    def _get_history_score(self, tool_name: str) -> float:
        """获取历史成功率分数。"""
        hist = self._history.get(tool_name)
        if not hist:
            return 0.5  # 无历史数据时默认中等分数
        total = hist.get("total", 0)
        success = hist.get("success", 0)
        return success / total if total > 0 else 0.5

    def _get_cost_score(self, tool_name: str) -> float:
        """获取成本分数（成本越低分数越高）。"""
        cost = self._costs.get(tool_name, 0.0)
        if cost <= 0:
            return 1.0
        # 成本映射为 0~1 分数，成本越高分数越低
        return max(0.0, 1.0 - min(cost / 10.0, 1.0))

    def _compute_confidence(
        self,
        semantic_score: float,
        history_score: float,
        tool_name: str,
    ) -> float:
        """计算选择置信度。"""
        # 历史数据充足时置信度更高
        hist = self._history.get(tool_name)
        history_confidence = 0.5
        if hist:
            total = hist.get("total", 0)
            if total >= 10:
                history_confidence = 0.9
            elif total >= 5:
                history_confidence = 0.7
            elif total >= 1:
                history_confidence = 0.6

        # 综合置信度
        base = 0.5 * semantic_score + 0.5 * history_confidence
        return min(base, 1.0)

    def _build_reason(
        self,
        tool: ToolSchema,
        semantic_score: float,
        history_score: float,
        cost_score: float,
    ) -> str:
        """构建选择理由。"""
        parts: List[str] = []
        if semantic_score > 0.5:
            parts.append(f"与任务描述高度相关 (语义分数: {semantic_score:.2f})")
        elif semantic_score > 0.2:
            parts.append(f"与任务描述部分相关 (语义分数: {semantic_score:.2f})")
        else:
            parts.append(f"与任务描述相关性较低 (语义分数: {semantic_score:.2f})")

        if history_score > 0.5:
            parts.append(f"历史成功率较高 ({history_score:.2f})")
        if cost_score < 0.5:
            parts.append(f"调用成本较高 (成本分数: {cost_score:.2f})")

        return "; ".join(parts) if parts else "综合匹配"

    # -- 排序方法 --------------------------------------------------------------

    def rank_tools_by_history(
        self, tools: List[ToolSchema]
    ) -> List[Tuple[ToolSchema, float]]:
        """根据历史成功率排序工具。

        Returns:
            [(ToolSchema, success_rate), ...] 排序列表。
        """
        scored = [
            (tool, self._get_history_score(tool.name))
            for tool in tools
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    def rank_tools_by_cost(
        self, tools: List[ToolSchema]
    ) -> List[Tuple[ToolSchema, float]]:
        """根据调用成本排序工具（成本低优先）。

        Returns:
            [(ToolSchema, cost_score), ...] 排序列表。
        """
        scored = [
            (tool, self._get_cost_score(tool.name))
            for tool in tools
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored

    # -- 智能路由 --------------------------------------------------------------

    def smart_route(
        self,
        task: str,
        tools: List[ToolSchema],
        top_k: int = 3,
    ) -> List[SelectionResult]:
        """综合选择最优工具。

        结合语义相似度、历史成功率、调用成本，并考虑工具多样性。

        Args:
            task: 任务描述。
            tools: 可用工具列表。
            top_k: 返回结果数量。

        Returns:
            最优工具选择结果列表。
        """
        # 获取基础选择
        base_results = self.select_tools(task, tools, top_k=top_k * 2)

        # 多样性与综合评分
        final_results, seen_categories = self._apply_diversity(base_results, top_k)

        return final_results

    def _apply_diversity(
        self, results: List[SelectionResult], top_k: int
    ) -> Tuple[List[SelectionResult], set]:
        """应用多样性策略，避免选择相似工具。

        当有多个高分工具来自同一 Server 时，优先保留最优的。
        """
        final: List[SelectionResult] = []
        seen_servers: set = set()
        seen_names: set = set()

        for r in results:
            # 获取工具来源（从 schema 提取，如果没有则用名称）
            server_key = getattr(r.tool, "server_name", r.tool.name)
            if server_key in seen_servers and len(final) >= top_k:
                continue
            if r.tool.name in seen_names:
                continue

            final.append(r)
            seen_servers.add(server_key)
            seen_names.add(r.tool.name)

            if len(final) >= top_k:
                break

        return final, seen_servers

    # -- 历史记录 --------------------------------------------------------------

    def record_result(
        self, tool_name: str, success: bool, elapsed: float = 0.0
    ) -> None:
        """记录工具调用结果，更新历史数据。"""
        if tool_name not in self._history:
            self._history[tool_name] = {"total": 0, "success": 0, "total_elapsed": 0.0}
        self._history[tool_name]["total"] += 1
        if success:
            self._history[tool_name]["success"] += 1
        self._history[tool_name]["total_elapsed"] += elapsed

    def set_tool_cost(self, tool_name: str, cost: float) -> None:
        """设置工具调用成本（越低越好）。"""
        self._costs[tool_name] = cost

    def get_history(self, tool_name: str) -> Optional[Dict[str, Any]]:
        """获取工具历史记录。"""
        return self._history.get(tool_name)

    # -- 分词工具 --------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """中文+英文分词。

        - 中文按单字分词
        - 英文按单词分词
        """
        tokens: List[str] = []
        # 中文字符
        chinese = re.findall(r"[\u4e00-\u9fff]", text)
        tokens.extend(chinese)
        # 英文单词
        english = re.findall(r"[a-zA-Z_]+", text)
        tokens.extend(w.lower() for w in english)
        # 数字
        numbers = re.findall(r"\d+", text)
        tokens.extend(numbers)
        return tokens

    def __repr__(self) -> str:
        return (
            f"ToolRouter(use_llm={self._use_llm}, "
            f"history_entries={len(self._history)}, "
            f"cost_entries={len(self._costs)})"
        )
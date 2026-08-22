"""
MCP ToolRegistry -- 增强版工具注册表

扩展工具注册功能，支持从 MCP Server 发现工具、搜索工具、
以及工具元数据统计（调用次数、成功率、平均耗时）。
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .schema import ToolSchema
from .server import MCPServer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具元数据
# ---------------------------------------------------------------------------

@dataclass
class ToolMetadata:
    """工具运行时元数据。"""

    call_count: int = 0
    """调用总次数。"""

    success_count: int = 0
    """成功调用次数。"""

    fail_count: int = 0
    """失败调用次数。"""

    total_elapsed: float = 0.0
    """总耗时（秒）。"""

    last_called_at: float = 0.0
    """最后调用时间戳。"""

    @property
    def success_rate(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.success_count / self.call_count

    @property
    def avg_elapsed(self) -> float:
        if self.call_count == 0:
            return 0.0
        return self.total_elapsed / self.call_count

    def record_call(self, success: bool, elapsed: float) -> None:
        """记录一次调用。"""
        self.call_count += 1
        if success:
            self.success_count += 1
        else:
            self.fail_count += 1
        self.total_elapsed += elapsed
        self.last_called_at = time.time()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "call_count": self.call_count,
            "success_count": self.success_count,
            "fail_count": self.fail_count,
            "success_rate": round(self.success_rate, 4),
            "avg_elapsed_seconds": round(self.avg_elapsed, 4),
            "last_called_at": self.last_called_at,
        }


# ---------------------------------------------------------------------------
# 工具条目
# ---------------------------------------------------------------------------

@dataclass
class _ToolEntry:
    """注册表内部工具条目。"""

    schema: ToolSchema
    handler: Optional[Callable[..., Any]] = None
    server_name: str = ""
    metadata: ToolMetadata = field(default_factory=ToolMetadata)


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------

class ToolRegistry:
    """MCP 专用增强版工具注册表。

    管理所有已注册工具，支持从 MCP Server 批量发现工具、
    基于描述搜索工具、以及工具元数据统计。

    使用示例::

        registry = ToolRegistry()
        registry.register_tool(my_schema, my_handler)
        registry.discover_from_server(campus_server)
        results = registry.search_tools("搜索课程", top_k=5)
    """

    def __init__(self):
        self._tools: Dict[str, _ToolEntry] = {}
        self._source_map: Dict[str, str] = {}  # tool_name -> server_name

    # -- 属性 ------------------------------------------------------------------

    @property
    def tool_count(self) -> int:
        return len(self._tools)

    @property
    def tool_names(self) -> List[str]:
        return list(self._tools.keys())

    # -- 工具注册与注销 --------------------------------------------------------

    def register_tool(
        self,
        schema: ToolSchema,
        handler: Optional[Callable[..., Any]] = None,
        server_name: str = "",
    ) -> None:
        """注册一个工具。

        Args:
            schema: 工具 Schema。
            handler: 工具处理函数（可选，如果从 Server 调用则不需要）。
            server_name: 来源 Server 名称（可选）。
        """
        name = schema.name
        if name in self._tools:
            logger.warning("Tool '%s' already registered, overwriting.", name)
        self._tools[name] = _ToolEntry(
            schema=schema,
            handler=handler,
            server_name=server_name,
        )
        if server_name:
            self._source_map[name] = server_name
        logger.info("Registered tool '%s' in registry (source: %s)", name, server_name or "direct")

    def unregister(self, name: str) -> bool:
        """注销工具。"""
        if name in self._tools:
            del self._tools[name]
            self._source_map.pop(name, None)
            logger.info("Unregistered tool '%s' from registry", name)
            return True
        return False

    # -- 从 MCP Server 发现工具 -------------------------------------------------

    def discover_from_server(self, server: MCPServer) -> int:
        """从 MCP Server 发现并注册所有工具。

        Args:
            server: MCP Server 实例。

        Returns:
            新发现的工具数量。
        """
        count = 0
        for tool_schema in server.tools:
            if tool_schema.name not in self._tools:
                self.register_tool(
                    schema=tool_schema,
                    server_name=server.name,
                )
                count += 1
        logger.info(
            "Discovered %d new tools from server '%s'", count, server.name
        )
        return count

    # -- 查询 ------------------------------------------------------------------

    def get_tool_schema(self, name: str) -> Optional[ToolSchema]:
        """获取工具 Schema。"""
        entry = self._tools.get(name)
        return entry.schema if entry else None

    def get_tool_handler(self, name: str) -> Optional[Callable[..., Any]]:
        """获取工具处理函数。"""
        entry = self._tools.get(name)
        return entry.handler if entry else None

    def get_tool_metadata(self, name: str) -> Optional[ToolMetadata]:
        """获取工具元数据。"""
        entry = self._tools.get(name)
        return entry.metadata if entry else None

    def get_server_name(self, tool_name: str) -> Optional[str]:
        """获取工具来源 Server 名称。"""
        return self._source_map.get(tool_name)

    # -- 工具搜索 --------------------------------------------------------------

    def search_tools(
        self, query: str, top_k: int = 5
    ) -> List[Tuple[ToolSchema, float]]:
        """基于描述搜索工具。

        使用关键词匹配算法，对工具名称和描述进行打分排序。

        Args:
            query: 搜索查询字符串。
            top_k: 返回结果数量。

        Returns:
            [(ToolSchema, score), ...] 的排序列表，score 在 0.0~1.0 之间。
        """
        query_lower = query.lower()
        query_tokens = self._tokenize(query_lower)

        if not query_tokens:
            return []

        scored: List[Tuple[ToolSchema, float]] = []
        for entry in self._tools.values():
            schema = entry.schema
            score = self._compute_relevance(
                query_tokens,
                schema.name.lower(),
                schema.description.lower(),
            )
            if score > 0:
                scored.append((schema, score))

        # 按分数降序排序
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """中文+英文分词（简单版）。"""
        # 提取中文字符和英文单词
        tokens: List[str] = []
        # 中文按字符分
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        tokens.extend(chinese_chars)
        # 英文按单词分
        english_words = re.findall(r"[a-zA-Z_]+", text)
        tokens.extend(w.lower() for w in english_words)
        return tokens

    @staticmethod
    def _compute_relevance(
        query_tokens: List[str],
        name: str,
        description: str,
    ) -> float:
        """计算工具与查询的相关性分数。

        名称匹配权重更高（0.6），描述匹配权重较低（0.4）。
        """
        name_tokens = ToolRegistry._tokenize(name)
        desc_tokens = ToolRegistry._tokenize(description)

        # 名称匹配
        name_hits = sum(1 for t in query_tokens if t in name_tokens)
        name_score = name_hits / max(len(query_tokens), 1) if name_tokens else 0.0

        # 描述匹配
        desc_hits = sum(1 for t in query_tokens if t in desc_tokens)
        desc_score = desc_hits / max(len(query_tokens), 1) if desc_tokens else 0.0

        # 精确名称匹配加分
        exact_bonus = 0.0
        query_str = "".join(query_tokens)
        if query_str in name:
            exact_bonus = 0.3

        return min(0.6 * name_score + 0.4 * desc_score + exact_bonus, 1.0)

    # -- 元数据记录 -------------------------------------------------------------

    def record_call(
        self, tool_name: str, success: bool, elapsed: float
    ) -> None:
        """记录一次工具调用。"""
        entry = self._tools.get(tool_name)
        if entry:
            entry.metadata.record_call(success, elapsed)

    # -- 统计 ------------------------------------------------------------------

    def get_all_metadata(self) -> Dict[str, Dict[str, Any]]:
        """获取所有工具的元数据统计。"""
        return {
            name: entry.metadata.to_dict()
            for name, entry in self._tools.items()
        }

    def get_top_tools_by_success_rate(self, top_k: int = 10) -> List[Tuple[str, float]]:
        """按成功率排序获取工具。"""
        scored = [
            (name, entry.metadata.success_rate)
            for name, entry in self._tools.items()
            if entry.metadata.call_count > 0
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    def get_top_tools_by_usage(self, top_k: int = 10) -> List[Tuple[str, int]]:
        """按使用次数排序获取工具。"""
        scored = [
            (name, entry.metadata.call_count)
            for name, entry in self._tools.items()
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]

    # -- 列表 ------------------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        """列出所有工具及其元数据。"""
        result = []
        for name, entry in self._tools.items():
            item = entry.schema.to_dict()
            item["server_name"] = entry.server_name
            item["metadata"] = entry.metadata.to_dict()
            result.append(item)
        return result

    def __repr__(self) -> str:
        return f"ToolRegistry(tools={len(self._tools)})"
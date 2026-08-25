"""
Planner 模块 -- 使用 LLM 将复杂任务分解为结构化子任务。

核心能力：
- 基于 LLM 的任务分解，生成 TaskDAG
- 自动识别可并行执行的子任务
- 输出格式验证（ID 唯一性、依赖合法性、无循环）
- 计划版本管理
- 基于历史计划的优化
- 计划预算控制
- 简单任务跳过规划
"""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from .dag import TaskDAG, TaskNode, TaskStatus

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 用于 LLM 规划的系统提示词
PLANNER_SYSTEM_PROMPT = """你是一个专业的任务规划师。你的职责是将用户描述的复杂任务分解为结构化的子任务列表。

## 输出格式要求
你必须返回一个严格的 JSON 对象，格式如下：
```json
{
  "analysis": "对任务的简要分析（1-2句话）",
  "is_simple": false,
  "subtasks": [
    {
      "id": "task_1",
      "description": "详细的子任务描述",
      "expected_output": "该子任务的预期产出",
      "dependencies": [],
      "priority": 0
    }
  ]
}
```

## 分解原则
1. 每个子任务应该是原子性的、可独立执行的
2. 子任务数量控制在 3-20 个之间
3. 明确标注子任务之间的依赖关系（使用 dependencies 数组引用其他子任务的 id）
4. 识别可以并行执行的子任务（即没有依赖关系的子任务）
5. 为每个子任务提供清晰的描述和预期产出
6. 优先级数字越小优先级越高（0 为最高）
7. 如果任务非常简单（只需 1-2 步），设置 is_simple 为 true

## 依赖关系规则
- dependencies 数组中的每个元素必须是其他子任务的 id
- 如果子任务 A 依赖 B，表示 B 必须先于 A 执行
- 无依赖的子任务可以并行执行
- 不能形成循环依赖

## 数据分析专项规则
1. 如果目标列是分类变量（cardinality<20且非数值），使用 model_classify 而非 model_train
2. 如果目标列是数值变量，使用 model_train
3. 如果数据有日期列且目标是预测，在 time_series_feat 后加 time_series_forecast
4. 数据清洗后先执行 data_quality 检查质量
5. 如果缺失率高（>20%），增加 missing_pattern 分析步骤
6. 特征工程后可加 feature_select 做特征筛选
7. 分析流程通常为：data_clean → data_quality → [feature_engineer → feature_select] → 统计分析 → 建模 → report_generate
8. 上下文中的 target_hints 是系统推荐的目标列，优先使用
"""

# 简单任务的关键词模式
SIMPLE_TASK_PATTERNS = [
    r"^(什么是|who is|what is|tell me about)\s",
    r"^(计算|calculate|compute)\s[\d\s\+\-\*\/\(\)]+$",
    r"^(翻译|translate)\s",
    r"^(总结|summarize|摘要)\s",
    r"^(解释|explain)\s.{1,50}$",
]

# 默认最大子任务数
DEFAULT_MAX_SUBTASKS = 20


# ---------------------------------------------------------------------------
# 计划版本
# ---------------------------------------------------------------------------


@dataclass
class PlanVersion:
    """计划版本记录。"""

    version: int
    dag: TaskDAG
    created_at: float = field(default_factory=time.time)
    task_description: str = ""
    context: Optional[Dict[str, Any]] = None
    score: Optional[float] = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------


class Planner:
    """基于 LLM 的任务规划器。

    将复杂任务描述分解为结构化的 TaskDAG，包含子任务定义和依赖关系。

    Attributes:
        llm_client: LLM 客户端，需支持 chat/completion 接口。
        max_subtasks: 最大子任务数，默认 20。
        enable_history: 是否启用历史计划优化。
        enable_versioning: 是否启用版本管理。
        system_prompt: 自定义系统提示词（可选）。
    """

    def __init__(
        self,
        llm_client: Any = None,
        max_subtasks: int = DEFAULT_MAX_SUBTASKS,
        enable_history: bool = True,
        enable_versioning: bool = True,
        system_prompt: Optional[str] = None,
    ) -> None:
        self.llm_client = llm_client
        self.max_subtasks = max_subtasks
        self.enable_history = enable_history
        self.enable_versioning = enable_versioning
        self.system_prompt = system_prompt or PLANNER_SYSTEM_PROMPT

        # 版本管理
        self._versions: Dict[str, List[PlanVersion]] = {}
        self._version_counter: Dict[str, int] = {}

        # 历史计划缓存（用于优化）
        self._history: List[PlanVersion] = []

    # ------------------------------------------------------------------
    # 核心接口
    # ------------------------------------------------------------------

    def plan(
        self,
        task_description: str,
        context: Optional[Dict[str, Any]] = None,
        force_replan: bool = False,
        force_plan: bool = False,
    ) -> TaskDAG:
        """将任务描述分解为 TaskDAG。

        Args:
            task_description: 任务的自然语言描述。
            context: 附加上下文信息（如已有的工具列表、环境变量等）。
            force_replan: 是否强制重新规划（忽略历史缓存）。

        Returns:
            包含子任务和依赖关系的 TaskDAG 对象。
        """
        # 1. 检查是否简单任务（force_plan 时强制走 LLM 规划，不做快捷路径）
        if not force_plan and self._is_simple_task(task_description):
            return self._build_simple_dag(task_description)

        # 2. 检查历史计划（force_plan 时强制生成新计划）
        if not force_plan and not force_replan and self.enable_history:
            cached = self._lookup_history(task_description)
            if cached is not None:
                return cached.clone()

        # 3. 调用 LLM 生成计划
        raw_plan = self._call_llm(task_description, context)

        # 4. 解析 LLM 输出
        dag = self._parse_llm_output(raw_plan, task_description)

        # 5. 验证计划
        self._validate_plan(dag)

        # 6. 版本管理
        if self.enable_versioning:
            self._save_version(task_description, dag, context)

        # 7. 记录历史
        if self.enable_history:
            self._history.append(
                PlanVersion(
                    version=0,
                    dag=dag.clone(),
                    task_description=task_description,
                    context=context,
                )
            )

        return dag

    def replan_partial(
        self,
        original_dag: TaskDAG,
        failed_task_ids: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> TaskDAG:
        """局部重新规划：只修改失败任务及其下游。

        Args:
            original_dag: 原始 DAG。
            failed_task_ids: 失败的任务 ID 列表。
            context: 上下文信息。

        Returns:
            修改后的新 DAG（原始 DAG 不受影响）。
        """
        new_dag = original_dag.clone()

        # 收集所有受影响的任务（失败任务 + 其下游）
        affected_ids: set = set(failed_task_ids)
        for fid in failed_task_ids:
            downstream = original_dag.get_downstream_tasks(fid)
            affected_ids.update(n.task_id for n in downstream)

        # 收集已完成任务的结果作为上下文
        completed_results: Dict[str, Any] = {}
        for node in original_dag.get_all_nodes():
            if node.status == TaskStatus.COMPLETED and node.task_id not in affected_ids:
                completed_results[node.task_id] = {
                    "description": node.description,
                    "result": node.result,
                }

        # 构建重新规划的提示
        replan_context = {
            "failed_tasks": [
                {
                    "task_id": fid,
                    "description": original_dag.get_node(fid).description,
                    "error": str(original_dag.get_node(fid).result or ""),
                }
                for fid in failed_task_ids
            ],
            "completed_results": completed_results,
            "affected_task_ids": list(affected_ids),
            **(context or {}),
        }

        prompt = self._build_replan_prompt(replan_context)
        raw_plan = self._call_llm_raw(prompt)

        # 解析并合并到新 DAG
        partial_dag = self._parse_llm_output(raw_plan, "replan")

        # 移除受影响的任务
        for aid in affected_ids:
            try:
                new_dag.remove_node(aid)
            except ValueError:
                pass

        # 将新规划的任务合并进去
        self._merge_dag(new_dag, partial_dag, completed_results)

        return new_dag

    # ------------------------------------------------------------------
    # 版本管理
    # ------------------------------------------------------------------

    def get_versions(self, task_description: str) -> List[PlanVersion]:
        """获取指定任务的所有计划版本。"""
        key = self._task_key(task_description)
        return self._versions.get(key, [])

    def get_latest_version(self, task_description: str) -> Optional[PlanVersion]:
        """获取最新版本。"""
        versions = self.get_versions(task_description)
        return versions[-1] if versions else None

    def compare_versions(
        self, v1: PlanVersion, v2: PlanVersion
    ) -> Dict[str, Any]:
        """对比两个计划版本。"""
        nodes1 = {n.task_id: n for n in v1.dag.get_all_nodes()}
        nodes2 = {n.task_id: n for n in v2.dag.get_all_nodes()}

        ids1 = set(nodes1.keys())
        ids2 = set(nodes2.keys())

        return {
            "only_in_v1": list(ids1 - ids2),
            "only_in_v2": list(ids2 - ids1),
            "common": list(ids1 & ids2),
            "v1_node_count": len(ids1),
            "v2_node_count": len(ids2),
            "v1_edges": v1.dag.edge_count,
            "v2_edges": v2.dag.edge_count,
            "v1_score": v1.score,
            "v2_score": v2.score,
        }

    def select_best_plan(
        self, task_description: str
    ) -> Optional[PlanVersion]:
        """从历史版本中选择最优计划（按评分排序）。"""
        versions = self.get_versions(task_description)
        if not versions:
            return None
        scored = [v for v in versions if v.score is not None]
        if scored:
            return max(scored, key=lambda v: v.score)  # type: ignore[arg-type, return-value]
        return versions[-1]  # 返回最新版本

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _is_simple_task(self, task_description: str) -> bool:
        """判断任务是否足够简单，可以跳过规划。"""
        import re as _re

        for pattern in SIMPLE_TASK_PATTERNS:
            if _re.search(pattern, task_description, _re.IGNORECASE):
                return True

        # 按长度判断：短任务通常简单
        if len(task_description.strip()) < 30:
            return True

        return False

    def _build_simple_dag(self, task_description: str) -> TaskDAG:
        """为简单任务构建单步 DAG。"""
        dag = TaskDAG(name="simple_task")
        node = TaskNode(
            task_id=uuid.uuid4().hex,
            description=task_description,
            expected_output=f"完成: {task_description}",
            priority=0,
        )
        dag.add_node(node)
        return dag

    def _lookup_history(self, task_description: str) -> Optional[TaskDAG]:
        """在历史记录中查找匹配的计划。"""
        # 简单相似度匹配
        from difflib import SequenceMatcher

        best_ratio = 0.0
        best_dag: Optional[TaskDAG] = None

        for pv in self._history:
            ratio = SequenceMatcher(
                None, pv.task_description, task_description
            ).ratio()
            if ratio > 0.85 and ratio > best_ratio:
                best_ratio = ratio
                best_dag = pv.dag

        return best_dag.clone() if best_dag else None

    def _call_llm(
        self, task_description: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        """调用 LLM 生成计划。"""
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self._build_user_prompt(task_description, context)},
        ]
        return self._call_llm_raw(messages, task=task_description)

    def _call_llm_raw(self, messages: Any, task: str = "") -> str:
        """底层 LLM 调用。

        支持多种 LLM 客户端接口：
        - OpenAI 风格: client.chat.completions.create()
        - Anthropic 风格: client.messages.create()
        - 简单 callable: llm_client(prompt) -> str

        Args:
            messages: 消息列表或纯文本提示。
            task: 原始任务描述，LLM 不可用时用于回退计划（避免把整段
                规划提示词当作子任务描述传给执行器）。
        """
        if self.llm_client is None:
            return self._fallback_plan(messages, error="", task=task)

        try:
            # 本项目 LLMClient：提供 chat_completion 高层方法，使用其配置的模型/base_url
            if hasattr(self.llm_client, "chat_completion"):
                message = self.llm_client.chat_completion(
                    messages, temperature=0.3
                )
                return message.content or ""

            # OpenAI 风格
            if hasattr(self.llm_client, "chat") and hasattr(
                self.llm_client.chat, "completions"
            ):
                kwargs: Dict[str, Any] = {
                    "messages": messages,
                    "temperature": 0.3,
                }
                # 模型名从客户端自身配置读取（不写死），未配置则由客户端默认决定
                client_model = getattr(self.llm_client, "model", None)
                if client_model:
                    kwargs["model"] = client_model
                response = self.llm_client.chat.completions.create(**kwargs)
                return response.choices[0].message.content

            # Anthropic 风格
            if hasattr(self.llm_client, "messages") and hasattr(
                self.llm_client.messages, "create"
            ):
                system_prompt = messages[0]["content"] if messages[0]["role"] == "system" else ""
                user_prompt = messages[-1]["content"]
                client_model = getattr(self.llm_client, "model", None)
                if not client_model:
                    raise ValueError("Anthropic client has no model configured")
                response = self.llm_client.messages.create(
                    model=client_model,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                    max_tokens=4096,
                )
                return response.content[0].text

            # 简单 callable
            if callable(self.llm_client):
                prompt = json.dumps(messages, ensure_ascii=False)
                return self.llm_client(prompt)

        except Exception as e:
            # LLM 调用失败时使用回退策略
            return self._fallback_plan(messages, error=str(e), task=task)

        return self._fallback_plan(messages, task=task)

    def _fallback_plan(
        self,
        messages: Any,
        error: str = "",
        task: str = "",
    ) -> str:
        """当 LLM 不可用时的回退规划策略。

        基于规则生成计划：简单任务（单步可答）退化为单任务 DAG；
        其余任务按标准分析流水线（加载→清洗→特征/可视化→建模→报告）
        生成链式 DAG，避免单任务选错起点工具导致整个 DAG 卡死。
        """
        # 优先使用调用方传入的原始任务描述；缺失时从消息中提取用户内容
        user_msg = task
        if not user_msg:
            if isinstance(messages, list):
                user_msg = next(
                    (m["content"] for m in reversed(messages) if m.get("role") == "user"),
                    "",
                )
            else:
                user_msg = str(messages)

        # 单任务只保留给「一句短查询」（行数/样例等）；中长任务即使
        # 表面简单也可能依赖清洗等前置产物，统一走流水线更可靠
        if len(user_msg.strip()) < 15:
            fallback = {
                "analysis": f"回退规划（LLM 不可用: {error}）" if error else "回退规划",
                "is_simple": False,
                "subtasks": [
                    {
                        "id": "task_1",
                        "description": user_msg,
                        "expected_output": f"完成: {user_msg}",
                        "dependencies": [],
                        "priority": 0,
                    }
                ],
            }
            return json.dumps(fallback, ensure_ascii=False)

        # 标准分析流水线：描述内嵌工具名（名称匹配权重最高，确保本地
        # 模式下可靠路由），其余文字用于向 LLM/验证器解释步骤意图
        pipeline = [
            ("task_1", "csv_load：加载 CSV 数据概览与样例"),
            ("task_2", "data_clean：检测并处理缺失值，清洗数据"),
            ("task_3", "feature_engineer：特征工程，对分类列做编码"),
            ("task_4", "eda_plot：可视化，绘制数值列分布与相关性热力图"),
            ("task_5", "model_train：训练回归模型并评估销售影响因素"),
            ("task_6", "report_generate：生成 Markdown 分析报告"),
        ]
        fallback = {
            "analysis": f"回退规划·标准流水线（LLM 不可用: {error}）" if error
            else "回退规划·标准流水线",
            "is_simple": False,
            "subtasks": [
                {
                    "id": tid,
                    "description": desc,
                    "expected_output": f"完成: {desc}",
                    "dependencies": [prev] if prev else [],
                    "priority": i,
                }
                for i, (prev, (tid, desc)) in enumerate(
                    zip([None] + [p[0] for p in pipeline[:-1]], pipeline)
                )
            ],
        }
        return json.dumps(fallback, ensure_ascii=False)

    def _build_user_prompt(
        self, task_description: str, context: Optional[Dict[str, Any]] = None
    ) -> str:
        """构建用户提示词。"""
        parts = [f"请将以下任务分解为子任务：\n\n{task_description}"]

        if context:
            parts.append(f"\n\n上下文信息：\n{json.dumps(context, ensure_ascii=False, indent=2)}")

        parts.append(f"\n\n要求：子任务数量不超过 {self.max_subtasks} 个。")
        parts.append("请严格按照 JSON 格式输出。")

        return "\n".join(parts)

    def _build_replan_prompt(self, context: Dict[str, Any]) -> str:
        """构建重新规划的提示词。"""
        return (
            f"以下任务的部分子任务执行失败，需要重新规划受影响的部分。\n\n"
            f"上下文：\n{json.dumps(context, ensure_ascii=False, indent=2)}\n\n"
            "请为失败任务及其下游任务重新生成子任务计划，保持 JSON 格式。"
        )

    def _parse_llm_output(self, raw_output: str, task_name: str = "") -> TaskDAG:
        """解析 LLM 输出的 JSON 并构建 TaskDAG。"""
        # 尝试从输出中提取 JSON 块
        json_str = self._extract_json(raw_output)

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError:
            # 解析失败，返回单步计划
            dag = TaskDAG(name=task_name or "parsed_task")
            node = TaskNode(
                task_id=uuid.uuid4().hex,
                description=task_name or "执行任务",
                expected_output="任务完成",
            )
            dag.add_node(node)
            return dag

        # 如果是简单任务，构建单步 DAG
        if data.get("is_simple", False):
            dag = TaskDAG(name=task_name or "simple_task")
            node = TaskNode(
                task_id=uuid.uuid4().hex,
                description=data.get("analysis", task_name),
                expected_output="任务完成",
            )
            dag.add_node(node)
            return dag

        # 构建 DAG
        dag = TaskDAG(name=task_name or "planned_task")
        dag.metadata["analysis"] = data.get("analysis", "")
        dag.metadata["is_simple"] = data.get("is_simple", False)
        subtasks = data.get("subtasks", [])

        if not subtasks:
            node = TaskNode(
                task_id=uuid.uuid4().hex,
                description=task_name or "执行任务",
                expected_output="任务完成",
            )
            dag.add_node(node)
            return dag

        # 限制子任务数量
        if len(subtasks) > self.max_subtasks:
            subtasks = subtasks[: self.max_subtasks]

        # 先添加所有节点
        for st in subtasks:
            node = TaskNode(
                task_id=st.get("id", uuid.uuid4().hex),
                description=st.get("description", ""),
                expected_output=st.get("expected_output", ""),
                dependencies=st.get("dependencies", []),
                priority=st.get("priority", 0),
            )
            dag.add_node(node)

        # 再添加边
        for st in subtasks:
            task_id = st.get("id", "")
            for dep_id in st.get("dependencies", []):
                try:
                    dag.add_edge(dep_id, task_id)
                except ValueError:
                    # 如果边已存在或产生循环，跳过
                    pass

        return dag

    def _extract_json(self, text: str) -> str:
        """从文本中提取 JSON 内容。"""
        # 尝试匹配 ```json ... ``` 代码块
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            return match.group(1)

        # 尝试匹配 { ... } 对象
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            return match.group(0)

        return text

    def _validate_plan(self, dag: TaskDAG) -> None:
        """验证计划的合法性。

        Raises:
            ValueError: 如果验证不通过。
        """
        errors: List[str] = []

        # 1. 检查子任务 ID 唯一性（已在 DAG 中保证）

        # 2. 检查依赖关系合法性
        for node in dag.get_all_nodes():
            for dep_id in node.dependencies:
                if dep_id not in dag.get_all_ids():
                    errors.append(
                        f"任务 '{node.task_id}' 依赖了不存在的任务 '{dep_id}'"
                    )

        # 3. 检查循环依赖
        if dag.detect_cycles():
            cycles = dag.find_cycles()
            errors.append(f"存在循环依赖: {cycles}")

        # 4. 检查子任务数量
        if dag.node_count > self.max_subtasks:
            errors.append(
                f"子任务数量 {dag.node_count} 超过最大限制 {self.max_subtasks}"
            )

        if errors:
            raise ValueError("计划验证失败:\n" + "\n".join(f"  - {e}" for e in errors))

    def _merge_dag(
        self,
        target: TaskDAG,
        source: TaskDAG,
        completed_results: Dict[str, Any],
    ) -> None:
        """将源 DAG 合并到目标 DAG 中。"""
        # 建立 ID 映射（源 DAG 的 ID 可能在目标 DAG 中冲突）
        id_map: Dict[str, str] = {}
        for node in source.get_all_nodes():
            new_id = uuid.uuid4().hex
            id_map[node.task_id] = new_id

        # 添加节点
        for node in source.get_all_nodes():
            new_node = TaskNode(
                task_id=id_map[node.task_id],
                description=node.description,
                expected_output=node.expected_output,
                dependencies=[id_map.get(d, d) for d in node.dependencies],
                priority=node.priority,
                max_retries=node.max_retries,
            )
            target.add_node(new_node)

        # 添加边
        for node in source.get_all_nodes():
            new_id = id_map[node.task_id]
            for dep_id in node.dependencies:
                mapped_dep = id_map.get(dep_id, dep_id)
                try:
                    target.add_edge(mapped_dep, new_id)
                except ValueError:
                    pass

        # 将已完成任务的结果连接到新任务
        for completed_id, result_data in completed_results.items():
            if completed_id in target.get_all_ids():
                for node in source.get_all_nodes():
                    new_id = id_map[node.task_id]
                    # 新任务的依赖如果已完成，则不需要等待
                    pass

    def _save_version(
        self,
        task_description: str,
        dag: TaskDAG,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """保存计划版本。"""
        key = self._task_key(task_description)
        if key not in self._version_counter:
            self._version_counter[key] = 0
        self._version_counter[key] += 1

        version = PlanVersion(
            version=self._version_counter[key],
            dag=dag.clone(),
            task_description=task_description,
            context=context,
        )

        if key not in self._versions:
            self._versions[key] = []
        self._versions[key].append(version)

    @staticmethod
    def _task_key(task_description: str) -> str:
        """生成任务描述的唯一键（用于版本管理）。"""
        # 简单哈希，取前 32 字符
        import hashlib

        return hashlib.md5(task_description.encode()).hexdigest()[:16]

    def __repr__(self) -> str:
        return (
            f"Planner(max_subtasks={self.max_subtasks}, "
            f"history={len(self._history)}, "
            f"versions={sum(len(v) for v in self._versions.values())})"
        )
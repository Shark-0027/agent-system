"""
Executor 模块 -- 任务执行器与顶层调度代理。

包含：
- Executor: 负责执行单个子任务，处理失败与重试，验证结果。
- PlannerExecutorAgent: 顶层调度器，协调 Planner / Verifier / Scheduler / Executor。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .dag import TaskDAG, TaskNode, TaskStatus, FailureStrategy
from .planner import Planner, PlanVersion
from .scheduler import ExecutionResult, ParallelScheduler, ScheduleResult
from .verifier import PlanVerifier, VerificationResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 工具注册表接口
# ---------------------------------------------------------------------------


class ToolRegistry:
    """工具注册表，管理可用的执行工具。

    Executor 通过工具注册表查找合适的工具来执行子任务。
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Any] = {}

    def register(self, name: str, tool: Any, description: str = "") -> None:
        """注册一个工具。"""
        self._tools[name] = {
            "tool": tool,
            "description": description,
        }

    def unregister(self, name: str) -> None:
        """注销一个工具。"""
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[Any]:
        """获取工具。"""
        entry = self._tools.get(name)
        return entry["tool"] if entry else None

    def list_tools(self) -> List[Dict[str, str]]:
        """列出所有工具及其描述。"""
        return [
            {"name": name, "description": entry["description"]}
            for name, entry in self._tools.items()
        ]

    def find_tool(self, task_description: str) -> Optional[str]:
        """根据任务描述查找匹配的工具。

        使用简单的关键词匹配。

        Args:
            task_description: 任务描述。

        Returns:
            匹配的工具名称，找不到则返回 None。
        """
        desc_lower = task_description.lower()
        best_match: Optional[str] = None
        best_score = 0

        for name, entry in self._tools.items():
            name_lower = name.lower()
            desc_lower_entry = entry["description"].lower()

            score = 0
            # 名称匹配
            if name_lower in desc_lower:
                score += 3
            # 关键词匹配
            keywords = set(name_lower.split()) | set(desc_lower_entry.split())
            for kw in keywords:
                if kw in desc_lower:
                    score += 1

            if score > best_score:
                best_score = score
                best_match = name

        return best_match

    def __len__(self) -> int:
        return len(self._tools)

    def __repr__(self) -> str:
        return f"ToolRegistry(tools={list(self._tools.keys())})"


# ---------------------------------------------------------------------------
# SessionManager 接口
# ---------------------------------------------------------------------------


class SessionManager:
    """会话管理器，跟踪执行上下文和状态。

    在 PlannerExecutorAgent 中用于维护跨任务的会话状态。
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._current_session_id: Optional[str] = None

    def create_session(self, task_description: str) -> str:
        """创建新会话。"""
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = {
            "task_description": task_description,
            "created_at": time.time(),
            "state": {},
            "history": [],
        }
        self._current_session_id = session_id
        return session_id

    def get_state(self, session_id: Optional[str] = None) -> Dict[str, Any]:
        """获取会话状态。"""
        sid = session_id or self._current_session_id
        if sid and sid in self._sessions:
            return self._sessions[sid]["state"]
        return {}

    def set_state(self, key: str, value: Any, session_id: Optional[str] = None) -> None:
        """设置会话状态。"""
        sid = session_id or self._current_session_id
        if sid and sid in self._sessions:
            self._sessions[sid]["state"][key] = value

    def add_history(self, entry: Dict[str, Any], session_id: Optional[str] = None) -> None:
        """添加历史记录。"""
        sid = session_id or self._current_session_id
        if sid and sid in self._sessions:
            entry["timestamp"] = time.time()
            self._sessions[sid]["history"].append(entry)

    def close_session(self, session_id: Optional[str] = None) -> None:
        """关闭会话。"""
        sid = session_id or self._current_session_id
        if sid:
            self._sessions.pop(sid, None)
            if self._current_session_id == sid:
                self._current_session_id = None


# ---------------------------------------------------------------------------
# TraceLogger
# ---------------------------------------------------------------------------


class TraceLogger:
    """执行追踪日志，记录整个执行流程的详细信息。

    用于调试、审计和性能分析。
    """

    def __init__(self) -> None:
        self._traces: List[Dict[str, Any]] = []
        self._start_time: Optional[float] = None

    def start(self) -> None:
        """开始追踪。"""
        self._start_time = time.time()
        self._traces = []

    def log(
        self,
        event: str,
        data: Optional[Dict[str, Any]] = None,
        level: str = "info",
    ) -> None:
        """记录一条追踪事件。"""
        self._traces.append({
            "timestamp": time.time(),
            "elapsed": time.time() - (self._start_time or time.time()),
            "event": event,
            "data": data or {},
            "level": level,
        })

    def get_traces(self) -> List[Dict[str, Any]]:
        """获取所有追踪记录。"""
        return list(self._traces)

    def to_json(self, indent: int = 2) -> str:
        """序列化为 JSON。"""
        return json.dumps(self._traces, ensure_ascii=False, indent=indent)

    def summary(self) -> Dict[str, Any]:
        """生成追踪摘要。"""
        if not self._traces:
            return {}

        events = [t["event"] for t in self._traces]
        errors = [t for t in self._traces if t["level"] == "error"]
        total_duration = self._traces[-1]["elapsed"] if self._traces else 0

        return {
            "total_events": len(self._traces),
            "total_duration": total_duration,
            "error_count": len(errors),
            "event_types": list(set(events)),
        }


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class Executor:
    """任务执行器，负责执行单个子任务。

    核心能力：
    - 使用 Agent Runtime 或工具执行子任务
    - 根据子任务描述选择合适的工具
    - 失败重试与异常处理
    - 自动验证执行结果

    Attributes:
        tool_registry: 工具注册表。
        llm_client: LLM 客户端（可选，用于智能工具选择）。
        max_retries: 默认最大重试次数。
        default_timeout: 默认超时时间（秒）。
    """

    def __init__(
        self,
        tool_registry: ToolRegistry,
        llm_client: Any = None,
        max_retries: int = 3,
        default_timeout: float = 300.0,
    ) -> None:
        self.tool_registry = tool_registry
        self.llm_client = llm_client
        self.max_retries = max_retries
        self.default_timeout = default_timeout

    # ------------------------------------------------------------------
    # 核心接口
    # ------------------------------------------------------------------

    def execute(
        self,
        task_node: TaskNode,
        tool_registry: Optional[ToolRegistry] = None,
        llm_client: Any = None,
    ) -> ExecutionResult:
        """执行单个子任务。

        Args:
            task_node: 待执行的任务节点。
            tool_registry: 工具注册表（覆盖默认）。
            llm_client: LLM 客户端（覆盖默认）。

        Returns:
            ExecutionResult 包含执行状态和结果。
        """
        registry = tool_registry or self.tool_registry
        client = llm_client or self.llm_client

        start_time = time.time()

        try:
            # 1. 选择合适的工具
            tool_name = self._select_tool(task_node, registry)

            # 2. 执行任务
            if tool_name:
                tool = registry.get(tool_name)
                if tool is None:
                    raise ValueError(f"Tool '{tool_name}' not found in registry")
                result = self._execute_with_tool(task_node, tool)
            elif client is not None:
                result = self._execute_with_llm(task_node, client)
            else:
                # 无匹配工具且无 LLM：不应静默标记为完成，否则"假成功"污染
                # 成功率和最终报告。改为返回带错误标记的结果，交由 verify_result 判别。
                raise ValueError(
                    f"No tool matched for task '{task_node.description}' and no LLM "
                    "fallback available."
                )

            # 3. 验证结果
            verified = self.verify_result(task_node, result)

            if verified:
                return ExecutionResult(
                    task_id=task_node.task_id,
                    status=TaskStatus.COMPLETED,
                    result=result,
                    duration=time.time() - start_time,
                )
            else:
                return ExecutionResult(
                    task_id=task_node.task_id,
                    status=TaskStatus.FAILED,
                    result=result,
                    error="Result verification failed",
                    duration=time.time() - start_time,
                )

        except Exception as e:
            logger.error(
                "Task %s execution failed: %s",
                task_node.task_id[:8],
                str(e),
            )
            return self.handle_failure(task_node, e)

    def handle_failure(
        self, task_node: TaskNode, error: Exception
    ) -> ExecutionResult:
        """处理任务执行失败。

        判断是否可重试，进行重试或标记为失败。

        Args:
            task_node: 失败的任务节点。
            error: 异常信息。

        Returns:
            ExecutionResult。
        """
        # 判断是否可重试
        retryable = self._is_retryable(error)

        if retryable and task_node.retry_count < task_node.max_retries:
            task_node.retry_count += 1
            logger.warning(
                "Task %s failed, retrying (%d/%d): %s",
                task_node.task_id[:8],
                task_node.retry_count,
                task_node.max_retries,
                str(error),
            )
            return ExecutionResult(
                task_id=task_node.task_id,
                status=TaskStatus.FAILED,
                error=str(error),
                retry_count=task_node.retry_count,
            )
        else:
            logger.error(
                "Task %s permanently failed after %d retries: %s",
                task_node.task_id[:8],
                task_node.retry_count,
                str(error),
            )
            return ExecutionResult(
                task_id=task_node.task_id,
                status=TaskStatus.FAILED,
                error=str(error),
                retry_count=task_node.retry_count,
            )

    def verify_result(
        self, task_node: TaskNode, result: Any
    ) -> bool:
        """自动验证执行结果。

        检查结果是否满足预期输出的基本要求。

        Args:
            task_node: 任务节点。
            result: 执行结果。

        Returns:
            True 如果结果通过验证。
        """
        if result is None:
            logger.warning("Task %s returned None result", task_node.task_id[:8])
            return False

        # 如果结果是字典，检查是否有错误标记
        if isinstance(result, dict):
            if result.get("error"):
                logger.warning(
                    "Task %s result contains error: %s",
                    task_node.task_id[:8],
                    result["error"],
                )
                return False
            if result.get("status") == "failed":
                return False

        # 如果结果是字符串，检查是否为空
        if isinstance(result, str) and not result.strip():
            logger.warning("Task %s returned empty string", task_node.task_id[:8])
            return False

        # 检查预期输出关键词匹配（简单启发式）
        if task_node.expected_output:
            expected_lower = task_node.expected_output.lower()
            result_str = str(result).lower()
            # 预期输出中的关键词至少有 30% 出现在结果中
            keywords = [
                w for w in expected_lower.split()
                if len(w) > 2 and w not in ("the", "for", "and", "一个", "完成", "的")
            ]
            if keywords:
                matched = sum(1 for kw in keywords if kw in result_str)
                match_ratio = matched / len(keywords)
                if match_ratio < 0.3:
                    logger.warning(
                        "Task %s result matches only %.0f%% of expected keywords",
                        task_node.task_id[:8],
                        match_ratio * 100,
                    )
                    # 不直接判定失败，仅警告

        return True

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _select_tool(
        self, task_node: TaskNode, registry: ToolRegistry
    ) -> Optional[str]:
        """根据任务描述选择合适的工具。

        优先使用 LLM 进行智能选择，回退到关键词匹配。

        Args:
            task_node: 任务节点。
            registry: 工具注册表。

        Returns:
            工具名称，没有合适工具则返回 None。
        """
        # 如果有 LLM，尝试智能选择
        if self.llm_client is not None:
            tool_name = self._llm_select_tool(task_node, registry)
            if tool_name:
                return tool_name

        # 回退到关键词匹配
        return registry.find_tool(task_node.description)

    def _llm_select_tool(
        self, task_node: TaskNode, registry: ToolRegistry
    ) -> Optional[str]:
        """使用 LLM 智能选择工具。"""
        tools_list = registry.list_tools()
        if not tools_list:
            return None

        prompt = (
            f"任务描述: {task_node.description}\n\n"
            f"可用工具列表:\n"
            + "\n".join(
                f"- {t['name']}: {t['description']}" for t in tools_list
            )
            + "\n\n请选择最适合的工具名称，只返回工具名称，不要其他内容。"
        )

        try:
            if hasattr(self.llm_client, "chat") and hasattr(
                self.llm_client.chat, "completions"
            ):
                response = self.llm_client.chat.completions.create(
                    model="gpt-4",
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.0,
                    max_tokens=50,
                )
                tool_name = response.choices[0].message.content.strip()
                if tool_name in {t["name"] for t in tools_list}:
                    return tool_name
        except Exception:
            pass

        return None

    def _execute_with_tool(self, task_node: TaskNode, tool: Any) -> Any:
        """使用工具执行任务。"""
        if callable(tool):
            import inspect
            try:
                sig = inspect.signature(tool)
                params = list(sig.parameters.keys())
                if len(params) >= 2:
                    return tool(task_node.description, task_node.metadata)
                elif len(params) == 1:
                    return tool(task_node.description)
                else:
                    return tool()
            except (ValueError, TypeError):
                # 无法检查签名时尝试两参数调用
                try:
                    return tool(task_node.description, task_node.metadata)
                except TypeError:
                    return tool(task_node.description)
        elif hasattr(tool, "execute"):
            return tool.execute(task_node.description, **task_node.metadata)
        elif hasattr(tool, "run"):
            return tool.run(task_node.description)
        else:
            raise ValueError(f"Tool type not supported: {type(tool)}")

    def _execute_with_llm(self, task_node: TaskNode, llm_client: Any) -> Any:
        """使用 LLM 直接执行任务。"""
        prompt = (
            f"请执行以下任务并返回结果：\n\n"
            f"任务: {task_node.description}\n"
            f"预期输出: {task_node.expected_output}\n\n"
            f"请直接返回执行结果。"
        )

        if hasattr(llm_client, "chat") and hasattr(llm_client.chat, "completions"):
            response = llm_client.chat.completions.create(
                model="gpt-4",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
            )
            return {"output": response.choices[0].message.content}
        elif callable(llm_client):
            return {"output": llm_client(prompt)}
        else:
            return {"output": f"LLM execution not available for: {task_node.description}"}

    @staticmethod
    def _is_retryable(error: Exception) -> bool:
        """判断异常是否可重试。"""
        retryable_types = (
            TimeoutError,
            ConnectionError,
            OSError,
        )
        if isinstance(error, retryable_types):
            return True

        # 检查错误消息中的关键词
        error_msg = str(error).lower()
        retryable_keywords = [
            "timeout",
            "connection",
            "temporary",
            "unavailable",
            "rate limit",
            "too many requests",
            "server error",
            "503",
            "502",
            "429",
        ]
        return any(kw in error_msg for kw in retryable_keywords)

    def __repr__(self) -> str:
        return (
            f"Executor(tools={len(self.tool_registry)}, "
            f"max_retries={self.max_retries})"
        )


# ---------------------------------------------------------------------------
# PlannerExecutorAgent
# ---------------------------------------------------------------------------


@dataclass
class ExecutionTrace:
    """单次执行追踪记录。"""

    plan_version: int
    dag: TaskDAG
    verification: Optional[VerificationResult] = None
    schedule_result: Optional[ScheduleResult] = None
    replan_triggered: bool = False
    replan_reason: str = ""
    final_output: Optional[Any] = None
    duration: float = 0.0


class PlannerExecutorAgent:
    """顶层调度代理 -- Planner-Executor 系统的总控。

    协调 Planner、PlanVerifier、ParallelScheduler、Executor 完成：
    1. 任务分解（Planner）
    2. 计划验证（PlanVerifier）
    3. 循环执行（Scheduler + Executor）
    4. 失败处理与局部重新规划
    5. 结果汇总

    Attributes:
        llm_client: LLM 客户端。
        tool_registry: 工具注册表。
        session_manager: 会话管理器。
        trace_logger: 追踪日志。
        planner: Planner 实例。
        verifier: PlanVerifier 实例。
        scheduler: ParallelScheduler 实例。
        executor: Executor 实例。
        max_replan_attempts: 最大重新规划次数。
        complexity_threshold: 复杂度阈值（超过此值启用规划）。
        auto_planning: 是否自动根据复杂度决定是否启用规划。
    """

    def __init__(
        self,
        llm_client: Any = None,
        tool_registry: Optional[ToolRegistry] = None,
        session_manager: Optional[SessionManager] = None,
        trace_logger: Optional[TraceLogger] = None,
        max_workers: int = 4,
        max_replan_attempts: int = 3,
        complexity_threshold: float = 0.3,
        auto_planning: bool = True,
        failure_strategy: FailureStrategy = FailureStrategy.RETRY,
    ) -> None:
        self.llm_client = llm_client
        self.tool_registry = tool_registry or ToolRegistry()
        self.session_manager = session_manager or SessionManager()
        self.trace_logger = trace_logger or TraceLogger()

        # 子组件
        self.planner = Planner(
            llm_client=llm_client,
            enable_history=True,
            enable_versioning=True,
        )
        self.verifier = PlanVerifier()
        self.scheduler = ParallelScheduler(
            max_workers=max_workers,
            failure_strategy=failure_strategy,
        )
        self.executor = Executor(
            tool_registry=self.tool_registry,
            llm_client=llm_client,
        )

        self.max_replan_attempts = max_replan_attempts
        self.complexity_threshold = complexity_threshold
        self.auto_planning = auto_planning

        # 执行历史
        self._execution_traces: List[ExecutionTrace] = []

    # ------------------------------------------------------------------
    # 核心接口
    # ------------------------------------------------------------------

    def run(self, task_description: str) -> Dict[str, Any]:
        """运行完整的 Planner-Executor 流程。

        1. Planner 分解任务 -> 生成 TaskDAG
        2. PlanVerifier 验证计划 -> 不通过则重新规划
        3. 循环执行：
           a. 获取 ready 任务
           b. ParallelScheduler 并行调度
           c. Executor 执行每个任务
           d. 更新 DAG 状态
           e. 失败时局部重新规划
        4. 汇总结果

        Args:
            task_description: 任务描述。

        Returns:
            包含最终结果的字典。
        """
        start_time = time.time()
        self.trace_logger.start()
        self.trace_logger.log("agent_start", {"task": task_description})

        # 创建会话
        session_id = self.session_manager.create_session(task_description)

        # 1. 判断是否需要规划
        if self.auto_planning and self._task_complexity(task_description) < self.complexity_threshold:
            self.trace_logger.log("planning_skipped", {"reason": "task_too_simple"})
            plan_dag = self._build_simple_plan(task_description)
        else:
            # 2. Planner 分解任务
            self.trace_logger.log("planning_start")
            plan_dag = self._plan_with_verification(task_description)
            self.trace_logger.log("planning_complete", {
                "node_count": plan_dag.node_count,
                "edge_count": plan_dag.edge_count,
            })

        # 3. 执行循环
        trace = ExecutionTrace(
            plan_version=len(self._execution_traces) + 1,
            dag=plan_dag.clone(),
        )

        replan_count = 0
        while not plan_dag.is_complete() and replan_count <= self.max_replan_attempts:
            if plan_dag.is_stuck():
                self.trace_logger.log("dag_stuck", {"replan_count": replan_count})
                if replan_count < self.max_replan_attempts:
                    plan_dag = self._replan_stuck(plan_dag, task_description)
                    replan_count += 1
                    trace.replan_triggered = True
                    trace.replan_reason = "dag_stuck"
                    continue
                else:
                    self.trace_logger.log("max_replan_exceeded", level="error")
                    break

            # 调度执行
            self.trace_logger.log("schedule_cycle_start")
            batch_result = self.scheduler.schedule(
                plan_dag,
                self._create_executor_func(),
            )

            # 检查失败任务
            failed_tasks = plan_dag.get_failed_tasks()
            if failed_tasks:
                self.trace_logger.log("tasks_failed", {
                    "failed_count": len(failed_tasks),
                    "failed_ids": [t.task_id[:8] for t in failed_tasks],
                })

                if replan_count < self.max_replan_attempts:
                    # 局部重新规划
                    self.trace_logger.log("replan_partial_start")
                    plan_dag = self.planner.replan_partial(
                        plan_dag,
                        [t.task_id for t in failed_tasks],
                        {"task_description": task_description},
                    )
                    replan_count += 1
                    trace.replan_triggered = True
                    trace.replan_reason = "task_failure"
                    self.trace_logger.log("replan_partial_complete", {
                        "new_node_count": plan_dag.node_count,
                    })
                else:
                    self.trace_logger.log("max_replan_exceeded", level="error")
                    break

        # 4. 汇总结果
        final_output = self._aggregate_results(plan_dag)
        trace.final_output = final_output
        trace.duration = time.time() - start_time
        self._execution_traces.append(trace)

        self.trace_logger.log("agent_complete", {
            "duration": trace.duration,
            "total_nodes": plan_dag.node_count,
            "replan_count": replan_count,
        })

        self.session_manager.close_session(session_id)

        return {
            "success": plan_dag.is_complete(),
            "task_description": task_description,
            "plan": plan_dag.to_dict(),
            "output": final_output,
            "trace": self.trace_logger.summary(),
            "duration": trace.duration,
            "replan_triggered": trace.replan_triggered,
            "replan_count": replan_count,
        }

    def run_with_trace(self, task_description: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """运行并返回完整追踪日志。"""
        result = self.run(task_description)
        return result, self.trace_logger.get_traces()

    # ------------------------------------------------------------------
    # 计划版本对比
    # ------------------------------------------------------------------

    def compare_plan_versions(
        self, task_description: str
    ) -> Optional[Dict[str, Any]]:
        """对比最新两个版本的计划差异。"""
        versions = self.planner.get_versions(task_description)
        if len(versions) < 2:
            return None
        v1 = versions[-2]
        v2 = versions[-1]
        return self.planner.compare_versions(v1, v2)

    # ------------------------------------------------------------------
    # 执行历史
    # ------------------------------------------------------------------

    def get_execution_history(self) -> List[ExecutionTrace]:
        """获取执行历史。"""
        return list(self._execution_traces)

    def get_last_execution(self) -> Optional[ExecutionTrace]:
        """获取最近一次执行记录。"""
        return self._execution_traces[-1] if self._execution_traces else None

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _plan_with_verification(self, task_description: str) -> TaskDAG:
        """规划并验证，不通过则重新规划。"""
        max_attempts = 3
        for attempt in range(max_attempts):
            plan_dag = self.planner.plan(task_description)

            # 验证
            verification = self.verifier.verify(plan_dag)
            self.trace_logger.log("plan_verified", {
                "attempt": attempt + 1,
                "score": verification.score,
                "passed": verification.passed,
                "issues": len(verification.issues),
            })

            if verification.passed:
                return plan_dag

            # 根据建议改进
            if attempt < max_attempts - 1:
                suggestions = self.verifier.suggest_improvements(plan_dag)
                self.trace_logger.log("plan_improvement_needed", {
                    "suggestions": suggestions,
                })
                # 使用改进建议作为上下文重新规划
                context = {
                    "previous_verification": {
                        "score": verification.score,
                        "issues": [
                            {"message": i.message, "suggestion": i.suggestion}
                            for i in verification.issues
                        ],
                    },
                    "improvement_suggestions": suggestions,
                }
                plan_dag = self.planner.plan(
                    task_description, context=context, force_replan=True
                )
            else:
                # 最后一次尝试，即使不通过也使用
                logger.warning(
                    "Plan verification failed after %d attempts, using last plan "
                    "(score: %.1f)",
                    max_attempts,
                    verification.score,
                )
                return plan_dag

        # 不应到达这里
        return plan_dag

    def _replan_stuck(
        self, dag: TaskDAG, task_description: str
    ) -> TaskDAG:
        """处理 DAG 陷入死锁的情况。"""
        self.trace_logger.log("replan_stuck_start")

        # 找出所有未完成的任务
        pending_ids = [
            n.task_id
            for n in dag.get_all_nodes()
            if n.status == TaskStatus.PENDING
        ]

        # 使用局部重新规划
        new_dag = self.planner.replan_partial(
            dag,
            pending_ids,
            {"task_description": task_description, "reason": "dag_stuck"},
        )

        self.trace_logger.log("replan_stuck_complete", {
            "new_node_count": new_dag.node_count,
        })

        return new_dag

    def _create_executor_func(self) -> Callable[[TaskNode], ExecutionResult]:
        """创建适配调度器的执行器函数。"""
        executor = self.executor

        def execute_fn(task_node: TaskNode) -> ExecutionResult:
            return executor.execute(task_node, self.tool_registry, self.llm_client)

        return execute_fn

    def _aggregate_results(self, dag: TaskDAG) -> Dict[str, Any]:
        """汇总所有任务结果。"""
        results: Dict[str, Any] = {}
        for node in dag.get_all_nodes():
            if node.status == TaskStatus.COMPLETED:
                results[node.task_id] = {
                    "description": node.description,
                    "result": node.result,
                }
            elif node.status == TaskStatus.FAILED:
                results[node.task_id] = {
                    "description": node.description,
                    "error": str(node.result or "Unknown error"),
                    "retries": node.retry_count,
                }

        return {
            "total_tasks": dag.node_count,
            "completed": sum(
                1 for n in dag.get_all_nodes()
                if n.status == TaskStatus.COMPLETED
            ),
            "failed": sum(
                1 for n in dag.get_all_nodes()
                if n.status == TaskStatus.FAILED
            ),
            "skipped": sum(
                1 for n in dag.get_all_nodes()
                if n.status == TaskStatus.SKIPPED
            ),
            "task_results": results,
        }

    def _build_simple_plan(self, task_description: str) -> TaskDAG:
        """为简单任务构建单步计划。"""
        dag = TaskDAG(name="simple_plan")
        node = TaskNode(
            task_id=uuid.uuid4().hex,
            description=task_description,
            expected_output=f"完成: {task_description}",
            priority=0,
        )
        dag.add_node(node)
        return dag

    @staticmethod
    def _task_complexity(task_description: str) -> float:
        """评估任务复杂度（0.0 ~ 1.0）。

        基于以下维度：
        - 描述长度
        - 连接词数量（"并且"、"然后"、"同时"等）
        - 问号数量（多步询问）
        - 步骤性词汇（"首先"、"然后"、"最后"等）

        Returns:
            复杂度评分，越高越复杂。
        """
        complexity = 0.0
        desc = task_description

        # 长度因素
        length = len(desc)
        if length > 200:
            complexity += 0.3
        elif length > 100:
            complexity += 0.2
        elif length > 50:
            complexity += 0.1

        # 连接词
        connectors = [
            "并且", "然后", "同时", "此外", "另外", "接着",
            "and", "then", "also", "first", "second", "finally",
            "步骤", "第", "step",
        ]
        connector_count = sum(1 for c in connectors if c in desc.lower())
        complexity += min(connector_count * 0.1, 0.3)

        # 步骤性标记
        step_markers = ["首先", "然后", "最后", "下一步", "接下来"]
        step_count = sum(1 for m in step_markers if m in desc)
        complexity += min(step_count * 0.1, 0.2)

        # 任务数量关键词
        task_markers = ["任务", "task", "需要", "完成"]
        task_count = sum(1 for m in task_markers if m in desc.lower())
        complexity += min(task_count * 0.05, 0.2)

        return min(complexity, 1.0)

    def __repr__(self) -> str:
        return (
            f"PlannerExecutorAgent(max_workers={self.scheduler.max_workers}, "
            f"replan_attempts={self.max_replan_attempts}, "
            f"tools={len(self.tool_registry)})"
        )
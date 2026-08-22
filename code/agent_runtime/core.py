"""
Agent Runtime 核心模块。

提供 AgentRuntime 核心类，实现完整的 Agent 执行循环，
包含任务调度、工具调用、终止检测、错误处理和 Trace 记录。

创新特性：
- 重复工具调用检测：连续 3 次调用同一工具且参数相同则终止
- 死循环检测：连续 5 步无新增有效 observation 则终止
- 工具调用重试和降级机制
- Token/步数预算控制
- 统一模型和工具适配接口
"""

import json
import logging
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple

from .llm import LLMClient
from .tools import ToolRegistry
from .state import StateManager
from .session import SessionManager
from .trace import TraceLogger
from .exceptions import (
    AgentException,
    ToolNotFoundException,
    ToolExecutionException,
    InvalidToolParameterException,
    ModelCallException,
    MaxStepsExceededException,
    TimeoutException,
    SessionNotFoundException,
)

logger = logging.getLogger("agent_runtime.core")


class AgentRuntime:
    """Agent 运行时核心引擎。

    管理 Agent 的完整执行生命周期，包括：
    - 消息循环（思考 -> 行动 -> 观察 -> 思考）
    - 终止条件检测
    - 错误恢复与降级
    - 完整 Trace 记录

    使用示例::

        llm = LLMClient()
        registry = ToolRegistry()
        session_mgr = SessionManager()
        trace = TraceLogger()

        agent = AgentRuntime(llm, registry, session_mgr, trace)
        result = agent.run("帮我查询天气")
        print(result)

    Attributes:
        llm_client: LLM 客户端实例。
        tool_registry: 工具注册表实例。
        session_manager: 会话管理器实例。
        trace_logger: Trace 日志记录器实例。
        max_steps: 最大执行步数。
        max_time_seconds: 最大执行时间（秒）。
        termination_conditions: 自定义终止条件函数列表。
        max_tool_retries: 工具调用最大重试次数。
        max_model_retries: 模型调用最大重试次数。
        system_prompt: 系统提示词。
    """

    def __init__(
        self,
        llm_client: LLMClient,
        tool_registry: ToolRegistry,
        session_manager: SessionManager,
        trace_logger: TraceLogger,
        max_steps: int = 10,
        max_time_seconds: float = 300.0,
        termination_conditions: Optional[List[Callable[[StateManager], Tuple[bool, str]]]] = None,
        max_tool_retries: int = 2,
        max_model_retries: int = 3,
        system_prompt: Optional[str] = None,
    ) -> None:
        """初始化 Agent Runtime。

        Args:
            llm_client: LLM 客户端实例。
            tool_registry: 工具注册表实例。
            session_manager: 会话管理器实例。
            trace_logger: Trace 日志记录器实例。
            max_steps: 最大执行步数，默认 10。
            max_time_seconds: 最大执行时间（秒），默认 300。
            termination_conditions: 自定义终止条件函数列表。
                每个函数接受 StateManager 实例，返回 (should_terminate, reason)。
            max_tool_retries: 工具调用失败最大重试次数，默认 2。
            max_model_retries: 模型调用失败最大重试次数，默认 3。
            system_prompt: 系统提示词。如果不提供则使用默认提示词。
        """
        self.llm_client = llm_client
        self.tool_registry = tool_registry
        self.session_manager = session_manager
        self.trace_logger = trace_logger
        self.max_steps = max_steps
        self.max_time_seconds = max_time_seconds
        self.termination_conditions = termination_conditions or []
        self.max_tool_retries = max_tool_retries
        self.max_model_retries = max_model_retries
        self.system_prompt = system_prompt or self._build_default_system_prompt()

        # 运行时追踪变量
        self._start_time: Optional[float] = None
        self._session_id: Optional[str] = None
        self._last_tool_calls: List[Dict[str, Any]] = []
        self._consecutive_no_progress: int = 0

    @staticmethod
    def _build_default_system_prompt() -> str:
        """构建默认系统提示词。"""
        return (
            "You are a helpful AI assistant with access to various tools. "
            "When you need to perform an action, use the appropriate tool. "
            "After receiving tool results, analyze them and decide on the next step. "
            "When you have completed the task, provide a clear final answer. "
            "Do not call the same tool with the same parameters repeatedly."
        )

    def run(
        self,
        task: str,
        session_id: Optional[str] = None,
        context_messages: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """执行 Agent 主循环。

        完整的执行流程：
        1. 创建或获取会话
        2. 初始化状态，添加系统提示词和用户任务
        3. 进入 Agent 循环：
           a. 调用 LLM，传入消息历史和工具列表
           b. 如果模型返回 tool_calls，逐个执行工具
           c. 将工具结果作为 observation 添加回消息
           d. 如果模型返回文本回复且无 tool_calls，结束循环
           e. 检查终止条件
        4. 记录完整 trace
        5. 返回最终结果

        Args:
            task: 用户任务描述。
            session_id: 可选的会话 ID。如果不提供则创建新会话。
            context_messages: 可选的上下文消息列表。

        Returns:
            包含执行结果和元数据的字典：
            {
                "success": bool,
                "output": str,
                "steps": int,
                "duration_seconds": float,
                "session_id": str,
                "termination_reason": str,
                "error": Optional[str],
            }

        Raises:
            AgentException: 当执行过程中发生不可恢复的错误时抛出。
        """
        self._start_time = time.time()

        # 1. 创建或获取会话
        self._session_id = self.session_manager.get_or_create_session(session_id)
        state = self.session_manager.get_session(self._session_id)

        # 2. 初始化状态
        state.clear()

        # 添加系统提示词
        state.add_message("system", self.system_prompt)

        # 添加上下文消息
        if context_messages:
            for msg in context_messages:
                state.add_message(**msg)

        # 添加用户任务
        state.add_message("user", task)

        # 重置追踪变量
        self._last_tool_calls = []
        self._consecutive_no_progress = 0

        logger.info("Agent run started: session=%s, task=%s", self._session_id, task[:100])

        final_output: str = ""
        termination_reason: str = "completed"
        error_message: Optional[str] = None
        success: bool = True

        try:
            # 3. Agent 主循环
            while True:
                # 3e. 检查终止条件
                should_terminate, reason = self._check_termination(state)
                if should_terminate:
                    termination_reason = reason
                    logger.info("Agent terminated: %s", reason)

                    self.trace_logger.log_step(
                        step_num=state.current_step,
                        event_type="termination",
                        data={"reason": reason, "final_output": final_output},
                    )
                    break

                # 3a. 调用 LLM
                step_start = time.time()
                try:
                    message = self._call_llm_with_retry(state)
                except ModelCallException as e:
                    # 模型调用失败，记录错误并终止
                    self.trace_logger.log_step(
                        step_num=state.current_step,
                        event_type="error",
                        data={
                            "error_type": "model_call_failed",
                            "error_message": str(e),
                            "recovery": "terminate",
                        },
                    )
                    termination_reason = "model_call_failed"
                    error_message = str(e)
                    success = False
                    break

                step_duration = (time.time() - step_start) * 1000

                # 3b. 检查是否有工具调用
                if message.tool_calls:
                    tool_names = [tc.function.name for tc in message.tool_calls]
                    content_preview = message.content or ""

                    # 记录 LLM 调用
                    self.trace_logger.log_step(
                        step_num=state.current_step,
                        event_type="llm_call",
                        data={
                            "messages_count": len(state.messages),
                            "tools_count": len(self.tool_registry),
                            "has_tool_calls": True,
                            "tool_names": tool_names,
                            "content_preview": content_preview[:200],
                        },
                        duration_ms=step_duration,
                    )

                    # 添加 assistant 消息（含 tool_calls）
                    tc_data = []
                    for tc in message.tool_calls:
                        tc_data.append({
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        })

                    state.add_message("assistant", content=message.content, tool_calls=tc_data)

                    # 3c. 执行工具调用
                    all_results = []
                    for tc in message.tool_calls:
                        tool_name = tc.function.name
                        tool_call_id = tc.id

                        try:
                            arguments = json.loads(tc.function.arguments)
                        except json.JSONDecodeError:
                            arguments = {}

                        # 检查非法工具名
                        if tool_name not in self.tool_registry:
                            handled = self._handle_invalid_tool(tool_name, state)
                            if handled:
                                continue
                            else:
                                # 无法处理，记录错误并继续
                                state.add_message(
                                    "tool",
                                    content=f"Error: Tool '{tool_name}' not found.",
                                    tool_call_id=tool_call_id,
                                    name=tool_name,
                                )
                                self.trace_logger.log_step(
                                    step_num=state.current_step,
                                    event_type="error",
                                    data={
                                        "error_type": "tool_not_found",
                                        "error_message": f"Tool '{tool_name}' not found",
                                        "recovery": "skip",
                                    },
                                )
                                continue

                        # 执行工具（带重试）
                        tool_result = self._execute_tool_with_retry(
                            tool_name, arguments, state, tool_call_id
                        )

                        all_results.append(tool_result)

                        # 添加工具结果到消息
                        result_content = tool_result.get("result", "")
                        if isinstance(result_content, (dict, list)):
                            result_content = json.dumps(result_content, ensure_ascii=False)

                        state.add_message(
                            "tool",
                            content=str(result_content),
                            tool_call_id=tool_call_id,
                            name=tool_name,
                        )

                        # 记录工具调用
                        state.add_tool_call({
                            "id": tool_call_id,
                            "name": tool_name,
                            "arguments": arguments,
                            "success": tool_result.get("success", False),
                        })

                        # 记录观察
                        state.add_observation({
                            "tool_name": tool_name,
                            "result": tool_result.get("result"),
                            "success": tool_result.get("success", False),
                            "error": tool_result.get("error"),
                        })

                    # 3d. 检测重复工具调用
                    self._check_duplicate_tool_calls(tc_data)

                else:
                    # 模型返回纯文本回复，无 tool_calls
                    content = message.content or ""

                    self.trace_logger.log_step(
                        step_num=state.current_step,
                        event_type="llm_call",
                        data={
                            "messages_count": len(state.messages),
                            "tools_count": len(self.tool_registry),
                            "has_tool_calls": False,
                            "content_preview": content[:200],
                        },
                        duration_ms=step_duration,
                    )

                    state.add_message("assistant", content=content)
                    final_output = content
                    termination_reason = "completed"

                    self.trace_logger.log_step(
                        step_num=state.current_step,
                        event_type="termination",
                        data={"reason": "completed", "final_output": final_output},
                    )
                    break

                # 递增步数
                state.increment_step()

        except AgentException as e:
            logger.error("Agent execution failed: %s", e)
            self.trace_logger.log_step(
                step_num=state.current_step,
                event_type="error",
                data={
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                    "recovery": "terminate",
                },
            )
            termination_reason = "error"
            error_message = str(e)
            success = False

        except Exception as e:
            logger.exception("Unexpected error during agent execution")
            self.trace_logger.log_step(
                step_num=state.current_step,
                event_type="error",
                data={
                    "error_type": "unexpected",
                    "error_message": str(e),
                    "recovery": "terminate",
                },
            )
            termination_reason = "unexpected_error"
            error_message = str(e)
            success = False

        # 4. 构建返回结果
        duration = time.time() - self._start_time

        result: Dict[str, Any] = {
            "success": success,
            "output": final_output,
            "steps": state.current_step,
            "duration_seconds": round(duration, 2),
            "session_id": self._session_id,
            "termination_reason": termination_reason,
            "error": error_message,
            "trace_summary": self.trace_logger.get_trace_summary(),
        }

        logger.info(
            "Agent run completed: session=%s, steps=%d, duration=%.1fs, success=%s",
            self._session_id,
            state.current_step,
            duration,
            success,
        )

        return result

    def _call_llm_with_retry(self, state: StateManager) -> Any:
        """调用 LLM 并支持重试。

        Args:
            state: 当前状态管理器。

        Returns:
            ChatCompletionMessage: 模型返回的消息对象。

        Raises:
            ModelCallException: 当所有重试均失败时抛出。
        """
        tools = self.tool_registry.get_tools_openai_format() if self.tool_registry else None
        messages = state.get_messages()

        last_error: Optional[Exception] = None
        for attempt in range(self.max_model_retries):
            try:
                return self.llm_client.chat_completion(
                    messages=messages,
                    tools=tools,
                )
            except ModelCallException as e:
                last_error = e
                if attempt < self.max_model_retries - 1:
                    backoff = 2 ** attempt
                    logger.warning(
                        "LLM call attempt %d/%d failed: %s. Backing off %ds",
                        attempt + 1,
                        self.max_model_retries,
                        e,
                        backoff,
                    )
                    time.sleep(backoff)
                else:
                    raise

        raise ModelCallException(
            f"LLM call failed after {self.max_model_retries} attempts",
            attempt=self.max_model_retries,
            max_attempts=self.max_model_retries,
        ) from last_error

    def _execute_tool_with_retry(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        state: StateManager,
        tool_call_id: str,
    ) -> Dict[str, Any]:
        """执行工具调用并支持重试和降级。

        Args:
            tool_name: 工具名称。
            arguments: 工具参数。
            state: 当前状态管理器。
            tool_call_id: 工具调用 ID。

        Returns:
            包含执行结果的字典：
            {"success": bool, "result": Any, "error": Optional[str]}
        """
        tool = self.tool_registry.get(tool_name)

        for attempt in range(self.max_tool_retries + 1):
            tool_start = time.time()
            try:
                result = tool.execute(**arguments)
                tool_duration = (time.time() - tool_start) * 1000

                self.trace_logger.log_step(
                    step_num=state.current_step,
                    event_type="tool_call",
                    data={
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "tool_call_id": tool_call_id,
                    },
                    duration_ms=tool_duration,
                )

                self.trace_logger.log_step(
                    step_num=state.current_step,
                    event_type="tool_result",
                    data={
                        "tool_name": tool_name,
                        "success": True,
                        "result": result,
                    },
                )

                return {"success": True, "result": result, "error": None}

            except (InvalidToolParameterException, ToolExecutionException) as e:
                tool_duration = (time.time() - tool_start) * 1000
                logger.warning(
                    "Tool '%s' execution attempt %d/%d failed: %s",
                    tool_name,
                    attempt + 1,
                    self.max_tool_retries + 1,
                    e,
                )

                self.trace_logger.log_step(
                    step_num=state.current_step,
                    event_type="tool_result",
                    data={
                        "tool_name": tool_name,
                        "success": False,
                        "result": None,
                        "error": str(e),
                    },
                    duration_ms=tool_duration,
                )

                if attempt < self.max_tool_retries:
                    # 重试：将错误信息添加到状态中，让模型可以调整参数
                    state.add_message(
                        "tool",
                        content=f"Error: {str(e)}. Please fix the arguments and try again.",
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    )
                    # 生成新的 tool_call_id 用于重试
                    return {"success": False, "result": None, "error": str(e)}

                else:
                    # 降级：跳过该工具
                    self.trace_logger.log_step(
                        step_num=state.current_step,
                        event_type="error",
                        data={
                            "error_type": "tool_execution_failed",
                            "error_message": str(e),
                            "recovery": "degraded",
                            "tool_name": tool_name,
                        },
                    )
                    logger.warning(
                        "Tool '%s' degraded after %d attempts",
                        tool_name,
                        self.max_tool_retries + 1,
                    )
                    return {
                        "success": False,
                        "result": f"Tool execution failed after retries: {str(e)}",
                        "error": str(e),
                    }

            except Exception as e:
                # 未知错误，不重试，直接降级
                logger.error("Unexpected error executing tool '%s': %s", tool_name, e)
                self.trace_logger.log_step(
                    step_num=state.current_step,
                    event_type="error",
                    data={
                        "error_type": "tool_unexpected_error",
                        "error_message": str(e),
                        "recovery": "degraded",
                        "tool_name": tool_name,
                    },
                )
                return {
                    "success": False,
                    "result": f"Unexpected error: {str(e)}",
                    "error": str(e),
                }

        return {"success": False, "result": "Tool execution failed", "error": "max_retries_exceeded"}

    def _handle_invalid_tool(self, tool_name: str, state: StateManager) -> bool:
        """处理非法工具名称。

        提示模型重新选择正确的工具。

        Args:
            tool_name: 非法的工具名称。
            state: 当前状态管理器。

        Returns:
            是否成功处理（True 表示模型应该重新选择）。
        """
        available_tools = self.tool_registry.list_names()
        error_msg = (
            f"Tool '{tool_name}' is not available. "
            f"Available tools: {', '.join(available_tools)}. "
            f"Please select a valid tool."
        )

        state.add_message(
            "tool",
            content=error_msg,
            name="system",
            tool_call_id="invalid_tool",
        )

        self.trace_logger.log_step(
            step_num=state.current_step,
            event_type="error",
            data={
                "error_type": "invalid_tool_name",
                "error_message": f"Tool '{tool_name}' not found",
                "recovery": "prompt_reselection",
                "available_tools": available_tools,
            },
        )

        logger.warning("Invalid tool '%s' requested. Prompting model to reselect.", tool_name)
        return True

    def _check_termination(self, state: StateManager) -> Tuple[bool, str]:
        """检查终止条件。

        按优先级依次检查：
        1. 最大步数
        2. 最大时间
        3. 重复工具调用检测
        4. 死循环检测
        5. 自定义终止条件

        Args:
            state: 当前状态管理器。

        Returns:
            (should_terminate, reason) 元组。
        """
        # 1. 最大步数检查
        if state.current_step >= self.max_steps:
            return True, f"max_steps_reached ({state.current_step}/{self.max_steps})"

        # 2. 最大时间检查
        if self._start_time is not None:
            elapsed = time.time() - self._start_time
            if elapsed >= self.max_time_seconds:
                return True, f"timeout ({elapsed:.1f}s/{self.max_time_seconds:.1f}s)"

        # 3. 重复工具调用检测：连续 3 次调用同一工具且参数相同
        if self._last_tool_calls and len(self._last_tool_calls) >= 3:
            recent = self._last_tool_calls[-3:]
            if self._all_same_tool_call(recent):
                tool_name = recent[0].get("function", {}).get("name", "unknown")
                return True, f"duplicate_tool_calls_detected (tool='{tool_name}' called 3 times with same params)"

        # 4. 死循环检测：连续 5 步无新增有效 observation
        if self._consecutive_no_progress >= 5:
            return True, "infinite_loop_detected (5 consecutive steps without progress)"

        # 5. 自定义终止条件
        for condition in self.termination_conditions:
            should_stop, reason = condition(state)
            if should_stop:
                return True, f"custom_condition: {reason}"

        return False, ""

    @staticmethod
    def _all_same_tool_call(tool_calls: List[Dict[str, Any]]) -> bool:
        """检查一组工具调用是否完全相同。

        Args:
            tool_calls: 工具调用记录列表。

        Returns:
            是否所有调用相同。
        """
        if len(tool_calls) < 2:
            return False

        first = tool_calls[0]
        first_name = first.get("function", {}).get("name", "")
        first_args = first.get("function", {}).get("arguments", "")

        for tc in tool_calls[1:]:
            tc_name = tc.get("function", {}).get("name", "")
            tc_args = tc.get("function", {}).get("arguments", "")
            if tc_name != first_name or tc_args != first_args:
                return False

        return True

    def _check_duplicate_tool_calls(self, tc_data: List[Dict[str, Any]]) -> None:
        """更新重复工具调用追踪状态。

        记录最近 3 次工具调用，并检测无进展步数。

        Args:
            tc_data: 当前步骤的工具调用数据。
        """
        self._last_tool_calls.append(tc_data[0] if tc_data else {})
        if len(self._last_tool_calls) > 3:
            self._last_tool_calls = self._last_tool_calls[-3:]

        # 检查是否有实质进展
        has_progress = self._has_new_observation(self._session_id)
        if has_progress:
            self._consecutive_no_progress = 0
        else:
            self._consecutive_no_progress += 1

    def _has_new_observation(self, session_id: str) -> bool:
        """检查当前步骤是否有新的有效观察结果。

        Args:
            session_id: 会话 ID。

        Returns:
            是否有新观察。
        """
        try:
            state = self.session_manager.get_session(session_id)
            if not state.observations:
                return True  # 第一步没有观察是正常的

            # 检查最近 2 次观察是否有不同
            if len(state.observations) >= 2:
                recent = state.observations[-2:]
                if recent[0].get("tool_name") != recent[1].get("tool_name"):
                    return True
                if recent[0].get("result") != recent[1].get("result"):
                    return True

            return False
        except SessionNotFoundException:
            return False

    def get_runtime_info(self) -> Dict[str, Any]:
        """获取运行时信息。

        Returns:
            包含当前运行时配置和状态的字典。
        """
        return {
            "session_id": self._session_id,
            "max_steps": self.max_steps,
            "max_time_seconds": self.max_time_seconds,
            "tools_count": len(self.tool_registry),
            "tool_names": self.tool_registry.list_names(),
            "model_name": self.llm_client.model_name,
            "elapsed_seconds": round(time.time() - self._start_time, 2) if self._start_time else 0,
            "consecutive_no_progress": self._consecutive_no_progress,
        }
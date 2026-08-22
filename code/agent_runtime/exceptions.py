"""
Agent Runtime 异常类体系。

定义了 Agent Runtime 系统所有可能抛出的异常类型，
支持细粒度的错误处理和恢复策略。
"""

from typing import Any, Dict, Optional


class AgentException(Exception):
    """Agent Runtime 异常的基类。

    所有 Agent Runtime 相关异常都继承自此类，
    便于统一捕获和处理。

    Attributes:
        message: 异常描述信息。
        details: 可选的额外详细信息字典。
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} (details: {self.details})"
        return self.message


class ToolNotFoundException(AgentException):
    """工具未找到异常。

    当请求调用一个未注册的工具时抛出。

    Attributes:
        tool_name: 未找到的工具名称。
    """

    def __init__(self, tool_name: str, details: Optional[Dict[str, Any]] = None) -> None:
        self.tool_name = tool_name
        super().__init__(
            message=f"Tool '{tool_name}' not found in registry",
            details=details or {"tool_name": tool_name},
        )


class ToolExecutionException(AgentException):
    """工具执行异常。

    当工具函数在执行过程中发生错误时抛出。

    Attributes:
        tool_name: 执行失败的工具名称。
        original_error: 原始异常对象（可选）。
    """

    def __init__(
        self,
        tool_name: str,
        message: str = "",
        original_error: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.tool_name = tool_name
        self.original_error = original_error
        full_message = message or f"Tool '{tool_name}' execution failed"
        if original_error:
            full_message = f"{full_message}: {original_error}"
        full_details = details or {"tool_name": tool_name}
        if original_error:
            full_details["original_error"] = str(original_error)
        super().__init__(message=full_message, details=full_details)


class InvalidToolParameterException(AgentException):
    """工具参数错误异常。

    当调用工具时传入的参数不符合工具定义的 JSON Schema 时抛出。

    Attributes:
        tool_name: 工具名称。
        invalid_params: 无效的参数列表或描述。
    """

    def __init__(
        self,
        tool_name: str,
        invalid_params: Any,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.tool_name = tool_name
        self.invalid_params = invalid_params
        super().__init__(
            message=f"Invalid parameters for tool '{tool_name}': {invalid_params}",
            details=details or {"tool_name": tool_name, "invalid_params": invalid_params},
        )


class ModelCallException(AgentException):
    """模型调用异常。

    当调用 LLM 模型时发生错误时抛出，包括超时、限流、认证失败等。

    Attributes:
        attempt: 当前重试次数。
        max_attempts: 最大重试次数。
    """

    def __init__(
        self,
        message: str,
        attempt: int = 0,
        max_attempts: int = 3,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.attempt = attempt
        self.max_attempts = max_attempts
        full_details = details or {}
        full_details.update({"attempt": attempt, "max_attempts": max_attempts})
        super().__init__(message=message, details=full_details)


class MaxStepsExceededException(AgentException):
    """超出最大步数异常。

    当 Agent 执行步数超过预设的最大值时抛出。

    Attributes:
        current_step: 当前步数。
        max_steps: 最大步数限制。
    """

    def __init__(
        self,
        current_step: int,
        max_steps: int,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.current_step = current_step
        self.max_steps = max_steps
        super().__init__(
            message=f"Agent exceeded maximum steps: {current_step}/{max_steps}",
            details=details or {"current_step": current_step, "max_steps": max_steps},
        )


class TimeoutException(AgentException):
    """超时异常。

    当 Agent 执行时间超过预设的最大时间时抛出。

    Attributes:
        elapsed_seconds: 已用时间（秒）。
        max_seconds: 最大时间限制（秒）。
    """

    def __init__(
        self,
        elapsed_seconds: float,
        max_seconds: float,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.elapsed_seconds = elapsed_seconds
        self.max_seconds = max_seconds
        super().__init__(
            message=f"Agent execution timed out: {elapsed_seconds:.1f}s / {max_seconds:.1f}s",
            details=details or {"elapsed_seconds": elapsed_seconds, "max_seconds": max_seconds},
        )


class SessionNotFoundException(AgentException):
    """会话未找到异常。

    当请求操作一个不存在的会话时抛出。

    Attributes:
        session_id: 未找到的会话 ID。
    """

    def __init__(
        self,
        session_id: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.session_id = session_id
        super().__init__(
            message=f"Session '{session_id}' not found",
            details=details or {"session_id": session_id},
        )
"""
Agent Runtime 系统包。

红岩网校 AI 部门考核项目 - 公共主线部分。

提供完整的 Agent 运行时框架，包括：
- 统一的 LLM 客户端接口（支持 OpenAI 兼容 API）
- 可扩展的工具注册与管理系统
- 状态管理与会话隔离
- 完整的 Trace 日志记录
- 智能的终止条件检测与错误恢复

核心组件:
    - AgentRuntime: Agent 运行时核心引擎
    - LLMClient: LLM 客户端
    - ToolRegistry: 工具注册表
    - Tool: 工具定义
    - StateManager: 状态管理器
    - SessionManager: 会话管理器
    - TraceLogger: Trace 日志记录器

异常体系:
    - AgentException: 基础异常
    - ToolNotFoundException: 工具未找到
    - ToolExecutionException: 工具执行异常
    - InvalidToolParameterException: 参数错误
    - ModelCallException: 模型调用异常
    - MaxStepsExceededException: 超出最大步数
    - TimeoutException: 超时
    - SessionNotFoundException: 会话未找到
"""

from .core import AgentRuntime
from .llm import LLMClient
from .tools import Tool, ToolRegistry
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

__all__ = [
    # 核心
    "AgentRuntime",
    # 客户端
    "LLMClient",
    # 工具
    "Tool",
    "ToolRegistry",
    # 状态
    "StateManager",
    # 会话
    "SessionManager",
    # 日志
    "TraceLogger",
    # 异常
    "AgentException",
    "ToolNotFoundException",
    "ToolExecutionException",
    "InvalidToolParameterException",
    "ModelCallException",
    "MaxStepsExceededException",
    "TimeoutException",
    "SessionNotFoundException",
]

__version__ = "1.0.0"
"""
统一工具注册协议。

历史原因：框架内存在 3 个语义不同的 ``ToolRegistry``
（agent_runtime 面向 Tool 对象、planner_executor 面向 (name, handler, desc)、
mcp 面向 (schema, handler, server)）。物理强行合并会破坏大量既有消费方。

本模块以"统一接入协议"为目标：外部扩展者面对**一套** ``ToolRegistryProtocol``
（register_tool / get / list_names / find_tool），
内部保留各层对工具形态的原生支持。

职责：
- :data:`ToolRegistryProtocol`：统一接入接口（ABC）。
- :func:`create_registry`：按场景创建统一协议实例。
- :func:`register_tool`：通配注册入口，自动适配任意协议实现。
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("framework.registry")

# 结构最完整的 AgentRuntime ToolRegistry 也是一次 Protocol 镇定基准
_HAS_AGENT_RUNTIME = True

try:
    from .agent_runtime.tools import Tool as AgentTool
except Exception:  # pragma: no cover  # noqa: BLE001
    _HAS_AGENT_RUNTIME = False
    AgentTool = None  # type: ignore[assignment]


class ToolRegistryProtocol(ABC):
    """所有注册表必须实现的统一接入协议。

    让扩展者不关心底层是哪种注册表，只依赖这四个能力。
    """

    @abstractmethod
    def register_tool(
        self,
        name: str,
        handler: Optional[Callable[..., Any]] = None,
        description: str = "",
        **extra: Any,
    ) -> None:
        """注册一个工具（统一接入入口）。"""

    @abstractmethod
    def get(self, name: str) -> Any:
        """按名称获取工具句柄。"""

    @abstractmethod
    def list_names(self) -> List[str]:
        """列出全部工具名称。"""

    @abstractmethod
    def find_tool(self, task_description: str) -> Optional[str]:
        """根据任务描述返回最匹配的工具名（匹配不到返回 None）。"""

    # 一些消费方只需要"能执行即可"，缺少统一执行方法则降级为无操作
    def execute(self, name: str, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError(f"{type(self).__name__} does not expose execute()")


def _resolve_name(name_or_obj: Any) -> str:
    """name 位置传入对象时，取其 .name；否则原样返回。"""
    if isinstance(name_or_obj, str):
        return name_or_obj
    n = getattr(name_or_obj, "name", None)
    if isinstance(n, str):
        return n
    raise TypeError(
        f"register_tool 需要工具名称字符串或带 .name 的对象，得到 {type(name_or_obj)!r}"
    )


class StandardRegistry(ToolRegistryProtocol):
    """协议的标准实现：面向 ``(name, handler, description)``。

    与 planner_executor.ToolRegistry 语义一致，内置简单关键词 ``find_tool``。
    是"统一协议"的默认落地，多数自建工具接入直接用本类即可。
    """

    def __init__(self, overwrite: bool = True) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._overwrite = overwrite

    def register_tool(
        self,
        name: str,
        handler: Optional[Callable[..., Any]] = None,
        description: str = "",
        **extra: Any,
    ) -> None:
        key = _resolve_name(name)
        if not self._overwrite and key in self._tools:
            raise ValueError(f"Tool '{key}' is already registered.")
        self._tools[key] = {
            "handler": handler,
            "description": description,
            "extra": extra,
        }
        logger.info("Registered tool '%s' (standard)", key)

    register = register_tool  # 兼容偏好 register 的调用方

    def get(self, name: str) -> Any:
        entry = self._tools.get(name)
        return entry["handler"] if entry else None

    def list_names(self) -> List[str]:
        return list(self._tools.keys())

    def list_tools(self) -> List[Dict[str, str]]:
        return [
            {"name": name, "description": entry["description"]}
            for name, entry in self._tools.items()
        ]

    def find_tool(self, task_description: str) -> Optional[str]:
        desc_lower = task_description.lower()
        best: Optional[str] = None
        best_score = 0
        for name, entry in self._tools.items():
            score = 0
            if name.lower() in desc_lower:
                score += 3
            word = set(name.lower().split()) | set(entry["description"].lower().split())
            for kw in word:
                if kw in desc_lower:
                    score += 1
            if score > best_score:
                best_score, best = score, name
        return best

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: str) -> bool:
        return name in self._tools


def create_registry(kind: str = "standard", **kwargs: Any) -> ToolRegistryProtocol:
    """按场景创建统一协议实例。

    kind:
        - "standard"：默认标准实现（推荐给自建工具/新层）。
        - "agent"  ：agent_runtime 注册表（面向 Tool 对象）。
        - "executor"：planner_executor 注册表。
        - "mcp"    ：MCP 增强注册表（面向 schema + server 发现）。

    说明：这里延迟 import 以避免模块间循环依赖；
    若某子包未就绪则回退到标准实现。
    """
    kind = (kind or "standard").lower()
    try:
        if kind == "agent":
            from .agent_runtime.tools import ToolRegistry as AgentRegistry
            return AgentRegistry()
        if kind == "executor":
            from .planner_executor.executor import ToolRegistry as ExecutorRegistry
            return ExecutorRegistry()
        if kind == "mcp":
            from .mcp.registry import ToolRegistry as McpRegistry
            return McpRegistry()
    except Exception as e:  # pragma: no cover  # noqa: BLE001
        logger.warning("create_registry('%s') failed (%s); falling back to standard", kind, e)
    return StandardRegistry(**kwargs)


def register_tool(
    registry: ToolRegistryProtocol,
    name: str,
    handler: Optional[Callable[..., Any]] = None,
    description: str = "",
    **extra: Any,
) -> str:
    """通配注册入口：对任意协议实现执行统一注册，返回工具名。

    入参兼容三种风格：传 ``(name, handler, description)`` 或只传 ``(Tool对象)``。
    """
    if handler is None and name and not hasattr(name, "execute"):
        handler = extra.pop("tool", None)
    registry.register_tool(name, handler, description, **extra)
    return _resolve_name(name)
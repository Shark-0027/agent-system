"""
MCP Server 基类

提供 MCP Server 的核心抽象：工具注册、调用、健康检查、超时控制。
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import time
from abc import ABC
from typing import Any, Callable, Dict, List, Optional

from .schema import ParameterValidationError, ToolSchema

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 自定义异常
# ---------------------------------------------------------------------------

class MCPError(Exception):
    """MCP 通用异常基类。"""


class ToolNotFoundError(MCPError):
    """工具未找到异常。"""

    def __init__(self, tool_name: str, server_name: str = "") -> None:
        self.tool_name = tool_name
        self.server_name = server_name
        msg = f"Tool '{tool_name}' not found"
        if server_name:
            msg += f" on server '{server_name}'"
        super().__init__(msg)


class ToolExecutionError(MCPError):
    """工具执行异常。"""

    def __init__(self, tool_name: str, message: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' execution error: {message}")


class ToolTimeoutError(MCPError):
    """工具执行超时异常。"""

    def __init__(self, tool_name: str, timeout: float) -> None:
        self.tool_name = tool_name
        self.timeout = timeout
        super().__init__(f"Tool '{tool_name}' timed out after {timeout}s")


# ---------------------------------------------------------------------------
# 工具包装器
# ---------------------------------------------------------------------------

class _ToolWrapper:
    """内部工具包装器，将 Schema 与处理函数绑定。"""

    def __init__(
        self,
        schema: ToolSchema,
        handler: Callable[..., Any],
        timeout: Optional[float] = None,
    ):
        self.schema = schema
        self.handler = handler
        self.timeout = timeout

    def __repr__(self) -> str:
        return f"_ToolWrapper(name={self.schema.name!r})"


# ---------------------------------------------------------------------------
# MCPServer
# ---------------------------------------------------------------------------

class MCPServer(ABC):
    """MCP Server 基类。

    所有自定义 MCP Server 必须继承此类，并实现相关业务逻辑。
    通过 register_tool 注册工具，通过 call_tool 调用工具。

    使用示例::

        class MyServer(MCPServer):
            def __init__(self):
                super().__init__(
                    name="my-server",
                    description="My custom MCP server",
                )
                self.register_tool(
                    schema=ToolSchema(name="hello", ...),
                    handler=self._hello,
                    timeout=5.0,
                )

            def _hello(self, name: str) -> dict:
                return {"greeting": f"Hello, {name}!"}
    """

    # -- 类属性 ----------------------------------------------------------------

    DEFAULT_TIMEOUT: float = 30.0
    """默认工具超时时间（秒）。"""

    # -- 构造与初始化 ----------------------------------------------------------

    def __init__(
        self,
        name: str,
        version: str = "1.0.0",
        description: str = "",
        default_timeout: Optional[float] = None,
    ):
        self._name = name
        self._version = version
        self._description = description
        self._default_timeout = default_timeout or self.DEFAULT_TIMEOUT
        self._tools: Dict[str, _ToolWrapper] = {}
        self._started_at: Optional[float] = None
        self._call_count: int = 0

    # -- 属性 ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def version(self) -> str:
        return self._version

    @property
    def description(self) -> str:
        return self._description

    @property
    def tools(self) -> List[ToolSchema]:
        """返回所有已注册工具的 Schema 列表。"""
        return [tw.schema for tw in self._tools.values()]

    @property
    def call_count(self) -> int:
        """工具调用总次数。"""
        return self._call_count

    # -- 工具注册 --------------------------------------------------------------

    def register_tool(
        self,
        schema: ToolSchema,
        handler: Callable[..., Any],
        timeout: Optional[float] = None,
    ) -> None:
        """注册一个工具。

        Args:
            schema: 工具 Schema 定义。
            handler: 工具处理函数，接受关键字参数，返回结果。
            timeout: 工具独立超时时间（秒），默认为 Server 全局超时。
        """
        if schema.name in self._tools:
            logger.warning(
                "Tool '%s' already registered on server '%s', overwriting.",
                schema.name,
                self._name,
            )
        self._tools[schema.name] = _ToolWrapper(
            schema=schema, handler=handler, timeout=timeout
        )
        logger.info(
            "Registered tool '%s' on server '%s' (version %s)",
            schema.name,
            self._name,
            schema.version,
        )

    def unregister_tool(self, tool_name: str) -> bool:
        """注销工具。返回是否成功。"""
        if tool_name in self._tools:
            del self._tools[tool_name]
            logger.info("Unregistered tool '%s' from server '%s'", tool_name, self._name)
            return True
        return False

    # -- 工具发现 --------------------------------------------------------------

    def list_tools(self) -> List[Dict[str, Any]]:
        """返回所有工具的 Schema 字典列表。"""
        return [tw.schema.to_dict() for tw in self._tools.values()]

    def get_tool_schema(self, tool_name: str) -> Optional[ToolSchema]:
        """获取指定工具的 Schema。"""
        wrapper = self._tools.get(tool_name)
        return wrapper.schema if wrapper else None

    # -- 工具调用 --------------------------------------------------------------

    def call_tool(self, tool_name: str, **kwargs: Any) -> Dict[str, Any]:
        """调用工具并返回结果。

        流程：
        1. 查找工具
        2. 参数校验
        3. 执行（带超时）
        4. 返回标准化结果

        Returns:
            包含 success / result / error 字段的字典。
        """
        start_time = time.monotonic()
        self._call_count += 1

        wrapper = self._tools.get(tool_name)
        if not wrapper:
            return self._error_result(
                ToolNotFoundError(tool_name, self._name).args[0],
                start_time,
            )

        # 参数校验
        try:
            validated_kwargs = wrapper.schema.validate_params(kwargs)
        except ParameterValidationError as e:
            return self._error_result(
                f"Parameter validation error: {e}",
                start_time,
            )

        # 执行
        timeout = wrapper.timeout if wrapper.timeout is not None else self._default_timeout
        try:
            result = self._execute_with_timeout(wrapper.handler, timeout, validated_kwargs)
            elapsed = time.monotonic() - start_time
            return {
                "success": True,
                "result": result,
                "tool": tool_name,
                "server": self._name,
                "elapsed_seconds": round(elapsed, 4),
                "error": None,
            }
        except ToolTimeoutError as e:
            return self._error_result(str(e), start_time)
        except Exception as e:
            return self._error_result(
                f"ToolExecutionError: {e}",
                start_time,
            )

    def _execute_with_timeout(
        self,
        handler: Callable[..., Any],
        timeout: float,
        kwargs: Dict[str, Any],
    ) -> Any:
        """带超时控制的执行器。

        支持同步和异步 handler，使用 threading 实现跨平台超时。
        """
        if asyncio.iscoroutinefunction(handler):
            return self._run_async_with_timeout(handler, timeout, kwargs)
        else:
            return self._run_sync_with_timeout(handler, timeout, kwargs)

    def _run_sync_with_timeout(
        self,
        handler: Callable[..., Any],
        timeout: float,
        kwargs: Dict[str, Any],
    ) -> Any:
        """同步 handler 超时执行（使用 ThreadPoolExecutor）。"""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(handler, **kwargs)
            try:
                return future.result(timeout=timeout)
            except concurrent.futures.TimeoutError:
                raise ToolTimeoutError("unknown", timeout)

    def _run_async_with_timeout(
        self,
        handler: Callable[..., Any],
        timeout: float,
        kwargs: Dict[str, Any],
    ) -> Any:
        """异步 handler 超时执行。"""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(
                asyncio.wait_for(handler(**kwargs), timeout=timeout)
            )
        except asyncio.TimeoutError:
            raise ToolTimeoutError("unknown", timeout)

    def _error_result(self, error_msg: str, start_time: float) -> Dict[str, Any]:
        """构建错误结果。"""
        elapsed = time.monotonic() - start_time
        return {
            "success": False,
            "result": None,
            "error": error_msg,
            "server": self._name,
            "elapsed_seconds": round(elapsed, 4),
        }

    # -- 健康检查 --------------------------------------------------------------

    def health_check(self) -> Dict[str, Any]:
        """健康检查。

        Returns:
            包含 status、uptime、tool_count、call_count 等信息的字典。
        """
        uptime = None
        if self._started_at is not None:
            uptime = round(time.monotonic() - self._started_at, 2)
        return {
            "status": "healthy",
            "server": self._name,
            "version": self._version,
            "tool_count": len(self._tools),
            "tool_names": list(self._tools.keys()),
            "call_count": self._call_count,
            "uptime_seconds": uptime,
        }

    def start(self) -> None:
        """标记 Server 启动。"""
        self._started_at = time.monotonic()
        logger.info("Server '%s' started (version %s)", self._name, self._version)

    def stop(self) -> None:
        """标记 Server 停止。"""
        self._started_at = None
        logger.info("Server '%s' stopped", self._name)

    def __repr__(self) -> str:
        return (
            f"MCPServer(name={self._name!r}, version={self._version!r}, "
            f"tools={len(self._tools)})"
        )
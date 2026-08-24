"""
MCP Client

管理多个 MCP Server 连接，统一调用接口，提供 Trace 记录和权限控制。
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from .server import MCPServer, ToolNotFoundError, ToolTimeoutError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 权限等级
# ---------------------------------------------------------------------------

# 显式的等级顺序（字符串字典序与等级语义不一致，需显式定义）
_PERMISSION_ORDER: Dict[str, int] = {"read": 0, "write": 1, "admin": 2}


class PermissionLevel(Enum):
    """工具权限等级。"""

    READ = "read"
    """只读操作：查询、搜索等。"""

    WRITE = "write"
    """写入操作：修改、创建、删除等。"""

    ADMIN = "admin"
    """管理员操作：系统配置、用户管理等。"""

    @classmethod
    def from_string(cls, value: str) -> "PermissionLevel":
        try:
            return cls(value.lower())
        except ValueError:
            logger.warning("Unknown permission level '%s', defaulting to READ", value)
            return cls.READ

    def rank(self) -> int:
        """返回等级数值，用于比较。"""
        return _PERMISSION_ORDER[self.value]

    def __lt__(self, other: "PermissionLevel") -> bool:
        return self.rank() < other.rank()


# ---------------------------------------------------------------------------
# Trace 记录
# ---------------------------------------------------------------------------

@dataclass
class TraceRecord:
    """工具调用 Trace 记录。"""

    trace_id: str
    server_name: str
    tool_name: str
    params: Dict[str, Any]
    success: bool
    result: Any = None
    error: str = ""
    elapsed_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "server_name": self.server_name,
            "tool_name": self.tool_name,
            "params": self.params,
            "success": self.success,
            "result": self.result,
            "error": self.error,
            "elapsed_seconds": self.elapsed_seconds,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# 权限配置
# ---------------------------------------------------------------------------

@dataclass
class ToolPermissionConfig:
    """工具权限配置。"""

    tool_name: str
    level: PermissionLevel = PermissionLevel.READ
    """工具所需权限等级。"""


# ---------------------------------------------------------------------------
# MCPClient
# ---------------------------------------------------------------------------

class MCPClient:
    """MCP Client -- 管理多个 MCP Server 连接。

    提供统一的工具发现、调用、Trace 记录和权限控制。

    使用示例::

        client = MCPClient()
        client.connect_server(my_server)
        tools = client.list_all_tools()
        result = client.call_tool("my-server", "hello", name="World")
    """

    # -- 类属性 ----------------------------------------------------------------

    DEFAULT_TIMEOUT: float = 60.0
    """默认调用超时（秒）。"""

    MAX_TRACE_HISTORY: int = 1000
    """最大 Trace 记录数。"""

    # -- 构造与初始化 ----------------------------------------------------------

    def __init__(
        self,
        default_timeout: Optional[float] = None,
        require_permission: bool = False,
    ):
        self._servers: Dict[str, MCPServer] = {}
        self._default_timeout: float = default_timeout or self.DEFAULT_TIMEOUT
        self._require_permission: bool = require_permission
        self._trace_records: List[TraceRecord] = []
        self._trace_counter: int = 0
        self._trace_lock: threading.Lock = threading.Lock()
        self._permissions: Dict[str, PermissionLevel] = {}

    # -- 属性 ------------------------------------------------------------------

    @property
    def servers(self) -> Dict[str, MCPServer]:
        return dict(self._servers)

    @property
    def trace_records(self) -> List[TraceRecord]:
        return list(self._trace_records)

    # -- 连接管理 --------------------------------------------------------------

    def connect_server(self, server: MCPServer) -> None:
        """注册一个 MCP Server。

        Args:
            server: 实现了 MCPServer 接口的服务器实例。
        """
        if server.name in self._servers:
            logger.warning(
                "Server '%s' already connected, replacing.", server.name
            )
        self._servers[server.name] = server
        server.start()
        logger.info(
            "Connected server '%s' with %d tools",
            server.name,
            len(server.tools),
        )

    def disconnect_server(self, server_name: str) -> bool:
        """断开 MCP Server 连接。

        Returns:
            是否成功断开。
        """
        server = self._servers.pop(server_name, None)
        if server:
            server.stop()
            logger.info("Disconnected server '%s'", server_name)
            return True
        logger.warning("Server '%s' not found for disconnection", server_name)
        return False

    def get_server(self, server_name: str) -> Optional[MCPServer]:
        """获取已连接的 Server。"""
        return self._servers.get(server_name)

    # -- 工具发现 --------------------------------------------------------------

    def discover_tools(self) -> Dict[str, List[Dict[str, Any]]]:
        """发现所有已连接 Server 的工具。

        Returns:
            {server_name: [tool_dict, ...]} 的映射。
        """
        result: Dict[str, List[Dict[str, Any]]] = {}
        for name, server in self._servers.items():
            try:
                result[name] = server.list_tools()
            except Exception as e:
                logger.error("Failed to discover tools from server '%s': %s", name, e)
                result[name] = []
        return result

    def list_all_tools(self) -> List[Dict[str, Any]]:
        """列出所有已连接 Server 的可用工具。

        Returns:
            扁平化的工具列表，每个工具包含 server_name 字段。
        """
        all_tools: List[Dict[str, Any]] = []
        for server_name, server in self._servers.items():
            try:
                for tool_dict in server.list_tools():
                    tool_dict["server_name"] = server_name
                    all_tools.append(tool_dict)
            except Exception as e:
                logger.error(
                    "Failed to list tools from server '%s': %s", server_name, e
                )
        return all_tools

    # -- 工具调用 --------------------------------------------------------------

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        user_level: Optional[PermissionLevel] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """调用远程工具。

        Args:
            server_name: Server 名称。
            tool_name: 工具名称。
            user_level: 调用方权限等级，默认 READ。当启用权限检查（
                require_permission）且设置了工具所需权限时，若用户等级低于
                工具要求则调用被拒绝。用于支持多身份/真实用户权限体系。
            **kwargs: 工具参数。

        Returns:
            标准化调用结果字典。
        """
        trace_id = self._generate_trace_id()

        # 降级：Server 不可用
        server = self._servers.get(server_name)
        if server is None:
            record = TraceRecord(
                trace_id=trace_id,
                server_name=server_name,
                tool_name=tool_name,
                params=kwargs,
                success=False,
                error=f"Server '{server_name}' not connected",
            )
            self._record_trace(record)
            return {
                "success": False,
                "result": None,
                "error": f"Server '{server_name}' not connected",
                "trace_id": trace_id,
            }

        # 权限检查
        if self._require_permission:
            perm_key = f"{server_name}:{tool_name}"
            required_level = self._permissions.get(perm_key)
            if required_level is not None:
                # 默认当前用户权限为 READ（兼容旧行为），调用方可显式传入真实等级
                current = user_level or PermissionLevel.READ
                if current < required_level:
                    record = TraceRecord(
                        trace_id=trace_id,
                        server_name=server_name,
                        tool_name=tool_name,
                        params=kwargs,
                        success=False,
                        error=f"Permission denied: requires {required_level.value}"
                        f", user level {current.value}",
                    )
                    self._record_trace(record)
                    return {
                        "success": False,
                        "result": None,
                        "error": f"Permission denied: requires {required_level.value}"
                        f", user level {current.value}",
                        "trace_id": trace_id,
                    }

        # 调用
        try:
            result = server.call_tool(tool_name, **kwargs)
            record = TraceRecord(
                trace_id=trace_id,
                server_name=server_name,
                tool_name=tool_name,
                params=kwargs,
                success=result.get("success", False),
                result=result.get("result"),
                error=result.get("error", ""),
                elapsed_seconds=result.get("elapsed_seconds", 0.0),
            )
            self._record_trace(record)
            result["trace_id"] = trace_id
            return result
        except Exception as e:
            record = TraceRecord(
                trace_id=trace_id,
                server_name=server_name,
                tool_name=tool_name,
                params=kwargs,
                success=False,
                error=str(e),
            )
            self._record_trace(record)
            return {
                "success": False,
                "result": None,
                "error": f"Client error: {e}",
                "trace_id": trace_id,
            }

    # -- 权限控制 --------------------------------------------------------------

    def set_tool_permission(
        self, server_name: str, tool_name: str, level: PermissionLevel
    ) -> None:
        """设置工具权限等级。

        Args:
            server_name: Server 名称。
            tool_name: 工具名称。
            level: 权限等级，支持 PermissionLevel 枚举或字符串 ('read'/'write'/'admin')。
        """
        if isinstance(level, str):
            level = PermissionLevel.from_string(level)
        self._require_permission = True
        perm_key = f"{server_name}:{tool_name}"
        self._permissions[perm_key] = level
        logger.info(
            "Set permission for '%s:%s' to %s", server_name, tool_name, level.value
        )

    def get_tool_permission(
        self, server_name: str, tool_name: str
    ) -> Optional[PermissionLevel]:
        """获取工具权限等级。"""
        return self._permissions.get(f"{server_name}:{tool_name}")

    # -- Trace 记录 ------------------------------------------------------------

    def _generate_trace_id(self) -> str:
        """生成唯一 Trace ID（线程安全）。"""
        with self._trace_lock:
            self._trace_counter += 1
            counter = self._trace_counter
        return f"trace_{counter}_{int(time.time() * 1000)}"

    def _record_trace(self, record: TraceRecord) -> None:
        """记录 Trace（线程安全）。"""
        with self._trace_lock:
            self._trace_records.append(record)
            # 控制内存
            if len(self._trace_records) > self.MAX_TRACE_HISTORY:
                self._trace_records = self._trace_records[-self.MAX_TRACE_HISTORY:]

    def get_trace_history(
        self,
        server_name: Optional[str] = None,
        tool_name: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """获取 Trace 历史记录。

        Args:
            server_name: 按 Server 过滤（可选）。
            tool_name: 按工具名过滤（可选）。
            limit: 返回记录数上限。

        Returns:
            Trace 记录列表。
        """
        records = self._trace_records
        if server_name:
            records = [r for r in records if r.server_name == server_name]
        if tool_name:
            records = [r for r in records if r.tool_name == tool_name]
        return [r.to_dict() for r in records[-limit:]]

    # -- 工具统计 --------------------------------------------------------------

    def get_tool_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有工具的调用统计。

        Returns:
            {tool_key: {count, success_rate, avg_elapsed}} 的映射。
        """
        stats: Dict[str, Dict[str, Any]] = {}
        for record in self._trace_records:
            key = f"{record.server_name}:{record.tool_name}"
            if key not in stats:
                stats[key] = {
                    "server": record.server_name,
                    "tool": record.tool_name,
                    "count": 0,
                    "success_count": 0,
                    "total_elapsed": 0.0,
                }
            s = stats[key]
            s["count"] += 1
            if record.success:
                s["success_count"] += 1
            s["total_elapsed"] += record.elapsed_seconds

        for key, s in stats.items():
            count = s["count"]
            s["success_rate"] = round(s["success_count"] / count, 4) if count > 0 else 0.0
            s["avg_elapsed"] = round(s["total_elapsed"] / count, 4) if count > 0 else 0.0
            del s["total_elapsed"]

        return stats

    # -- 生命周期 --------------------------------------------------------------

    def shutdown(self) -> None:
        """关闭所有连接。"""
        for name in list(self._servers.keys()):
            self.disconnect_server(name)
        logger.info("MCPClient shutdown complete")

    def __repr__(self) -> str:
        return (
            f"MCPClient(servers={list(self._servers.keys())}, "
            f"traces={len(self._trace_records)})"
        )
"""
MCP (Model Context Protocol) 工具系统

红岩网校 AI 部门考核项目 -- 选题一

本模块提供完整的 MCP 工具系统实现，包括：
- ToolSchema: 工具参数 Schema 定义与校验
- MCPServer: MCP Server 基类，支持工具注册、调用、超时控制
- MCPClient: MCP Client，管理多 Server 连接，统一调用接口
- ToolRegistry: 工具注册表，支持元数据统计和工具搜索
- ToolRouter: 智能工具路由器，基于任务描述动态选择工具

使用示例::

    from mcp import MCPServer, MCPClient, ToolRegistry, ToolRouter, ToolSchema
    from mcp.servers import CampusInfoServer, RepoAnalysisServer, DocSearchServer

    # 创建 Server
    campus = CampusInfoServer()
    repo = RepoAnalysisServer()

    # 创建 Client 并连接
    client = MCPClient()
    client.connect_server(campus)
    client.connect_server(repo)

    # 调用工具
    result = client.call_tool("campus-info", "search_courses", keyword="Python")
    print(result)
"""

from .schema import ToolSchema, make_tool_schema
from .server import MCPServer, MCPError, ToolNotFoundError, ToolExecutionError, ToolTimeoutError
from .client import MCPClient, PermissionLevel, TraceRecord, ToolPermissionConfig
from .registry import ToolRegistry, ToolMetadata
from .router import ToolRouter, SelectionResult

# 服务器子模块
from . import servers

__all__ = [
    # Schema
    "ToolSchema",
    "make_tool_schema",
    # Server
    "MCPServer",
    "MCPError",
    "ToolNotFoundError",
    "ToolExecutionError",
    "ToolTimeoutError",
    # Client
    "MCPClient",
    "PermissionLevel",
    "TraceRecord",
    "ToolPermissionConfig",
    # Registry
    "ToolRegistry",
    "ToolMetadata",
    # Router
    "ToolRouter",
    "SelectionResult",
    # Servers
    "servers",
]

__version__ = "1.0.0"
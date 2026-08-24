from __future__ import annotations
from typing import Any, Dict, List, Optional
from code.framework.agent_runtime import Tool
from code.framework.planner_executor import ToolRegistry
from code.framework.mcp import MCPClient
from code.workbench.csv_agent.servers import (DataLoaderServer, DataProcessorServer, VisualizerServer,
                                    ModelTrainerServer, ReportGeneratorServer, StatisticsServer, QueryServer)

def all_servers(llm_config: Optional[Dict[str, Any]] = None) -> List:
    return [DataLoaderServer(), DataProcessorServer(), VisualizerServer(),
            ModelTrainerServer(), ReportGeneratorServer(), StatisticsServer(),
            QueryServer(llm_config=llm_config)]

def connect_mcp_servers(llm_config: Optional[Dict[str, Any]] = None) -> MCPClient:
    client = MCPClient()
    for srv in all_servers(llm_config=llm_config):
        client.connect_server(srv)
    return client


class _PlannerTool:
    """包装 agent_runtime.Tool 以适应 planner_executor 的 Executor 驱动方式。

    Executor._execute_with_tool 优先把 tool 当 callable 调用：
    tool(description, metadata)（位置参数）。而 agent_runtime.Tool 是 dataclass，
    不可调用，且其 execute(**kwargs) 不接受位置参数，直接注册会被 Executor
    以 tool.execute(description, **metadata) 位置调用而抛 TypeError。

    该包装同时提供：
    - __call__(description, workspace, ...)：适配 Executor 的 callable 分支；
    - execute(description=..., params=...)：保留对直接调用
      reg.get(name).execute(description=..., params=...) 的支持（eval/orchestrator 使用）。
    """

    __slots__ = ("_tool",)

    def __init__(self, tool: Tool) -> None:
        self._tool = tool  # 底层 agent_runtime.Tool，含 .execute

    def __call__(
        self, description: str = "", workspace: str = "", params: dict = None,
        ws: str = "", **kwargs: dict
    ) -> dict:
        return self._tool.function(
            description=description, workspace=workspace, params=params, ws=ws, **kwargs
        )

    def execute(self, **kwargs: dict) -> dict:
        return self._tool.execute(**kwargs)

def build_tool_registry(llm_config: Optional[Dict[str, Any]] = None) -> ToolRegistry:
    reg = ToolRegistry()
    for srv in all_servers(llm_config=llm_config):
        for schema in srv.tools:
            handler = srv._tools[schema.name].handler
            name = schema.name
            desc = schema.description
            params_schema = schema.parameters

            def make_fn(hobj):
                def fn(description: str = "", workspace: str = "", params: dict = None,
                       ws: str = "", **kwargs) -> dict:
                    p = dict(params or {})
                    ws_val = ws or p.get("ws") or workspace
                    if not ws_val:
                        from code.workbench.csv_agent.workspace import WorkspaceContext
                        cur = WorkspaceContext.current()
                        if cur is not None:
                            ws_val = str(cur.root)
                    p["ws"] = ws_val or ""
                    return hobj(**p)
                return fn

            reg_tool = Tool(name=name, description=desc, parameters=params_schema,
                            function=make_fn(handler))
            reg.register(name=name, tool=_PlannerTool(reg_tool), description=desc)
    return reg
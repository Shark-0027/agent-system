from __future__ import annotations
from typing import List
from code.agent_runtime import Tool, ToolRegistry
from code.mcp import MCPClient
from code.csv_agent.servers import (DataLoaderServer, DataProcessorServer, VisualizerServer,
                                    ModelTrainerServer, ReportGeneratorServer)

def all_servers() -> List:
    return [DataLoaderServer(), DataProcessorServer(), VisualizerServer(),
            ModelTrainerServer(), ReportGeneratorServer()]

def connect_mcp_servers() -> MCPClient:
    client = MCPClient()
    for srv in all_servers():
        client.connect_server(srv)
    return client

def build_tool_registry() -> ToolRegistry:
    reg = ToolRegistry()
    for srv in all_servers():
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
                        from code.csv_agent.workspace import WorkspaceContext
                        cur = WorkspaceContext.current()
                        if cur is not None:
                            ws_val = str(cur.root)
                    p["ws"] = ws_val or ""
                    return hobj(**p)
                return fn

            reg.register(Tool(name=name, description=desc, parameters=params_schema,
                              function=make_fn(handler)))
    return reg
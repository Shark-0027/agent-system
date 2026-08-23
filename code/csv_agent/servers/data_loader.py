from __future__ import annotations
from pathlib import Path
from typing import Any, Dict
import pandas as pd
from code.mcp import MCPServer, ToolSchema
from code.csv_agent.workspace import Workspace

def _resolve_ws(params: Dict[str, Any]) -> Workspace:
    from code.csv_agent.workspace import WorkspaceContext
    ws_str = params.get("ws")
    if ws_str:
        return Workspace(run_id="rs", root=Path(ws_str))
    cur = WorkspaceContext.current()
    if cur is not None:
        return cur
    raise ValueError("no workspace provided: pass params['ws'] or set WorkspaceContext")

def csv_load(ws: Workspace, params: Dict[str, Any]) -> Dict[str, Any]:
    init = Path(ws.root) / "input.csv"
    if not init.exists():
        return {"success": False, "error": f"input.csv not found in {ws.root}"}
    try:
        df = pd.read_csv(init)
    except Exception as e:
        return {"success": False, "error": f"read error: {e}"}
    missing = {c: int(df[c].isna().sum()) for c in df.columns}
    info = {"success": True, "rows": int(len(df)), "cols": int(len(df.columns)),
            "columns": list(map(str, df.columns)),
            "dtypes": {c: str(df[c].dtype) for c in df.columns},
            "missing": missing,
            "sample": df.head(5).astype(object).to_dict(orient="records")}
    ws.save_json(info, "schema.json")
    return info

def data_summary(ws: Workspace, params: Dict[str, Any]) -> Dict[str, Any]:
    out = csv_load(ws, params)
    if not out["success"]:
        return out
    df = pd.read_csv(ws.root / "input.csv")
    num = df.select_dtypes(include="number")
    summary = {}
    for c in num.columns:
        s = num[c]
        summary[c] = {"mean": round(float(s.mean()),4) if not s.isna().all() else None,
                      "median": round(float(s.median()),4) if not s.isna().all() else None,
                      "min": round(float(s.min()),4) if not s.isna().all() else None,
                      "max": round(float(s.max()),4) if not s.isna().all() else None,
                      "missing": int(s.isna().sum())}
    return {"success": True, "summary": summary}

class DataLoaderServer(MCPServer):
    def __init__(self):
        super().__init__(name="data-loader", description="CSV 加载与概览")
        self.register_tool(
            schema=ToolSchema(name="csv_load",
                description="加载 CSV，返回行列数、列名、类型、样本、缺失率",
                parameters={"type":"object","properties":{"ws":{"type":"string","description":"工作区根目录"}}}),
            handler=lambda **kw: csv_load(_resolve_ws(kw), kw))
        self.register_tool(
            schema=ToolSchema(name="data_summary",
                description="数值列统计摘要与异常探针",
                parameters={"type":"object","properties":{"ws":{"type":"string","description":"工作区根目录"}}}),
            handler=lambda **kw: data_summary(_resolve_ws(kw), kw))
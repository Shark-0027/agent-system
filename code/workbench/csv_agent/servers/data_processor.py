from __future__ import annotations
from typing import Any, Dict
import pandas as pd
from code.framework.mcp import MCPServer, ToolSchema
from code.workbench.csv_agent.servers.data_loader import _resolve_ws
from code.workbench.csv_agent.workspace import Workspace

def data_clean(ws, params):
    init = ws.root / "input.csv"
    if not init.exists():
        return {"success": False, "error": "input.csv not found"}
    df = pd.read_csv(init)
    fill = params.get("fill", "median")
    records = {"filled": [], "clipped": []}
    for c in df.columns:
        missing = int(df[c].isna().sum())
        if missing == 0:
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            val = df[c].median() if fill == "median" else df[c].mean()
            df[c] = df[c].fillna(val)
            records["filled"].append({"col": c, "n": missing, "method": fill})
        else:
            mode = df[c].mode()
            df[c] = df[c].fillna(mode.iloc[0] if not mode.empty else "未知")
            records["filled"].append({"col": c, "n": missing, "method": "mode"})
    for c in df.select_dtypes(include="number").columns:
        q1, q3 = df[c].quantile(0.25), df[c].quantile(0.75)
        iqr = q3 - q1
        lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
        nlo = int((df[c] < lo).sum()); nhi = int((df[c] > hi).sum())
        if pd.notna(lo) and pd.notna(hi) and (nlo + nhi) > 0:
            df[c] = df[c].clip(lo, hi)
            records["clipped"].append({"col": c, "n": nlo + nhi})
    df = df.drop_duplicates()
    ws.save_csv(df, "cleaned.csv")
    records["rows_after"] = int(len(df))
    records["dups_removed"] = int(len(pd.read_csv(init)) - len(df))
    return {"success": True, **records}

def feature_engineer(ws, params):
    path = ws.root / "cleaned.csv"
    if not path.exists():
        return {"success": False, "error": "cleaned.csv not found, run data_clean first"}
    df = pd.read_csv(path)
    created = []
    if params.get("encode", True):
        for c in df.select_dtypes(include="object").columns:
            df[f"{c}_code"] = df[c].astype("category").cat.codes
            created.append(f"{c}_code")
            df = df.drop(columns=[c])
    if params.get("scale", True):
        for c in df.select_dtypes(include="number").columns:
            if c.endswith("_scaled"):
                continue
            s = df[c]
            if s.std() == 0 or s.isna().all():
                continue
            df[f"{c}_scaled"] = (s - s.mean()) / s.std()
            created.append(f"{c}_scaled")
    ws.save_csv(df, "cleaned.csv")
    return {"success": True, "features_added": created}

class DataProcessorServer(MCPServer):
    def __init__(self):
        super().__init__(name="data-processor", description="数据清洗与特征工程")
        self.register_tool(
            schema=ToolSchema(name="data_clean",
                description="缺失填充、类型转换、异常值处理",
                parameters={"type":"object","properties":{"ws":{"type":"string"},"fill":{"type":"string","enum":["median","mean"]}}}),
            handler=lambda **kw: data_clean(_resolve_ws(kw), kw))
        self.register_tool(
            schema=ToolSchema(name="feature_engineer",
                description="分类编码、数值标准化、组合特征生成",
                parameters={"type":"object","properties":{"ws":{"type":"string"},"encode":{"type":"boolean"},"scale":{"type":"boolean"}}}),
            handler=lambda **kw: feature_engineer(_resolve_ws(kw), kw))
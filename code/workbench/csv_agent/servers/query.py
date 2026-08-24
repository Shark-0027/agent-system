from __future__ import annotations
import json
from typing import Any, Dict, List, Optional
import pandas as pd
from code.framework.mcp import MCPServer, ToolSchema
from code.workbench.csv_agent.servers.data_loader import _resolve_ws
from code.workbench.csv_agent.workspace import Workspace


def _llm_client(llm_config: Optional[Dict[str, Any]] = None):
    try:
        from code.framework.agent_runtime import LLMClient
        return LLMClient(**(llm_config or {}))
    except Exception:
        return None


def _load_df(ws) -> Optional[pd.DataFrame]:
    path = ws.root / "cleaned.csv"
    if not path.exists():
        path = ws.root / "input.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


_SORT_KEYWORDS = {"降序": -1, "最小": 1, "最大": -1, "倒序": -1, "前n": -1}
_NUM_KEYWORDS = ["平均", "总和", "合计", "均值", "最多", "最少", "最大", "最小", "排名", "最高", "最低"]


def _parse_filter_locally(question: str, df: pd.DataFrame) -> Dict[str, Any]:
    """无 LLM 时的本地关键词回退：从问题中提取数值/名称列条件。"""
    cond = {"sort_desc": True, "limit": None, "kol": "", "过滤条件": []}
    # 选取一个数值列（含候选排序）
    ncols = list(df.select_dtypes(include="number").columns)
    obj_cols = [c for c in df.columns if c not in ncols]
    cond["kol"] = ncols[0] if ncols else (df.columns[0] if len(df.columns) else "")
    cond["sort_col"] = ncols[0] if ncols else ""
    # 简单的数值下界抽取（如“大于 100”）
    import re
    for m in re.finditer(r"(大于|超过|高于|>)\s*([0-9.]+)", question):
        for c in ncols:
            cond["过滤条件"].append({"col": c, "op": ">", "value": float(m.group(2))})
    for m in re.finditer(r"(小于|低于|少于|<)\s*([0-9.]+)", question):
        for c in ncols:
            cond["过滤条件"].append({"col": c, "op": "<", "value": float(m.group(2))})
    for m in re.finditer(r"前\s*([0-9]+)\s*名|top\s*([0-9]+)", question, re.IGNORECASE):
        n = int(m.group(1) or m.group(2))
        cond["limit"] = n
    return cond


def _prompt_columns(df: pd.DataFrame) -> str:
    ncols = list(df.select_dtypes(include="number").columns)
    return f"数值列:{ncols} 非数值列:{[c for c in df.columns if c not in ncols]}"


def _apply_filter(ws, cond: Dict[str, Any]) -> Dict[str, Any]:
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    q = df.copy()
    for f in cond.get("过滤条件") or []:
        col = f.get("col")
        op = f.get("op")
        val = f.get("value")
        if col not in q.columns or op not in (">", "<", "==", ">=", "<="):
            continue
        num = pd.to_numeric(q[col], errors="coerce")
        if op in (">", ">="):
            q = q[num >= float(val)] if op == ">=" else q[num > float(val)]
        elif op in ("<", "<="):
            q = q[num <= float(val)] if op == "<=" else q[num < float(val)]
        elif op == "==":
            q = q[num == float(val)]
    sort_col = cond.get("sort_col")
    if sort_col and sort_col in q.columns:
        q = q.sort_values(sort_col, ascending=not bool(cond.get("sort_desc", True)))
    limit = cond.get("limit")
    if limit:
        q = q.head(int(limit))
    sample = q.head(10).astype(object).where(pd.notnull(q), None).to_dict(orient="records")
    return {"success": True, "hit_rows": int(len(q)), "columns": list(q.columns), "sample": sample}


def _parse_json(content: str) -> Dict[str, Any]:
    try:
        return json.loads(content)
    except Exception:
        pass
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(content[start:end + 1])
        except Exception:
            pass
    return {}


def nl_filter(ws, params, llm=None):
    question = params.get("question", "").strip()
    if not question:
        return {"success": False, "error": "question is required"}
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    cond = {}
    used_llm = False
    if llm is not None:
        prompt = (
            "你是 CSV 数据分析助手。仅根据问题输出 JSON 筛选条件，不要多余文字。"
            f"可用列与类型：{_prompt_columns(df)}。"
            "输出格式：{\"过滤条件\":[{\"col\":\"列名\",\"op\":\"==|>|<|>=\",\"value\":数值}],"
            "\"sort_col\":\"排序列名(可为空)\",\"sort_desc\":true,\"limit\":空或整数}\n"
            f"问题：{question}"
        )
        try:
            msg = llm.chat_completion([{"role": "user", "content": prompt}], temperature=0.0)
            parsed = _parse_json(getattr(msg, "content", "") or "")
            if "过滤条件" in parsed or "sort_col" in parsed or parsed:
                cond = parsed
                used_llm = True
        except Exception:
            cond = {}
    if not cond:
        cond = _parse_filter_locally(question, df)
    res = _apply_filter(ws, cond)
    res["used_llm"] = used_llm
    ws.save_json({"question": question, "condition": cond, "result": res}, "query_filter.json")
    res["meta_file"] = str(ws.root / "query_filter.json")
    return res


def nl_insight(ws, params, llm=None):
    question = params.get("question", "").strip()
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    schema = ws.load_json("schema.json") or {}
    stats = ws.load_json("stats_hyptest.json") or ws.load_json("data_summary.json") or {}
    numeric = list(df.select_dtypes(include="number").columns)
    basic = {"rows": int(len(df)), "cols": int(len(df.columns)), "numeric_cols": numeric[:8]}
    used_llm = False
    if llm is not None:
        prompt = (
            "你是资深数据分析师。基于以下数据背景，围绕问题给出 3-5 条简洁、数据支撑的洞察。"
            "只输出中文洞察要点，用 - 列表。\n"
            f"数据概览：{basic}\n概览JSON：{dict(schema) or {}}\n统计：{dict(stats) or {}}\n问题：{question}"
        )
        try:
            msg = llm.chat_completion([{"role": "user", "content": prompt}], temperature=0.4)
            content = (getattr(msg, "content", "") or "").strip()
            if len(content) >= 10:
                used_llm = True
                ws.save_json({"question": question, "insights": content}, "query_insight.json")
                return {"success": True, "used_llm": True, "insights": content,
                        "meta_file": str(ws.root / "query_insight.json")}
        except Exception:
            pass
    fallback = [f"共 {len(df)} 行 {len(df.columns)} 列。", "已计算数值列相关性（如适用）。",
                "建议结合数据清理与可视化进一步分析。"]
    ws.save_json({"question": question, "insights": fallback}, "query_insight.json")
    return {"success": True, "used_llm": False, "insights": fallback,
            "meta_file": str(ws.root / "query_insight.json")}


def nl_agg(ws, params, llm=None):
    """自然语言分组聚合：按类目分组，对数值列做 sum/mean/count。"""
    question = params.get("question", "").strip()
    if not question:
        return {"success": False, "error": "question is required"}
    df = _load_df(ws)
    if df is None:
        return {"success": False, "error": "no csv available"}
    obj_cols = [c for c in df.columns if c not in list(df.select_dtypes(include="number").columns)]
    num_cols = list(df.select_dtypes(include="number").columns)
    if not obj_cols or not num_cols:
        return {"success": False, "error": "need both a categorical and a numeric column"}
    group = params.get("group") or obj_cols[0]
    metric = params.get("metric") or num_cols[0]
    agg = params.get("agg") or "sum"
    used_llm = False
    if llm is not None:
        prompt = (
            "你是 CSV 数据分析助手。仅输出 JSON，不要多余文字。\n"
            f"类目列:{obj_cols} 数值列:{num_cols}。聚合方式可选: sum|mean|count。\n"
            "输出格式:{\"group\":\"类目列名\",\"metric\":\"数值列名或空\",\"agg\":\"sum|mean|count\"}\n"
            f"问题：{question}"
        )
        try:
            msg = llm.chat_completion([{"role": "user", "content": prompt}], temperature=0.0)
            parsed = _parse_json(getattr(msg, "content", "") or "")
            if parsed.get("group") in df.columns:
                group = parsed["group"]
                if parsed.get("metric") in df.columns:
                    metric = parsed["metric"]
                if parsed.get("agg") in ("sum", "mean", "count"):
                    agg = parsed["agg"]
                used_llm = True
        except Exception:
            pass
    sub = df[[group] + ([metric] if metric and metric in df.columns else [])].dropna()
    if agg == "count":
        out = sub.groupby(group).size().reset_index(name="count")
    else:
        out = sub.groupby(group)[metric].agg(agg).reset_index()
    rows = out.astype(object).where(pd.notnull(out), None).to_dict(orient="records")
    res = {"group": group, "metric": metric, "agg": agg, "used_llm": used_llm,
           "rows": rows if len(rows) <= 50 else rows[:50]}
    ws.save_json({"question": question, "result": res}, "query_agg.json")
    res["meta_file"] = str(ws.root / "query_agg.json")
    return {"success": True, **res}


class QueryServer(MCPServer):
    def __init__(self, llm_config: Optional[Dict[str, Any]] = None):
        super().__init__(name="query", description="自然语言查数与其他分析")
        self._llm = _llm_client(llm_config)

        def make_filter_handler():
            llm = self._llm
            return lambda **kw: nl_filter(_resolve_ws(kw), kw, llm)

        def make_insight_handler():
            llm = self._llm
            return lambda **kw: nl_insight(_resolve_ws(kw), kw, llm)

        def make_agg_handler():
            llm = self._llm
            return lambda **kw: nl_agg(_resolve_ws(kw), kw, llm)

        self.register_tool(
            schema=ToolSchema(name="nl_filter",
                description="把自然语言问题转成筛选/排序/限量条件并返回命中数据",
                parameters={"type": "object",
                            "properties": {"ws": {"type": "string"}, "question": {"type": "string"}}}),
            handler=make_filter_handler())
        self.register_tool(
            schema=ToolSchema(name="nl_agg",
                description="自然语言分组聚合：按类目分组对数值列 sum/mean/count",
                parameters={"type": "object",
                            "properties": {"ws": {"type": "string"}, "question": {"type": "string"}}}),
            handler=make_agg_handler())
        self.register_tool(
            schema=ToolSchema(name="nl_insight",
                description="基于数据概览与统计产物生成洞察要点",
                parameters={"type": "object",
                            "properties": {"ws": {"type": "string"}, "question": {"type": "string"}}}),
            handler=make_insight_handler())
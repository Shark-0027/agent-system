from __future__ import annotations
import json
from datetime import datetime
from typing import Any, Dict, Optional
from code.framework.mcp import MCPServer, ToolSchema
from code.workbench.csv_agent.servers.data_loader import _resolve_ws
from code.workbench.csv_agent.workspace import Workspace


def _fmt(v) -> str:
    """把可能的 numpy 标量/nan/inf 归一化为可读文本。"""
    try:
        if v is None or (isinstance(v, float) and (v != v or v in (float("inf"), float("-inf")))):
            return "—"
        if hasattr(v, "item"):
            v = v.item()
        if isinstance(v, float):
            return f"{v:.4g}"
        return str(v)
    except Exception:  # noqa: BLE001
        return str(v)


def _llm_client(llm_config: Optional[Dict[str, Any]] = None):
    """构造 LLM 客户端；配置不可用时返回 None（调用方回退规则）。"""
    try:
        from code.framework.agent_runtime import LLMClient
        return LLMClient(**(llm_config or {}))
    except Exception:  # noqa: BLE001
        return None


def collect_context(ws, schema, model_metrics, charts_meta=None) -> Dict[str, Any]:
    """汇总工作区中已生成的分析产物，形成紧凑的数据背景，供 LLM / 规则共同消费。"""
    ctx: Dict[str, Any] = {"schema": schema or {}, "model": model_metrics or {}}
    for name in ("stats_corr", "stats_hyptest", "stats_timeseries", "stats_anomaly",
                 "stats_distfit", "stats_cluster", "stats_pca", "stats_regression",
                 "data_summary", "forecast", "feature_selected", "missing_pattern", "ab_test"):
        v = ws.load_json(f"{name}.json")
        if v:
            ctx[name] = v
    if charts_meta is None:
        charts = list((ws.charts_dir.glob("*.png"))) if ws.charts_dir.exists() else []
        ctx["charts"] = [c.name for c in charts]
    else:
        ctx["charts"] = charts_meta
    return ctx


def _ctx_preview(ctx: Dict[str, Any], limit: int = 3000) -> str:
    """把分析产物上下文压缩成一段紧凑文本，控制喂给 LLM 的 token 量。"""
    compact = {}
    schema = ctx.get("schema") or {}
    if schema:
        compact["数据概览"] = {k: schema.get(k) for k in ("rows", "cols", "columns", "missing", "target_hints")}
        # 列画像紧凑版
        profiles = schema.get("column_profiles", {})
        if profiles:
            compact["列画像"] = {c: {"cat": p.get("category"), "unique": p.get("unique_count", p.get("cardinality")),
                                   "skew": p.get("skewness")} for c, p in profiles.items()}
    model = ctx.get("model") or {}
    if model:
        compact["建模"] = {
            "best": model.get("best"),
            "指标": {k: {kk: _fmt(vv) for kk, vv in (v or {}).items()}
                     for k, v in (model.get("results") or {}).items()},
            "特征重要性Top": (model.get("importance") or [])[:5],
        }
    # 补全所有产物（修复此前遗漏 cluster/pca/regression + 新增产物）
    for src, label in (("stats_corr", "相关性"), ("stats_hyptest", "检验"),
                       ("stats_timeseries", "时序"), ("stats_anomaly", "离群"),
                       ("stats_distfit", "分布"), ("stats_cluster", "聚类"),
                       ("stats_pca", "PCA"), ("stats_regression", "回归"),
                       ("data_summary", "汇总"), ("forecast", "预测"),
                       ("feature_selected", "特征选择"), ("missing_pattern", "缺失模式"),
                       ("ab_test", "AB实验")):
        if ctx.get(src):
            compact[label] = ctx[src]
    if ctx.get("charts"):
        compact["图表"] = ctx["charts"]
    return json.dumps(compact, ensure_ascii=False, default=str)[:limit]


def _rule_conclusions(goal, schema, model_metrics, ctx) -> list:
    """无 LLM 时的规则兜底：基于真实统计与建模值生成结论，避免固定文案。"""
    out = []
    model = model_metrics or {}
    best = model.get("best")
    results = model.get("results") or {}
    if best and best in results:
        m = results[best]
        out.append(f"{goal} 场景下，{best} 拟合效果最佳（R²={_fmt(m.get('r2'))}，RMSE={_fmt(m.get('rmse'))}）。")
    imp = model.get("importance") or []
    if imp:
        top = imp[0]
        out.append(f"特征重要性分析表明，「{_fmt(top[0])}」对目标的贡献最大，建议优先优化该维度。")
    corr = (ctx.get("stats_corr") or {}).get("pairs") or []
    corr = sorted((p for p in corr), key=lambda x: abs(x.get("pearson", 0) or 0), reverse=True)
    if corr:
        a, b = corr[0]
        out.append(f"相关性分析发现 '{_fmt(a.get('a'))}' 与 '{_fmt(a.get('b'))}' 的相关系数为 {_fmt(a.get('pearson'))}，值得重点关注。")
    anomaly = ctx.get("stats_anomaly") or {}
    if anomaly.get("outlier_count"):
        out.append(f"共识别到 {anomaly['outlier_count']} 个离群点（{anomaly.get('col')}，阈值 {_fmt(anomaly.get('threshold'))}），建议核对是否需剔除或单独处理。")
    dist = (ctx.get("stats_distfit") or {})
    if dist.get("best"):
        out.append(f"数值列 '{_fmt(dist.get('col'))}' 的概率分布以 {dist['best']} 拟合最优，建模时可作为数据分布假设依据。")
    missing = (schema or {}).get("missing")
    if isinstance(missing, dict) and any(v for v in missing.values()):
        out.append("数据仍存在缺失值，后续分析可结合填充策略进一步提升质量。")
    if not out:
        rows = (schema or {}).get("rows")
        out.append(f"共 {rows} 行数据的初步分析已完成。")
        out.append("基于现有指标，建议进一步开展特征工程以提升模型表现。")
    out.append("以上结论由本地规则基于实际分析结果生成，接入 LLM 后将提供更全面的解读。")
    return out


def _llm_conclusions(goal, schema, model_metrics, ctx, llm) -> list:
    """LLM 优先级：让模型看到分析产物后总结结论与建议。失败/不可用则回退规则。"""
    prompt = (
        "你是资深数据分析师。根据下面的数据概览、统计与建模结果，围绕分析目标给出 3-5 条"
        "【结论与建议】，每条一句话，用精简中文，直接用数值支撑，不要客套话。\n"
        f"分析目标：{goal}\n分析产物：\n{_ctx_preview(ctx)}"
    )
    try:
        msg = llm.chat_completion([{"role": "user", "content": prompt}], temperature=0.4)
        content = (getattr(msg, "content", "") or "").strip()
        # 清洗成列表：兼容“1. xxx / - xxx”两种格式
        items = [ln.strip() for ln in content.splitlines() if ln.strip()]
        kept = []
        for ln in items:
            for pfx in ("1.", "2.", "3.", "4.", "5.", "-", "*", "·"):
                if ln.startswith(pfx):
                    ln = ln[len(pfx):].strip()
                    break
            if ln:
                kept.append(ln)
        if len(kept) >= 2:
            return kept
    except Exception:  # noqa: BLE001
        pass
    return _rule_conclusions(goal, schema, model_metrics, ctx)


def report_generate(ws, params, llm=None):
    # 优先从 params 读取 goal，其次从 goal.json（orchestrator 持久化的用户目标）
    goal = params.get("goal")
    if not goal:
        goal_data = ws.load_json("goal.json") or {}
        goal = goal_data.get("goal", "数据分析")
    schema = ws.load_json("schema.json") or {}
    model_metrics = ws.load_json("model_metrics.json") or {}
    ctx = collect_context(ws, schema, model_metrics)
    if llm is None:
        llm = _llm_client()
    lines = ["# AI 数据分析报告", "",
             f"**分析目标：** {goal}", "",
             f"**生成时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    if schema:
        lines += ["## 数据概览", "",
                  f"- 行数：{schema.get('rows')}  列数：{schema.get('cols')}",
                  f"- 数据列：{', '.join(str(c) for c in (schema.get('columns') or []))}",
                  f"- 缺失情况：{schema.get('missing', {})}", ""]
    # 探索性分析：已有统计产物全部汇入报告，避免只给模板
    if ctx.get("stats_corr") or ctx.get("stats_timeseries") or ctx.get("stats_anomaly") or ctx.get("stats_distfit"):
        lines += ["## 探索性分析", ""]
        corr = (ctx.get("stats_corr") or {}).get("pairs") or []
        if corr:
            top = sorted(corr, key=lambda x: abs(x.get("pearson", 0) or 0), reverse=True)[0]
            lines.append(f"- 相关性：相关性最高的是 `{top.get('a')}` 与 `{top.get('b')}`（r={_fmt(top.get('pearson'))}）。")
        ts = ctx.get("stats_timeseries") or {}
        if ts.get("mean") is not None:
            lines.append(f"- 时序：`{ts.get('col')}` 均值 {_fmt(ts.get('mean'))}，波动系数 CV={_fmt(ts.get('cv'))}。")
        anomaly = ctx.get("stats_anomaly") or {}
        if anomaly.get("outlier_count"):
            lines.append(f"- 离群：`{anomaly.get('col')}` 检测到 {anomaly['outlier_count']} 个离群点。")
        dist = ctx.get("stats_distfit") or {}
        if dist.get("best"):
            lines.append(f"- 分布：`{dist.get('col')}` 以 {dist['best']} 分布拟合最优。")
        lines += [""]
    if ctx.get("charts"):
        lines += ["## 可视化", "", *[f"- 图表：`{c}`" for c in ctx["charts"]], ""]
    if model_metrics:
        lines += ["## 建模与评估", ""]
        best = model_metrics.get("best", "")
        if best:
            lines.append(f"- 最优模型：**{best}**")
        for name, m in (model_metrics.get("results") or {}).items():
            lines.append(f"- `{name}`：RMSE={_fmt(m.get('rmse'))}  R²={_fmt(m.get('r2'))}")
        imp = model_metrics.get("importance") or []
        if imp:
            lines += ["", "### 特征重要性", ""]
            for k, v in imp[:5]:
                lines.append(f"- `{k}`：{_fmt(v)}")
        lines += [""]
    lines += ["## 结论与建议", ""]
    # 结论条目已去除序号前缀，统一以 “1.” 开头，markdown 会按有序列表正确编号
    for c in _llm_conclusions(goal, schema, model_metrics, ctx, llm):
        lines.append(f"1. {c}")
    lines += [""]
    ws.report_md.write_text("\n".join(lines), encoding="utf-8")
    return {"success": True, "report": str(ws.report_md)}


class ReportGeneratorServer(MCPServer):
    def __init__(self, llm_config: Optional[Dict[str, Any]] = None):
        super().__init__(name="report-generator", description="生成分析报告")
        self._llm = _llm_client(llm_config)

        def make_report_handler():
            llm = self._llm
            return lambda **kw: report_generate(_resolve_ws(kw), kw, llm)

        self.register_tool(
            schema=ToolSchema(name="report_generate",
                description="汇总各阶段产物生成 Markdown 报告",
                parameters={"type":"object","properties":{"ws":{"type":"string"},"goal":{"type":"string"},"models":{"type":"string"}}}),
            handler=make_report_handler())
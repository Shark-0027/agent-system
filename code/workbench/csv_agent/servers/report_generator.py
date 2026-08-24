from __future__ import annotations
from datetime import datetime
from typing import Any, Dict
from code.framework.mcp import MCPServer, ToolSchema
from code.workbench.csv_agent.servers.data_loader import _resolve_ws
from code.workbench.csv_agent.workspace import Workspace

def report_generate(ws, params):
    goal = params.get("goal", "数据分析")
    schema = ws.load_json("schema.json") or {}
    model_metrics = ws.load_json("model_metrics.json") or {}
    charts = ws.load_json("charts_meta.json") or []
    lines = ["# AI 数据分析报告", "",
             f"**分析目标：** {goal}", "",
             f"**生成时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}", ""]
    if schema:
        lines += ["## 数据概览", "",
                  f"- 行数：{schema.get('rows')}  -  列数：{schema.get('cols')}",
                  f"- 数据列：{', '.join(schema.get('columns', []))}",
                  f"- 缺失情况：{schema.get('missing', {})}", ""]
    if charts:
        lines += ["## 探索性分析", "",
                  "![图表](charts/)  *请查看 workspace 的 charts/ 目录*", ""]
    if model_metrics:
        lines += ["## 建模与评估", ""]
        best = model_metrics.get("best", "")
        lines.append(f"- 最优模型：**{best}**")
        for name, m in (model_metrics.get("results") or {}).items():
            lines.append(f"- `{name}`：RMSE={m.get('rmse')}  R2={m.get('r2')}")
        imp = model_metrics.get("importance") or []
        if imp:
            lines += ["", "### 特征重要性", ""]
            for k, v in imp[:5]:
                lines.append(f"- `{k}`：{v}")
        lines += [""]
    lines += ["## 结论与建议", "",
               "1. 依据特征重要性优先优化高影响指标。",
               "2. 建议在更大样本上交叉验证。", ""]
    ws.report_md.write_text("\n".join(lines), encoding="utf-8")
    return {"success": True, "report": str(ws.report_md)}

class ReportGeneratorServer(MCPServer):
    def __init__(self):
        super().__init__(name="report-generator", description="生成分析报告")
        self.register_tool(
            schema=ToolSchema(name="report_generate",
                description="汇总各阶段产物生成 Markdown 报告",
                parameters={"type":"object","properties":{"ws":{"type":"string"},"goal":{"type":"string"},"models":{"type":"string"}}}),
            handler=lambda **kw: report_generate(_resolve_ws(kw), kw))
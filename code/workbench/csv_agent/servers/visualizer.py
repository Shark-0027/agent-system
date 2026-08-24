from __future__ import annotations
import json
import os
import tempfile
from typing import Any, Dict
# 强制把 matplotlib 缓存指向可写临时目录，避免沙箱/受限用户目录报错
os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "mplconfig"))
import matplotlib
matplotlib.use("Agg")
from matplotlib import font_manager
import matplotlib.pyplot as plt
import pandas as pd


def _setup_cjk_font() -> None:
    """优先选用系统中文字体，避免图表标题/坐标轴中文乱码。"""
    candidates = ["Microsoft YaHei", "SimHei", "SimSun", "PingFang SC",
                  "Noto Sans CJK SC", "WenQuanYi Zen Hei", "AR PL UMing CN"]
    installed = {f.name for f in font_manager.fontManager.ttflist}
    for name in candidates:
        if name in installed:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            break
    else:
        # 未发现中文字体：提示而非报错，缺字时回退默认字体
        import logging
        logging.getLogger("csv_agent.visualizer").warning(
            "未找到中文字体，图表中文可能显示为方框。可安装 Noto Sans CJK 等字体。")


_setup_cjk_font()
plt.rcParams["axes.unicode_minus"] = False  # 负号正常显示
from code.framework.mcp import MCPServer, ToolSchema
from code.workbench.csv_agent.servers.data_loader import _resolve_ws
from code.workbench.csv_agent.workspace import Workspace

def _hist_for(df, col, path):
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(df[col].dropna(), bins=20, color="#4c8bf5", edgecolor="white")
    ax.set_title(f"{col} 分布")
    fig.tight_layout(); fig.savefig(path, dpi=90); plt.close(fig)
    return {"kind": "hist", "col": col}

def eda_plot(ws, params):
    path = ws.root / ("cleaned.csv" if (ws.root / "cleaned.csv").exists() else "input.csv")
    if not path.exists():
        return {"success": False, "error": "no csv available"}
    df = pd.read_csv(path)
    kind = params.get("kind", "all")
    charts = []
    num_cols = df.select_dtypes(include="number").columns
    if kind in ("hist", "all"):
        for c in num_cols[:3]:
            p = ws.charts_dir / f"hist_{c}.png"
            charts.append(_hist_for(df, c, str(p)))
    if kind in ("corr", "all") and len(num_cols) >= 2:
        corr = df[num_cols].corr()
        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(corr.values, cmap="coolwarm", aspect="auto")
        ax.set_xticks(range(len(num_cols))); ax.set_xticklabels(num_cols, rotation=45, ha="right")
        ax.set_yticks(range(len(num_cols))); ax.set_yticklabels(num_cols)
        fig.colorbar(im); fig.tight_layout()
        p = ws.charts_dir / "corr.png"
        fig.savefig(p, dpi=90); plt.close(fig)
        charts.append({"kind": "corr", "cols": list(num_cols)})
    meta = ws.save_json(charts, "charts_meta.json")
    return {"success": True, "charts": charts, "meta_file": meta}

class VisualizerServer(MCPServer):
    def __init__(self):
        super().__init__(name="visualizer", description="EDA 可视化")
        self.register_tool(
            schema=ToolSchema(name="eda_plot",
                description="生成分布图/箱线图/相关性热力图",
                parameters={"type":"object","properties":{"ws":{"type":"string"},"kind":{"type":"string","enum":["hist","corr","all"]}}}),
            handler=lambda **kw: eda_plot(_resolve_ws(kw), kw))
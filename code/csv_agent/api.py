"""CSV 数据分析 Agent 的 FastAPI 接口。

启动: uvicorn code.csv_agent.api:app --reload

提供工作台相关端点：上传/生成样例、分步执行底层工具、产物预览与下载、
一键全流程分析、历史与偏好管理。前端单页由 / 与 /web 提供。
"""
from __future__ import annotations

import io
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from fastapi import Body, File, Form, Query, UploadFile
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from code.csv_agent.bridge import build_tool_registry
from code.csv_agent.datagen import gen_sales
from code.csv_agent.memory import MemoryStore
from code.csv_agent.orchestrator import CsvAgent
from code.csv_agent.workspace import Workspace, WorkspaceContext

app = FastAPI(title="CSV 数据分析 Agent 工作台")

_memory = MemoryStore()
_tools = build_tool_registry()
# run_id -> workspace 根目录（工作区产物均落在其下）
_runs: Dict[str, Any] = {}


def _run_root(rid: str) -> Path:
    root = _runs.get(rid)
    if not root or not isinstance(root, Path) or not root.is_dir():
        raise HTTPException(404, f"run not found: {rid}")
    return root


def _safe_file(root: Path, name: str) -> Path:
    """解析工作区内的文件名，阻止路径穿越。"""
    if not name:
        raise HTTPException(400, "missing file name")
    p = (root / name).resolve()
    if not p.is_relative_to(root.resolve()):
        raise HTTPException(400, "invalid file name")
    return p


def _jsonable(v: Any) -> Any:
    """把 numpy 标量与 nan/inf 归一化为 JSON 安全值。"""
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return None
    if hasattr(v, "item"):
        try:
            return _jsonable(v.item())
        except (ValueError, AttributeError):
            return v
    return v


def _clean(obj: Any) -> Any:
    """递归清理结构中的非 JSON 安全值。"""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    return _jsonable(obj)


def _preview(root: Path) -> Dict[str, Any]:
    """读取 input.csv/cleaned.csv 返回样例预览（NaN 归一化为 None 以兼容 JSON）。"""
    path = root / ("cleaned.csv" if (root / "cleaned.csv").exists() else "input.csv")
    if not path.exists():
        return {"success": False, "error": "no csv available"}
    df = pd.read_csv(path)
    sample = [[_jsonable(v) for v in row] for row in df.head(10).astype(object).values]
    columns = list(map(str, df.columns))
    return {"success": True, "rows": int(len(df)), "cols": int(len(df.columns)),
            "columns": columns,
            "sample": [dict(zip(columns, row)) for row in sample]}


# ---------------------------------------------------------------------------
# 页面与静态资源
# ---------------------------------------------------------------------------
_WEB_DIR = Path(__file__).parent / "web"


@app.get("/", response_class=FileResponse)
def index():
    return _WEB_DIR / "index.html"


app.mount("/web", StaticFiles(directory=_WEB_DIR), name="web")


# ---------------------------------------------------------------------------
# 系统状态
# ---------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# 数据接入：上传 / 生成样例
# ---------------------------------------------------------------------------
def _create_run(df: pd.DataFrame) -> Dict[str, Any]:
    ws = Workspace.create()
    ws.save_csv(df, "input.csv")
    _runs[ws.run_id] = ws.root
    return {"run_id": ws.run_id, "root": str(ws.root)}


@app.post("/api/run")
def upload(file: UploadFile = File(...)):
    """上传 CSV 并新建一个运行（含数据表预览）。"""
    raw = file.file.read()
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"invalid csv: {e}")
    meta = _create_run(df)
    meta["data"] = _preview(Path(meta["root"]))
    return meta


@app.get("/api/sample")
def sample():
    """生成样例销量数据并新建一个运行，供分步操作演示。"""
    df = gen_sales(dirty=True)
    meta = _create_run(df)
    meta["data"] = _preview(Path(meta["root"]))
    return meta


# ---------------------------------------------------------------------------
# 运行管理
# ---------------------------------------------------------------------------
@app.get("/api/runs")
def list_runs():
    """列出所有运行及其基本信息。"""
    out = []
    for rid, root in _runs.items():
        out.append({"run_id": rid, "root": str(root),
                    "has_report": (root / "report.md").exists(),
                    "has_cleaned": (root / "cleaned.csv").exists(),
                    "n_charts": len(list((root / "charts").glob("*.png"))) if (root / "charts").exists() else 0})
    out.sort(key=lambda r: r["run_id"], reverse=True)
    return {"runs": out}


@app.get("/api/run/{rid}/info")
def run_info(rid: str):
    root = _run_root(rid)
    return {"run_id": rid, "root": str(root),
            "has_report": (root / "report.md").exists(),
            "has_cleaned": (root / "cleaned.csv").exists(),
            "schema": root.joinpath("schema.json").read_text(encoding="utf-8") if (root / "schema.json").exists() else None}


@app.get("/api/run/{rid}/data")
def run_data(rid: str, which: str = Query("auto", description="auto|input|cleaned")):
    if which != "auto":
        if which not in ("input", "cleaned"):
            raise HTTPException(400, "which must be input|cleaned|auto")
        path = _run_root(rid) / f"{which}.csv"
        if not path.exists():
            raise HTTPException(404, f"{which}.csv not found")
    result = _preview(_run_root(rid))
    if not result.get("success"):
        raise HTTPException(404, result.get("error", "no data"))
    return result


# ---------------------------------------------------------------------------
# 分步工具执行
# ---------------------------------------------------------------------------
@app.get("/api/tools")
def list_tool_names():
    """列出可用的分析工具（前端据此渲染分步按钮）。"""
    return {"tools": _tools.list_tools()}


@app.post("/api/run/{rid}/tool")
def run_tool(rid: str, body: Dict[str, Any] = Body(...)):
    """在当前运行上执行单个分析工具。"""
    root = _run_root(rid)
    tool_name = body.get("tool", "")
    params = body.get("params") or {}
    tool = _tools.get(tool_name) if tool_name else None
    if tool is None:
        raise HTTPException(404, f"tool not found: {tool_name}")
    ws = Workspace(run_id=rid, root=root)
    WorkspaceContext.push(ws)
    try:
        result = tool.execute(description=tool_name, params={**params, "ws": str(root)})
    finally:
        WorkspaceContext.pop()
    if isinstance(result, dict):
        result.setdefault("success", True)
        result["tool"] = tool_name
    else:
        result = {"success": False, "tool": tool_name, "error": result}
    return _clean(result)


# ---------------------------------------------------------------------------
# 一键全流程分析
# ---------------------------------------------------------------------------
@app.post("/api/analyze")
def analyze(goal: str = Form(...), file: UploadFile = File(...)):
    ws = Workspace.create()
    raw = file.file.read()
    df = pd.read_csv(io.BytesIO(raw))
    ws.save_csv(df, "input.csv")
    _runs[ws.run_id] = ws.root
    try:
        agent = CsvAgent(use_llm=True, memory=_memory)
    except Exception:  # noqa: BLE001 无 LLM key 时回退本地模式
        agent = CsvAgent(use_llm=False, memory=_memory)
    out = agent.analyze(ws, goal)
    return {
        "success": out.get("success"),
        "run_id": ws.run_id,
        "report": str(ws.report_md),
        "error": out.get("error"),
    }


# ---------------------------------------------------------------------------
# 结果查看：报表 / 图表 / 下载
# ---------------------------------------------------------------------------
def _report_text_or_none(rid: str) -> Optional[str]:
    root = _runs.get(rid)
    if not root or not isinstance(root, Path):
        return None
    p = root / "report.md"
    if not p.exists():
        return None
    return p.read_text(encoding="utf-8")


@app.get("/api/report/{run_id}", response_class=PlainTextResponse)
def report(run_id: str):
    text = _report_text_or_none(run_id)
    if text is None:
        raise HTTPException(404, "report not found")
    return text


@app.get("/api/run/{rid}/charts")
def run_charts(rid: str):
    root = _run_root(rid)
    out = []
    for p in sorted((root / "charts").glob("*.png")):
        out.append({"name": p.name, "kind": "hist" if p.stem.startswith("hist_") else "corr",
                    "url": f"/api/run/{rid}/chart?name={p.name}"})
    return {"charts": out}


@app.get("/api/run/{rid}/chart")
def run_chart(rid: str, name: str = Query(...)):
    root = _run_root(rid)
    p = (root / "charts" / name).resolve()
    if not p.is_relative_to((root / "charts").resolve()) or not p.exists():
        raise HTTPException(404, "chart not found")
    return FileResponse(str(p), media_type="image/png")


@app.get("/api/run/{rid}/download")
def run_download(rid: str, name: str = Query(...)):
    """下载工作区内的产物文件（报告/CSV/JSON）。"""
    root = _run_root(rid)
    p = _safe_file(root, name)
    if not p.exists():
        raise HTTPException(404, f"file not found: {name}")
    return FileResponse(str(p), filename=name)


# ---------------------------------------------------------------------------
# 历史与偏好（Agent Memory）
# ---------------------------------------------------------------------------
@app.get("/api/history")
def history(keyword: str = Query("")):
    return {"history": _memory.lookup_history(keyword, limit=20)}


@app.get("/api/preferences")
def get_preferences():
    return {"preferences": _memory.all_preferences()}


@app.put("/api/preferences")
def set_preferences(preferences: Dict[str, Any] = Body(...)):
    prefs = preferences.get("preferences") or preferences
    for k, v in prefs.items():
        _memory.set_preference(k, v)
    return {"preferences": _memory.all_preferences()}
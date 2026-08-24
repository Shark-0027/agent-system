"""CSV 数据分析 Agent 的 FastAPI 接口。

启动: uvicorn code.workbench.csv_agent.api:app --reload

提供工作台相关端点：上传/生成样例、分步执行底层工具、产物预览与下载、
一键全流程分析、历史与偏好管理。前端单页由 / 与 /web 提供。
"""
from __future__ import annotations

import io
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd
from fastapi import Body, File, Form, Query, UploadFile
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from code.workbench.csv_agent.bridge import build_tool_registry
from code.workbench.csv_agent.datagen import gen_sales
from code.workbench.csv_agent.memory import MemoryStore
from code.workbench.csv_agent.orchestrator import CsvAgent
from code.workbench.csv_agent.workspace import Workspace, WorkspaceContext
from code.framework.agent_runtime import LLMClient

app = FastAPI(title="CSV 数据分析 Agent 工作台")

_memory = MemoryStore(str(Path(tempfile.gettempdir()) / "csv_agent_memory.db"))
# run_id -> workspace 根目录（工作区产物均落在其下）
_runs: Dict[str, Any] = {}
# 内存中保留的运行数上限，超限时清理最旧运行与其工作区目录，防止长期运行内存/磁盘泄漏
_MAX_RUNS = 200
# 首次确定后缓存的服务运行模式（"llm"|"local"）
_MODE_CACHE: Optional[str] = None
# 前端通过 /api/llm/config 传入的 LLM 覆盖配置（api_key/base_url/model_name）。
# 为 None 时后端使用 .env 中的默认配置，不硬编码。
_LLM_OVERRIDE: Optional[Dict[str, Optional[str]]] = None

# 允许在 /api/llm/config 中设置的前端字段（白名单，避免任意键注入）
_LLM_FIELDS = ("api_key", "base_url", "model_name")

# 工具注册表在 LLM 配置确定后构建（QueryServer 需要用到 LLM 配置穿透）
_tools = build_tool_registry(llm_config=_LLM_OVERRIDE)


def _rebuild_tools() -> None:
    """LLM 覆盖配置变更后重建工具注册表，使查询服务及时采用新的 LLM 配置。"""
    global _tools
    _tools = build_tool_registry(llm_config=_LLM_OVERRIDE)


def _trim_runs() -> None:
    """当运行数超过上限时，移除最旧的一批并清理对应工作区目录。"""
    while len(_runs) > _MAX_RUNS:
        oldest_id, oldest_root = next(iter(_runs.items()))
        _runs.pop(oldest_id, None)
        if isinstance(oldest_root, Path):
            shutil.rmtree(oldest_root, ignore_errors=True)


def _build_agent() -> Dict[str, Any]:
    """构造编排 Agent，并报告实际采用的运行模式。

    优先使用 LLM 模式（use_llm=True）。LLM 客户端配置优先取前端传入的
    /api/llm/config 覆盖，未覆盖字段回退 .env 默认；当最终因缺少 api_key 等
    导致 LLMClient 初始化失败时，回退到本地规则模式（use_llm=False）。
    返回 {"agent": CsvAgent, "mode": "llm"|"local"}。
    """
    try:
        return {
            "agent": CsvAgent(use_llm=True, memory=_memory, llm_config=_LLM_OVERRIDE),
            "mode": "llm",
        }
    except Exception:  # noqa: BLE001 无 LLM key 时回退本地模式
        return {"agent": CsvAgent(use_llm=False, memory=_memory), "mode": "local"}


def _resolve_mode() -> str:
    """当前服务实际可用的运行模式（不创建 Agent，缓存首次结果）。"""
    global _MODE_CACHE
    if _MODE_CACHE is None:
        _MODE_CACHE = _build_agent()["mode"]
    return _MODE_CACHE


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
    mode = _resolve_mode()
    return {"status": "ok", "mode": mode,
            "mode_label": "LLM 自动编排" if mode == "llm" else "本地规则模式"}


# ---------------------------------------------------------------------------
# LLM 配置（前端传入 key/base_url/模型名，后端据此构建 LLM 客户端）
# ---------------------------------------------------------------------------
@app.get("/api/llm/config")
def get_llm_config():
    """读取当前 LLM 配置（不回显 api_key，避免泄露凭据）。"""
    cfg = _LLM_OVERRIDE or {}
    try:
        llm = LLMClient(**cfg)
        model, base_url = llm.model_name, llm.base_url or "默认"
    except Exception:  # noqa: BLE001 配置不可用时给出占位
        model, base_url = None, None
    return {
        "configured": bool(cfg),
        "using_env_defaults": not cfg,
        "model": model,
        "base_url": base_url,
        "mode": _resolve_mode(),
    }


@app.post("/api/llm/config")
def set_llm_config(body: Dict[str, Any] = Body(...)):
    """设置前端传入的 LLM 配置并据此构建/校验 LLM 客户端。

    body 仅接受白名单字段 {api_key, base_url, model_name}；
    传空或省略表示清除覆盖、回退使用 .env 默认配置。不可硬编码。
    """
    global _MODE_CACHE, _LLM_OVERRIDE

    override: Dict[str, str] = {}
    for field in _LLM_FIELDS:
        value = body.get(field)
        if value and str(value).strip():
            override[field] = str(value).strip()

    # 用新配置构造 LLM 客户端校验是否可用（构造级校验，不发起网络请求）
    try:
        llm = LLMClient(**override)
        ok, err = True, None
        model, base_url = llm.model_name, llm.base_url or "默认"
    except Exception as e:  # noqa: BLE001
        ok, err = False, str(e)
        model, base_url = None, None

    _LLM_OVERRIDE = override or None
    # 配置变更后失效模式缓存，下次请求（/api/health 等）重新探测
    _MODE_CACHE = None
    # LLM 配置变动后重建工具注册表，让查询服务采用最新配置
    _rebuild_tools()

    return {
        "success": ok,
        "error": err,
        "configured": _LLM_OVERRIDE is not None,
        "using_env_defaults": _LLM_OVERRIDE is None,
        "model": model,
        "base_url": base_url,
        "mode": _resolve_mode(),
    }


# ---------------------------------------------------------------------------
# 数据接入：上传 / 生成样例
# ---------------------------------------------------------------------------
def _create_run(df: pd.DataFrame) -> Dict[str, Any]:
    ws = Workspace.create()
    ws.save_csv(df, "input.csv")
    _runs[ws.run_id] = ws.root
    _trim_runs()
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
    try:
        df = pd.read_csv(io.BytesIO(raw))
    except Exception as e:  # noqa: BLE001 非 CSV 内容统一返回 400
        raise HTTPException(400, f"invalid csv: {e}")
    ws.save_csv(df, "input.csv")
    _runs[ws.run_id] = ws.root
    _trim_runs()
    built = _build_agent()
    out = built["agent"].analyze(ws, goal)
    return {
        "success": out.get("success"),
        "run_id": ws.run_id,
        "report": str(ws.report_md),
        "error": out.get("error"),
        "mode": built["mode"],
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


@app.get("/api/run/{rid}/bundle")
def run_bundle(rid: str):
    """打包运行的全部产物为 Zip（报告/CSV/JSON/图表）。"""
    import zipfile
    root = _run_root(rid)
    buf = io.BytesIO()
    files = sorted(f for f in root.rglob("*") if f.is_file())
    if not files:
        raise HTTPException(404, "no artifacts to bundle")
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.relative_to(root).as_posix())
    buf.seek(0)
    name = f"{rid}_artifacts.zip"
    return Response(content=buf.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})


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
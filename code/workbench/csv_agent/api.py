"""CSV 数据分析 Agent 的 FastAPI 接口。

启动: uvicorn code.workbench.csv_agent.api:app --reload

提供工作台相关端点：上传/生成样例、分步执行底层工具、产物预览与下载、
一键全流程分析、历史与偏好管理。前端单页由 / 与 /web 提供。
"""
from __future__ import annotations

import io
import json
import shutil
import tempfile
import threading
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
from code.workbench.csv_agent.servers.report_generator import collect_context
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

# 全流程分析目标为空时的默认目标：让"不填也能分析"有合理的语义兜底
_DEFAULT_GOAL = "对这份数据进行全面的探索性分析，识别关键趋势与异常，并生成可视化报告"

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


# run_id -> 后台异步分析的实时状态（可观测性进度推送数据源）
_ANALYZE_STATE: Dict[str, Dict[str, Any]] = {}


def _analyze_background(rid: str, goal: str) -> None:
    """在后台线程执行一次全流程分析，并实时刷新 _ANALYZE_STATE 供 /progress 轮询。"""
    _ANALYZE_STATE[rid] = {"status": "running", "goal": goal, "error": None}
    try:
        built = _build_agent()
        out = built["agent"].analyze(Workspace(run_id=rid, root=_run_root(rid)), goal)
        _ANALYZE_STATE[rid].update({
            "status": "done",
            "success": bool(out.get("success") == True),
            "mode": built["mode"],
        })
    except Exception as e:  # noqa: BLE001 客户端只关心最终状态与错误信息
        _ANALYZE_STATE[rid].update({"status": "failed", "error": str(e)})


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


def _preview(root: Path, path: Optional[Path] = None) -> Dict[str, Any]:
    """读取指定 CSV（缺省自动选择 cleaned/input）返回样例预览（NaN 归一化为 None）。"""
    p = path or root / ("cleaned.csv" if (root / "cleaned.csv").exists() else "input.csv")
    if not p.exists():
        return {"success": False, "error": "no csv available"}
    df = pd.read_csv(p)
    sample = [[_jsonable(v) for v in row] for row in df.head(10).astype(object).values]
    columns = list(map(str, df.columns))
    return {"success": True, "rows": int(len(df)), "cols": int(len(df.columns)),
            "columns": columns,
            "sample": [dict(zip(columns, row)) for row in sample]}


# ---------------------------------------------------------------------------
# 页面与静态资源
# ---------------------------------------------------------------------------
_WEB_DIR = Path(__file__).parent / "web"


@app.middleware("http")
async def _no_cache_web(request, call_next):
    """前端页面与静态资源禁用缓存，避免浏览器加载旧版 js/css 导致功能不一致。"""
    resp = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/web"):
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        resp.headers["Pragma"] = "no-cache"
        resp.headers["Expires"] = "0"
    return resp


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
def _run_meta(root: Path) -> Dict[str, Any]:
    """从工作区提取运行元数据，供列表与详情使用。"""
    trace: Dict[str, Any] = {}
    trace_path = root / "trace.json"
    if trace_path.exists():
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    title = trace.get("goal") or rid_from_root(root)
    return {
        "title": title,
        "created_at": int(root.stat().st_ctime),
        "mode": trace.get("mode") or _resolve_mode(),
    }


def rid_from_root(root: Path) -> str:
    return root.name


@app.get("/api/runs")
def list_runs():
    """列出所有运行及其基本信息。"""
    out = []
    for rid, root in _runs.items():
        meta = _run_meta(root)
        out.append({
            "run_id": rid,
            "title": meta["title"],
            "created_at": meta["created_at"],
            "mode": meta["mode"],
            "has_report": (root / "report.md").exists(),
            "has_cleaned": (root / "cleaned.csv").exists(),
            "n_charts": len(list((root / "charts").glob("*.png"))) if (root / "charts").exists() else 0,
        })
    out.sort(key=lambda r: r["created_at"], reverse=True)
    return {"runs": out}


@app.get("/api/run/{rid}/info")
def run_info(rid: str):
    root = _run_root(rid)
    meta = _run_meta(root)
    preview = _preview(root)
    return {
        "run_id": rid,
        "title": meta["title"],
        "rows": preview.get("rows", 0),
        "cols": preview.get("cols", 0),
        "has_report": (root / "report.md").exists(),
        "has_cleaned": (root / "cleaned.csv").exists(),
        "schema": root.joinpath("schema.json").read_text(encoding="utf-8") if (root / "schema.json").exists() else None,
    }


@app.get("/api/run/{rid}/data")
def run_data(rid: str, which: str = Query("auto", description="auto|input|cleaned")):
    if which not in ("auto", "input", "cleaned"):
        raise HTTPException(400, "which must be input|cleaned|auto")
    path = None
    if which != "auto":
        path = _run_root(rid) / f"{which}.csv"
    result = _preview(_run_root(rid), path)
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
# 全流程异步分析（基于既有 run）+ 进度轮询 + 执行轨迹
# ---------------------------------------------------------------------------
def _suggest_goals(rid: str) -> Dict[str, Any]:
    """基于已上传数据的 schema 推断可执行的分析方向，帮助用户提供分析目标。

    读取 input.csv 头部判断数值/时间/类别列，据此给出 3-4 条目标建议。
    即使读不到 CSV，也会给出通用的综合报告建议，保证前端始终有可选目标。
    """
    root = _run_root(rid)
    schema = Workspace(run_id=rid, root=root).load_json("schema.json") or {}
    rows = schema.get("rows")
    suggestions = []
    numeric_cols, time_cols, cat_cols = [], [], []
    p = root / "input.csv"
    if p.exists():
        try:
            df = pd.read_csv(p, nrows=100)
            for c in df.columns:
                col = str(c)
                low = col.lower()
                if any(k in low for k in ("date", "time", "year", "month", "日", "时间", "年", "月")) or pd.api.types.is_datetime64_any_dtype(df[c]):
                    time_cols.append(col)
                elif pd.api.types.is_numeric_dtype(df[c]):
                    numeric_cols.append(col)
                elif c is not None:
                    cat_cols.append(col)
        except Exception:  # noqa: BLE001 读不到时仅用列名兜底
            pass
    if time_cols:
        suggestions.append(f"📈 趋势分析：分析「{time_cols[0]}」随时间的变化趋势，识别增长或下滑拐点")
    if numeric_cols:
        suggestions.append(f"📐 分布分析：分析数值列（如 {numeric_cols[0]}）的分布特征并拟合最优分布")
        suggestions.append("🔍 异常检测：识别数据中的离群点与异常值，分析其成因")
    if len(numeric_cols) >= 2:
        suggestions.append(f"🤝 多因素分析：找出影响「{numeric_cols[-1]}」的关键因素并构建回归模型")
    if cat_cols:
        suggestions.append(f"🧩 特征画像：对比不同「{cat_cols[0]}」类别下的分布差异")
    if rows is not None:
        suggestions.append(f"📊 综合报告：对 {rows} 行数据进行全面探索性分析并生成报告")
    if not suggestions:
        suggestions.append("📊 综合报告：对这份数据进行全面探索性分析并生成报告")
    return {"success": True, "suggestions": suggestions[:4]}


@app.get("/api/run/{rid}/suggest-goals")
def run_suggest_goals(rid: str):
    """根据该次运行的数据推断可执行的分析目标建议，供前端一键选用。"""
    return _suggest_goals(rid)


@app.post("/api/run/{rid}/analyze")
def run_analyze(rid: str, goal: str = Form(""), async_mode: bool = Query(False)):
    """在既有运行上执行全流程分析。

    goal 可为空：空时使用默认目标，保证"不填也能分析"。
    async_mode=True 时后台线程执行，通过 /api/run/{rid}/progress 轮询进度；
    否则同步返回结果（兼容旧调用）。无 LLM 时回退本地规则模式。
    """
    goal = (goal or "").strip() or _DEFAULT_GOAL
    root = _run_root(rid)
    if async_mode:
        threading.Thread(
            target=_analyze_background, args=(rid, goal), daemon=True
        ).start()
        return {"started": True, "run_id": rid}
    built = _build_agent()
    out = built["agent"].analyze(Workspace(run_id=rid, root=root), goal)
    return {
        "success": out.get("success"),
        "run_id": rid,
        "report": str(Workspace(run_id=rid, root=root).report_md),
        "error": out.get("error"),
        "mode": built["mode"],
    }


@app.get("/api/run/{rid}/progress")
def run_progress(rid: str):
    """查询一次异步全流程分析的实时进度（无记录时返回 idle）。"""
    st = _ANALYZE_STATE.get(rid)
    if not st:
        return {"status": "idle"}
    return st


@app.get("/api/run/{rid}/trace")
def run_trace(rid: str):
    """返回一次分析的结构化执行轨迹（规划/调度/工具事件与耗时）。"""
    root = _run_root(rid)
    p = root / "trace.json"
    if not p.exists():
        raise HTTPException(404, "trace not found")
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/api/run/{rid}/llm-mode")
def run_llm_mode(rid: str):
    """单次运行实际采用的 LLM 模式（llm|local）。"""
    return {"mode": _resolve_mode()}


@app.post("/api/analyze")
def analyze(goal: str = Form(""), file: UploadFile = File(...)):
    goal = (goal or "").strip() or _DEFAULT_GOAL
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


# ---------------------------------------------------------------------------
# 数据答疑对话：基于单次运行的分析产物回答问题（LLM 优先 + 规则兜底）
# ---------------------------------------------------------------------------
def _rule_chat_answer(question: str, ctx: Dict[str, Any]) -> str:
    """无 LLM 时用规则基于真实产物回答，命中关键词即引用对应产物。"""
    q = question or ""
    chunks = []
    schema = ctx.get("schema") or {}
    model = ctx.get("model") or {}

    if any(k in q for k in ("分布", "正态", "服从", "概率")):
        dist = ctx.get("stats_distfit") or {}
        if dist.get("best"):
            chunks.append(f"`{dist.get('col')}` 的最优拟合分布是 {dist['best']}（KS 检验p={dist.get('results',[{}])[0].get('p_value') if dist.get('results') else '—'}）。")
    if any(k in q for k in ("离群", "异常", "极端", "outlier")):
        anom = ctx.get("stats_anomaly") or {}
        if anom.get("outlier_count"):
            chunks.append(f"`{anom.get('col')}` 检测到 {anom['outlier_count']} 个离群点（z 阈值为 {anom.get('threshold')}）。")
    if any(k in q for k in ("相关", "关系", "相互作用", "联动")):
        corr = ctx.get("stats_corr") or {}
        pairs = sorted((corr.get("pairs") or []), key=lambda x: abs(x.get("pearson", 0) or 0), reverse=True)
        if pairs:
            p = pairs[0]
            chunks.append(f"相关性最高的是 `{p.get('a')}` 与 `{p.get('b')}`，皮尔逊 r={p.get('pearson')}。")
    if any(k in q for k in ("缺失", "空值", "多少空")):
        missing = schema.get("missing")
        if isinstance(missing, dict):
            chunks.append(f"数据缺失情况：{missing}")
    if any(k in q for k in ("特征", "重要", "关键因素", "哪些因素", "影响最大")):
        imp = model.get("importance") or []
        if imp:
            top = imp[0]
            chunks.append(f"特征重要性最高的是 `{top[0]}`（{top[1]}），对目标贡献最大。")
    if any(k in q for k in ("模型", "拟合", "指标", "R2", "评估", "效果如何")):
        best = model.get("best")
        results = model.get("results") or {}
        if best:
            m = results.get(best) or {}
            chunks.append(f"当前最优模型为 {best}（R²={m.get('r2')}，RMSE={m.get('rmse')}）。")
    if any(k in q for k in ("多少行", "几行", "规模", "概览", "多少列", "几列", "数据结构", "有哪些列", "列名")):
        if schema.get("rows") is not None:
            chunks.append(f"数据共 {schema.get('rows')} 行、{schema.get('cols')} 列；列：{', '.join(str(c) for c in (schema.get('columns') or [])[:8])}。")

    if chunks:
        return "\n".join(chunks)
    return ("当前未检测到与问题直接对应的分析结果。可尝试询问：哪些特征最影响目标、"
            "数据分布/有无离群、列间相关性、缺失情况等。")


@app.post("/api/run/{rid}/chat")
def run_chat(rid: str, body: Dict[str, Any] = Body(...)):
    """基于该次运行的分析产物回答用户的自然语言问题。

    LLM 可用时让模型看到产物与报告后作答；否则回退本地规则基于真实数值回答。
    """
    root = _run_root(rid)
    workspace = Workspace(run_id=rid, root=root)
    question = str((body.get("question") or "")).strip()
    if not question:
        raise HTTPException(400, "question is required")
    schema = workspace.load_json("schema.json") or {}
    model = workspace.load_json("model_metrics.json") or {}
    ctx = collect_context(workspace, schema, model)

    # LLM 优先：把分析产物 + 现有报告一起给模型，让它基于数据回答
    llm = None
    reason = None
    reason_code = None
    try:
        llm = LLMClient(**(dict(_LLM_OVERRIDE or {})))
    except Exception:  # noqa: BLE001 无可用配置则走规则，并向前端说明原因
        reason = ("当前未配置可用的 LLM（缺少或无效的 API Key / Base URL / 模型名），"
                  "本次已回退为本地规则应答。解决办法：点击右上角「LLM 配置」填写有效配置，或检查服务端 .env。")
        reason_code = "no_llm"
    used_llm = False
    if llm is not None:
        report_txt = ""
        p = root / "report.md"
        if p.exists():
            report_txt = p.read_text(encoding="utf-8")[:1500]
        from code.workbench.csv_agent.servers.report_generator import _ctx_preview
        prompt = (
            "你是这份 CSV 数据分析结果的解答助手。请依据下面的数据分析产物与报告，"
            "用简洁中文回答用户问题；若产物不足以回答，请明确说明缺少哪方面数据。不要编造数值。\n"
            f"分析产物：\n{_ctx_preview(ctx)}\n"
            f"已生成报告：\n{report_txt}\n"
            f"用户问题：{question}"
        )
        try:
            msg = llm.chat_completion([{"role": "user", "content": prompt}], temperature=0.2)
            content = (getattr(msg, "content", "") or "").strip()
            if len(content) >= 10:
                used_llm = True
                return _clean({"success": True, "answer": content, "used_llm": True,
                               "reason": None, "reason_code": None})
        except Exception as e:  # noqa: BLE001 LLM 调用失败回退规则，并向前端说明原因
            detail = str(e)[:180]
            reason = (f"LLM 调用失败：{detail}。已回退为本地规则应答。"
                      "解决办法：检查 API 配额/余额是否充足（如 429），或更换 Base URL / 模型后再次提问。")
            reason_code = "llm_error"
    answer = _rule_chat_answer(question, ctx)
    return _clean({"success": True, "answer": answer, "used_llm": used_llm,
                   "reason": reason, "reason_code": reason_code})


# 工具结果解释：LLM 根据工具名和返回数据生成通俗易懂的中文说明
_TOOL_LABELS = {
    "data_clean": "数据清洗", "feature_engineer": "特征工程", "data_quality": "数据质量体检",
    "corr_analysis": "相关性分析", "hypo_test": "假设检验", "regression_fit": "回归拟合",
    "time_series_feat": "时间序列分析", "cluster_profile": "聚类分析", "anomaly_detect": "离群点检测",
    "dist_fit": "分布拟合", "pca_decompose": "主成分分析",
    "model_suggest": "模型建议", "model_train": "模型训练", "model_classify": "模型分类",
}


@app.post("/api/run/{rid}/explain")
def run_explain(rid: str, body: Dict[str, Any] = Body(...)):
    """让 LLM 根据工具执行结果生成通俗中文解释。

    前端在工具执行后把 tool_name 和 result 发过来，后端构造 prompt 调 LLM。
    LLM 不可用时回退为简短规则提示。
    """
    tool_name = str(body.get("tool") or "")
    tool_result = body.get("result") or {}
    label = _TOOL_LABELS.get(tool_name, tool_name)

    # 构造 LLM prompt
    import json as _json
    result_str = _json.dumps(tool_result, ensure_ascii=False, default=str)[:2000]
    prompt = (
        f"你是数据分析助手。用户刚执行了「{label}」工具，以下是工具返回的结果数据（JSON）。\n"
        "请用简洁通俗的中文（2-4句话）解释这个结果说明了什么，重点回答：\n"
        "1. 关键数值代表什么含义\n"
        "2. 结果好还是不好，有什么值得关注的地方\n"
        "3. 如果适用，给出下一步建议\n"
        "不要罗列原始数值，要解读。不要编造数据。\n"
        f"工具返回数据：\n{result_str}"
    )

    llm = None
    try:
        llm = LLMClient(**(dict(_LLM_OVERRIDE or {})))
    except Exception as e:
        return _clean({"success": True,
                       "explain": f"「{label}」执行完成。LLM 初始化失败：{str(e)[:120]}",
                       "used_llm": False})

    if llm is not None:
        try:
            msg = llm.chat_completion([{"role": "user", "content": prompt}], temperature=0.3)
            content = (getattr(msg, "content", "") or "").strip()
            if len(content) >= 10:
                return _clean({"success": True, "explain": content, "used_llm": True})
        except Exception as e:
            return _clean({"success": True,
                           "explain": f"「{label}」执行完成。LLM 调用失败：{str(e)[:120]}",
                           "used_llm": False})

    # LLM 不可用时回退
    return _clean({"success": True,
                   "explain": f"「{label}」执行完成。LLM 未配置或调用失败，无法生成详细解读。请在「LLM 配置」中设置有效的 API Key 后重试。",
                   "used_llm": False})


@app.get("/api/run/{rid}/charts")
def run_charts(rid: str):
    root = _run_root(rid)
    out = []
    for p in sorted((root / "charts").glob("*.png")):
        out.append({"name": p.name,
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
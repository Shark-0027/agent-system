"""CSV 数据分析 Agent 的 FastAPI 接口。启动: uvicorn code.csv_agent.api:app --reload"""
import io
import os

import pandas as pd
from fastapi import File, Form, UploadFile
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse

from code.csv_agent.memory import MemoryStore
from code.csv_agent.orchestrator import CsvAgent
from code.csv_agent.workspace import Workspace

app = FastAPI(title="CSV 数据分析 Agent API")

_memory = MemoryStore()
_run_map: dict[str, str] = {}


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/analyze")
def analyze(goal: str = Form(...), file: UploadFile = File(...)):
    ws = Workspace.create()
    raw = file.file.read()
    df = pd.read_csv(io.BytesIO(raw))
    ws.save_csv(df, "input.csv")
    try:
        agent = CsvAgent(use_llm=True, memory=_memory)
    except Exception:  # noqa: BLE001 无 LLM key 时回退本地模式
        agent = CsvAgent(use_llm=False, memory=_memory)
    out = agent.analyze(ws, goal)
    _run_map[ws.run_id] = str(ws.report_md)
    return {
        "success": out.get("success"),
        "run_id": ws.run_id,
        "report": str(ws.report_md),
        "error": out.get("error"),
    }


@app.get("/api/report/{run_id}", response_class=PlainTextResponse)
def report(run_id: str):
    path = _run_map.get(run_id, "")
    if not path or not os.path.exists(path):
        return "report not found"
    with open(path, encoding="utf-8") as f:
        return f.read()
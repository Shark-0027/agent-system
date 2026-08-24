from __future__ import annotations
import json, tempfile, uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
_WS_BASE = Path(tempfile.gettempdir()) / "csv_agent_workspaces"

@dataclass
class Workspace:
    run_id: str
    root: Path
    @classmethod
    def create(cls, run_id=None, base=None):
        run_id = run_id or uuid.uuid4().hex[:12]
        root = (base or _WS_BASE) / run_id
        (root / "charts").mkdir(parents=True, exist_ok=True)
        return cls(run_id=run_id, root=root)
    @property
    def input_csv(self): return self.root / "input.csv"
    @property
    def cleaned_csv(self): return self.root / "cleaned.csv"
    @property
    def charts_dir(self): return self.root / "charts"
    @property
    def report_md(self): return self.root / "report.md"
    @property
    def trace_file(self): return self.root / "trace.json"
    def save_csv(self, df, name="input.csv"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        return str(path)
    def load_csv(self, name="input.csv"):
        import pandas as pd
        return pd.read_csv(self.root / name)
    def save_json(self, data, name):
        path = self.root / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(path)
    def load_json(self, name):
        path = self.root / name
        if not path.exists(): return None
        return json.loads(path.read_text(encoding="utf-8"))
    def as_ctx(self, params=None):
        return {"workspace": str(self.root), "params": params or {}}

class WorkspaceContext:
    """进程级当前工作区上下文。

    注意：PlannerExecutor 的 Scheduler 会在工作线程中执行工具，因此该上下文
    必须跨线程可见，不能使用 thread-local。并发隔离由调用方显式传 params['ws']
    保证（bridge.make_fn 优先用 params['ws']/workspace 解析，context 仅为兜底）。
    """
    _current = None

    @classmethod
    def push(cls, ws):
        cls._current = ws

    @classmethod
    def pop(cls):
        cls._current = None

    @classmethod
    def current(cls):
        return cls._current
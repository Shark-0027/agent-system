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
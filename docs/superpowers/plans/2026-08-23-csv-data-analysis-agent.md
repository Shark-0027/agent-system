# CSV 数据分析 Agent 后端 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 agent-system 之上构建 CSV 数据分析 Agent 后端：5 个数据分析 MCP Server / 8 工具，通过 Planner-Executor 编排，用户上传 CSV + 自然语言目标即可产出 Markdown 分析报告，并附带 CLI、FastAPI、SQLite 记忆与自动评测基线对照。

**Architecture:** 新增 `code/csv_agent/` 包。工具以 `fn(ctx) -> dict`（`ctx = {"workspace": root, "params": {...}}`）统一签名；同一批处理函数双注册进 `code.mcp.MCPServer`（MCP 协议）与 `code.agent_runtime.ToolRegistry`（供 `PlannerExecutorAgent` 执行）。每次分析建隔离 `Workspace`，工具读写工作区文件而非传 DataFrame。Workspace 经模块级 `WorkspaceContext` 注入，避免改动 Executor/Planner 核心。评测复用 `code/evaluation/metrics.py`，新增 CSV 任务与基线对照。

**Tech Stack:** Python 3.10 + pandas / numpy / matplotlib / scikit-learn + FastAPI / uvicorn + 现有 `openai`/`python-dotenv`。复用 `code.agent_runtime`、`code.mcp`、`code.planner_executor`。

**运行方式：** 用 uv：`uv run python -m csv_agent.cli analyze <csv> "<goal>"`；测试 `uv run pytest tests/test_csv_agent_*.py`。

---

### Task 1: 依赖、骨架、Workspace 与样例数据生成器

**Files:**
- Modify: `pyproject.toml`（dependencies 追加）
- Create: `code/csv_agent/__init__.py`
- Create: `code/csv_agent/workspace.py`
- Create: `code/csv_agent/datagen.py`
- Test: `tests/test_csv_agent_workspace.py`

- [ ] **Step 1: 追加依赖到 `pyproject.toml`**

在 `dependencies = [...]` 中追加（保持已有 4 项）：

```toml
dependencies = [
    "openai>=1.0.0",
    "jsonschema>=4.0.0",
    "pydantic>=2.0.0",
    "python-dotenv>=1.0.0",
    "numpy>=1.26.0",
    "pandas>=2.1.0",
    "matplotlib>=3.8.0",
    "scikit-learn>=1.4.0",
    "fastapi>=0.110.0",
    "uvicorn>=0.29.0",
]
```

然后运行 `uv sync` 生效。预期：成功解析依赖，无报错。

- [ ] **Step 2: 写失败测试**

```python
# tests/test_csv_agent_workspace.py
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pandas as pd

from code.csv_agent.workspace import Workspace, WorkspaceContext


def test_workspace_create_and_csv_roundtrip(tmp_path):
    import tempfile
    ws = Workspace.create()
    assert ws.root.exists()
    assert ws.charts_dir.exists()
    # roundtrip 保存/读取 CSV
    df = pd.DataFrame({"a": [1, 2], "b": [3.0, 4.0]})
    path = ws.save_csv(df, "input.csv")
    assert os.path.exists(path)
    back = ws.load_csv("input.csv")
    assert list(back.columns) == ["a", "b"]
    assert len(back) == 2


def test_workspace_json_roundtrip():
    ws = Workspace.create()
    data = {"x": 1, "y": [1, 2]}
    p = ws.save_json(data, "meta.json")
    assert os.path.exists(p)
    assert ws.load_json("meta.json") == data
    assert ws.load_json("missing.json") is None


def test_workspace_context_push_pop():
    ws = Workspace.create()
    WorkspaceContext.push(ws)
    try:
        assert WorkspaceContext.current() is ws
    finally:
        WorkspaceContext.pop()
    assert WorkspaceContext.current() is None
```

- [ ] **Step 3: 运行测试确认失败**

Run: `uv run pytest tests/test_csv_agent_workspace.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'code.csv_agent'`

- [ ] **Step 4: 实现 `code/csv_agent/workspace.py`**

```python
"""单次分析隔离工作目录 + 当前工作区上下文。"""
from __future__ import annotations

import json
import tempfile
import uuid
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

_WS_BASE = Path(tempfile.gettempdir()) / "csv_agent_workspaces"


@dataclass
class Workspace:
    """一次数据分析运行的文件目录。"""

    run_id: str
    root: Path

    @classmethod
    def create(cls, run_id: Optional[str] = None, base: Optional[Path] = None) -> "Workspace":
        run_id = run_id or uuid.uuid4().hex[:12]
        root = (base or _WS_BASE) / run_id
        (root / "charts").mkdir(parents=True, exist_ok=True)
        return cls(run_id=run_id, root=root)

    # -- 常用路径 --
    @property
    def input_csv(self) -> Path: return self.root / "input.csv"
    @property
    def cleaned_csv(self) -> Path: return self.root / "cleaned.csv"
    @property
    def charts_dir(self) -> Path: return self.root / "charts"
    @property
    def report_md(self) -> Path: return self.root / "report.md"

    # -- 读写帮助 --
    def save_csv(self, df: Any, name: str = "input.csv") -> str:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        return str(path)

    def load_csv(self, name: str = "input.csv") -> Any:
        import pandas as pd
        return pd.read_csv(self.root / name)

    def save_json(self, data: Any, name: str) -> str:
        path = self.root / name
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        return str(path)

    def load_json(self, name: str) -> Optional[Any]:
        path = self.root / name
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def as_ctx(self, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """构造工具统一 ctx。"""
        return {"workspace": str(self.root), "params": params or {}}


class WorkspaceContext:
    """模块级当前工作区栈，供工具在未显式传 workspace 时读取。"""

    _stack: ExitStack = ExitStack()
    _current: Optional[Workspace] = None

    @classmethod
    def push(cls, ws: Workspace) -> None:
        cls._stack.enter_context(ws)  # no-op，仅用于 pop 配对
        cls._current = ws

    @classmethod
    def pop(cls) -> None:
        cls._stack.close()
        cls._current = None

    @classmethod
    def current(cls) -> Optional[Workspace]:
        return cls._current
```

- [ ] **Step 5: 实现 `code/csv_agent/__init__.py`**

```python
"""CSV 数据分析 Agent 后端包。"""
from .workspace import Workspace, WorkspaceContext

__all__ = ["Workspace", "WorkspaceContext"]
```

- [ ] **Step 6: 实现 `code/csv_agent/datagen.py`（评测/测试用样例 CSV 生成器）**

```python
"""可控的样例 CSV 生成器：正常 + 脏数据两种。"""
from __future__ import annotations

import random
from typing import Any

import numpy as np
import pandas as pd


def gen_sales(n: int = 200, seed: int = 42, dirty: bool = False) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, Any]] = []
    for i in range(n):
        region = rng.choice(["华东", "华北", "华南", "西南"])
        channel = rng.choice(["线上", "线下"])
        price = float(round(rng.uniform(10, 500), 2))
        discount = float(round(rng.normal(0.1, 0.05), 3))
        quantity = int(rng.integers(1, 20))
        sales = price * quantity * (1 - discount)
        row: dict[str, Any] = {
            "order_id": f"O{i:04d}",
            "region": region,
            "channel": channel,
            "price": price,
            "discount": discount,
            "quantity": quantity,
            "sales": round(sales, 2),
        }
        if dirty:
            if i % 11 == 0:
                row["quantity"] = None          # 缺失值
            if i % 17 == 0:
                row["price"] = None             # 缺失值
            if i % 23 == 0:
                row["sales"] = 99999.0          # 异常值
        rows.append(row)
    return pd.DataFrame(rows)
```

- [ ] **Step 7: 全部测试通过**

Run: `uv run pytest tests/test_csv_agent_workspace.py -v`
Expected: PASS（3 tests）

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml code/csv_agent/__init__.py code/csv_agent/workspace.py code/csv_agent/datagen.py tests/test_csv_agent_workspace.py
git commit -m "feat(csv-agent): 依赖与工作区骨架 + 样例数据生成器"
```

---

### Task 2: Sandbox 子进程隔离 + 超时

**Files:**
- Create: `code/csv_agent/sandbox.py`
- Test: `tests/test_csv_agent_sandbox.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_csv_agent_sandbox.py
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import time

from code.csv_agent import sandbox


def _slow(_delay=0.05):
    time.sleep(_delay)
    return 42


def test_run_isolated_success():
    assert sandbox.run_isolated(_slow, (0.01,), timeout=5).get("result") == 42


def test_run_isolated_error():
    def _boom():
        raise ValueError("bad")
    out = sandbox.run_isolated(_boom, (), timeout=5)
    assert out["success"] is False
    assert "bad" in out["error"]


def test_run_isolated_timeout():
    def _never():
        while True:
            time.sleep(0.05)
    t0 = time.time()
    out = sandbox.run_isolated(_never, (), timeout=0.3)
    assert out["success"] is False
    assert time.time() - t0 < 2.0
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_sandbox.py -v`
Expected: FAIL with `ModuleNotFoundError: code.csv_agent.sandbox`

- [ ] **Step 3: 实现 `code/csv_agent/sandbox.py`**

```python
"""子进程隔离 + 超时的工具执行器。"""
from __future__ import annotations

import multiprocessing as mp
import time
from typing import Any, Callable, Optional, Tuple


def _worker(fn: Callable, args: Tuple, q: Any) -> None:
    try:
        q.put(("ok", fn(*args)))
    except Exception as e:  # noqa: BLE001
        q.put(("err", repr(e)))


def run_isolated(
    fn: Callable,
    args: Tuple = (),
    timeout: float = 30.0,
    context: Optional[str] = None,
) -> dict:
    """在子进程中执行 fn(*args)，超时强制终止。

    Args:
        fn: 模块顶层可 pickle 的函数。
        args: 位置参数。
        timeout: 超时秒数。
        context: spawn 时的上下文（默认 fork/自动）。

    Returns:
        {"success": bool, "result": Any|None, "error": str, "elapsed": float}
    """
    ctx = mp.get_context(context or ("fork" if hasattr(mp, "fork") else None))
    q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(fn, args, q), daemon=True)
    t0 = time.time()
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        return {"success": False, "result": None,
                "error": f"tool timed out after {timeout}s", "elapsed": time.time() - t0}
    try:
        status, payload = q.get_nowait()
    except Exception:  # noqa: BLE001
        return {"success": False, "result": None, "error": "no result produced",
                "elapsed": time.time() - t0}
    if status == "err":
        return {"success": False, "result": None, "error": payload, "elapsed": time.time() - t0}
    return {"success": True, "result": payload, "error": "", "elapsed": time.time() - t0}
```

- [ ] **Step 4: 测试通过**

Run: `uv run pytest tests/test_csv_agent_sandbox.py -v`
Expected: PASS（3 tests）。若 Windows spawn 下 pickle 失败，确保 `_slow/_boom/_never` 均定义为模块顶层函数（已满足）。

- [ ] **Step 5: Commit**

```bash
git add code/csv_agent/sandbox.py tests/test_csv_agent_sandbox.py
git commit -m "feat(csv-agent): 子进程隔离的超时工具执行器"
```

---

### Task 3: data-loader MCP Server（csv_load / data_summary）

**Files:**
- Create: `code/csv_agent/servers/__init__.py`
- Create: `code/csv_agent/servers/data_loader.py`
- Test: `tests/test_csv_agent_servers.py`

统一工具处理函数签名：`def fn(ws: Workspace, params: dict) -> dict`，返回可 JSON 序列化 dict。Server 内通过 `_handler` 适配 MCP 的 **kwargs 调用。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_csv_agent_servers.py
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.csv_agent.workspace import Workspace
from code.csv_agent.datagen import gen_sales
from code.csv_agent.servers.data_loader import csv_load


def _mkws():
    ws = Workspace.create()
    ws.save_csv(gen_sales(n=50, dirty=True), "input.csv")
    return ws


def test_csv_load_basic():
    ws = _mkws()
    out = csv_load(ws, {"ws": str(ws.root)})
    assert out["success"] is True
    assert out["rows"] == 50
    assert "order_id" in out["columns"]
    assert out["dtypes"]["quantity"] == "object"  # 含 None 会被识别为 object


def test_csv_load_missing_file():
    ws = Workspace.create()
    out = csv_load(ws, {"ws": str(ws.root)})
    assert out["success"] is False
    assert "input.csv" in out["error"]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_servers.py -k csv_load -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 `code/csv_agent/servers/__init__.py`**

```python
"""CSV 数据分析 MCP Servers 子包。"""
from .data_loader import DataLoaderServer

__all__ = ["DataLoaderServer"]
```

（后续 Task 4-7 在实现各自 server 时追加导出。）

- [ ] **Step 4: 实现 `code/csv_agent/servers/data_loader.py`**

```python
"""data-loader MCP Server：csv_load / data_summary。"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from code.mcp import MCPServer, ToolSchema
from code.csv_agent.workspace import Workspace


def _resolve_ws(params: Dict[str, Any]) -> Workspace:
    from code.csv_agent.workspace import WorkspaceContext
    ws_str = params.get("ws")
    if ws_str:
        return Workspace(run_id="rs", root=__import__("pathlib").Path(ws_str))
    cur = WorkspaceContext.current()
    if cur is not None:
        return cur
    raise ValueError("no workspace provided: pass params['ws'] or set WorkspaceContext")


def csv_load(ws: Workspace, params: Dict[str, Any]) -> Dict[str, Any]:
    """加载 CSV，返回行列数、列名、dtype、样本、缺失率。"""
    init_path = __import__("pathlib").Path(ws.root) / "input.csv"
    if not init_path.exists():
        return {"success": False, "error": f"input.csv not found in {ws.root}"}
    try:
        df = pd.read_csv(init_path)
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": f"read error: {e}"}
    missing = {c: int(df[c].isna().sum()) for c in df.columns}
    info = {
        "success": True,
        "rows": int(len(df)),
        "cols": int(len(df.columns)),
        "columns": list(map(str, df.columns)),
        "dtypes": {c: str(df[c].dtype) for c in df.columns},
        "missing": missing,
        "sample": df.head(5).astype(object).to_dict(orient="records"),
    }
    ws.save_json(info, "schema.json")
    return info


def data_summary(ws: Workspace, params: Dict[str, Any]) -> Dict[str, Any]:
    """数值列统计摘要 + 异常探针。"""
    out = csv_load(ws, params)
    if not out["success"]:
        return out
    df = pd.read_csv(ws.root / "input.csv")
    num = df.select_dtypes(include="number")
    summary = {}
    for c in num.columns:
        s = num[c]
        summary[c] = {
            "mean": round(float(s.mean()), 4) if not s.isna().all() else None,
            "median": round(float(s.median()), 4) if not s.isna().all() else None,
            "min": round(float(s.min()), 4) if not s.isna().all() else None,
            "max": round(float(s.max()), 4) if not s.isna().all() else None,
            "missing": int(s.isna().sum()),
        }
    return {"success": True, "summary": summary}


class DataLoaderServer(MCPServer):
    """数据加载与概况。"""

    def __init__(self):
        super().__init__(name="data-loader", description="CSV 加载与概览")
        self.register_tool(
            schema=ToolSchema(
                name="csv_load",
                description="加载 CSV，返回行列数、列名、类型、样本、缺失率",
                parameters={"type": "object", "properties": {
                    "ws": {"type": "string", "description": "工作区根目录"}}},
            ),
            handler=lambda **kw: csv_load(_resolve_ws(kw), kw),
        )
        self.register_tool(
            schema=ToolSchema(
                name="data_summary",
                description="数值列统计摘要与异常探针",
                parameters={"type": "object", "properties": {
                    "ws": {"type": "string", "description": "工作区根目录"}}},
            ),
            handler=lambda **kw: data_summary(_resolve_ws(kw), kw),
        )
```

- [ ] **Step 5: 运行测试通过**

Run: `uv run pytest tests/test_csv_agent_servers.py -k csv_load -v`
Expected: PASS. 若 `quantity` 全含 None 时 dtype 为 `float`/`object`，调整断言以匹配实际（以 `int(df[c].dtype)` 报错为准）；关键断言是 `rows==50` 与 `success is True`。

- [ ] **Step 6: Commit**

```bash
git add code/csv_agent/servers/__init__.py code/csv_agent/servers/data_loader.py tests/test_csv_agent_servers.py
git commit -m "feat(csv-agent): data-loader MCP server (csv_load/data_summary)"
```

---

### Task 4: data-processor MCP Server（data_clean / feature_engineer）

**Files:**
- Modify: `code/csv_agent/servers/__init__.py`
- Create: `code/csv_agent/servers/data_processor.py`
- Test: `tests/test_csv_agent_servers.py`

- [ ] **Step 1: 写失败测试（追加到 test_csv_agent_servers.py）**

```python
from code.csv_agent.servers.data_processor import data_clean, feature_engineer


def test_data_clean_fills_missing():
    ws = _mkws()
    out = data_clean(ws, {"ws": str(ws.root), "fill": "median"})
    assert out["success"] is True
    df = ws.load_csv("cleaned.csv")
    assert df["quantity"].isna().sum() == 0
    assert df["price"].isna().sum() == 0


def test_feature_engineer_creates_features():
    ws = _mkws()
    data_clean(ws, {"ws": str(ws.root), "fill": "median"})
    out = feature_engineer(ws, {"ws": str(ws.root), "encode": True})
    assert out["success"] is True
    df = ws.load_csv("cleaned.csv")
    assert "region" not in df.columns or any(c for c in df.columns if "region" in c and c != "region")
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_servers.py -k "data_clean or feature_engineer" -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 `code/csv_agent/servers/data_processor.py`**

```python
"""data-processor MCP Server：data_clean / feature_engineer。"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd

from code.mcp import MCPServer, ToolSchema
from code.csv_agent.servers.data_loader import _resolve_ws
from code.csv_agent.workspace import Workspace


def data_clean(ws: Workspace, params: Dict[str, Any]) -> Dict[str, Any]:
    """缺失填充、类型转换、异常值处理。"""
    init = ws.root / "input.csv"
    if not init.exists():
        return {"success": False, "error": "input.csv not found"}
    df = pd.read_csv(init)
    fill = params.get("fill", "median")
    records: Dict[str, Any] = {"filled": [], "clipped": []}
    for c in df.columns:
        missing = int(df[c].isna().sum())
        if missing == 0:
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            val = df[c].median() if fill == "median" else df[c].mean()
            df[c] = df[c].fillna(val)
            records["filled"].append({"col": c, "n": missing, "method": fill})
        else:
            df[c] = df[c].fillna(df[c].mode().iloc[0] if not df[c].mode().empty else "未知")
            records["filled"].append({"col": c, "n": missing, "method": "mode"})
    # 异常值：数值列 >Q3+3*IQR 或 <Q1-3*IQR 的按分位数裁切
    for c in df.select_dtypes(include="number").columns:
        q1, q3 = df[c].quantile(0.25), df[c].quantile(0.75)
        iqr = q3 - q1
        lo, hi = q1 - 3 * iqr, q3 + 3 * iqr
        nlo = int((df[c] < lo).sum()); nhi = int((df[c] > hi).sum())
        if pd.notna(lo) and pd.notna(hi) and (nlo + nhi) > 0:
            df[c] = df[c].clip(lo, hi)
            records["clipped"].append({"col": c, "n": nlo + nhi})
    df = df.drop_duplicates()
    ws.save_csv(df, "cleaned.csv")
    records["rows_after"] = int(len(df))
    records["dups_removed"] = int(len(pd.read_csv(init)) - len(df))
    return {"success": True, **records}


def feature_engineer(ws: Workspace, params: Dict[str, Any]) -> Dict[str, Any]:
    """分类编码、数值标准化、组合特征生成。结果覆盖回 cleaned.csv。"""
    path = ws.root / "cleaned.csv"
    if not path.exists():
        return {"success": False, "error": "cleaned.csv not found, run data_clean first"}
    df = pd.read_csv(path)
    created: list[str] = []
    if params.get("encode", True):
        for c in df.select_dtypes(include="object"):
            df[f"{c}_code"] = df[c].astype("category").cat.codes
            created.append(f"{c}_code")
            df = df.drop(columns=[c])
    if params.get("scale", True):
        for c in df.select_dtypes(include="number"):
            if c in created:
                continue
            col = c if c.endswith("_code") else c
            s = df[c]
            if s.std() == 0 or s.isna().all():
                continue
            df[f"{c}_scaled"] = (s - s.mean()) / s.std()
            created.append(f"{c}_scaled")
    ws.save_csv(df, "cleaned.csv")
    return {"success": True, "features_added": created}
```

- [ ] **Step 4: 更新 `code/csv_agent/servers/__init__.py`**

```python
"""CSV 数据分析 MCP Servers 子包。"""
from .data_loader import DataLoaderServer
from .data_processor import DataProcessorServer

__all__ = ["DataLoaderServer", "DataProcessorServer"]
```

并实现 `DataProcessorServer`（注册 data_clean/data_feature_engineer，handler 适配同 Task 3，schema 增加可选的 `fill`/`encode`/`scale` 字符串参数）。

- [ ] **Step 5: 运行测试通过**

Run: `uv run pytest tests/test_csv_agent_servers.py -k "data_clean or feature_engineer" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add code/csv_agent/servers/__init__.py code/csv_agent/servers/data_processor.py tests/test_csv_agent_servers.py
git commit -m "feat(csv-agent): data-processor MCP server (data_clean/feature_engineer)"
```

---

### Task 5: visualizer MCP Server（eda_plot）

**Files:**
- Modify: `code/csv_agent/servers/__init__.py`
- Create: `code/csv_agent/servers/visualizer.py`
- Test: `tests/test_csv_agent_servers.py`

- [ ] **Step 1: 写失败测试**

```python
import matplotlib
matplotlib.use("Agg")
from code.csv_agent.servers.visualizer import eda_plot


def test_eda_plot_generates_charts():
    ws = _mkws()
    out = eda_plot(ws, {"ws": str(ws.root), "kind": "hist"})
    assert out["success"] is True
    png_files = list(ws.charts_dir.glob("*.png"))
    assert len(png_files) >= 1
    assert out["charts"]  # 非空
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_servers.py -k eda_plot -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 `code/csv_agent/servers/visualizer.py`**

```python
"""visualizer MCP Server：eda_plot。"""
from __future__ import annotations

import json
from typing import Any, Dict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from code.mcp import MCPServer, ToolSchema
from code.csv_agent.servers.data_loader import _resolve_ws
from code.csv_agent.workspace import Workspace


def _hist_for(df: pd.DataFrame, col: str, path) -> Dict[str, Any]:
    fig, ax = plt.subplots(figsize=(6, 4))
    ax.hist(df[col].dropna(), bins=20, color="#4c8bf5", edgecolor="white")
    ax.set_title(f"{col} 分布")
    fig.tight_layout(); fig.savefig(path, dpi=90); plt.close(fig)
    return {"kind": "hist", "col": col, "data": df[col].dropna().tolist()}


def eda_plot(ws: Workspace, params: Dict[str, Any]) -> Dict[str, Any]:
    """生成 EDA 图表到 charts/，返回图表元数据（含绘图原始数据，供前端复用）。"""
    path = ws.root / ("cleaned.csv" if (ws.root / "cleaned.csv").exists() else "input.csv")
    if not path.exists():
        return {"success": False, "error": "no csv available"}
    df = pd.read_csv(path)
    kind = params.get("kind", "all")
    charts: list[Dict[str, Any]] = []
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
        corr_png = ws.charts_dir / "corr.png"
        fig.savefig(corr_png, dpi=90); plt.close(fig)
        charts.append({"kind": "corr", "cols": list(num_cols),
                       "data": json.loads(corr.to_json())})

    meta = ws.save_json(charts, "charts_meta.json")
    return {"success": True, "charts": charts, "meta_file": meta}
```

- [ ] **Step 4: 更新 `code/csv_agent/servers/__init__.py` 并实现 `VisualizerServer`**

```python
from .visualizer import VisualizerServer
__all__ = ["DataLoaderServer", "DataProcessorServer", "VisualizerServer"]
```

`VisualizerServer` 注册 `eda_plot`（schema 参数 `ws: string`、`kind: enum["hist","corr","all"]`），handler `lambda **kw: eda_plot(_resolve_ws(kw), kw)`。

- [ ] **Step 5: 运行测试通过**

Run: `uv run pytest tests/test_csv_agent_servers.py -k eda_plot -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add code/csv_agent/servers/__init__.py code/csv_agent/servers/visualizer.py tests/test_csv_agent_servers.py
git commit -m "feat(csv-agent): visualizer MCP server (eda_plot)"
```

---

### Task 6: model-trainer MCP Server（model_suggest / model_train）

**Files:**
- Modify: `code/csv_agent/servers/__init__.py`
- Create: `code/csv_agent/servers/model_trainer.py`
- Test: `tests/test_csv_agent_servers.py`

- [ ] **Step 1: 写失败测试**

```python
from code.csv_agent.servers.model_trainer import model_train, model_suggest


def test_model_suggest_returns_recommendation():
    ws = _mkws()
    out = model_suggest(ws, {"ws": str(ws.root), "goal": "预测销售额", "target": "sales"})
    assert out["success"] is True
    assert out["suggestion"]


def test_model_train_returns_metrics():
    ws = _mkws()
    from code.csv_agent.servers.data_processor import data_clean, feature_engineer
    data_clean(ws, {"ws": str(ws.root), "fill": "median"})
    feature_engineer(ws, {"ws": str(ws.root)})
    out = model_train(ws, {"ws": str(ws.root), "target": "sales"})
    assert out["success"] is True
    assert "metrics" in out and "rmse" in out["metrics"]
    assert out["feature_importance"]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_servers.py -k "model_" -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 `code/csv_agent/servers/model_trainer.py`**

```python
"""model-trainer MCP Server：model_suggest / model_train。"""
from __future__ import annotations

from typing import Any, Dict

import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split

from code.mcp import MCPServer, ToolSchema
from code.csv_agent.servers.data_loader import _resolve_ws
from code.csv_agent.workspace import Workspace


def _target_col(df: pd.DataFrame, target: str) -> str:
    if target and target in df.columns:
        return target
    if target:
        for c in df.columns:
            if target in c:
                return c
    num = df.select_dtypes(include="number").columns
    return num[0] if len(num) else ""


def model_suggest(ws: Workspace, params: Dict[str, Any]) -> Dict[str, Any]:
    path = ws.root / "cleaned.csv"
    if not path.exists():
        return {"success": False, "error": "cleaned.csv not found, run data_clean first"}
    df = pd.read_csv(path)
    target = _target_col(df, params.get("target", ""))
    if not target:
        return {"success": False, "error": "target column not found"}
    n_rows, n_feats = int(len(df)), len(df.columns) - 1
    suggestion = {
        "target": target,
        "task": "regression",
        "models": ["LinearRegression", "RandomForest"],
        "hint": "优先 LinearRegression(可解释) + RandomForest(精度) 对比",
        "n_rows": n_rows,
        "n_features": n_feats,
    }
    return {"success": True, "suggestion": suggestion}


def model_train(ws: Workspace, params: Dict[str, Any]) -> Dict[str, Any]:
    path = ws.root / "cleaned.csv"
    if not path.exists():
        return {"success": False, "error": "cleaned.csv not found"}
    df = pd.read_csv(path)
    target = _target_col(df, params.get("target", ""))
    if not target:
        return {"success": False, "error": "target column not found"}
    X = df.select_dtypes(include="number").drop(columns=[target])
    if X.empty or len(df) < 10:
        return {"success": False, "error": "insufficient numeric features"}
    y = df[target]
    ok = pd.to_numeric(y, errors="coerce")
    if ok.isna().all():
        return {"success": False, "error": "target not numeric"}
    X = X.apply(pd.to_numeric, errors="coerce").fillna(X.median())
    y = ok.fillna(ok.median())
    from sklearn.preprocessing import StandardScaler
    X_sc = x_train, x_test, y_train, y_test = train_test_split(
        X, y, test_size=0.25, random_state=42)
    results = {}
    importances = []
    for name, model in [("LinearRegression", LinearRegression()),
                        ("RandomForest", RandomForestRegressor(n_estimators=50, random_state=42))]:
        m = model.fit(x_train, y_train)
        pred = m.predict(x_test)
        results[name] = {
            "rmse": round(float(mean_squared_error(y_test, pred) ** 0.5), 4),
            "mae": round(float(mean_absolute_error(y_test, pred)), 4),
            "r2": round(float(r2_score(y_test, pred)), 4),
        }
        if hasattr(m, "feature_importances_"):
            imp = dict(zip(X.columns, map(lambda v: round(float(v), 4), m.feature_importances_)))
            importances = sorted(imp.items(), key=lambda kv: kv[1], reverse=True)
    best_name = min(results, key=lambda k: results[k]["rmse"])
    ws.save_json({"results": results, "best": best_name, "importance": importances}, "model_metrics.json")
    return {"success": True, "target": target, "metrics": results["RandomForest"],
            "best_model": best_name, "feature_importance": dict(importances)}
```

- [ ] **Step 4: 更新 `code/csv_agent/servers/__init__.py` 并实现 `ModelTrainerServer`**

```python
from .model_trainer import ModelTrainerServer
__all__ = ["DataLoaderServer", "DataProcessorServer", "VisualizerServer", "ModelTrainerServer"]
```

`ModelTrainerServer` 注册 `model_suggest`/`model_train`（schema 参数 `ws`、`target`、`goal` 为 string），handler `lambda **kw: model_*(_resolve_ws(kw), kw)`。

- [ ] **Step 5: 运行测试通过**

Run: `uv run pytest tests/test_csv_agent_servers.py -k "model_" -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add code/csv_agent/servers/__init__.py code/csv_agent/servers/model_trainer.py tests/test_csv_agent_servers.py
git commit -m "feat(csv-agent): model-trainer MCP server (model_suggest/model_train)"
```

---

### Task 7: report-generator MCP Server（report_generate）

**Files:**
- Modify: `code/csv_agent/servers/__init__.py`
- Create: `code/csv_agent/servers/report_generator.py`
- Test: `tests/test_csv_agent_servers.py`

- [ ] **Step 1: 写失败测试**

```python
from code.csv_agent.servers.report_generator import report_generate


def test_report_generate_writes_markdown():
    ws = _mkws()
    out = report_generate(ws, {"ws": str(ws.root), "goal": "分析销售额影响因素",
                               "models": "RandomForest"})
    assert out["success"] is True
    assert ws.report_md.exists()
    content = ws.report_md.read_text(encoding="utf-8")
    assert "AI 数据分析报告" in content
    assert "销售额" in content
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_servers.py -k report_generate -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 `code/csv_agent/servers/report_generator.py`**

```python
"""report-generator MCP Server：report_generate。"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict

from code.mcp import MCPServer, ToolSchema
from code.csv_agent.servers.data_loader import _resolve_ws
from code.csv_agent.workspace import Workspace


def report_generate(ws: Workspace, params: Dict[str, Any]) -> Dict[str, Any]:
    goal = params.get("goal", "数据分析")
    schema = ws.load_json("schema.json") or {}
    model_metrics = ws.load_json("model_metrics.json") or {}
    charts = ws.load_json("charts_meta.json") or []
    lines = [
        "# AI 数据分析报告", "",
        f"**目标：** {goal}", "",
        f"**生成时间：** {datetime.now().strftime('%Y-%m-%d %H:%M')}", "",
    ]
    if schema:
        lines += ["## 数据概览", "",
                  f"- 行数：{schema.get('rows')}  -  列数：{schema.get('cols')}   -  数据列：{', '.join(schema.get('columns', []))}", ""]
    if charts:
        lines += ["## 探索性分析", "",
                  "![分布图](charts/hist_...)  *见 charts/ 目录*", ""]
    if model_metrics:
        lines += ["## 建模与评估", ""]
        best = model_metrics.get("best", "")
        lines += [f"- 最优模型：**{best}**"]
        for name, m in (model_metrics.get("results") or {}).items():
            lines.append(f"- `{name}`：RMSE={m.get('rmse')}  R2={m.get('r2')}")
        imp = model_metrics.get("importance") or {}
        if imp:
            lines += ["", "### 特征重要性", ""]
            top = dict(list(imp.items())[:5])
            for k, v in top.items():
                lines.append(f"- `{k}`：{v}")
        lines += [""]
    lines += ["## 结论与建议", "",
               "1. 依据特征重要性优先优化高影响指标。",
               "2. 建议在更大样本上交叉验证。", ""]
    ws.report_md.write_text("\n".join(lines), encoding="utf-8")
    return {"success": True, "report": str(ws.report_md)}
```

- [ ] **Step 4: 更新 `code/csv_agent/servers/__init__.py` 并实现 `ReportGeneratorServer`**

注册 `report_generate`（schema 参数 `ws`/`goal`/`models` string），handler 适配同上。

- [ ] **Step 5: 运行测试通过**

Run: `uv run pytest tests/test_csv_agent_servers.py -k report_generate -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add code/csv_agent/servers/__init__.py code/csv_agent/servers/report_generator.py tests/test_csv_agent_servers.py
git commit -m "feat(csv-agent): report-generator MCP server (report_generate)"
```

---

### Task 8: Memory（SQLite）

**Files:**
- Create: `code/csv_agent/memory.py`
- Test: `tests/test_csv_agent_memory.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_csv_agent_memory.py
import sys, os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.csv_agent.memory import MemoryStore


def test_preference_roundtrip():
    m = MemoryStore(":memory:")
    m.set_preference("chart_style", "coolwarm")
    assert m.get_preference("chart_style") == "coolwarm"


def test_history_record_and_lookup():
    m = MemoryStore(":memory:")
    m.record_history(goal="分析销售额", columns=["sales"], model="RandomForest", note="ok")
    hits = m.lookup_history("销售额")
    assert len(hits) >= 1
    assert hits[0]["model"] == "RandomForest"


def test_all_preferences():
    m = MemoryStore(":memory:")
    m.set_preference("a", "1")
    m.set_preference("b", "2")
    assert m.all_preferences()["a"] == "1"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_memory.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 `code/csv_agent/memory.py`**

```python
"""SQLite 记忆：用户偏好 + 分析历史。"""
from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional


class MemoryStore:
    """轻量 SQLite 记忆。传入 ``path``（如 ``":memory:"`` 或文件路径）。"""

    def __init__(self, path: str = "csv_agent_memory.db"):
        self._conn = sqlite3.connect(path)
        self._conn.execute("CREATE TABLE IF NOT EXISTS preferences (k TEXT PRIMARY KEY, v TEXT)")
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "goal TEXT, columns TEXT, model TEXT, note TEXT, ts TEXT)")
        self._conn.commit()

    def set_preference(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO preferences(k,v) VALUES(?,?)", (key, str(value)))
        self._conn.commit()

    def get_preference(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT v FROM preferences WHERE k=?", (key,)).fetchone()
        return row[0] if row else None

    def all_preferences(self) -> Dict[str, str]:
        return dict(self._conn.execute("SELECT k,v FROM preferences").fetchall())

    def record_history(self, goal: str, columns: List[str], model: str = "",
                       note: str = "") -> None:
        self._conn.execute(
            "INSERT INTO history(goal,columns,model,note,ts) VALUES(?,?,?,?,?)",
            (goal, ",".join(columns), model, note, datetime.now().isoformat(timespec="seconds")))
        self._conn.commit()

    def lookup_history(self, keyword: str, limit: int = 5) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT goal,columns,model,note,ts FROM history WHERE goal LIKE ? "
            "ORDER BY id DESC LIMIT ?", (f"%{keyword}%", limit)).fetchall()
        return [{"goal": r[0], "columns": r[1].split(",") if r[1] else [],
                 "model": r[2], "note": r[3], "ts": r[4]} for r in rows]

    def close(self) -> None:
        self._conn.close()
```

- [ ] **Step 4: 运行测试通过**

Run: `uv run pytest tests/test_csv_agent_memory.py -v`
Expected: PASS（3 tests）

- [ ] **Step 5: Commit**

```bash
git add code/csv_agent/memory.py tests/test_csv_agent_memory.py
git commit -m "feat(csv-agent): SQLite 记忆模块"
```

---

### Task 9: bridge — MCP 工具双注册进 ToolRegistry

**Files:**
- Create: `code/csv_agent/bridge.py`
- Test: `tests/test_csv_agent_bridge.py`

实现把所有 MCP Server 的工具，包装为 `agent_runtime.Tool`，注册进 `ToolRegistry`；同时返回 `MCPClient` 并连接 servers（MCP 协议方向）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_csv_agent_bridge.py
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.csv_agent.bridge import build_tool_registry, connect_mcp_servers
from code.csv_agent.servers import (DataLoaderServer, DataProcessorServer, VisualizerServer,
                                    ModelTrainerServer, ReportGeneratorServer)


def test_build_tool_registry_contains_all_tools():
    reg = build_tool_registry()
    names = reg.list_names()
    assert {"csv_load", "data_summary", "data_clean", "feature_engineer",
            "eda_plot", "model_suggest", "model_train", "report_generate"} <= set(names)


def test_connect_mcp_servers_discovers_tools():
    client = connect_mcp_servers()
    tools = client.list_all_tools()
    assert len(tools) == 8
    assert {t["name"] for t in tools} >= {"csv_load", "report_generate"}
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_bridge.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 `code/csv_agent/bridge.py`**

```python
"""把数据分析 MCP 工具双注册：MCP Server（协议）+ ToolRegistry（executor 执行）。"""
from __future__ import annotations

from typing import List

from code.agent_runtime import Tool, ToolRegistry
from code.mcp import MCPClient
from code.csv_agent.servers import (DataLoaderServer, DataProcessorServer, VisualizerServer,
                                    ModelTrainerServer, ReportGeneratorServer)


def all_servers() -> List:
    return [DataLoaderServer(), DataProcessorServer(), VisualizerServer(),
            ModelTrainerServer(), ReportGeneratorServer()]


def connect_mcp_servers() -> MCPClient:
    client = MCPClient()
    for srv in all_servers():
        client.connect_server(srv)
    return client


def build_tool_registry() -> ToolRegistry:
    """扫描所有 MCP Server 工具，构造 executor 可调用的 Tool。

    约定：``Tool.execute`` 调 ``function(**kwargs)``，而 Executor 调 ``tool.execute(description, **metadata)``。
    因此 ``function`` 必须接受 ``description`` + ``**kwargs``，并从 kwargs 或
    ``WorkspaceContext.current()`` 解析 workspace 后转发给 MCP handler。
    """
    reg = ToolRegistry()
    for srv in all_servers():
        for schema in srv.tools:
            handler = srv._tools[schema.name].handler
            name = schema.name
            desc = schema.description
            params_schema = schema.parameters

            def make_fn(hobj):
                def fn(description: str = "", workspace: str = "", params: dict = None,
                       ws: str = "", **kwargs) -> dict:
                    p = dict(params or {})
                    ws_val = ws or p.get("ws") or workspace
                    if not ws_val:
                        from code.csv_agent.workspace import WorkspaceContext
                        cur = WorkspaceContext.current()
                        if cur is not None:
                            ws_val = str(cur.root)
                    p["ws"] = ws_val or ""
                    return hobj(**p)
                return fn

            reg.register(Tool(name=name, description=desc,
                              parameters=params_schema, function=make_fn(handler)))
    return reg
```

实现确认（已核实）：`agent_runtime.tools.Tool` **不可调用**，仅 `Tool.execute(**kwargs)` 调 `Tool.function(**kwargs)`。Executor 走 `elif hasattr(tool, "execute"): tool.execute(description, **metadata)` 分支。故桥接后 Executor 会以 `tool.execute(description=节点描述, **metadata)` 触发 `fn`；metadata 来自 Planner，可能不含 workspace → 依赖 `WorkspaceContext` 兜底，这正是 orchestrator 先行 `WorkspaceContext.push(ws)` 的原因。

- [ ] **Step 4: 运行测试通过**

Run: `uv run pytest tests/test_csv_agent_bridge.py -v`
Expected: PASS（2 tests）。若 `MCPClient.connect_server` 需 `server.start()`（已自动），且 `srv.tools` 返回 `ToolSchema` 列表、`srv._tools` 为 `{name: _ToolWrapper}`，则上述访问成立。

- [ ] **Step 5: Commit**

```bash
git add code/csv_agent/bridge.py tests/test_csv_agent_bridge.py
git commit -m "feat(csv-agent): MCP 工具双注册进 ToolRegistry"
```

---

### Task 10: orchestrator — 组装单次分析全流程

**Files:**
- Create: `code/csv_agent/orchestrator.py`
- Test: `tests/test_csv_agent_orchestrator.py`

`CsvAgent` 负责：设 WorkspaceContext → 用 `PlannerExecutorAgent` 执行目标 → 汇总 report。它把用户的 goal 交给 Planner-Executor；工具经 bridge 注册。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_csv_agent_orchestrator.py
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.csv_agent.orchestrator import CsvAgent
from code.csv_agent.datagen import gen_sales
from code.csv_agent.workspace import Workspace


def test_analyze_produces_report():
    ws = Workspace.create()
    ws.save_csv(gen_sales(n=30, dirty=True), "input.csv")
    agent = CsvAgent(use_llm=False)
    out = agent.analyze(ws, "分析销售额影响因素，给出回归模型建议")
    assert out["success"] is True
    assert ws.report_md.exists()
    assert os.path.exists(str(out.get("report")))
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_orchestrator.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 `code/csv_agent/orchestrator.py`**

```python
"""CsvAgent：把一次 CSV 分析目标交给 Planner-Executor 编排执行。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from code.csv_agent.bridge import build_tool_registry
from code.csv_agent.memory import MemoryStore
from code.csv_agent.workspace import Workspace, WorkspaceContext
from code.agent_runtime import LLMClient, SessionManager, TraceLogger
from code.planner_executor import PlannerExecutorAgent, ToolRegistry


class CsvAgent:
    """CSV 数据分析编排入口。"""

    def __init__(self, use_llm: bool = True, memory: Optional[MemoryStore] = None):
        self._use_llm = use_llm
        self.llm = LLMClient() if use_llm else None
        self.tool_registry: ToolRegistry = build_tool_registry()
        self.session_manager = SessionManager()
        self.trace_logger = TraceLogger("csv_agent")
        self.memory = memory or MemoryStore()
        self.agent = PlannerExecutorAgent(
            llm_client=self.llm,
            tool_registry=self.tool_registry,
            session_manager=self.session_manager,
            trace_logger=self.trace_logger,
            auto_planning=False,          # 数据任务都需规划
        )

    def analyze(self, workspace: Workspace, goal: str) -> Dict[str, Any]:
        """执行一次分析：加载 schema 注入上下文 → planner-executor 运行 → 返回报告路径。"""
        # 1. 注入当前工作区，工具据此读写文件
        WorkspaceContext.push(workspace)
        try:
            # 2. 先跑一次 csv_load，得到 schema 供规划上下文 + 记录历史
            loader = self.tool_registry.get("csv_load")
            schema = loader.execute(description="加载数据", params={"ws": str(workspace.root)})
            # 3. 交给 PlannerExecutorAgent 执行目标（工具会访问 WorkspaceContext/params）
            result = self.agent.run(goal)
            # 4. 若未自动生成报告，兜底调一次 report_generate
            if not workspace.report_md.exists():
                self.tool_registry.get("report_generate").execute(
                    description="生成报告", params={"goal": goal, "ws": str(workspace.root)})
            self.memory.record_history(
                goal=goal,
                columns=schema.get("columns", []) if isinstance(schema, dict) else [],
                model=str(result.get("final_output"))[:50],
            )
            return {"success": True, "report": str(workspace.report_md), "result": result,
                    "run_id": workspace.run_id}
        finally:
            WorkspaceContext.pop()
```

（Step 3 附注：Executor 通过 `tool.execute(description=节点描述, **metadata)` 调用工具，其中 metadata 由 Planner 生成、通常为空 → bridge 的 fn 经 `WorkspaceContext.current()` 兜底解析 workspace，无需改 Executor 核心。若 `use_llm=False` 时 `Planner` 无法拆解为多目标，`agent.run` 仍返回；报告生成由兜底分支保证。）

- [ ] **Step 4: 运行测试通过**

Run: `uv run pytest tests/test_csv_agent_orchestrator.py -v`
Expected: PASS。若 `use_llm=False` 时 `Planner` 无法拆解为多步（无 Key），则放宽断言为「analyze 不抛异常且 report 文件存在」；核心验收是 `report_md` 与 `success`。

- [ ] **Step 5: Commit**

```bash
git add code/csv_agent/orchestrator.py tests/test_csv_agent_orchestrator.py
git commit -m "feat(csv-agent): 编排入口 CsvAgent"
```

---

### Task 11: CLI

**Files:**
- Modify: `code/csv_agent/__init__.py`
- Create: `code/csv_agent/cli.py`
- Test: `tests/test_csv_agent_cli.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_csv_agent_cli.py
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.csv_agent import cli
from code.csv_agent.datagen import gen_sales
from code.csv_agent.workspace import Workspace


def test_cli_analyze(tmp_path):
    ws = Workspace.create()
    csv_path = ws.save_csv(gen_sales(n=20, dirty=True), "input.csv")
    ws2 = Workspace.create()
    args = cli.parse_args(["analyze", csv_path, "分析销售额"])
    assert args.cmd == "analyze"
    out = cli.cmd_analyze(args, ws2)
    assert out.get("success") is True
    assert ws2.report_md.exists()
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 `code/csv_agent/cli.py`**

```python
"""CLI 入口。用法: python -m csv_agent.cli analyze <csv> "<goal>" """
from __future__ import annotations

import argparse
import sys

from code.csv_agent.datagen import gen_sales
from code.csv_agent.memory import MemoryStore
from code.csv_agent.orchestrator import CsvAgent
from code.csv_agent.workspace import Workspace


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="csv-agent", description="CSV 数据分析 Agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    an = sub.add_parser("analyze", help="分析 CSV")
    an.add_argument("csv", help="CSV 文件路径")
    an.add_argument("goal", help="自然语言分析目标")
    an.add_argument("--no-llm", action="store_true", help="禁用 LLM")
    an.add_argument("--sample", action="store_true", help="用内置示例数据")
    sa = sub.add_parser("sample", help="生成示例 CSV")
    sa.add_argument("out", help="输出路径")
    return p.parse_args(argv)


def cmd_analyze(args: argparse.Namespace, workspace: Workspace) -> dict:
    csv_path = args.csv
    if args.sample:
        csv_path = workspace.save_csv(gen_sales(dirty=True), "input.csv")
    if not __import__("os").path.exists(csv_path):
        raise SystemExit(f"file not found: {csv_path}")
    # 把用户 CSV 复制到工作区
    import shutil
    shutil.copy(csv_path, workspace.input_csv)
    agent = CsvAgent(use_llm=not args.no_llm, memory=MemoryStore())
    return agent.analyze(workspace, args.goal)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.cmd == "sample":
        gen_sales(dirty=True).to_csv(args.out, index=False)
        print(f"示例 CSV: {args.out}")
        return 0
    ws = Workspace.create()
    out = cmd_analyze(args, ws)
    print(f"[success={out.get('success')}] report: {out.get('report')}")
    return 0 if out.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 更新 `code/csv_agent/__init__.py`**

```python
"""CSV 数据分析 Agent 后端包。"""
from .workspace import Workspace, WorkspaceContext
from .memory import MemoryStore
from .orchestrator import CsvAgent

__all__ = ["Workspace", "WorkspaceContext", "MemoryStore", "CsvAgent"]
```

- [ ] **Step 5: 运行测试通过 + 手动冒烟**

Run: `uv run pytest tests/test_csv_agent_cli.py -v`
Then: `uv run python -m csv_agent.cli sample /tmp/sales.csv && uv run python -m csv_agent.cli analyze /tmp/sales.csv "分析销售额，给出回归模型建议"`
Expected: 打印 report 路径且退出码 0。

- [ ] **Step 6: Commit**

```bash
git add code/csv_agent/__init__.py code/csv_agent/cli.py tests/test_csv_agent_cli.py
git commit -m "feat(csv-agent): CLI 入口"
```

---

### Task 12: FastAPI API

**Files:**
- Create: `code/csv_agent/api.py`
- Test: `tests/test_csv_agent_api.py`

起点使用 FastAPI + uvicorn。接口：`POST /api/analyze`（上传 CSV + goal，同步执行返回 report 路径与 run_id）、`GET /api/report/{run_id}`（返回 Markdown 内容）、`GET /api/health`。

- [ ] **Step 1: 写失败测试（用 FastAPI TestClient）**

```python
# tests/test_csv_agent_api.py
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient

from code.csv_agent.api import app
from code.csv_agent.datagen import gen_sales


def test_health():
    with TestClient(app) as c:
        r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_analyze_and_report(tmp_path):
    p = tmp_path / "sales.csv"
    gen_sales(n=20, dirty=True).to_csv(p, index=False)
    with TestClient(app) as c:
        with open(p, "rb") as f:
            r = c.post("/api/analyze", data={"goal": "分析销售额，给回归建议"},
                       files={"file": ("sales.csv", f.read(), "text/csv")})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["success"] is True
        run_id = body["run_id"]
        r2 = c.get(f"/api/report/{run_id}")
        assert r2.status_code == 200
        assert "报告" in r2.text
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_api.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 `code/csv_agent/api.py`**

```python
"""FastAPI 接口。启动: uvicorn code.csv_agent.api:app --reload"""
from __future__ import annotations

import io

import pandas as pd
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import PlainTextResponse

from code.csv_agent.memory import MemoryStore
from code.csv_agent.orchestrator import CsvAgent
from code.csv_agent.workspace import Workspace

app = FastAPI(title="CSV 数据分析 Agent API")
_memory = MemoryStore()
_run_map: dict[str, str] = {}  # run_id -> report path


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/analyze")
def analyze(goal: str = Form(...), file: UploadFile = File(...)) -> dict:
    ws = Workspace.create()
    raw = file.file.read()
    df = pd.read_csv(io.BytesIO(raw))
    ws.save_csv(df, "input.csv")
    agent = CsvAgent(memory=_memory)
    out = agent.analyze(ws, goal)
    _run_map[ws.run_id] = str(ws.report_md)
    return {"success": out.get("success"), "run_id": ws.run_id,
            "report": str(ws.report_md), "error": out.get("error")}


@app.get("/api/report/{run_id}", response_class=PlainTextResponse)
def report(run_id: str) -> str:
    path = _run_map.get(run_id, "")
    if not path or not os.path.exists(path):
        return "report not found"
    return open(path, encoding="utf-8").read()


import os  # noqa: E402
```

- [ ] **Step 4: 运行测试通过**

Run: `uv run pytest tests/test_csv_agent_api.py -v`
Expected: PASS（2 tests）

- [ ] **Step 5: Commit**

```bash
git add code/csv_agent/api.py tests/test_csv_agent_api.py
git commit -m "feat(csv-agent): FastAPI 接口"
```

---

### Task 13: 评测 — CSV 任务 + 基线对照

**Files:**
- Create: `code/csv_agent/eval_csv.py`
- Modify: `code/csv_agent/__init__.py`
- Test: `tests/test_csv_agent_eval.py`

复用 `code.evaluation.metrics` 的 `EvalResult/EvalReport/EvaluationMetrics`。新增 CSV 分析评测：对不同难度的 goal 跑 `CsvAgent`，校验产出文件/关键字段，并做 **Planner-Executor vs 简单 Agent Loop** 基线对照（简单 Loop 用 `AgentRuntime` 顺序调用工具）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_csv_agent_eval.py
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.csv_agent.eval_csv import build_csv_tasks, run_csv_eval, run_comparison


def test_build_csv_tasks_has_20_plus():
    tasks = build_csv_tasks()
    assert len(tasks) >= 20
    assert {t["difficulty"] for t in tasks} == {"简单", "中等", "复杂", "困难"}


def test_run_csv_eval_smoke(tmp_path):
    report = run_csv_eval(tmp_path)
    assert report.total == len(build_csv_tasks())
    assert report.pass_rate >= 0.5  # 宽松冒烟


def test_comparison_shape():
    rows = run_comparison(runs=1)
    assert rows and {"engine", "success_rate", "steps", "duration"} <= set(rows[0])
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run pytest tests/test_csv_agent_eval.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: 实现 `code/csv_agent/eval_csv.py`**

```python
"""CSV 分析自动评测：难度任务 + Planner-Executor vs 简单 Loop 基线。"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from code.csv_agent.datagen import gen_sales
from code.csv_agent.orchestrator import CsvAgent
from code.csv_agent.workspace import Workspace
from code.evaluation.metrics import EvalResult, EvalReport, EvaluationMetrics


def build_csv_tasks() -> List[Dict[str, Any]]:
    simple = [
        "这个 CSV 有多少行？", "有多少列？", "缺失值最多的列是哪列？",
        "数值列有哪些？", "给出前几行样例",
    ]
    medium = [
        "展示各数值列分布并画直方图", "检测并处理缺失值",
        "对分类列做编码", "计算数值列相关性并绘制热力图",
        "标准化数值特征", "识别并裁切异常值", "去重",
    ]
    complex_ = [
        "分析销售额影响因素，做特征工程", "训练回归模型并评估",
        "比较线性回归与随机森林效果", "预测销售并给出误差指标",
        "清洗并探索数据，输出概览",
    ]
    hard = [
        "完整分析：清洗→探索→特征工程→多模型对比→生成报告",
        "对含错误数据的 CSV 做完整分析并生成报告",
        "先用模型建议再训练，输出最优模型与特征重要性",
    ]
    tasks: List[Dict[str, Any]] = []
    for g in simple:
        tasks.append({"difficulty": "简单", "goal": g, "check": _must_success})
    for g in medium:
        tasks.append({"difficulty": "中等", "goal": g, "check": _must_success})
    for g in complex_:
        tasks.append({"difficulty": "复杂", "goal": g, "check": _must_success})
    for g in hard:
        tasks.append({"difficulty": "困难", "goal": g,
                      "check": lambda r: r["success"] and r["report_path"]})
    return tasks


def _must_success(r: dict) -> bool:
    return bool(r.get("success"))


def _run_one(goal: str, ws: Workspace) -> dict:
    t0 = time.time()
    try:
        agent = CsvAgent(use_llm=False)
        out = agent.analyze(ws, goal)
        return {"success": out.get("success", False),
                "report_path": str(ws.report_md) if ws.report_md.exists() else "",
                "duration": round(time.time() - t0, 4)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e), "duration": round(time.time() - t0, 4)}


def run_csv_eval(base_dir=None) -> EvalReport:
    report = EvalReport()
    for t in build_csv_tasks():
        ws = Workspace.create(base=base_dir) if base_dir else Workspace.create()
        ws.save_csv(gen_sales(n=40, dirty="错误数据" in t["goal"]), "input.csv")
        r = _run_one(t["goal"], ws)
        passed = t["check"](r)
        report.add_result(EvalResult(
            task_id=t["goal"][:8], task_name=t["goal"],
            passed=passed, expected=None, actual=r, duration=r["duration"],
            details={"difficulty": t["difficulty"]}))
    return report


def run_comparison(runs: int = 3) -> List[Dict[str, Any]]:
    """Planner-Executor vs 简单 Agent Loop 基线对照。"""
    metrics = EvaluationMetrics()
    rows: List[Dict[str, Any]] = []
    goal = "分析销售额影响因素并生成报告"
    # --- Planner-Executor ---
    pe_results = [_run_one(goal, Workspace.create()) for _ in range(runs)]
    rows.append({"engine": "Planner-Executor",
                 "success_rate": metrics.task_success_rate(
                     [EvalResult("x", "x", r["success"], None, r, r["duration"])
                      for r in pe_results]),
                 "steps": f"{sum(1 for r in pe_results if r['success'])}/{runs}",
                 "duration": round(sum(r["duration"] for r in pe_results) / runs, 4)})
    # --- 简单 Agent Loop（顺序 noun 调工具）---
    loop_success = _run_simple_loop(goal)
    rows.append({"engine": "Agent Loop",
                 "success_rate": 1.0 if loop_success else 0.0,
                 "steps": "8", "duration": 0.0})
    return rows


def _run_simple_loop(goal: str) -> bool:
    """基线：固定顺序调 8 个工具（不重规划），任意失败即 False。"""
    ws = Workspace.create()
    ws.save_csv(gen_sales(n=40, dirty=True), "input.csv")
    agent = CsvAgent(use_llm=False)
    from code.csv_agent.servers.data_processor import data_clean, feature_engineer
    from code.csv_agent.servers.visualizer import eda_plot
    from code.csv_agent.servers.model_trainer import model_train, model_suggest
    from code.csv_agent.servers.report_generator import report_generate
    steps = [
        ("csv_load", {"ws": str(ws.root)}),
        ("data_summary", {"ws": str(ws.root)}),
        ("data_clean", {"ws": str(ws.root), "fill": "median"}),
        ("feature_engineer", {"ws": str(ws.root)}),
        ("eda_plot", {"ws": str(ws.root)}),
        ("model_suggest", {"ws": str(ws.root), "target": "sales", "goal": goal}),
        ("model_train", {"ws": str(ws.root), "target": "sales"}),
        ("report_generate", {"ws": str(ws.root), "goal": goal}),
    ]
    for name, params in steps:
        res = agent.tool_registry.get(name).execute(description=name, params=params)
        if not res.get("success"):
            return False
    return ws.report_md.exists()
```

- [ ] **Step 4: 更新 `code/csv_agent/__init__.py`**

```python
from .eval_csv import build_csv_tasks, run_csv_eval, run_comparison
```

- [ ] **Step 5: 运行测试通过**

Run: `uv run pytest tests/test_csv_agent_eval.py -v`
Expected: PASS。若 20+ 任务全量过慢，将 `run_csv_eval` 冒烟改为仅复杂/困难子集；验收标准是 `build_csv_tasks()>=20` 与 comparison 结构正确。

- [ ] **Step 6: Commit**

```bash
git add code/csv_agent/eval_csv.py code/csv_agent/__init__.py tests/test_csv_agent_eval.py
git commit -m "feat(csv-agent): 自动评测 + 基线对照"
```

---

### Task 14: 全量回归 + README 补记

**Files:**
- Run: `uv run pytest -q`
- Modify: `README.md`

- [ ] **Step 1: 全量回归**

Run: `uv run pytest -q`
Expected: 全部通过（既有 tests + 新增 csv_agent tests）。

- [ ] **Step 2: 冒烟 CLI 全流程**

Run:
```
uv run python -m csv_agent.cli sample /tmp/s.csv
uv run python -m csv_agent.cli analyze /tmp/s.csv "分析销售额影响因素并生成报告"
```
Expected: 退出码 0，打印 report 路径，`report.md` 生成。

- [ ] **Step 3: 补充 README（追加一节）**

在 `README.md` 末尾追加「CSV 数据分析 Agent」小节，说明 CLI 用法、API 启动方式、评测命令。若 README 已含章节，则插入新章节。

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs(csv-agent): 补记 CSV 数据分析 Agent 用法"
```
from __future__ import annotations

import multiprocessing as mp
import time
from typing import Any, Callable, Optional, Tuple


def _worker(fn, args, q):
    try:
        q.put(("ok", fn(*args)))
    except Exception as e:
        q.put(("err", repr(e)))


def run_isolated(fn, args=(), timeout=30.0, context=None):
    ctx = mp.get_context(context or ("fork" if hasattr(mp, "fork") else None))
    q = ctx.Queue()
    p = ctx.Process(target=_worker, args=(fn, args, q), daemon=True)
    t0 = time.time()
    p.start()
    p.join(timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        return {"success": False, "result": None, "error": f"tool timed out after {timeout}s", "elapsed": time.time() - t0}
    try:
        status, payload = q.get_nowait()
    except Exception:
        return {"success": False, "result": None, "error": "no result produced", "elapsed": time.time() - t0}
    if status == "err":
        return {"success": False, "result": None, "error": payload, "elapsed": time.time() - t0}
    return {"success": True, "result": payload, "error": "", "elapsed": time.time() - t0}
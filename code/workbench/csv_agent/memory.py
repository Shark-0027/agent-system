from __future__ import annotations
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

class MemoryStore:
    def __init__(self, path="csv_agent_memory.db"):
        # check_same_thread=False: 供 FastAPI 等线程池中共享同一连接（如 API 模块级 MemoryStore）
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute("CREATE TABLE IF NOT EXISTS preferences (k TEXT PRIMARY KEY, v TEXT)")
        self._conn.execute("CREATE TABLE IF NOT EXISTS history (id INTEGER PRIMARY KEY AUTOINCREMENT, goal TEXT, columns TEXT, model TEXT, note TEXT, ts TEXT)")
        self._conn.commit()
    def set_preference(self, key, value):
        self._conn.execute("INSERT OR REPLACE INTO preferences(k,v) VALUES(?,?)", (key, str(value)))
        self._conn.commit()
    def get_preference(self, key):
        row = self._conn.execute("SELECT v FROM preferences WHERE k=?", (key,)).fetchone()
        return row[0] if row else None
    def all_preferences(self):
        return dict(self._conn.execute("SELECT k,v FROM preferences").fetchall())
    def record_history(self, goal, columns, model="", note=""):
        self._conn.execute("INSERT INTO history(goal,columns,model,note,ts) VALUES(?,?,?,?,?)",
                           (goal, ",".join(columns), model, note, datetime.now().isoformat(timespec="seconds")))
        self._conn.commit()
    def lookup_history(self, keyword, limit=5):
        rows = self._conn.execute("SELECT goal,columns,model,note,ts FROM history WHERE goal LIKE ? ORDER BY id DESC LIMIT ?",
                                  (f"%{keyword}%", limit)).fetchall()
        return [{"goal": r[0], "columns": r[1].split(",") if r[1] else [], "model": r[2], "note": r[3], "ts": r[4]} for r in rows]
    def close(self):
        self._conn.close()
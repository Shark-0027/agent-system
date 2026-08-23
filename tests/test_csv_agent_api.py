import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from code.csv_agent.api import app
from code.csv_agent.datagen import gen_sales


def test_health():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_analyze_and_report(tmp_path):
    client = TestClient(app)
    df = gen_sales(n=20, dirty=True)
    df.to_csv(tmp_path / "sales.csv", index=False)
    raw = (tmp_path / "sales.csv").read_bytes()
    r = client.post(
        "/api/analyze",
        data={"goal": "分析销售额，给回归建议"},
        files={"file": ("sales.csv", raw, "text/csv")},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    run_id = body["run_id"]

    rr = client.get(f"/api/report/{run_id}")
    assert rr.status_code == 200
    assert "报告" in rr.text
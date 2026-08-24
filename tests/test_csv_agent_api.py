import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient

from code.workbench.csv_agent.api import app
from code.workbench.csv_agent.datagen import gen_sales


def test_health():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    # 双运行模式需通过接口上报给前端
    assert r.json()["mode"] in ("llm", "local")
    assert "mode_label" in r.json()


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
    # 全流程分析需返回实际采用的运行模式
    assert body["mode"] in ("llm", "local")

    rr = client.get(f"/api/report/{run_id}")
    assert rr.status_code == 200
    assert "报告" in rr.text
    # 可观测性：全流程分析后应有执行轨迹可查
    tr = client.get(f"/api/run/{run_id}/trace")
    assert tr.status_code == 200
    trace = tr.json()
    assert "events" in trace
    assert isinstance(trace["events"], list)


def test_run_analyze_async_and_progress():
    client = TestClient(app)
    r = _upload(client)
    rid = r.json()["run_id"]
    # 异步触发
    a = client.post(f"/api/run/{rid}/analyze?async_mode=true",
                    data={"goal": "分析销售额，给出建议"})
    assert a.status_code == 200
    assert a.json()["started"] is True
    # 轮询直至完成（进度状态应经历 running→done/failed）
    seen = set()
    for _ in range(300):
        p = client.get(f"/api/run/{rid}/progress").json()
        seen.add(p["status"])
        if p["status"] in ("done", "failed"):
            break
        time.sleep(0.1)
    assert "running" in seen, f"should observe running before terminal state: {seen}"
    final = client.get(f"/api/run/{rid}/progress").json()
    assert final["status"] in ("done", "failed")
    if final["status"] == "done":
        assert "success" in final
        # 有执行轨迹可查
        assert client.get(f"/api/run/{rid}/trace").status_code == 200
    # 同步模式兼容旧调用
    s = client.post(f"/api/run/{rid}/analyze", data={"goal": "再分析一次"})
    assert s.status_code == 200
    assert s.json()["mode"] in ("llm", "local")


def test_run_llm_mode():
    client = TestClient(app)
    r = client.get("/api/run/none/llm-mode")
    assert r.status_code == 200
    assert r.json()["mode"] in ("llm", "local")


def _upload(client, n=30):
    df = gen_sales(n=n, dirty=True)
    buf = df.to_csv(index=False)
    return client.post("/api/run", files={"file": ("sales.csv", buf.encode(), "text/csv")})


def test_upload_run():
    client = TestClient(app)
    r = _upload(client)
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"]
    assert body["data"]["success"] is True
    assert body["data"]["rows"] == 30
    assert "order_id" in body["data"]["columns"]


def test_sample_run():
    client = TestClient(app)
    r = client.get("/api/sample")
    assert r.status_code == 200
    body = r.json()
    assert body["run_id"]
    assert body["data"]["success"] is True
    assert body["data"]["rows"] == 200


def test_runs_listing():
    client = TestClient(app)
    rid = _upload(client).json()["run_id"]
    r = client.get("/api/runs")
    assert r.status_code == 200
    ids = [x["run_id"] for x in r.json()["runs"]]
    assert rid in ids


def test_run_data_and_download():
    client = TestClient(app)
    rid = _upload(client).json()["run_id"]
    r = client.get(f"/api/run/{rid}/data?which=input")
    assert r.status_code == 200
    assert r.json()["cols"] == 7
    d = client.get(f"/api/run/{rid}/download?name=input.csv")
    assert d.status_code == 200
    assert "order_id" in d.text


def test_run_tool_csv_load():
    client = TestClient(app)
    rid = _upload(client).json()["run_id"]
    r = client.post(f"/api/run/{rid}/tool", json={"tool": "csv_load", "params": {}})
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["tool"] == "csv_load"
    assert body["columns"]


def test_run_tool_model_train_and_charts():
    client = TestClient(app)
    rid = _upload(client).json()["run_id"]
    for tool in ("csv_load", "data_clean", "feature_engineer", "model_train", "eda_plot"):
        r = client.post(f"/api/run/{rid}/tool", json={"tool": tool, "params": {}})
        assert r.status_code == 200, (tool, r.text)
        assert r.json()["success"] is True, (tool, r.text)
    c = client.get(f"/api/run/{rid}/charts")
    assert c.status_code == 200
    assert len(c.json()["charts"]) >= 1
    first = c.json()["charts"][0]["name"]
    img = client.get(f"/api/run/{rid}/chart", params={"name": first})
    assert img.status_code == 200
    assert img.headers["content-type"] == "image/png"


def test_run_tool_not_found():
    client = TestClient(app)
    rid = _upload(client).json()["run_id"]
    r = client.post(f"/api/run/{rid}/tool", json={"tool": "no_such_tool"})
    assert r.status_code == 404


def test_missing_run_returns_404():
    client = TestClient(app)
    assert client.get("/api/run/nope/data").status_code == 404


def test_preferences_roundtrip():
    client = TestClient(app)
    r = client.put("/api/preferences", json={"preferences": {"region": "default"}})
    assert r.status_code == 200
    prefs = client.get("/api/preferences").json()["preferences"]
    assert prefs.get("region") == "default"


def test_history_endpoint():
    client = TestClient(app)
    r = client.get("/api/history", params={"keyword": ""})
    assert r.status_code == 200
    assert isinstance(r.json()["history"], list)


def test_index_served():
    client = TestClient(app)
    r = client.get("/")
    assert r.status_code == 200
    assert "数据分析" in r.text


def test_tools_listed():
    client = TestClient(app)
    names = {t["name"] for t in client.get("/api/tools").json()["tools"]}
    assert {"csv_load", "data_clean", "eda_plot", "model_train", "report_generate"} <= names
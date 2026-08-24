import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import matplotlib
matplotlib.use("Agg")
from code.workbench.csv_agent.workspace import Workspace
from code.workbench.csv_agent.servers.statistics import (
    corr_analysis, hypo_test, regression_fit, time_series_feat, cluster_profile, anomaly_detect)
from code.workbench.csv_agent.servers.query import nl_filter, nl_insight, QueryServer
from code.workbench.csv_agent.datagen import gen_sales


def _mkws(n=50):
    ws = Workspace.create()
    ws.save_csv(gen_sales(n=n, dirty=True), "input.csv")
    return ws


def test_corr_analysis_heatmap():
    ws = _mkws()
    out = corr_analysis(ws, {"ws": str(ws.root)})
    assert out["success"] is True
    assert out["top_pairs"]
    assert (ws.charts_dir / "corr_heatmap.png").exists()


def test_hypo_test_shapiro():
    ws = _mkws()
    out = hypo_test(ws, {"ws": str(ws.root), "col": "sales"})
    assert out["success"] is True
    assert "shapiro" in out
    assert "ttest_vs_zero" in out


def test_regression_fit_returns_r2():
    ws = _mkws()
    out = regression_fit(ws, {"ws": str(ws.root), "feature": "price", "target": "sales"})
    assert out["success"] is True
    assert "r2" in out
    assert out["chart"]


def test_time_series_feat():
    ws = _mkws()
    out = time_series_feat(ws, {"ws": str(ws.root), "col": "sales"})
    assert out["success"] is True
    assert "chart" in out or "error" in out


def test_cluster_profile():
    ws = _mkws()
    out = cluster_profile(ws, {"ws": str(ws.root), "k": 3})
    assert out["success"] is True
    assert "counts" in out
    assert (ws.charts_dir / "cluster.png").exists()


def test_anomaly_detect():
    ws = _mkws()
    out = anomaly_detect(ws, {"ws": str(ws.root), "col": "sales"})
    assert out["success"] is True
    assert "outlier_count" in out


def test_nl_filter_no_llm_fallback():
    ws = _mkws()
    out = nl_filter(ws, {"ws": str(ws.root), "question": "前5名销量"}, llm=None)
    assert out["success"] is True
    assert out["used_llm"] is False
    assert out["hit_rows"] == 5


def test_nl_insight_no_llm_fallback():
    ws = _mkws()
    out = nl_insight(ws, {"ws": str(ws.root), "question": "分析销售额"}, llm=None)
    assert out["success"] is True
    assert out["used_llm"] is False
    assert out["insights"]


def test_query_server_registers_llm_config():
    server = QueryServer(llm_config=None)
    names = [s.name for s in server.tools]
    assert "nl_filter" in names
    assert "nl_insight" in names
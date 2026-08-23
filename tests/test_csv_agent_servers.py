import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from code.csv_agent.workspace import Workspace
from code.csv_agent.datagen import gen_sales
from code.csv_agent.servers.data_loader import csv_load, data_summary
from code.csv_agent.servers.data_processor import data_clean, feature_engineer
import matplotlib
matplotlib.use("Agg")
from code.csv_agent.servers.visualizer import eda_plot

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
    assert isinstance(out["dtypes"]["quantity"], str)

def test_csv_load_missing_file():
    ws = Workspace.create()
    out = csv_load(ws, {"ws": str(ws.root)})
    assert out["success"] is False
    assert "input.csv" in out["error"]

def test_data_summary_numeric_cols():
    ws = _mkws()
    out = data_summary(ws, {"ws": str(ws.root)})
    assert out["success"] is True
    assert "sales" in out["summary"]
    assert "mean" in out["summary"]["sales"]

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
    assert "region_code" in df.columns
    assert "price_scaled" in df.columns

def test_eda_plot_generates_charts():
    ws = _mkws()
    out = eda_plot(ws, {"ws": str(ws.root), "kind": "hist"})
    assert out["success"] is True
    png_files = list(ws.charts_dir.glob("*.png"))
    assert len(png_files) >= 1
    assert out["charts"]
import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from code.csv_agent.workspace import Workspace
from code.csv_agent.datagen import gen_sales
from code.csv_agent.servers.data_loader import csv_load, data_summary

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
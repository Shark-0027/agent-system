import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import pandas as pd
from code.workbench.csv_agent.workspace import Workspace, WorkspaceContext

def test_workspace_create_and_csv_roundtrip(tmp_path):
    ws = Workspace.create()
    assert ws.root.exists()
    assert ws.charts_dir.exists()
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
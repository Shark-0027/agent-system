import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from code.workbench.csv_agent.memory import MemoryStore

def test_preference_roundtrip():
    m = MemoryStore(":memory:")
    m.set_preference("chart_style", "coolwarm")
    assert m.get_preference("chart_style") == "coolwarm"

def test_history_record_and_lookup():
    m = MemoryStore(":memory:")
    m.record_history(goal="分析销售额", columns=["sales","price"], model="RandomForest", note="ok")
    hits = m.lookup_history("销售额")
    assert len(hits) >= 1
    assert hits[0]["model"] == "RandomForest"

def test_all_preferences():
    m = MemoryStore(":memory:")
    m.set_preference("a", "1")
    m.set_preference("b", "2")
    assert m.all_preferences()["a"] == "1"
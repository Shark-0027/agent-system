import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from code.workbench.csv_agent.bridge import build_tool_registry, connect_mcp_servers

def test_build_tool_registry_contains_all_tools():
    reg = build_tool_registry()
    names = {t["name"] for t in reg.list_tools()}
    assert {"csv_load","data_summary","data_clean","feature_engineer","eda_plot","model_suggest","model_train","report_generate"} <= names
    assert reg.find_tool("加载 CSV") is not None

def test_connect_mcp_servers_discovers_tools():
    client = connect_mcp_servers()
    tools = client.list_all_tools()
    assert len(tools) == 8
    assert {t["name"] for t in tools} >= {"csv_load","report_generate"}
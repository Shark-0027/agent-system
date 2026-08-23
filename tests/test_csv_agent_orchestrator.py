import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.csv_agent.orchestrator import CsvAgent
from code.csv_agent.datagen import gen_sales
from code.csv_agent.workspace import Workspace


def test_analyze_produces_report():
    ws = Workspace.create()
    ws.save_csv(gen_sales(n=30, dirty=True), "input.csv")
    agent = CsvAgent(use_llm=False)
    out = agent.analyze(ws, "分析销售额影响因素，给出回归模型建议")
    assert out["success"] is True
    assert ws.report_md.exists()
    assert os.path.exists(str(out.get("report")))
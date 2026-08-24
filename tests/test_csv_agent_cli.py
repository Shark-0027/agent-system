import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.workbench.csv_agent import cli
from code.workbench.csv_agent.datagen import gen_sales
from code.workbench.csv_agent.workspace import Workspace


def test_cli_analyze():
    ws = Workspace.create()
    ws.save_csv(gen_sales(n=20, dirty=True), "input.csv")
    csv_path = str(ws.input_csv)

    ws2 = Workspace.create()
    args = cli.parse_args(["analyze", csv_path, "分析销售额", "--no-llm"])
    assert args.cmd == "analyze"

    out = cli.cmd_analyze(args, ws2)
    assert out["success"] is True
    assert ws2.report_md.exists()
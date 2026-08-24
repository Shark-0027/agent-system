import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.workbench.csv_agent.orchestrator import CsvAgent
from code.workbench.csv_agent.bridge import build_tool_registry
from code.workbench.csv_agent.datagen import gen_sales
from code.workbench.csv_agent.workspace import Workspace, WorkspaceContext
from code.framework.agent_runtime import SessionManager, TraceLogger
from code.framework.planner_executor import PlannerExecutorAgent


def test_analyze_produces_report():
    ws = Workspace.create()
    ws.save_csv(gen_sales(n=30, dirty=True), "input.csv")
    agent = CsvAgent(use_llm=False)
    out = agent.analyze(ws, "分析销售额影响因素，给出回归模型建议")
    assert out["success"] is True
    assert ws.report_md.exists()
    assert os.path.exists(str(out.get("report")))
    # 可观测性：分析应产出结构化执行轨迹
    assert ws.trace_file.exists()
    trace = ws.load_json("trace.json")
    assert "events" in trace
    assert "duration" in trace


def test_planner_drives_tool_via_find_tool():
    """无 LLM + 提供了 tool_registry 时，PlannerExecutorAgent 应通过 Executor.find_tool
    真正调度 csv_load 工具，而不是返回 no tool available 或空跑。"""
    ws = Workspace.create()
    ws.save_csv(gen_sales(n=30, dirty=True), "input.csv")

    # 先确认 find_tool 对目标描述能匹配到 csv_load
    reg = build_tool_registry()
    tool = reg.find_tool("加载 CSV 数据并返回列数")
    assert tool == "csv_load"

    agent = PlannerExecutorAgent(
        llm_client=None,
        tool_registry=reg,
        session_manager=SessionManager(),
        trace_logger=TraceLogger("csv_agent"),
        auto_planning=False,
    )
    WorkspaceContext.push(ws)
    try:
        result = agent.run("加载 CSV 数据并返回列数")
    finally:
        WorkspaceContext.pop()

    # 判据 1：整体成功
    assert result["success"] is True
    # 判据 2：不是 "no tool available" 空跑
    assert "no tool available" not in str(result["output"])
    # 判据 3：csv_load 实际执行并写出了 schema.json
    assert ws.load_json("schema.json") is not None
    assert (ws.root / "schema.json").exists()
    # 判据 4：计划 DAG 中确有一个完成的任务节点，且正是 csv_load
    completed = result["plan"]["nodes"]  # TaskDAG.to_dict 输出的节点列表
    assert any(n["status"] == "completed" for n in completed), "计划中应有完成节点"
    outputs = [t["description"] for t in result["output"]["task_results"].values()]
    assert any("加载" in d for d in outputs)
    # 工具执行了 csv_load 并产出列数（schema.json 的 cols == gen_sales 列数）
    schema = ws.load_json("schema.json")
    assert schema["cols"] == len(gen_sales(n=30, dirty=True).columns)
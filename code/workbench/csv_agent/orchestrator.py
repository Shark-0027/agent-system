"""CsvAgent：把一次 CSV 分析目标交给 Planner-Executor 编排执行。"""
from __future__ import annotations

from typing import Any, Dict, Optional

from code.workbench.csv_agent.bridge import build_tool_registry
from code.workbench.csv_agent.memory import MemoryStore
from code.workbench.csv_agent.workspace import Workspace, WorkspaceContext
from code.framework.agent_runtime import LLMClient, SessionManager, TraceLogger
from code.framework.planner_executor import PlannerExecutorAgent, ToolRegistry


class CsvAgent:
    """CSV 数据分析编排入口。

    负责：注入当前工作区到 WorkspaceContext（工具据此读写文件）→
    用 PlannerExecutorAgent 执行用户目标 → 汇总并兜底生成报告。
    """

    def __init__(self, use_llm: bool = True, memory: Optional[MemoryStore] = None):
        self._use_llm = use_llm
        self.llm = LLMClient() if use_llm else None
        self.tool_registry: ToolRegistry = build_tool_registry()
        self.session_manager = SessionManager()
        self.trace_logger = TraceLogger("csv_agent")
        self.memory = memory or MemoryStore()
        self.agent = PlannerExecutorAgent(
            llm_client=self.llm,
            tool_registry=self.tool_registry,
            session_manager=self.session_manager,
            trace_logger=self.trace_logger,
            auto_planning=False,          # 数据任务都需规划
        )

    def analyze(self, workspace: Workspace, goal: str) -> Dict[str, Any]:
        """执行一次分析：加载 schema 注入上下文 → planner-executor 运行 → 返回报告路径。"""
        # 1. 注入当前工作区，工具据此读写文件
        WorkspaceContext.push(workspace)
        try:
            # 2. 先跑一次 csv_load，得到 schema 供规划上下文 + 记录历史
            loader = self.tool_registry.get("csv_load")
            schema = loader.execute(description="加载数据", params={"ws": str(workspace.root)})
            # 3. 交给 PlannerExecutorAgent 执行目标（工具会访问 WorkspaceContext/params）
            result: Any = None
            try:
                result = self.agent.run(goal)
            except Exception:  # noqa: BLE001
                result = {}
            # 4. 若未自动生成报告，兜底调一次 report_generate（params 含 goal 与 ws）
            if not workspace.report_md.exists():
                self.tool_registry.get("report_generate").execute(
                    description="生成报告",
                    params={"goal": goal, "ws": str(workspace.root)})
            # 5. 记录分析历史
            columns = schema.get("columns", []) if isinstance(schema, dict) else []
            model = str(result.get("final_output"))[:50] if isinstance(result, dict) else ""
            self.memory.record_history(goal=goal, columns=columns, model=model)
            return {"success": True, "report": str(workspace.report_md), "result": result,
                    "run_id": workspace.run_id}
        finally:
            WorkspaceContext.pop()
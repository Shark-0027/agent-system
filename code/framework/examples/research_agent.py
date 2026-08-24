"""
深度研究 Agent - Planner-Executor 综合示例

使用 Planner-Executor 架构完成复杂的深度研究任务。
演示：任务分解、并行执行、失败恢复、局部重规划。

使用方法:
    python research_agent.py
"""

import os
import sys
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from code.agent_runtime import (
    AgentRuntime, LLMClient, ToolRegistry, Tool,
    StateManager, SessionManager, TraceLogger,
)
from code.mcp import MCPClient, ToolRouter
from code.mcp.servers import RepoAnalysisServer, DocSearchServer
from code.planner_executor import (
    PlannerExecutorAgent, Planner, Executor,
    TaskDAG, TaskNode, TaskStatus,
    PlanVerifier, ParallelScheduler, FailureStrategy,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_research_tools() -> ToolRegistry:
    """创建研究工具集"""
    registry = ToolRegistry()

    def analyze_code(repo_path: str, aspect: str = "structure") -> dict:
        """分析代码仓库"""
        return {
            "success": True,
            "repo": repo_path,
            "aspect": aspect,
            "summary": f"已完成 {aspect} 分析",
            "files_analyzed": 42,
            "lines_of_code": 3500,
        }

    registry.register(
        Tool(
            name="analyze_code",
            description="分析代码仓库的特定方面",
            parameters={
                "type": "object",
                "properties": {
                    "repo_path": {"type": "string", "description": "仓库路径"},
                    "aspect": {
                        "type": "string",
                        "enum": ["structure", "quality", "dependencies", "security"],
                        "description": "分析方面",
                    },
                },
                "required": ["repo_path"],
            },
            function=analyze_code,
        )
    )

    def search_literature(topic: str, max_results: int = 10) -> dict:
        """搜索文献"""
        return {
            "success": True,
            "topic": topic,
            "results": [
                {
                    "title": f"关于 {topic} 的研究论文",
                    "authors": ["张三", "李四"],
                    "year": 2025,
                    "abstract": f"本文研究了 {topic} 的相关问题...",
                }
            ],
            "total": 1,
        }

    registry.register(
        Tool(
            name="search_literature",
            description="搜索学术文献",
            parameters={
                "type": "object",
                "properties": {
                    "topic": {"type": "string", "description": "研究主题"},
                    "max_results": {"type": "integer", "description": "最大结果数"},
                },
                "required": ["topic"],
            },
            function=search_literature,
        )
    )

    def generate_report(title: str, sections: list[str], findings: list[dict]) -> dict:
        """生成研究报告"""
        return {
            "success": True,
            "title": title,
            "sections": sections,
            "findings_count": len(findings),
            "report": f"# {title}\n\n报告已生成，包含 {len(sections)} 个章节。",
        }

    registry.register(
        Tool(
            name="generate_report",
            description="生成结构化研究报告",
            parameters={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "报告标题"},
                    "sections": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "章节列表",
                    },
                    "findings": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "研究发现",
                    },
                },
                "required": ["title", "sections"],
            },
            function=generate_report,
        )
    )

    def compare_approaches(approaches: list[str], criteria: list[str]) -> dict:
        """比较不同方案"""
        return {
            "success": True,
            "approaches": approaches,
            "criteria": criteria,
            "comparison": {
                a: {c: f"评分: {hash(a + c) % 10 + 1}/10" for c in criteria}
                for a in approaches
            },
        }

    registry.register(
        Tool(
            name="compare_approaches",
            description="比较多个方案或技术",
            parameters={
                "type": "object",
                "properties": {
                    "approaches": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "方案列表",
                    },
                    "criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "评估标准",
                    },
                },
                "required": ["approaches", "criteria"],
            },
            function=compare_approaches,
        )
    )

    return registry


def demo_planning():
    """演示任务规划"""
    print("\n" + "=" * 60)
    print("演示: 深度研究 Agent 任务规划")
    print("=" * 60)

    llm = LLMClient()
    planner = Planner(llm_client=llm)
    verifier = PlanVerifier()

    task = (
        "研究 AI Agent 框架的技术选型："
        "1) 分析 LangGraph、AutoGen、CrewAI 三个框架的架构差异；"
        "2) 对比它们在工具集成、任务编排、并行执行方面的能力；"
        "3) 基于对比结果，推荐最适合构建校园助手的技术方案；"
        "4) 生成最终研究报告。"
    )

    print(f"任务: {task}\n")

    plan = planner.plan(task)
    print(f"子任务数: {plan.node_count}")

    order = plan.get_execution_order()
    print(f"执行顺序: {' -> '.join(order)}")

    groups = plan.get_parallel_groups()
    print(f"并行组数: {len(groups)}")
    for i, group in enumerate(groups):
        print(f"  组 {i+1}: {group}")

    result = verifier.verify(plan)
    print(f"\n计划质量评分: {result.score}/100")
    for issue in result.issues:
        print(f"  [{issue.severity}] {issue.message}")

    if suggestions := [i.suggestion for i in result.issues if i.suggestion]:
        print("改进建议:")
        for s in suggestions:
            print(f"  - {s}")


def demo_execution():
    """演示任务执行"""
    print("\n" + "=" * 60)
    print("演示: 任务执行与失败恢复")
    print("=" * 60)

    llm = LLMClient()
    tools = create_research_tools()
    sessions = SessionManager()
    trace = TraceLogger("research_demo")

    agent = PlannerExecutorAgent(
        llm_client=llm,
        tool_registry=tools,
        session_manager=sessions,
        trace_logger=trace,
    )

    task = "分析 /workspace/agent-system 项目的代码结构，并生成分析报告"
    print(f"任务: {task}\n")

    complexity = agent._task_complexity(task)
    print(f"复杂度: {complexity:.2f}")

    if complexity > 0.3:
        planner = Planner(llm_client=llm)
        plan = planner.plan(task)
        print(f"计划: {len(plan.nodes)} 个子任务")

        # 模拟执行
        for node_id in plan.get_execution_order():
            node = plan.nodes[node_id]
            print(f"  执行: {node.description}")
            plan.update_status(node_id, TaskStatus.COMPLETED, result={"status": "ok"})

        print(f"\n执行完成！所有 {len(plan.nodes)} 个子任务已完成")


def main():
    """主函数"""
    print("=" * 60)
    print("深度研究 Agent - Planner-Executor 演示")
    print("红岩网校 AI 部门 2026 暑期考核项目")
    print("=" * 60)

    demo_planning()
    demo_execution()

    print("\n" + "=" * 60)
    print("演示完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
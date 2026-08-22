"""
校园智能助手 - 综合示例应用

整合 Agent Runtime + MCP 工具系统 + Planner-Executor
实现一个完整的校园信息查询助手。

使用方法:
    python campus_assistant.py
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
from code.mcp.servers import CampusInfoServer, RepoAnalysisServer, DocSearchServer
from code.planner_executor import PlannerExecutorAgent, Planner, Executor, TaskDAG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def create_tools() -> ToolRegistry:
    """创建工具注册表"""
    registry = ToolRegistry()

    def calculator(expression: str) -> dict:
        """计算数学表达式"""
        try:
            result = eval(expression, {"__builtins__": {}}, {})
            return {"success": True, "result": result, "expression": expression}
        except Exception as e:
            return {"success": False, "error": str(e)}

    registry.register(
        Tool(
            name="calculator",
            description="计算数学表达式，支持加减乘除和括号",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "数学表达式，如 '2+3*4'",
                    }
                },
                "required": ["expression"],
            },
            function=calculator,
        )
    )

    def search_web(query: str) -> dict:
        """搜索网络信息"""
        return {
            "success": True,
            "query": query,
            "results": [
                {"title": f"搜索结果: {query}", "snippet": "模拟搜索结果..."},
            ],
        }

    registry.register(
        Tool(
            name="search_web",
            description="搜索网络信息，获取实时数据",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    }
                },
                "required": ["query"],
            },
            function=search_web,
        )
    )

    return registry


def demo_agent_runtime():
    """演示 Agent Runtime 基本功能"""
    print("\n" + "=" * 60)
    print("演示 1: Agent Runtime 基本功能")
    print("=" * 60)

    llm = LLMClient()
    tools = create_tools()
    sessions = SessionManager()
    trace = TraceLogger("agent_runtime_demo")

    agent = AgentRuntime(
        llm_client=llm,
        tool_registry=tools,
        session_manager=sessions,
        trace_logger=trace,
        max_steps=10,
        max_time_seconds=120,
    )

    print(f"已注册工具: {tools.list_names()}")
    print(f"LLM 模型: {os.getenv('MODEL_NAME', '未配置')}")
    print("Agent Runtime 初始化完成！")


def demo_mcp_system():
    """演示 MCP 工具系统"""
    print("\n" + "=" * 60)
    print("演示 2: MCP 工具系统")
    print("=" * 60)

    client = MCPClient()
    router = ToolRouter()

    campus_server = CampusInfoServer()
    repo_server = RepoAnalysisServer()
    doc_server = DocSearchServer()

    client.connect_server(campus_server)
    client.connect_server(repo_server)
    client.connect_server(doc_server)

    all_tools = client.list_all_tools()
    print(f"已连接 {len(client.servers)} 个 MCP Server")
    print(f"共发现 {len(all_tools)} 个工具")

    for server_name, tools in sorted(all_tools.items()):
        print(f"  [{server_name}]: {', '.join(t.name for t in tools)}")

    # 测试工具路由
    print("\n--- 工具路由测试 ---")
    task = "我想查询计算机学院的课程信息"
    selected = router.select_tools(task, all_tools, top_k=5)
    print(f"任务: {task}")
    print(f"推荐工具:")
    for s in selected[:3]:
        print(f"  - {s.tool_name} (分数: {s.score:.2f}, 理由: {s.reason})")

    # 测试工具调用
    print("\n--- 工具调用测试 ---")
    result = client.call_tool("campus-info", "search_courses", keyword="Python")
    if result.get("success"):
        courses = result.get("result", [])
        print(f"查询到 {len(courses)} 门课程")
        for c in courses[:3]:
            print(f"  - {c.get('name')}: {c.get('teacher')} ({c.get('credits')}学分)")
    else:
        print(f"调用失败: {result.get('error')}")

    # 健康检查
    print("\n--- 健康检查 ---")
    for name in client.servers:
        health = client.check_server_health(name)
        status = "✓ 正常" if health.get("healthy") else "✗ 异常"
        print(f"  [{name}]: {status}")


def demo_planner_executor():
    """演示 Planner-Executor"""
    print("\n" + "=" * 60)
    print("演示 3: Planner-Executor 任务规划")
    print("=" * 60)

    llm = LLMClient()
    tools = create_tools()
    sessions = SessionManager()
    trace = TraceLogger("planner_demo")

    agent = PlannerExecutorAgent(
        llm_client=llm,
        tool_registry=tools,
        session_manager=sessions,
        trace_logger=trace,
    )

    # 测试任务分解
    tasks = [
        "帮我分析这个项目的代码结构，统计代码行数，然后生成一份分析报告",
        "查询计算机学院的所有课程，找出学分最高的课程，并计算平均学分",
    ]

    for task in tasks:
        print(f"\n任务: {task}")
        complexity = agent._task_complexity(task)
        print(f"复杂度评估: {complexity:.2f}")

        if complexity > 0.3:
            planner = Planner(llm_client=llm)
            plan = planner.plan(task)
            print(f"计划包含 {len(plan.nodes)} 个子任务:")
            for node_id in plan.get_execution_order():
                node = plan.nodes[node_id]
                print(f"  [{node.status.value}] {node.description}")
        else:
            print("任务足够简单，跳过规划")


def main():
    """主函数"""
    print("=" * 60)
    print("校园智能助手 - Agent 系统演示")
    print("红岩网校 AI 部门 2026 暑期考核项目")
    print("=" * 60)

    demo_agent_runtime()
    demo_mcp_system()
    demo_planner_executor()

    print("\n" + "=" * 60)
    print("演示完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
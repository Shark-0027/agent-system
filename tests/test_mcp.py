"""
MCP 工具系统测试
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from code.framework.mcp.schema import ToolSchema, ParameterValidationError
from code.framework.mcp.server import MCPServer
from code.framework.mcp.client import MCPClient
from code.framework.mcp.registry import ToolRegistry
from code.framework.mcp.router import ToolRouter, SelectionResult
from code.framework.mcp.servers import CampusInfoServer, RepoAnalysisServer, DocSearchServer


class TestToolSchema(unittest.TestCase):
    """测试工具 Schema"""

    def test_basic_schema(self):
        schema = ToolSchema(
            name="test_tool",
            description="测试工具",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "输入文本"},
                    "count": {"type": "integer", "description": "数量"},
                },
                "required": ["text"],
            },
        )
        self.assertEqual(schema.name, "test_tool")
        self.assertEqual(schema.version, "1.0.0")

    def test_validate_valid_params(self):
        schema = ToolSchema(
            name="test",
            description="test",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "age": {"type": "integer"},
                },
                "required": ["name"],
            },
        )
        result = schema.validate_params({"name": "Alice", "age": 25})
        self.assertEqual(result["name"], "Alice")
        self.assertEqual(result["age"], 25)

    def test_validate_missing_required(self):
        schema = ToolSchema(
            name="test",
            description="test",
            parameters={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )
        with self.assertRaises(ParameterValidationError):
            schema.validate_params({})

    def test_validate_wrong_type(self):
        schema = ToolSchema(
            name="test",
            description="test",
            parameters={
                "type": "object",
                "properties": {"age": {"type": "integer"}},
                "required": ["age"],
            },
        )
        with self.assertRaises(ParameterValidationError):
            schema.validate_params({"age": "not_a_number"})

    def test_validate_enum(self):
        schema = ToolSchema(
            name="test",
            description="test",
            parameters={
                "type": "object",
                "properties": {
                    "color": {"type": "string", "enum": ["red", "green", "blue"]}
                },
                "required": ["color"],
            },
        )
        result = schema.validate_params({"color": "red"})
        self.assertEqual(result["color"], "red")

        with self.assertRaises(ParameterValidationError):
            schema.validate_params({"color": "yellow"})

    def test_default_values(self):
        schema = ToolSchema(
            name="test",
            description="test",
            parameters={
                "type": "object",
                "properties": {"count": {"type": "integer", "default": 10}},
            },
        )
        result = schema.validate_params({})
        self.assertEqual(result["count"], 10)

    def test_serialization(self):
        schema = ToolSchema(
            name="test",
            description="test",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
        d = schema.to_dict()
        restored = ToolSchema.from_dict(d)
        self.assertEqual(restored.name, "test")


class TestMCPServer(unittest.TestCase):
    """测试 MCP Server"""

    def setUp(self):
        self.server = MCPServer(name="test-server", version="1.0.0")

        def echo(text: str) -> str:
            return f"Echo: {text}"

        schema = ToolSchema(
            name="echo",
            description="回显工具",
            parameters={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
        self.server.register_tool(schema, echo)

    def test_server_info(self):
        self.assertEqual(self.server.name, "test-server")
        self.assertEqual(self.server.version, "1.0.0")

    def test_list_tools(self):
        tools = self.server.list_tools()
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "echo")

    def test_call_tool(self):
        result = self.server.call_tool("echo", text="hello")
        self.assertTrue(result["success"])
        self.assertEqual(result["result"], "Echo: hello")

    def test_call_nonexistent_tool(self):
        result = self.server.call_tool("nonexistent", text="hello")
        self.assertFalse(result["success"])

    def test_health_check(self):
        health = self.server.health_check()
        self.assertEqual(health["status"], "healthy")

    def test_tool_count(self):
        self.assertEqual(len(self.server.tools), 1)


class TestMCPClient(unittest.TestCase):
    """测试 MCP Client"""

    def setUp(self):
        self.client = MCPClient()

        self.server1 = MCPServer(name="server1", version="1.0.0")
        schema1 = ToolSchema(
            name="tool1",
            description="工具1",
            parameters={
                "type": "object",
                "properties": {"arg": {"type": "string"}},
                "required": ["arg"],
            },
        )
        self.server1.register_tool(schema1, lambda arg: f"result1: {arg}")

        self.server2 = MCPServer(name="server2", version="1.0.0")
        schema2 = ToolSchema(
            name="tool2",
            description="工具2",
            parameters={
                "type": "object",
                "properties": {"arg": {"type": "string"}},
                "required": ["arg"],
            },
        )
        self.server2.register_tool(schema2, lambda arg: f"result2: {arg}")

        self.client.connect_server(self.server1)
        self.client.connect_server(self.server2)

    def test_connect_servers(self):
        self.assertEqual(len(self.client.servers), 2)

    def test_list_all_tools(self):
        all_tools = self.client.list_all_tools()
        server_names = [t["server_name"] for t in all_tools]
        self.assertIn("server1", server_names)
        self.assertIn("server2", server_names)

    def test_call_tool(self):
        result = self.client.call_tool("server1", "tool1", arg="test")
        self.assertTrue(result["success"])
        self.assertEqual(result["result"], "result1: test")

    def test_call_nonexistent_server(self):
        result = self.client.call_tool("nonexistent", "tool1", arg="test")
        self.assertFalse(result["success"])

    def test_disconnect_server(self):
        self.client.disconnect_server("server1")
        self.assertEqual(len(self.client.servers), 1)

    def test_health_check(self):
        health = self.client.get_server("server1").health_check()
        self.assertEqual(health["status"], "healthy")


class TestServers(unittest.TestCase):
    """测试自定义 MCP Server"""

    def test_campus_info_server(self):
        server = CampusInfoServer()
        self.assertEqual(server.name, "campus-info")
        self.assertGreaterEqual(len(server.tools), 4)

        result = server.call_tool("search_courses", keyword="Python")
        self.assertTrue(result["success"])
        self.assertGreater(len(result["result"]), 0)

    def test_repo_analysis_server(self):
        server = RepoAnalysisServer()
        self.assertEqual(server.name, "repo-analysis")
        self.assertGreaterEqual(len(server.tools), 4)

    def test_doc_search_server(self):
        server = DocSearchServer()
        self.assertEqual(server.name, "doc-search")
        self.assertGreaterEqual(len(server.tools), 4)

        result = server.call_tool("search_docs", query="AI")
        self.assertTrue(result["success"])


class TestToolRouter(unittest.TestCase):
    """测试工具路由"""

    def setUp(self):
        self.router = ToolRouter()

    def test_selection_result(self):
        tool = ToolSchema(name="test_tool", description="test")
        result = SelectionResult(
            tool=tool,
            score=0.85,
            reason="最佳匹配",
            confidence=0.9,
        )
        self.assertEqual(result.tool.name, "test_tool")
        self.assertGreater(result.score, 0.8)

    def test_select_tools(self):
        all_tools = [
            ToolSchema(name="search_courses", description="搜索课程"),
            ToolSchema(name="get_teacher", description="获取教师信息"),
            ToolSchema(name="calculate", description="数学计算"),
        ]
        results = self.router.select_tools("我想查询课程", all_tools, top_k=3)
        self.assertGreater(len(results), 0)

    def test_rank_by_score(self):
        results = [
            SelectionResult(ToolSchema(name="a", description=""), 0.5, "", 0.5),
            SelectionResult(ToolSchema(name="b", description=""), 0.9, "", 0.9),
            SelectionResult(ToolSchema(name="c", description=""), 0.3, "", 0.3),
        ]
        ranked = sorted(results, key=lambda x: x.score, reverse=True)
        self.assertEqual(ranked[0].tool.name, "b")
        self.assertEqual(ranked[-1].tool.name, "c")


if __name__ == "__main__":
    unittest.main()
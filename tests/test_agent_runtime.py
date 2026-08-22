"""
Agent Runtime 测试
"""

import os
import sys
import unittest
import tempfile
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from code.agent_runtime.exceptions import (
    AgentException, ToolNotFoundException, ToolExecutionException,
    InvalidToolParameterException, ModelCallException,
    MaxStepsExceededException, TimeoutException, SessionNotFoundException,
)
from code.agent_runtime.tools import Tool, ToolRegistry
from code.agent_runtime.state import StateManager
from code.agent_runtime.session import SessionManager
from code.agent_runtime.trace import TraceLogger


class TestExceptions(unittest.TestCase):
    """测试异常类"""

    def test_agent_exception_base(self):
        exc = AgentException("测试错误", details={"key": "value"})
        self.assertEqual(str(exc), "测试错误 (details: {'key': 'value'})")
        self.assertEqual(exc.details, {"key": "value"})

    def test_tool_not_found(self):
        exc = ToolNotFoundException("calculator", details={"available": ["add"]})
        self.assertEqual(exc.tool_name, "calculator")
        self.assertIn("calculator", str(exc))

    def test_tool_execution(self):
        exc = ToolExecutionException("calculator", "division by zero")
        self.assertEqual(exc.tool_name, "calculator")
        self.assertIn("division by zero", str(exc))

    def test_invalid_tool_parameter(self):
        exc = InvalidToolParameterException("calculator", "expression")
        self.assertEqual(exc.tool_name, "calculator")
        self.assertEqual(exc.invalid_params, "expression")

    def test_model_call(self):
        exc = ModelCallException("connection timeout", attempt=3)
        self.assertEqual(exc.attempt, 3)
        self.assertIn("connection timeout", str(exc))

    def test_max_steps(self):
        exc = MaxStepsExceededException(10, 5)
        self.assertEqual(exc.current_step, 10)
        self.assertEqual(exc.max_steps, 5)

    def test_timeout(self):
        exc = TimeoutException(300, 301)
        self.assertEqual(exc.elapsed_seconds, 300)
        self.assertEqual(exc.max_seconds, 301)

    def test_session_not_found(self):
        exc = SessionNotFoundException("session-123")
        self.assertEqual(exc.session_id, "session-123")


class TestToolRegistry(unittest.TestCase):
    """测试工具注册表"""

    def setUp(self):
        self.registry = ToolRegistry()

        def echo(text: str) -> dict:
            return {"echo": text}

        self.tool = Tool(
            name="echo",
            description="回显输入文本",
            parameters={
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "要回显的文本"}
                },
                "required": ["text"],
            },
            function=echo,
        )

    def test_register_tool(self):
        self.registry.register(self.tool)
        self.assertIn("echo", self.registry.list_names())

    def test_register_duplicate(self):
        self.registry.register(self.tool)
        with self.assertRaises(ValueError):
            self.registry.register(self.tool)

    def test_unregister_tool(self):
        self.registry.register(self.tool)
        self.registry.unregister("echo")
        self.assertNotIn("echo", self.registry.list_names())

    def test_unregister_nonexistent(self):
        with self.assertRaises(ToolNotFoundException):
            self.registry.unregister("nonexistent")

    def test_get_tool(self):
        self.registry.register(self.tool)
        tool = self.registry.get("echo")
        self.assertEqual(tool.name, "echo")

    def test_get_nonexistent(self):
        with self.assertRaises(ToolNotFoundException):
            self.registry.get("nonexistent")

    def test_list_all(self):
        self.registry.register(self.tool)

        def add(a: int, b: int) -> dict:
            return {"result": a + b}

        tool2 = Tool(
            name="add",
            description="加法",
            parameters={
                "type": "object",
                "properties": {
                    "a": {"type": "integer"},
                    "b": {"type": "integer"},
                },
                "required": ["a", "b"],
            },
            function=add,
        )
        self.registry.register(tool2)
        self.assertEqual(len(self.registry.list_all()), 2)

    def test_search_by_description(self):
        self.registry.register(self.tool)
        results = self.registry.search_by_description("回显")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].name, "echo")

    def test_to_openai_format(self):
        self.registry.register(self.tool)
        fmt = self.registry.get_tools_openai_format()
        self.assertEqual(len(fmt), 1)
        self.assertEqual(fmt[0]["function"]["name"], "echo")

    def test_tool_execute(self):
        self.registry.register(self.tool)
        result = self.registry.get("echo").execute(text="hello")
        self.assertEqual(result, {"echo": "hello"})

    def test_tool_execute_invalid_params(self):
        self.registry.register(self.tool)
        with self.assertRaises(InvalidToolParameterException):
            self.registry.get("echo").execute(wrong_param="value")


class TestStateManager(unittest.TestCase):
    """测试状态管理"""

    def setUp(self):
        self.state = StateManager()

    def test_add_message(self):
        self.state.add_message("user", "hello")
        msgs = self.state.get_messages()
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[0]["content"], "hello")

    def test_add_tool_call(self):
        self.state.add_tool_call(
            {"tool_name": "calculator", "arguments": {"expr": "2+2"}, "call_id": "call_1"}
        )
        calls = self.state.get_latest_tool_calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["tool_name"], "calculator")

    def test_add_observation(self):
        self.state.add_observation({"result": 42})
        self.assertEqual(len(self.state.observations), 1)

    def test_serialization(self):
        self.state.add_message("user", "test")
        d = self.state.to_dict()
        restored = StateManager()
        restored.from_dict(d)
        self.assertEqual(len(restored.get_messages()), 1)

    def test_json_serialization(self):
        self.state.add_message("user", "test")
        json_str = self.state.to_json()
        restored = StateManager()
        restored.from_json(json_str)
        self.assertEqual(len(restored.get_messages()), 1)

    def test_snapshot_restore(self):
        self.state.add_message("user", "msg1")
        snap = self.state.snapshot()
        self.state.add_message("user", "msg2")
        self.state.restore(snap)
        self.assertEqual(len(self.state.get_messages()), 1)


class TestSessionManager(unittest.TestCase):
    """测试会话管理"""

    def setUp(self):
        self.manager = SessionManager()

    def test_create_session(self):
        sid = self.manager.create_session()
        self.assertIsNotNone(sid)
        self.assertIn(sid, self.manager.list_sessions())

    def test_create_session_with_id(self):
        sid = self.manager.create_session("my-session")
        self.assertEqual(sid, "my-session")

    def test_session_isolation(self):
        s1 = self.manager.create_session()
        s2 = self.manager.create_session()
        state1 = self.manager.get_session(s1)
        state2 = self.manager.get_session(s2)
        state1.add_message("user", "msg1")
        self.assertEqual(len(state2.get_messages()), 0)

    def test_delete_session(self):
        sid = self.manager.create_session()
        self.manager.delete_session(sid)
        self.assertNotIn(sid, self.manager.list_sessions())

    def test_get_nonexistent_session(self):
        with self.assertRaises(SessionNotFoundException):
            self.manager.get_session("nonexistent")

    def test_get_or_create(self):
        sid = self.manager.get_or_create_session("new-session")
        self.assertEqual(sid, "new-session")
        state = self.manager.get_session(sid)
        self.assertIsNotNone(state)


class TestTraceLogger(unittest.TestCase):
    """测试 Trace 日志"""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.trace = TraceLogger("test_trace", log_file=os.path.join(self.temp_dir, "trace.log"))

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_log_step(self):
        self.trace.log_step(1, "llm_call", {"model": "gpt-4"})
        events = self.trace.get_trace()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_type"], "llm_call")

    def test_multiple_events(self):
        self.trace.log_step(1, "llm_call", {})
        self.trace.log_step(1, "tool_call", {"tool": "calc"})
        self.trace.log_step(1, "tool_result", {"result": 42})
        self.assertEqual(len(self.trace.get_trace()), 3)

    def test_save_trace(self):
        self.trace.log_step(1, "llm_call", {})
        filepath = os.path.join(self.temp_dir, "saved_trace.json")
        self.trace.save_trace(filepath)
        self.assertTrue(os.path.exists(filepath))

    def test_trace_summary(self):
        self.trace.log_step(1, "llm_call", {})
        self.trace.log_step(1, "tool_call", {})
        self.trace.log_step(1, "error", {"msg": "test error"})
        summary = self.trace.get_trace_summary()
        self.assertEqual(summary["total_events"], 3)
        self.assertEqual(summary["event_counts"]["llm_call"], 1)
        self.assertEqual(summary["event_counts"]["error"], 1)


if __name__ == "__main__":
    unittest.main()
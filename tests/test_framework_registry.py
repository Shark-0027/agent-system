"""统一工具注册协议（framework.registry）的单元测试。"""

from code.framework.registry import (
    StandardRegistry,
    create_registry,
    register_tool as unified_register,
)


def _agent_tool(name="avg_calc", desc="计算两数平均"):
    from code.framework.agent_runtime import Tool
    return Tool(name=name, description=desc, parameters={},
                function=lambda a=0, b=0: (a + b) / 2)


# ---------------------------------------------------------------------------
# 协议必须暴露的四个能力（且统一注册入口在各类注册表上真实可用）
# ---------------------------------------------------------------------------
def test_all_registries_expose_unified_protocol():
    kinds = ["standard", "executor", "agent", "mcp"]
    for kind in kinds:
        reg = create_registry(kind)
        for m in ("register_tool", "get", "list_names", "find_tool"):
            assert hasattr(reg, m), f"{kind} registry missing protocol method {m}"


# 统一入口 register_tool 必须能在每类注册表上按 (name, handler, description) 注册成功
def test_unified_register_works_on_all_kinds():
    for kind in ("standard", "executor", "agent", "mcp"):
        reg = create_registry(kind)
        unified_register(
            reg,
            name="avg_calc",
            handler=lambda **k: 3.0,
            description="计算两数平均",
        )
        assert reg.list_names() == ["avg_calc"], f"{kind} did not register via protocol"
        # get 返回"工具句柄"（agent 层为 Tool 包装对象，其余层为 callable），非空即可
        assert reg.get("avg_calc") is not None, f"{kind}.get returned None"
        assert reg.find_tool("avg_calc") == "avg_calc", f"{kind}.find_tool failed"


# ---------------------------------------------------------------------------
# StandardRegistry（默认标准实现）
# ---------------------------------------------------------------------------
def test_standard_register_find_execute():
    reg = create_registry("standard")
    unified_register(reg, name="avg_calc", handler=_agent_tool().function, description="求两数平均")
    assert reg.list_names() == ["avg_calc"]
    assert reg.find_tool("avg_calc 帮我算平均") == "avg_calc"
    assert callable(reg.get("avg_calc"))


# ---------------------------------------------------------------------------
# agent_runtime 注册表（面向 Tool 对象）
# ---------------------------------------------------------------------------
def test_agent_registry_accepts_tool_object():
    reg = create_registry("agent")
    unified_register(reg, _agent_tool())
    assert reg.list_names() == ["avg_calc"]
    assert reg.find_tool("平均") == "avg_calc"
    assert reg.get("avg_calc").execute(a=2, b=4) == 3.0


# ---------------------------------------------------------------------------
# planner_executor 注册表（保障 _select_tool 的 find_tool 链路）
# ---------------------------------------------------------------------------
def test_executor_registry_unified_access():
    reg = create_registry("executor")
    unified_register(reg, name="sum_calc", handler=lambda *a, **k: None, description="求和")
    assert reg.list_names() == ["sum_calc"]
    assert reg.find_tool("sum_calc 对销售数据求和") == "sum_calc"
    assert reg.list_tools()[0]["name"] == "sum_calc"


# ---------------------------------------------------------------------------
# mcp 注册表：查询能力（注册经 server 侧 register_tool(schema)）
# ---------------------------------------------------------------------------
def test_mcp_registry_query_protocol_empty():
    reg = create_registry("mcp")
    assert reg.list_names() == []
    assert reg.find_tool("anything") is None


# ---------------------------------------------------------------------------
# 通配入口：传 Tool 对象或 (name, handler, desc)
# ---------------------------------------------------------------------------
def test_unified_register_tool_edge():
    reg = StandardRegistry()
    unified_register(reg, _agent_tool())
    assert reg.list_names() == ["avg_calc"]
    reg2 = StandardRegistry()
    unified_register(reg2, name="x", handler=lambda **k: None, description="d")
    assert reg2.list_names() == ["x"]


def test_standard_register_duplicate_raises():
    reg = StandardRegistry(overwrite=False)
    unified_register(reg, name="a", handler=lambda **k: None)
    try:
        unified_register(reg, name="a", handler=lambda **k: None)
        assert False, "expected ValueError on duplicate"
    except ValueError:
        pass
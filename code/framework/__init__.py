"""Agent 系统框架层。

通用、可复用的 Agent 底层基础设施：
- agent_runtime:   Agent Loop 引擎、LLM 客户端、工具注册、状态/会话/追踪
- mcp:             MCP 与工具系统（Client/Server/Registry/Router）
- planner_executor:任务规划、DAG、并行调度、失败恢复与计划验证
- evaluation:      评测指标与任务集合
- examples:        基于框架层的使用示例
"""
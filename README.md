# 可靠 AI Agent 系统开发

红岩网校 AI 部门 2026 暑期考核项目

> **公共主线：Agent Runtime** | **选题一：MCP 与工具系统** | **选题三：Planner–Executor 与任务规划**

---

## 项目概述

本项目实现了一个可靠、可追踪、可扩展的 AI Agent 系统，采用"一条公共主线 + 两个选做方向"的架构：

- **Agent Runtime**：模型调用、工具系统、Agent Loop、状态管理、异常处理、Trace 追踪、自动评测
- **MCP 与工具系统**：MCP Client/Server 架构、工具注册发现、Schema 校验、智能工具路由、3 个自定义 MCP Server
- **Planner–Executor**：任务分解、依赖建模、动态 DAG、并行调度、局部重规划、计划质量验证

## 项目结构

```
agent-system/
├── README.md
├── pyproject.toml
├── uv.lock
├── requirements.txt
├── .env.example
├── .gitignore
├── code/
│   ├── __init__.py
│   ├── agent_runtime/          # 公共主线：Agent Runtime
│   │   ├── __init__.py
│   │   ├── core.py             # Agent Loop 核心引擎
│   │   ├── llm.py              # LLM 客户端（OpenAI 兼容）
│   │   ├── tools.py            # 工具注册与管理
│   │   ├── state.py            # 状态管理
│   │   ├── session.py          # 会话隔离
│   │   ├── trace.py            # 运行追踪
│   │   └── exceptions.py       # 异常类体系
│   ├── mcp/                    # 选题一：MCP 与工具系统
│   │   ├── __init__.py
│   │   ├── client.py           # MCP Client
│   │   ├── server.py           # MCP Server 基类
│   │   ├── registry.py         # 工具注册表
│   │   ├── schema.py           # 工具参数 Schema
│   │   ├── router.py           # 智能工具路由
│   │   └── servers/            # 自定义 MCP Server
│   │       ├── campus_info.py  # 校园信息查询
│   │       ├── repo_analysis.py # 代码仓库分析
│   │       └── doc_search.py   # 文档检索
│   ├── planner_executor/       # 选题三：Planner–Executor
│   │   ├── __init__.py
│   │   ├── planner.py          # 任务规划器
│   │   ├── executor.py         # 执行器 + 顶层调度
│   │   ├── dag.py              # 动态 DAG 任务图
│   │   ├── verifier.py         # 计划质量验证
│   │   └── scheduler.py        # 并行调度器
│   ├── evaluation/             # 评测系统
│   │   ├── __init__.py
│   │   ├── tasks.py            # 20+ 评测任务
│   │   └── metrics.py          # 评价指标
│   └── examples/               # 示例应用
│       ├── campus_assistant.py # 校园智能助手
│       └── research_agent.py   # 深度研究 Agent
└── tests/                      # 测试
    ├── test_agent_runtime.py
    ├── test_mcp.py
    └── test_planner_executor.py
```

## 快速开始

### 环境配置

```bash
# 克隆仓库
git clone https://github.com/Shark-0027/agent-system.git
cd agent-system

# 使用 uv 安装依赖（推荐）
uv sync

# 或者使用 pip
pip install -r requirements.txt

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 API Key
```

### 运行示例

```bash
# 校园智能助手
python code/examples/campus_assistant.py

# 深度研究 Agent
python code/examples/research_agent.py
```

### 运行测试

```bash
# 运行测试（uv）
uv run python -m unittest tests.test_agent_runtime tests.test_mcp tests.test_planner_executor -v
```

## 核心模块

### 1. Agent Runtime（公共主线）

Agent Runtime 是 Agent 系统的运行基础，负责组织模型推理、工具调用、执行结果反馈和任务终止。

**核心能力：**
- LLM 适配层：支持 OpenAI 兼容 API，含重试和指数退避
- 工具注册表：参数校验、JSON Schema 支持、描述搜索
- Agent Loop：ReAct 模式，多轮推理 + 工具调用
- 状态管理：消息历史、工具调用、Observation 的完整记录
- 会话隔离：不同 Session 完全独立
- Trace 追踪：完整运行日志，支持 JSON 导出和回放
- 异常处理：工具重试/降级、模型重试、非法工具名处理

**创新点：**
- 重复工具调用检测（连续 3 次相同调用自动终止）
- 死循环检测（连续 5 步无进展自动终止）
- 工具调用重试和降级机制
- Token/步数/时间预算控制

### 2. MCP 与工具系统（选题一）

实现完整的 MCP Client/Server 架构，统一管理工具的注册、发现、选择和调用。

**核心能力：**
- MCP Client：多 Server 连接管理，统一调用接口
- MCP Server 基类：工具注册、超时控制、健康检查
- ToolSchema：完整参数校验、类型检查、枚举约束
- ToolRegistry：工具发现、元数据管理、搜索
- ToolRouter：智能工具选择（语义相似度 + 历史成功率）

**自定义 MCP Server：**
| Server | 工具数 | 功能 |
|--------|--------|------|
| campus-info | 5 | 课程搜索、教师查询、教室查询、课表获取、学院列表 |
| repo-analysis | 5 | 代码结构分析、行数统计、函数搜索、依赖检查、文件列表 |
| doc-search | 5 | 文档索引、TF-IDF 搜索、文档获取、主题列表、文档摘要 |

**创新点：**
- 基于任务描述动态选择工具
- 工具排序（语义相似度 70% + 历史成功率 30%）
- 分层工具检索（>20 工具时先粗筛再精排）
- 工具调用成本因子调节

### 3. Planner–Executor（选题三）

将任务规划与具体执行分离，使 Agent 能拆解复杂任务并按依赖关系并行执行。

**核心能力：**
- Planner：LLM 驱动的任务分解，自动识别并行子任务
- Executor：子任务执行、失败处理、自动结果验证
- TaskDAG：动态依赖图，循环检测，拓扑排序
- PlanVerifier：六维度计划质量评分（0-100）
- ParallelScheduler：并行调度，三种失败策略
- 局部重规划：失败时只修改影响的任务

**创新点：**
- 动态 DAG（执行中可调整依赖）
- 局部重规划（非全部重来）
- 计划质量自动评分和修正
- 按任务复杂度自动决定是否启用规划
- 历史计划缓存与复用

## 评测系统

包含 20+ 自动评测任务，覆盖 6 大类别：

| 类别 | 任务数 | 覆盖内容 |
|------|--------|----------|
| 工具调用 | 5 | 参数校验、错误处理、多工具协作 |
| Agent Loop | 5 | 单步/多步执行、步数/时间限制 |
| 异常处理 | 5 | 重试、降级、模型错误、格式错误 |
| 状态管理 | 3 | 消息记录、会话隔离、序列化 |
| Trace 追踪 | 2 | 完整记录、事件类型覆盖 |
| 创新点 | 3 | 重复检测、死循环检测、退避机制 |

## 技术栈

- **语言**：Python 3.10+
- **LLM**：OpenAI 兼容 API（GPT-4o / DeepSeek 等）
- **依赖**：openai, jsonschema, pydantic, python-dotenv

## 许可证

本项目仅用于红岩网校 AI 部门考核目的。

---

**参考项目**：[datawhalechina/hello-agents](https://github.com/datawhalechina/hello-agents) — 从零开始构建智能体
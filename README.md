# AI 数据分析工作台（Agent System）

基于自研 Agent 框架构建的 **端到端 CSV 数据分析平台**。上传 CSV + 一句话描述分析目标，系统自动完成数据加载、清洗、探索、特征工程、建模/绘图，最终生成一份 Markdown 分析报告。底层由可扩展的 Agent Runtime / MCP 工具系统 / Planner-Executor 规划执行框架驱动。

---

## 特性

- **一句话全流程分析**：LLM 自动规划分析路径，从数据到洞察全程无需手动干预
- **工作台交互（双模式）**：既可走「全流程分析」一键自动编排，也可切到「工作台」分步手动执行单个工具，两个入口在顶部导航自由切换
- **自然语言查数**：用中文提问即可实现智能查询、聚合与洞察（NL2Query / NL2Insight）
- **手动工具箱**：工作台侧栏按 9 大类分组提供全部分析工具，工具支持 ⚙ 参数展开、增量执行、结果栈回看
- **可视化报告**：自动生成图表 + Markdown 报告，支持单独下载产物（报告 / 清洗数据 / 图表 / 原始数据）
- **可观测性**：前台实时进度、结构化执行轨迹（`trace.json`）回放（DAG + 日志）
- **双模式运行**：LLM 智能编排 / 本地规则模式（无 LLM Key 时自动降级）
- **数据答疑**：分析完成后，可就本次分析产物向 AI 提问（报告页内置数据答疑面板）
- **安全隔离**：每次运行独立工作区，原始数据与清洗数据分开存储
- **可扩展框架**：统一工具注册协议，工具可在 Runtime / Planner-Executor / MCP 三层无缝接入

---

## 架构

```
┌──────────────────────────────────────────────────────────────┐
│                  Web 工作台（SPA 双模式）                       │
│   🚀 全流程分析(上传+目标→运行→报告)   🛠 工作台(工具箱+查数)   │
└───────────────────────────────┬──────────────────────────────┘
                                │ HTTP /api/*
┌───────────────────────────────▼──────────────────────────────┐
│                    CSV Agent 后端（FastAPI）                   │
│  上传/样例 · 分步工具 · 全流程分析 · 进度/轨迹 · 报告/图表/下载   │
│  CsvAgent(编排入口) → Workspace(工作区) → MemoryStore(SQLite)   │
└───────────────────────────────┬──────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────┐
│                   Agent 框架层（可扩展、可复用）                │
│  Agent Runtime ── MCP 工具系统 ── Planner-Executor            │
│  统一工具注册协议（ToolRegistryProtocol） + Trace 追踪 + 评测      │
└──────────────────────────────────────────────────────────────┘
```

## 项目结构

```
agent-system/
├── code/
│   ├── framework/                 # ══ Agent 框架层（通用、可复用）══
│   │   ├── registry.py            # 统一工具注册协议
│   │   ├── agent_runtime/         # Agent Loop、LLM 客户端、状态/会话/Trace
│   │   ├── mcp/                   # MCP Client/Server、工具路由、注册表
│   │   ├── planner_executor/      # 任务规划、动态 DAG、并行调度、执行器、验证器
│   │   ├── evaluation/            # 评测系统（任务 + 指标）
│   │   └── examples/              # 框架层示例应用
│   └── workbench/
│       └── csv_agent/             # ══ CSV 数据分析工作台应用层 ══
│           ├── api.py             # FastAPI 后端（全部 /api 端点）
│           ├── orchestrator.py    # CsvAgent 编排入口
│           ├── bridge.py          # 工具双注册（MCP 协议 + Planner-Executor）
│           ├── workspace.py       # 独立工作区数据总线
│           ├── sandbox.py         # 子进程隔离执行沙箱
│           ├── memory.py          # SQLite 记忆/历史
│           ├── datagen.py         # 样例数据生成（demo/测试用）
│           ├── cli.py             # 命令行入口（analyze / sample）
│           ├── servers/           # 数据分析 MCP Server（数据加载/处理/统计/可视化/建模/查询/报告）
│           └── web/               # 前端 SPA（index.html / app.css / app.js）
└── tests/                         # 单测（同一命令全量运行）
```

## 快速开始

### 1. 安装依赖

```bash
cd agent-system
uv sync          # 推荐（也可 pip install -r requirements.txt）
```

### 2. 配置 LLM（可选）

```bash
cp .env.example .env
# 编辑 .env 填入 API Key；未配置时将自动降级为本地规则模式
```

后端通过 `.env` 读取 `OPENAI_API_KEY / OPENAI_BASE_URL / MODEL_NAME`，**模型名不硬编码、一律来自 `.env`**。前端「LLM 配置」弹窗也可临时覆盖 key / base_url / model_name，仅存于当前服务进程。

### 3. 启动 Web 工作台

```bash
uv run uvicorn code.workbench.csv_agent.api:app --reload --port 8000
```

浏览器访问 <http://127.0.0.1:8000/>，顶部导航提供两个模式：

| 模式 | 说明 |
|---|---|
| **🚀 全流程分析** | 首页上传 CSV + 填写一句话目标 → 点「开始分析」，Agent 自动规划 DAG 并执行清洗/统计/建模 → 完成后以 3 个页签查看：报告&答疑 / 结果（图表+数据） / 执行轨迹 |
| **🛠 工作台** | 上传 CSV 后进入三栏界面：左侧 9 类工具箱（支持 ⚙ 参数展开）· 中间数据预览 / 工具结果 · 右侧自然语言查数。可增量手动分析，不强制跑全流程 |

每个上传都会创建一个独立运行（RID），侧边栏「历史运行」可随时回看；已分析完成的运行同样可切到「工作台」继续手动加工。

### 4. CLI 用法（无前端）

```bash
uv run python -m code.workbench.csv_agent.cli sample /tmp/s.csv
uv run python -m code.workbench.csv_agent.cli analyze /tmp/s.csv "分析销售额影响因素并生成报告" --no-llm
```

### 5. 运行测试

```bash
uv run pytest -q
```

---

## 后端 API

启动后接口前缀为 `http://<host>:8000`。

### 系统与 LLM 配置
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/health` | 服务状态与运行模式 `{status, mode: llm\|local, mode_label}` |
| GET | `/api/llm/config` | 读取当前 LLM 配置（不回显 api_key） |
| POST | `/api/llm/config` | 设置/清除前端 LLM 覆盖（api_key/base_url/model_name 白名单） |

### 数据接入与运行管理
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/run` | 上传 CSV 新建运行（multipart `file`），返回数据表预览 |
| GET | `/api/sample` | 生成样例销量数据并新建运行（供演示/测试） |
| GET | `/api/runs` | 列出全部运行（title / created_at / mode / 产物标记） |
| GET | `/api/run/{rid}/info` | 单运行详情（行数列数 / schema / 产物标记） |
| GET | `/api/run/{rid}/data?which=` | 数据预览，`which=auto\|input\|cleaned` 指定数据版本 |

### 分析与工具
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/tools` | 列出可用分析工具 |
| POST | `/api/run/{rid}/tool` | 在当前运行上执行单个工具（工作台手动工具箱底层的调用） |
| POST | `/api/run/{rid}/analyze` | 全流程异步分析（`async_mode=true` 后台执行） |
| GET | `/api/run/{rid}/progress` | 查询异步分析实时进度 |
| GET | `/api/run/{rid}/dag` | 读取规划 DAG 节点 + 实时事件（前端 DAG/日志渲染用） |
| GET | `/api/run/{rid}/trace` | 返回结构化执行轨迹（规划/调度/工具事件与耗时） |
| GET | `/api/run/{rid}/llm-mode` | 单次运行实际采用的 LLM 模式 |
| POST | `/api/analyze` | 上传并立即分析（一次性合并端点，multipart `goal`+`file`） |

### 结果查看与下载
| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/report/{run_id}` | 返回 Markdown 报告文本 |
| GET | `/api/run/{rid}/charts` | 列出图表 |
| GET | `/api/run/{rid}/chart?name=` | 读取单张图表 PNG |
| GET | `/api/run/{rid}/chart_data?name=` | 读取图表结构化数据（Plotly 交互式渲染用） |
| GET | `/api/run/{rid}/data?which=cleaned\|input` | 下载清洗后 / 原始数据 CSV |
| GET | `/api/run/{rid}/download?name=` | 下载工作区产物（report.md / cleaned.csv / input.csv 等） |
| GET | `/api/run/{rid}/bundle` | 打包全部产物为 Zip |
| GET | `/api/history` | 历史分析记录（支持 keyword 检索） |
| GET / PUT | `/api/preferences` | 读取 / 设置用户偏好 |

### 问答与洞察
| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/run/{rid}/chat` | 数据答疑：基于本次分析产物回答中文问题（LLM 优先 + 规则兜底） |
| POST | `/api/run/{rid}/explain` | 对单次工具执行结果生成中文解读（LLM 优先） |
| GET | `/api/run/{rid}/suggest-goals` | 基于数据列给出后续可做的分析方向建议 |
| POST | `/api/run/{rid}/explore` | 对当前运行数据做一次探索性分析 |

---

## 可用分析工具

| 工具 | 说明 |
|---|---|
| `csv_load` / `data_summary` | 数据加载 / 数据概览 |
| `data_quality` / `data_clean` | 数据质量体检 / 数据清洗 |
| `feature_engineer` / `feature_select` | 特征工程 / 特征选择 |
| `eda_plot` | 可视化出图 |
| `corr_analysis` / `hypo_test` / `regression_fit` / `time_series_feat` / `time_series_forecast` / `cluster_profile` / `anomaly_detect` / `dist_fit` / `pca_decompose` / `ab_test` / `sample_size_calc` | 统计分析（相关性/假设检验/回归/时序/预测/聚类/离群点/分布拟合/主成分/A-B 实验/样本量） |
| `model_suggest` / `model_train` / `model_classify` | 建模建议 / 模型训练 / 模型分类 |
| `nl_filter` / `nl_agg` / `nl_insight` | 自然语言查数 / 分组聚合 / 智能洞察 |
| `missing_pattern` / `table_join` | 缺失模式分析 / 多表关联 |
| `report_generate` | 生成 Markdown 报告 |

---

## 框架层能力

### Agent Runtime（公共主线）
LLM 适配（重试 + 指数退避）、工具注册表、ReAct Agent Loop、状态/会话隔离、Trace 追踪、异常处理降级，以及重复调用检测、死循环检测、预算控制等创新机制。

### MCP 与工具系统
MCP Client/Server 架构、ToolSchema 校验、ToolRegistry 发现、智能工具路由（语义相似度 + 历史成功率）；内置 `campus-info` / `repo-analysis` / `doc-search` 三个示例 Server。

### Planner–Executor
LLM 驱动的任务分解、动态 DAG、并行调度（多失败策略）、局部重规划、六维计划质量评分、历史计划缓存复用。

### 统一工具注册协议
`ToolRegistryProtocol` 定义了 `register_tool / get / list_names / find_tool` 标准接口，`create_registry(kind)` 工厂动态实例化协议兼容的注册表，使 Runtime / Planner-Executor / MCP 三层的工具接入保持一致、可扩展。

---

## 技术栈

- **语言**：Python 3.10+
- **框架**：FastAPI · Agent Runtime · MCP · Planner-Executor
- **前端**：原生 HTML / CSS / JS 单页应用（Design Token 驱动，浅色主题）
- **数据**：pandas · numpy · scikit-learn · statsmodels · matplotlib · xgboost
- **依赖管理**：uv

## 环境变量

| 变量 | 说明 |
|---|---|
| `OPENAI_API_KEY` | LLM API Key |
| `OPENAI_BASE_URL` | LLM API Base URL |
| `MODEL_NAME` | LLM 模型名（由 `.env` 提供，不硬编码） |
| `MCP_SERVER_TIMEOUT` / `MCP_MAX_RETRIES` | MCP 超时/重试 |
| `AGENT_MAX_STEPS` / `AGENT_MAX_TIME_SECONDS` / `AGENT_ENABLE_TRACE` / `AGENT_TRACE_DIR` | Agent 运行预算与轨迹目录 |
| `PLANNER_MAX_SUBTASKS` / `PLANNER_ENABLE_AUTO_PLAN` / `EXECUTOR_MAX_WORKERS` | 规划/调度配置 |
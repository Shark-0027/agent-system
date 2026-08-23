# CSV 数据分析 Agent — 后端设计规格

> 考核方向：公共主线 Agent Runtime + 选题三 Planner–Executor（主攻）
> 辅助融合：MCP 工具系统 / Agent Memory / Sandbox 安全
> 日期：2026-08-23
> 交付范围：**本轮只做后端**（CLI + FastAPI + 评测 + 记忆），前端另开一轮精修 UI。

---

## 1. 目标

用户上传 CSV 文件并给出自然语言分析目标，Agent 自动完成全流程数据分析并输出 Markdown 报告（含数据概览、清洗记录、EDA 图表、特征工程、建模建议、可复现代码）。

**驱动接口目标（CLI）：**
```
python -m csv_agent.cli analyze data.csv "分析销售数据，找出影响销售额的因素并给预测模型建议"
```

**服务接口目标（FastAPI）：**
- `POST /api/upload` — 上传 CSV，返回 `file_id`
- `POST /api/plan` — 输入 `file_id` + `goal`，运行 Planner，返回 DAG
- `POST /api/execute` — 执行计划，流式/轮询返回执行状态与 Trace
- `GET /api/report/{run_id}` — 返回 Markdown 报告 + 图表元数据
- `GET /api/trace/{run_id}` — 返回完整 Trace

## 2. 架构

```
┌─ code/csv_agent/
│  ├─ servers/                  # 5 个数据分析 MCP Server（复用 code.mcp.MCPServer）
│  │   data_loader.py           #   csv_load / data_summary
│  │   data_processor.py        #   data_clean / feature_engineer
│  │   visualizer.py            #   eda_plot
│  │   model_trainer.py         #   model_train / model_suggest
│  │   report_generator.py      #   report_generate
│  ├─ workspace.py              # 单次分析隔离工作目录
│  ├─ memory.py                 # SQLite：用户偏好 + 分析历史
│  ├─ bridge.py                 # MCP 工具双注册进 ToolRegistry（供 Executor）
│  ├─ orchestrator.py           # 组装 MCPClient + ToolRegistry + PlannerExecutorAgent + Memory
│  ├─ report.py                 # Markdown 报告渲染
│  ├─ sandbox.py                # 子进程隔离 + 超时执行
│  ├─ cli.py                    # 命令行入口
│  └─ api.py                    # FastAPI 入口
└─ code/evaluation/             # 评测：20+ 任务 + 基线对照
docs/superpowers/specs/         # 本规格
tests/test_csv_agent*.py        # 后端单元测试
```

复用现有包：`code.agent_runtime`（LLMClient/Tool/ToolRegistry/SessionManager/TraceLogger）、`code.mcp`（MCPServer/MCPClient/ToolSchema）、`code.planner_executor`（Planner/PlanVerifier/ParallelScheduler/PlannerExecutorAgent/TaskDAG/TaskNode）。

## 3. 核心设计决策

### 3.1 Workspace 驱动的数据共享（主线数据总线）
每次分析创建独立工作目录：
```
workspace/
  input.csv        # 用户上传原始文件（csv_load 定位）
  cleaned.csv      # 清洗后
  train.csv        # 建模训练集
  charts/*.png     # EDA 图（分布/箱线/相关性热力图）
  feat_importance.json
  model_metrics.json
  report.md        # 最终报告
  repro.py         # 可复现代码
```
工具之间不直接传 DataFrame，而是读写工作区文件。解决：中间结果管理、回退、上下文/Token 爆炸。

### 3.2 Executor 上下文传递（对现成 Executor 的聚焦增强）
现有 `PlannerExecutorAgent` 的 Executor 支持 `tool(task_node.description, task_node.metadata)`。分析工具函数统一签名 `fn(description: str, context: dict)`，其中
`context = {"workspace": str, "params": dict}`。断言：不改 Executor 调度/失败恢复主逻辑，仅确保 metadata 携带 `workspace` 与 `params`（由 Planner 生成任务节点时注入）。

### 3.3 MCP 双注册（主攻融合辅助）
同一批处理函数（纯 Python，接受 `workspace` 定位）：
- 注册进 `MCPServer`（`register_tool(ToolSchema, handler)`）→ 经 `MCPClient` 走 MCP 协议发现/调用。
- 同一函数包装为 `agent_runtime.Tool` 注册进 `ToolRegistry` → 供 `PlannerExecutorAgent` 执行。
两个方向都复用现有 `code.mcp` 与 `code.agent_runtime`，无重复实现。

### 3.4 先 Schema 后规划
先调 `csv_load` 得到列/类型/样本 → 注入 `Planner.plan(goal, context={"schema": ...})`，LLM 据此拆解任务，保证后续工具参数生成有依据。

**目标列推断**：当 goal 需要建模时，目标列由 LLM 从 goal+列名推断（如「销售额」→ sales 列）；LLM 推断失败则回退为第一个数值列。若无法定位目标列，在 `model_suggest` 返回引导性报错而非硬失败。

### 3.5 Sandbox：单工具子进程隔离 + 超时
pandas/sklearn 逻辑在子进程执行，主进程设置超时并回收。避免整 CSV 塞 prompt；限制资源与执行时间。

### 3.6 报告
Markdown + 图表图片 + 图形原始 JSON（供前端用 ECharts 二次渲染）。本轮不做 PDF。

## 4. MCP 工具（5 Server / 8 工具）

| Server | 工具 | 说明 |
|--------|------|------|
| data-loader | csv_load | 加载 CSV：行/列数、列名、dtype、样本、缺失率 |
| data-loader | data_summary | 统计摘要：均值/中位数/分位数/分布/异常探测 |
| data-processor | data_clean | 缺失填充、异常处理、类型转换、去重 |
| data-processor | feature_engineer | 编码/标准化/组合特征生成 |
| visualizer | eda_plot | 分布图/箱线图/相关性热力图，输出到 charts/ |
| model-trainer | model_suggest | 根据数据特征（目标类型/样本量/缺失）推荐模型 |
| model-trainer | model_train | 训练并返回评估指标 + 特征重要性 |
| report-generator | report_generate | 汇总所有阶段产物生成 report.md + repro.py |

## 5. Memory（轻量 SQLite）

`memory.py` 用 SQLite 存两张表：
- `preferences`（用户分析偏好：图表风格、默认模型、top_features 数）→ 注入 Planner 上下文与 visualizer 参数。
- `history`（历史分析：goal、schema 摘要、工具调用、模型、结论）→ 跨会话复用（同目标查历史、拾取成功模式）。
提供 `get_preferences() / set_preference() / record_history() / lookup_history()`。

## 6. 评测体系（本轮完成）

`code/evaluation/`：
- **任务集**：≥20 个分 4 档（简单5/中等7/复杂5/困难3+），覆盖「行数/缺失率 → 分布图 → 特征+回归 → 完整清洗→探索→多模型对比→报告」，含错误/脏数据用例。
- **基线对照**：Planner–Executor vs 普通 Agent Loop（复用 `AgentRuntime`）。指标：任务成功率、总执行步数、总耗时、工具调用次数、失败恢复率、并行加速比。
- **输出**：脚本自动跑，落 `evaluation/report.json` + 汇总表。

## 7. 错误处理

- 工具级：handler 捕获异常，`MCPServer` 返回 `{success:False, error}`；`sandbox` 子进程崩溃/超时 → 明确错误码。
- 计划级：`PlanVerifier` 校验 DAG 合法性；执行失败 → 失败恢复策略（RETRY）→ 局部重规划（`replan_partial`）。
- 输入级：非 CSV / 无目标列 / 全空列 → 明确报错并建议。

## 8. 测试

- `tests/test_csv_agent_*.py`：MCP 双注册、各工具在样例 CSV 上的行为、Planner 上下文注入、Workspace 生命周期、Memory CRUD、sandbox 超时、CLI/FastAPI 冒烟。
- 沿用 `pytest`，`testpaths=["tests"]`。
- 提供测试样例 CSV（生成器产出，含正常 + 脏数据）。

## 9. 非目标（本轮）

- 不做 Web 前端页面（另开一轮）。
- 不做真实 Docker 沙箱（用子进程隔离）。
- 不做 PDF 导出。
- 不做多用户完整鉴权（Memory/Workspace 按分析会话隔离即可）。

## 10. 验收

1. `uv run python -m csv_agent.cli analyze <csv> "<goal>"` 输出完整 Markdown 报告目录。
2. FastAPI 冒烟：上传→规划→执行→报告接口可用。
3. 评测脚本产出 20+ 任务指标表与基线对照。
4. 全部 pytest 通过。
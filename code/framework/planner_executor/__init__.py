"""
Planner-Executor 任务规划与执行系统。

红岩网校 AI 部门考核项目 -- 选题三。

本模块实现了一个完整的 Planner-Executor 架构，包含：
- 动态 DAG 任务图（TaskDAG / TaskNode）
- LLM 驱动的任务规划器（Planner）
- 计划质量验证器（PlanVerifier）
- 并行调度器（ParallelScheduler）
- 任务执行器（Executor）
- 顶层调度代理（PlannerExecutorAgent）

核心创新点：
- 动态 DAG：执行过程中根据结果动态调整任务依赖
- 局部重新规划：失败时只重规划受影响的部分
- 计划质量自动评分和修正
- 基于历史经验选择更优计划
- 自动子任务结果验证
- 按任务复杂度自动决定是否启用规划
"""

# DAG 模块
from .dag import (
    TaskNode,
    TaskDAG,
    TaskStatus,
    FailureStrategy,
)

# Planner 模块
from .planner import (
    Planner,
    PlanVersion,
)

# Verifier 模块
from .verifier import (
    PlanVerifier,
    VerificationResult,
    VerificationIssue,
)

# Scheduler 模块
from .scheduler import (
    ParallelScheduler,
    ExecutionResult,
    ScheduleResult,
    ExecutorFunc,
)

# Executor 模块
from .executor import (
    Executor,
    PlannerExecutorAgent,
    ToolRegistry,
    SessionManager,
    TraceLogger,
    ExecutionTrace,
)

__all__ = [
    # DAG
    "TaskNode",
    "TaskDAG",
    "TaskStatus",
    "FailureStrategy",
    # Planner
    "Planner",
    "PlanVersion",
    # Verifier
    "PlanVerifier",
    "VerificationResult",
    "VerificationIssue",
    # Scheduler
    "ParallelScheduler",
    "ExecutionResult",
    "ScheduleResult",
    "ExecutorFunc",
    # Executor + Agent
    "Executor",
    "PlannerExecutorAgent",
    "ToolRegistry",
    "SessionManager",
    "TraceLogger",
    "ExecutionTrace",
]

__version__ = "1.0.0"
__author__ = "Red Rock Web School AI Department"
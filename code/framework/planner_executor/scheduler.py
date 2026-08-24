"""
ParallelScheduler 并行调度器。

负责将 TaskDAG 中的可执行任务按并行组调度执行，
支持最大并行度、任务超时、失败处理策略等配置。
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from .dag import TaskDAG, TaskNode, TaskStatus, FailureStrategy

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class ExecutionResult:
    """单个任务的执行结果。"""

    task_id: str
    status: TaskStatus
    result: Optional[Any] = None
    error: Optional[str] = None
    duration: float = 0.0
    retry_count: int = 0


@dataclass
class ScheduleResult:
    """调度执行的整体结果。"""

    success: bool
    total_tasks: int
    completed: int
    failed: int
    skipped: int
    results: Dict[str, ExecutionResult] = field(default_factory=dict)
    total_duration: float = 0.0
    error_message: str = ""


# ---------------------------------------------------------------------------
# 任务执行器类型
# ---------------------------------------------------------------------------

# 执行器函数签名: (TaskNode) -> ExecutionResult
ExecutorFunc = Callable[[TaskNode], ExecutionResult]


# ---------------------------------------------------------------------------
# ParallelScheduler
# ---------------------------------------------------------------------------


class ParallelScheduler:
    """并行任务调度器。

    对 TaskDAG 中依赖已满足的任务进行并行调度执行。

    Attributes:
        max_workers: 最大并行工作线程数。
        task_timeout: 单个任务超时时间（秒），None 表示不限制。
        failure_strategy: 失败处理策略（skip/retry/abort）。
        retry_delay: 重试间隔（秒）。
        progress_callback: 进度回调函数，签名为 (task_id, status, result) -> None。
    """

    def __init__(
        self,
        max_workers: int = 4,
        task_timeout: Optional[float] = None,
        failure_strategy: FailureStrategy = FailureStrategy.RETRY,
        retry_delay: float = 1.0,
        progress_callback: Optional[Callable[[str, TaskStatus, Any], None]] = None,
    ) -> None:
        self.max_workers = max_workers
        self.task_timeout = task_timeout
        self.failure_strategy = failure_strategy
        self.retry_delay = retry_delay
        self.progress_callback = progress_callback

        # 内部状态
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # 核心接口
    # ------------------------------------------------------------------

    def schedule(
        self,
        task_dag: TaskDAG,
        executor_func: ExecutorFunc,
    ) -> ScheduleResult:
        """调度执行整个 TaskDAG。

        按并行组执行：获取所有依赖已满足的 pending 任务，
        使用 ThreadPoolExecutor 并行执行，完成后继续下一组。

        Args:
            task_dag: 待执行的任务 DAG。
            executor_func: 执行单个任务的函数，签名为 (TaskNode) -> ExecutionResult。

        Returns:
            ScheduleResult 包含所有任务的执行结果。
        """
        start_time = time.time()
        self._stop_event.clear()

        results: Dict[str, ExecutionResult] = {}
        total = task_dag.node_count
        completed = 0
        failed = 0
        skipped = 0

        logger.info(
            "Starting schedule: %d tasks, max_workers=%d, strategy=%s",
            total,
            self.max_workers,
            self.failure_strategy.value,
        )

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            while not task_dag.is_complete() and not self._stop_event.is_set():
                # 获取当前批次可执行的任务
                ready_tasks = task_dag.get_ready_tasks()

                if not ready_tasks:
                    if task_dag.is_stuck() or not task_dag.has_pending():
                        logger.error("DAG cannot make further progress")
                        break
                    # 没有 ready 任务但有 running 任务，等待
                    time.sleep(0.1)
                    continue

                logger.debug("Executing batch: %d tasks", len(ready_tasks))

                # 提交当前批次
                futures: Dict[Future, str] = {}
                for task in ready_tasks:
                    task_dag.update_status(task.task_id, TaskStatus.RUNNING)
                    future = pool.submit(executor_func, task)
                    futures[future] = task.task_id

                # 等待当前批次完成
                for future in as_completed(futures):
                    task_id = futures[future]
                    try:
                        result = future.result(timeout=self.task_timeout)
                    except Exception as e:
                        # 超时或执行异常
                        result = ExecutionResult(
                            task_id=task_id,
                            status=TaskStatus.FAILED,
                            error=str(e),
                        )

                    results[task_id] = result
                    task_dag.update_status(task_id, result.status, result.result)

                    if result.status == TaskStatus.COMPLETED:
                        completed += 1
                    elif result.status == TaskStatus.FAILED:
                        final_status = self._handle_failure(task_dag, task_id, result)
                        # 只有终止性失败才计入 failed；被重置待重试（PENDING）的不算
                        if final_status != TaskStatus.PENDING:
                            failed += 1
                    elif result.status == TaskStatus.SKIPPED:
                        skipped += 1

                    if self.progress_callback:
                        self.progress_callback(task_id, result.status, result.result)

                # 检查是否需要中止
                if self.failure_strategy == FailureStrategy.ABORT and failed > 0:
                    logger.warning("Aborting due to failure (strategy=ABORT)")
                    self._stop_event.set()
                    break

        total_duration = time.time() - start_time

        success = failed == 0 and task_dag.is_complete()

        return ScheduleResult(
            success=success,
            total_tasks=total,
            completed=completed,
            failed=failed,
            skipped=skipped,
            results=results,
            total_duration=total_duration,
            error_message=(
                f"{failed} task(s) failed" if failed > 0 else ""
            ),
        )

    def schedule_batch(
        self,
        tasks: List[TaskNode],
        executor_func: ExecutorFunc,
    ) -> Dict[str, ExecutionResult]:
        """并行执行一批无依赖关系的任务。

        Args:
            tasks: 待执行的任务列表。
            executor_func: 执行函数。

        Returns:
            任务 ID 到执行结果的映射。
        """
        results: Dict[str, ExecutionResult] = {}

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures: Dict[Future, str] = {}
            for task in tasks:
                future = pool.submit(executor_func, task)
                futures[future] = task.task_id

            for future in as_completed(futures):
                task_id = futures[future]
                try:
                    result = future.result(timeout=self.task_timeout)
                except Exception as e:
                    result = ExecutionResult(
                        task_id=task_id,
                        status=TaskStatus.FAILED,
                        error=str(e),
                    )
                results[task_id] = result

                if self.progress_callback:
                    self.progress_callback(task_id, result.status, result.result)

        return results

    def stop(self) -> None:
        """停止调度器。"""
        self._stop_event.set()
        logger.info("Scheduler stopped.")

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    def _handle_failure(
        self,
        dag: TaskDAG,
        task_id: str,
        result: ExecutionResult,
    ) -> "TaskStatus":
        """处理任务失败，并返回节点在失败处理后的最终状态。

        - RETRY 且未超限：重置为 PENDING（下一批重新调度），返回 PENDING；
        - RETRY 且已超限 / ABORT：保持 FAILED，返回 FAILED；
        - SKIP：标记 SKIPPED，返回 SKIPPED。

        retry_count 只在这里统一递增，Executor 不再自增，避免双重计数。
        """
        node = dag.get_node(task_id)

        if self.failure_strategy == FailureStrategy.RETRY:
            if node.retry_count < node.max_retries:
                node.retry_count += 1
                node.status = TaskStatus.PENDING
                logger.info(
                    "Task %s will be retried (%d/%d)",
                    task_id[:8],
                    node.retry_count,
                    node.max_retries,
                )
                time.sleep(self.retry_delay)
                return TaskStatus.PENDING
            else:
                logger.error(
                    "Task %s failed after %d retries",
                    task_id[:8],
                    node.max_retries,
                )
                return TaskStatus.FAILED

        elif self.failure_strategy == FailureStrategy.SKIP:
            node.status = TaskStatus.SKIPPED
            logger.info("Task %s skipped", task_id[:8])
            return TaskStatus.SKIPPED

        elif self.failure_strategy == FailureStrategy.ABORT:
            logger.error("Aborting due to task %s failure", task_id[:8])

        return TaskStatus.FAILED
"""
评测指标模块

定义 Agent 评测的核心指标和计算方法。
"""

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class EvalResult:
    """单个评测任务的结果"""
    task_id: str
    task_name: str
    passed: bool
    expected: Any
    actual: Any
    duration: float
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalReport:
    """评测报告"""
    total: int = 0
    passed: int = 0
    failed: int = 0
    results: list[EvalResult] = field(default_factory=list)
    total_duration: float = 0.0

    @property
    def pass_rate(self) -> float:
        if self.total == 0:
            return 0.0
        return self.passed / self.total

    @property
    def avg_duration(self) -> float:
        if self.total == 0:
            return 0.0
        return self.total_duration / self.total

    def add_result(self, result: EvalResult):
        self.results.append(result)
        self.total += 1
        if result.passed:
            self.passed += 1
        else:
            self.failed += 1
        self.total_duration += result.duration

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "评测报告",
            "=" * 60,
            f"总任务数: {self.total}",
            f"通过: {self.passed}",
            f"失败: {self.failed}",
            f"通过率: {self.pass_rate:.1%}",
            f"总耗时: {self.total_duration:.2f}s",
            f"平均耗时: {self.avg_duration:.2f}s",
            "",
            "详细结果:",
        ]
        for r in self.results:
            status = "✓" if r.passed else "✗"
            err = f" | 错误: {r.error}" if r.error else ""
            lines.append(f"  [{status}] {r.task_name} ({r.duration:.3f}s){err}")
        return "\n".join(lines)


class EvaluationMetrics:
    """评价指标计算"""

    @staticmethod
    def task_success_rate(results: list[EvalResult]) -> float:
        """任务成功率"""
        if not results:
            return 0.0
        return sum(1 for r in results if r.passed) / len(results)

    @staticmethod
    def tool_call_accuracy(expected_calls: list[str], actual_calls: list[str]) -> float:
        """工具调用准确率"""
        if not expected_calls:
            return 1.0 if not actual_calls else 0.0
        expected_set = set(expected_calls)
        actual_set = set(actual_calls)
        intersection = expected_set & actual_set
        return len(intersection) / len(expected_set)

    @staticmethod
    def tool_call_precision(expected_calls: list[str], actual_calls: list[str]) -> float:
        """工具调用精确率"""
        if not actual_calls:
            return 0.0
        expected_set = set(expected_calls)
        actual_set = set(actual_calls)
        intersection = expected_set & actual_set
        return len(intersection) / len(actual_set)

    @staticmethod
    def tool_call_recall(expected_calls: list[str], actual_calls: list[str]) -> float:
        """工具调用召回率"""
        if not expected_calls:
            return 1.0
        expected_set = set(expected_calls)
        actual_set = set(actual_calls)
        intersection = expected_set & actual_set
        return len(intersection) / len(expected_set)

    @staticmethod
    def tool_call_f1(expected_calls: list[str], actual_calls: list[str]) -> float:
        """工具调用 F1 分数"""
        precision = EvaluationMetrics.tool_call_precision(expected_calls, actual_calls)
        recall = EvaluationMetrics.tool_call_recall(expected_calls, actual_calls)
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    @staticmethod
    def execution_efficiency(
        steps: int, optimal_steps: int
    ) -> float:
        """执行效率（步数）"""
        if steps == 0:
            return 0.0
        return min(optimal_steps / steps, 1.0)

    @staticmethod
    def error_recovery_rate(
        total_errors: int, recovered_errors: int
    ) -> float:
        """错误恢复率"""
        if total_errors == 0:
            return 1.0
        return recovered_errors / total_errors

    @staticmethod
    def plan_quality_score(
        subtask_count: int,
        isolated_tasks: int,
        cyclic_deps: int,
        max_subtasks: int = 20,
    ) -> float:
        """计划质量评分"""
        score = 100.0
        if cyclic_deps > 0:
            score -= 30 * cyclic_deps
        if subtask_count > max_subtasks:
            score -= 10 * (subtask_count - max_subtasks) / max_subtasks
        if isolated_tasks > 0:
            score -= 5 * isolated_tasks
        return max(0.0, min(100.0, score))

    @staticmethod
    def tool_selection_accuracy(
        selected_tools: list[str],
        ideal_tools: list[str],
    ) -> float:
        """工具选择准确率"""
        if not ideal_tools:
            return 1.0 if not selected_tools else 0.0
        ideal_set = set(ideal_tools)
        selected_set = set(selected_tools)
        return len(ideal_set & selected_set) / len(ideal_set)
"""
Planner-Executor 测试
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from code.framework.planner_executor.dag import TaskNode, TaskDAG, TaskStatus
from code.framework.planner_executor.verifier import PlanVerifier, VerificationResult
from code.framework.planner_executor.scheduler import ParallelScheduler, FailureStrategy, ExecutionResult
from code.framework.planner_executor.planner import Planner


class TestTaskNode(unittest.TestCase):
    """测试 TaskNode"""

    def test_create_node(self):
        node = TaskNode(
            task_id="task-1",
            description="测试任务",
            expected_output="完成",
        )
        self.assertEqual(node.task_id, "task-1")
        self.assertEqual(node.status, TaskStatus.PENDING)
        self.assertEqual(node.retry_count, 0)

    def test_node_defaults(self):
        node = TaskNode(task_id="t1", description="test")
        self.assertEqual(node.max_retries, 3)
        self.assertEqual(node.priority, 0)
        self.assertEqual(node.dependencies, [])


class TestTaskDAG(unittest.TestCase):
    """测试 TaskDAG"""

    def setUp(self):
        self.dag = TaskDAG()
        self.dag.add_node(TaskNode("task-1", "任务1"))
        self.dag.add_node(TaskNode("task-2", "任务2"))
        self.dag.add_node(TaskNode("task-3", "任务3"))

    def test_add_node(self):
        self.assertEqual(self.dag.node_count, 3)

    def test_add_edge(self):
        self.dag.add_edge("task-1", "task-2")
        self.assertIn("task-1", self.dag.get_node("task-2").dependencies)

    def test_add_edge_invalid(self):
        with self.assertRaises(ValueError):
            self.dag.add_edge("nonexistent", "task-2")

    def test_cycle_detection(self):
        self.dag.add_edge("task-1", "task-2")
        self.dag.add_edge("task-2", "task-3")
        with self.assertRaises(ValueError):
            self.dag.add_edge("task-3", "task-1")

    def test_get_ready_tasks(self):
        self.dag.add_edge("task-1", "task-2")
        ready = self.dag.get_ready_tasks()
        self.assertEqual(len(ready), 2)
        ready_ids = [n.task_id for n in ready]
        self.assertIn("task-1", ready_ids)
        self.assertIn("task-3", ready_ids)

    def test_get_ready_after_completion(self):
        self.dag.add_edge("task-1", "task-2")
        self.dag.update_status("task-1", TaskStatus.COMPLETED)
        ready = self.dag.get_ready_tasks()
        ready_ids = [n.task_id for n in ready]
        self.assertIn("task-2", ready_ids)

    def test_execution_order(self):
        self.dag.add_edge("task-1", "task-2")
        self.dag.add_edge("task-2", "task-3")
        order = self.dag.get_execution_order()
        self.assertEqual(order, ["task-1", "task-2", "task-3"])

    def test_parallel_groups(self):
        self.dag.add_edge("task-1", "task-3")
        self.dag.add_edge("task-2", "task-3")
        groups = self.dag.get_parallel_groups()
        self.assertEqual(len(groups), 2)
        self.assertEqual(len(groups[0]), 2)

    def test_is_complete(self):
        self.assertFalse(self.dag.is_complete())
        for nid in self.dag.get_all_ids():
            self.dag.update_status(nid, TaskStatus.COMPLETED)
        self.assertTrue(self.dag.is_complete())

    def test_is_stuck(self):
        self.dag.add_edge("task-1", "task-2")
        self.dag.add_edge("task-2", "task-3")
        self.dag.update_status("task-1", TaskStatus.FAILED)
        self.assertTrue(self.dag.is_stuck())

    def test_serialization(self):
        self.dag.add_edge("task-1", "task-2")
        d = self.dag.to_dict()
        restored = TaskDAG.from_dict(d)
        self.assertEqual(restored.node_count, 3)

    def test_get_downstream(self):
        self.dag.add_edge("task-1", "task-2")
        self.dag.add_edge("task-1", "task-3")
        downstream = self.dag.get_downstream_tasks("task-1")
        self.assertEqual(len(downstream), 2)

    def test_find_cycles(self):
        cycles = self.dag.find_cycles()
        self.assertEqual(len(cycles), 0)


class TestPlanVerifier(unittest.TestCase):
    """测试计划验证器"""

    def setUp(self):
        self.verifier = PlanVerifier()

    def test_verify_valid_plan(self):
        dag = TaskDAG()
        dag.add_node(TaskNode("t1", "分析代码结构"))
        dag.add_node(TaskNode("t2", "统计代码行数"))
        dag.add_node(TaskNode("t3", "生成报告"))
        dag.add_edge("t1", "t3")
        dag.add_edge("t2", "t3")

        result = self.verifier.verify(dag)
        self.assertGreater(result.score, 50)

    def test_verify_isolated_task(self):
        dag = TaskDAG()
        dag.add_node(TaskNode("t1", "任务1"))
        dag.add_node(TaskNode("t2", "任务2"))
        dag.add_node(TaskNode("t3", "孤立任务"))
        dag.add_edge("t1", "t2")

        result = self.verifier.verify(dag)
        issues = [i.message for i in result.issues]
        self.assertTrue(any("孤立" in msg for msg in issues))

    def test_verify_empty_description(self):
        dag = TaskDAG()
        dag.add_node(TaskNode("t1", ""))

        result = self.verifier.verify(dag)
        issues = [i.message for i in result.issues]
        self.assertTrue(any("描述" in msg for msg in issues))

    def test_suggestions(self):
        dag = TaskDAG()
        dag.add_node(TaskNode("t1", "任务1"))
        dag.add_node(TaskNode("t2", "任务2"))
        dag.add_node(TaskNode("t3", "任务3"))
        dag.add_node(TaskNode("t4", "任务4"))

        suggestions = self.verifier.suggest_improvements(dag)
        self.assertGreater(len(suggestions), 0)


class TestParallelScheduler(unittest.TestCase):
    """测试并行调度器"""

    def setUp(self):
        self.scheduler = ParallelScheduler(max_workers=2)

    def test_schedule_empty(self):
        dag = TaskDAG()
        result = self.scheduler.schedule(dag, lambda n: ExecutionResult(
            task_id=n.task_id, status=TaskStatus.COMPLETED, result="ok"))
        self.assertTrue(result.success)

    def test_schedule_sequential(self):
        dag = TaskDAG()
        dag.add_node(TaskNode("t1", "任务1"))
        dag.add_node(TaskNode("t2", "任务2"))
        dag.add_edge("t1", "t2")

        execution_order = []

        def executor(node):
            execution_order.append(node.task_id)
            return ExecutionResult(
                task_id=node.task_id, status=TaskStatus.COMPLETED, result=node.task_id)

        result = self.scheduler.schedule(dag, executor)
        self.assertTrue(result.success)
        self.assertEqual(execution_order, ["t1", "t2"])

    def test_schedule_parallel(self):
        dag = TaskDAG()
        dag.add_node(TaskNode("t1", "任务1"))
        dag.add_node(TaskNode("t2", "任务2"))

        results = []

        def executor(node):
            results.append(node.task_id)
            return ExecutionResult(
                task_id=node.task_id, status=TaskStatus.COMPLETED, result=node.task_id)

        result = self.scheduler.schedule(dag, executor)
        self.assertTrue(result.success)
        self.assertEqual(len(results), 2)

    def test_failure_strategy_skip(self):
        dag = TaskDAG()
        dag.add_node(TaskNode("t1", "任务1"))
        dag.add_node(TaskNode("t2", "任务2"))

        def failing_executor(node):
            if node.task_id == "t1":
                raise Exception("模拟失败")
            return ExecutionResult(
                task_id=node.task_id, status=TaskStatus.COMPLETED, result="ok")

        scheduler = ParallelScheduler(
            max_workers=1,
            failure_strategy=FailureStrategy.SKIP,
        )
        result = scheduler.schedule(dag, failing_executor)
        self.assertEqual(result.failed, 1)
        self.assertEqual(result.completed, 1)


if __name__ == "__main__":
    unittest.main()
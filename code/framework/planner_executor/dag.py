"""
动态 DAG 任务图模块。

提供 TaskNode（任务节点）和 TaskDAG（有向无环图）两个核心类，
用于表示和管理 Planner–Executor 系统中的任务依赖关系。
"""

from __future__ import annotations

import copy
import json
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# 枚举
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    """任务状态枚举。"""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class FailureStrategy(str, Enum):
    """失败处理策略。"""

    SKIP = "skip"
    RETRY = "retry"
    ABORT = "abort"


# ---------------------------------------------------------------------------
# TaskNode
# ---------------------------------------------------------------------------


@dataclass
class TaskNode:
    """任务图中的节点，表示一个可执行的子任务。

    Attributes:
        task_id: 唯一标识符（UUID 字符串）。
        description: 任务的自然语言描述。
        expected_output: 预期产出的描述。
        status: 当前状态（pending / running / completed / failed / skipped）。
        dependencies: 前置任务 ID 列表。
        result: 执行结果，成功时为任意类型，失败时可为错误信息。
        retry_count: 当前重试次数。
        max_retries: 最大允许重试次数。
        priority: 优先级（数字越小优先级越高）。
        metadata: 附加元数据，可存放任意键值对。
    """

    task_id: str
    description: str
    expected_output: str = ""
    status: TaskStatus = TaskStatus.PENDING
    dependencies: List[str] = field(default_factory=list)
    result: Optional[Any] = None
    retry_count: int = 0
    max_retries: int = 3
    priority: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.task_id:
            self.task_id = uuid.uuid4().hex

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典。"""
        return {
            "task_id": self.task_id,
            "description": self.description,
            "expected_output": self.expected_output,
            "status": self.status.value,
            "dependencies": list(self.dependencies),
            "result": self.result,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "priority": self.priority,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskNode":
        """从字典反序列化。"""
        return cls(
            task_id=data["task_id"],
            description=data["description"],
            expected_output=data.get("expected_output", ""),
            status=TaskStatus(data.get("status", "pending")),
            dependencies=data.get("dependencies", []),
            result=data.get("result"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            priority=data.get("priority", 0),
            metadata=data.get("metadata", {}),
        )

    def clone(self) -> "TaskNode":
        """深拷贝当前节点。"""
        return copy.deepcopy(self)


# ---------------------------------------------------------------------------
# TaskDAG
# ---------------------------------------------------------------------------


class TaskDAG:
    """有向无环任务图，管理任务节点及其依赖关系。

    提供添加节点/边、获取可执行任务、拓扑排序、并行分组、
    循环检测、序列化等能力。
    """

    def __init__(self, name: str = "") -> None:
        self.name: str = name
        self._nodes: Dict[str, TaskNode] = {}
        # 邻接表：from_id -> [to_id, ...]
        self._adj: Dict[str, List[str]] = defaultdict(list)
        # 入度表：to_id -> 入度计数
        self._in_degree: Dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------
    # 基本操作
    # ------------------------------------------------------------------

    def add_node(self, node: TaskNode) -> None:
        """向图中添加一个任务节点。

        Args:
            node: TaskNode 实例。

        Raises:
            ValueError: 如果 task_id 已存在。
        """
        if node.task_id in self._nodes:
            raise ValueError(f"Node with task_id '{node.task_id}' already exists.")
        self._nodes[node.task_id] = node
        # 确保入度/邻接表中有该节点
        if node.task_id not in self._adj:
            self._adj[node.task_id] = []
        if node.task_id not in self._in_degree:
            self._in_degree[node.task_id] = self._in_degree.get(node.task_id, 0)

    def add_edge(self, from_id: str, to_id: str) -> None:
        """添加一条有向边 from_id -> to_id。

        Args:
            from_id: 前置任务 ID。
            to_id: 后置任务 ID。

        Raises:
            ValueError: 如果节点不存在或添加边后产生循环。
        """
        self._validate_node_exists(from_id)
        self._validate_node_exists(to_id)

        if to_id not in self._adj[from_id]:
            self._adj[from_id].append(to_id)
            self._in_degree[to_id] += 1
            # 同步更新 TaskNode 的 dependencies 字段
            if from_id not in self._nodes[to_id].dependencies:
                self._nodes[to_id].dependencies.append(from_id)

        # 添加边后检测循环
        if self.detect_cycles():
            # 回滚
            self._adj[from_id].remove(to_id)
            self._in_degree[to_id] -= 1
            if from_id in self._nodes[to_id].dependencies:
                self._nodes[to_id].dependencies.remove(from_id)
            raise ValueError(
                f"Adding edge {from_id} -> {to_id} would create a cycle."
            )

    def remove_edge(self, from_id: str, to_id: str) -> None:
        """移除一条有向边。"""
        if to_id in self._adj.get(from_id, []):
            self._adj[from_id].remove(to_id)
            self._in_degree[to_id] = max(0, self._in_degree[to_id] - 1)
            if from_id in self._nodes[to_id].dependencies:
                self._nodes[to_id].dependencies.remove(from_id)

    def remove_node(self, task_id: str) -> None:
        """移除一个节点及其所有关联边。"""
        self._validate_node_exists(task_id)
        # 移除所有以该节点为源的边
        for to_id in list(self._adj.get(task_id, [])):
            self.remove_edge(task_id, to_id)
        # 移除所有以该节点为目标的边
        for from_id in list(self._adj.keys()):
            if task_id in self._adj.get(from_id, []):
                self.remove_edge(from_id, task_id)
        del self._adj[task_id]
        del self._in_degree[task_id]
        del self._nodes[task_id]

    def get_node(self, task_id: str) -> TaskNode:
        """根据 ID 获取节点。"""
        self._validate_node_exists(task_id)
        return self._nodes[task_id]

    def get_all_nodes(self) -> List[TaskNode]:
        """返回所有节点。"""
        return list(self._nodes.values())

    def get_all_ids(self) -> List[str]:
        """返回所有节点 ID。"""
        return list(self._nodes.keys())

    @property
    def node_count(self) -> int:
        """图中节点总数。"""
        return len(self._nodes)

    @property
    def edge_count(self) -> int:
        """图中边的总数。"""
        return sum(len(targets) for targets in self._adj.values())

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def get_ready_tasks(self) -> List[TaskNode]:
        """返回所有依赖已满足的 pending 任务。

        依赖已满足的含义：所有前置任务的状态均为 COMPLETED 或 SKIPPED。

        Returns:
            可立即执行的任务列表。
        """
        ready: List[TaskNode] = []
        for node in self._nodes.values():
            if node.status != TaskStatus.PENDING:
                continue
            if self._dependencies_satisfied(node):
                ready.append(node)
        return ready

    def get_next_task(self) -> Optional[TaskNode]:
        """返回下一个可执行的任务（考虑优先级）。

        在 ready 任务中按优先级（数字越小越高）排序，返回第一个。

        Returns:
            下一个可执行的任务，没有则返回 None。
        """
        ready = self.get_ready_tasks()
        if not ready:
            return None
        ready.sort(key=lambda n: (n.priority, n.task_id))
        return ready[0]

    def update_status(
        self,
        task_id: str,
        status: TaskStatus,
        result: Optional[Any] = None,
    ) -> None:
        """更新节点状态与结果。

        Args:
            task_id: 任务 ID。
            status: 新状态。
            result: 执行结果（可选）。
        """
        self._validate_node_exists(task_id)
        node = self._nodes[task_id]
        node.status = status
        if result is not None:
            node.result = result

    def is_complete(self) -> bool:
        """判断整个 DAG 是否已完成。

        所有节点状态为 COMPLETED 或 SKIPPED 时视为完成。

        Returns:
            True 如果所有任务都已完成。
        """
        if not self._nodes:
            return True
        return all(
            node.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
            for node in self._nodes.values()
        )

    def is_stuck(self) -> bool:
        """判断 DAG 是否陷入死锁（有 pending 任务但无法执行）。

        存在 pending 任务，但其依赖未被满足，且没有正在运行的任务，
        且没有更多可执行的任务。

        Returns:
            True 如果 DAG 陷入死锁。
        """
        if self.is_complete():
            return False
        pending = [
            n for n in self._nodes.values() if n.status == TaskStatus.PENDING
        ]
        running = [
            n for n in self._nodes.values() if n.status == TaskStatus.RUNNING
        ]
        ready = self.get_ready_tasks()
        return len(pending) > 0 and len(ready) == 0 and len(running) == 0

    def get_failed_tasks(self) -> List[TaskNode]:
        """返回所有失败的任务。"""
        return [n for n in self._nodes.values() if n.status == TaskStatus.FAILED]

    def has_pending(self) -> bool:
        """是否存在尚未执行的 pending 任务。"""
        return any(
            n.status == TaskStatus.PENDING for n in self._nodes.values()
        )

    def get_downstream_tasks(self, task_id: str) -> List[TaskNode]:
        """返回指定任务的所有下游任务（直接和间接依赖）。"""
        self._validate_node_exists(task_id)
        visited: Set[str] = set()
        result: List[TaskNode] = []

        def dfs(current: str) -> None:
            for neighbor in self._adj.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    result.append(self._nodes[neighbor])
                    dfs(neighbor)

        dfs(task_id)
        return result

    def get_upstream_tasks(self, task_id: str) -> List[TaskNode]:
        """返回指定任务的所有上游任务（直接和间接被依赖）。"""
        self._validate_node_exists(task_id)
        # 构建反向邻接表
        reverse_adj: Dict[str, List[str]] = defaultdict(list)
        for from_id, targets in self._adj.items():
            for to_id in targets:
                reverse_adj[to_id].append(from_id)

        visited: Set[str] = set()
        result: List[TaskNode] = []

        def dfs(current: str) -> None:
            for neighbor in reverse_adj.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    result.append(self._nodes[neighbor])
                    dfs(neighbor)

        dfs(task_id)
        return result

    # ------------------------------------------------------------------
    # 拓扑排序 & 并行分组
    # ------------------------------------------------------------------

    def get_execution_order(self) -> List[str]:
        """返回拓扑排序后的任务 ID 列表。

        使用 Kahn 算法。如果检测到循环，抛出 ValueError。

        Returns:
            拓扑排序的任务 ID 列表。

        Raises:
            ValueError: 如果图中存在循环依赖。
        """
        in_degree = dict(self._in_degree)
        queue: deque = deque(
            [nid for nid, deg in in_degree.items() if deg == 0]
        )
        order: List[str] = []

        while queue:
            current = queue.popleft()
            order.append(current)
            for neighbor in self._adj.get(current, []):
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if len(order) != len(self._nodes):
            raise ValueError("Cycle detected in DAG; cannot produce topological order.")

        return order

    def get_parallel_groups(self) -> List[List[str]]:
        """返回可并行执行的任务组。

        每一组内的任务互不依赖，可以同时执行。
        组之间按拓扑顺序排列。

        Returns:
            嵌套列表，每个子列表是一组可并行执行的任务 ID。
        """
        if not self._nodes:
            return []

        in_degree = dict(self._in_degree)
        groups: List[List[str]] = []
        current_group = [
            nid for nid, deg in in_degree.items() if deg == 0
        ]
        processed_count = 0

        while current_group:
            groups.append(sorted(current_group))
            next_group: List[str] = []
            for nid in current_group:
                processed_count += 1
                for neighbor in self._adj.get(nid, []):
                    in_degree[neighbor] -= 1
                    if in_degree[neighbor] == 0:
                        next_group.append(neighbor)
            current_group = next_group

        if processed_count != len(self._nodes):
            raise ValueError("Cycle detected; cannot produce parallel groups.")

        return groups

    # ------------------------------------------------------------------
    # 循环检测
    # ------------------------------------------------------------------

    def detect_cycles(self) -> bool:
        """检测图中是否存在循环依赖。

        使用三色 DFS 标记法：
        - 0: 未访问
        - 1: 正在访问（灰色，在递归栈中）
        - 2: 已完成访问（黑色）

        Returns:
            True 如果存在循环。
        """
        color: Dict[str, int] = {nid: 0 for nid in self._nodes}

        def dfs(node_id: str) -> bool:
            color[node_id] = 1
            for neighbor in self._adj.get(node_id, []):
                if color.get(neighbor, 0) == 1:
                    return True  # 发现后向边，存在循环
                if color.get(neighbor, 0) == 0:
                    if dfs(neighbor):
                        return True
            color[node_id] = 2
            return False

        for nid in self._nodes:
            if color.get(nid, 0) == 0:
                if dfs(nid):
                    return True
        return False

    def find_cycles(self) -> List[List[str]]:
        """找出图中的所有循环路径。

        Returns:
            循环路径列表，每个循环是一个节点 ID 列表。
        """
        cycles: List[List[str]] = []
        color: Dict[str, int] = {nid: 0 for nid in self._nodes}
        parent: Dict[str, Optional[str]] = {nid: None for nid in self._nodes}

        def dfs(node_id: str) -> None:
            color[node_id] = 1
            for neighbor in self._adj.get(node_id, []):
                if color.get(neighbor, 0) == 1:
                    # 找到循环，回溯路径
                    cycle: List[str] = [neighbor, node_id]
                    cur = node_id
                    while parent.get(cur) and parent[cur] != neighbor:
                        cur = parent[cur]  # type: ignore[assignment]
                        cycle.append(cur)
                    cycle.append(neighbor)
                    cycle.reverse()
                    cycles.append(cycle)
                elif color.get(neighbor, 0) == 0:
                    parent[neighbor] = node_id
                    dfs(neighbor)
            color[node_id] = 2

        for nid in self._nodes:
            if color.get(nid, 0) == 0:
                dfs(nid)
        return cycles

    # ------------------------------------------------------------------
    # 序列化
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """将整个 DAG 序列化为字典。"""
        return {
            "name": self.name,
            "nodes": [node.to_dict() for node in self._nodes.values()],
            "edges": [
                {"from": from_id, "to": to_id}
                for from_id, targets in self._adj.items()
                for to_id in targets
            ],
        }

    def to_json(self, indent: int = 2) -> str:
        """将 DAG 序列化为 JSON 字符串。"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskDAG":
        """从字典反序列化构造 TaskDAG。"""
        dag = cls(name=data.get("name", ""))
        # 先添加所有节点
        for node_data in data.get("nodes", []):
            node = TaskNode.from_dict(node_data)
            dag._nodes[node.task_id] = node
            dag._adj[node.task_id] = []
            dag._in_degree[node.task_id] = 0
        # 再添加所有边
        for edge_data in data.get("edges", []):
            dag.add_edge(edge_data["from"], edge_data["to"])
        return dag

    @classmethod
    def from_json(cls, json_str: str) -> "TaskDAG":
        """从 JSON 字符串反序列化构造 TaskDAG。"""
        return cls.from_dict(json.loads(json_str))

    def clone(self) -> "TaskDAG":
        """深拷贝整个 DAG。"""
        return self.from_dict(self.to_dict())

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _validate_node_exists(self, task_id: str) -> None:
        """验证节点是否存在，不存在则抛出 ValueError。"""
        if task_id not in self._nodes:
            raise ValueError(f"Node with task_id '{task_id}' does not exist.")

    def _dependencies_satisfied(self, node: TaskNode) -> bool:
        """检查节点的所有前置任务是否已完成或跳过。"""
        for dep_id in node.dependencies:
            dep_node = self._nodes.get(dep_id)
            if dep_node is None:
                return False
            if dep_node.status not in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
                return False
        return True

    def __repr__(self) -> str:
        return (
            f"TaskDAG(name={self.name!r}, nodes={self.node_count}, "
            f"edges={self.edge_count})"
        )

    def __str__(self) -> str:
        lines = [f"TaskDAG: {self.name} ({self.node_count} nodes, {self.edge_count} edges)"]
        for node in self._nodes.values():
            deps = ", ".join(node.dependencies) if node.dependencies else "none"
            lines.append(
                f"  [{node.status.value}] {node.task_id[:8]}... "
                f"| pri={node.priority} | deps=[{deps}] | {node.description[:50]}"
            )
        return "\n".join(lines)
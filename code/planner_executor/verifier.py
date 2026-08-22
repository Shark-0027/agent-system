"""
PlanVerifier 计划质量验证器。

对 Planner 生成的 TaskDAG 进行多维度质量检查，包括：
- 依赖合法性
- 子任务粒度合理性
- 孤立任务检测
- 任务描述清晰度
- 综合评分（0-100）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .dag import TaskDAG, TaskNode, TaskStatus

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class VerificationIssue:
    """验证问题描述。"""

    severity: str  # "error", "warning", "info"
    category: str  # 问题类别
    task_id: Optional[str]  # 关联的任务 ID（可选）
    message: str  # 问题描述
    suggestion: str = ""  # 改进建议


@dataclass
class VerificationResult:
    """验证结果。"""

    passed: bool
    score: float  # 0-100
    issues: List[VerificationIssue] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def errors(self) -> List[VerificationIssue]:
        """返回所有 error 级别的问题。"""
        return [i for i in self.issues if i.severity == "error"]

    @property
    def warnings(self) -> List[VerificationIssue]:
        """返回所有 warning 级别的问题。"""
        return [i for i in self.issues if i.severity == "warning"]

    @property
    def info(self) -> List[VerificationIssue]:
        """返回所有 info 级别的问题。"""
        return [i for i in self.issues if i.severity == "info"]


# ---------------------------------------------------------------------------
# PlanVerifier
# ---------------------------------------------------------------------------


class PlanVerifier:
    """计划质量验证器。

    对 TaskDAG 进行全面质量检查，返回评分和改进建议。

    Attributes:
        min_subtasks: 最小子任务数（低于此数会警告）。
        max_subtasks: 最大子任务数（高于此数会警告）。
        max_description_length: 任务描述最大长度建议。
        min_description_length: 任务描述最小长度建议。
        max_dependency_depth: 最大依赖深度建议。
        scoring_weights: 各项检查的评分权重。
    """

    def __init__(
        self,
        min_subtasks: int = 2,
        max_subtasks: int = 20,
        min_description_length: int = 10,
        max_description_length: int = 500,
        max_dependency_depth: int = 5,
        scoring_weights: Optional[Dict[str, float]] = None,
    ) -> None:
        self.min_subtasks = min_subtasks
        self.max_subtasks = max_subtasks
        self.min_description_length = min_description_length
        self.max_description_length = max_description_length
        self.max_dependency_depth = max_dependency_depth
        self.scoring_weights = scoring_weights or {
            "dependency_validity": 25.0,
            "granularity": 20.0,
            "orphan_detection": 15.0,
            "description_clarity": 20.0,
            "structure_quality": 10.0,
            "parallelism": 10.0,
        }

    # ------------------------------------------------------------------
    # 核心接口
    # ------------------------------------------------------------------

    def verify(self, plan_dag: TaskDAG) -> VerificationResult:
        """验证计划质量。

        Args:
            plan_dag: 待验证的 TaskDAG。

        Returns:
            VerificationResult 包含评分和问题列表。
        """
        issues: List[VerificationIssue] = []
        scores: Dict[str, float] = {}

        # 1. 依赖合法性检查
        dep_score, dep_issues = self._check_dependency_validity(plan_dag)
        scores["dependency_validity"] = dep_score
        issues.extend(dep_issues)

        # 2. 子任务粒度检查
        gran_score, gran_issues = self._check_granularity(plan_dag)
        scores["granularity"] = gran_score
        issues.extend(gran_issues)

        # 3. 孤立任务检测
        orphan_score, orphan_issues = self._check_orphan_tasks(plan_dag)
        scores["orphan_detection"] = orphan_score
        issues.extend(orphan_issues)

        # 4. 任务描述清晰度
        clarity_score, clarity_issues = self._check_description_clarity(plan_dag)
        scores["description_clarity"] = clarity_score
        issues.extend(clarity_issues)

        # 5. 结构质量
        struct_score, struct_issues = self._check_structure_quality(plan_dag)
        scores["structure_quality"] = struct_score
        issues.extend(struct_issues)

        # 6. 并行度评估
        parallel_score, parallel_issues = self._check_parallelism(plan_dag)
        scores["parallelism"] = parallel_score
        issues.extend(parallel_issues)

        # 计算加权总分
        total_score = self._compute_weighted_score(scores)

        # 判断是否通过
        has_errors = any(i.severity == "error" for i in issues)
        passed = not has_errors and total_score >= 60.0

        return VerificationResult(
            passed=passed,
            score=round(total_score, 1),
            issues=issues,
            details={
                "sub_scores": scores,
                "weights": self.scoring_weights,
                "node_count": plan_dag.node_count,
                "edge_count": plan_dag.edge_count,
                "parallel_groups": len(plan_dag.get_parallel_groups()),
            },
        )

    def get_issues(self, plan_dag: TaskDAG) -> List[VerificationIssue]:
        """返回计划中的问题列表。"""
        result = self.verify(plan_dag)
        return result.issues

    def suggest_improvements(self, plan_dag: TaskDAG) -> List[str]:
        """给出改进建议。

        Args:
            plan_dag: 待评估的 TaskDAG。

        Returns:
            改进建议字符串列表。
        """
        result = self.verify(plan_dag)
        suggestions: List[str] = []

        for issue in result.issues:
            if issue.suggestion:
                suggestions.append(issue.suggestion)
            elif issue.severity == "error":
                suggestions.append(f"[严重] {issue.message}")
            elif issue.severity == "warning":
                suggestions.append(f"[警告] {issue.message}")

        # 通用建议
        if result.score < 60:
            suggestions.append(
                "计划质量较低，建议：1) 细化子任务描述；2) 检查依赖关系是否合理；"
                "3) 确保每个子任务有明确的预期输出。"
            )
        elif result.score < 80:
            suggestions.append(
                "计划质量一般，可通过以下方式改进：1) 优化任务粒度；"
                "2) 增加可并行执行的任务。"
            )

        return suggestions

    # ------------------------------------------------------------------
    # 各项检查
    # ------------------------------------------------------------------

    def _check_dependency_validity(
        self, dag: TaskDAG
    ) -> Tuple[float, List[VerificationIssue]]:
        """检查依赖关系合法性。"""
        issues: List[VerificationIssue] = []
        max_score = 100.0
        penalty = 0.0

        # 循环依赖
        if dag.detect_cycles():
            cycles = dag.find_cycles()
            issues.append(
                VerificationIssue(
                    severity="error",
                    category="dependency_validity",
                    task_id=None,
                    message=f"存在循环依赖: {cycles}",
                    suggestion="移除形成循环的边，确保依赖关系为有向无环图。",
                )
            )
            penalty += 40.0

        # 引用不存在的依赖
        all_ids = set(dag.get_all_ids())
        for node in dag.get_all_nodes():
            for dep_id in node.dependencies:
                if dep_id not in all_ids:
                    issues.append(
                        VerificationIssue(
                            severity="error",
                            category="dependency_validity",
                            task_id=node.task_id,
                            message=f"任务 '{node.task_id[:8]}...' 依赖了不存在的任务 '{dep_id}'",
                            suggestion=f"移除无效依赖或添加缺失的任务 '{dep_id}'。",
                        )
                    )
                    penalty += 15.0

        # 自依赖
        for node in dag.get_all_nodes():
            if node.task_id in node.dependencies:
                issues.append(
                    VerificationIssue(
                        severity="error",
                        category="dependency_validity",
                        task_id=node.task_id,
                        message=f"任务 '{node.task_id[:8]}...' 依赖自身",
                        suggestion="移除自依赖关系。",
                    )
                )
                penalty += 10.0

        # 冗余依赖（A->B 且 A->C->B，则 A->B 是冗余的）
        # 简化检查：如果存在直接边同时存在间接路径，标记警告
        for node in dag.get_all_nodes():
            for dep_id in node.dependencies:
                if self._has_indirect_path(dag, dep_id, node.task_id):
                    issues.append(
                        VerificationIssue(
                            severity="warning",
                            category="dependency_validity",
                            task_id=node.task_id,
                            message=(
                                f"任务 '{node.task_id[:8]}...' 对 '{dep_id[:8]}...' "
                                f"的依赖可能是冗余的（存在间接路径）"
                            ),
                            suggestion="考虑移除冗余的直接依赖，简化图结构。",
                        )
                    )
                    penalty += 5.0

        # 依赖深度检查
        depths = self._compute_depths(dag)
        for node_id, depth in depths.items():
            if depth > self.max_dependency_depth:
                node = dag.get_node(node_id)
                issues.append(
                    VerificationIssue(
                        severity="warning",
                        category="dependency_validity",
                        task_id=node_id,
                        message=(
                            f"任务 '{node_id[:8]}...' 的依赖深度为 {depth}，"
                            f"超过建议值 {self.max_dependency_depth}"
                        ),
                        suggestion="考虑减少依赖链长度，或合并部分子任务。",
                    )
                )
                penalty += 5.0

        score = max(0.0, max_score - penalty)
        return score, issues

    def _check_granularity(
        self, dag: TaskDAG
    ) -> Tuple[float, List[VerificationIssue]]:
        """检查子任务粒度是否合理。"""
        issues: List[VerificationIssue] = []
        max_score = 100.0
        penalty = 0.0

        node_count = dag.node_count

        if node_count == 0:
            issues.append(
                VerificationIssue(
                    severity="error",
                    category="granularity",
                    task_id=None,
                    message="计划中没有任何子任务",
                    suggestion="至少需要添加一个子任务。",
                )
            )
            return 0.0, issues

        if node_count < self.min_subtasks:
            issues.append(
                VerificationIssue(
                    severity="info",
                    category="granularity",
                    task_id=None,
                    message=f"子任务数量 ({node_count}) 少于建议最小值 ({self.min_subtasks})",
                    suggestion="考虑进一步分解任务以增加并行度。",
                )
            )
            penalty += 10.0

        if node_count > self.max_subtasks:
            issues.append(
                VerificationIssue(
                    severity="warning",
                    category="granularity",
                    task_id=None,
                    message=f"子任务数量 ({node_count}) 超过建议最大值 ({self.max_subtasks})",
                    suggestion="考虑合并部分子任务，降低计划复杂度。",
                )
            )
            penalty += 15.0

        # 描述长度检查
        for node in dag.get_all_nodes():
            desc_len = len(node.description)
            if desc_len < self.min_description_length:
                issues.append(
                    VerificationIssue(
                        severity="warning",
                        category="granularity",
                        task_id=node.task_id,
                        message=(
                            f"任务 '{node.task_id[:8]}...' 的描述过短 ({desc_len} 字符)"
                        ),
                        suggestion="请提供更详细的子任务描述。",
                    )
                )
                penalty += 5.0
            elif desc_len > self.max_description_length:
                issues.append(
                    VerificationIssue(
                        severity="info",
                        category="granularity",
                        task_id=node.task_id,
                        message=(
                            f"任务 '{node.task_id[:8]}...' 的描述过长 ({desc_len} 字符)"
                        ),
                        suggestion="考虑精简描述，保持聚焦。",
                    )
                )
                penalty += 2.0

        score = max(0.0, max_score - penalty)
        return score, issues

    def _check_orphan_tasks(
        self, dag: TaskDAG
    ) -> Tuple[float, List[VerificationIssue]]:
        """检查是否存在孤立任务。"""
        issues: List[VerificationIssue] = []
        max_score = 100.0
        penalty = 0.0

        nodes = dag.get_all_nodes()
        if not nodes:
            return 100.0, issues

        # 计算每个节点的入度和出度
        in_degree: Dict[str, int] = {n.task_id: 0 for n in nodes}
        out_degree: Dict[str, int] = {n.task_id: 0 for n in nodes}

        for node in nodes:
            out_degree[node.task_id] = len(node.dependencies)
            # 依赖关系在 dag 中以邻接表存储
            # 这里通过 node.dependencies 来计算入度

        for node in nodes:
            for dep_id in node.dependencies:
                if dep_id in in_degree:
                    in_degree[dep_id] += 1

        # 孤立任务：入度=0 且出度=0（既无依赖也无被依赖）
        orphan_count = 0
        for node in nodes:
            if in_degree.get(node.task_id, 0) == 0 and out_degree.get(node.task_id, 0) == 0:
                orphan_count += 1

        if orphan_count > 0 and len(nodes) > 1:
            issues.append(
                VerificationIssue(
                    severity="warning",
                    category="orphan_detection",
                    task_id=None,
                    message=f"存在 {orphan_count} 个孤立任务（无依赖关系）",
                    suggestion="检查这些任务是否真的独立，或者遗漏了依赖关系。",
                )
            )
            penalty += 20.0

        # 检查是否有任务永远无法到达（入口任务过多）
        entry_count = sum(1 for n in nodes if len(n.dependencies) == 0)
        if entry_count > len(nodes) * 0.5 and len(nodes) > 3:
            issues.append(
                VerificationIssue(
                    severity="info",
                    category="orphan_detection",
                    task_id=None,
                    message=f"入口任务 ({entry_count}) 占比过高，可能缺乏合理的依赖结构",
                    suggestion="检查是否可以让部分任务形成依赖链。",
                )
            )
            penalty += 10.0

        score = max(0.0, max_score - penalty)
        return score, issues

    def _check_description_clarity(
        self, dag: TaskDAG
    ) -> Tuple[float, List[VerificationIssue]]:
        """检查任务描述清晰度。"""
        issues: List[VerificationIssue] = []
        max_score = 100.0
        penalty = 0.0

        for node in dag.get_all_nodes():
            desc = node.description

            # 空描述
            if not desc or not desc.strip():
                issues.append(
                    VerificationIssue(
                        severity="error",
                        category="description_clarity",
                        task_id=node.task_id,
                        message=f"任务 '{node.task_id[:8]}...' 的描述为空",
                        suggestion="请为每个子任务提供清晰的描述。",
                    )
                )
                penalty += 15.0
                continue

            # 包含模糊词汇
            vague_terms = ["可能", "也许", "大概", "应该", "maybe", "perhaps", "大概"]
            found_vague = [t for t in vague_terms if t in desc]
            if found_vague:
                issues.append(
                    VerificationIssue(
                        severity="warning",
                        category="description_clarity",
                        task_id=node.task_id,
                        message=(
                            f"任务 '{node.task_id[:8]}...' 包含模糊词汇: {found_vague}"
                        ),
                        suggestion="使用更明确、具体的描述代替模糊词汇。",
                    )
                )
                penalty += 5.0

            # 缺少预期输出
            if not node.expected_output:
                issues.append(
                    VerificationIssue(
                        severity="warning",
                        category="description_clarity",
                        task_id=node.task_id,
                        message=f"任务 '{node.task_id[:8]}...' 缺少预期输出描述",
                        suggestion="为每个子任务添加预期输出，便于验证执行结果。",
                    )
                )
                penalty += 8.0

            # 描述是纯动词开头（说明是动作而不是任务目标）
            action_starts = ["写", "计算", "搜索", "创建", "读取", "write", "compute", "search", "create", "read", "get", "fetch"]
            desc_lower = desc.lower().strip()
            for action in action_starts:
                if desc_lower.startswith(action):
                    issues.append(
                        VerificationIssue(
                            severity="info",
                            category="description_clarity",
                            task_id=node.task_id,
                            message=(
                                f"任务 '{node.task_id[:8]}...' 的描述以动词开头，"
                                f"建议改为目标导向的描述"
                            ),
                            suggestion="描述应聚焦于'要达成什么'而非'要做什么'。",
                        )
                    )
                    penalty += 2.0
                    break

        score = max(0.0, max_score - penalty)
        return score, issues

    def _check_structure_quality(
        self, dag: TaskDAG
    ) -> Tuple[float, List[VerificationIssue]]:
        """检查图结构质量。"""
        issues: List[VerificationIssue] = []
        max_score = 100.0
        penalty = 0.0

        nodes = dag.get_all_nodes()
        if not nodes:
            return 0.0, issues

        # 边密度检查
        node_count = len(nodes)
        max_possible_edges = node_count * (node_count - 1)
        actual_edges = dag.edge_count

        if node_count > 1:
            density = actual_edges / max_possible_edges if max_possible_edges > 0 else 0
            if density > 0.5:
                issues.append(
                    VerificationIssue(
                        severity="warning",
                        category="structure_quality",
                        task_id=None,
                        message=f"边密度过高 ({density:.2f})，依赖关系可能过于复杂",
                        suggestion="考虑简化依赖关系，减少不必要的边。",
                    )
                )
                penalty += 15.0

        # 检查是否有"瓶颈"任务（被很多任务依赖）
        dep_count: Dict[str, int] = {n.task_id: 0 for n in nodes}
        for node in nodes:
            for dep_id in node.dependencies:
                if dep_id in dep_count:
                    dep_count[dep_id] += 1

        for node_id, count in dep_count.items():
            if count > node_count * 0.5 and node_count > 3:
                node = dag.get_node(node_id)
                issues.append(
                    VerificationIssue(
                        severity="warning",
                        category="structure_quality",
                        task_id=node_id,
                        message=(
                            f"任务 '{node_id[:8]}...' 是瓶颈任务（被 {count} 个任务依赖）"
                        ),
                        suggestion="考虑拆分该任务或减少对其的依赖。",
                    )
                )
                penalty += 10.0

        # 检查优先级设置是否合理
        priorities = [n.priority for n in nodes]
        if len(set(priorities)) == 1 and len(priorities) > 3:
            issues.append(
                VerificationIssue(
                    severity="info",
                    category="structure_quality",
                    task_id=None,
                    message="所有任务优先级相同，建议按重要性区分优先级",
                    suggestion="为关键路径上的任务设置更高优先级。",
                )
            )
            penalty += 5.0

        score = max(0.0, max_score - penalty)
        return score, issues

    def _check_parallelism(
        self, dag: TaskDAG
    ) -> Tuple[float, List[VerificationIssue]]:
        """检查并行度。"""
        issues: List[VerificationIssue] = []
        max_score = 100.0
        penalty = 0.0

        try:
            groups = dag.get_parallel_groups()
        except ValueError:
            issues.append(
                VerificationIssue(
                    severity="error",
                    category="parallelism",
                    task_id=None,
                    message="无法计算并行组（可能存在循环依赖）",
                    suggestion="修复循环依赖后再评估并行度。",
                )
            )
            return 0.0, issues

        if not groups:
            return 100.0, issues

        # 各组大小
        group_sizes = [len(g) for g in groups]
        max_group_size = max(group_sizes) if group_sizes else 0
        avg_group_size = sum(group_sizes) / len(group_sizes) if group_sizes else 0
        total_nodes = dag.node_count

        if total_nodes > 1:
            # 并行度 = 平均组大小 / 总节点数
            parallelism_ratio = avg_group_size / total_nodes if total_nodes > 0 else 0

            if parallelism_ratio < 0.1 and total_nodes > 5:
                issues.append(
                    VerificationIssue(
                        severity="warning",
                        category="parallelism",
                        task_id=None,
                        message=(
                            f"并行度较低 ({parallelism_ratio:.2f})，"
                            f"平均每组仅 {avg_group_size:.1f} 个任务"
                        ),
                        suggestion="检查是否可以增加可并行的子任务，减少不必要的串行依赖。",
                    )
                )
                penalty += 20.0

            if max_group_size == 1 and total_nodes > 3:
                issues.append(
                    VerificationIssue(
                        severity="info",
                        category="parallelism",
                        task_id=None,
                        message="所有任务串行执行，无可并行机会",
                        suggestion="考虑重新设计任务分解，增加可并行的子任务。",
                    )
                )
                penalty += 15.0

        # 组数过多说明任务过于碎片化
        if len(groups) > total_nodes * 0.8:
            issues.append(
                VerificationIssue(
                    severity="info",
                    category="parallelism",
                    task_id=None,
                    message=f"并行组数 ({len(groups)}) 接近总任务数，可能存在过度碎片化",
                    suggestion="考虑合并部分小任务以提高效率。",
                )
            )
            penalty += 5.0

        score = max(0.0, max_score - penalty)
        return score, issues

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    def _compute_weighted_score(self, scores: Dict[str, float]) -> float:
        """计算加权总分。"""
        total = 0.0
        total_weight = 0.0
        for key, weight in self.scoring_weights.items():
            if key in scores:
                total += scores[key] * weight
                total_weight += weight
        if total_weight == 0:
            return 0.0
        return total / total_weight

    def _has_indirect_path(
        self, dag: TaskDAG, from_id: str, to_id: str
    ) -> bool:
        """检查 from_id 到 to_id 是否存在间接路径（排除直接边）。"""
        visited: set = {from_id}
        queue = [from_id]

        while queue:
            current = queue.pop(0)
            for dep_id in dag._adj.get(current, []):
                if dep_id == to_id:
                    # 确认不是 from_id 的直接依赖
                    if to_id not in dag._adj.get(from_id, []):
                        return True
                    # 是直接依赖，但只有当存在另一条路径时才返回 True
                    continue
                if dep_id not in visited:
                    visited.add(dep_id)
                    queue.append(dep_id)

        return False

    def _compute_depths(self, dag: TaskDAG) -> Dict[str, int]:
        """计算每个节点的依赖深度（最长依赖链长度）。"""
        depths: Dict[str, int] = {}
        nodes = dag.get_all_nodes()

        # 拓扑排序
        try:
            order = dag.get_execution_order()
        except ValueError:
            return {n.task_id: 0 for n in nodes}

        for node_id in order:
            node = dag.get_node(node_id)
            if not node.dependencies:
                depths[node_id] = 0
            else:
                depths[node_id] = (
                    max(depths.get(d, 0) for d in node.dependencies) + 1
                )

        return depths

    def __repr__(self) -> str:
        return (
            f"PlanVerifier(min_subtasks={self.min_subtasks}, "
            f"max_subtasks={self.max_subtasks})"
        )
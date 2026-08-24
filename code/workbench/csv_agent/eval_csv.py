"""CSV 分析自动评测：难度任务 + Planner-Executor vs 简单 Loop 基线。"""
from __future__ import annotations

import time
from typing import Any, Dict, List

from code.workbench.csv_agent.datagen import gen_sales
from code.workbench.csv_agent.orchestrator import CsvAgent
from code.workbench.csv_agent.workspace import Workspace
from code.framework.evaluation.metrics import EvalResult, EvalReport, EvaluationMetrics


def build_csv_tasks() -> List[Dict[str, Any]]:
    simple = [
        "这个 CSV 有多少行？", "有多少列？", "缺失值最多的列是哪列？",
        "数值列有哪些？", "给出前几行样例",
    ]
    medium = [
        "展示各数值列分布并画直方图", "检测并处理缺失值",
        "对分类列做编码", "计算数值列相关性并绘制热力图",
        "标准化数值特征", "识别并裁切异常值", "去重",
    ]
    complex_ = [
        "分析销售额影响因素，做特征工程", "训练回归模型并评估",
        "比较线性回归与随机森林效果", "预测销售并给出误差指标",
        "清洗并探索数据，输出概览",
    ]
    hard = [
        "完整分析：清洗→探索→特征工程→多模型对比→生成报告",
        "对含错误数据的 CSV 做完整分析并生成报告",
        "先用模型建议再训练，输出最优模型与特征重要性",
    ]
    tasks: List[Dict[str, Any]] = []
    for g in simple:
        tasks.append({"difficulty": "简单", "goal": g, "check": _must_success})
    for g in medium:
        tasks.append({"difficulty": "中等", "goal": g, "check": _must_success})
    for g in complex_:
        tasks.append({"difficulty": "复杂", "goal": g, "check": _must_success})
    for g in hard:
        tasks.append({"difficulty": "困难", "goal": g,
                      "check": lambda r: r["success"] and r["report_path"]})
    return tasks


def _must_success(r: dict) -> bool:
    return bool(r.get("success"))


def _run_one(goal: str, ws: Workspace) -> dict:
    t0 = time.time()
    try:
        agent = CsvAgent(use_llm=False)
        out = agent.analyze(ws, goal)
        return {"success": out.get("success", False),
                "report_path": str(ws.report_md) if ws.report_md.exists() else "",
                "duration": round(time.time() - t0, 4)}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "error": str(e), "duration": round(time.time() - t0, 4)}


def run_csv_eval(base_dir=None) -> EvalReport:
    report = EvalReport()
    for t in build_csv_tasks():
        ws = Workspace.create(base=base_dir) if base_dir else Workspace.create()
        ws.save_csv(gen_sales(n=40, dirty="错误数据" in t["goal"]), "input.csv")
        r = _run_one(t["goal"], ws)
        passed = t["check"](r)
        report.add_result(EvalResult(
            task_id=t["goal"][:8], task_name=t["goal"],
            passed=passed, expected=None, actual=r, duration=r["duration"],
            details={"difficulty": t["difficulty"]}))
    return report


def run_comparison(runs: int = 3) -> List[Dict[str, Any]]:
    """Planner-Executor vs 简单 Agent Loop 基线对照。"""
    metrics = EvaluationMetrics()
    rows: List[Dict[str, Any]] = []
    goal = "分析销售额影响因素并生成报告"
    # --- Planner-Executor ---
    pe_results = [_run_one(goal, Workspace.create()) for _ in range(runs)]
    rows.append({"engine": "Planner-Executor",
                 "success_rate": metrics.task_success_rate(
                     [EvalResult("x", "x", r["success"], None, r, r["duration"])
                      for r in pe_results]),
                 "steps": f"{sum(1 for r in pe_results if r['success'])}/{runs}",
                 "duration": round(sum(r["duration"] for r in pe_results) / runs, 4)})
    # --- 简单 Agent Loop（顺序 noun 调工具）---
    loop_success = _run_simple_loop(goal)
    rows.append({"engine": "Agent Loop",
                 "success_rate": 1.0 if loop_success else 0.0,
                 "steps": "8", "duration": 0.0})
    return rows


def _run_simple_loop(goal: str) -> bool:
    """基线：固定顺序调 8 个工具（不重规划），任意失败即 False。"""
    ws = Workspace.create()
    ws.save_csv(gen_sales(n=40, dirty=True), "input.csv")
    agent = CsvAgent(use_llm=False)
    from code.workbench.csv_agent.servers.data_processor import data_clean, feature_engineer
    from code.workbench.csv_agent.servers.visualizer import eda_plot
    from code.workbench.csv_agent.servers.model_trainer import model_train, model_suggest
    from code.workbench.csv_agent.servers.report_generator import report_generate
    steps = [
        ("csv_load", {"ws": str(ws.root)}),
        ("data_summary", {"ws": str(ws.root)}),
        ("data_clean", {"ws": str(ws.root), "fill": "median"}),
        ("feature_engineer", {"ws": str(ws.root)}),
        ("eda_plot", {"ws": str(ws.root)}),
        ("model_suggest", {"ws": str(ws.root), "target": "sales", "goal": goal}),
        ("model_train", {"ws": str(ws.root), "target": "sales"}),
        ("report_generate", {"ws": str(ws.root), "goal": goal}),
    ]
    for name, params in steps:
        res = agent.tool_registry.get(name).execute(description=name, params=params)
        if not res.get("success"):
            return False
    return ws.report_md.exists()
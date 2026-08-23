import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from code.csv_agent.eval_csv import build_csv_tasks, run_csv_eval, run_comparison


def test_build_csv_tasks_has_20_plus():
    tasks = build_csv_tasks()
    assert len(tasks) >= 20
    assert {t["difficulty"] for t in tasks} == {"简单", "中等", "复杂", "困难"}


def test_run_csv_eval_smoke(tmp_path):
    report = run_csv_eval(tmp_path)
    assert report.total == len(build_csv_tasks())
    assert report.pass_rate >= 0.5  # 宽松冒烟


def test_comparison_shape():
    rows = run_comparison(runs=1)
    assert rows and {"engine", "success_rate", "steps", "duration"} <= set(rows[0])
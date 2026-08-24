"""csv-agent 命令行入口。

提供 analyze / sample 两个子命令，包装 CsvAgent 完成本地 CSV 数据分析。
"""
from __future__ import annotations

import os
import sys
import shutil
import argparse

from code.csv_agent.orchestrator import CsvAgent
from code.csv_agent.memory import MemoryStore
from code.csv_agent.datagen import gen_sales
from code.csv_agent.workspace import Workspace


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="csv-agent", description="CSV 数据分析命令行工具")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pa = sub.add_parser("analyze", help="分析一个 CSV 文件")
    pa.add_argument("csv", help="CSV 文件路径（--sample 时忽略）")
    pa.add_argument("goal", help="分析目标描述")
    pa.add_argument("--no-llm", action="store_true", help="不使用 LLM（本地规则模式）")
    pa.add_argument("--sample", action="store_true", help="使用生成的样例数据，忽略 csv 参数")

    ps = sub.add_parser("sample", help="生成样例 CSV 到文件")
    ps.add_argument("out", help="输出 CSV 路径")

    return parser


def parse_args(argv=None):
    return build_parser().parse_args(argv)


def cmd_analyze(args, workspace: Workspace):
    """执行分析：准备 CSV → 构造 CsvAgent → 返回 analyze() 结果 dict。"""
    csv_path = args.csv
    if args.sample:
        csv_path = workspace.save_csv(gen_sales(dirty=True), "input.csv")
    if not os.path.exists(csv_path):
        raise SystemExit(f"file not found: {csv_path}")
    # 把外部 CSV 复制到工作区作为输入，工具据此读写
    shutil.copy(csv_path, workspace.input_csv)
    agent = CsvAgent(use_llm=not args.no_llm, memory=MemoryStore())
    return agent.analyze(workspace, args.goal)


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.cmd == "sample":
        gen_sales(dirty=True).to_csv(args.out, index=False)
        print(f"样例数据已写入: {args.out}")
        return 0
    workspace = Workspace.create()
    out = cmd_analyze(args, workspace)
    print(f"success: {out['success']}")
    print(f"report: {out['report']}")
    return 0 if out.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
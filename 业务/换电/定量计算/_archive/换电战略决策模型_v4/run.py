from __future__ import annotations

from pathlib import Path

from config_loader import ROOT, load_config
from model import build_model
from report import write_outputs


def main() -> None:
    config = load_config()
    snapshot = build_model(config)
    report_path = ROOT.parent.parent / "分析结论" / "换电毛估估_战略投入产出与资本循环_v4.0.md"
    paths = write_outputs(config, snapshot, report_path)
    print(f"报告: {paths['report']}")
    print(f"决策快照: {paths['snapshot']}")
    print(f"Dashboard参数: {paths['parameters']}")
    print(f"最终判断: {snapshot.memos[-1].status}")
    print(f"CATL建设期累计资本调用: {snapshot.capex.catl_total_equity_call_yi:.1f}亿元")
    print(f"2030E换电增量价值: {snapshot.ledger.total_swap_increment_value_yi:.1f}亿元")


if __name__ == "__main__":
    main()


"""模型入口：只负责组装与调度，不持有任何业务口径或展示内容。

所有指标定义、表格与文案均在其子模块（scale / capex / report 等）中实现；
本文件仅完成：载入配置 → 按情景构建快照 → 交给report落盘 → 打印结果摘要。
"""
from __future__ import annotations

from config_loader import ROOT, load_config
from model import build_model
from report import (
    PRIVATE_SCENARIO_ORDER,
    format_private_scenario_console,
    write_outputs,
)

REPORT_NAME = "换电毛估估_宁德时代应不应该下重注_v4.2.3.md"


def main() -> None:
    config = load_config()
    # 私家车是需求侧最大不确定项：三档分档渗透率各完整重跑一条链，
    # 中枢作为报告基准，保守/激进并列进Part 7.2。
    snapshots = {
        scen: build_model(config, private_scenario=scen)
        for scen in PRIVATE_SCENARIO_ORDER
    }
    snapshot = snapshots["中枢"]
    # v3.2遗留寿命口径的对照重跑，仅供附录A.2量化口径变更影响，不参与基准结论。
    legacy_snapshot = build_model(config, private_scenario="中枢", life_mode="legacy_v32")
    report_path = ROOT.parent.parent / "分析结论" / REPORT_NAME
    paths = write_outputs(config, snapshot, report_path, snapshots, legacy_snapshot)
    print(f"报告: {paths['report']}")
    print(f"决策快照: {paths['snapshot']}")
    print(f"Dashboard参数: {paths['parameters']}")
    print(f"最终判断: {snapshot.memos[-1].status}")
    print("")
    print(format_private_scenario_console(snapshots))


if __name__ == "__main__":
    main()

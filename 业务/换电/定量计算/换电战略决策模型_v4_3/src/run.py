"""模型入口：只负责组装与调度，不持有任何业务口径或展示内容。

所有指标定义、表格与文案均在其子模块（scale / capex / report 等）中实现；
本文件仅完成：载入配置 → 按情景构建快照 → 交给report落盘 → 打印结果摘要。
"""
from __future__ import annotations

from config_loader import ROOT, load_config
from model import build_model, build_scenarios
from report import (
    format_private_scenario_console,
    write_outputs,
)

REPORT_NAME = "换电战略决策报告_v4.3.md"


def main() -> None:
    config = load_config()
    # 三情景 = [drivers] 声明的驱动因子**同时拨档**，每个情景完整重跑一条链。
    # 此前只拨私家车渗透率一档（DECISIONS「2026-09-02 · 三情景名不副实」），
    # 导致营运车（占 EBITDA 约 95%）在三档间恒定，情景区间形同虚设。
    snapshots = build_scenarios(config)
    snapshot = snapshots["中性"]
    # v3.2遗留寿命口径的对照重跑，仅供附录A.2量化口径变更影响，不参与基准结论。
    legacy_snapshot = build_model(config, private_scenario="中枢", life_mode="legacy_v32")
    # v4.3 目录自包含：报告与快照统一落 outputs/
    report_path = ROOT.parent / "outputs" / REPORT_NAME
    paths = write_outputs(config, snapshot, report_path, snapshots, legacy_snapshot)
    print(f"报告: {paths['report']}")
    print(f"决策快照: {paths['snapshot']}")
    print(f"Dashboard参数: {paths['parameters']}")
    print(f"最终判断: {snapshot.memos[-1].status}")
    print("")
    print(format_private_scenario_console(snapshots))
    # 生成"参数与血缘"工作簿（用户可读的敏感性分析；裸 CSV 不可读，不在此产出）
    try:
        from lab import cmd_workbook, rerun, read_metrics
        base_values = read_metrics(rerun(config))
        cmd_workbook(config, base_values)
        print("参数与血缘工作簿: outputs/换电模型_参数与血缘_v4.3.xlsx")
    except Exception as exc:  # 敏感性/Excel 生成失败不应阻断主报告
        print(f"⚠ 参数与血缘工作簿生成跳过：{exc}")
    # 步骤3：以终为始决策树（可口算视图，三情景链路审计）→ 可折叠 Excel
    try:
        import sys as _sys
        import tree
        _sys.argv = ["tree", "--xlsx"]
        tree.main()
        print("决策树(可口算视图): outputs/换电决策树_v4.3.xlsx")
    except Exception as exc:  # 决策树失败不应阻断主报告
        print(f"⚠ 决策树生成跳过：{exc}")
    # 步骤4：一页纸（核心终端指标 + 四列判断列）——方案 §2.1 定义的目标态
    try:
        import onepager
        onepager.main()
        print("一页纸(可口算视图): outputs/换电一页纸_v4.3.xlsx")
    except Exception as exc:  # 一页纸失败不应阻断主报告
        print(f"⚠ 一页纸生成跳过：{exc}")


if __name__ == "__main__":
    main()

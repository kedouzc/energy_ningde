"""数字回扫校验：验证叙述文档（MANIFEST.md）中的关键数字与决策快照一致。

背景
----
v4.3 报告三层分工：数据层（骨架表，机器生成）／必答问题层（机器填数）／
叙述层（MANIFEST.md，人写或 LLM 起草）。叙述层一旦脱离模型手改数字，
就会发生"文数脱钩"。本脚本从 decision_snapshot_v4_3.json 读取关键指标，
在叙述文档中回扫其多种格式化写法（千分位/无千分位/不同小数位），
逐项给出 PASS/FAIL，作为叙述层的强制关卡——同 station_capacity() 之于
规划能力的关系：验证是运行时关卡，不是一次性检查。

用法
----
python src/backscan.py [target_md]
默认 target = ../MANIFEST.md；快照固定读 ../outputs/decision_snapshot_v4_3.json。
退出码：全部 PASS 为 0，存在 FAIL 为 1（可挂 CI 或运行前自检）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SNAPSHOT_PATH = ROOT.parent / "outputs" / "decision_snapshot_v4_3.json"
DEFAULT_TARGET = ROOT.parent / "MANIFEST.md"


def _dig(data: dict, path: tuple[str, ...]) -> float:
    """按 ('capex', 'catl_total_equity_call_yi') 形式的路径取数。"""
    node = data
    for key in path:
        node = node[key]
    return float(node)


def _peak_funding(data: dict) -> dict:
    """取换电资本调用峰值年的资金行。"""
    return max(data["funding"], key=lambda row: row["swap_equity_call_yi"])


def build_metrics(data: dict) -> list[tuple[str, float, str]]:
    """返回 (指标名, 快照值, 单位) 列表——与骨架报告必答问题层同源。"""
    peak = _peak_funding(data)
    total_swap_gwh = sum(row["catl_swap_gwh"] for row in data["scale"]["rows"])
    swap_vehicles_wan = sum(
        data["scale"]["operating_stock_by_vehicle_wan"].values()
    )
    metrics = [
        # Q1 规模（快照站数键=四池/四站型；两大类汇总在读取端派生，重卡=短途+中长途）
        ("骐骥重卡站（终局）", float(sum(
            count for pool, count in data["scale"]["target_station_demand"].items()
            if pool.startswith("qiji75")
        )), "座"),
        ("巧克力站（终局）", float(sum(
            count for pool, count in data["scale"]["target_station_demand"].items()
            if pool.startswith("choco")
        )), "座"),
        ("CATL换电车辆（终局）", swap_vehicles_wan, "万辆"),
        ("换电电池总装机（终局）", total_swap_gwh, "GWh"),
        ("年换电交易电量", data["swap_business"]["annual_energy_yi_kwh"], "亿kWh"),
        # Q2 代价
        ("初装CAPEX合计", data["capex"]["total_initial_capex_yi"], "亿元"),
        ("全周期资本底座", data["capex"]["lifecycle_capital_base_yi"], "亿元"),
        ("CATL建设期累计资本调用", data["capex"]["catl_total_equity_call_yi"], "亿元"),
        ("CATL全周期权益承诺", data["capex"]["catl_lifecycle_equity_commitment_yi"], "亿元"),
        # Q3 价值（含运营层明细——§4.1.0 快照值，防文数脱钩）
        ("换电业务总收入", data["swap_business"]["revenue_yi"], "亿元"),
        ("服务费收入", data["swap_business"]["service_revenue_yi"], "亿元"),
        ("电池租金收入", data["swap_business"]["battery_rent_yi"], "亿元"),
        ("峰谷套利收入", data["swap_business"]["arbitrage_yi"], "亿元"),
        ("租金计费装机", data["swap_business"]["rent_eligible_gwh"], "GWh"),
        ("可交付EBITDA", data["swap_business"]["ebitda_yi"], "亿元"),
        ("年折旧", data["swap_business"]["depreciation_yi"], "亿元"),
        ("EBIT", data["swap_business"]["ebit_yi"], "亿元"),
        ("可归因换电增量价值", data["ledger"]["total_swap_increment_value_yi"], "亿元"),
        ("2030E动力电池业务线价值", data["ledger"]["power_value_2030_with_swap_yi"], "亿元"),
        ("无换电纯制造对照价值", data["ledger"]["power_value_2030_no_swap_yi"], "亿元"),
        ("CATL年可分派现金", data["swap_business"]["catl_forward_distributable_cash_yi"], "亿元"),
        # Q4 资金
        ("换电现金调用峰值", peak["swap_equity_call_yi"], "亿元"),
        ("战略敞口合计", data["strategic_exposure_yi"], "亿元"),
    ]
    return metrics


def _candidates(value: float) -> list[str]:
    """生成一个数值在行文中的常见写法（千分位×小数位组合）。"""
    formats = []
    for digits in (1, 0, 2):
        comma = f"{value:,.{digits}f}"
        plain = f"{value:.{digits}f}"
        formats.extend([comma, plain])
        if comma not in formats:
            formats.append(comma)
    # 去重且保序
    seen: set[str] = set()
    return [f for f in formats if not (f in seen or seen.add(f))]


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_TARGET
    if not SNAPSHOT_PATH.exists():
        print(f"快照不存在：{SNAPSHOT_PATH}（先运行 python src/run.py）")
        return 2
    if not target.exists():
        print(f"目标文档不存在：{target}")
        return 2
    data = json.loads(SNAPSHOT_PATH.read_text(encoding="utf-8"))
    text = target.read_text(encoding="utf-8")
    metrics = build_metrics(data)

    passed = 0
    print(f"回扫校验：{target.name} vs {SNAPSHOT_PATH.name}")
    print(f"{'指标':<28}{'快照值':>16}  结果")
    print("-" * 60)
    for name, value, unit in metrics:
        hit = next((c for c in _candidates(value) if c in text), None)
        if hit:
            passed += 1
            print(f"{name:<28}{value:>16,.1f}  PASS（匹配「{hit}{unit}」）")
        else:
            print(f"{name:<28}{value:>16,.1f}  FAIL（文档中未找到该数值）")
    print("-" * 60)
    print(f"合计：{passed}/{len(metrics)} 通过")
    return 0 if passed == len(metrics) else 1


if __name__ == "__main__":
    sys.exit(main())

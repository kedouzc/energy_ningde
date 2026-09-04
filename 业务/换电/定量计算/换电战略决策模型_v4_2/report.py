"""报告渲染层：所有指标定义、表格与文案都在这里，run.py只负责组装与打印。

变更历史
--------
v4.2.2（2026-08-29）
- 【新增】PRIVATE_SCENARIO_METRICS / format_private_scenario_console：私家车三情景的
  指标定义与终端格式化。此前这些口径写在run.py里，违反"run只做组装"的分层，本版移回本模块。
- 【新增】_private_scenario_tables：Part 7.2 私家车三情景（分档渗透率表＋完整重跑对比表＋解读）。
- 【新增】_battery_life_sections：Part 2.2.1 电池寿命由使用强度反推（大车短、小车长）表与解读。
- 【新增】_life_mode_comparison：附录A.2 新旧寿命口径完整重跑对比（含折旧税盾对现金的解释）。
- 【改动】站内电池寿命相关展示（单站经济表、建站时点说明）改用scale推算值，不再读硬编码。
"""
from __future__ import annotations

import json
from pathlib import Path
from string import Template
from typing import Callable, Iterable

from config_loader import ROOT, parameter_registry
from derived import (
    LEGACY_V32_STATION_LIFE_YEARS,
    LEGACY_V32_VEHICLE_LIFE_YEARS,
    battery_price_rmb_kwh,
    lifecycle_factors,
    terminal_residual_details,
)
from schemas import DecisionMemo, ModelSnapshot
from v32_audit import (
    outcome_audit_rows,
    parameter_audit_rows,
    station_reconciliation_rows,
)


def _n(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}"


def _p(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}%}"


def _x(value: float, digits: int = 2) -> str:
    return f"{value:.{digits}f}×"


def _table(headers: list[str], rows: Iterable[Iterable[object]]) -> str:
    text = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    text.extend("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows)
    return "\n".join(text)


def _memo_text(memo: DecisionMemo) -> str:
    def show(value: float | str | bool) -> str:
        if isinstance(value, bool):
            return "是" if value else "否"
        if isinstance(value, float):
            return _p(value) if 0 <= value < 1 else _n(value, 1)
        return str(value)

    evidence = "；".join(f"{key}={show(value)}" for key, value in memo.evidence.items())
    return (
        f"> **{memo.owner}｜{memo.status}**：{memo.conclusion}  \n"
        f"> 证据：{evidence}  \n"
        f"> 风险：{memo.key_risk}"
    )


def _build_sensitivity_interpretation(snapshot: ModelSnapshot) -> str:
    """按各参数组对2030动力电池价值的极差排序，生成7.1表后解读段落。

    解读分三部分：生死线（覆盖倍数最低的情景）、弹性排序（价值极差降序）、
    结论句（单变量扰动是否推翻中性结论）。全部由敏感性重跑结果计算，不手写数字。
    """
    rows = snapshot.sensitivity
    base_power_value = snapshot.ledger.power_value_2030_with_swap_yi
    groups: dict[str, list[dict]] = {}
    for row in rows:
        groups.setdefault(row["parameter_group"], []).append(row)

    ranked = sorted(
        (
            (group, max(r["power_value_2030_yi"] for r in items)
             - min(r["power_value_2030_yi"] for r in items))
            for group, items in groups.items()
        ),
        key=lambda item: item[1],
        reverse=True,
    )
    ranking_text = "＞".join(
        f"{group}（±{_n(spread / 2, 0)}亿）" for group, spread in ranked[:4]
    )

    worst = min(rows, key=lambda row: row["ebitda_coverage"])
    worst_below = [row for row in rows if row["ebitda_coverage"] < 1.0]
    if worst_below:
        below_text = "、".join(
            f"{row['parameter_group']}{row['scenario']}（覆盖{_x(row['ebitda_coverage'])}）"
            for row in worst_below
        )
        life_line = (
            f"**生死线**：以下情景的正算EBITDA跌破CRF门槛，项目在该情景下不覆盖资本要求——{below_text}。"
        )
    else:
        life_line = (
            f"**生死线**：全部单变量情景的覆盖倍数均未跌破1.0，最低为"
            f"{worst['parameter_group']}{worst['scenario']}的{_x(worst['ebitda_coverage'])}。"
        )

    charge_rows = groups.get("充电段份额差", [])
    if charge_rows:
        charge_worst = min(charge_rows, key=lambda row: row["power_value_2030_yi"])
        charge_drop = base_power_value - charge_worst["power_value_2030_yi"]
        still_above = (
            charge_worst["power_value_2030_yi"]
            > snapshot.ledger.power_value_2030_no_swap_yi
        )
        direction = (
            "仍高于无换电纯制造情景" if still_above else "已跌破无换电纯制造情景"
        )
        charge_text = (
            f"证据最弱的“充电段份额差”链条若完全归零（{charge_worst['scenario']}），"
            f"2030动力电池价值较中性下降{_n(charge_drop, 0)}亿元"
            f"（{_p(charge_drop / base_power_value)}），{direction}。"
        )
    else:
        charge_text = ""

    return (
        "**读表结论（程序按敏感度自动排序）**  \n"
        f"{life_line}  \n"
        f"**弹性排序**：对2030动力电池价值影响最大的四个参数组依次为{ranking_text}。"
        "估值倍数与净利率差直接作用于价值换算层；服务费与租金、电池价格先改变单体经营，"
        "再放大到估值；CRF只改变门槛，不制造价值。  \n"
        f"**结论句**：{charge_text}"
        "单变量扰动没有推翻中性结论——项目经营可行性与换电战略价值的主要威胁"
        "不在参数取值，而在充电段份额链条与估值倍数中枢的假设。"
    )


PRIVATE_SCENARIO_ORDER = ("保守", "中枢", "激进")

# 私家车三情景的指标定义（标签, 取值函数, 小数位）。
# 内容定义属于report层；run.py只负责组装与打印，不持有任何指标口径。
PRIVATE_SCENARIO_METRICS: list[tuple[str, Callable[[ModelSnapshot], float], int]] = [
    ("私家车换电车辆(万)", lambda s: s.scale.operating_stock_by_vehicle_wan.get("private", 0.0), 1),
    ("换电电池总装机(GWh)", lambda s: sum(r.catl_swap_gwh for r in s.scale.rows), 1),
    ("初装CAPEX合计(亿)", lambda s: s.capex.total_initial_capex_yi, 1),
    ("全周期资本底座(亿)", lambda s: s.capex.lifecycle_capital_base_yi, 1),
    ("CATL建设期资本调用(亿)", lambda s: s.capex.catl_total_equity_call_yi, 1),
    ("年折旧(亿)", lambda s: s.capex.mature_annual_depreciation_yi, 1),
    ("门槛EBITDA(亿)", lambda s: s.swap_business.required_ebitda_yi, 1),
    ("可交付EBITDA(亿)", lambda s: s.swap_business.ebitda_yi, 1),
    ("EBITDA覆盖倍数", lambda s: s.swap_business.forward_to_required_ebitda, 2),
    ("EBIT(亿)", lambda s: s.swap_business.ebit_yi, 1),
    ("最低年可分派现金(亿)", lambda s: s.swap_business.minimum_distributable_cash_yi, 1),
    ("可归因换电增量(亿)", lambda s: s.ledger.total_swap_increment_value_yi, 1),
    ("动力电池线价值(亿)", lambda s: s.ledger.power_value_2030_with_swap_yi, 1),
]


def format_private_scenario_console(snapshots: dict[str, ModelSnapshot]) -> str:
    """私家车三情景的终端文本表。指标口径定义在本模块，run.py只管打印。"""
    order = [s for s in PRIVATE_SCENARIO_ORDER if s in snapshots]
    lines = [
        "私家车三情景：",
        f"{'指标':<26}" + "".join(f"{s:>14}" for s in order),
    ]
    for label, extract, digits in PRIVATE_SCENARIO_METRICS:
        lines.append(
            f"{label:<26}"
            + "".join(f"{extract(snapshots[s]):>14,.{digits}f}" for s in order)
        )
    return "\n".join(lines)


def _battery_life_sections(config: dict, snapshot: ModelSnapshot) -> tuple[str, str]:
    """Part 2.2.1：电池寿命由使用强度反推的表格与解读（大车短、小车长）。"""
    days = config["swap_business"]["operating_days"]
    crit = config["battery_life_model"]["critical_cycles"]
    cap = config["battery_life_model"]["calendar_cap_years"]
    y0 = config["construction"]["years"][0]
    scale = snapshot.scale

    def life_of(freq: float) -> float:
        return min(crit / (freq * days), cap)

    def mult(life: float) -> float:
        return lifecycle_factors(config, y0, life).capital_multiplier

    def vehicle_freq(key: str) -> tuple[float, float]:
        rs = [r for r in scale.rows if r.vehicle_key == key]
        gwh = sum(r.catl_swap_gwh for r in rs)
        f = (sum(r.catl_swap_gwh * r.swap_frequency_per_day for r in rs) / gwh) if gwh else 0.0
        return f, gwh

    labels = {
        "heavy": "重卡", "city": "城配物流", "taxi": "出租车",
        "ridehail": "网约车", "robotaxi": "Robotaxi", "private": "私家车",
    }
    rows: list[tuple[object, ...]] = []
    # 重卡先列三个场景（车辆电池本就分场景计寿命），再列其使用量加权值
    for scene_name in ("短途", "中途", "长途"):
        rs = [r for r in scale.rows
              if r.vehicle_key == "heavy" and r.scene == scene_name]
        if not rs:
            continue
        f = rs[0].swap_frequency_per_day
        life = life_of(f)
        old = LEGACY_V32_VEHICLE_LIFE_YEARS["heavy"]
        rows.append((
            f"重卡-{scene_name}", f"{f:.2f}", f"{f*days:,.0f}",
            f"{life:.2f}", f"{old:.2f}", f"{life-old:+.2f}",
            f"{mult(old):.3f}→{mult(life):.3f}",
        ))
    for key in ("heavy", "city", "taxi", "ridehail", "robotaxi", "private"):
        f, gwh = vehicle_freq(key)
        life = life_of(f)
        old = LEGACY_V32_VEHICLE_LIFE_YEARS[key]
        rows.append((
            f"{labels[key]}（车辆·使用量加权）", f"{f:.2f}", f"{f*days:,.0f}",
            f"{life:.2f}", f"{old:.2f}", f"{life-old:+.2f}",
            f"{mult(old):.3f}→{mult(life):.3f}",
        ))
    for group, label in (("heavy", "骐骥重卡站"), ("choco", "巧克力站")):
        life = scale.station_battery_life_years[group]
        old = LEGACY_V32_STATION_LIFE_YEARS[group]
        rows.append((
            f"{label}（站内周转）", "—", "—",
            f"{life:.2f}", f"{old:.2f}", f"{life-old:+.2f}",
            f"{mult(old):.3f}→{mult(life):.3f}",
        ))

    table = _table(
        ["口径", "日均换电(次)", "年循环(次)", "推算寿命(年)",
         "v3.2旧值(年)", "差异", "资本倍数 旧→新"],
        rows,
    )

    h_f, _ = vehicle_freq("heavy")
    h_life = life_of(h_f)
    p_f, p_gwh = vehicle_freq("private")
    p_life = life_of(p_f)
    c_life = scale.station_battery_life_years["choco"]
    note = (
        f"这张表最值得注意的不是某个具体年数，而是**大车与小车被推向了相反方向**。"
        f"重卡是换电强度最高的资产：使用量加权日均换电{h_f:.2f}次（长途场景高达2.69次），"
        f"年循环{h_f*days:,.0f}次，约{h_life:.2f}年就走到{crit:,.0f}次临界点——"
        f"v3.2给它拍的{LEGACY_V32_VEHICLE_LIFE_YEARS['heavy']}年，反推只对应日均1.00次，"
        f"与它自己算出来的频次严重不符，等于低估了重卡的电池周转压力。"
        f"反过来，私家车日均换电仅{p_f:.2f}次，纯按循环可支撑{crit/(p_f*days):.1f}年，"
        f"但电池熬不过静置衰减与技术迭代，故由日历寿命封顶到{p_life:.0f}年。"
        f"巧克力站因池子里混入了大量低频私家车，整体使用强度被摊薄到{c_life:.2f}年，"
        f"反而比v3.2的3.8年更长。"
        f"\n\n结论对资本账的含义是直接的：重卡重置最密，资本倍数最高"
        f"（{mult(LEGACY_V32_VEHICLE_LIFE_YEARS['heavy']):.3f}→{mult(h_life):.3f}），"
        f"意味着**重卡的资本占用强度显著高于其装机占比**；"
        f"而私家车虽然装机不小（{p_gwh:.1f}GWh），重置压力却最轻"
        f"（倍数仅{mult(p_life):.3f}）。"
        f"因此“重卡换电更费钱”不是印象，而是由2000次循环临界点下的使用强度直接推出的结论——"
        f"这也解释了为什么重卡场景必须靠高频运营摊薄电池重置成本才成立。"
    )
    return table, note


def _life_mode_comparison(
    config: dict,
    snapshot: ModelSnapshot,
    legacy: ModelSnapshot | None,
) -> tuple[str, str]:
    """附录A.2：同一套输入下，新旧两套寿命口径完整重跑的结果对比。"""
    metrics: list[tuple[str, Callable[[ModelSnapshot], float], int, str]] = [
        ("重卡车辆电池寿命(年)",
         lambda s: s.scale.station_battery_life_years["heavy"], 2, "重卡使用量加权"),
        ("巧克力站周转电池寿命(年)",
         lambda s: s.scale.station_battery_life_years["choco"], 2, "使用量加权"),
        ("初装CAPEX合计(亿)", lambda s: s.capex.total_initial_capex_yi, 1, "车辆+站内+站体"),
        ("全周期资本底座(亿)", lambda s: s.capex.lifecycle_capital_base_yi, 1, "含历次更新"),
        ("CATL建设期资本调用(亿)", lambda s: s.capex.catl_total_equity_call_yi, 1, "40%经济权益"),
        ("年折旧(亿)", lambda s: s.capex.mature_annual_depreciation_yi, 1, "成熟年"),
        ("门槛EBITDA(亿)", lambda s: s.swap_business.required_ebitda_yi, 1, "CRF倒算"),
        ("可交付EBITDA(亿)", lambda s: s.swap_business.ebitda_yi, 1, "交易量正算"),
        ("EBITDA覆盖倍数", lambda s: s.swap_business.forward_to_required_ebitda, 2, "≥1.0方可覆盖"),
        ("EBIT(亿)", lambda s: s.swap_business.ebit_yi, 1, "EBITDA−折旧"),
        ("最低年可分派现金(亿)", lambda s: s.swap_business.minimum_distributable_cash_yi, 1, "CRF门槛链"),
        ("CATL可归因换电运营价值(亿)", lambda s: s.swap_business.catl_attributable_value_yi, 1, "运营层EV归母"),
        ("可归因换电增量价值(亿)", lambda s: s.ledger.total_swap_increment_value_yi, 1, "制造+运营"),
        ("动力电池业务线价值(亿)", lambda s: s.ledger.power_value_2030_with_swap_yi, 1, "有换电情景"),
    ]
    if legacy is None:
        return _table(
            ["指标", "v3.2寿命口径", "本报告口径", "差异", "说明"],
            [(label, "—", f"{ex(snapshot):,.{d}f}", "—", note)
             for label, ex, d, note in metrics],
        ), "未获取到v3.2寿命口径的对照快照，本节仅列示本报告口径结果。"

    rows = []
    for label, ex, digits, note in metrics:
        old_v, new_v = ex(legacy), ex(snapshot)
        delta = new_v - old_v
        pct = f" ({delta/old_v*100:+.1f}%)" if abs(old_v) > 1e-9 else ""
        rows.append((label, f"{old_v:,.{digits}f}", f"{new_v:,.{digits}f}",
                     f"{delta:+,.{digits}f}{pct}", note))
    table = _table(["指标", "v3.2寿命口径", "本报告口径", "差异", "说明"], rows)

    d_base = (snapshot.capex.lifecycle_capital_base_yi
              - legacy.capex.lifecycle_capital_base_yi)
    d_call = (snapshot.capex.catl_total_equity_call_yi
              - legacy.capex.catl_total_equity_call_yi)
    d_val = (snapshot.ledger.total_swap_increment_value_yi
             - legacy.ledger.total_swap_increment_value_yi)
    note = (
        f"寿命口径变更的净效应是**方向相反的两种力量相抵**：重卡寿命由"
        f"{LEGACY_V32_VEHICLE_LIFE_YEARS['heavy']}年缩短到"
        f"{snapshot.scale.station_battery_life_years['heavy']:.2f}年（重置更密、资本更重），"
        f"而巧克力站周转电池由{LEGACY_V32_STATION_LIFE_YEARS['choco']}年延长到"
        f"{snapshot.scale.station_battery_life_years['choco']:.2f}年（重置更少、资本更轻）。"
        f"两者相抵后，全周期资本底座变化{d_base:+.1f}亿、CATL建设期资本调用变化{d_call:+.1f}亿、"
        f"可归因换电增量价值变化{d_val:+.1f}亿。"
        f"\n\n表中有一处需要解释，否则容易被误读：年折旧大幅上升"
        f"（{legacy.capex.mature_annual_depreciation_yi:,.1f}→"
        f"{snapshot.capex.mature_annual_depreciation_yi:,.1f}亿），使EBIT由正转负"
        f"（{legacy.swap_business.ebit_yi:,.1f}→{snapshot.swap_business.ebit_yi:,.1f}亿），"
        f"但最低年可分派现金反而增加"
        f"（{legacy.swap_business.minimum_distributable_cash_yi:,.1f}→"
        f"{snapshot.swap_business.minimum_distributable_cash_yi:,.1f}亿）。"
        f"原因是折旧是非现金支出：它压低账面利润，却通过折旧税盾增加现金流"
        f"（FCFF＝EBITDA×(1−税率)＋折旧×税率−资本支出）。"
        f"这恰好印证了3.3节的判断——换电这类重资产基础设施，"
        f"可分派现金比净利润更适合作为回报口径，会计亏损不构成否决理由。"
        f"\n\n需要强调的是：本报告口径并非「调参」，而是把v3.2三个互相矛盾的拍值"
        f"换成与频次、里程、带电量和循环临界点自洽的推导结果。"
        f"v3.2重卡5.7年隐含日均换电仅1.00次，而同一套参数算出的实际强度是"
        f"1.83次——旧口径相当于默认重卡电池比它实际被使用的方式更耐用。"
        f"因此本表的差异，应读作「修正口径误差」而非「改变假设」。"
    )
    return table, note


def _private_market_totals(config: dict, pen: dict[str, float]) -> tuple[float, float]:
    """某档私家车渗透率下的全市场换电车辆与CATL可及车辆（万辆）。"""
    private = config["vehicles"]["private"]
    net_inc = sum(private["annual_net_additions_wan"])
    catl_share = private["scenes"][0]["catl_swap_share"]
    market = sum(
        net_inc * scene["weight"] * pen.get(scene["name"], 0.0)
        for scene in private["scenes"]
    )
    return market, market * catl_share


def _private_scenario_tables(
    config: dict, snapshots: dict[str, ModelSnapshot]
) -> tuple[str, str, str]:
    """私家车三情景：分档渗透率表、完整重跑对比表、解读。"""
    order = ("保守", "中枢", "激进")
    pen_table = config["vehicles"]["private"]["scenario_swap_penetration"]
    penetration_table = _table(
        ["情景", "8万元以下", "8至15万元", "15万元以上", "全市场换电保有(万)", "CATL可及(万)"],
        [
            (
                scen,
                _p(pen_table[scen]["8万元以下"], 0),
                _p(pen_table[scen]["8至15万元"], 0),
                _p(pen_table[scen]["15万元以上"], 0),
                _n(_private_market_totals(config, pen_table[scen])[0], 0),
                _n(_private_market_totals(config, pen_table[scen])[1], 0),
            )
            for scen in order if scen in pen_table
        ],
    )

    def cell(extractor, digits: int = 1, suffix: str = ""):
        out = []
        for scen in order:
            snap = snapshots.get(scen)
            out.append(f"{extractor(snap):,.{digits}f}{suffix}" if snap else "—")
        return out

    def _private_vehicles(snap):
        return snap.scale.operating_stock_by_vehicle_wan.get("private", 0.0)

    def _private_gwh(snap):
        return sum(r.catl_swap_gwh for r in snap.scale.rows if r.vehicle_key == "private")

    def _total_gwh(snap):
        return sum(r.catl_swap_gwh for r in snap.scale.rows)

    rows: list[tuple[object, ...]] = [
        ("私家车CATL换电车辆（万辆）", *cell(_private_vehicles),
         "分档渗透率×价格带权重×CATL市占率"),
        ("私家车装机（GWh）", *cell(_private_gwh), "车辆×56kWh÷100"),
        ("换电电池总装机（GWh）", *cell(_total_gwh), "含全部车型，营运车底座在三情景间恒定"),
        ("初装CAPEX合计（亿）", *cell(lambda s: s.capex.total_initial_capex_yi), "车辆电池＋站内电池＋站体"),
        ("全周期资本底座（亿）", *cell(lambda s: s.capex.lifecycle_capital_base_yi),
         "含历次更新，受电池寿命驱动"),
        ("CATL建设期资本调用（亿）", *cell(lambda s: s.capex.catl_total_equity_call_yi),
         "40%经济权益口径"),
        ("年折旧（亿）", *cell(lambda s: s.capex.mature_annual_depreciation_yi),
         "电池寿命越短、重置越密，折旧越高"),
        ("门槛EBITDA（亿）", *cell(lambda s: s.swap_business.required_ebitda_yi),
         "CRF倒算的最低经营要求"),
        ("可交付EBITDA（亿）", *cell(lambda s: s.swap_business.ebitda_yi), "交易量正算"),
        ("EBITDA覆盖倍数",
         *cell(lambda s: s.swap_business.forward_to_required_ebitda, digits=2, suffix="×"),
         "≥1.0方可覆盖门槛"),
        ("EBIT（亿）", *cell(lambda s: s.swap_business.ebit_yi),
         "EBITDA－折旧；换电重资产下会计口径为负，故净利润不具参考性"),
        ("最低年可分派现金（亿）", *cell(lambda s: s.swap_business.minimum_distributable_cash_yi),
         "正算经营FCFF－项目债务利息；基础设施更应看现金而非净利"),
        ("CATL可归因换电运营价值（亿）", *cell(lambda s: s.swap_business.catl_attributable_value_yi),
         "运营层EV归母"),
        ("可归因换电增量价值（亿）", *cell(lambda s: s.ledger.total_swap_increment_value_yi),
         "制造＋运营，可归因部分"),
        (f"动力电池业务线价值（亿）",
         *cell(lambda s: s.ledger.power_value_2030_with_swap_yi), "有换电情景"),
    ]
    scenario_table = _table(
        ["指标", "保守", "中枢", "激进", "口径/说明"], rows
    )

    base = snapshots.get("中枢")
    if base:
        low = snapshots.get("保守")
        high = snapshots.get("激进")
        spread = ""
        if low and high:
            spread = (
                f"私家车从保守到激进，可归因换电增量价值由"
                f"{_n(low.ledger.total_swap_increment_value_yi, 1)}亿到"
                f"{_n(high.ledger.total_swap_increment_value_yi, 1)}亿，"
                f"极差{_n(high.ledger.total_swap_increment_value_yi - low.ledger.total_swap_increment_value_yi, 1)}亿"
                f"（约为中枢{_n(base.ledger.total_swap_increment_value_yi, 1)}亿的"
                f"{_p((high.ledger.total_swap_increment_value_yi - low.ledger.total_swap_increment_value_yi) / base.ledger.total_swap_increment_value_yi, 0)}）。"
            )
        coverage_low = low.swap_business.forward_to_required_ebitda if low else None
        note = (
            f"三情景共享同一套营运车底座：重卡、城配、出租/网约/Robotaxi的车辆数、频次、"
            f"装站需求在三档之间完全一致，差异全部来自私家车这一档，因此本表可直接读作"
            f"“私家车这块的不确定性到底值多少钱”。{spread}"
        )
        # 覆盖倍数随渗透率上升而递减：私家车日均换电仅约0.2次，每增加一辆都在抬高
        # 装机与门槛EBITDA，其贡献的服务费与租金却远低于营运车，故单位资本效率递减。
        covers = {
            scen: snap.swap_business.forward_to_required_ebitda
            for scen, snap in snapshots.items() if snap
        }
        if "保守" in covers and "激进" in covers:
            if covers["激进"] < covers["保守"]:
                note += (
                    f"需要特别注意：覆盖倍数随渗透率上升而**下降**"
                    f"（{covers['保守']:.2f}×→{covers['中枢'] if '中枢' in covers else covers['激进']:.2f}×"
                    f"→{covers['激进']:.2f}×）。私家车日均换电仅约0.2次，每增加一辆都在抬高"
                    f"装机与门槛EBITDA，其带来的服务费和电池租金却远低于营运车，因此私家车是"
                    f"“绝对价值增厚、单位资本效率递减”的业务——它放大总盘子，但会摊薄项目整体的"
                    f"资本回报率。这决定了私家车应当被当作**顺周期的上行期权**去争取，"
                    f"而不应作为立项时的必要假设。"
                )
        if coverage_low is not None:
            note += f"保守档EBITDA覆盖倍数为{coverage_low:.2f}×，"
            if coverage_low >= 1.0:
                note += (
                    f"回看保守档的{coverage_low:.2f}×，它仍在门槛之上：即便私家车几乎不渗透，"
                    f"仅靠营运车底座项目就已成立——私家车决定的是上行空间有多大，"
                    f"而不是项目能不能立。"
                )
            else:
                note += (
                    "已跌破1.0门槛：私家车渗透是项目成立的必要条件之一，"
                    "并非可有可无的上行项。"
                )
    else:
        note = "未获取到中枢情景快照，三情景对比未完整生成。"
    return penetration_table, scenario_table, note


def render_report(
    config: dict,
    snapshot: ModelSnapshot,
    private_snapshots: dict[str, ModelSnapshot] | None = None,
    legacy_snapshot: ModelSnapshot | None = None,
) -> str:
    ledger = snapshot.ledger
    baseline = ledger.baseline
    capex = snapshot.capex
    swap = snapshot.swap_business
    scale = snapshot.scale
    # 城配换电块寿命：按CATL换电装机GWh加权的推算值（寿命已不再硬编码于配置）。
    _city_life_rows = [row for row in scale.rows if row.vehicle_key == "city"]
    _city_life_gwh = sum(row.catl_swap_gwh for row in _city_life_rows)
    city_battery_life_years = (
        sum(row.catl_swap_gwh * row.battery_life_years for row in _city_life_rows)
        / _city_life_gwh
        if _city_life_gwh
        else 0.0
    )
    sources = snapshot.sources
    current_light = max(snapshot.light_asset, key=lambda row: row.terminal_ownership)
    light_by_ownership = {
        row.terminal_ownership: row for row in snapshot.light_asset
    }
    final_memo = snapshot.memos[-1]
    memo_map = {memo.owner: memo for memo in snapshot.memos}

    source_table = _table(
        ["事实基准", "本模型采用内容", "来源"],
        [
            (
                "2025A",
                "集团与动力电池收入、归母净利润、经营现金流",
                f"[宁德时代2025年报]({sources['annual_report_2025']})",
            ),
            (
                "2026H1",
                "集团与动力业务毛利、归母净利润、CFO、现金及交易性金融资产",
                f"[港交所披露检索]({sources['interim_report_2026_hkex']})",
            ),
            (
                "2026E",
                "集团归母净利润一致预期中性值",
                f"[盈利预测汇总]({sources['consensus_reference']})",
            ),
            (
                "换电建站",
                f"官方{config['meta']['reference_year']}目标为骐骥"
                f"{_n(config['construction']['official_2026_station_plan']['heavy'])}座、巧克力超"
                f"{_n(config['construction']['official_2026_station_plan']['choco'])}座；模型按"
                f"{_n(config['construction']['station_2026_cumulative_targets']['heavy'])}/"
                f"{_n(config['construction']['station_2026_cumulative_targets']['choco'])}，并在"
                f"{config['construction']['station_network_completion_year']}完成需求站数",
                f"[宁德时代换电网络进展]({sources['catl_swap_plan_2026']})",
            ),
            (
                "分红习惯",
                f"连续三年按归母净利润约{_p(config['group_funding']['dividend_payout_ratio'], 0)}现金分红，作为资金压力情景",
                f"[2025年报致股东信]({sources['dividend_habit']})",
            ),
            (
                "蔚来站网",
                "站数、累计换电量和累计交付电量",
                f"[蔚来1亿次换电公告]({sources['nio_network_2026']})",
            ),
            (
                "蔚能电池资产",
                "ABS底层样本资产评估、出租率与租金",
                f"[世联资产评估报告]({sources['nio_abs_appraisal_local']})",
            ),
            (
                "蔚能整体参考",
                "电池银行规模、用户、资产负债与融资估值整理",
                f"[蔚能REITs案例分析]({sources['nio_reits_analysis_local']})",
            ),
            (
                "市值",
                sources["market_cap_note"],
                "用户给定市场快照，不外推其他业务线",
            ),
        ],
    )

    parameter_table = _table(
        ["参数", "中性值", "来源/用途"],
        [
            ("WACC", _p(config["finance"]["wacc"]), "照抄蔚来ABS横向基准；只用于现值折现"),
            (
                "资本回收系数CRF",
                _p(config["finance"]["capital_recovery_factor"]),
                f"期望回报{_p(config['finance']['required_return_range'][0], 0)}—{_p(config['finance']['required_return_range'][1], 0)}对应区间的中值；用于倒算年资本要求",
            ),
            (
                "建设期CATL经济权益",
                _p(config["finance"]["construction_ownership"]),
                "2030前用于资本调用与归母价值；轻资产只在业务成熟后讨论",
            ),
            ("项目债务比例", _p(config["finance"]["debt_ratio"]), "项目资本结构"),
            ("制造估值", _x(config["finance"]["manufacturing_pe"], 1) + " PE", "制造归母净利润×PE"),
            ("换电运营估值", _x(config["finance"]["swap_ev_ebitda"], 1), "EBITDA×倍数－债务，再乘CATL权益"),
            (
                "电池价格路径",
                " / ".join(
                    f"{year}:{_n(price, 1)}"
                    for year, price in capex.battery_price_path_rmb_kwh.items()
                ),
                "2026—2028平台期，之后先快降、再慢降；由曲线参数生成",
            ),
            (
                "退役回收率",
                _p(capex.retirement_recovery_ratio),
                "储能/动力价格比×退役SOH×二手折价；不是期末残值率",
            ),
        ],
    )

    h1 = config["financial_2026h1"]
    power_gp = h1["power_battery_revenue_yi"] * h1["power_battery_gross_margin"]
    group_gp = h1["group_revenue_yi"] * h1["group_gross_margin"]
    baseline_table = _table(
        ["2026E动力电池基准拆分", "公式", "结果"],
        [
            ("H1动力毛利润", "动力收入×动力毛利率", _n(power_gp, 1) + "亿元"),
            ("H1集团毛利润", "集团收入×集团毛利率", _n(group_gp, 1) + "亿元"),
            ("动力归因比例", "动力毛利润÷集团毛利润", _p(baseline.power_gross_profit_share)),
            (
                "2026E动力归母净利润",
                "集团一致预期净利润×动力归因比例",
                _n(baseline.power_net_profit_2026e_yi, 1) + "亿元",
            ),
            (
                "2026E动力市值贡献",
                "A+H市值×动力归因比例",
                _n(baseline.power_market_value_2026e_yi, 1) + "亿元",
            ),
            (
                "2026E量价法制造模型净利润",
                f"{_n(config['financial_2026e']['power_battery_shipments_gwh'], 0)}GWh×"
                f"当年电池价格×{_p(config['swap_business']['with_swap_manufacturing_net_margin'], 0)}",
                _n(baseline.modeled_power_net_profit_2026e_yi, 1) + "亿元",
            ),
            (
                "2026E量价法制造模型价值",
                "量价法制造净利润×PE",
                _n(baseline.modeled_power_market_value_2026e_yi, 1) + "亿元",
            ),
            (
                "校验",
                "动力市值＋其余业务当前市值＝当前A+H市值",
                _n(baseline.group_market_value_2026e_yi, 1) + "亿元",
            ),
        ],
    )
    baseline_method_gap_table = _table(
        ["2026E口径", "归母净利润", "价值", "数据含义"],
        [
            (
                "H1财务分摊法",
                _n(baseline.power_net_profit_2026e_yi, 1),
                _n(baseline.power_market_value_2026e_yi, 1),
                "动力分部毛利润占集团毛利润×集团净利润/市值；覆盖动力分部全部用途及共同费用分摊",
            ),
            (
                "644GWh量价法",
                _n(baseline.modeled_power_net_profit_2026e_yi, 1),
                _n(baseline.modeled_power_market_value_2026e_yi, 1),
                "券商出货预测×590元×15%×PE20；近似作为道路交通制造比较锚",
            ),
            (
                "方法差额",
                _n(
                    baseline.power_net_profit_2026e_yi
                    - baseline.modeled_power_net_profit_2026e_yi,
                    1,
                ),
                _n(
                    baseline.power_market_value_2026e_yi
                    - baseline.modeled_power_market_value_2026e_yi,
                    1,
                ),
                "估算方法差，不是已识别的船舶/eVTOL/机器人利润；没有依据把差额归到具体终端",
            ),
        ],
    )

    annual_scale_table = _table(
        ["年份", "CATL换电装机", "CATL充电装机", "无换电纯制造装机"],
        [
            (
                year,
                _n(scale.annual_catl_swap_gwh[year], 1) + "GWh",
                _n(scale.annual_catl_charge_gwh[year], 1) + "GWh",
                _n(scale.annual_catl_no_swap_gwh[year], 1) + "GWh",
            )
            for year in scale.years
        ],
    )
    frequency_rows = []
    for key, vehicle in config["vehicles"].items():
        frequency_rows.append((
            vehicle["label"],
            _n(scale.operating_stock_by_vehicle_wan[key], 1),
            _n(scale.terminal_frequency_by_vehicle[key], 1),
            "原始漏斗/频次先完整计算，在车型终局节点各保留1位小数",
        ))
    frequency_table = _table(
        ["车型", "累计CATL换电车", "加权日频次", "推导"], frequency_rows
    )
    station_demand_table = _table(
        ["站网", "工位上限", "能量上限", "规划能力（外生）", "成熟日需求", "终局站数", "2025末存量", "2026累计目标", "建成"],
        [
            (
                "骐骥重卡",
                _n(scale.station_capacity_diagnostics["heavy"]["mechanical_limit"], 0),
                _n(scale.station_capacity_diagnostics["heavy"]["energy_limit"], 0),
                _n(scale.station_capacity_diagnostics["heavy"]["planning_capacity"], 0),
                _n(scale.mature_daily_swaps["heavy"], 0) + "次",
                _n(scale.target_station_demand["heavy"]) + "座",
                _n(config["construction"]["opening_2025_stations"]["heavy"]) + "座",
                _n(config["construction"]["station_2026_cumulative_targets"]["heavy"]) + "座",
                str(config["construction"]["station_network_completion_year"]),
            ),
            (
                "巧克力",
                _n(scale.station_capacity_diagnostics["choco"]["mechanical_limit"], 0),
                _n(scale.station_capacity_diagnostics["choco"]["energy_limit"], 0),
                _n(scale.station_capacity_diagnostics["choco"]["planning_capacity"], 0),
                _n(scale.mature_daily_swaps["choco"], 0) + "次",
                _n(scale.target_station_demand["choco"]) + "座",
                _n(config["construction"]["opening_2025_stations"]["choco"]) + "座",
                _n(config["construction"]["station_2026_cumulative_targets"]["choco"]) + "座",
                str(config["construction"]["station_network_completion_year"]),
            ),
        ],
    )
    station_reconciliation_table = _table(
        [
            "车辆组", "v3.2车辆(万)", "v4.1车辆(万)", "v3.2频次",
            "v4.1频次", "v3.2日需求(万次)", "v4.1日需求(万次)", "差异解释",
        ],
        station_reconciliation_rows(config, snapshot),
    )

    station_unit_rows = []
    station_unit_metrics: dict[str, dict[str, float]] = {}
    station_labels = {"heavy": "骐骥重卡", "choco": "巧克力"}
    swap_cfg = config["swap_business"]
    price_2026 = battery_price_rmb_kwh(config, config["construction"]["years"][0])
    crf = config["finance"]["capital_recovery_factor"]
    station_economics_rows = []
    for group in ("heavy", "choco"):
        station = config["stations"][group]
        station_battery_gwh = (
            1000 * station["inventory_blocks"] * station["block_kwh"] / 1e6
        )
        battery_capex = (
            station_battery_gwh
            * battery_price_rmb_kwh(config, config["construction"]["years"][0])
            / 100.0
        )
        body_capex = 1000 * station["station_body_capex_wan"] / 1e4
        factor = lifecycle_factors(
            config,
            config["construction"]["years"][0],
            # 站内电池寿命改为按本组所服务车型GWh加权推算，不再读硬编码。
            scale.station_battery_life_years[group],
        )
        lifecycle_capital = body_capex + battery_capex * factor.capital_multiplier
        arbitrage = (
            station_battery_gwh
            * config["swap_business"]["operating_days"]
            * config["swap_business"]["grid_spread_rmb_kwh"]
            * config["swap_business"]["rte"]
            / 100.0
        )
        station_battery_rent = (
            station_battery_gwh
            * config["swap_business"]["swap_battery_external_sales_share"]
            * config["swap_business"]["battery_rent_rmb_kwh_year"]
            / 100.0
        )
        site_rent = (
            1000 * config["swap_business"]["site_rent_wan_year"] / 1e4
        )
        ebitda_delta = station_battery_rent + arbitrage - site_rent
        # 单站满负荷经济账：服务费按外生规划能力满打满算，人工随次数；两项合计为满负荷EBITDA。
        full_load_swaps_day = station["planning_daily_capacity"]
        full_load_energy_kwh_day = (
            full_load_swaps_day
            * station["block_kwh"]
            * swap_cfg["usable_energy_factor"]
        )
        full_load_service_wan = (
            full_load_energy_kwh_day
            * swap_cfg["service_fee_rmb_kwh"]
            * swap_cfg["operating_days"]
            / 1e4
        )
        labor_per_swap = (
            swap_cfg["heavy_labor_rmb_swap"]
            if group == "heavy"
            else swap_cfg["passenger_labor_rmb_swap"]
        )
        full_load_labor_wan = (
            full_load_swaps_day
            * labor_per_swap
            * swap_cfg["operating_days"]
            / 1e4
        )
        demand_side_ebitda_wan = full_load_service_wan - full_load_labor_wan
        # 单站经济表统一为“万元/站”口径：站体、电池、租金、套利与场租原为
        # 千站·亿元，×10换算为单站·万元，避免与满负荷服务费（万元/站）混算。
        per_station_wan = 1e4 / 1000.0
        body_capex_station_wan = body_capex * per_station_wan
        battery_capex_station_wan = battery_capex * per_station_wan
        lifecycle_capital_station_wan = lifecycle_capital * per_station_wan
        ebitda_delta_station_wan = ebitda_delta * per_station_wan
        full_load_ebitda_wan = demand_side_ebitda_wan + ebitda_delta_station_wan
        annual_capital_charge_wan = lifecycle_capital_station_wan * crf
        breakeven_utilization = (
            annual_capital_charge_wan / full_load_ebitda_wan
            if full_load_ebitda_wan > 0
            else None
        )
        full_load_payback_years = (
            lifecycle_capital_station_wan / full_load_ebitda_wan
            if full_load_ebitda_wan > 0
            else None
        )
        station_unit_metrics[group] = {
            "initial_capex": body_capex + battery_capex,
            "lifecycle_capital": lifecycle_capital,
            "arbitrage": arbitrage,
            "station_battery_rent": station_battery_rent,
            "site_rent": site_rent,
            "ebitda_delta": ebitda_delta,
            "value_delta": (
                ebitda_delta * config["finance"]["swap_ev_ebitda"]
                - lifecycle_capital * config["finance"]["debt_ratio"]
            )
            * config["finance"]["construction_ownership"],
        }
        station_economics_rows.append({
            "group": group,
            "station": station,
            "battery_wan": battery_capex_station_wan,
            "body_wan": body_capex_station_wan,
            "lifecycle_capital": lifecycle_capital_station_wan,
            "full_load_service_wan": full_load_service_wan,
            "full_load_labor_wan": full_load_labor_wan,
            "demand_side_ebitda_wan": demand_side_ebitda_wan,
            "asset_side_ebitda_wan": ebitda_delta_station_wan,
            "full_load_ebitda_wan": full_load_ebitda_wan,
            "annual_capital_charge_wan": annual_capital_charge_wan,
            "breakeven_utilization": breakeven_utilization,
            "full_load_payback_years": full_load_payback_years,
        })
        station_unit_rows.append((
            station_labels[group],
            _n(station_battery_gwh, 3),
            _n(body_capex + battery_capex, 1),
            _n(lifecycle_capital, 1),
            _n(station_battery_rent, 2),
            _n(arbitrage, 2),
            _n(site_rent, 2),
            _n(ebitda_delta, 2),
            _n(station_unit_metrics[group]["value_delta"], 2),
        ))

    def _wan(value: float) -> str:
        return _n(value, 1) + "万元"

    heavy_row = station_economics_rows[0]
    choco_row = station_economics_rows[1]
    station_economics_table = _table(
        ["计算项目", "公式", "参数代入", "骐骥重卡站", "巧克力站"],
        [
            (
                "① 站体初装投资",
                "外生输入（不含站内电池）",
                "—",
                _wan(heavy_row["body_wan"]),
                _wan(choco_row["body_wan"]),
            ),
            (
                "② 电池库存初装投资",
                "库存块数×单块电量×电池价格",
                f"{heavy_row['station']['inventory_blocks']:g}×{heavy_row['station']['block_kwh']:g}kWh / "
                f"{choco_row['station']['inventory_blocks']:g}×{choco_row['station']['block_kwh']:g}kWh；"
                f"电池价{_n(price_2026, 0)}元/kWh",
                _wan(heavy_row["battery_wan"]),
                _wan(choco_row["battery_wan"]),
            ),
            (
                "③ 单站初装CAPEX",
                "①＋②",
                "—",
                _wan(heavy_row["body_wan"] + heavy_row["battery_wan"]),
                _wan(choco_row["body_wan"] + choco_row["battery_wan"]),
            ),
            (
                "④ 单站全周期资本",
                "站体＋电池×全周期资本倍数（含历次更新）",
                f"寿命{scale.station_battery_life_years['heavy']:g}年 / "
                f"{scale.station_battery_life_years['choco']:g}年（按组GWh加权推算）",
                _wan(heavy_row["lifecycle_capital"]),
                _wan(choco_row["lifecycle_capital"]),
            ),
            (
                "⑤ 满负荷服务费收入/年",
                "规划日次×运营天数×单次净电量×服务费",
                f"{heavy_row['station']['planning_daily_capacity']:g}次/日×{swap_cfg['operating_days']:g}天"
                f"×{_p(swap_cfg['usable_energy_factor'], 0)}×{swap_cfg['service_fee_rmb_kwh']:g}元",
                _wan(heavy_row["full_load_service_wan"]),
                _wan(choco_row["full_load_service_wan"]),
            ),
            (
                "⑥ 满负荷人工运维/年",
                "规划日次×运营天数×单次人工",
                f"单次{swap_cfg['heavy_labor_rmb_swap']:g}元 / {swap_cfg['passenger_labor_rmb_swap']:g}元",
                _wan(heavy_row["full_load_labor_wan"]),
                _wan(choco_row["full_load_labor_wan"]),
            ),
            (
                "⑦ 需求侧EBITDA/年",
                "⑤－⑥",
                "—",
                _wan(heavy_row["demand_side_ebitda_wan"]),
                _wan(choco_row["demand_side_ebitda_wan"]),
            ),
            (
                "⑧ 资产侧EBITDA/年",
                "外部权益租金＋套利－场租",
                f"外部权益{_p(swap_cfg['swap_battery_external_sales_share'], 0)}；"
                f"场租{config['swap_business']['site_rent_wan_year']:g}万元/站",
                _wan(heavy_row["asset_side_ebitda_wan"]),
                _wan(choco_row["asset_side_ebitda_wan"]),
            ),
            (
                "⑨ 满负荷单站EBITDA/年",
                "⑦＋⑧",
                "—",
                _wan(heavy_row["full_load_ebitda_wan"]),
                _wan(choco_row["full_load_ebitda_wan"]),
            ),
            (
                "⑩ 年资本要求",
                "④×CRF",
                f"CRF {_p(crf, 1)}",
                _wan(heavy_row["annual_capital_charge_wan"]),
                _wan(choco_row["annual_capital_charge_wan"]),
            ),
            (
                "⑪ 盈亏平衡利用率",
                "⑩÷⑨",
                "利用率低于此值则单站不覆盖资本要求",
                _p(heavy_row["breakeven_utilization"]) if heavy_row["breakeven_utilization"] else "不适用",
                _p(choco_row["breakeven_utilization"]) if choco_row["breakeven_utilization"] else "不适用",
            ),
            (
                "⑫ 满负荷CAPEX回收期",
                "④÷⑨",
                "不含建设期爬坡",
                _n(heavy_row["full_load_payback_years"], 1) + "年" if heavy_row["full_load_payback_years"] else "不适用",
                _n(choco_row["full_load_payback_years"], 1) + "年" if choco_row["full_load_payback_years"] else "不适用",
            ),
        ],
    )
    station_economics_note = (
        f"满负荷口径指按外生规划能力（骐骥{heavy_row['station']['planning_daily_capacity']:g}次/日、"
        f"巧克力{choco_row['station']['planning_daily_capacity']:g}次/日）打满，这是单站经济上界；"
        f"盈亏平衡利用率才是单站生死线：骐骥站利用率只要"
        f"约{_p(heavy_row['breakeven_utilization'], 0)}即可覆盖CRF资本要求，"
        f"巧克力站需要约{_p(choco_row['breakeven_utilization'], 0)}——几乎要按设计能力满负荷运转。"
        "这解释了为什么模型坚持站数由需求反推：巧克力站在低利用率下是纯现金消耗，"
        "骐骥站则对利用率波动有较强缓冲。"
    )
    station_unit_impact_table = _table(
        [
            "每增加1,000站", "站内电池(GWh)", "初装CAPEX", "全周期资本",
            "外部权益电池租金/年", "套利收入/年", "场租/年", "固定需求下EBITDA变化", "CATL运营价值变化",
        ],
        station_unit_rows,
    )
    old_station_targets = {"heavy": 3563, "choco": 8902}
    station_delta_rows = []
    total_initial_delta = 0.0
    total_ebitda_delta = 0.0
    total_value_delta = 0.0
    for group in ("heavy", "choco"):
        old_count = old_station_targets[group]
        current_count = scale.target_station_demand[group]
        delta = current_count - old_count
        metrics = station_unit_metrics[group]
        initial_delta = metrics["initial_capex"] * delta / 1000.0
        ebitda_delta = metrics["ebitda_delta"] * delta / 1000.0
        value_delta = metrics["value_delta"] * delta / 1000.0
        total_initial_delta += initial_delta
        total_ebitda_delta += ebitda_delta
        total_value_delta += value_delta
        station_delta_rows.append((
            station_labels[group],
            f"{old_count:,}",
            f"{current_count:,}",
            f"{delta:+,}",
            _n(initial_delta, 2),
            _n(ebitda_delta, 2),
            _n(value_delta, 2),
        ))
    station_delta_rows.append((
        "合计", "12,465", f"{sum(scale.target_station_demand.values()):,}",
        f"{sum(scale.target_station_demand.values()) - 12465:+,}",
        _n(total_initial_delta, 2), _n(total_ebitda_delta, 2),
        _n(total_value_delta, 2),
    ))
    station_delta_impact_table = _table(
        [
            "站网", "v3.2站数", "v4.1站数", "站数变化", "初装CAPEX一阶变化",
            "稳态EBITDA一阶变化", "CATL运营价值一阶变化",
        ],
        station_delta_rows,
    )

    capital_factor_rows = []
    for label, factor in sorted(capex.lifecycle_factor_by_life.items()):
        life = float(label.removesuffix("年"))
        details = terminal_residual_details(
            config, config["construction"]["years"][0], life
        )
        capital_factor_rows.append((
            label,
            _x(factor, 3),
            _p(details.horizon_price_ratio),
            _n(details.terminal_batch_age_years, 1),
            _p(details.terminal_batch_soh),
            f"{details.storage_to_power_price_ratio:.3f}×{_p(details.secondary_market_discount,0)}",
            _p(details.terminal_residual_ratio),
        ))
    capital_factor_table = _table(
        [
            "电池寿命", "全周期资本倍数", "第15年共同价格折", "末批在役年龄",
            "末批SOH", "储能价格比×二手折价", "期末在役批可回收价值/初装",
        ],
        capital_factor_rows,
    )

    capex_table = _table(
        [
            "年份", "新增/累计重卡站", "新增/累计巧克力站", "车辆电池", "站内电池",
            "站体", "首轮更新净支出", "项目CAPEX", "CATL资本调用",
        ],
        [
            (
                row.year,
                f"{_n(row.new_heavy_stations)}/{_n(row.cumulative_heavy_stations)}",
                f"{_n(row.new_choco_stations)}/{_n(row.cumulative_choco_stations)}",
                _n(row.vehicle_battery_capex_yi, 1),
                _n(row.station_battery_capex_yi, 1),
                _n(row.station_body_capex_yi, 1),
                _n(row.replacement_net_capex_yi, 1),
                _n(row.total_project_capex_yi, 1),
                _n(row.catl_equity_call_yi, 1),
            )
            for row in capex.annual
        ],
    )
    # 2.2表补充的实物规模与EAC派生资本倍数：五年新增与2030年保有分开，
    # EAC=等效全周期资本底座÷终局初装，方法沿用v3.2 §1.2.1折扣链。
    new_swap_vehicles_wan = sum(row.catl_swap_vehicles_wan for row in scale.rows)
    new_stations_5y = (
        sum(capex.station_targets.values()) - sum(capex.opening_station_stock.values())
    )
    new_vehicle_battery_gwh = sum(scale.annual_catl_swap_gwh.values())
    terminal_swap_stock_wan = sum(scale.operating_stock_by_vehicle_wan.values())
    terminal_stations = sum(capex.station_targets.values())
    terminal_vehicle_battery_gwh = sum(
        scale.operating_stock_by_vehicle_wan[key]
        * vehicle["battery_kwh"] / 100.0
        for key, vehicle in config["vehicles"].items()
    )
    terminal_station_battery_gwh = sum(
        capex.station_targets[group]
        * config["stations"][group]["inventory_blocks"]
        * config["stations"][group]["block_kwh"] / 1e6
        for group in ("heavy", "choco")
    )
    eac_multiple = capex.lifecycle_capital_base_yi / capex.total_initial_capex_yi
    capex_summary = _table(
        ["计算项目", "公式", "参数代入", "结果"],
        [
            (
                "2025年末存量站等效初装CAPEX",
                "存量站体＋站内电池",
                f"305座骐骥＋1,020座巧克力；已投入、不进入2026现金",
                _n(capex.preperiod_station_initial_capex_yi, 1) + "亿元",
            ),
            (
                "2026—2030新增初装CAPEX",
                "逐年新增车辆电池＋新增站内电池＋新增站体",
                f"5年合计新增装车{_n(new_swap_vehicles_wan, 1)}万辆、新站{new_stations_5y:,.0f}座、"
                f"新增车辆电池{_n(new_vehicle_battery_gwh, 1)}GWh；终局初装－2025存量",
                _n(
                    capex.total_initial_capex_yi
                    - capex.preperiod_station_initial_capex_yi,
                    1,
                ) + "亿元",
            ),
            (
                "终局初装项目CAPEX",
                "2025存量＋2026—2030新增",
                f"2030年最终保有装车{_n(terminal_swap_stock_wan, 1)}万辆、站{terminal_stations:,.0f}座、"
                f"车辆电池{_n(terminal_vehicle_battery_gwh, 1)}GWh＋站内电池{_n(terminal_station_battery_gwh, 1)}GWh",
                _n(capex.total_initial_capex_yi, 1) + "亿元",
            ),
            (
                "建设期首轮更新",
                "到期电池重购－残值回收",
                "—",
                _n(capex.first_replacement_net_capex_yi, 1) + "亿元",
            ),
            (
                "CATL终局初装权益投入",
                "初装项目CAPEX×权益资本比例×CATL权益",
                f"{_n(capex.total_initial_capex_yi, 1)}×(1－{_p(config['finance']['debt_ratio'], 0)})×{_p(config['finance']['construction_ownership'], 0)}",
                _n(
                    capex.total_initial_capex_yi
                    * (1 - config["finance"]["debt_ratio"])
                    * config["finance"]["construction_ownership"],
                    1,
                ) + "亿元",
            ),
            (
                "其中2025年前已投入站网权益",
                "2025存量站初装CAPEX×权益资本比例×CATL权益",
                f"{_n(capex.preperiod_station_initial_capex_yi, 1)}×(1－{_p(config['finance']['debt_ratio'], 0)})×{_p(config['finance']['construction_ownership'], 0)}",
                _n(capex.catl_preperiod_station_equity_investment_yi, 1) + "亿元",
            ),
            (
                "CATL建设期首轮更新投入",
                "首轮更新净支出×权益资本比例×CATL权益",
                f"{_n(capex.first_replacement_net_capex_yi, 1)}×(1－{_p(config['finance']['debt_ratio'], 0)})×{_p(config['finance']['construction_ownership'], 0)}",
                _n(
                    capex.first_replacement_net_capex_yi
                    * (1 - config["finance"]["debt_ratio"])
                    * config["finance"]["construction_ownership"],
                    1,
                ) + "亿元",
            ),
            (
                "等效全周期资本底座",
                "Σ各批初装电池×派生资本倍数＋站体",
                f"初装{_n(capex.total_initial_capex_yi, 1)}×EAC {_x(eac_multiple, 2)}；"
                f"EAC＝1＋净重置比例（v3.2 §1.2.1折扣链：历次更新净支出按WACC折回初装时点）；"
                f"三类车寿命倍数：重卡5.7年{_x(capex.lifecycle_factor_by_life.get('5.7年', 0), 2)}、"
                f"乘用3.8年{_x(capex.lifecycle_factor_by_life.get('3.8年', 0), 2)}、"
                f"私家车10年{_x(capex.lifecycle_factor_by_life.get('10年', 0), 2)}",
                _n(capex.lifecycle_capital_base_yi, 1) + "亿元",
            ),
            (
                "稳态项目债务",
                "等效全周期资本底座×项目债务比例",
                f"{_n(capex.lifecycle_capital_base_yi, 1)}×{_p(config['finance']['debt_ratio'], 0)}",
                _n(capex.project_debt_yi, 1) + "亿元",
            ),
            (
                "CATL全周期权益承诺",
                "等效全周期资本底座×权益资本比例×CATL权益",
                f"{_n(capex.lifecycle_capital_base_yi, 1)}×(1－{_p(config['finance']['debt_ratio'], 0)})×{_p(config['finance']['construction_ownership'], 0)}",
                _n(capex.catl_lifecycle_equity_commitment_yi, 1) + "亿元",
            ),
            (
                "年资本要求",
                "等效全周期资本底座×CRF",
                f"{_n(capex.lifecycle_capital_base_yi, 1)}×{_p(config['finance']['capital_recovery_factor'], 1)}",
                _n(capex.annual_capital_requirement_yi, 1) + "亿元",
            ),
            (
                "CATL 2026—2030累计资本调用",
                "本期项目CAPEX×权益资本比例×CATL权益；不含2025存量",
                "—",
                _n(capex.catl_total_equity_call_yi, 1) + "亿元",
            ),
            (
                "CATL单年峰值",
                "年度资本调用最大值",
                f"{capex.peak_year}年",
                f"{_n(capex.catl_peak_equity_call_yi, 1)}亿元",
            ),
        ],
    )

    required_ebitda_table = _table(
        ["计算项目", "公式", "参数代入", "结果"],
        [
            (
                "等效全周期资本底座",
                "初装＋历次净更新折现",
                "不以结果锚校准",
                _n(capex.lifecycle_capital_base_yi, 1) + "亿元",
            ),
            (
                "资本要求FCFF",
                "资本底座×CRF",
                f"{_n(capex.lifecycle_capital_base_yi, 1)}×{_p(config['finance']['capital_recovery_factor'], 1)}",
                _n(capex.annual_capital_requirement_yi, 1) + "亿元",
            ),
            (
                "成熟期折旧",
                "各批初装×(全周期倍数－期末残值率)÷寿命＋站体÷年限",
                "—",
                _n(capex.mature_annual_depreciation_yi, 1) + "亿元",
            ),
            (
                "门槛EBITDA",
                "(FCFF－折旧×税率)÷(1－税率)",
                f"税率{_p(config['finance']['tax_rate'], 0)}",
                _n(swap.required_ebitda_yi, 1) + "亿元",
            ),
            (
                "正算覆盖",
                "正算EBITDA÷门槛EBITDA",
                f"{_n(swap.ebitda_yi, 1)}÷{_n(swap.required_ebitda_yi, 1)}",
                _x(swap.forward_to_required_ebitda),
            ),
        ],
    )
    annual_swaps_yi = (
        sum(scale.mature_daily_swaps.values())
        * config["swap_business"]["operating_days"] / 1e8
    )
    charged_energy_yi = (
        swap.annual_energy_yi_kwh
        / config["swap_business"]["rte"]
        * (1 + config["swap_business"]["auxiliary_power_rate"])
    )
    station_battery_total_gwh = (
        swap.rent_station_external_gwh
        / config["swap_business"]["swap_battery_external_sales_share"]
    )
    operating_table = _table(
        ["经营链节点", "核心参数/公式", "参数值", "结果"],
        [
            ("① 年换电次数", "(重卡日需求＋巧克力日需求)×运营天数", f"{_n(sum(scale.mature_daily_swaps.values())/1e4,1)}万次/日×{config['swap_business']['operating_days']:g}天", _n(annual_swaps_yi, 2) + "亿次"),
            ("② 年交易电量", "Σ车型换电次数×单车电量×可用比例", f"可用比例{_p(config['swap_business']['usable_energy_factor'],0)}", _n(swap.annual_energy_yi_kwh, 1) + "亿kWh"),
            ("③ 换电服务收入", "年交易电量×度电服务费", f"{_n(swap.annual_energy_yi_kwh,1)}亿kWh×{config['swap_business']['service_fee_rmb_kwh']:g}元/kWh", _n(swap.service_revenue_yi, 1) + "亿元"),
            ("④ 车端可收租电池", "终局各车型CATL换电车辆×单车带电量", "只计实际进入换电运营池的车端电池", _n(swap.rent_vehicle_gwh, 1) + "GWh"),
            ("⑤ 站内周转电池", "Σ终局站数×单站库存块数×单块电量", f"重卡/巧克力站={capex.station_targets['heavy']:,}/{capex.station_targets['choco']:,}", _n(station_battery_total_gwh, 1) + "GWh"),
            ("⑥ 站内可收租部分", "站内周转电池×外部经济权益", f"{_n(station_battery_total_gwh,1)}GWh×{_p(config['swap_business']['swap_battery_external_sales_share'],0)}", _n(swap.rent_station_external_gwh, 1) + "GWh"),
            ("⑦ 可收租电池合计", "车端＋站内外部权益部分", f"{_n(swap.rent_vehicle_gwh,1)}＋{_n(swap.rent_station_external_gwh,1)}", _n(swap.rent_eligible_gwh, 1) + "GWh"),
            ("⑧ 电池租金", "可收租电池×度电年租", f"{_n(swap.rent_eligible_gwh,1)}GWh×{config['swap_business']['battery_rent_rmb_kwh_year']:g}元/kWh年；约10元/kWh月", _n(swap.battery_rent_yi, 1) + "亿元"),
            ("⑨ 峰谷套利", "站内电池×运营天数×峰谷差×RTE", f"{_n(station_battery_total_gwh,1)}GWh×{config['swap_business']['operating_days']:g}×{config['swap_business']['grid_spread_rmb_kwh']:g}元×{_p(config['swap_business']['rte'],0)}", _n(swap.arbitrage_yi, 1) + "亿元"),
            ("⑩ 辅助服务", "VPP/辅助服务外生小项", "不作为估值溢价依据", _n(swap.ancillary_yi, 1) + "亿元"),
            ("▶ 营业收入", "③＋⑧＋⑨＋⑩", "—", _n(swap.revenue_yi, 1) + "亿元"),
            ("⑪ 充入电量", "交付电量÷RTE×(1＋厂用电率)", f"RTE={_p(config['swap_business']['rte'],0)}；厂用电={_p(config['swap_business']['auxiliary_power_rate'],0)}", _n(charged_energy_yi, 1) + "亿kWh"),
            ("⑫ 损耗电费", "(充入－交付)×谷电价", f"谷电价{config['swap_business']['valley_power_price_rmb_kwh']:g}元/kWh", _n(swap.energy_cost_yi, 1) + "亿元"),
            ("⑬ 场租", "终局站数×单站年场租", f"{sum(capex.station_targets.values()):,}座×{config['swap_business']['site_rent_wan_year']:g}万元", _n(swap.station_rent_yi, 1) + "亿元"),
            ("⑭ 人工运维", "重卡/巧克力换电次数×单次成本", f"重卡{config['swap_business']['heavy_labor_rmb_swap']:g}元；巧克力{config['swap_business']['passenger_labor_rmb_swap']:g}元", _n(swap.labor_yi, 1) + "亿元"),
            ("⑮ 软件调度", "年度固定投入", f"{config['swap_business']['software_opex_yi_year']:g}亿元/年", _n(swap.software_opex_yi, 1) + "亿元"),
            ("▶ 现金OPEX", "⑫＋⑬＋⑭＋⑮", "—", _n(swap.opex_yi, 1) + "亿元"),
            ("▶ EBITDA", "营业收入－现金OPEX", "—", _n(swap.ebitda_yi, 1) + "亿元"),
            ("⑯ 折旧", "全周期资本倍数、期末残值与寿命共同推导", "非现金费用", _n(swap.depreciation_yi, 1) + "亿元"),
            ("⑰ 债务利息", "全周期项目债务×债息", f"{_n(capex.project_debt_yi,1)}亿元×{_p(config['finance']['debt_interest_rate'])}", _n(swap.project_interest_yi, 1) + "亿元"),
            ("▶ 项目净利润", "(EBITDA－折旧－利息)×(1－税率)", f"税率{_p(config['finance']['tax_rate'],0)}", _n(swap.project_net_profit_yi, 1) + "亿元"),
            ("▶ CATL归母净利润", "项目净利润×CATL经济权益", _p(config['finance']['construction_ownership'],0), _n(swap.catl_attributable_net_profit_yi, 1) + "亿元"),
            ("▶ 项目EV", "EBITDA×EV/EBITDA", _x(config['finance']['swap_ev_ebitda'],0), _n(swap.enterprise_value_yi, 1) + "亿元"),
            ("▶ CATL运营价值", "(项目EV－项目债务)×CATL经济权益", "—", _n(swap.catl_attributable_value_yi, 1) + "亿元"),
            ("▶ 年可分派现金", "正算经营FCFF－项目债务利息", "正算口径；保守口径见3.3", _n(swap.forward_distributable_cash_yi, 1) + "亿元"),
            ("▶ CATL年可分派现金", "年可分派现金×CATL经济权益", _p(config['finance']['construction_ownership'],0), _n(swap.catl_forward_distributable_cash_yi, 1) + "亿元"),
            ("▶ 初装回收期", "CATL终局初装权益投入÷CATL年可分派现金", f"{_n(swap.catl_initial_equity_investment_yi,1)}÷{_n(swap.catl_forward_distributable_cash_yi,1)}", _n(swap.catl_initial_equity_investment_yi / swap.catl_forward_distributable_cash_yi, 2) + "年"),
            ("▶ 全投资回收期", "CATL全周期权益承诺÷CATL年可分派现金", f"{_n(capex.catl_lifecycle_equity_commitment_yi,1)}÷{_n(swap.catl_forward_distributable_cash_yi,1)}", _n(capex.catl_lifecycle_equity_commitment_yi / swap.catl_forward_distributable_cash_yi, 2) + "年"),
        ],
    )
    cash_return_table = _table(
        ["现金回报节点", "公式", "结果", "投资含义"],
        [
            ("资本要求FCFF", "全周期资本底座×CRF", _n(swap.required_fcff_yi,1)+"亿元", "含更新资本后的最低年资本回报要求"),
            ("最低项目可分派现金", "资本要求FCFF－项目债务利息", _n(swap.minimum_distributable_cash_yi,1)+"亿元", "与v3.2回收期同口径；项目债续作、未另扣本金摊还"),
            ("CATL最低年可分派现金", "最低项目可分派现金×40%经济权益", _n(swap.catl_minimum_distributable_cash_yi,1)+"亿元", "保守回收期采用这一口径"),
            ("正算经营FCFF", "可交付EBITDA×(1－税率)＋折旧税盾", _n(swap.forward_fcff_yi,1)+"亿元", "按中性经营能力形成的上行现金口径"),
            ("正算项目可分派现金", "正算经营FCFF－项目债务利息", _n(swap.forward_distributable_cash_yi,1)+"亿元", "不把会计净利润误当现金"),
            ("CATL正算年可分派现金", "正算项目可分派现金×40%经济权益", _n(swap.catl_forward_distributable_cash_yi,1)+"亿元", "中性经营能力下可落到CATL的现金"),
            ("CATL终局初装权益投入", "终局初装CAPEX×40%股权资本×40%CATL权益", _n(swap.catl_initial_equity_investment_yi,1)+"亿元", "含2025已投入站网；不倒改历史"),
            ("保守初装现金收益率", "CATL最低年可分派现金÷CATL终局初装权益投入", _p(swap.catl_cash_yield_on_initial_equity), "不使用正算经营上行来缩短回收期"),
            ("保守初装回收期", "CATL终局初装权益投入÷最低年可分派现金", _n(swap.catl_initial_payback_years,2)+"年", "未计爬坡，按稳态最低年现金"),
            ("保守全周期权益回收期", "CATL全周期权益承诺÷最低年可分派现金", _n(swap.catl_lifecycle_payback_years,2)+"年", "把后续更新义务纳入分子"),
        ],
    )

    manufacturing_table = _table(
        ["制造情景", "装机", "收入", "净利率", "归母净利润", "PE", "估值"],
        [
            (
                ledger.no_swap_manufacturing.label,
                _n(ledger.no_swap_manufacturing.shipments_gwh, 1) + "GWh",
                _n(ledger.no_swap_manufacturing.revenue_yi, 1),
                _p(ledger.no_swap_manufacturing.net_margin),
                _n(ledger.no_swap_manufacturing.net_profit_yi, 1),
                _x(config["finance"]["manufacturing_pe"], 0),
                _n(ledger.no_swap_manufacturing.equity_value_yi, 1),
            ),
            (
                ledger.with_swap_manufacturing.label,
                _n(ledger.with_swap_manufacturing.shipments_gwh, 1) + "GWh",
                _n(ledger.with_swap_manufacturing.revenue_yi, 1),
                _p(ledger.with_swap_manufacturing.net_margin),
                _n(ledger.with_swap_manufacturing.net_profit_yi, 1),
                _x(config["finance"]["manufacturing_pe"], 0),
                _n(ledger.with_swap_manufacturing.equity_value_yi, 1),
            ),
        ],
    )

    # 4.1与1.1装机口径勾稽：底座口径含CATL全部换电车辆电池（含40%内部权益），
    # 制造出货口径只确认外部权益60%部分加更换循环，两表差异由此而来。
    target_year_scale = scale.years[-1]
    swap_fleet_gwh = scale.annual_catl_swap_gwh[target_year_scale]
    charge_fleet_gwh = scale.annual_catl_charge_gwh[target_year_scale]
    replacement_gwh_2030 = next(
        row.vehicle_replacement_gwh
        for row in capex.annual
        if row.year == target_year_scale
    )
    external_share = config["swap_business"]["swap_battery_external_sales_share"]
    operating_calibration_table = _table(
        ["口径", "2030E装机", "构成与差异原因"],
        [
            (
                "车辆底座装机（1.1表）",
                _n(swap_fleet_gwh + charge_fleet_gwh, 1) + "GWh",
                f"换电段{_n(swap_fleet_gwh, 1)}＋充电段{_n(charge_fleet_gwh, 1)}；"
                "CATL全部换电车辆的电池装机，含40%内部权益部分",
            ),
            (
                "制造确认出货（4.1表）",
                _n(ledger.with_swap_manufacturing.shipments_gwh, 1) + "GWh",
                f"(换电段{_n(swap_fleet_gwh, 1)}＋更换循环{_n(replacement_gwh_2030, 1)})×"
                f"外部权益{_p(external_share, 0)}＋充电段{_n(charge_fleet_gwh, 1)}；"
                "内部权益40%的电池留作运营资产不出售，不确认制造收入",
            ),
        ],
    )
    power_total_table = _table(
        ["观察口径", "制造净利润", "运营归母净利润", "动力电池归母净利润", "制造价值", "运营价值", "动力电池价值"],
        [
            (
                "2026E动力分部市值分摊基准",
                _n(baseline.power_net_profit_2026e_yi, 1), "—", _n(baseline.power_net_profit_2026e_yi, 1),
                _n(baseline.power_market_value_2026e_yi, 1), "—", _n(baseline.power_market_value_2026e_yi, 1),
            ),
            (
                "2030E无换电纯制造",
                _n(ledger.no_swap_manufacturing.net_profit_yi, 1), "0",
                _n(ledger.power_net_profit_2030_no_swap_yi, 1),
                _n(ledger.no_swap_manufacturing.equity_value_yi, 1), "0",
                _n(ledger.power_value_2030_no_swap_yi, 1),
            ),
            (
                "2030E重资产换电",
                _n(ledger.with_swap_manufacturing.net_profit_yi, 1),
                _n(swap.catl_attributable_net_profit_yi, 1),
                _n(ledger.power_net_profit_2030_with_swap_yi, 1),
                _n(ledger.with_swap_manufacturing.equity_value_yi, 1),
                _n(swap.catl_attributable_value_yi, 1),
                _n(ledger.power_value_2030_with_swap_yi, 1),
            ),
        ],
    )
    bridge_table = _table(
        ["增量桥", "利润增量", "价值增量", "是否计入可归因换电价值", "计算含义"],
        [
            (
                "制造销量/市占率差（合计）",
                _n(ledger.manufacturing_volume_share_effect_net_profit_yi, 1),
                _n(ledger.manufacturing_volume_share_effect_value_yi, 1),
                "拆分为以下两行",
                "(有换电收入－纯制造收入)×纯制造净利率",
            ),
            (
                "①换电段+更换循环锁定订单",
                _n(ledger.manufacturing_swap_locked_volume_effect_net_profit_yi, 1),
                _n(ledger.manufacturing_swap_locked_volume_effect_value_yi, 1),
                "是",
                "(换电段装机+更换循环装机)×外部权益60%×电池价格×纯制造净利率；这部分订单由换电体系锁定，计入换电功劳",
            ),
            (
                "②充电段份额净效应",
                _n(ledger.manufacturing_charge_share_effect_net_profit_yi, 1),
                _n(ledger.manufacturing_charge_share_effect_value_yi, 1),
                "否",
                "量差剩余部分＝充电段装机－无换电总装机；依赖“换电数据反哺充电市占率”长链条，证据最弱，只进敏感性",
            ),
            (
                "电动车制造盘利润率保护",
                _n(ledger.manufacturing_swap_margin_effect_net_profit_yi, 1),
                _n(ledger.manufacturing_swap_margin_effect_value_yi, 1),
                "是",
                "有换电制造收入×净利率差3.0pct；本次仅含已建模电动车",
            ),
            (
                "制造线情景差额合计",
                _n(ledger.full_manufacturing_scenario_gap_net_profit_yi, 1),
                _n(ledger.full_manufacturing_scenario_gap_value_yi, 1),
                "部分",
                "制造销量/市占率差＋利润率保护",
            ),
            (
                "换电直接运营",
                _n(ledger.direct_swap_increment_net_profit_yi, 1),
                _n(ledger.direct_swap_increment_value_yi, 1),
                "是",
                "项目归母净利润与归母权益价值",
            ),
            (
                "可归因换电价值合计",
                _n(ledger.total_swap_increment_net_profit_yi, 1),
                _n(ledger.total_swap_increment_value_yi, 1),
                "是",
                "①锁定订单＋利润率保护＋直接运营（运营主体价值、锁定订单的量、护价的价）",
            ),
            (
                "完整有换电－纯制造差额",
                _n(ledger.full_with_vs_pure_manufacturing_gap_net_profit_yi, 1),
                _n(ledger.full_with_vs_pure_manufacturing_gap_value_yi, 1),
                "情景上限",
                "制造线全部差额＋直接运营＝可归因价值＋充电段份额净效应",
            ),
        ],
    )
    # 4.4按“业绩是锚、市值是换算”拆成三张小表：先看业务与业绩，
    # 再看与2026基准的量级比较，最后才做市值换算。
    performance_anchor_table = _table(
        ["业绩锚（根本）", "计算", "结果"],
        [
            (
                "2030E换电运营归母净利润",
                "项目净利润×CATL经济权益",
                _n(swap.catl_attributable_net_profit_yi, 1) + "亿元",
            ),
            (
                "可归因换电价值（合计）",
                "锁定订单＋利润率保护＋直接运营",
                _n(ledger.total_swap_increment_value_yi, 1) + "亿元",
            ),
            (
                "——其中：直接运营价值",
                "项目归母权益价值",
                _n(ledger.direct_swap_increment_value_yi, 1) + "亿元",
            ),
            (
                "——其中：换电段锁定订单价值",
                "(换电段+更换循环装机)×外部权益×电池价格×纯制造净利率×PE",
                _n(ledger.manufacturing_swap_locked_volume_effect_value_yi, 1) + "亿元",
            ),
            (
                "——其中：制造利润率保护价值",
                "有换电制造收入×净利率差3pct×PE",
                _n(ledger.manufacturing_swap_margin_effect_value_yi, 1) + "亿元",
            ),
            (
                "稳态初装现金收益率",
                "CATL最低年可分派现金÷终局初装权益投入",
                _p(swap.catl_cash_yield_on_initial_equity),
            ),
        ],
    )
    baseline_comparison_table = _table(
        ["与2026基准比较", "计算", "结果"],
        [
            (
                "2030动力价值较2026分部市值分摊增加",
                "2030有换电动力价值－2026动力分部市值分摊",
                _n(ledger.power_value_growth_vs_2026_allocated_yi, 1) + "亿元",
            ),
            (
                "2030动力价值/2026动力分部市值分摊",
                "2030有换电动力价值÷2026动力分部市值分摊",
                _x(ledger.power_value_multiple_vs_2026_allocated),
            ),
            (
                "可归因换电价值/2026动力分部市值分摊",
                "可归因换电价值÷当前动力业务市值贡献",
                _p(ledger.attributable_swap_value_to_2026_allocated_power_value),
            ),
        ],
    )
    market_value_table = _table(
        ["市值换算（换算层）", "计算", "结果"],
        [
            (
                "可归因换电价值/当前宁德时代市值",
                "可归因换电价值÷当前A+H市值",
                _p(ledger.attributable_swap_value_to_current_group_market_cap),
            ),
            (
                "完整情景差额/当前宁德时代市值",
                "完整有换电－纯制造差额÷当前A+H市值",
                _p(ledger.full_gap_to_current_group_market_cap),
            ),
            (
                "换电价值/2030前CATL现金调用",
                "可归因换电价值÷建设期实际权益现金",
                _x(ledger.total_swap_increment_value_yi / capex.catl_total_equity_call_yi),
            ),
            (
                "换电价值/CATL全周期权益承诺",
                "可归因换电价值÷全周期权益资本承诺",
                _x(ledger.total_swap_increment_value_yi / capex.catl_lifecycle_equity_commitment_yi),
            ),
            (
                "稳态归母净利润/全周期权益承诺",
                "换电运营归母净利润÷全周期权益资本承诺",
                _p(swap.catl_attributable_net_profit_yi / capex.catl_lifecycle_equity_commitment_yi),
            ),
        ],
    )

    valuation_method_table = _table(
        ["价值层", "估值公式", "参数解释"],
        [
            ("制造线", "归母净利润×制造PE", f"中性{_x(config['finance']['manufacturing_pe'], 0)}"),
            (
                "重资产运营线",
                "(EBITDA×EV/EBITDA－项目债务)×CATL权益",
                f"中性{_x(config['finance']['swap_ev_ebitda'], 0)}；沿用v3 §4.1的含战略溢价基建运营口径",
            ),
        ],
    )
    valuation_comparable_table = _table(
        ["商业模式族", "代表与倍数", "与CATL换电的关系", "本报告处理"],
        [
            (
                "重资产基建/能源运营",
                "Brookfield Infrastructure约6.7×；公用事业/储能平台约8—14×",
                "资产持有者靠运营现金流和分派回报",
                "构成基础区间",
            ),
            (
                "资管/科技平台",
                "Blackstone约21.8×；行业中位约18×；Ares约38.8×",
                "真GP以少量资本管理第三方AUM并收管理费/carry；CATL当前并不同构",
                "不直接用作重资产运营倍数锚",
            ),
            (
                "车+能源网络复合",
                "Tesla倍数显著更高",
                "只提供能源网络入口的叙事参照",
                "不用于数值估值",
            ),
            (
                "本报告中枢",
                f"{_x(config['finance']['swap_ev_ebitda'],0)} EV/EBITDA",
                "6.7—14×基建区间＋电池供应、换电标准和数据闭环战略溢价",
                "18×已经含溢价，不再叠加资管溢价",
            ),
        ],
    )
    light_transaction_table = _table(
        ["终局权益", "毛回款", "净回款", "制造价值", "保留运营价值", "持续动力价值"],
        [
            (
                _p(row.terminal_ownership, 0),
                _n(row.sale_proceeds_gross_yi, 1),
                _n(row.sale_proceeds_net_yi, 1),
                _n(
                    row.post_exit_power_value_ex_cash_yi
                    - row.retained_operating_value_yi,
                    1,
                ),
                _n(row.retained_operating_value_yi, 1),
                _n(row.post_exit_power_value_ex_cash_yi, 1),
            )
            for row in snapshot.light_asset
        ],
    )
    light_decision_table = _table(
        ["终局权益", "持续价值保留率", "经常利润保留率", "持续动力价值变化", "含净回款后变化", "回款/持续价值损失", "决策位置"],
        [
            (
                _p(row.terminal_ownership, 0),
                _p(row.sustainable_value_retention),
                _p(row.recurring_profit_retention),
                _n(row.persistent_power_value_delta_yi, 1),
                _n(row.including_cash_power_value_delta_yi, 1),
                "—" if row.cash_per_persistent_value_lost is None else _x(row.cash_per_persistent_value_lost),
                row.decision_role,
            )
            for row in snapshot.light_asset
        ],
    )
    light_conclusion = (
        f"当前资金表没有触发流动性缺口，因此中性终局仍是保留"
        f" **{_p(current_light.terminal_ownership, 0)}**、暂不出表。成熟后不指定30%或20%为固定最优："
        f"保留30%/20%/10%分别可净回款约"
        f" **{_n(light_by_ownership[0.30].sale_proceeds_net_yi,1)} /"
        f" {_n(light_by_ownership[0.20].sale_proceeds_net_yi,1)} /"
        f" {_n(light_by_ownership[0.10].sale_proceeds_net_yi,1)}亿元**。"
        "资金需求大、市场承接好就多卖；资金需求小或发行环境弱就少卖。真正的决策变量是届时资金缺口、"
        "替代项目回报和市场承接能力，不是一年净现金流量级的档位差本身。"
    )

    history = config["historical_cash_conversion"]
    historical_cfo_rows = [
        (
            year,
            _n(np, 1),
            _n(cfo, 1),
            _x(cfo / np),
            "年报合并口径",
        )
        for year, np, cfo in zip(
            history["years"], history["net_profit_yi"], history["cfo_yi"]
        )
    ]
    historical_cfo_rows.append((
        "2026H1",
        _n(config["financial_2026h1"]["group_net_profit_yi"], 1),
        _n(config["financial_2026h1"]["group_cfo_yi"], 1),
        _x(
            config["financial_2026h1"]["group_cfo_yi"]
            / config["financial_2026h1"]["group_net_profit_yi"]
        ),
        "中报合并口径",
    ))
    historical_cfo_table = _table(
        ["期间", "归母净利润", "经营活动现金流净额", "CFO/归母净利润", "来源口径"],
        historical_cfo_rows,
    )
    funding_table = _table(
        [
            "年份", "期初现金类资产", "预测归母净利润", "本期原始CFO", "分红储备",
            "回购储备", "已识别投资/并购现金", "换电资本", "当年新增可投资资金",
            "其他战略动作前期末现金类资产", "流动性底线", "预留给其他战略项目的资金储备",
        ],
        [
            (
                row.year,
                _n(row.opening_liquid_resources_yi, 1),
                _n(row.projected_net_profit_yi, 1),
                _n(row.period_cfo_yi, 1),
                _n(row.dividend_reserve_yi, 1),
                _n(row.buyback_reserve_yi, 1),
                _n(row.known_direct_mna_cash_yi, 1),
                _n(row.swap_equity_call_yi, 1),
                _n(row.annual_investable_funds_generated_yi, 1),
                _n(row.closing_liquid_resources_before_uncommitted_strategy_yi, 1),
                _n(row.minimum_liquidity_reserve_yi, 1),
                _n(row.funds_reserved_for_other_strategy_yi, 1),
            )
            for row in snapshot.funding
        ],
    )
    commitment_table = _table(
        ["事项", "披露/交易总额", "计入资金表现金", "口径", "时点", "处理", "来源"],
        [
            (
                item["label"],
                _n(item["headline_amount_yi"], 1),
                _n(item["cash_in_model_yi"], 1),
                item["perimeter"],
                item["timing"],
                item["note"],
                f"[披露文件]({item['source_url']})",
            )
            for item in snapshot.capital_commitments
        ],
    )
    mna_2026_total = next(
        row.known_direct_mna_cash_yi
        for row in snapshot.funding
        if row.year == 2026
    )
    commitment_2026_note = (
        f"2026年已识别并购共三项合并计算：中恒电气现金{_n(29.03495, 2)}亿＋世纪互联{_n(64.0, 1)}亿"
        f"＋启源芯动力摘牌价{_n(25.5566, 2)}亿，合计{_n(mna_2026_total, 1)}亿元，"
        "全部计入2026年资金表现金。v4.1只计中恒与启源两项（54.6亿），v4.2把世纪互联按审慎口径补入。"
    )
    solid_state = config["strategic_exposure"]["solid_state"]
    solid_high_end_share = 0.15
    solid_capacity_ratio = 1.3
    solid_capex_per_gwh_yi = 7.0
    solid_upper_share = 0.20
    solid_upper_capex_per_gwh_yi = 8.0
    solid_demand_gwh = (
        ledger.with_swap_manufacturing.shipments_gwh * solid_high_end_share
    )
    solid_capacity_gwh = solid_demand_gwh * solid_capacity_ratio
    solid_neutral_capex_yi = solid_capacity_gwh * solid_capex_per_gwh_yi
    solid_upper_capex_yi = (
        ledger.with_swap_manufacturing.shipments_gwh
        * solid_upper_share
        * solid_capacity_ratio
        * solid_upper_capex_per_gwh_yi
    )
    global_high_end_gwh = 560.0
    solid_state_derivation_table = _table(
        ["推导步骤", "逻辑", "参数代入", "结果"],
        [
            (
                "① CATL 2030E动力装机",
                "模型主链产出（Part 4.1有换电制造情景）",
                "—",
                _n(ledger.with_swap_manufacturing.shipments_gwh, 1) + "GWh",
            ),
            (
                "② 高端场景适配需求",
                "全固态从高端乘用车、低空与高性能场景切入（外生假设：高端适配比例15%）",
                f"{_n(ledger.with_swap_manufacturing.shipments_gwh, 1)}×{_p(solid_high_end_share, 0)}",
                _n(solid_demand_gwh, 1) + "GWh",
            ),
            (
                "③ 固态产能规划",
                "产能/出货冗余（外生假设：1.3，为良率爬坡与设备代际迭代预留）",
                f"{_n(solid_demand_gwh, 1)}×{solid_capacity_ratio:g}",
                _n(solid_capacity_gwh, 1) + "GWh",
            ),
            (
                "④ 新建等价投资（中性）",
                "单位投资强度（外生假设：约7亿元/GWh；固态整线电解质膜、等静压、无隔膜叠片全部新增，远高于液态线约2亿元/GWh）",
                f"{_n(solid_capacity_gwh, 1)}×{solid_capex_per_gwh_yi:g}亿",
                _n(solid_neutral_capex_yi, 1) + "亿元",
            ),
            (
                "⑤ 上限口径",
                "适配比例20%＋单位强度8亿元/GWh（外生假设）",
                f"{_n(ledger.with_swap_manufacturing.shipments_gwh, 1)}×{_p(solid_upper_share, 0)}×{solid_capacity_ratio:g}×{solid_upper_capex_per_gwh_yi:g}亿",
                _n(solid_upper_capex_yi, 1) + "亿元",
            ),
            (
                "⑥ 市占率交叉验证",
                "CATL固态产能÷2030全球高端电池需求（外生假设：全球动力装机约2,800GWh×高端约20%≈560GWh）",
                f"{_n(solid_capacity_gwh, 1)}÷{global_high_end_gwh:g}",
                _p(solid_capacity_gwh / global_high_end_gwh)
                + "，低于CATL当前全球动力份额，压力刻度不冒进",
            ),
            (
                "⑦ 实际新增口径",
                "新建等价×(1－液态线复用率25%)",
                f"{_n(solid_neutral_capex_yi, 1)}×(1－{_p(solid_state['assumed_reuse_rate'], 0)})",
                _n(solid_neutral_capex_yi * (1 - solid_state["assumed_reuse_rate"]), 1) + "亿元",
            ),
        ],
    )
    solid_state_note = (
        "固态、储能/AIDC的容量估算只作压力刻度，不进入价值总账：推导链的作用是让"
        f"{_n(solid_state['full_newbuild_capex_yi'], 0)}亿元中性投资额可追溯、可质疑，"
        "而不是冒充公司预算。真正的判断标准是届时高端车型的固态适配订单是否兑现。"
    )
    exposure_table = _table(
        ["未决战略方向", "若全部新建所需投入", "假设产线/资产复用率", "仍需新增资金", "性质"],
        [
            (
                item["label"],
                _n(item["full_newbuild_capex_yi"], 1),
                _p(item["assumed_reuse_rate"], 0),
                _n(
                    item["full_newbuild_capex_yi"]
                    * (1 - item["assumed_reuse_rate"]),
                    1,
                ),
                "研究情景，不是公司预算",
            )
            for item in config["strategic_exposure"].values()
        ]
        + [("合计", "—", "—", _n(snapshot.strategic_exposure_yi, 1), "仅作压力刻度")],
    )
    light_support_table = _table(
        ["终局权益", "成熟后净回款", "未来更新资本释放", "可覆盖未决战略敞口情景", "解释"],
        [
            (
                _p(row.terminal_ownership, 0),
                _n(row.sale_proceeds_net_yi, 1),
                _n(row.future_catl_capital_released_yi, 1),
                _p(row.sale_proceeds_net_yi / snapshot.strategic_exposure_yi),
                row.decision_role,
            )
            for row in snapshot.light_asset
        ],
    )
    reits = config["reits_reference"]
    qiyuan = config["qiyuan_reference"]
    exit_30 = light_by_ownership[0.30]
    exit_30_net_yi = exit_30.sale_proceeds_net_yi
    exit_20_net_yi = light_by_ownership[0.20].sale_proceeds_net_yi
    exit_10_net_yi = light_by_ownership[0.10].sale_proceeds_net_yi
    exit_multiple = exit_30_net_yi / capex.catl_total_equity_call_yi
    reits_capacity_theoretical_yi = (
        swap.catl_minimum_distributable_cash_yi / reits["nio_battery_reits_yield"]
    )
    abs_capacity_low, abs_capacity_high = config["light_asset"]["current_abs_reits_capacity_range_yi"]
    exit_years_at_market_capacity = (
        exit_30_net_yi / ((abs_capacity_low + abs_capacity_high) / 2)
    )
    spread_crf_vs_reits = (
        config["finance"]["capital_recovery_factor"]
        - reits["nio_battery_reits_yield"]
    )
    buyback_yield = (
        config["group_funding"]["projected_group_net_profit_yi"][0]
        / config["financial_2026e"]["group_market_cap_ah_yi"]
    )
    reits_case_table = _table(
        ["类固收市场证据", "规模/条款", "对CATL的含义"],
        [
            (
                "蔚能电池持有型REITs（全球首单）",
                f"{reits['nio_battery_reits_issue_month']}发行；{_n(reits['nio_battery_reits_issue_yi'], 2)}亿元；{_p(reits['nio_battery_reits_yield'], 2)}；{reits['nio_battery_reits_tenor_years']:g}年期",
                "换电电池资产可以按租赁现金流向类固收市场证券化——退出路径已被蔚来跑通",
            ),
            (
                "蔚能储架ABS",
                f"{reits['nio_battery_abs_shelf_month']}；储架{_n(reits['nio_battery_abs_shelf_size_yi'], 0)}亿元；A1档利率{_p(reits['nio_battery_abs_shelf_a1_rate'], 2)}",
                "AAA档资金成本远低于项目资本要求，发起人存在结构化套利空间",
            ),
            (
                "启源芯动力资产侧",
                f"100%股权评估{_n(qiyuan['equity_appraisal_yi'], 2)}亿元；2025年净利{_n(qiyuan['net_profit_2025_yi'], 2)}亿元",
                "收购后CATL直接获得成熟的营运车换电资产池与发行人身份，REITs循环可加速",
            ),
        ],
    )
    reits_recycle_table = _table(
        ["计算项目", "公式", "参数代入", "结果"],
        [
            (
                "稳态CATL最低年可分派现金",
                "项目最低可分派现金×40%经济权益",
                "保守口径（CRF门槛链），非正算上行",
                _n(swap.catl_minimum_distributable_cash_yi, 1) + "亿元",
            ),
            (
                "按REITs收益率折算的理论发行容量",
                "年可分派现金÷REITs收益率",
                f"{_n(swap.catl_minimum_distributable_cash_yi, 1)}÷{_p(reits['nio_battery_reits_yield'], 2)}",
                _n(reits_capacity_theoretical_yi, 1) + "亿元（受市场承接量约束）",
            ),
            (
                "最保守出表净回款（保留30%）",
                "费后权益价值×(40%－30%)×(1－交易成本)",
                "卖得最少的一档；卖20%/10%分别为"
                f"{_n(exit_20_net_yi, 1)}/{_n(exit_10_net_yi, 1)}亿元",
                _n(exit_30_net_yi, 1) + "亿元",
            ),
            (
                "最保守出表回报倍数",
                "出表净回款÷建设期累计资本调用",
                f"{_n(exit_30_net_yi, 1)}÷{_n(capex.catl_total_equity_call_yi, 1)}",
                _x(exit_multiple) + "（且保留70%权益仍在持续分派）",
            ),
            (
                "发起人套利利差",
                "项目CRF－REITs收益率",
                f"{_p(config['finance']['capital_recovery_factor'], 1)}－{_p(reits['nio_battery_reits_yield'], 2)}",
                f"{_p(spread_crf_vs_reits, 1)}：资产按{_p(config['finance']['capital_recovery_factor'], 1)}要求内生回报，按{_p(reits['nio_battery_reits_yield'], 2)}的类固收成本发行，利差留在发起人",
            ),
        ],
    )
    abs_capacity_text = f"{abs_capacity_low:g}—{abs_capacity_high:g}"
    reits_recycle_note = (
        f"REITs回笼是财务回报的大头，不只是净利润：蔚能首单REITs（{_p(reits['nio_battery_reits_yield'], 2)}、"
        f"{reits['nio_battery_reits_tenor_years']:g}年期）已经证明电池资产可按租赁现金流向类固收市场发行；"
        f"CATL收购启源后获得成熟资产池，这一循环可以加速。看似要投{_n(capex.catl_total_equity_call_yi, 1)}亿元，"
        "但成熟一批发一批、回笼资金滚投下一批的轮动模式下，峰值资金占用远低于累计口径——"
        f"市场年承接量{abs_capacity_text}亿元本身决定了节奏："
        f"出表10个百分点约需{exit_years_at_market_capacity:.1f}年完成。"
        "从本质上看，换电的业务属性有二：其一，稳住动力电池基本盘（锁定订单＋护价＋直接运营，"
        f"可归因价值{_n(ledger.total_swap_increment_value_yi, 1)}亿元）；其二，做成一门金融类的权益投资生意——"
        "面向类固收市场提供比蔚来私家车换电更高质量的营运车换电投资机会（重卡/出租网约高频使用、"
        "现金流密度远高于私家车），CATL作为发起人赚取项目内生回报与发行利率之间的套利。"
    )
    sensitivity_table = _table(
        [
            "参数组", "情景", "重卡/巧克力站", "2030前CATL资本调用",
            "门槛EBITDA", "可交付EBITDA", "覆盖倍数", "制造归母净利润", "可归因换电价值",
            "动力电池价值", "较中性变化",
        ],
        [
            (
                row["parameter_group"],
                row["scenario"],
                f"{row['heavy_stations']:,}/{row['choco_stations']:,}",
                _n(row["catl_construction_cash_call_yi"], 1),
                _n(row["required_ebitda_yi"], 1),
                _n(row["deliverable_ebitda_yi"], 1),
                _x(row["ebitda_coverage"]),
                _n(row["manufacturing_net_profit_yi"], 1),
                _n(row["attributable_swap_value_yi"], 1),
                _n(row["power_value_2030_yi"], 1),
                _n(row["power_value_delta_yi"], 1),
            )
            for row in snapshot.sensitivity
        ],
    )

    # 7.1表后解读：程序按各参数组对动力电池价值的极差自动排序，
    # 给出生死线、弹性排序与结论句。
    sensitivity_interpretation = _build_sensitivity_interpretation(snapshot)

    # 7.2 私家车三情景：未显式传入时，退化为当前快照所属情景（保证单情景调用仍可渲染）。
    if private_snapshots is None:
        private_snapshots = {snapshot.meta.get("private_scenario", "中枢"): snapshot}
    (
        private_penetration_table,
        private_scenario_table,
        private_scenario_note,
    ) = _private_scenario_tables(config, private_snapshots)

    # 2.2.1 电池寿命由使用强度反推（大车短、小车长）
    battery_life_table, battery_life_note = _battery_life_sections(config, snapshot)
    # 附录A.2 新旧寿命口径完整重跑对比
    life_mode_comparison_table, life_mode_comparison_note = _life_mode_comparison(
        config, snapshot, legacy_snapshot
    )

    nio = config["nio_reference"]
    nio_ev_reference = (
        nio["battery_bank_reference_equity_value_yi"]
        + nio["battery_bank_total_liabilities_yi"]
    )
    network_replacement_value = (
        nio["network_stations"]
        * nio["network_replacement_cost_wan_per_station"]
        / 1e4
    )
    qiyuan = config["qiyuan_reference"]
    qiyuan_asset_table = _table(
        ["启源芯动力资产锚（2026-08摘牌交易）", "数值", "推导/含义"],
        [
            (
                "100%股权评估值",
                _n(qiyuan["equity_appraisal_yi"], 2) + "亿元",
                "DCF收益法评估；CATL按25%股权对应摘牌价25.56亿元入股",
            ),
            (
                "账面权益",
                _n(qiyuan["book_equity_yi"], 2) + "亿元",
                "评估溢价主要来自营运车换电资产的未来现金流，不是重置成本",
            ),
            (
                "2025年净利润",
                _n(qiyuan["net_profit_2025_yi"], 2) + "亿元",
                "已盈利的营运车换电运营商；资产侧证明该生意可以赚钱",
            ),
            (
                "2025年营收",
                _n(qiyuan["revenue_2025_yi"], 2) + "亿元",
                "—",
            ),
            (
                "隐含估值倍数",
                f"PE {_x(qiyuan['implied_pe'], 1)}；PB {_x(qiyuan['implied_pb'], 2)}；PS {_x(qiyuan['implied_ps'], 2)}",
                "与Part 6.1运营18×EV/EBITDA口径互为印证：成熟换电运营资产按现金流定价，不按制造PE定价",
            ),
            (
                "资产负债率",
                _p(qiyuan["liability_ratio"], 1),
                "高杠杆是重资产运营常态；项目债务由换电现金流自偿",
            ),
        ],
    )
    qiyuan_asset_note = (
        "启源的资产侧价值不在收购价差，而在两件事：其一，它是营运车换电已跑通的盈利样本"
        f"（2025年净利{_n(qiyuan['net_profit_2025_yi'], 2)}亿），其二，它把CATL带入类固收发行人的位置——"
        "启源旗下站网与电池资产成熟后同样可以进入REITs/ABS循环。"
    )
    nio_fact_table = _table(
        ["资产", "规模/财务锚", "估值或交易含义"],
        [
            (
                "蔚来换电网络",
                f"{_n(nio['network_stations'])}座；累计{_n(nio['cumulative_swaps_yi'], 1)}亿次；{_n(nio['cumulative_energy_yi_kwh'], 1)}亿kWh",
                f"按{_n(nio['network_replacement_cost_wan_per_station'], 0)}万元/站重置成本约{_n(network_replacement_value, 1)}亿元；只作交易锚",
            ),
            (
                "蔚能电池银行",
                f"{_n(nio['battery_bank_operating_gwh'], 1)}GWh+、{_n(nio['battery_bank_users_wan'], 0)}万+用户",
                f"参考权益价值{_n(nio['battery_bank_reference_equity_value_yi'], 0)}亿元以上；加负债后的资本承载约{_n(nio_ev_reference, 1)}亿元",
            ),
            (
                "ABS评估样本",
                f"{_n(nio['abs_sample_battery_count'])}块、{_n(nio['abs_sample_capacity_gwh'], 3)}GWh、出租率{_p(nio['abs_sample_occupancy'], 0)}",
                f"账面{_n(nio['abs_sample_book_value_yi'], 3)}亿元、评估{_n(nio['abs_sample_appraised_value_yi'], 2)}亿元；75/100—102kWh月租{_n(nio['abs_rent_75kwh_rmb_month'], 0)}/{_n(nio['abs_rent_100_102kwh_rmb_month'], 0)}元",
            ),
        ],
    )
    mna_input_table = _table(
        [
            "方案", "买入资产", "交易现金", "纯自建CATL资本调用",
            "收购后剩余自建调用", "节省自建现金", "CATL总现金需求",
            "较纯自建现金增量", "布局提前", "价格依据",
        ],
        [
            (
                row["label"],
                f"站网{_n(row['acquired_network_stations'])}座 / 电池银行{_n(row['acquired_battery_bank_gwh'], 1)}GWh",
                _n(row["cash_consideration_yi"], 1),
                _n(row["pure_selfbuild_catl_equity_call_yi"], 1),
                _n(row["remaining_selfbuild_catl_equity_call_yi"], 1),
                _n(row["selfbuild_cash_saved_yi"], 1),
                _n(row["total_catl_cash_requirement_yi"], 1),
                _n(row["incremental_catl_cash_vs_pure_selfbuild_yi"], 1),
                _n(row["network_acceleration_years"], 2) + "年",
                row["price_basis"],
            )
            for row in snapshot.mna_comparison
        ],
    )
    mna_bridge_table = _table(
        ["方案", "收购资产参考价值", "换电运营协同增量", "制造协同增量", "可归因换电增量", "动力线协同增量", "动力线毛增量含买入资产", "扣现金后股东价值创造"],
        [
            (
                row["label"],
                _n(row["acquired_asset_value_reference_yi"], 1),
                _n(row["incremental_swap_operating_value_vs_base_yi"], 1),
                _n(row["incremental_manufacturing_value_vs_base_yi"], 1),
                _n(row["incremental_attributable_swap_value_vs_base_yi"], 1),
                _n(row["incremental_power_value_vs_base_yi"], 1),
                _n(row["gross_power_value_addition_yi"], 1),
                _n(row["net_shareholder_value_creation_after_cash_yi"], 1),
            )
            for row in snapshot.mna_comparison
        ],
    )

    # Part8直陈式结论：六段结构（结论/价值贡献/资源投入/业绩影响/关键项/风险提示），
    # 全部由模型数字生成，不再使用模块负责人表与两次拍板会议纪要体例。
    target_year = config["meta"]["target_year"]
    completion_year = config["construction"]["station_network_completion_year"]
    final_conclusion = "\n\n".join([
        f"### 结论：{final_memo.status}",
        f"按中性假设，宁德时代应当对换电下重注：建设期维持"
        f"{_p(config['finance']['construction_ownership'], 0)}经济权益，"
        f"把需求反推的站网在{completion_year}年以前建完，{target_year}年前把车辆、"
        "盈利和数据飞轮跑通。这不是一次把所有战术写死的决定——成熟后卖多少权益，"
        "留给届时按资金缺口与市场承接能力再拍。",
        f"### 价值贡献：可归因换电价值{_n(ledger.total_swap_increment_value_yi, 1)}亿元",
        f"其中直接运营价值{_n(ledger.direct_swap_increment_value_yi, 1)}亿元、"
        f"换电段锁定订单价值{_n(ledger.manufacturing_swap_locked_volume_effect_value_yi, 1)}亿元、"
        f"制造利润率保护价值{_n(ledger.manufacturing_swap_margin_effect_value_yi, 1)}亿元，"
        f"相当于当前A+H市值的{_p(ledger.attributable_swap_value_to_current_group_market_cap)}、"
        f"当前动力分部市值分摊的{_p(ledger.attributable_swap_value_to_2026_allocated_power_value)}。"
        "换电的业务属性有二：稳住动力电池基本盘，以及做成面向类固收市场的金融类权益投资生意。",
        f"### 资源投入：建设期累计资本调用{_n(capex.catl_total_equity_call_yi, 1)}亿元",
        f"单年峰值{_n(capex.catl_peak_equity_call_yi, 1)}亿元（{capex.peak_year}年），"
        f"全周期权益承诺{_n(capex.catl_lifecycle_equity_commitment_yi, 1)}亿元。"
        f"集团资金模型最低余量为正：预留给其他战略项目的资金储备最紧年份仍有"
        f"{_n(min(row.funds_reserved_for_other_strategy_yi for row in snapshot.funding), 1)}亿元，"
        "不出现流动性缺口；固态、储能/AIDC等未决敞口以压力刻度另行监控。",
        f"### 业绩影响：2030动力电池业务线价值{_n(ledger.power_value_2030_with_swap_yi, 1)}亿元",
        f"较无换电纯制造情景{_n(ledger.power_value_2030_no_swap_yi, 1)}亿元增加"
        f"{_n(ledger.power_value_2030_with_swap_yi - ledger.power_value_2030_no_swap_yi, 1)}亿元；"
        f"稳态换电运营归母净利润{_n(swap.catl_attributable_net_profit_yi, 1)}亿元/年，"
        f"初装现金收益率{_p(swap.catl_cash_yield_on_initial_equity, 0)}"
        f"（400亿元回购隐含回报约{_p(buyback_yield, 0)}），"
        f"正算EBITDA对CRF门槛覆盖{_x(swap.forward_to_required_ebitda)}。",
        "### 关键项：先看覆盖与现金，再看价值",
        f"单变量敏感性中经营可行性的生死线是覆盖倍数不低于1.0"
        f"（中性{_x(swap.forward_to_required_ebitda)}）；"
        "估值层的最大变量是运营EV/EBITDA与制造PE中枢；"
        "证据最弱、需要持续跟踪验证的是充电段份额差链条——它只进敏感性，不进可归因价值。",
        "### 风险提示",
        "结论依赖中性参数：若服务费与租金、电池价格路径、换电渗透率或站均利用率"
        "显著弱于假设，覆盖倍数与可归因价值将同步下修；估值倍数中枢若从18×回落到"
        "纯基建区间，换电运营价值部分将大幅缩水。并购情景（启源、蔚来）只作扰动项，"
        "站体物理兼容未论证前不计入基准。所有数字可由configs/base.toml参数复算。",
    ])
    executive_summary = (
        f"中性假设下结论为 **{final_memo.status}**：建设期维持{_p(config['finance']['construction_ownership'], 0)}经济权益，"
        f"把需求反推的站网在{config['construction']['station_network_completion_year']}年以前建完；"
        f"CATL建设期累计资本调用约 **{_n(capex.catl_total_equity_call_yi, 1)}亿元**，"
        f"单年峰值约 **{_n(capex.catl_peak_equity_call_yi, 1)}亿元**。"
        f"{config['meta']['target_year']}E动力电池业务线价值约 **{_n(ledger.power_value_2030_with_swap_yi, 1)}亿元**；"
        f"其中可归因换电价值约 **{_n(ledger.total_swap_increment_value_yi, 1)}亿元**，"
        f"相当于当前宁德时代A+H市值的 **{_p(ledger.attributable_swap_value_to_current_group_market_cap)}**。"
        "换电的业务属性有二：既以"
        f"**{_p(swap.catl_cash_yield_on_initial_equity, 0)}稳态初装现金收益率**（远高于400亿元回购约"
        f"{_p(buyback_yield, 0)}的隐含回报）稳住动力电池基本盘，又构成面向类固收市场的金融类权益投资生意——"
        f"蔚能REITs已跑通退出路径，最保守出表30%可净回款 **{_n(exit_30_net_yi, 1)}亿元**，"
        f"为建设期资本调用的 **{_x(exit_multiple)}**。集团当前资金模型不要求提前出表；业务成熟后是否卖到30%、20%或10%，"
        "取决于届时明确资金需求与ABS/REITs市场承接能力，不预设固定最优档。"
    )
    valuation_note = (
        f"运营{_x(config['finance']['swap_ev_ebitda'], 0)}落在基础设施/公用事业运营区间"
        "（约6.7—14×）之上：换电标准、电池供应和数据闭环构成战略溢价，18×已经包含这部分。"
        "Blackstone、Ares等独立资管公司倍数只用于对照说明商业模式差异——真GP以少量资本管理第三方AUM收费，"
        "与CATL重资产持有运营并不同构，因此不叠加资管溢价，也不在主估值中单列资管平台价值；"
        "只有未来资产实际滚动发行、形成真实管理费收入后，才作为向上情景另行讨论。"
    )
    light_formula = (
        f"`净回款 = 费后项目权益价值 ×（{_p(config['finance']['construction_ownership'], 0)}－终局权益）"
        "×（1－交易成本率）`  \n"
        "`持续动力价值 = 制造价值 + 保留运营权益价值`  \n"
        "`含回款后动力价值 = 持续动力价值 + 净回款`"
    )
    profit_retention_note = (
        "经常利润保留率可能略高于原值，原因是降低底层权益后，更多电池转为对SPV的外部制造销售，"
        "这不是把同一利润重复计算。持续价值仍会因运营权益下降而减少，"
        "因此不能只看利润保留率下结论。"
    )
    funding_method_note = (
        f"资金起点使用{config['meta']['reference_year']}H1货币资金加交易性金融资产（下表统称现金类资产）。"
        f"{config['meta']['reference_year']}本期原始CFO只取全年预测减已实现H1 CFO，避免重复。"
        "原始CFO独立依据历史CFO/净利润转化和预测输入，不由净利润直接代替；"
        f"分红按连续三年{_p(config['group_funding']['dividend_payout_ratio'], 0)}的习惯做全年储备；"
        "已宣告中期分红属于该储备的一部分，不再另扣一次。原始CFO再扣分红、回购、三项已识别并购（中恒＋世纪互联＋启源）和换电资本后，"
        "得到的是‘当年新增可投资资金’，而不是会计报表中的‘可用CFO’。"
    )
    mineral_commitment = next(
        item for item in snapshot.capital_commitments if "矿产资源" in item["label"]
    )
    commitment_method_note = (
        f"矿产资源投资公司的{_n(mineral_commitment['headline_amount_yi'], 0)}亿元是注册资本安排，"
        "且含现金与股权出资，实缴时点未披露，不能为了让表格“完整”而机械均摊进集团年度现金流。"
        "世纪互联买方虽为宁德时代非控制、非并表关联方，v4.2起仍按审慎口径与中恒电气、启源芯动力"
        "合并计入2026年三项已识别并购现金。"
    )
    nio_method_note = (
        "ABS评估样本不是蔚能全部资产的估值。它证明了电池资产可以按租赁现金流独立评估；"
        f"蔚能整体{_n(nio['battery_bank_operating_gwh'], 0)}GWh级资产银行仍需同时看权益价值、负债和存量融资。"
        "蔚来站网则按重置成本只作交易价格锚，不等于可直接兼容巧克力站。"
    )
    reference_year = config["meta"]["reference_year"]
    construction_years = config["construction"]["years"]
    rounding = config["modeling"]["rounding"]
    city = config["vehicles"]["city"]
    city_high = city["scenes"][0]
    city_annual_high_frequency = (
        city["stock_wan"] / city["replacement_cycle_years"] * city_high["weight"]
    )
    city_old_rounded_annual = round(city_annual_high_frequency)
    city_old_compounded = (
        city_old_rounded_annual
        * len(construction_years)
        * city["nev_rates"][-1]
        * city_high["swap_penetration"]
        * city_high["catl_swap_share"]
    )
    city_raw_frequency = (
        city["daily_km"]
        / (
            city["battery_kwh"]
            * config["swap_business"]["usable_energy_factor"]
            / city["energy_consumption_kwh_km"]
        )
    )
    city_rounding_note = (
        f"城配旧版{round(city_old_compounded):g}万辆的原因已经查清："
        f"`{city['stock_wan']:g}÷{city['replacement_cycle_years']:g}×"
        f"{_p(city_high['weight'],0)}={city_annual_high_frequency:g}万辆/年`曾先取整为"
        f"{city_old_rounded_annual:g}，再乘{len(construction_years)}年、"
        f"{_p(city['nev_rates'][-1],0)}、{_p(city_high['swap_penetration'],0)}、"
        f"{_p(city_high['catl_swap_share'],0)}，得到{city_old_compounded:.2f}并显示"
        f"{round(city_old_compounded):g}。{city_raw_frequency:.3f}是日均换电频次，不是"
        f"{reference_year - 1}年存量。若保留{city_annual_high_frequency:g}到车型终局节点，"
        f"则得到{scale.operating_stock_by_vehicle_wan['city']:.1f}万辆；v4.1采用后者。"
        "这是修正过早取整，并没有改变汽车总量。"
    )
    station_timing_note = (
        f"{reference_year - 1}年末已建成骐骥"
        f"{config['construction']['opening_2025_stations']['heavy']:,}座、巧克力"
        f"{config['construction']['opening_2025_stations']['choco']:,}座，它们属于终局总资产和总CAPEX，"
        f"但不属于{reference_year}年新增现金。因此它们只改变建设期现金时点，不改变完成同一终局网络所需的项目总资本。"
        f"{completion_year + 1}—{target_year}只有车辆继续放量和早期"
        f"{city_battery_life_years:g}年电池首轮更新（城配寿命按2000次循环临界点推算），没有新增站体。"
    )
    station_impact_explanation = (
        f"同样增加1,000站，骐骥EBITDA为正、巧克力为负，原因不是收入需求方向相反，而是单站电池库存差异："
        f"骐骥{config['stations']['heavy']['inventory_blocks']:g}×"
        f"{config['stations']['heavy']['block_kwh']:g}kWh带来的外部权益电池租金和套利可覆盖场租；"
        f"巧克力{config['stations']['choco']['inventory_blocks']:g}×"
        f"{config['stations']['choco']['block_kwh']:g}kWh的两项收入低于固定场租。"
        "上表把每个节点都拆出，避免将车辆增长误归因到站数。"
    )
    v32_audit_table = _table(
        ["模块", "参数", "v3.2主链", "v4.2当前", "核对结论", "原因/处理", "影响"],
        parameter_audit_rows(config, snapshot),
    )
    v32_outcome_audit_table = _table(
        ["拍板结果", "v3.2", "v4.2当前", "变化", "归因"],
        outcome_audit_rows(snapshot),
    )

    values = {
        "model_name": snapshot.meta["model_name"],
        "reference_year": reference_year,
        "post_reference_year": reference_year + 1,
        "target_year": target_year,
        "completion_year": completion_year,
        "construction_start_year": construction_years[0],
        "construction_end_year": construction_years[-1],
        "current_market_cap_text": _n(config["financial_2026e"]["group_market_cap_ah_yi"], 0) + "亿元",
        "current_shipments_gwh": _n(config["financial_2026e"]["power_battery_shipments_gwh"], 0),
        "wacc_pct": _p(config["finance"]["wacc"]),
        "crf_pct": _p(config["finance"]["capital_recovery_factor"], 0),
        "terminal_vehicle_decimals": rounding["terminal_vehicle_decimals"],
        "terminal_frequency_decimals": rounding["terminal_frequency_decimals"],
        "report_money_decimals": rounding["report_money_decimals"],
        "city_rounding_note": city_rounding_note,
        "choco_planning_capacity": _n(config["stations"]["choco"]["planning_daily_capacity"], 0),
        "old_heavy_station_target": _n(3563, 0),
        "station_impact_explanation": station_impact_explanation,
        "construction_ownership_pct": _p(config["finance"]["construction_ownership"], 0),
        "debt_ratio_pct": _p(config["finance"]["debt_ratio"], 0),
        "station_timing_note": station_timing_note,
        "model_horizon_years": config["finance"]["model_horizon_years"],
        "external_share_pct": _p(config["swap_business"]["swap_battery_external_sales_share"], 0),
        "manufacturing_pe": _x(config["finance"]["manufacturing_pe"], 0),
        "swap_multiple": _x(config["finance"]["swap_ev_ebitda"], 0),
        "terminal_ownership_text": "/".join(
            _p(value, 0) for value in sorted(
                config["light_asset"]["terminal_ownership_options"], reverse=True
            )
        ),
        "executive_summary": executive_summary,
        "source_table": source_table,
        "parameter_table": parameter_table,
        "baseline_table": baseline_table,
        "baseline_method_gap_table": baseline_method_gap_table,
        "annual_scale_table": annual_scale_table,
        "frequency_table": frequency_table,
        "station_demand_table": station_demand_table,
        "station_reconciliation_table": station_reconciliation_table,
        "station_economics_table": station_economics_table,
        "station_economics_note": station_economics_note,
        "station_unit_impact_table": station_unit_impact_table,
        "station_delta_impact_table": station_delta_impact_table,
        "scale_memo": _memo_text(memo_map["规模与网络"]),
        "capex_table": capex_table,
        "capital_factor_table": capital_factor_table,
        "capex_summary": capex_summary,
        "capex_memo": _memo_text(memo_map["资本开支"]),
        "required_ebitda_table": required_ebitda_table,
        "operating_table": operating_table,
        "cash_return_table": cash_return_table,
        "manufacturing_table": manufacturing_table,
        "operating_calibration_table": operating_calibration_table,
        "business_memo": _memo_text(memo_map["换电经营"]),
        "power_total_table": power_total_table,
        "bridge_table": bridge_table,
        "performance_anchor_table": performance_anchor_table,
        "baseline_comparison_table": baseline_comparison_table,
        "market_value_table": market_value_table,
        "ledger_memo": _memo_text(memo_map["动力电池总账"]),
        "valuation_method_table": valuation_method_table,
        "valuation_comparable_table": valuation_comparable_table,
        "valuation_note": valuation_note,
        "light_formula": light_formula,
        "light_transaction_table": light_transaction_table,
        "light_decision_table": light_decision_table,
        "profit_retention_note": profit_retention_note,
        "light_conclusion": light_conclusion,
        "reits_case_table": reits_case_table,
        "reits_recycle_table": reits_recycle_table,
        "reits_recycle_note": reits_recycle_note,
        "light_memo": _memo_text(memo_map["成熟期资本循环"]),
        "funding_table": funding_table,
        "historical_cfo_table": historical_cfo_table,
        "funding_method_note": funding_method_note,
        "commitment_table": commitment_table,
        "commitment_method_note": commitment_method_note,
        "commitment_2026_note": commitment_2026_note,
        "solid_state_derivation_table": solid_state_derivation_table,
        "solid_state_note": solid_state_note,
        "solid_state_capex_text": f"{solid_state['full_newbuild_capex_yi'] / 100:.0f}亿",
        "exposure_table": exposure_table,
        "light_support_table": light_support_table,
        "sensitivity_table": sensitivity_table,
        "sensitivity_interpretation": sensitivity_interpretation,
        "private_penetration_table": private_penetration_table,
        "private_scenario_table": private_scenario_table,
        "private_scenario_note": private_scenario_note,
        "critical_cycles": f"{config['battery_life_model']['critical_cycles']:,.0f}",
        "calendar_cap_years": f"{config['battery_life_model']['calendar_cap_years']:g}",
        "battery_life_table": battery_life_table,
        "battery_life_note": battery_life_note,
        "life_mode_comparison_table": life_mode_comparison_table,
        "life_mode_comparison_note": life_mode_comparison_note,
        "funding_memo": _memo_text(memo_map["集团资金"]),
        "nio_fact_table": nio_fact_table,
        "nio_method_note": nio_method_note,
        "qiyuan_asset_table": qiyuan_asset_table,
        "qiyuan_asset_note": qiyuan_asset_note,
        "mna_input_table": mna_input_table,
        "mna_bridge_table": mna_bridge_table,
        "v32_audit_table": v32_audit_table,
        "v32_outcome_audit_table": v32_outcome_audit_table,
        "final_conclusion": final_conclusion,
    }
    template_path = ROOT / "templates" / "strategic_report_v4_2_1.md.tpl"
    return Template(template_path.read_text(encoding="utf-8")).substitute(values)


def write_outputs(
    config: dict,
    snapshot: ModelSnapshot,
    report_path: Path,
    private_snapshots: dict[str, ModelSnapshot] | None = None,
    legacy_snapshot: ModelSnapshot | None = None,
) -> dict[str, Path]:
    output_dir = ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_dir / "decision_snapshot_v4_2.json"
    registry_path = output_dir / "dashboard_parameter_registry_v4_2.json"
    snapshot_path.write_text(
        json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    registry_path.write_text(
        json.dumps(parameter_registry(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_path.write_text(
        render_report(config, snapshot, private_snapshots, legacy_snapshot),
        encoding="utf-8",
    )
    return {
        "report": report_path,
        "snapshot": snapshot_path,
        "parameters": registry_path,
    }

from __future__ import annotations

import json
from pathlib import Path
from string import Template
from typing import Iterable

from config_loader import ROOT, parameter_registry
from derived import battery_price_rmb_kwh, lifecycle_factors
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


def render_report(config: dict, snapshot: ModelSnapshot) -> str:
    ledger = snapshot.ledger
    baseline = ledger.baseline
    capex = snapshot.capex
    swap = snapshot.swap_business
    scale = snapshot.scale
    sources = snapshot.sources
    current_light = max(snapshot.light_asset, key=lambda row: row.terminal_ownership)
    first_light = max(
        (
            row for row in snapshot.light_asset
            if row.terminal_ownership < current_light.terminal_ownership
        ),
        key=lambda row: row.terminal_ownership,
    )
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
                "资管平台估值",
                f"费率{_p(config['finance']['manager_fee_rate'])} / 净利率{_p(config['finance']['manager_net_margin'], 0)} / PE {_x(config['finance']['manager_pe'], 0)}",
                "全部为可调研究参数，不冒充公司指引",
            ),
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
                "2026E道路电动车制造基准净利润",
                f"{_n(config['financial_2026e']['power_battery_shipments_gwh'], 0)}GWh×"
                f"当年电池价格×{_p(config['swap_business']['with_swap_manufacturing_net_margin'], 0)}",
                _n(baseline.modeled_power_net_profit_2026e_yi, 1) + "亿元",
            ),
            (
                "2026E道路电动车制造基准价值",
                "道路电动车制造净利润×PE",
                _n(baseline.modeled_power_market_value_2026e_yi, 1) + "亿元",
            ),
            (
                "校验",
                "动力市值＋其余业务当前市值＝当前A+H市值",
                _n(baseline.group_market_value_2026e_yi, 1) + "亿元",
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
        relevant = [row for row in scale.rows if row.vehicle_key == key]
        vehicles = sum(row.catl_swap_vehicles_wan for row in relevant)
        weighted_frequency = (
            sum(row.catl_swap_vehicles_wan * row.swap_frequency_per_day for row in relevant)
            / vehicles if vehicles else 0.0
        )
        frequency_rows.append((
            vehicle["label"],
            _n(vehicles, 1),
            _n(weighted_frequency, 2),
            "Σ场景车辆×(日均里程÷可用续航)÷Σ场景车辆",
        ))
    frequency_table = _table(
        ["车型", "累计CATL换电车", "加权日频次", "推导"], frequency_rows
    )
    station_demand_table = _table(
        ["站网", "工位上限", "能量上限", "规划能力（外生）", "物理余量", "成熟日需求", "终局站数", "2026目标", "建成"],
        [
            (
                "骐骥重卡",
                _n(scale.station_capacity_diagnostics["heavy"]["mechanical_limit"], 0),
                _n(scale.station_capacity_diagnostics["heavy"]["energy_limit"], 0),
                _n(scale.station_capacity_diagnostics["heavy"]["planning_capacity"], 0),
                _p(scale.station_capacity_diagnostics["heavy"]["physical_headroom_ratio"], 0),
                _n(scale.mature_daily_swaps["heavy"], 0) + "次",
                _n(scale.target_station_demand["heavy"]) + "座",
                _n(config["construction"]["station_2026_cumulative_targets"]["heavy"]) + "座",
                str(config["construction"]["station_network_completion_year"]),
            ),
            (
                "巧克力",
                _n(scale.station_capacity_diagnostics["choco"]["mechanical_limit"], 0),
                _n(scale.station_capacity_diagnostics["choco"]["energy_limit"], 0),
                _n(scale.station_capacity_diagnostics["choco"]["planning_capacity"], 0),
                _p(scale.station_capacity_diagnostics["choco"]["physical_headroom_ratio"], 0),
                _n(scale.mature_daily_swaps["choco"], 0) + "次",
                _n(scale.target_station_demand["choco"]) + "座",
                _n(config["construction"]["station_2026_cumulative_targets"]["choco"]) + "座",
                str(config["construction"]["station_network_completion_year"]),
            ),
        ],
    )
    station_reconciliation_table = _table(
        [
            "车辆组", "v3.2车辆(万)", "v4车辆(万)", "v3.2频次",
            "v4频次", "v3.2日需求(万次)", "v4日需求(万次)", "差异解释",
        ],
        station_reconciliation_rows(config, snapshot),
    )

    station_unit_rows = []
    station_unit_metrics: dict[str, dict[str, float]] = {}
    station_labels = {"heavy": "骐骥重卡", "choco": "巧克力"}
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
            station["battery_life_years"],
        )
        lifecycle_capital = body_capex + battery_capex * factor.capital_multiplier
        arbitrage = (
            station_battery_gwh
            * config["swap_business"]["operating_days"]
            * config["swap_business"]["grid_spread_rmb_kwh"]
            * config["swap_business"]["rte"]
            / 100.0
        )
        site_rent = (
            1000 * config["swap_business"]["site_rent_wan_year"] / 1e4
        )
        ebitda_delta = arbitrage - site_rent
        value_delta = (
            ebitda_delta * config["finance"]["swap_ev_ebitda"]
            - lifecycle_capital * config["finance"]["debt_ratio"]
        ) * config["finance"]["construction_ownership"]
        station_unit_metrics[group] = {
            "initial_capex": body_capex + battery_capex,
            "lifecycle_capital": lifecycle_capital,
            "arbitrage": arbitrage,
            "site_rent": site_rent,
            "ebitda_delta": ebitda_delta,
            "value_delta": value_delta,
        }
        station_unit_rows.append((
            station_labels[group],
            _n(station_battery_gwh, 3),
            _n(body_capex + battery_capex, 1),
            _n(lifecycle_capital, 1),
            _n(arbitrage, 2),
            _n(site_rent, 2),
            _n(ebitda_delta, 2),
            _n(value_delta, 2),
        ))
    station_unit_impact_table = _table(
        [
            "每增加1,000站", "站内电池(GWh)", "初装CAPEX", "全周期资本",
            "套利收入/年", "场租/年", "固定需求下EBITDA变化", "CATL运营价值变化",
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
            "站网", "v3.2站数", "v4站数", "站数变化", "初装CAPEX一阶变化",
            "稳态EBITDA一阶变化", "CATL运营价值一阶变化",
        ],
        station_delta_rows,
    )

    capital_factor_table = _table(
        ["电池寿命", "全周期资本倍数", "观察期末残值率", "推导口径"],
        [
            (
                label,
                _x(factor, 3),
                _p(capex.terminal_residual_by_life[label]),
                "初装1＋历次(买新－卖旧)按WACC折现；残值由期末在役批年龄推导",
            )
            for label, factor in sorted(capex.lifecycle_factor_by_life.items())
        ],
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
    capex_summary = _table(
        ["指标", "计算", "结果"],
        [
            ("初装项目CAPEX", "各年车辆电池＋站内电池＋站体", _n(capex.total_initial_capex_yi, 1) + "亿元"),
            ("建设期首轮更新", "到期电池重购－残值回收", _n(capex.first_replacement_net_capex_yi, 1) + "亿元"),
            (
                "CATL初装权益投入",
                "初装项目CAPEX×权益资本比例×CATL权益",
                _n(
                    capex.total_initial_capex_yi
                    * (1 - config["finance"]["debt_ratio"])
                    * config["finance"]["construction_ownership"],
                    1,
                ) + "亿元",
            ),
            (
                "CATL建设期首轮更新投入",
                "首轮更新净支出×权益资本比例×CATL权益",
                _n(
                    capex.first_replacement_net_capex_yi
                    * (1 - config["finance"]["debt_ratio"])
                    * config["finance"]["construction_ownership"],
                    1,
                ) + "亿元",
            ),
            ("等效全周期资本底座", "Σ各批初装电池×派生资本倍数＋站体", _n(capex.lifecycle_capital_base_yi, 1) + "亿元"),
            ("稳态项目债务", "等效全周期资本底座×项目债务比例", _n(capex.project_debt_yi, 1) + "亿元"),
            ("CATL全周期权益承诺", "等效全周期资本底座×权益资本比例×CATL权益", _n(capex.catl_lifecycle_equity_commitment_yi, 1) + "亿元"),
            ("年资本要求", "等效全周期资本底座×CRF", _n(capex.annual_capital_requirement_yi, 1) + "亿元"),
            ("CATL累计资本调用", "项目CAPEX×权益资本比例×CATL权益", _n(capex.catl_total_equity_call_yi, 1) + "亿元"),
            ("CATL单年峰值", "年度资本调用最大值", f"{_n(capex.catl_peak_equity_call_yi, 1)}亿元（{capex.peak_year}年）"),
        ],
    )

    required_ebitda_table = _table(
        ["倒算步骤", "公式", "结果"],
        [
            ("等效全周期资本底座", "初装＋历次净更新折现；不以结果锚校准", _n(capex.lifecycle_capital_base_yi, 1) + "亿元"),
            ("资本要求FCFF", "资本底座×CRF", _n(capex.annual_capital_requirement_yi, 1) + "亿元"),
            ("成熟期折旧", "各批初装×(全周期倍数－期末残值率)÷寿命＋站体÷年限", _n(capex.mature_annual_depreciation_yi, 1) + "亿元"),
            (
                "门槛EBITDA",
                "(FCFF－折旧×税率)÷(1－税率)",
                _n(swap.required_ebitda_yi, 1) + "亿元",
            ),
            ("正算覆盖", "正算EBITDA÷门槛EBITDA", _x(swap.forward_to_required_ebitda)),
        ],
    )
    operating_table = _table(
        ["经营链项目", "公式口径", "结果"],
        [
            ("换电服务收入", "年交易电量×服务费", _n(swap.service_revenue_yi, 1) + "亿元"),
            ("电池租金", "可收费电池GWh×年租金", _n(swap.battery_rent_yi, 1) + "亿元"),
            ("峰谷套利", "站内电池×价差×效率×运营天数", _n(swap.arbitrage_yi, 1) + "亿元"),
            ("辅助服务", "外部参数", _n(swap.ancillary_yi, 1) + "亿元"),
            ("营业收入", "以上收入合计", _n(swap.revenue_yi, 1) + "亿元"),
            ("现金OPEX", "损耗电费＋场租＋人工＋软件", _n(swap.opex_yi, 1) + "亿元"),
            ("EBITDA", "收入－现金OPEX", _n(swap.ebitda_yi, 1) + "亿元"),
            ("项目净利润", "(EBITDA－折旧－利息)×(1－税率)", _n(swap.project_net_profit_yi, 1) + "亿元"),
            ("CATL归母净利润", "项目净利润×建设期权益", _n(swap.catl_attributable_net_profit_yi, 1) + "亿元"),
            ("项目EV", "EBITDA×EV/EBITDA", _n(swap.enterprise_value_yi, 1) + "亿元"),
            ("CATL运营价值", "(项目EV－项目债务)×建设期权益", _n(swap.catl_attributable_value_yi, 1) + "亿元"),
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

    power_total_table = _table(
        ["观察口径", "制造净利润", "运营归母净利润", "动力电池归母净利润", "制造价值", "运营价值", "动力电池价值"],
        [
            (
                "2026E道路电动车制造基准",
                _n(baseline.modeled_power_net_profit_2026e_yi, 1), "0", _n(baseline.modeled_power_net_profit_2026e_yi, 1),
                _n(baseline.modeled_power_market_value_2026e_yi, 1), "0", _n(baseline.modeled_power_market_value_2026e_yi, 1),
            ),
            (
                "2026E动力分部市值分摊基准",
                "—", "—", _n(baseline.power_net_profit_2026e_yi, 1),
                "—", "—", _n(baseline.power_market_value_2026e_yi, 1),
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
                "制造销量/市占率差",
                _n(ledger.manufacturing_volume_share_effect_net_profit_yi, 1),
                _n(ledger.manufacturing_volume_share_effect_value_yi, 1),
                "否",
                "(有换电收入－纯制造收入)×纯制造净利率",
            ),
            (
                "道路电动车制造盘利润率保护",
                _n(ledger.manufacturing_swap_margin_effect_net_profit_yi, 1),
                _n(ledger.manufacturing_swap_margin_effect_value_yi, 1),
                "是",
                "有换电制造收入×净利率差；本次仅含已建模道路电动车",
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
                "道路电动车制造盘利润率保护＋直接运营",
            ),
            (
                "完整有换电－纯制造差额",
                _n(ledger.full_with_vs_pure_manufacturing_gap_net_profit_yi, 1),
                _n(ledger.full_with_vs_pure_manufacturing_gap_value_yi, 1),
                "情景上限",
                "制造线全部差额＋直接运营",
            ),
        ],
    )
    current_comparison_table = _table(
        ["战略观察", "计算", "结果"],
        [
            (
                "较2026道路电动车制造基准增加",
                "2030有换电动力价值－2026同口径制造价值",
                _n(ledger.power_value_growth_vs_2026_modeled_yi, 1) + "亿元",
            ),
            (
                "2030动力价值/2026道路电动车制造基准",
                "2030有换电动力价值÷2026同口径制造价值",
                _x(ledger.power_value_multiple_vs_2026_modeled),
            ),
            (
                "2030动力价值/2026动力分部市值分摊",
                "2030有换电动力价值÷H1毛利占比分摊的当前动力价值",
                _x(ledger.power_value_multiple_vs_2026_allocated),
            ),
            (
                "可归因换电价值/2026道路电动车制造基准",
                "可归因换电价值÷同口径2026制造价值",
                _p(ledger.attributable_swap_value_to_2026_modeled_power_value),
            ),
            (
                "可归因换电价值/2026动力分部市值分摊",
                "可归因换电价值÷当前动力业务市值贡献",
                _p(ledger.attributable_swap_value_to_2026_allocated_power_value),
            ),
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
            (
                "轻资产后底层权益",
                "(费后资产EV－债务)×保留权益",
                "管理费由SPV支付，先扣费再估权益，防止双算",
            ),
            (
                "资管平台",
                "AUM×管理费率×资管净利率×资管PE",
                "平台费收入与底层资产价值分开；参数可调",
            ),
        ],
    )
    sale_example = next(
        row for row in snapshot.light_asset
        if row.terminal_ownership < config["finance"]["construction_ownership"]
    )
    manager_table = _table(
        ["资管平台推导", "公式", "结果"],
        [
            ("管理资产AUM", "经营EBITDA×运营倍数÷(1＋费率×运营倍数)", _n(sale_example.managed_aum_yi, 1) + "亿元"),
            ("管理费收入", "AUM×管理费率", _n(sale_example.manager_fee_revenue_yi, 1) + "亿元"),
            ("资管净利润", "管理费收入×资管净利率", _n(sale_example.manager_net_profit_yi, 1) + "亿元"),
            ("资管平台价值", "资管净利润×资管PE", _n(sale_example.manager_value_yi, 1) + "亿元"),
        ],
    )
    light_transaction_table = _table(
        ["终局权益", "毛回款", "净回款", "制造价值", "保留运营价值", "资管平台价值", "持续动力价值"],
        [
            (
                _p(row.terminal_ownership, 0),
                _n(row.sale_proceeds_gross_yi, 1),
                _n(row.sale_proceeds_net_yi, 1),
                _n(
                    row.post_exit_power_value_ex_cash_yi
                    - row.retained_operating_value_yi
                    - row.manager_value_yi,
                    1,
                ),
                _n(row.retained_operating_value_yi, 1),
                _n(row.manager_value_yi, 1),
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
        f" **{_p(current_light.terminal_ownership, 0)}**、暂不出表。若成熟后出现已经拍板且回报更高的资金用途，"
        f"优先测试保留 **{_p(first_light.terminal_ownership, 0)}**：可净回款"
        f" **{_n(first_light.sale_proceeds_net_yi, 1)}亿元**，代价是持续动力价值减少"
        f" **{_n(-first_light.persistent_power_value_delta_yi, 1)}亿元**；计入回款后净增加"
        f" **{_n(first_light.including_cash_power_value_delta_yi, 1)}亿元**。"
        "其余更低权益档只有在资金缺口进一步扩大、且替代项目价值足以覆盖更大的持续价值损失时才进入选择。"
    )

    funding_table = _table(
        ["年份", "预测归母净利润", "可用CFO", "分红率", "分红储备", "回购储备", "已识别直接并购现金", "换电资本", "期末液态资源", "高于流动性底线"],
        [
            (
                row.year,
                _n(row.projected_net_profit_yi, 1),
                _n(row.available_cfo_yi, 1),
                _p(row.dividend_payout_ratio, 0),
                _n(row.dividend_reserve_yi, 1),
                _n(row.buyback_reserve_yi, 1),
                _n(row.known_direct_mna_cash_yi, 1),
                _n(row.swap_equity_call_yi, 1),
                _n(row.ending_liquid_resources_before_uncommitted_strategy_yi, 1),
                _n(row.headroom_above_liquidity_floor_yi, 1),
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
        ["方案", "买入资产", "现金支出", "承接负债", "总资本负担", "剩余自建资本调用", "布局提前", "价格依据"],
        [
            (
                row["label"],
                f"站网{_n(row['acquired_network_stations'])}座 / 电池银行{_n(row['acquired_battery_bank_gwh'], 1)}GWh",
                _n(row["cash_consideration_yi"], 1),
                _n(row["assumed_debt_yi"], 1),
                _n(row["total_transaction_burden_yi"], 1),
                _n(row["remaining_selfbuild_catl_equity_call_yi"], 1),
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

    memo_table = _table(
        ["模块负责人", "判断", "先提交的子结论", "关键风险"],
        [
            (memo.owner, memo.status, memo.conclusion, memo.key_risk)
            for memo in snapshot.memos[:-1]
        ],
    )
    executive_summary = (
        f"中性假设下结论为 **{final_memo.status}**：建设期维持{_p(config['finance']['construction_ownership'], 0)}经济权益，"
        f"把需求反推的站网在{config['construction']['station_network_completion_year']}年以前建完；"
        f"CATL建设期累计资本调用约 **{_n(capex.catl_total_equity_call_yi, 1)}亿元**，"
        f"单年峰值约 **{_n(capex.catl_peak_equity_call_yi, 1)}亿元**。"
        f"{config['meta']['target_year']}E动力电池业务线价值约 **{_n(ledger.power_value_2030_with_swap_yi, 1)}亿元**；"
        f"其中可归因换电价值约 **{_n(ledger.total_swap_increment_value_yi, 1)}亿元**，"
        f"相当于当前宁德时代A+H市值的 **{_p(ledger.attributable_swap_value_to_current_group_market_cap)}**。"
        f"集团当前资金模型不要求提前出表；业务成熟后若出现更高回报的明确资金用途，"
        f"{_p(first_light.terminal_ownership, 0)}是第一档轻资产方案。"
    )
    valuation_note = (
        f"运营{_x(config['finance']['swap_ev_ebitda'], 0)}沿用"
        "[v3.0 §4.1](换电毛估估_折扣链与总表_v3.0.md#41-倍数影响极大)的可比框架："
        "它是含标准、数据和电池供应协同溢价的基础设施运营估值，不是把宁德时代直接类比成Blackstone。"
        "资管平台只有在真实收取管理费并承担持续管理职能后才单列估值。"
    )
    light_formula = (
        f"`净回款 = 费后项目权益价值 ×（{_p(config['finance']['construction_ownership'], 0)}－终局权益）"
        "×（1－交易成本率）`  \n"
        "`持续动力价值 = 制造价值 + 保留运营权益价值 + 资管平台价值`  \n"
        "`含回款后动力价值 = 持续动力价值 + 净回款`"
    )
    profit_retention_note = (
        "经常利润保留率可能略高于原值，原因是降低底层权益后，更多电池转为对SPV的外部制造销售，"
        "同时新增管理费利润；这不是把同一利润重复计算。持续价值仍会因运营权益下降而减少，"
        "因此不能只看利润保留率下结论。"
    )
    funding_method_note = (
        f"资金起点使用{config['meta']['reference_year']}H1货币资金加交易性金融资产。"
        f"{config['meta']['reference_year']}可用CFO只取全年预测减已实现H1 CFO，避免重复。"
        f"分红按连续三年{_p(config['group_funding']['dividend_payout_ratio'], 0)}的习惯做全年储备；"
        "已宣告中期分红属于该储备的一部分，不再另扣一次。"
    )
    mineral_commitment = next(
        item for item in snapshot.capital_commitments if "矿产资源" in item["label"]
    )
    commitment_method_note = (
        f"矿产资源投资公司的{_n(mineral_commitment['headline_amount_yi'], 0)}亿元是注册资本安排，"
        "且含现金与股权出资，实缴时点未披露；世纪互联买方是宁德时代非控制、非并表关联方。"
        "两项都不能为了让表格“完整”而机械均摊进集团年度现金流。"
    )
    nio_method_note = (
        "ABS评估样本不是蔚能全部资产的估值。它证明了电池资产可以按租赁现金流独立评估；"
        f"蔚能整体{_n(nio['battery_bank_operating_gwh'], 0)}GWh级资产银行仍需同时看权益价值、负债和存量融资。"
        "蔚来站网则按重置成本只作交易价格锚，不等于可直接兼容巧克力站。"
    )
    v32_audit_table = _table(
        ["模块", "参数", "v3.2主链", "v4当前", "核对结论", "原因/处理", "影响"],
        parameter_audit_rows(config, snapshot),
    )
    v32_outcome_audit_table = _table(
        ["拍板结果", "v3.2", "v4当前", "变化", "归因"],
        outcome_audit_rows(snapshot),
    )

    values = {
        "model_name": snapshot.meta["model_name"],
        "executive_summary": executive_summary,
        "source_table": source_table,
        "parameter_table": parameter_table,
        "baseline_table": baseline_table,
        "annual_scale_table": annual_scale_table,
        "frequency_table": frequency_table,
        "station_demand_table": station_demand_table,
        "station_reconciliation_table": station_reconciliation_table,
        "station_unit_impact_table": station_unit_impact_table,
        "station_delta_impact_table": station_delta_impact_table,
        "scale_memo": _memo_text(memo_map["规模与网络"]),
        "capex_table": capex_table,
        "capital_factor_table": capital_factor_table,
        "capex_summary": capex_summary,
        "capex_memo": _memo_text(memo_map["资本开支"]),
        "required_ebitda_table": required_ebitda_table,
        "operating_table": operating_table,
        "manufacturing_table": manufacturing_table,
        "business_memo": _memo_text(memo_map["换电经营"]),
        "power_total_table": power_total_table,
        "bridge_table": bridge_table,
        "current_comparison_table": current_comparison_table,
        "ledger_memo": _memo_text(memo_map["动力电池总账"]),
        "valuation_method_table": valuation_method_table,
        "valuation_note": valuation_note,
        "manager_table": manager_table,
        "light_formula": light_formula,
        "light_transaction_table": light_transaction_table,
        "light_decision_table": light_decision_table,
        "profit_retention_note": profit_retention_note,
        "light_conclusion": light_conclusion,
        "light_memo": _memo_text(memo_map["成熟期资本循环"]),
        "funding_table": funding_table,
        "funding_method_note": funding_method_note,
        "commitment_table": commitment_table,
        "commitment_method_note": commitment_method_note,
        "exposure_table": exposure_table,
        "light_support_table": light_support_table,
        "funding_memo": _memo_text(memo_map["集团资金"]),
        "nio_fact_table": nio_fact_table,
        "nio_method_note": nio_method_note,
        "mna_input_table": mna_input_table,
        "mna_bridge_table": mna_bridge_table,
        "v32_audit_table": v32_audit_table,
        "v32_outcome_audit_table": v32_outcome_audit_table,
        "memo_table": memo_table,
        "final_conclusion": _memo_text(final_memo),
    }
    template_path = ROOT / "templates" / "strategic_report.md.tpl"
    return Template(template_path.read_text(encoding="utf-8")).substitute(values)


def write_outputs(
    config: dict,
    snapshot: ModelSnapshot,
    report_path: Path,
) -> dict[str, Path]:
    output_dir = ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_dir / "decision_snapshot_v4.json"
    registry_path = output_dir / "dashboard_parameter_registry_v4.json"
    snapshot_path.write_text(
        json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    registry_path.write_text(
        json.dumps(parameter_registry(config), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    report_path.write_text(render_report(config, snapshot), encoding="utf-8")
    return {
        "report": report_path,
        "snapshot": snapshot_path,
        "parameters": registry_path,
    }

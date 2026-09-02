from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from string import Template
from typing import Iterable

from config_loader import ROOT, parameter_registry
from derived import (
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


# ===========================================================================
# 方案A：把“结论”当作模型计算结果，而不是写死的散文
# ---------------------------------------------------------------------------
# 所有定性判断从句都从这里取 verdicts，叙述层永远跟着数据走，
# 不会出现“数字变了但结论相反”的脱节。
def compute_verdicts(config: dict, snapshot: ModelSnapshot) -> dict:
    dt = config.get("decision_thresholds", {})
    funding_rows = list(snapshot.funding)

    # 资金表是否出现流动性缺口：预留给其他战略项目的资金储备转负
    funding_gap = any(
        (getattr(r, "funds_reserved_for_other_strategy_yi", 0.0) or 0.0) < 0
        for r in funding_rows
    )
    # 是否跌破最低流动性底线
    liquidity_breach = any(
        (getattr(r, "closing_liquid_resources_before_uncommitted_strategy_yi", 1e12) or 1e12)
        < (getattr(r, "minimum_liquidity_reserve_yi", 0.0) or 0.0)
        for r in funding_rows
    )

    swap = snapshot.swap_business
    ebitda_coverage = float(getattr(swap, "forward_to_required_ebitda", 0.0) or 0.0)
    ebitda_coverage_pass = ebitda_coverage >= float(
        dt.get("min_forward_to_required_ebitda", 1.0)
    )

    ledger = snapshot.ledger
    capex = snapshot.capex
    value_mult = float(getattr(ledger, "total_swap_increment_value_yi", 0.0) or 0.0) / (
        float(getattr(capex, "catl_total_equity_call_yi", 1.0) or 1.0)
    )
    value_creation_pass = value_mult >= float(
        dt.get("min_swap_value_creation_multiple", 3.0)
    )

    peak_cash = float(getattr(capex, "catl_peak_equity_call_yi", 0.0) or 0.0)
    cfo_sum = sum(
        float(getattr(r, "period_cfo_yi", 0.0) or 0.0) for r in funding_rows
    ) or 1.0
    peak_cash_to_cfo = peak_cash / cfo_sum
    peak_cash_pass = peak_cash_to_cfo <= float(
        dt.get("max_peak_swap_cash_to_cfo", 0.15)
    )

    return {
        "funding_gap": funding_gap,
        "liquidity_breach": liquidity_breach,
        "ebitda_coverage": ebitda_coverage,
        "ebitda_coverage_pass": ebitda_coverage_pass,
        "value_creation_multiple": value_mult,
        "value_creation_pass": value_creation_pass,
        "peak_swap_cash_to_cfo": peak_cash_to_cfo,
        "peak_cash_pass": peak_cash_pass,
    }


# ===========================================================================
# 方案B：可选地把解释性段落交给 LLM 填写，但用已算好的 verdicts + 数字做围栏
# ---------------------------------------------------------------------------
# 任何异常（无 key、网络错、解析错）都回退到确定性规则文本，报告永远能生成。
def llm_narrate(
    config: dict,
    verdicts: dict,
    section: str,
    rule_text: str,
    numbers: dict | None = None,
) -> str:
    cfg = config.get("llm_narration", {})
    if not cfg.get("enabled", False):
        return rule_text
    try:
        import urllib.request

        api_key = os.environ.get(cfg.get("api_key_env", "OPENAI_API_KEY"), "")
        if not api_key:
            return rule_text

        facts = {
            "section": section,
            "verdicts": verdicts,
            "key_numbers": numbers or {},
        }
        system = (
            "你是投资研究报告的定性分析助手。下面给出已被确定性模型核实的指标(verdicts)"
            "与关键数字(key_numbers)。请只用这些数字和指标，撰写一段中文定性分析"
            "(markdown，不超过300字)。严格要求：(1)不得编造、不得改变任何数字；"
            "(2)结论必须与verdicts一致——尤其当verdicts.funding_gap为true时，必须明确"
            "提示流动性缺口，不得声称'没有触发流动性缺口'，反之亦然；"
            "(3)不新增表格；(4)保持客观、可审计的研究语气。"
        )
        user = json.dumps(facts, ensure_ascii=False)
        payload = json.dumps(
            {
                "model": cfg.get("model", "gpt-4o-mini"),
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "temperature": float(cfg.get("temperature", 0.2)),
            },
            ensure_ascii=False,
        )
        req = urllib.request.Request(
            cfg.get("base_url", "https://api.openai.com/v1/chat/completions"),
            data=payload.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        with urllib.request.urlopen(req, timeout=float(cfg.get("timeout", 30))) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["choices"][0]["message"]["content"].strip()
        return text or rule_text
    except Exception as exc:  # 任何失败都回退到确定性规则文本
        print(f"[llm_narrate] 回退到规则文本：{exc}", file=sys.stderr)
        return rule_text


# ===========================================================================
# 方案C：渲染后兜底校验——叙述必须与 verdicts 一致，否则报警/抛错
# ---------------------------------------------------------------------------
def validate_consistency(verdicts: dict, text: str) -> list[str]:
    warnings = []
    if verdicts.get("funding_gap") and "没有触发流动性缺口" in text:
        warnings.append(
            "不一致：verdicts 显示存在流动性缺口，但报告仍称'没有触发流动性缺口'"
        )
    if (not verdicts.get("funding_gap")) and "出现流动性缺口" in text:
        warnings.append(
            "不一致：verdicts 显示无流动性缺口，但报告称'出现流动性缺口'"
        )
    if verdicts.get("ebitda_coverage_pass") is False:
        if "覆盖门槛" in text and "不足" not in text and "未达" not in text:
            warnings.append("提示：EBITDA覆盖未达门槛，但报告未提示该风险")
    if verdicts.get("value_creation_pass") is False:
        if "价值创造倍数" in text and "不足" not in text:
            warnings.append("提示：换电价值创造倍数未达门槛，但报告未提示该风险")
    return warnings


def _handle_consistency(warnings: list[str], config: dict) -> None:
    if not warnings:
        return
    for w in warnings:
        print(f"[consistency] {w}", file=sys.stderr)
    if config.get("llm_narration", {}).get("strict_consistency", False):
        raise AssertionError("；".join(warnings))


def render_report(
    config: dict,
    snapshot: ModelSnapshot,
    use_llm: bool | None = None,
) -> str:
    ledger = snapshot.ledger
    baseline = ledger.baseline
    capex = snapshot.capex
    swap = snapshot.swap_business
    scale = snapshot.scale
    sources = snapshot.sources
    current_light = max(snapshot.light_asset, key=lambda row: row.terminal_ownership)
    light_by_ownership = {
        row.terminal_ownership: row for row in snapshot.light_asset
    }
    if use_llm is not None:
        _cfg = dict(config)
        _llm = dict(config.get("llm_narration", {}))
        _llm["enabled"] = bool(use_llm)
        _cfg["llm_narration"] = _llm
        config = _cfg

    final_memo = snapshot.memos[-1]
    memo_map = {memo.owner: memo for memo in snapshot.memos}
    verdicts = compute_verdicts(config, snapshot)

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
        value_delta = (
            ebitda_delta * config["finance"]["swap_ev_ebitda"]
            - lifecycle_capital * config["finance"]["debt_ratio"]
        ) * config["finance"]["construction_ownership"]
        station_unit_metrics[group] = {
            "initial_capex": body_capex + battery_capex,
            "lifecycle_capital": lifecycle_capital,
            "arbitrage": arbitrage,
            "station_battery_rent": station_battery_rent,
            "site_rent": site_rent,
            "ebitda_delta": ebitda_delta,
            "value_delta": value_delta,
        }
        station_unit_rows.append((
            station_labels[group],
            _n(station_battery_gwh, 3),
            _n(body_capex + battery_capex, 1),
            _n(lifecycle_capital, 1),
            _n(station_battery_rent, 2),
            _n(arbitrage, 2),
            _n(site_rent, 2),
            _n(ebitda_delta, 2),
            _n(value_delta, 2),
        ))
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
    capex_summary = _table(
        ["指标", "计算", "结果"],
        [
            (
                "2025年末存量站等效初装CAPEX",
                "305座骐骥＋1,020座巧克力的站体与站内电池；已投入、不进入2026现金",
                _n(capex.preperiod_station_initial_capex_yi, 1) + "亿元",
            ),
            (
                "2026—2030新增初装CAPEX",
                "逐年新增车辆电池＋新增站内电池＋新增站体",
                _n(
                    capex.total_initial_capex_yi
                    - capex.preperiod_station_initial_capex_yi,
                    1,
                ) + "亿元",
            ),
            ("终局初装项目CAPEX", "2025存量＋2026—2030新增", _n(capex.total_initial_capex_yi, 1) + "亿元"),
            ("建设期首轮更新", "到期电池重购－残值回收", _n(capex.first_replacement_net_capex_yi, 1) + "亿元"),
            (
                "CATL终局初装权益投入",
                "初装项目CAPEX×权益资本比例×CATL权益",
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
                _n(capex.catl_preperiod_station_equity_investment_yi, 1) + "亿元",
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
            ("CATL 2026—2030累计资本调用", "本期项目CAPEX×权益资本比例×CATL权益；不含2025存量", _n(capex.catl_total_equity_call_yi, 1) + "亿元"),
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

    power_total_table = _table(
        ["观察口径", "制造净利润", "运营归母净利润", "动力电池归母净利润", "制造价值", "运营价值", "动力电池价值"],
        [
            (
                "2026E量价法制造模型基准",
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
    sale_example = next(
        row for row in snapshot.light_asset
        if row.terminal_ownership < config["finance"]["construction_ownership"]
    )
    manager_table = _table(
        ["资管平台推导", "公式", "结果"],
        [
            ("基准已确认AUM", "只认已经滚动发行并进入管理平台的资产", _n(sale_example.managed_aum_yi, 1) + "亿元"),
            ("管理费收入", "AUM×管理费率", _n(sale_example.manager_fee_revenue_yi, 1) + "亿元"),
            ("资管净利润", "管理费收入×资管净利率", _n(sale_example.manager_net_profit_yi, 1) + "亿元"),
            ("资管平台价值", "资管净利润×资管PE", _n(sale_example.manager_value_yi, 1) + "亿元"),
        ],
    )
    manager_ramp_table = _table(
        ["滚动已发行AUM", "管理费收入", "资管净利润", "资管平台价值", "定位"],
        [
            (
                _n(aum, 0),
                _n(aum * config["finance"]["manager_fee_rate"], 1),
                _n(
                    aum * config["finance"]["manager_fee_rate"]
                    * config["finance"]["manager_net_margin"], 1
                ),
                _n(
                    aum * config["finance"]["manager_fee_rate"]
                    * config["finance"]["manager_net_margin"]
                    * config["finance"]["manager_pe"], 1
                ),
                (
                    "基准：未发行不计值" if aum == 0
                    else "滚动发行向上情景，不进入主估值"
                ),
            )
            for aum in config["light_asset"]["rolling_manager_aum_scenarios_yi"]
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
    _gap = verdicts["funding_gap"]
    light_conclusion_rule = (
        ("当前资金表**出现流动性缺口**（当年新增可投资资金为负，预留给其他战略项目的"
         "资金储备耗尽），因此需重新评估是否提前出表以回笼现金；" if _gap else
         f"当前资金表未触发流动性缺口，因此中性终局仍是保留"
         f" **{_p(current_light.terminal_ownership, 0)}**、暂不出表。")
        + "成熟后不指定30%或20%为固定最优："
        f"保留30%/20%/10%分别可净回款约"
        f" **{_n(light_by_ownership[0.30].sale_proceeds_net_yi,1)} /"
        f" {_n(light_by_ownership[0.20].sale_proceeds_net_yi,1)} /"
        f" {_n(light_by_ownership[0.10].sale_proceeds_net_yi,1)}亿元**。"
        "资金需求大、市场承接好就多卖；资金需求小或发行环境弱就少卖。真正的决策变量是届时资金缺口、"
        "替代项目回报和市场承接能力，不是一年净现金流量级的档位差本身。"
    )
    light_conclusion = llm_narrate(
        config, verdicts, "light_conclusion", light_conclusion_rule,
        {
            "terminal_ownership": current_light.terminal_ownership,
            "sale_proceeds_net_yi": {
                "0.30": light_by_ownership[0.30].sale_proceeds_net_yi,
                "0.20": light_by_ownership[0.20].sale_proceeds_net_yi,
                "0.10": light_by_ownership[0.10].sale_proceeds_net_yi,
            },
            "funding_gap": _gap,
        },
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
            "年份", "期初液态资产", "预测归母净利润", "本期原始CFO", "分红储备",
            "回购储备", "已识别投资/并购现金", "换电资本", "当年新增可投资资金",
            "其他战略动作前期末液态资产", "流动性底线", "预留给其他战略项目的资金储备",
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
    sensitivity_table = _table(
        [
            "参数组", "情景", "重卡/巧克力站", "2030前CATL资本调用",
            "门槛EBITDA", "可交付EBITDA", "覆盖倍数", "可归因换电价值",
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
                _n(row["attributable_swap_value_yi"], 1),
                _n(row["power_value_2030_yi"], 1),
                _n(row["power_value_delta_yi"], 1),
            )
            for row in snapshot.sensitivity
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
        [
            "方案", "买入资产", "交易现金", "纯自建CATL资本调用",
            "收购后剩余自建调用", "节省自建现金", "CATL总现金需求",
            "较纯自建现金增量", "项目端承接负债", "布局提前", "价格依据",
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
                _n(row["inherited_project_debt_yi"], 1),
                _n(row["network_acceleration_years"], 2) + "年",
                row["price_basis"],
            )
            for row in snapshot.mna_comparison
        ],
    )
    mna_debt_table = _table(
        ["方案", "纯自建项目债务", "收购承接项目债务", "换电项目合计债务", "对CATL的含义"],
        [
            (
                row["label"],
                _n(row["organic_project_debt_yi"], 1),
                _n(row["inherited_project_debt_yi"], 1),
                _n(row["total_project_debt_yi"], 1),
                "项目现金流续作和偿付；不是CATL交割日新增现金，除非存在追索或增信",
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
    _gap = verdicts["funding_gap"]
    executive_summary_rule = (
        f"中性假设下结论为 **{final_memo.status}**：建设期维持{_p(config['finance']['construction_ownership'], 0)}经济权益，"
        f"把需求反推的站网在{config['construction']['station_network_completion_year']}年以前建完；"
        f"CATL建设期累计资本调用约 **{_n(capex.catl_total_equity_call_yi, 1)}亿元**，"
        f"单年峰值约 **{_n(capex.catl_peak_equity_call_yi, 1)}亿元**。"
        f"{config['meta']['target_year']}E动力电池业务线价值约 **{_n(ledger.power_value_2030_with_swap_yi, 1)}亿元**；"
        f"其中可归因换电价值约 **{_n(ledger.total_swap_increment_value_yi, 1)}亿元**，"
        f"相当于当前宁德时代A+H市值的 **{_p(ledger.attributable_swap_value_to_current_group_market_cap)}**。"
        + ("集团当前资金模型**已出现流动性缺口**，若缺口扩大可能要求提前出表回笼现金；" if _gap
           else "集团当前资金模型不要求提前出表；")
        + "业务成熟后是否卖到30%、20%或10%，"
        "取决于届时明确资金需求与ABS/REITs市场承接能力，不预设固定最优档。"
    )
    executive_summary = llm_narrate(
        config, verdicts, "executive_summary", executive_summary_rule,
        {
            "status": final_memo.status,
            "catl_total_equity_call_yi": capex.catl_total_equity_call_yi,
            "catl_peak_equity_call_yi": capex.catl_peak_equity_call_yi,
            "power_value_2030_with_swap_yi": ledger.power_value_2030_with_swap_yi,
            "total_swap_increment_value_yi": ledger.total_swap_increment_value_yi,
            "attributable_swap_value_to_current_group_market_cap": ledger.attributable_swap_value_to_current_group_market_cap,
            "funding_gap": _gap,
        },
    )
    valuation_note = (
        f"运营{_x(config['finance']['swap_ev_ebitda'], 0)}不是从资管公司倍数照搬：基础设施/公用事业运营"
        "通常落在较低的EV/EBITDA区间，本报告在其上加入换电标准、电池供应和数据闭环的战略溢价。"
        "Blackstone、Ares等真GP倍数只用于说明资管平台的商业模式，不用于抬高底层换电资产估值。"
        "资管平台只有在资产已实际发行、收取管理费并承担持续管理职能后才确认价值。"
    )
    light_formula = (
        f"`净回款 = 费后项目权益价值 ×（{_p(config['finance']['construction_ownership'], 0)}－终局权益）"
        "×（1－交易成本率）`  \n"
        "`持续动力价值 = 制造价值 + 保留运营权益价值 + 资管平台价值`  \n"
        "`含回款后动力价值 = 持续动力价值 + 净回款`"
    )
    profit_retention_note = (
        "经常利润保留率可能略高于原值，原因是降低底层权益后，更多电池转为对SPV的外部制造销售，"
        "这不是把同一利润重复计算。基准情景的已确认资管AUM为零，因此没有凭空加入管理费利润；"
        "只有未来滚动发行形成真实AUM后，资管利润才进入向上情景。持续价值仍会因运营权益下降而减少，"
        "因此不能只看利润保留率下结论。"
    )
    funding_method_note = (
        f"资金起点使用{config['meta']['reference_year']}H1货币资金加交易性金融资产。"
        f"{config['meta']['reference_year']}本期原始CFO只取全年预测减已实现H1 CFO，避免重复。"
        "原始CFO独立依据历史CFO/净利润转化和预测输入，不由净利润直接代替；"
        f"分红按连续三年{_p(config['group_funding']['dividend_payout_ratio'], 0)}的习惯做全年储备；"
        "已宣告中期分红属于该储备的一部分，不再另扣一次。原始CFO再扣分红、回购、已识别并购和换电资本后，"
        "得到的是‘当年新增可投资资金’，而不是会计报表中的‘可用CFO’。"
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
    reference_year = config["meta"]["reference_year"]
    target_year = config["meta"]["target_year"]
    completion_year = config["construction"]["station_network_completion_year"]
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
        f"{config['vehicles']['city']['battery_life_years']:g}年电池首轮更新，没有新增站体。"
    )
    station_impact_explanation = (
        f"同样增加1,000站，骐骥EBITDA为正、巧克力为负，原因不是收入需求方向相反，而是单站电池库存差异："
        f"骐骥{config['stations']['heavy']['inventory_blocks']:g}×"
        f"{config['stations']['heavy']['block_kwh']:g}kWh带来的外部权益电池租金和套利可覆盖场租；"
        f"巧克力{config['stations']['choco']['inventory_blocks']:g}×"
        f"{config['stations']['choco']['block_kwh']:g}kWh的两项收入低于固定场租。"
        "上表把每个节点都拆出，避免将车辆增长误归因到站数。"
    )
    manager_capacity_note = (
        "中国当前ABS和公募REITs市场的年度承接量有限，而CATL换电终局资产规模很大。"
        f"基准把已确认AUM设为{config['light_asset']['recognized_manager_aum_yi']:g}；"
        + "/".join(
            f"{value:g}" for value in config["light_asset"]["rolling_manager_aum_scenarios_yi"]
            if value != config["light_asset"]["recognized_manager_aum_yi"]
        )
        + "亿元只是逐批发行后的向上情景。未出售、仍在项目公司表内的资产不能在第一天全部计入资管AUM。"
    )
    v32_audit_table = _table(
        ["模块", "参数", "v3.2主链", "v4.1当前", "核对结论", "原因/处理", "影响"],
        parameter_audit_rows(config, snapshot),
    )
    v32_outcome_audit_table = _table(
        ["拍板结果", "v3.2", "v4.1当前", "变化", "归因"],
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
        "manager_capacity_note": manager_capacity_note,
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
        "business_memo": _memo_text(memo_map["换电经营"]),
        "power_total_table": power_total_table,
        "bridge_table": bridge_table,
        "current_comparison_table": current_comparison_table,
        "ledger_memo": _memo_text(memo_map["动力电池总账"]),
        "valuation_method_table": valuation_method_table,
        "valuation_comparable_table": valuation_comparable_table,
        "valuation_note": valuation_note,
        "manager_table": manager_table,
        "manager_ramp_table": manager_ramp_table,
        "light_formula": light_formula,
        "light_transaction_table": light_transaction_table,
        "light_decision_table": light_decision_table,
        "profit_retention_note": profit_retention_note,
        "light_conclusion": light_conclusion,
        "light_memo": _memo_text(memo_map["成熟期资本循环"]),
        "funding_table": funding_table,
        "historical_cfo_table": historical_cfo_table,
        "funding_method_note": funding_method_note,
        "commitment_table": commitment_table,
        "commitment_method_note": commitment_method_note,
        "exposure_table": exposure_table,
        "light_support_table": light_support_table,
        "sensitivity_table": sensitivity_table,
        "funding_memo": _memo_text(memo_map["集团资金"]),
        "nio_fact_table": nio_fact_table,
        "nio_method_note": nio_method_note,
        "mna_input_table": mna_input_table,
        "mna_debt_table": mna_debt_table,
        "mna_bridge_table": mna_bridge_table,
        "v32_audit_table": v32_audit_table,
        "v32_outcome_audit_table": v32_outcome_audit_table,
        "memo_table": memo_table,
        "final_conclusion": _memo_text(final_memo),
    }
    template_path = ROOT / "templates" / "strategic_report.md.tpl"
    text = Template(template_path.read_text(encoding="utf-8")).substitute(values)
    _handle_consistency(validate_consistency(verdicts, text), config)
    return text


def write_outputs(
    config: dict,
    snapshot: ModelSnapshot,
    report_path: Path,
) -> dict[str, Path]:
    output_dir = ROOT / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = output_dir / "decision_snapshot_v4_1.json"
    registry_path = output_dir / "dashboard_parameter_registry_v4_1.json"
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

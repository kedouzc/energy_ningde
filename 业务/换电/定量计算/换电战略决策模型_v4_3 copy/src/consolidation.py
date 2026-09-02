from __future__ import annotations

from schemas import BaselineResult, ConsolidatedLedger, ManufacturingResult, SwapBusinessResult


def _cagr(end: float, begin: float, years: int) -> float:
    return (end / begin) ** (1 / years) - 1 if begin > 0 and end >= 0 else float("nan")


def build_consolidated_ledger(
    config: dict,
    baseline: BaselineResult,
    no_swap: ManufacturingResult,
    with_swap: ManufacturingResult,
    swap: SwapBusinessResult,
) -> ConsolidatedLedger:
    """只合并动力电池业务线；不外推储能、AIDC等未研究分部。"""
    pe = config["finance"]["manufacturing_pe"]
    margin_delta = with_swap.net_margin - no_swap.net_margin

    power_np_no = no_swap.net_profit_yi
    power_np_with = with_swap.net_profit_yi + swap.catl_attributable_net_profit_yi
    power_value_no = no_swap.equity_value_yi
    power_value_with = with_swap.equity_value_yi + swap.catl_attributable_value_yi

    # 制造线情景差额拆成三个可读零件，三项之和必须等于有换电制造－纯制造。
    volume_share_np = (with_swap.revenue_yi - no_swap.revenue_yi) * no_swap.net_margin
    # 量差再拆两层：换电段+更换循环的锁定订单（部分归因、计入换电主值）；
    # 充电段份额净效应（依赖“数据反哺充电份额”长链条，证据最弱，只进敏感性）。
    unit_price = (
        with_swap.revenue_yi * 100.0 / with_swap.shipments_gwh
        if with_swap.shipments_gwh else 0.0
    )
    swap_locked_np = (
        with_swap.swap_locked_gwh * unit_price / 100.0 * no_swap.net_margin
    )
    charge_share_np = volume_share_np - swap_locked_np
    swap_margin_np = with_swap.swap_addressable_revenue_yi * margin_delta
    other_revenue = max(0.0, with_swap.revenue_yi - with_swap.swap_addressable_revenue_yi)
    other_margin_np = other_revenue * margin_delta
    full_mfg_np_gap = with_swap.net_profit_yi - no_swap.net_profit_yi
    full_mfg_value_gap = full_mfg_np_gap * pe

    direct_np = swap.catl_attributable_net_profit_yi
    direct_value = swap.catl_attributable_value_yi
    # 换电主值=制造线全口径净利增量×PE + 运营40%权益价值。
    # 制造净利增量已综合量(锁单+虹吸)与价(利润率保护)。
    # 虹吸是换电对充电的真实量影响，必须随制造线一起×PE放大；
    # 运营单体计的是网络运营EBITDA(存量/现金流)，制造计的是电池销售损益(流量)，估值基础不同，
    # 不存在"运营已计→制造剔除"的双算。原口径剔除虹吸会虚高1,153亿。
    total_np_increment = full_mfg_np_gap + direct_np
    total_value_increment = full_mfg_value_gap + direct_value
    full_np_gap = power_np_with - power_np_no
    full_value_gap = power_value_with - power_value_no

    bridge_error = full_mfg_np_gap - volume_share_np - swap_margin_np - other_margin_np
    year_gap = config["meta"]["target_year"] - config["meta"]["reference_year"]
    current_group_value = baseline.group_market_value_2026e_yi
    return ConsolidatedLedger(
        baseline=baseline,
        no_swap_manufacturing=no_swap,
        with_swap_manufacturing=with_swap,
        swap_business=swap,
        power_net_profit_2030_no_swap_yi=power_np_no,
        power_net_profit_2030_with_swap_yi=power_np_with,
        power_value_2030_no_swap_yi=power_value_no,
        power_value_2030_with_swap_yi=power_value_with,
        manufacturing_volume_share_effect_net_profit_yi=volume_share_np,
        manufacturing_volume_share_effect_value_yi=volume_share_np * pe,
        manufacturing_swap_locked_volume_effect_net_profit_yi=swap_locked_np,
        manufacturing_swap_locked_volume_effect_value_yi=swap_locked_np * pe,
        manufacturing_charge_share_effect_net_profit_yi=charge_share_np,
        manufacturing_charge_share_effect_value_yi=charge_share_np * pe,
        manufacturing_swap_margin_effect_net_profit_yi=swap_margin_np,
        manufacturing_swap_margin_effect_value_yi=swap_margin_np * pe,
        manufacturing_other_margin_effect_net_profit_yi=other_margin_np,
        manufacturing_other_margin_effect_value_yi=other_margin_np * pe,
        full_manufacturing_scenario_gap_net_profit_yi=full_mfg_np_gap,
        full_manufacturing_scenario_gap_value_yi=full_mfg_value_gap,
        direct_swap_increment_net_profit_yi=direct_np,
        direct_swap_increment_value_yi=direct_value,
        total_swap_increment_net_profit_yi=total_np_increment,
        total_swap_increment_value_yi=total_value_increment,
        full_with_vs_pure_manufacturing_gap_net_profit_yi=full_np_gap,
        full_with_vs_pure_manufacturing_gap_value_yi=full_value_gap,
        power_value_growth_vs_2026_modeled_yi=(
            power_value_with - baseline.modeled_power_market_value_2026e_yi
        ),
        power_value_multiple_vs_2026_modeled=(
            power_value_with / baseline.modeled_power_market_value_2026e_yi
        ),
        power_value_growth_vs_2026_allocated_yi=(
            power_value_with - baseline.power_market_value_2026e_yi
        ),
        power_value_multiple_vs_2026_allocated=(
            power_value_with / baseline.power_market_value_2026e_yi
        ),
        attributable_swap_value_to_2026_modeled_power_value=(
            total_value_increment / baseline.modeled_power_market_value_2026e_yi
        ),
        attributable_swap_value_to_2026_allocated_power_value=(
            total_value_increment / baseline.power_market_value_2026e_yi
        ),
        attributable_swap_value_to_current_group_market_cap=total_value_increment / current_group_value,
        full_gap_to_current_group_market_cap=full_value_gap / current_group_value,
        power_value_cagr_2026_to_2030=_cagr(
            power_value_with, baseline.power_market_value_2026e_yi, year_gap
        ),
        value_bridge_error_yi=bridge_error,
    )

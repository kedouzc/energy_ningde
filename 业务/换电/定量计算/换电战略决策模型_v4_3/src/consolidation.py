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
        # 2026-09-12 从 lab.py 下沉：合并增量价值（业务整体口径）
        # = 运营项目权益价值(100%) + 制造侧增量价值；归属股东口径见 total_swap_increment_value_yi
        combined_increment_value_yi=swap.project_equity_value_yi + full_mfg_value_gap,
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
        **_per_share(config, current_group_value, total_value_increment, year_gap),
    )


def _per_share(
    config: dict, base_cap_yi: float, increment_yi: float, year_gap: float
) -> dict[str, float]:
    """【2026-09-18b】把"增量价值"折成每股，作为调仓的刻度。

    为什么必须做这一步：第 8 章原来只判断资本端"有没有定价"，那是个是非题；
    要决定**加多少、在什么价位加**，就得把亿元换算成元/股，和屏幕上的价格放在同一个数轴上。

    三条口径必须写死，否则这个数会被误用：
    1. **增量价值是兑现年时点口径**（运营侧＝兑现年 EBITDA × 倍数，制造侧＝兑现年净利 × PE），
       没有折回今天。所以目标价是**兑现年的价**，不能直接和今天的股价比"空间"，
       只能比**年化回报**——那才是可以和机会成本对齐的量。
    2. **基准每股假定主业价值不变**，即这段时间里除换电以外什么都没发生。这是"世界 A"的
       静态基准，不是主业预测；主业自身的增减不在本模型的解释范围内。
    3. **每股按总股本摊**，但 A 股与 H 股同股不同价（H 对 A 溢价约五成）。同一个
       "每股增量价值"落到两个市场上，占各自股价的比例不同——用在哪个市场就取哪个现价。
    """
    fin = config.get("financial_2026e") or {}
    shares = float(fin.get("total_shares_yi") or 0.0)
    spot = float(fin.get("spot_price_a_rmb") or 0.0)
    if shares <= 0:
        return {}
    base_ps = base_cap_yi / shares
    incr_ps = increment_yi / shares
    target_ps = base_ps + incr_ps
    out = {
        "base_price_per_share": base_ps,
        "increment_per_share": incr_ps,
        "target_price_per_share": target_ps,
    }
    if spot > 0 and target_ps:
        out["upside_over_spot_pct"] = (target_ps / spot - 1.0) * 100.0
        # 安全边际：现价相对兑现年目标价的折让，是"还能跌多少才不亏"的刻度
        out["margin_of_safety_pct"] = (1.0 - spot / target_ps) * 100.0
        if year_gap > 0:
            out["annualized_to_target_pct"] = (
                (target_ps / spot) ** (1.0 / year_gap) - 1.0
            ) * 100.0
        # 现价相对基准每股的折让。**它不是"换电被定价了多少"**——基准本身就是市场自己的报价，
        # 里面已经含着市场对换电的任何看法，无法从价格里单独剥离出来。能读的只有：
        # 现价相对这一季的自身均值偏离多少，也就是"买点相对基准便宜还是贵"。
        out["discount_to_base_pct"] = (spot / base_ps - 1.0) * 100.0 if base_ps else 0.0
    return out

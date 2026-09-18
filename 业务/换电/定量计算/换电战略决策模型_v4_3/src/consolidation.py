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
        **_per_share(config, current_group_value, total_value_increment, year_gap,
                     float(getattr(swap, "dcf_ke_derived", 0.0) or 0.0)),
    )


def _per_share(
    config: dict, base_cap_yi: float, increment_yi: float, year_gap: float, ke: float = 0.0
) -> dict[str, float]:
    """【2026-09-18d 重写】把"增量价值"折成每股——**分市场各算各的，不混算**。

    为什么必须分开（上一版的错）：A 股与 H 股同股不同价（H 对 A 溢价约五成）。
    "合计市值 ÷ 总股本"得到的是一个**混合价**，它既不是 A 股的价、也不是 H 股的价，
    拿它跟任一市场的现价比空间，比的是两个不存在的东西。
    **能加总的是价值，不能加总的是价格**——这与分部估值是同一条纪律。

    正确的做法：
    - 市值：A 股股本 × A 股价 ＋ H 股股本 × H 股价 × 汇率，**先分后合**；
    - 每股增量：增量价值 ÷ **总股本**（同一份股东权益，两地同权，这一项确实该按总股本摊）；
    - 目标价：各自的基准价 ＋ 每股增量（H 股按汇率折回港元），**两个市场各得一个目标价**。

    "几年几倍"的口径（2026-09-18d 按研究者的框架改）：
    除换电以外的业务都是可线性外推的，**当前市值已经是市场对它们的有效定价**，
    所以不需要"假定主业价值不变"这个说法——那是把一个定价事实说成了假设。
    换电当前被当作零（第 7 章三条外部观察），因此它是**纯增量**：
        纯增量倍数 ＝ 1 ＋ 增量价值 ÷ 当前市值
    唯一要补的严谨性是**时点**：增量是兑现年的价值，当前市值是今天的价格。
    所以同时给出折现口径（按本报告隐含股权成本折回今天），两个数一起看：
    **不折现的倍数回答"到那一年能变成几倍"，折现的倍数回答"今天该为它付多少"。**
    """
    fin = config.get("financial_2026e") or {}
    shares = float(fin.get("total_shares_yi") or 0.0)
    a_sh = float(fin.get("a_shares_yi") or 0.0)
    h_sh = float(fin.get("h_shares_yi") or 0.0)
    a_avg = float(fin.get("a_price_avg_rmb") or 0.0)
    h_avg = float(fin.get("h_price_avg_hkd") or 0.0)
    fx = float(fin.get("hkd_to_cny") or 0.0)
    spot_a = float(fin.get("spot_price_a_rmb") or 0.0)
    spot_h = float(fin.get("spot_price_h_hkd") or 0.0)
    if shares <= 0 or a_sh <= 0 or h_sh <= 0 or fx <= 0:
        return {}

    out: dict[str, float] = {
        "mktcap_a_yi": a_sh * a_avg,
        "mktcap_h_yi": h_sh * h_avg * fx,
    }
    out["mktcap_ah_yi"] = out["mktcap_a_yi"] + out["mktcap_h_yi"]
    # 每股增量按总股本摊——两地同股同权，增量价值不区分在哪个市场上市
    incr_ps = increment_yi / shares
    out["increment_per_share"] = incr_ps
    out["target_price_a"] = a_avg + incr_ps
    out["target_price_h_hkd"] = h_avg + incr_ps / fx

    def _leg(tag: str, spot: float, target: float) -> None:
        if spot <= 0 or target <= 0:
            return
        out[f"upside_{tag}_pct"] = (target / spot - 1.0) * 100.0
        out[f"margin_of_safety_{tag}_pct"] = (1.0 - spot / target) * 100.0
        if year_gap > 0:
            out[f"annualized_{tag}_pct"] = ((target / spot) ** (1.0 / year_gap) - 1.0) * 100.0

    _leg("a", spot_a, out["target_price_a"])
    _leg("h", spot_h, out["target_price_h_hkd"])

    # 纯增量倍数：当前市值已有效定价了可线性外推的业务，换电被当作零，所以它是纯加项
    if base_cap_yi > 0:
        out["pure_multiple"] = 1.0 + increment_yi / base_cap_yi
        if ke > 0 and year_gap > 0:
            pv = increment_yi / (1.0 + ke) ** year_gap
            out["increment_pv_yi"] = pv
            out["pure_multiple_pv"] = 1.0 + pv / base_cap_yi
    return out

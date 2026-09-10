from __future__ import annotations

from business import build_manufacturing_cases
from schemas import CapexResult, ConsolidatedLedger, LightAssetScenario, ScaleResult, SwapBusinessResult


def strategic_exposure_total(config: dict) -> float:
    return sum(
        item["full_newbuild_capex_yi"] * (1.0 - item["assumed_reuse_rate"])
        for item in config["strategic_exposure"].values()
    )


def _future_catl_capital(config: dict, capex: CapexResult, ownership: float) -> float:
    target_year = config["meta"]["target_year"]
    wacc = config["finance"]["wacc"]
    equity_share = 1.0 - config["finance"]["debt_ratio"]
    return sum(
        amount / ((1 + wacc) ** (year - target_year)) * equity_share * ownership
        for year, amount in capex.lifecycle_replacement_schedule_yi.items()
        if year > target_year
    )


def _decision_role(
    ownership: float,
    current: float,
    options: list[float],
) -> str:
    if ownership == current:
        return "基准终局：资金不短缺时不出表"
    sold = current - ownership
    if sold <= 0.10 + 1e-9:
        return "低强度资产循环：少卖、保留较多持续价值"
    if sold <= 0.20 + 1e-9:
        return "中强度资产循环：回款与持续价值居中"
    return "高强度资产循环：资金需求大时多卖"


def build_light_asset_scenarios(
    config: dict,
    scale: ScaleResult,
    capex: CapexResult,
    swap: SwapBusinessResult,
    ledger: ConsolidatedLedger,
) -> list[LightAssetScenario]:
    finance = config["finance"]
    current = finance["construction_ownership"]
    controls = config["light_asset"]
    control_ok = all((
        controls["data_control_required"],
        controls["standard_control_required"],
        controls["technology_validation_access_required"],
    ))
    current_future_capital = _future_catl_capital(config, capex, current)
    pre_power_profit = ledger.power_net_profit_2030_with_swap_yi
    pre_power_value = ledger.power_value_2030_with_swap_yi
    scenarios: list[LightAssetScenario] = []

    for ownership in controls["terminal_ownership_options"]:
        sold = max(0.0, current - ownership)
        if sold > 0:
            # 基准只确认已经滚动发行、实际进入管理平台的AUM；不把全项目EV在第一天
            # 一次性认作AUM。当前中性值为0，资管价值留作发行爬坡的向上情景。
            managed_aum = min(
                controls["recognized_manager_aum_yi"],
                swap.enterprise_value_yi,
            )
            manager_fee_revenue = managed_aum * finance["manager_fee_rate"]
            manager_np = manager_fee_revenue * finance["manager_net_margin"]
            manager_value = manager_np * finance["manager_pe"]
            post_fee_project_ev = max(
                0.0,
                (swap.ebitda_yi - manager_fee_revenue)
                * finance["swap_ev_ebitda"],
            )
            post_fee_project_equity = max(
                0.0, post_fee_project_ev - capex.project_debt_yi
            )
            project_np_after_fee = max(
                0.0,
                swap.project_net_profit_yi
                - manager_fee_revenue * (1 - finance["tax_rate"]),
            )
        else:
            managed_aum = swap.enterprise_value_yi
            manager_fee_revenue = 0.0
            manager_np = 0.0
            manager_value = 0.0
            post_fee_project_equity = swap.project_equity_value_yi
            project_np_after_fee = swap.project_net_profit_yi

        sale_gross = post_fee_project_equity * sold
        sale_net = sale_gross * (1 - finance["transaction_cost_rate"])
        retained_operating_value = post_fee_project_equity * ownership
        post_operating_profit = project_np_after_fee * ownership + manager_np

        _, manufacturing = build_manufacturing_cases(
            config, scale, capex, terminal_ownership=ownership
        )
        post_power_profit = manufacturing.net_profit_yi + post_operating_profit
        post_power_value_ex_cash = (
            manufacturing.equity_value_yi + retained_operating_value + manager_value
        )
        post_power_value_with_cash = post_power_value_ex_cash + sale_net
        persistent_delta = post_power_value_ex_cash - pre_power_value
        cash_delta = post_power_value_with_cash - pre_power_value
        lost = -persistent_delta
        scenarios.append(LightAssetScenario(
            terminal_ownership=ownership,
            sale_proceeds_gross_yi=sale_gross,
            sale_proceeds_net_yi=sale_net,
            managed_aum_yi=managed_aum,
            manager_fee_revenue_yi=manager_fee_revenue,
            manager_net_profit_yi=manager_np,
            manager_value_yi=manager_value,
            retained_operating_value_yi=retained_operating_value,
            post_exit_recurring_profit_yi=post_power_profit,
            recurring_profit_retention=post_power_profit / pre_power_profit,
            post_exit_power_value_ex_cash_yi=post_power_value_ex_cash,
            post_exit_power_value_including_cash_yi=post_power_value_with_cash,
            sustainable_value_retention=post_power_value_ex_cash / pre_power_value,
            persistent_power_value_delta_yi=persistent_delta,
            including_cash_power_value_delta_yi=cash_delta,
            cash_per_persistent_value_lost=sale_net / lost if lost > 0 else None,
            future_catl_capital_released_yi=(
                current_future_capital - _future_catl_capital(config, capex, ownership)
            ),
            data_control_ok=control_ok,
            decision_role=_decision_role(
                ownership, current, controls["terminal_ownership_options"]
            ),
        ))
    return scenarios


def reit_recycle_multiple(
    config: dict,
    scale: ScaleResult | None = None,
    capex: CapexResult | None = None,
    swap: SwapBusinessResult | None = None,
    ledger: ConsolidatedLedger | None = None,
) -> float | None:
    """发行 REITs / 资产出表可回笼资金 ÷ CATL 初装权益投入（=回笼倍数）。

    取资本循环模型「退出后保留 20% 股权」情景的净回款（与 v3.2 §5.1 口径一致）。
    计算失败或投资为 0 返回 None（页面标待补，不崩）。

    scale/capex/swap/ledger 由调用方传入（sandbox 已 build_model 一次，直接喂结果，
    不重复建模型）；缺省则内部惰性 build_model 兜底（仅历史兼容，不推荐重复建）。
    """
    if scale is None or capex is None or swap is None or ledger is None:
        from model import build_model  # 惰性，避免 capital_cycle↔model 顶层循环导入
        snap = build_model(config)
        scale = scale or snap.scale
        capex = capex or snap.capex
        swap = swap or snap.swap_business
        ledger = ledger or snap.ledger
    scs = build_light_asset_scenarios(config, scale, capex, swap, ledger)
    target = next((s for s in scs if abs(s.terminal_ownership - 0.20) < 1e-9), None)
    if target is None:
        target = min(scs, key=lambda s: s.terminal_ownership)
    inv = swap.catl_initial_equity_investment_yi
    if inv:
        return round(target.sale_proceeds_net_yi / inv, 2)
    return None

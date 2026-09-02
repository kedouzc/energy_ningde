from __future__ import annotations

from schemas import CapexResult, FundingRow, SourcingAdjustment


def build_capital_commitments(config: dict) -> list[dict]:
    """保留披露边界：未明确实缴时点或不在合并口径的事项不硬塞进年度现金流。"""
    return [item.copy() for item in config["capital_commitments"]]


def build_funding_envelope(
    config: dict,
    capex: CapexResult,
    sourcing: SourcingAdjustment,
) -> list[FundingRow]:
    funding = config["group_funding"]
    years = config["construction"]["years"]
    capex_by_year = {row.year: row for row in capex.annual}
    liquid_resources = funding["initial_cash_and_trading_assets_yi"]
    rows: list[FundingRow] = []

    for index, year in enumerate(years):
        full_year_cfo = funding["projected_group_cfo_yi"][index]
        available_cfo = (
            full_year_cfo - funding["reported_2026h1_cfo_yi"]
            if index == 0 else full_year_cfo
        )
        net_profit = funding["projected_group_net_profit_yi"][index]
        dividend_ratio = funding["dividend_payout_ratio"]
        dividend = net_profit * dividend_ratio
        buyback = funding["buyback_yi"][index]
        known_mna = funding["known_catl_direct_mna_cash_yi"][index]
        if index == 0:
            known_mna += sourcing.cash_consideration_yi
        swap_call = capex_by_year[year].catl_equity_call_yi
        liquid_resources += available_cfo - dividend - buyback - known_mna - swap_call
        rows.append(FundingRow(
            year=year,
            projected_net_profit_yi=net_profit,
            available_cfo_yi=available_cfo,
            dividend_payout_ratio=dividend_ratio,
            dividend_reserve_yi=dividend,
            buyback_reserve_yi=buyback,
            known_direct_mna_cash_yi=known_mna,
            swap_equity_call_yi=swap_call,
            ending_liquid_resources_before_uncommitted_strategy_yi=liquid_resources,
            headroom_above_liquidity_floor_yi=(
                liquid_resources - funding["minimum_liquidity_yi"]
            ),
            swap_cash_to_cfo=swap_call / available_cfo if available_cfo else float("inf"),
        ))
    return rows

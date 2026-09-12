from __future__ import annotations

from schemas import CapexResult, FundingRow, SourcingAdjustment


def build_capital_commitments(config: dict) -> list[dict]:
    """保留披露边界：未明确实缴时点或不在合并口径的事项不硬塞进年度现金流。"""
    return [item.copy() for item in config["capital_commitments"]]


def funding_peak_cash_to_cfo(rows: list[FundingRow]) -> float:
    """换电出资峰值 ÷ CFO：整条资金包络里**最吃紧的那一年**。

    2026-09-12 从 lab.py 下沉——它读的是本模块产出的资金包络，
    理应由本模块回答"哪一年最紧"，而不是让取数层去遍历。
    """
    return max((row.swap_cash_to_cfo for row in rows), default=float("nan"))


def funding_closing_liquidity(rows: list[FundingRow]) -> float:
    """期末可动用资金（未计入待决战略敞口前）。"""
    return (
        rows[-1].closing_liquid_resources_before_uncommitted_strategy_yi
        if rows else float("nan")
    )


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
        opening_liquid_resources = liquid_resources
        full_year_cfo = funding["projected_group_cfo_yi"][index]
        period_cfo = (
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
        annual_investable_funds = (
            period_cfo - dividend - buyback - known_mna - swap_call
        )
        liquid_resources += annual_investable_funds
        rows.append(FundingRow(
            year=year,
            opening_liquid_resources_yi=opening_liquid_resources,
            projected_net_profit_yi=net_profit,
            period_cfo_yi=period_cfo,
            dividend_payout_ratio=dividend_ratio,
            dividend_reserve_yi=dividend,
            buyback_reserve_yi=buyback,
            known_direct_mna_cash_yi=known_mna,
            swap_equity_call_yi=swap_call,
            annual_investable_funds_generated_yi=annual_investable_funds,
            closing_liquid_resources_before_uncommitted_strategy_yi=liquid_resources,
            minimum_liquidity_reserve_yi=funding["minimum_liquidity_yi"],
            funds_reserved_for_other_strategy_yi=(
                liquid_resources - funding["minimum_liquidity_yi"]
            ),
            swap_cash_to_cfo=swap_call / period_cfo if period_cfo else float("inf"),
        ))
    return rows

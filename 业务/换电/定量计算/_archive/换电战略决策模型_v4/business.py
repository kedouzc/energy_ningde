from __future__ import annotations

from derived import battery_price_rmb_kwh
from schemas import (
    BaselineResult,
    CapexResult,
    ManufacturingResult,
    ScaleResult,
    SwapBusinessResult,
)


def build_2026_baseline(config: dict) -> BaselineResult:
    h1 = config["financial_2026h1"]
    estimate = config["financial_2026e"]
    power_gross_profit = h1["power_battery_revenue_yi"] * h1["power_battery_gross_margin"]
    group_gross_profit = h1["group_revenue_yi"] * h1["group_gross_margin"]
    power_share = power_gross_profit / group_gross_profit
    group_np = estimate["group_net_profit_consensus_yi"]
    group_value = estimate["group_market_cap_ah_yi"]
    power_np = group_np * power_share
    power_value = group_value * power_share
    modeled_revenue = (
        estimate["power_battery_shipments_gwh"]
        * battery_price_rmb_kwh(config, config["meta"]["reference_year"])
        / 100.0
    )
    modeled_np = modeled_revenue * config["swap_business"]["with_swap_manufacturing_net_margin"]
    modeled_value = modeled_np * config["finance"]["manufacturing_pe"]
    power_revenue = config["financial_2025a"]["power_battery_revenue_yi"] * (
        1.0 + h1["power_battery_revenue_yoy"]
    )
    return BaselineResult(
        power_gross_profit_share=power_share,
        power_revenue_2026e_yi=power_revenue,
        power_net_profit_2026e_yi=power_np,
        power_market_value_2026e_yi=power_value,
        modeled_power_net_profit_2026e_yi=modeled_np,
        modeled_power_market_value_2026e_yi=modeled_value,
        non_power_net_profit_2026e_yi=group_np - power_np,
        non_power_market_value_2026e_yi=group_value - power_value,
        group_net_profit_2026e_yi=group_np,
        group_market_value_2026e_yi=group_value,
        implied_group_pe=group_value / group_np,
    )


def build_swap_business(config: dict, scale: ScaleResult, capex: CapexResult) -> SwapBusinessResult:
    business = config["swap_business"]
    finance = config["finance"]
    annual_energy = sum(scale.mature_annual_energy_yi_kwh.values())
    service = annual_energy * business["service_fee_rmb_kwh"]
    cumulative_vehicle_gwh = sum(scale.annual_catl_swap_gwh.values())
    station_battery_gwh = 0.0
    for group, station_count in capex.station_targets.items():
        station = config["stations"][group]
        station_battery_gwh += station_count * station["inventory_blocks"] * station["block_kwh"] / 1e6
    # 电池租金只向车端在运营电池资产收取。站内周转库存是同一换电体系的
    # 备货资产，若在项目合并口径下再次计租，会把内部占用误记成外部收入。
    rent_gwh = cumulative_vehicle_gwh
    battery_rent = rent_gwh * business["battery_rent_rmb_kwh_year"] / 100.0
    arbitrage = (
        station_battery_gwh * business["operating_days"] * business["grid_spread_rmb_kwh"]
        * business["rte"] / 100.0
    )
    ancillary = business["ancillary_revenue_yi_year"]
    revenue = service + battery_rent + arbitrage + ancillary

    charged_energy = annual_energy / business["rte"] * (1 + business["auxiliary_power_rate"])
    loss_energy = charged_energy - annual_energy
    energy_cost = loss_energy * business["valley_power_price_rmb_kwh"]
    station_rent = sum(capex.station_targets.values()) * business["site_rent_wan_year"] / 1e4
    labor = 0.0
    for row in scale.rows:
        annual_swaps = (
            row.catl_swap_vehicles_wan * 1e4 * row.swap_frequency_per_day
            * business["operating_days"]
        )
        unit_cost = business["heavy_labor_rmb_swap"] if row.station_group == "heavy" else business["passenger_labor_rmb_swap"]
        labor += annual_swaps * unit_cost / 1e8
    opex = energy_cost + station_rent + labor + business["software_opex_yi_year"]
    ebitda = revenue - opex
    depreciation = capex.mature_annual_depreciation_yi
    ebit = ebitda - depreciation
    interest = capex.project_debt_yi * finance["debt_interest_rate"]
    project_np = max(0.0, ebit - interest) * (1 - finance["tax_rate"])
    catl_np = project_np * finance["construction_ownership"]
    ev = ebitda * finance["swap_ev_ebitda"]
    equity_value = max(0.0, ev - capex.project_debt_yi)
    catl_value = equity_value * finance["construction_ownership"]
    required_ebitda = max(
        0.0,
        (capex.annual_capital_requirement_yi - depreciation * finance["tax_rate"])
        / (1 - finance["tax_rate"]),
    )
    return SwapBusinessResult(
        revenue_yi=revenue,
        service_revenue_yi=service,
        battery_rent_yi=battery_rent,
        arbitrage_yi=arbitrage,
        ancillary_yi=ancillary,
        opex_yi=opex,
        ebitda_yi=ebitda,
        depreciation_yi=depreciation,
        ebit_yi=ebit,
        project_net_profit_yi=project_np,
        catl_attributable_net_profit_yi=catl_np,
        enterprise_value_yi=ev,
        project_equity_value_yi=equity_value,
        catl_attributable_value_yi=catl_value,
        required_ebitda_yi=required_ebitda,
        forward_to_required_ebitda=ebitda / required_ebitda if required_ebitda else float("inf"),
    )


def build_manufacturing_cases(
    config: dict,
    scale: ScaleResult,
    capex: CapexResult,
    terminal_ownership: float | None = None,
) -> tuple[ManufacturingResult, ManufacturingResult]:
    years = scale.years
    target = years[-1]
    business = config["swap_business"]
    no_swap_gwh = scale.annual_catl_no_swap_gwh[target]
    external_share = (
        business["swap_battery_external_sales_share"]
        if terminal_ownership is None else 1.0 - terminal_ownership
    )
    replacement_gwh = next(
        row.vehicle_replacement_gwh for row in capex.annual if row.year == target
    )
    with_swap_gwh = (
        scale.annual_catl_charge_gwh[target]
        + (scale.annual_catl_swap_gwh[target] + replacement_gwh) * external_share
    )
    price = battery_price_rmb_kwh(config, target)
    pe = config["finance"]["manufacturing_pe"]

    def make(label: str, gwh: float, margin: float, addressable_revenue: float = 0.0) -> ManufacturingResult:
        revenue = gwh * price / 100.0
        net_profit = revenue * margin
        return ManufacturingResult(
            label=label,
            shipments_gwh=gwh,
            revenue_yi=revenue,
            net_margin=margin,
            net_profit_yi=net_profit,
            equity_value_yi=net_profit * pe,
            swap_addressable_revenue_yi=addressable_revenue,
        )

    # 本报告只建模道路电动车场景；有换电制造收入全部属于该场景的定价权保护范围。
    addressable_revenue = with_swap_gwh * price / 100.0
    return (
        make("2030E无换电纯制造", no_swap_gwh, business["no_swap_manufacturing_net_margin"]),
        make(
            "2030E重资产换电",
            with_swap_gwh,
            business["with_swap_manufacturing_net_margin"],
            addressable_revenue,
        ),
    )

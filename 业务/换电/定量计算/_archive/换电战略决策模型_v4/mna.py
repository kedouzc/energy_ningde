from __future__ import annotations

from schemas import SourcingAdjustment


def get_sourcing_adjustment(config: dict, scenario_name: str | None = None) -> SourcingAdjustment:
    scenarios = config["mna"]["scenarios"]
    selected = scenarios[0] if scenario_name is None else next(
        item for item in scenarios if item["name"] == scenario_name
    )
    return SourcingAdjustment(
        name=selected["name"],
        label=selected["label"],
        purchase_price_yi=selected["purchase_price_yi"],
        assumed_debt_yi=selected["assumed_debt_yi"],
        integration_cost_yi=selected["integration_cost_yi"],
        heavy_share_uplift=selected["heavy_catl_swap_share_uplift"],
        passenger_share_uplift=selected["passenger_catl_swap_share_uplift"],
        reusable_heavy_stations=selected["physically_reusable_heavy_stations"],
        reusable_choco_stations=selected["physically_reusable_choco_stations"],
        acceleration_years=selected["network_acceleration_years"],
        acquired_network_stations=selected["acquired_network_stations"],
        acquired_battery_bank_gwh=selected["acquired_battery_bank_gwh"],
        price_basis=selected["price_basis"],
        price_status=selected["price_status"],
    )

from __future__ import annotations

import math

from derived import station_capacity, swap_frequency_per_day
from schemas import ScaleResult, ScaleRow, SourcingAdjustment


def _operating_stocks(config: dict) -> dict[str, float]:
    d = config["operating_demand"]
    robotaxi_km = d["robotaxi_fleet_wan"] * d["robotaxi_daily_km"] * d["robotaxi_days"] / 1e4
    human_stock = (d["pool_2030_yi_km"] - robotaxi_km) / (
        d["human_daily_km"] * d["human_days"] / 1e4
    )
    return {"taxi": d["taxi_stock_wan"], "ridehail": human_stock - d["taxi_stock_wan"]}


def _annual_ev_wan(vehicle: dict, year_index: int, stocks: dict[str, float]) -> float:
    pure = vehicle.get("pure_electric_share", 1.0)
    if "annual_net_additions_wan" in vehicle:
        return vehicle["annual_net_additions_wan"][year_index] * pure
    stock = stocks[vehicle["stock_source"]] if "stock_source" in vehicle else vehicle["stock_wan"]
    return stock / vehicle["replacement_cycle_years"] * vehicle["nev_rates"][year_index] * pure


def build_scale(config: dict, sourcing: SourcingAdjustment) -> ScaleResult:
    years = config["construction"]["years"]
    stocks = _operating_stocks(config)
    rows: list[ScaleRow] = []
    operating_stock: dict[str, float] = {}
    annual_swap = {year: 0.0 for year in years}
    annual_charge = {year: 0.0 for year in years}
    annual_no_swap = {year: 0.0 for year in years}
    identity_error = 0.0

    for key, vehicle in config["vehicles"].items():
        operating_stock[key] = 0.0
        share_uplift = sourcing.heavy_share_uplift if vehicle["station_group"] == "heavy" else sourcing.passenger_share_uplift
        existing_stock = vehicle.get("existing_catl_swap_stock_wan", 0.0)
        existing_weights = [
            scene["weight"] * scene["swap_penetration"] * scene["catl_swap_share"]
            for scene in vehicle["scenes"]
        ]
        existing_weight_sum = sum(existing_weights)
        for year_index, year in enumerate(years):
            annual_ev = _annual_ev_wan(vehicle, year_index, stocks)
            for scene_index, scene in enumerate(vehicle["scenes"]):
                ev = annual_ev * scene["weight"]
                swap_penetration = scene["swap_penetration"]
                charge_penetration = 1.0 - swap_penetration
                identity_error = max(identity_error, abs(swap_penetration + charge_penetration - 1.0))
                catl_swap_share = min(1.0, scene["catl_swap_share"] + share_uplift)
                market_swap = ev * swap_penetration
                market_charge = ev * charge_penetration
                catl_swap = market_swap * catl_swap_share
                catl_charge = market_charge * scene["catl_charge_share"]
                catl_no_swap = ev * vehicle["no_swap_catl_share"]
                # 已有CATL换电存量不是本年新车漏斗，按原场景构成分摊到首年累计底座。
                if year_index == 0 and existing_stock and existing_weight_sum:
                    existing_scene_stock = (
                        existing_stock * existing_weights[scene_index] / existing_weight_sum
                    )
                    ev += existing_scene_stock
                    market_swap += existing_scene_stock
                    catl_swap += existing_scene_stock
                gwh_factor = vehicle["battery_kwh"] / 100.0
                frequency = swap_frequency_per_day(
                    vehicle, scene, config["swap_business"]["usable_energy_factor"]
                )
                daily_km = scene["daily_km"] if "daily_km" in scene else vehicle["daily_km"]
                row = ScaleRow(
                    year=year,
                    vehicle_key=key,
                    vehicle_label=vehicle["label"],
                    scene=scene["name"],
                    station_group=vehicle["station_group"],
                    ev_vehicles_wan=ev,
                    market_swap_vehicles_wan=market_swap,
                    market_charge_vehicles_wan=market_charge,
                    catl_swap_vehicles_wan=catl_swap,
                    catl_charge_vehicles_wan=catl_charge,
                    catl_no_swap_vehicles_wan=catl_no_swap,
                    catl_swap_gwh=catl_swap * gwh_factor,
                    catl_charge_gwh=catl_charge * gwh_factor,
                    catl_no_swap_gwh=catl_no_swap * gwh_factor,
                    battery_kwh=vehicle["battery_kwh"],
                    swap_frequency_per_day=frequency,
                    daily_km=daily_km,
                    usable_range_km=daily_km / frequency,
                    battery_life_years=vehicle["battery_life_years"],
                )
                rows.append(row)
                operating_stock[key] += catl_swap
                annual_swap[year] += row.catl_swap_gwh
                annual_charge[year] += row.catl_charge_gwh
                annual_no_swap[year] += row.catl_no_swap_gwh

    # “毛估估”取整发生在终局车型节点，而不是在漏斗每一层反复取整。
    # 这样既能消除无意义尾差，也不会重演v3把56.25先取57后层层放大的复合偏差。
    vehicle_decimals = config["modeling"]["rounding"]["terminal_vehicle_decimals"]
    frequency_decimals = config["modeling"]["rounding"]["terminal_frequency_decimals"]
    daily_swaps = {"heavy": 0.0, "choco": 0.0}
    annual_energy_yi = {"heavy": 0.0, "choco": 0.0}
    terminal_frequency: dict[str, float] = {}
    days = config["swap_business"]["operating_days"]
    usable = config["swap_business"]["usable_energy_factor"]
    for key, vehicle in config["vehicles"].items():
        relevant = [row for row in rows if row.vehicle_key == key]
        raw_vehicles = sum(row.catl_swap_vehicles_wan for row in relevant)
        raw_frequency = (
            sum(
                row.catl_swap_vehicles_wan * row.swap_frequency_per_day
                for row in relevant
            ) / raw_vehicles
            if raw_vehicles else 0.0
        )
        canonical_vehicles = round(raw_vehicles, vehicle_decimals)
        canonical_frequency = round(raw_frequency, frequency_decimals)
        operating_stock[key] = canonical_vehicles
        terminal_frequency[key] = canonical_frequency
        daily = canonical_vehicles * 1e4 * canonical_frequency
        group = vehicle["station_group"]
        daily_swaps[group] += daily
        annual_energy_yi[group] += (
            daily * vehicle["battery_kwh"] * usable * days / 1e8
        )

    stations = {}
    capacity_diagnostics = {}
    for group, demand in daily_swaps.items():
        diagnostics = station_capacity(config, group)
        capacity_diagnostics[group] = diagnostics
        capacity = diagnostics["planning_capacity"]
        reusable = sourcing.reusable_heavy_stations if group == "heavy" else sourcing.reusable_choco_stations
        stations[group] = max(0, math.ceil(demand / capacity) - reusable)

    return ScaleResult(
        years=years,
        rows=rows,
        operating_stock_by_vehicle_wan=operating_stock,
        terminal_frequency_by_vehicle=terminal_frequency,
        annual_catl_swap_gwh=annual_swap,
        annual_catl_charge_gwh=annual_charge,
        annual_catl_no_swap_gwh=annual_no_swap,
        target_station_demand=stations,
        mature_daily_swaps=daily_swaps,
        mature_annual_energy_yi_kwh=annual_energy_yi,
        station_capacity_diagnostics=capacity_diagnostics,
        route_identity_error=identity_error,
    )

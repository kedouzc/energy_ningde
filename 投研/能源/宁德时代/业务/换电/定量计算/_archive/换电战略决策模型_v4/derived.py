from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LifecycleFactors:
    capital_multiplier: float
    terminal_residual_ratio: float
    replacement_pv_ratio: float


def battery_price_rmb_kwh(config: dict, year: float) -> float:
    """按三阶段价格曲线返回任意年份的动力电池价格。"""
    curve = config["construction"]["battery_price_curve"]
    base = curve["base_price_rmb_kwh"]
    platform_end = float(curve["platform_end_year"])
    rapid_end = float(curve["rapid_decline_end_year"])
    if year <= platform_end:
        return base
    rapid_years = max(0.0, min(year, rapid_end) - platform_end)
    slow_years = max(0.0, year - rapid_end)
    return (
        base
        * (1.0 - curve["rapid_annual_decline_rate"]) ** rapid_years
        * (1.0 - curve["slow_annual_decline_rate"]) ** slow_years
    )


def annual_battery_price_path(config: dict) -> dict[int, float]:
    return {
        year: battery_price_rmb_kwh(config, year)
        for year in config["construction"]["years"]
    }


def retirement_recovery_ratio(config: dict) -> float:
    """退役时卖旧电池的回收额/同年新电池价格。"""
    curve = config["construction"]["battery_price_curve"]
    return (
        curve["storage_to_power_price_ratio"]
        * curve["retirement_soh"]
        * curve["secondary_market_discount"]
    )


def _terminal_residual_ratio(config: dict, install_year: float, life_years: float) -> float:
    """15年末在役批残值相对初装成本的比例。"""
    horizon = config["finance"]["model_horizon_years"]
    horizon_year = install_year + horizon
    completed_cycles = math.floor((horizon - 1e-9) / life_years)
    last_install_year = install_year + completed_cycles * life_years
    age = horizon_year - last_install_year
    curve = config["construction"]["battery_price_curve"]
    soh = max(
        curve["retirement_soh"],
        1.0 - curve["annual_soh_decline_rate"] * age,
    )
    storage_resale_price = (
        battery_price_rmb_kwh(config, horizon_year)
        * curve["storage_to_power_price_ratio"]
        * soh
        * curve["secondary_market_discount"]
    )
    return storage_resale_price / battery_price_rmb_kwh(config, install_year)


def lifecycle_factors(config: dict, install_year: float, life_years: float) -> LifecycleFactors:
    """由价格、寿命、WACC逐次推导EAC式全周期资本倍数与期末残值。"""
    horizon = config["finance"]["model_horizon_years"]
    wacc = config["finance"]["wacc"]
    initial_price = battery_price_rmb_kwh(config, install_year)
    recovery_ratio = retirement_recovery_ratio(config)
    replacement_pv = 0.0
    cycle = 1
    while cycle * life_years < horizon - 1e-9:
        elapsed = cycle * life_years
        replacement_price_ratio = (
            battery_price_rmb_kwh(config, install_year + elapsed) / initial_price
        )
        net_replacement_ratio = replacement_price_ratio * (1.0 - recovery_ratio)
        replacement_pv += net_replacement_ratio / (1.0 + wacc) ** elapsed
        cycle += 1
    return LifecycleFactors(
        capital_multiplier=1.0 + replacement_pv,
        terminal_residual_ratio=_terminal_residual_ratio(
            config, install_year, life_years
        ),
        replacement_pv_ratio=replacement_pv,
    )


def swap_frequency_per_day(vehicle: dict, scene: dict, usable_energy_factor: float) -> float:
    """f=日均里程/可用续航；可用续航=背电量×可用比例/电耗。"""
    daily_km = scene["daily_km"] if "daily_km" in scene else vehicle["daily_km"]
    onboard_kwh = scene.get("onboard_battery_kwh", vehicle["battery_kwh"])
    consumption = scene.get(
        "energy_consumption_kwh_km", vehicle.get("energy_consumption_kwh_km")
    )
    if consumption is None or onboard_kwh <= 0 or usable_energy_factor <= 0:
        raise ValueError("换电频次缺少日均里程、背电量或电耗参数")
    usable_range_km = onboard_kwh * usable_energy_factor / consumption
    return daily_km / usable_range_km


def station_capacity(config: dict, group: str) -> dict[str, float]:
    """物理能力只作上限校验；站数分母使用明确标注为外生假设的规划能力。"""
    station = config["stations"][group]
    business = config["swap_business"]
    mechanical = (
        station["operating_hours_day"] * 3600.0 / station["swap_duration_seconds"]
    )
    energy = (
        station["charging_power_kw"]
        * station["operating_hours_day"]
        * business["rte"]
        / (station["block_kwh"] * business["usable_energy_factor"])
    )
    physical = min(mechanical, energy)
    planning = station["planning_daily_capacity"]
    if planning > physical + 1e-9:
        raise ValueError(
            f"{station['label']}规划能力{planning:.1f}超过物理上限{physical:.1f}"
        )
    return {
        "mechanical_limit": mechanical,
        "energy_limit": energy,
        "physical_limit": physical,
        "planning_capacity": planning,
        "physical_headroom_ratio": physical / planning - 1.0,
    }

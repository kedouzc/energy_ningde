"""派生量计算：电池价格路径、全生命周期资本因子、换电频次、电池寿命、站能力。

变更历史
--------
v4.2.2（2026-08-29）
- 【新增】battery_life_years(config, frequency_per_day)：按2000次循环临界点÷年循环次数、
  与日历寿命封顶取min推算电池寿命，替代各车型硬编码。
- 【新增】LEGACY_V32_VEHICLE_LIFE_YEARS / LEGACY_V32_STATION_LIFE_YEARS：v3.2遗留硬编码
  寿命常量，不参与基准测算，仅供附录A.2新旧口径对比重跑。保留在代码而非配置，因其属于
  "口径定义"而非"可调参数"；并注明它与模型自身频次参数不自洽。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LifecycleFactors:
    capital_multiplier: float
    terminal_residual_ratio: float
    replacement_pv_ratio: float


@dataclass(frozen=True)
class TerminalResidualDetails:
    horizon_price_ratio: float
    terminal_batch_age_years: float
    terminal_batch_soh: float
    secondary_market_discount: float
    terminal_residual_ratio: float


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


def terminal_residual_details(
    config: dict, install_year: float, life_years: float
) -> TerminalResidualDetails:
    """拆出15年末共同价格因子与末批在役年龄/SOH，避免把二者混为一谈。

    【2026-09-03，经用户复核后修正】末代批次在模型horizon结束时仍在役、仍是换电电池，
    没有发生退役、没有转去做储能——因此不适用 storage_to_power_price_ratio
    （储能/动力价格比 0.917）：那一项只描述"退役电池降级卖给储能市场"这一具体转换，
    对应公式见 retirement_recovery_ratio()，专供期中更换回收使用，末代不适用。

    但 secondary_market_discount（二手转售折价）适用，理由与"是否发生真实交易"无关：
    这是 DCF 的期末资产残值（Terminal/Salvage Value）——项目分析期结束时，这批仍在役的
    换电电池对于「接盘方」或「二手市场」具有公允价值，理应作为期末现金流入计入 NPV
    （标准项目财务处理，不需要真的完成一次处置动作才能确认）。既然这份价值最终要以
    "变现假设"计入现金流，就该背上二手市场的流动性折价——买方不会按新电池同等价格
    收一批旧电池。公式：残值 = 期末同代新换电电池价（重置成本）× 实际SOH × 二手交易折扣。
    见 DECISIONS.md「2026-09-03 · 末代残值不再降级储能」。
    """
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
    price_ratio = (
        battery_price_rmb_kwh(config, horizon_year)
        / battery_price_rmb_kwh(config, install_year)
    )
    discount = curve["secondary_market_discount"]
    residual = price_ratio * soh * discount
    return TerminalResidualDetails(
        horizon_price_ratio=price_ratio,
        terminal_batch_age_years=age,
        terminal_batch_soh=soh,
        secondary_market_discount=discount,
        terminal_residual_ratio=residual,
    )


def _terminal_residual_ratio(config: dict, install_year: float, life_years: float) -> float:
    """15年末在役批可回收价值相对初装成本的比例。"""
    return terminal_residual_details(
        config, install_year, life_years
    ).terminal_residual_ratio


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


# v3.2遗留的硬编码电池寿命。不参与基准测算，仅供附录「新旧寿命口径对比」程序化重跑对照。
# 之所以保留在代码而非配置：它与模型自身的频次/里程参数并不自洽——
#   重卡5.7年  → 隐含日均换电 2000÷5.7÷350 = 1.00次，而模型实算1.83次（低估强度→寿命偏长）
#   巧克力站3.8年 → 隐含1.50次，而使用量加权实算0.87次（高估强度→寿命偏短）
# 保留它是为了量化「口径从拍值改为按使用强度推算」到底改变了多少。
LEGACY_V32_VEHICLE_LIFE_YEARS = {
    "heavy": 5.7,
    "city": 3.8,
    "taxi": 3.8,
    "ridehail": 3.8,
    "robotaxi": 3.8,
    "private": 10.0,
}
LEGACY_V32_STATION_LIFE_YEARS = {"heavy": 5.7, "choco": 3.8}


def battery_life_years(config: dict, frequency_per_day: float) -> float:
    """换电块寿命：以循环临界点为触发条件，叠加日历寿命封顶（超换一体.md §2.1）。

    不再硬编码 battery_life_years，而是按各车型实际换电强度反推：
        life = min( critical_cycles ÷ (frequency_per_day × operating_days), calendar_cap_years )

    双轨理由：营运车高频（日均1.5-2次→年循环548-730→2.7-3.6年到临界点）由循环主导；
    私家车低频（日均0.3-0.5次→年循环110-183→理论10.9-18.2年）循环推得过长，
    须以日历寿命封顶（LFP约8-10年，即便循环未到也因静置衰减退役）→ min(循环, 10)=10年。
    """
    model = config["battery_life_model"]
    days = config["swap_business"]["operating_days"]
    cycles_per_year = frequency_per_day * days
    if cycles_per_year <= 0:
        return float(model["calendar_cap_years"])
    cycle_life = model["critical_cycles"] / cycles_per_year
    return min(cycle_life, float(model["calendar_cap_years"]))


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

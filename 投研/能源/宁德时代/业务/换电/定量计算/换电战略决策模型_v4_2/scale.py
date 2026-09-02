"""换电规模测算：车辆漏斗、换电频次、装机、站数与电池寿命。

变更历史
--------
v4.2.3（2026-08-29）
- 【充电份额】删除实现率中间层与场景级 catl_charge_share；新增 _charge_share() 按悲观/中性/乐观取档，
  FALLBACK_CHARGE_SHARE 在 [charge_share] 配置缺失时兜底；legacy_v32 对照不再锁旧充电份额，使A.2纯对比寿命维度。
v4.2.2（2026-08-29）
- 【寿命】删除各车型/站组的硬编码 battery_life_years，改为按使用强度推算：
  life = min(critical_cycles ÷ (f̄ × days), calendar_cap)，
  f̄ = Σ(装机GWh × 频次)/Σ装机GWh，即按使用量（装机×频次）加权的使用强度。
  不可对寿命直接按装加权——寿命是频次的倒数，倒数后加权会系统性高估（Jensen不等式）。
- 【站数】改为「冗余优先」：营运车需求按规划能力建站，私家车需求先填单站物理冗余
  （物理上限552 − 规划300 = 252次/日），溢出部分才新建站。
- 【情景】新增 private_scenario（私家车保守/中枢/激进三档渗透率）。
- 【对照】新增 life_mode="legacy_v32"，沿用v3.2硬编码寿命重跑，仅供附录对比。
"""
from __future__ import annotations

import math

from derived import (
    LEGACY_V32_STATION_LIFE_YEARS,
    LEGACY_V32_VEHICLE_LIFE_YEARS,
    battery_life_years as derived_battery_life_years,
    station_capacity,
    swap_frequency_per_day,
)
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


# 充电段市占率三档的兜底值。正式口径以 configs/base.toml 的 [charge_share] 段为准
# （该段含完整的取值理由与信源链接）。此处仅在配置缺失时兜底，保证模型可运行。
FALLBACK_CHARGE_SHARE: dict[str, tuple[float, float]] = {
    "heavy": (0.35, 0.55),
    "city": (0.35, 0.45),
    "taxi": (0.35, 0.45),
    "ridehail": (0.35, 0.45),
    "robotaxi": (0.35, 0.00),
    "private": (0.33, 0.40),
}


def _charge_share(config: dict, vehicle_key: str, scenario: str) -> float:
    """充电段CATL市占率：按悲观/中性/乐观直接取档，不再用"份额提升实现率"插值。

    悲观 = 无换电保护、充分竞争下的份额；乐观 = 换电标准锁定后能保持的份额；
    中性 = (悲观+乐观)/2，由程序派生，不手工拍值。
    """
    entry = config.get("charge_share", {}).get(vehicle_key)
    if entry is None:
        pessimistic, optimistic = FALLBACK_CHARGE_SHARE[vehicle_key]
    else:
        pessimistic = entry["pessimistic"]
        optimistic = entry["optimistic"]
    if scenario == "悲观":
        return pessimistic
    if scenario == "乐观":
        return optimistic
    if scenario == "中性":
        return (pessimistic + optimistic) / 2.0
    raise ValueError(f"未知充电段市占率情景 {scenario}")


def _city_stock_layer(config: dict) -> dict:
    """城配存量层（高不确定·单列·不并入 headline）。

    补回自 _archive/重卡与城配物流换电规模测算_合并对比.py v2：
    城配换电2025才起步，存量层基准用 2025 单年 NEV销量(62.8万)；
    换电渗透率极低(2%)、CATL市占率高(80%，少数带换电者走巧克力标准)。
    该存量层与重卡 existing_catl_swap_stock_wan（已是CATL换电存量）不同：
    此处是"历史NEV存量"，需按存量换电渗透率/CATL市占率二次折算，且**单列不并入增量漏斗**。
    """
    city = config["vehicles"].get("city", {})
    nev_stock = city.get("city_existing_nev_stock_wan", 0.0)
    swap_pen = city.get("city_stock_swap_penetration", 0.0)
    catl_share = city.get("city_stock_catl_share", 0.0)
    battery_kwh = city.get("battery_kwh", 80.0)
    if nev_stock <= 0:
        return {}
    stock_swap_veh = nev_stock * swap_pen               # 存量层换电车辆（万辆）
    stock_catl_veh = stock_swap_veh * catl_share        # 存量层进CATL换电车辆（万辆）
    stock_catl_gwh = stock_catl_veh * battery_kwh / 100.0  # 存量层装机（GWh）
    # 频次沿用城配高频子集口径（f = 日均里程 ÷ (背电×余电折扣÷电耗)）
    usable = config["swap_business"]["usable_energy_factor"]
    f = city["daily_km"] / (battery_kwh * usable / city.get("energy_consumption_kwh_km", 0.27))
    return {
        "nev_stock_wan": round(nev_stock, 1),
        "swap_penetration": swap_pen,
        "catl_share": catl_share,
        "catl_swap_vehicles_wan": round(stock_catl_veh, 2),
        "catl_swap_gwh": round(stock_catl_gwh, 2),
        "swap_frequency_per_day": round(f, 2),
        "note": "城配存量层·高不确定·单列不并入 headline 增量（类比 _archive v2 城配C 存量支线）",
    }


def build_scale(
    config: dict,
    sourcing: SourcingAdjustment,
    private_scenario: str = "中枢",
    life_mode: str = "derived",
) -> ScaleResult:
    """private_scenario：私家车分档换电渗透率情景，取 保守/中枢/激进（见 base.toml
    [vehicles.private.scenario_swap_penetration]）。中枢即 scenes 内的默认口径。

    life_mode：电池寿命口径。
      "derived"    = 按[battery_life_model]以2000次循环临界点÷使用强度推算（基准）；
      "legacy_v32" = 沿用v3.2硬编码寿命，仅供附录新旧口径对比重跑，不用于基准结论。
    """
    if life_mode not in ("derived", "legacy_v32"):
        raise ValueError(f"未知寿命口径 {life_mode}")
    legacy_vehicle_life = LEGACY_V32_VEHICLE_LIFE_YEARS
    legacy_station_life = LEGACY_V32_STATION_LIFE_YEARS
    years = config["construction"]["years"]
    stocks = _operating_stocks(config)
    # 私家车三情景：非中枢档时按情景表覆盖各价格带分档的换电渗透率。
    private_scene_pen: dict[str, float] = {}
    if private_scenario != "中枢":
        table = config["vehicles"].get("private", {}).get("scenario_swap_penetration", {})
        if private_scenario not in table:
            raise ValueError(
                f"未知私家车情景 {private_scenario}，可用：{list(table)}"
            )
        private_scene_pen = table[private_scenario]
    # 充电段市占率：直接按悲观/中性/乐观取档（见[charge_share]），不再用实现率插值。
    # 中性档为程序派生的两档均值，基准不再默认取最乐观值。
    charge_scenario = config.get("charge_share", {}).get("scenario", "中性")
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
                swap_penetration = private_scene_pen.get(
                    scene["name"], scene["swap_penetration"]
                ) if private_scene_pen else scene["swap_penetration"]
                charge_penetration = 1.0 - swap_penetration
                identity_error = max(identity_error, abs(swap_penetration + charge_penetration - 1.0))
                catl_swap_share = min(1.0, scene["catl_swap_share"] + share_uplift)
                market_swap = ev * swap_penetration
                market_charge = ev * charge_penetration
                catl_swap = market_swap * catl_swap_share
                # 充电段份额按三档取档（与寿命口径正交；A.2仅对比寿命维度，不混入充电份额变更）。
                catl_charge = market_charge * _charge_share(config, key, charge_scenario)
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
                    # 寿命口径：基准按2000次循环临界点÷年循环次数，与日历寿命封顶取min；
                    # legacy_v32仅用于附录新旧口径对照重跑。
                    battery_life_years=(
                        legacy_vehicle_life[key]
                        if life_mode == "legacy_v32"
                        else derived_battery_life_years(config, frequency)
                    ),
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
    # 私家车日换电需求单列：站数反推时它先填现有站的物理冗余，溢出才新建站。
    private_daily_swaps = {"heavy": 0.0, "choco": 0.0}
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
        if key == "private":
            private_daily_swaps[group] += daily
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
        # 站数反推：营运车需求按规划能力建站；私家车需求先填这些站相对物理上限的冗余，
        # 只有在冗余被填满后才为溢出部分新建站。
        # 依据：巧克力站规划300次/日、物理上限552次/日，单站冗余252次/日——
        # 这个冗余本来就是为后续需求（含私家车）预留的，不应让私家车按300重新摊一遍站数。
        private_demand = private_daily_swaps[group]
        base_demand = max(0.0, demand - private_demand)
        base_stations = math.ceil(base_demand / capacity) if base_demand > 0 else 0
        headroom_per_station = max(0.0, diagnostics["physical_limit"] - capacity)
        absorbable = base_stations * headroom_per_station
        overflow = max(0.0, private_demand - absorbable)
        extra_stations = math.ceil(overflow / capacity) if overflow > 0 else 0
        stations[group] = max(0, base_stations + extra_stations - reusable)

    # 站内周转电池寿命同样不再硬编码，且**按使用量加权的使用强度推算**，而非对寿命直接加权。
    #
    # 使用量是双因素驱动的：使用频次 × 每次使用的度数。对每类车：
    #     使用量 = 装机GWh × 换电频次 × 余电折扣
    # 与计算换电收入时的「换电度数」是同一逻辑（余电折扣为全局常数，归一化时抵消）。
    #
    # 物理守恒：池子总装机 ΣGWh 承担总换电需求 Σ(GWh×f)，故每单位装机的等效频次
    #     f̄ = Σ(GWh×f) / ΣGWh
    # 再取 life = min(critical_cycles ÷ (f̄ × operating_days), calendar_cap_years)。
    #
    # 不可对寿命直接按装机加权：寿命是频次的**倒数**，倒数后再加权会因 Jensen 不等式
    # 系统性高估（低频的长寿命被放大）。重卡三场景即典型：对寿命加权得3.91年，
    # 按使用量加权仅3.13年。
    station_battery_life: dict[str, float] = {}
    fallback_life = float(config["battery_life_model"]["calendar_cap_years"])
    for group in ("heavy", "choco"):
        if life_mode == "legacy_v32":
            station_battery_life[group] = float(legacy_station_life[group])
            continue
        group_rows = [row for row in rows if row.station_group == group]
        gwh_total = sum(row.catl_swap_gwh for row in group_rows)
        usage_weighted_freq = (
            sum(row.catl_swap_gwh * row.swap_frequency_per_day for row in group_rows) / gwh_total
            if gwh_total else 0.0
        )
        station_battery_life[group] = (
            derived_battery_life_years(config, usage_weighted_freq)
            if usage_weighted_freq > 0 else fallback_life
        )

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
        station_battery_life_years=station_battery_life,
        city_stock_layer=_city_stock_layer(config),
    )

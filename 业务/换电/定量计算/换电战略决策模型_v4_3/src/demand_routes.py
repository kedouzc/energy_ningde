"""需求层（A4，2026-09-28i）：每类车走各条补能路线的全年资源账（系统口径，万元/车·年）。

资源账 ＝ 补能设施（供给层规划最优时的每度电站成本 × 年用电）
       ＋ 车上电池（资本回收，按各路线的电池寿命；兆瓦路线加高倍率溢价）
       ＋ 时间（每天多停的小时 × 年运营天 × 补运力成本）
       ＋ 车端溢价（换电底盘）。
电费四条路线相同，不列。资金成本一律用系统 WACC；车队融资贵这一类差别属账单账，在 A5 处理。
时间：每次补能 ＝ 进出与操作 ＋ 排队（供给层规划最优时的平均排队）＋ 补能时长；
      干线（中、长途）可与每 4 小时一次、20 分钟的强制休息重合，能重合的比例是声明值；封闭短途不重合。
补运力成本：短途封闭多班倒（车是瓶颈）＝ 车每小时成本 ＋ 司机每小时成本；干线单司机（司机工时是瓶颈）＝ 司机每小时成本。
"""
from __future__ import annotations

import math

import supply_routes as SR

SCENE_KEYS = ("short", "mid", "long")
ROUTE_KEYS = ("conventional", "megawatt", "swap", "depot")


def _crf(r: float, n: float) -> float:
    return r / (1.0 - (1.0 + r) ** -n) if r > 0 else 1.0 / n


def time_value(config: dict, scene_idx: int) -> dict:
    """补运力成本（元/时）。"""
    D = config["demand_routes"]
    soc = float(D["employer_social_factor"])
    r = float(config["finance"]["wacc"])
    hours_driver = float(D["driver_hours_day"]) * float(D["driver_days_year"])
    if scene_idx == 0:
        drv = float(D["driver_wage_short_rmb_month"]) * 12 * soc / hours_driver
        truck_year = float(D["truck_price_wan"]) * 1e4 * _crf(r, float(D["truck_life_years"])) + float(D["truck_insurance_wan_year"]) * 1e4
        trk = truck_year / float(D["short_truck_hours_year"])
        return {"driver": drv, "truck": trk, "w": drv + trk, "basis": "车是瓶颈：补车＋补人"}
    drv = float(D["driver_wage_trunk_rmb_month"]) * 12 * soc / hours_driver
    return {"driver": drv, "truck": 0.0, "w": drv, "basis": "司机工时是瓶颈：多雇司机"}


def _battery_year(config: dict, kwh: float, life_cycles: float, cycles_year: float, premium: float = 0.0) -> tuple[float, float]:
    from derived import retirement_recovery_ratio, terminal_battery_price
    life = min(life_cycles / cycles_year if cycles_year else 99.0, float(config["battery_life_model"]["calendar_cap_years"]))
    price = terminal_battery_price(config) * (1.0 + premium)
    r = float(config["finance"]["wacc"])
    cap = kwh * price
    salvage = cap * retirement_recovery_ratio(config) / (1.0 + r) ** life
    return (cap - salvage) * _crf(r, life), life


def scene_route(config: dict, scene_idx: int, route: str, supply: dict | None = None) -> dict:
    D = config["demand_routes"]
    sc = config["vehicles"]["heavy"]["scenes"][scene_idx]
    supply = supply or SR.summary(config)
    days = float(config["swap_business"]["operating_days"])
    daily_kwh = float(sc["daily_km"]) * float(sc["energy_consumption_kwh_km"])
    kwh_year = daily_kwh * days
    onboard = float(sc["onboard_battery_kwh"])
    cycles_year = kwh_year / onboard
    blc = config["battery_life_model"]
    crit = float(blc["critical_cycles"])
    pool_mult = max(1.0, float(blc.get("pool_life_multiplier") or 1.0))
    usable = float(config["swap_business"]["usable_energy_factor"])
    overhead_h = float(D["session_overhead_minutes"]) / 60.0
    S = config["supply_routes"]
    if route == "swap":
        per_session = onboard * usable
        o = supply["optimum"]["swap"]
        dur_h = float(config["stations"]["qiji75_trunk"]["swap_duration_seconds"]) / 3600.0
        queue_h = o["wait_min"] / 60.0
        station_cost = o["station_cost"]
        bat, life = _battery_year(config, onboard, crit * pool_mult, cycles_year)
        extra = float(D["swap_chassis_premium_wan"]) * 1e4 * _crf(float(config["finance"]["wacc"]), float(D["truck_life_years"]))
    elif route == "depot":
        per_session = onboard * usable
        dur_h, queue_h = 5.0 / 60.0, 0.0
        station_cost = 0.0
        spare = float(D["depot_spare_sets"])
        b1, life = _battery_year(config, onboard, crit * pool_mult, cycles_year / (1.0 + spare))
        bat = b1 * (1.0 + spare)
        r = float(config["finance"]["wacc"])
        extra = float(D["depot_station_wan"]) * 1e4 / float(D["depot_trucks_served"]) * _crf(r, float(S["equipment_life_years"]))
    else:
        R = S[route]
        per_session = onboard * float(D["charge_soc_window"])
        p_avg = float(R["pile_kw"]) * float(S["charge_power_factor"])
        dur_h = per_session / p_avg
        o = supply["optimum"][route]
        queue_h = o["wait_min"] / 60.0
        station_cost = o["station_cost"]
        if route == "megawatt":
            bat, life = _battery_year(config, onboard, crit, cycles_year, float(D["mw_battery_premium"]))
        else:
            bat, life = _battery_year(config, onboard, crit * pool_mult, cycles_year)
        extra = 0.0
    sessions_day = daily_kwh / per_session
    session_h = overhead_h + queue_h + dur_h
    absorbed_h = 0.0
    if scene_idx > 0:
        drive_h = float(sc["daily_km"]) / float(D["highway_speed_kmh"])
        rests = math.floor(drive_h / float(D["rest_every_hours"]))
        n_abs = min(rests, math.ceil(sessions_day - 1e-9))
        absorbed_h = float(D["rest_absorb_share"]) * n_abs * min(session_h, float(D["rest_minutes"]) / 60.0) \
            * (sessions_day / math.ceil(sessions_day - 1e-9) if sessions_day < 1 else 1.0)
    stop_h_day = max(0.0, sessions_day * session_h - absorbed_h)
    tv = time_value(config, scene_idx)
    time_cost = stop_h_day * days * tv["w"]
    facility = station_cost * kwh_year
    total = facility + bat + time_cost + extra
    return {"scene": sc["name"], "route": route, "daily_kwh": daily_kwh, "sessions_day": sessions_day,
            "session_min": session_h * 60.0, "absorbed_min": absorbed_h * 60.0, "stop_h_day": stop_h_day,
            "battery_life": life, "facility_wan": facility / 1e4, "battery_wan": bat / 1e4, "time_wan": time_cost / 1e4,
            "extra_wan": extra / 1e4, "total_wan": total / 1e4, "w": tv["w"]}


def summary(config: dict) -> dict:
    supply = SR.summary(config)
    out = {}
    for i, _ in enumerate(SCENE_KEYS):
        routes = ROUTE_KEYS if i == 0 else ("conventional", "megawatt", "swap")
        rows = {rt: scene_route(config, i, rt, supply) for rt in routes}
        best = min(rows.values(), key=lambda d: d["total_wan"])
        out[SCENE_KEYS[i]] = {"rows": rows, "winner": best["route"], "tv": time_value(config, i)}
    return out

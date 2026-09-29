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


def truck_life(config: dict, scene_idx: int) -> float:
    """车辆寿命 ＝ min（强制报废年限，引导报废里程 ÷ 年里程）。"""
    D = config["demand_routes"]
    sc = config["vehicles"]["heavy"]["scenes"][scene_idx]
    km_year = float(sc["daily_km"]) * float(config["swap_business"]["operating_days"])
    return min(float(D["truck_scrap_years"]), float(D["truck_scrap_km"]) / km_year)


def time_value(config: dict, scene_idx: int) -> dict:
    """补运力成本（元/时）。司机工资各场景相同（同一个劳动力市场）。"""
    D = config["demand_routes"]
    soc = float(D["employer_social_factor"])
    r = float(config["finance"]["wacc"])
    hours_driver = float(D["driver_hours_day"]) * float(D["driver_days_year"])
    drv = float(D["driver_wage_rmb_month"]) * 12 * soc / hours_driver
    if scene_idx == 0:
        life = truck_life(config, 0)
        truck_year = float(D["truck_price_wan"]) * 1e4 * _crf(r, life) + float(D["truck_insurance_wan_year"]) * 1e4
        trk = truck_year / float(D["short_truck_hours_year"])
        return {"driver": drv, "truck": trk, "w": drv + trk, "life": life, "basis": "车是瓶颈：补车＋补人"}
    return {"driver": drv, "truck": 0.0, "w": drv, "life": truck_life(config, scene_idx), "basis": "司机工时是瓶颈：多雇司机"}


def pack_price(config: dict, kind: str) -> float:
    """兑现年电池包价（元/度）：曲线价是换电专用包；普通包 ＝ 曲线价 ÷ (1＋换电附加)；兆瓦包 ＝ 普通包 ×（1＋高倍率溢价）。"""
    from derived import terminal_battery_price
    D = config["demand_routes"]
    swap = terminal_battery_price(config)
    plain = swap / (1.0 + float(D["swap_pack_premium"]))
    return {"swap": swap, "plain": plain, "megawatt": plain * (1.0 + float(D["mw_battery_premium"]))}[kind]


def _battery_year(config: dict, kwh: float, life_cycles: float, cycles_year: float, price: float) -> tuple[float, float]:
    from derived import retirement_recovery_ratio
    blm = config["battery_life_model"]
    cap = float(blm.get("heavy_calendar_cap_years") or blm["calendar_cap_years"])
    life = min(life_cycles / cycles_year if cycles_year else 99.0, cap)
    r = float(config["finance"]["wacc"])
    cap = kwh * price
    salvage = cap * retirement_recovery_ratio(config) / (1.0 + r) ** life
    return (cap - salvage) * _crf(r, life), life


def scene_route(config: dict, scene_idx: int, route: str, supply: dict | None = None, night: str = "public") -> dict:
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
        bat, life = _battery_year(config, onboard, crit * pool_mult, cycles_year, pack_price(config, "swap"))
        extra = float(D["swap_chassis_premium_wan"]) * 1e4 * _crf(float(config["finance"]["wacc"]), truck_life(config, scene_idx))
    elif route == "depot":
        per_session = onboard * usable
        dur_h, queue_h = 5.0 / 60.0, 0.0
        station_cost = 0.0
        spare = float(D["depot_spare_sets"])
        b1, life = _battery_year(config, onboard, crit * pool_mult, cycles_year / (1.0 + spare), pack_price(config, "swap"))
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
            bat, life = _battery_year(config, onboard, crit, cycles_year, pack_price(config, "megawatt"))
        else:
            bat, life = _battery_year(config, onboard, crit * pool_mult, cycles_year, pack_price(config, "plain"))
        extra = 0.0
    # 夜间补满：干线单班车出车前满电，途中只补差额；封闭多班倒没有空档，全部在途中补
    overnight = scene_idx > 0
    start = (onboard * usable) if route in ("swap", "depot") else per_session
    enroute_kwh = max(0.0, daily_kwh - start) if overnight else daily_kwh
    stops = math.ceil(enroute_kwh / per_session - 1e-9) if enroute_kwh > 0 else 0
    if not overnight:
        stops_f = daily_kwh / per_session          # 连续运转：按平均次数计
    else:
        stops_f = float(stops)
    e_stop = enroute_kwh / stops_f if stops_f else 0.0
    if route in ("swap", "depot"):
        dur_stop = dur_h
    else:
        dur_stop = e_stop / p_avg
    session_h = overhead_h + queue_h + dur_stop
    absorbed_h = 0.0
    if overnight and stops:
        drive_h = float(sc["daily_km"]) / float(D["highway_speed_kmh"])
        rests = math.floor(drive_h / float(D["rest_every_hours"]))
        absorbed_h = min(rests, stops) * min(session_h, float(D["rest_minutes"]) / 60.0)
    stop_h_day = max(0.0, stops_f * session_h - absorbed_h)
    sessions_day = stops_f
    # 兆瓦车只有途中那部分电是大电流快充，夜里在场站慢充：按两种充法各自的循环寿命加权
    if route == "megawatt":
        f_fast = enroute_kwh / daily_kwh if daily_kwh else 1.0
        eff = 1.0 / (f_fast / crit + (1.0 - f_fast) / (crit * pool_mult))
        bat, life = _battery_year(config, onboard, eff, cycles_year, pack_price(config, "megawatt"))
    # 夜间那部分电（干线单班车夜里停着，没有时间差）走最便宜的地方（研究者 2026-09-29，DECISIONS 2026-09-29h、2026-09-29i）：
    #   散户（零售）：公共常规快充站（按其最优利用率的站成本）；重卡司机多数没有固定车位，不像私家车能在自家车位装桩；
    #   签长协的车队（批发）：公共站与自建场站（supply_routes.depot_cost）取便宜的。
    #   换电车若换电站比上面更便宜，收车前去换满。充电车与换电车夜里的选项相同。
    night_via_swap = False
    night_cost = supply["optimum"]["conventional"]["station_cost"]
    if night == "depot":
        night_cost = min(night_cost, supply["depot"]["cost"])
    if overnight and route in ("conventional", "megawatt", "swap"):
        night_c = night_cost
        if route == "swap" and station_cost < night_cost:
            night_c, night_via_swap = station_cost, True
        station_cost = (enroute_kwh * station_cost + (daily_kwh - enroute_kwh) * night_c) / daily_kwh
    tv = time_value(config, scene_idx)
    time_cost = stop_h_day * days * tv["w"]
    facility = station_cost * kwh_year
    total = facility + bat + time_cost + extra
    return {"scene": sc["name"], "route": route, "daily_kwh": daily_kwh, "sessions_day": sessions_day, "enroute_kwh": enroute_kwh,
            "session_min": session_h * 60.0, "absorbed_min": absorbed_h * 60.0, "stop_h_day": stop_h_day,
            "battery_life": life, "facility_wan": facility / 1e4, "battery_wan": bat / 1e4, "time_wan": time_cost / 1e4,
            "extra_wan": extra / 1e4, "total_wan": total / 1e4, "w": tv["w"],
            "station_share": (1.0 if (not overnight or night_via_swap) else enroute_kwh / daily_kwh) if daily_kwh else 1.0,
            "night_cost": night_cost, "night_kwh": (daily_kwh - enroute_kwh) if overnight else 0.0, "night_via_swap": night_via_swap}


def summary(config: dict) -> dict:
    supply = SR.summary(config)
    out = {}
    for i, _ in enumerate(SCENE_KEYS):
        routes = ROUTE_KEYS if i == 0 else ("conventional", "megawatt", "swap")
        rows = {rt: scene_route(config, i, rt, supply) for rt in routes}
        best = min(rows.values(), key=lambda d: d["total_wan"])
        out[SCENE_KEYS[i]] = {"rows": rows, "winner": best["route"], "tv": time_value(config, i)}
    return out

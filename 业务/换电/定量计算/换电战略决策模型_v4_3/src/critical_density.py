"""换电网络的临界密度（第②层"能不能到"，2026-09-29g/h）。口径：口径/换电网络_临界密度.md。本模块只驱动口径文档读数，不进主链。

主线（研究者 2026-09-29 定的顺序）：
① 单站保本：换电站每天要换多少次才不亏（只看站的经济账，与哪条路无关）。
② 筛选线：一条线路上，每个方向每天至少要有多少辆换电车经过，按最稀的站距建的站才能换到①的次数。
③ 线路上真有这么多车吗：宁德 15 万公里干线网上，2030 年平均每个方向每天有多少电动重卡、多少换电车经过；与②比。
④ 要建多少站：由车一共要换多少次电定（按最优利用率时每站的换电次数），但不能少于"按最稀站距铺满"的站数；站数决定总投资。
⑤ 过渡期：来车不够时每站每年亏多少。
换电车只在途中换电；干线车夜里在自家场站慢充，除非换电站比自家桩还便宜（demand_routes 的 station_share）。
"""
from __future__ import annotations

import equilibrium as E
import supply_routes as SR


def _trunk(config: dict) -> dict:
    x = E.class_components(config, "trunk")
    pts = [p for p in x["points"] if p["chosen"]]
    days = float(config["swap_business"]["operating_days"])
    w = sum(p["weight"] for p in pts)
    kwh_day = sum(p["weight"] * p["kwh_year"] for p in pts) / w / days if w else 0.0
    return {"cap": x["fee_cap"] + x["m_rent"], "fee_cap": x["fee_cap"], "m_rent": x["m_rent"], "kwh_day": kwh_day,
            "station_share": x["station_share"], "share": x["share"], "access": x["access"], "market_share": x["market_share"]}


def station_cost(config: dict, rho: float, w: float) -> float:
    return SR.cost_at(config, "swap", rho, w)["station_cost"]


def breakeven_rho(config: dict, cap: float, w: float) -> float | None:
    """站成本随利用率下降（固定成本摊薄），二分求 站成本 ＝ 上限 的利用率；到电量上限还降不到则返回 None。"""
    c = SR.swap_constraints(config)
    hi = min(0.95, c["energy"] / c["lane"])
    if station_cost(config, hi, w) > cap:
        return None
    lo = 0.005
    for _ in range(60):
        mid = (lo + hi) / 2
        if station_cost(config, mid, w) > cap:
            lo = mid
        else:
            hi = mid
    return hi


def summary(config: dict) -> dict:
    cd = config["critical_density"]
    w = SR.provisional_wait_cost(config)
    c = SR.swap_constraints(config)
    tr = _trunk(config)
    scenes = config["vehicles"]["heavy"]["scenes"]
    e_km = float(scenes[1]["energy_consumption_kwh_km"])
    usable_range = float(scenes[1]["onboard_battery_kwh"]) * float(config["swap_business"]["usable_energy_factor"]) / e_km
    spacing = usable_range * (1.0 - float(cd["range_reserve"]))
    dirs = float(cd["directions"])
    L = float(cd["network_km"])
    days = float(config["swap_business"]["operating_days"])
    out = {"trunk": tr, "w": w, "lane": c["lane"], "e_swap": c["e_swap"], "e_km": e_km, "usable_range": usable_range,
           "spacing": spacing, "dirs": dirs, "L": L}
    # ③ 线路上的车：2030 年电动重卡里跑干线的，按日里程与运营天折成每天的车公里；80% 跑在这 15 万公里上
    trunk_w = sum(float(s["weight"]) for s in scenes[1:])
    trunk_trucks = float(cd["ev_heavy_stock_2030_wan"]) * 1e4 * trunk_w
    km_day = sum(float(s["weight"]) * float(s["daily_km"]) for s in scenes[1:]) / trunk_w
    veh_km = trunk_trucks * km_day * days / 365.0 * float(cd["network_trunk_share"])
    ev_flow = veh_km / L / dirs                       # 每个方向每天经过某一点的电动重卡
    swap_flow = ev_flow * tr["market_share"]
    out.update(trunk_trucks=trunk_trucks, km_day=km_day, veh_km=veh_km, ev_flow=ev_flow, swap_flow=swap_flow,
               cover_stations=dirs * L / spacing, old_stations=dirs * L / float(cd["old_spacing_km"]))
    rho = breakeven_rho(config, tr["cap"], w) if tr["kwh_day"] else None
    out["rho"] = rho
    if rho is None:
        out["ok"] = False
        return out
    # ① 单站保本
    swaps = c["lane"] * rho
    # ② 筛选线：每辆经过的换电车在一个站距里用掉 e_km × s 度电，其中途中换电占比那部分要在这座站换回
    per_truck_kwh = e_km * spacing * tr["station_share"]
    q_star = swaps * c["e_swap"] / per_truck_kwh
    # ④ 要建多少站：途中换电总次数 ÷ 最优利用率时每站每天的换电次数，不少于铺满所需
    opt = SR.planner_optimum(config, "swap", w)
    opt_swaps = c["lane"] * opt["rho"]
    swap_trucks = trunk_trucks * tr["market_share"] * float(cd["network_trunk_share"])
    swaps_needed = swap_trucks * tr["kwh_day"] * tr["station_share"] / c["e_swap"] * days / 365.0
    demand_stations = swaps_needed / opt_swaps
    out.update(ok=True, swaps_day=swaps, per_truck_kwh=per_truck_kwh, q_star=q_star, ev_flow_star=q_star / tr["market_share"],
               share_star=q_star / ev_flow, opt_rho=opt["rho"], opt_swaps=opt_swaps, swap_trucks=swap_trucks,
               swaps_needed=swaps_needed, demand_stations=demand_stations, stations=max(demand_stations, out["cover_stations"]),
               opt_spacing=dirs * L / max(demand_stations, out["cover_stations"]),
               today_per_station=float(cd["today_swap_trucks"]) / float(cd["today_swap_stations"]),
               n_star=swaps * c["e_swap"] / (tr["kwh_day"] * tr["station_share"]))
    # ⑤ 过渡期：每个方向每天经过 q 辆换电车时，按最稀站距建的站每年盈亏
    rows = []
    hi = min(0.95, c["energy"] / c["lane"])
    for q in sorted(set([round(q_star * f) for f in (0.25, 0.5, 0.75, 1.0)] + [round(swap_flow)])):
        r = q * per_truck_kwh / c["e_swap"] / c["lane"]
        if r <= 0 or r > hi:
            continue
        sc = station_cost(config, r, w)
        kwh_year = SR.cost_at(config, "swap", r, w)["kwh_year"]
        rows.append({"q": q, "rho": r, "swaps": r * c["lane"], "station_cost": sc, "margin": tr["cap"] - sc, "profit_wan": (tr["cap"] - sc) * kwh_year / 1e4})
    out["loss_rows"] = rows
    return out

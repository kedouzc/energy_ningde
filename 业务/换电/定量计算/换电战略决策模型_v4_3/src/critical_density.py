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
    """干线换电车（批发与零售合起来）：站能承受的每度电成本、每车每天用电、途中换电占比、份额。"""
    x = E.class_market(config, "trunk")
    days = float(config["swap_business"]["operating_days"])
    c = x["contract_share"]
    num = den = 0.0
    for seg, f in ((x["contract"], c), (x["retail"], 1.0 - c)):
        for p in seg["points"]:
            if p.get("swaps"):
                num += f * p["weight"] * p["kwh_year"]; den += f * p["weight"]
    kwh_day = num / den / days if den else 0.0
    # 按日里程分组：中途、长途各自途中换多少（研究者 2026-09-29：先按分布逐车算，再按构成加权，不先平均里程）
    groups: dict = {}
    for seg, f, tag in ((x["contract"], c, "wc"), (x["retail"], 1.0 - c, "wr")):
        for p in seg["points"]:
            g = groups.setdefault(p["scene"], {"w": 0.0, "kwh": 0.0, "st": 0.0, "km": 0.0, "wc": 0.0, "wr": 0.0, "all": 0.0})
            if tag == "wc":
                g["all"] += p["weight"]
            if not p.get("swaps"):
                continue
            g[tag] += p["weight"]
            g["w"] += f * p["weight"]; g["kwh"] += f * p["weight"] * p["kwh_year"] / days
            g["st"] += f * p["weight"] * p["st_kwh"] / days; g["km"] += f * p["weight"] * p["km"]
    swap_count = sum(g["w"] for g in groups.values())                  # 来换电的车占干线（不含只租电池的）
    st_share = (sum(g["st"] for g in groups.values()) / sum(g["kwh"] for g in groups.values())) if groups and sum(g["kwh"] for g in groups.values()) else 0.0
    return {"swap_count": swap_count, "st_share_swappers": st_share,
            "cap": x["fee_cap"] + x["m_rent"], "fee_cap": x["fee_cap"], "m_rent": x["m_rent"], "kwh_day": kwh_day,
            "station_share": x["station_share"], "share": x["share"], "access": x["access"], "market_share": x["market_share"],
            "groups": groups}


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
    out = {"trunk": tr, "w": w, "lane": c["lane"], "e_swap": c["e_swap"], "e_km": e_km, "usable_range": usable_range,
           "spacing": spacing, "dirs": dirs, "L": L}
    # ③ 线路上的车：2030 年纯电重卡（车辆与站数推算：2026–2030 逐年新车 × 电动化率 × 纯电占比之和，不含 2025 年以前的存量）里跑干线的，
    #    按日里程折成每个运营日的车公里；网承载的干线运力占比那部分跑在这张网上。以下"每天"都指运营日。
    import scale as _S
    h = config["vehicles"]["heavy"]
    ev_heavy = sum(_S._annual_ev_wan(h, i, {}) for i in range(len(h["nev_rates"]))) * 1e4
    trunk_w = sum(float(sc["weight"]) for sc in scenes[1:])
    trunk_trucks = ev_heavy * trunk_w
    km_day = sum(float(sc["weight"]) * float(sc["daily_km"]) for sc in scenes[1:]) / trunk_w
    # 跑在这张网上的比例 ＝ 可及比例（同一个量：宁德"八横十纵"覆盖全国 80% 干线运力，src.catl_qiji_launch_202505；三档随 [drivers.swap_share_ceiling]）
    on_net = tr["access"]
    veh_km = trunk_trucks * km_day * on_net
    ev_flow = veh_km / L / dirs                       # 每个方向每天经过某一点的纯电重卡
    # 换电车流按换电车自己的里程算：服务到的车是日里程高的那部分，按车数的比例乘全体平均里程会低估
    swap_km_per_truck = sum(g["km"] for g in tr["groups"].values())      # Σ（服务到的车占干线的比例 × 它的日里程）
    flow_share = swap_km_per_truck / km_day if km_day else 0.0           # 换电车占网上纯电重卡车流（按车公里）的比例
    swap_flow = ev_flow * flow_share
    out.update(on_net=on_net, swap_km_per_truck=swap_km_per_truck, flow_share=flow_share, ev_heavy=ev_heavy, trunk_trucks=trunk_trucks, km_day=km_day, veh_km=veh_km, ev_flow=ev_flow, swap_flow=swap_flow,
               cover_stations=dirs * L / spacing, old_stations=dirs * L / float(cd["old_spacing_km"]))
    rho = breakeven_rho(config, tr["cap"], w) if tr["kwh_day"] else None
    out["rho"] = rho
    if rho is None:
        out["ok"] = False
        return out
    # ① 单站保本
    swaps = c["lane"] * rho
    # ② 筛选线：每辆经过的换电车在一个站距里用掉 e_km × s 度电，其中途中换电占比那部分要在这座站换回
    per_truck_kwh = e_km * spacing * tr["st_share_swappers"]
    q_star = swaps * c["e_swap"] / per_truck_kwh
    # ④ 要建多少站：途中换电总次数 ÷ 最优利用率时每站每天的换电次数，不少于铺满所需
    opt = SR.planner_optimum(config, "swap", w)
    opt_swaps = c["lane"] * opt["rho"]
    swap_trucks = trunk_trucks * on_net * tr["swap_count"]   # ＝ 干线纯电重卡 × 可及比例 × 可及范围内来换电的车（不含只租电池的）
    swaps_needed = swap_trucks * tr["kwh_day"] * tr["st_share_swappers"] / c["e_swap"]
    demand_stations = swaps_needed / opt_swaps
    out.update(ok=True, swaps_day=swaps, per_truck_kwh=per_truck_kwh, q_star=q_star,
               share_star=q_star / ev_flow, opt_rho=opt["rho"], opt_swaps=opt_swaps, swap_trucks=swap_trucks,
               swaps_needed=swaps_needed, demand_stations=demand_stations, stations=max(demand_stations, out["cover_stations"]),
               opt_spacing=dirs * L / max(demand_stations, out["cover_stations"]),
               today_per_station=float(cd["today_swap_trucks"]) / float(cd["today_swap_stations"]),
               n_star=swaps * c["e_swap"] / (tr["kwh_day"] * tr["st_share_swappers"]))
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

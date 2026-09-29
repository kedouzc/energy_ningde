"""换电网络的临界密度（第②层"能不能到"，2026-09-29g）。口径：口径/换电网络_临界密度.md。本模块只驱动口径文档读数，不进主链。

问题：换电站要沿干线铺成网，车队才敢买换电车；可铺网的前提是每座站来的车够多、站能保本。
     "够多"的门槛是多少？今天离它多远？够不到的时候，每座站一年要贴多少钱？

算法（每一步都只用已有的层）：
1. 站能承受的每度电站成本（上限）＝ 干线换电车的服务费上限 ＋ 租金一项的利润（均衡层分项定价，按选换电的车的电量加权）。
   换电的站和电池是一家（宁德）的账：租金一项的利润可以用来养站。
2. 保本利用率 ρ*：换电站每度电站成本（供给层 cost_at，含电损、排队区）随利用率下降；解 站成本(ρ*) ＝ 上限。
3. 保本车数 n* ＝ 保本时每天的换电电量 ÷ 每辆换电车每天的用电（它全部的电都经换电站）。
4. 站距上限 s ＝ 满电可用里程 ×（1 − 预留）；每公里通道要有 方向数 ÷ s 座站。
5. 临界密度 ＝ n* × 方向数 ÷ s（每公里通道要有多少辆换电车在跑）；全国 ＝ × 通道总里程。
6. 不够时的亏损：每站来 n 辆车 → 利用率 ρ(n) → 每站每年亏（站成本(ρ) − 上限）× 年电量。
"""
from __future__ import annotations

import equilibrium as E
import supply_routes as SR


def _afford(config: dict) -> dict:
    x = E.class_components(config, "trunk")
    pts = [p for p in x["points"] if p["chosen"]]
    days = float(config["swap_business"]["operating_days"])
    w = sum(p["weight"] for p in pts)
    kwh_day = sum(p["weight"] * p["kwh_year"] for p in pts) / w / days if w else 0.0
    return {"cap": x["fee_cap"] + x["m_rent"], "fee_cap": x["fee_cap"], "m_rent": x["m_rent"], "kwh_day": kwh_day,
            "share": x["share"], "access": x["access"], "fee_cost": x["fee_cost"]}


def station_cost(config: dict, rho: float, w: float) -> float:
    return SR.cost_at(config, "swap", rho, w)["station_cost"]


def breakeven_rho(config: dict, cap: float, w: float) -> float | None:
    """站成本随利用率单调下降（固定成本摊薄），二分求 站成本 ＝ 上限 的利用率；到电量上限还降不到则返回 None。"""
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
    af = _afford(config)
    scenes = config["vehicles"]["heavy"]["scenes"]
    trunk = scenes[1]
    usable_range = float(trunk["onboard_battery_kwh"]) * float(config["swap_business"]["usable_energy_factor"]) / float(trunk["energy_consumption_kwh_km"])
    spacing = usable_range * (1.0 - float(cd["range_reserve"]))
    dirs = float(cd["directions"])
    out = {"afford": af, "w": w, "lane": c["lane"], "e_swap": c["e_swap"], "energy_cap": c["energy"],
           "usable_range": usable_range, "spacing": spacing, "dirs": dirs, "stations_per_km": dirs / spacing}
    rho = breakeven_rho(config, af["cap"], w) if af["kwh_day"] else None
    out["rho"] = rho
    if rho is None:
        out.update(ok=False)
        return out
    swaps = c["lane"] * rho
    kwh_day_station = swaps * c["e_swap"]
    n_star = kwh_day_station / af["kwh_day"]
    density = n_star * dirs / spacing
    L = float(cd["corridor_km_terminal"])
    out.update(ok=True, swaps_day=swaps, kwh_day_station=kwh_day_station, n_star=n_star, density=density,
               national_trucks=density * L, national_stations=dirs * L / spacing,
               today_per_station=float(cd["today_swap_trucks"]) / float(cd["today_swap_stations"]),
               opt_rho=SR.planner_optimum(config, "swap", w)["rho"])
    out["opt_trucks"] = c["lane"] * out["opt_rho"] * c["e_swap"] / af["kwh_day"]
    # 不够时每站每年亏多少
    days = float(config["swap_business"]["operating_days"])
    rows = []
    for n in sorted(set([20, 35, 50, 80, round(n_star), round(out["opt_trucks"])])):
        r = n * af["kwh_day"] / c["e_swap"] / c["lane"]
        if r > min(0.95, c["energy"] / c["lane"]) or r <= 0:
            continue
        sc = station_cost(config, r, w)
        kwh_year = SR.cost_at(config, "swap", r, w)["kwh_year"]
        rows.append({"n": n, "rho": r, "station_cost": sc, "margin": af["cap"] - sc, "profit_wan": (af["cap"] - sc) * kwh_year / 1e4})
    out["loss_rows"] = rows
    return out

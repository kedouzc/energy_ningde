"""均衡层（A5，2026-09-28m）：每类车谁赢、换电的整包价区间与利润厚度（资源口径）。

口径：口径/补能三路线_均衡定价.md；框架：口径/补能路线比较_总框架.md 第三节第 ③ ④ 步。
- 每辆车（场景代表里程 × 里程分布的五个点）比较各路线的全年资源账（demand_routes），选最省的路线。
- 换电赢的车：整包价上限 ＝ 第二名的全年资源账（第二名在竞争下只收成本），下限 ＝ 换电自己的资源账；差 ＝ 利润厚度。
- 第二名的"成本"有两种读法（市场结构，不是参数）：
    可竞争：对手若拿下这批车，可以按它的规划最优利用率建站 → 用供给层规划最优的每度电站成本；
    分散自由进入：充电站各家分散建、实际利用率低 → 充电站按实测利用率（charging_station.utilization_heavy_observed）算每度电站成本。
  换电一侧两种读法都按规划最优（宁德一家规划网络）。
本模块只驱动口径文档读数，不进主链（接入在研究者定了读法之后）。
"""
from __future__ import annotations

import copy

import demand_routes as DR
import supply_routes as SR
from price_response import _km_grid

BASES = ("contestable", "fragmented")
BASIS_CN = {"contestable": "可竞争（对手按最优利用率）", "fragmented": "分散自由进入（充电按实测利用率）"}


def supply_for(config: dict, basis: str) -> dict:
    sup = SR.summary(config)
    if basis == "fragmented":
        u = float(config["charging_station"]["utilization_heavy_observed"])
        pf = float(config["supply_routes"]["charge_power_factor"])
        for k in SR.ROUTES_CHARGE:
            sup["optimum"][k] = SR.cost_at(config, k, min(0.95, u / pf), sup["w"])
    return sup


def scene_equilibrium(config: dict, scene_idx: int, basis: str) -> dict:
    sup = supply_for(config, basis)
    routes = DR.ROUTE_KEYS if scene_idx == 0 else ("conventional", "megawatt", "swap")
    share = margin_w = margin_kwh_w = 0.0
    pts = []
    for m, w in _km_grid(config):
        cc = copy.deepcopy(config)
        sc = cc["vehicles"]["heavy"]["scenes"][scene_idx]
        sc["daily_km"] = float(sc["daily_km"]) * m
        rows = {rt: DR.scene_route(cc, scene_idx, rt, sup) for rt in routes}
        order = sorted(rows.values(), key=lambda d: d["total_wan"])
        best, second = order[0], order[1]
        kwh_year = best["daily_kwh"] * float(cc["swap_business"]["operating_days"])
        win = best["route"] == "swap"
        mg = (second["total_wan"] - best["total_wan"]) if win else 0.0
        if win:
            share += w
            margin_w += w * mg
            margin_kwh_w += w * mg * 1e4 / kwh_year
        pts.append({"m": m, "km": float(sc["daily_km"]), "winner": best["route"], "second": second["route"],
                    "swap": rows["swap"]["total_wan"], "second_total": second["total_wan"], "margin_wan": mg,
                    "margin_kwh": mg * 1e4 / kwh_year if win else 0.0, "rows": rows})
    return {"share": share, "margin_wan": margin_w / share if share else 0.0,
            "margin_kwh": margin_kwh_w / share if share else 0.0, "points": pts}


def scenario_configs(config: dict) -> dict:
    from config_loader import SCENARIO_ORDER, apply_scenario, cloned_config, load_drivers
    drivers = load_drivers(config)
    out = {}
    for tier in SCENARIO_ORDER:
        c = cloned_config(config)
        apply_scenario(c, drivers, tier)
        out[tier] = c
    return out

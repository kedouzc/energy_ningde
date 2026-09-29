"""均衡层（A5，2026-09-28m）：每类车谁赢、换电的整包价区间与利润厚度（资源口径）。

口径：口径/补能三路线_均衡定价.md；框架：口径/补能路线比较_总框架.md 第三节第 ③ ④ 步。
- 每辆车（场景代表里程 × 里程分布的五个点）比较各路线的全年资源账（demand_routes），选最省的路线。
- 换电赢的车：整包价上限 ＝ 第二名的全年资源账（第二名在竞争下只收成本），下限 ＝ 换电自己的资源账；差 ＝ 利润厚度。
- 终局（兑现年）稳态：车队不再换路线、运营商不再进出、站数与需求匹配；各路线都跑在自己的规划最优利用率（研究者 2026-09-28 确认）。
  今天的充电站实测利用率只作敏感性（basis="observed"）。
- 车型分两类：封闭短途多班倒（scene 0）；干线（scene 1、2 是同一批路与站上的两个日里程代表点，合并按权重抽样）。
本模块只驱动口径文档读数，不进主链。
"""
from __future__ import annotations

import copy

import demand_routes as DR
import supply_routes as SR
from price_response import _km_grid

BASES = ("optimal", "observed")
BASIS_CN = {"optimal": "终局：各路线按最优利用率（基准）", "observed": "敏感性：充电站按今天实测利用率"}
CLASSES = {"short": ((0, 1.0),), "trunk": ((1, None), (2, None))}   # None ＝ 按场景权重


def supply_for(config: dict, basis: str) -> dict:
    sup = SR.summary(config)
    if basis == "observed":
        u = float(config["charging_station"]["utilization_heavy_observed"])
        pf = float(config["supply_routes"]["charge_power_factor"])
        for k in SR.ROUTES_CHARGE:
            sup["optimum"][k] = SR.cost_at(config, k, min(0.95, u / pf), sup["w"])
    return sup


def class_equilibrium(config: dict, cls: str, basis: str = "optimal") -> dict:
    """一类车（short／trunk）的均衡：按里程分布逐车比较；干线把两个代表点按场景权重合并。"""
    sup = supply_for(config, basis)
    scenes = config["vehicles"]["heavy"]["scenes"]
    members = CLASSES[cls]
    wsum = sum(float(scenes[i]["weight"]) for i, _ in members)
    share = margin_w = margin_kwh_w = price_w = cost_w = 0.0
    setters: dict = {}
    access_w = 0.0
    pts = []
    for scene_idx, fixed_w in members:
        sw = fixed_w if fixed_w is not None else float(scenes[scene_idx]["weight"]) / wsum
        access_w += sw * float(scenes[scene_idx]["swap_share_ceiling"])
        routes = DR.ROUTE_KEYS if scene_idx == 0 else ("conventional", "megawatt", "swap")
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
            ww = w * sw
            if win:
                sr = rows["swap"]
                share += ww
                margin_w += ww * mg
                margin_kwh_w += ww * mg * 1e4 / kwh_year
                # 换电向车队收的整包（不含电费）＝ 第二名全年资源账 − 车队自己承担的时间与车端溢价
                price_w += ww * (second["total_wan"] - sr["time_wan"] - sr["extra_wan"]) * 1e4 / kwh_year
                cost_w += ww * (sr["facility_wan"] + sr["battery_wan"]) * 1e4 / kwh_year
                setters[second["route"]] = setters.get(second["route"], 0.0) + ww
            pts.append({"scene": scene_idx, "km": float(sc["daily_km"]), "weight": ww, "winner": best["route"], "second": second["route"],
                        "swap": rows["swap"]["total_wan"], "best_total": best["total_wan"], "second_total": second["total_wan"],
                        "margin_wan": mg, "margin_kwh": mg * 1e4 / kwh_year if win else 0.0, "rows": rows})
    # 统一价（研究者 2026-09-29）：价格由充电体系内部竞争定下——每辆车的充电替代（兆瓦或常规，取它最省的那条）
    # 折成"车队愿付给换电的整包价"（不含电费）＝（替代的全年资源账 − 换电车自己承担的时间与车端溢价）÷ 年用电；
    # 这一类车的价 ＝ 这些值按电量加权的平均；换电跟随这个价，只服务自己成本低于这个价的车。
    num = den = 0.0
    alt_mix: dict = {}
    for p in pts:
        sr = p["rows"]["swap"]
        kwh = sr["daily_kwh"] * float(config["swap_business"]["operating_days"])
        alts = {k: v for k, v in p["rows"].items() if k != "swap"}
        ak = min(alts, key=lambda k: alts[k]["total_wan"])
        p["alt"] = ak
        p["wtp_kwh"] = (alts[ak]["total_wan"] - sr["time_wan"] - sr["extra_wan"]) * 1e4 / kwh
        p["swap_cost_kwh"] = (sr["facility_wan"] + sr["battery_wan"]) * 1e4 / kwh
        p["kwh"] = kwh
        num += p["weight"] * kwh * p["wtp_kwh"]; den += p["weight"] * kwh
        alt_mix[ak] = alt_mix.get(ak, 0.0) + p["weight"] * kwh
    price = num / den if den else 0.0
    u_share = u_mw = u_kwh = u_cost = 0.0
    for p in pts:
        p["served"] = p["swap_cost_kwh"] < price
        if p["served"]:
            u_share += p["weight"]
            u_kwh += p["weight"] * p["kwh"]
            u_cost += p["weight"] * p["kwh"] * p["swap_cost_kwh"]
    u_cost_kwh = u_cost / u_kwh if u_kwh else 0.0
    return {"share": share, "margin_wan": margin_w / share if share else 0.0,
            "margin_kwh": margin_kwh_w / share if share else 0.0,
            "price_kwh": price_w / share if share else 0.0, "cost_kwh": cost_w / share if share else 0.0,
            "setters": {k: v / share for k, v in setters.items()} if share else {},
            "access": access_w, "market_share": access_w * share,
            "u_price": price, "u_alt_mix": {k: v / den for k, v in alt_mix.items()} if den else {},
            "u_share": u_share, "u_cost_kwh": u_cost_kwh, "u_margin_kwh": price - u_cost_kwh if u_kwh else 0.0,
            "u_market_share": access_w * u_share,
            "points": sorted(pts, key=lambda p: p["km"])}


CLASS_CN = {"short": "封闭短途多班倒", "trunk": "干线"}


def class_weights(config: dict) -> dict:
    sc = config["vehicles"]["heavy"]["scenes"]
    return {"short": float(sc[0]["weight"]), "trunk": float(sc[1]["weight"]) + float(sc[2]["weight"])}


def scenario_configs(config: dict) -> dict:
    from config_loader import SCENARIO_ORDER, apply_scenario, cloned_config, load_drivers
    drivers = load_drivers(config)
    out = {}
    for tier in SCENARIO_ORDER:
        c = cloned_config(config)
        apply_scenario(c, drivers, tier)
        out[tier] = c
    return out

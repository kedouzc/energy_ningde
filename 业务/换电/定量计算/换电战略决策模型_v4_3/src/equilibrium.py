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


# ---------------------------------------------------------------------------
# 分项跟平（2026-09-29e，已定判断第 1、2、3、7 条）：账单账口径
# 服务费：上限 ＝ 车队最省的充电替代的每度电站成本（途中那部分按兆瓦或常规、夜里按常规慢充，与资源账同一设施口径）＋ 时间差；
#         换电成本 ＝ 换电站每度电成本（含站内周转电池）。
# 租金：  上限 ＝ 替代路线车上电池的持有成本（含购置税），有租赁商时取 min（租赁商保本，低息车队自买），没有时取低息车队自买；
#         换电成本 ＝ 电池银行持有车上那块换电包（不交购置税、池里慢充延寿），资金按 WACC。
# 换电服务这辆车 ＝ 两项利润之和 > 0；车队选换电 ＝ 换电车自己承担的时间 ＋ 车端溢价不高于充电替代（价格到上限时车队两边一样，按选换电计）。
# 电费各家同价，不列。
# ---------------------------------------------------------------------------
LESSOR_STATES = (True, False)
LESSOR_CN = {True: "租赁商在场", False: "租赁商不在场"}


def _rent_year(config: dict, kwh: float, kind: str, life: float, rate: float, tax: float, resale: float, hold: float) -> float:
    from derived import battery_hold_month, sale_price_ratio
    return 12.0 * battery_hold_month(kwh, DR.pack_price(config, kind), tax, rate, life, resale, hold, sale_price_ratio(config, life))


def component_point(config: dict, scene_idx: int, sup: dict, lessor: bool = True, time_premium: bool = True) -> dict:
    from derived import fleet_resale_ratio, retirement_recovery_ratio
    tco = config["tco_jpm"]
    sc = config["vehicles"]["heavy"]["scenes"][scene_idx]
    kwh_bat = float(sc["onboard_battery_kwh"])
    days = float(config["swap_business"]["operating_days"])
    tax = float(tco.get("purchase_tax_rate") or 0.0)
    r_les, r_low = float(tco["lessor_capital_rate"]), float(tco["fleet_discount_rate_low"])
    r_bank = float(config["finance"]["wacc"])
    bank_res, fleet_res = retirement_recovery_ratio(config), fleet_resale_ratio(config)
    pool_hold, fleet_hold = float(tco["pool_hold_rmb_kwh_year"]), float(tco["fleet_battery_hold_rmb_kwh_year"])
    rows = {rt: DR.scene_route(config, scene_idx, rt, sup) for rt in ("conventional", "megawatt", "swap")}
    kwh_year = rows["swap"]["daily_kwh"] * days
    alts = {}
    for k in ("conventional", "megawatt"):
        rw = rows[k]
        kind = "megawatt" if k == "megawatt" else "plain"
        les = _rent_year(config, kwh_bat, kind, rw["battery_life"], r_les, tax, bank_res, pool_hold)
        own = _rent_year(config, kwh_bat, kind, rw["battery_life"], r_low, tax, fleet_res, fleet_hold)
        rent = min(les, own) if lessor else own
        fee = rw["facility_wan"] * 1e4
        alts[k] = {"fee": fee, "rent": rent, "lessor": les, "own": own, "rent_src": "租赁商" if (lessor and les <= own) else "车队自买",
                   "time": rw["time_wan"] * 1e4, "bill": fee + rent + rw["time_wan"] * 1e4}
    ak = min(alts, key=lambda k: alts[k]["bill"])
    a = alts[ak]
    sw = rows["swap"]
    s_fee = sw["facility_wan"] * 1e4
    s_rent = _rent_year(config, kwh_bat, "swap", sw["battery_life"], r_bank, 0.0, bank_res, pool_hold)
    # 时间差：车队走充电替代比走换电多花的时间与车端溢价（元/年，与车队总账同一笔时间账）。服务费上限 ＝ 充电服务费 ＋ 时间差（已定判断第 2 条，DECISIONS 2026-09-29f）；
    # 对手为兆瓦超充时时间差约为零，即跟平。time_premium＝False 只作对照。
    dt = a["time"] - (sw["time_wan"] + sw["extra_wan"]) * 1e4
    prem = max(0.0, dt) if time_premium else 0.0
    m_fee, m_rent = a["fee"] + prem - s_fee, a["rent"] - s_rent
    served = (m_fee + m_rent) > 0
    prefers = dt >= -1e-6
    return {"km": float(sc["daily_km"]), "kwh_year": kwh_year, "alt": ak, "alt_rent_src": a["rent_src"],
            "fee_cap": (a["fee"] + prem) / kwh_year, "fee_base": a["fee"] / kwh_year, "time_gap_kwh": dt / kwh_year, "fee_cost": s_fee / kwh_year,
            "rent_cap": a["rent"] / kwh_year, "rent_cost": s_rent / kwh_year,
            "rent_cap_month_kwh": a["rent"] / 12.0 / kwh_bat, "rent_cost_month_kwh": s_rent / 12.0 / kwh_bat,
            "lessor_year": a["lessor"], "own_year": a["own"],
            "m_fee": m_fee / kwh_year, "m_rent": m_rent / kwh_year, "m_kwh": (m_fee + m_rent) / kwh_year,
            "m_wan": (m_fee + m_rent) / 1e4, "served": served, "prefers": prefers, "chosen": served and prefers,
            "time_swap_wan": sw["time_wan"] + sw["extra_wan"], "time_alt_wan": a["time"] / 1e4,
            "swap_life": sw["battery_life"], "alt_life": rows[ak]["battery_life"]}


def class_components(config: dict, cls: str, basis: str = "optimal", lessor: bool = True, time_premium: bool = True) -> dict:
    """一类车的分项跟平均衡：逐车（里程分布）算两项上限、两项换电成本、利润与是否被选。"""
    sup = supply_for(config, basis)
    scenes = config["vehicles"]["heavy"]["scenes"]
    members = CLASSES[cls]
    wsum = sum(float(scenes[i]["weight"]) for i, _ in members)
    pts, access = [], 0.0
    for scene_idx, fixed_w in members:
        sw = fixed_w if fixed_w is not None else float(scenes[scene_idx]["weight"]) / wsum
        access += sw * float(scenes[scene_idx]["swap_share_ceiling"])
        for m, w in _km_grid(config):
            cc = copy.deepcopy(config)
            cc["vehicles"]["heavy"]["scenes"][scene_idx]["daily_km"] = float(scenes[scene_idx]["daily_km"]) * m
            p = component_point(cc, scene_idx, sup, lessor, time_premium)
            p["weight"] = w * sw
            pts.append(p)
    ch = [p for p in pts if p["chosen"]]
    share = sum(p["weight"] for p in ch)
    ekwh = sum(p["weight"] * p["kwh_year"] for p in ch)

    def avg(key: str, sel: list) -> float:
        d = sum(p["weight"] * p["kwh_year"] for p in sel)
        return sum(p["weight"] * p["kwh_year"] * p[key] for p in sel) / d if d else 0.0
    fee_setter: dict = {}
    rent_setter: dict = {}
    for p in ch:
        e = p["weight"] * p["kwh_year"]
        fee_setter[p["alt"]] = fee_setter.get(p["alt"], 0.0) + e / ekwh
        rent_setter[p["alt_rent_src"]] = rent_setter.get(p["alt_rent_src"], 0.0) + e / ekwh
    return {"points": sorted(pts, key=lambda p: p["km"]), "share": share, "access": access, "market_share": access * share,
            "fee_setter": fee_setter, "rent_setter": rent_setter,
            "served_share": sum(p["weight"] for p in pts if p["served"]),
            "fee_cap": avg("fee_cap", ch), "fee_cost": avg("fee_cost", ch), "rent_cap": avg("rent_cap", ch), "rent_cost": avg("rent_cost", ch),
            "m_fee": avg("m_fee", ch), "m_rent": avg("m_rent", ch), "m_kwh": avg("m_kwh", ch),
            "m_wan": sum(p["weight"] * p["m_wan"] for p in ch) / share if share else 0.0, "kwh_w": ekwh}


def leakage_margin(res: dict, leak: float) -> float:
    """套利漏损：换电车有 leak 比例的电在别处充，这部分丢掉服务费一项的利润（租金按电池自记电量照收）。"""
    return res["m_kwh"] - leak * res["m_fee"]

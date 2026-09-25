"""价格 → 净优势 → 份额：重卡换电份额 ＝ 换电份额天花板 × 算得过账的车队占比（2026-09-22 · 门② 重写）。

【为什么重写】2026-09-18g 版的份额链"按基准价归一、基准处乘数恒为 1"：配置里的渗透率
（短途 30%／中途 50%／长途 70%，加权 44.8%）在基准价上从来没被检验过——门① 逐群核对发现，
月租 13.3 下长途只有约 3% 的车队算得过账，模型却假设 70%（门① 一页纸第 2 节第四条）。

【现在的链条】
    两段价租金（保底＋超出按度）／服务费／充电价 → 本场景用户账（tco.build_scene_economics）
      → 按车队借钱成本三群（[fleet_capital_mix]），净优势为正的那部分车队占比（＝算得过账的占比）
      → 场景份额 ＝ 换电份额天花板（vehicles.heavy.scenes.*.swap_share_ceiling）× 算得过账的占比
      → 写进 swap_penetration，供规模链使用

【三条口径】
1. **天花板由站网与车型定，不由价格定。**车队全都算得过账时，换电最多能拿到的份额；三档见 [drivers.swap_share_ceiling]。
2. **算得过账的占比只依赖配置**（服务费、两段价、寿命），不依赖规模——所以在装配规模之前一次算定，不用探针、不迭代。
3. **下限 response_floor**：封闭短倒场景的补能方式由场景方定死，不随资金成本逐年重选，占比不低于它。
车队资金成本分布是经验假设（[fleet_capital_mix] 声明段），低置信度。
"""
from __future__ import annotations

from copy import deepcopy

_TIERS = ("low", "mid", "high")
_FIELDS = (("short", "短途"), ("mid", "中途"), ("long", "长途"))


def _break_even_rate(rates: list[float], adv: list[float]) -> float | None:
    """净优势由负转正落在哪个资金成本上。

    净优势对资金成本单调上升（车队的钱越贵，省下的首付越值钱），所以最多穿越一次。
    三档之间线性插值；三档全正返回 -inf（"全都够"）。

    【三档全负不能直接判"一个都不够"】那会让可服务份额在最高一档穿零的瞬间掉掉整整一档的权重，
    造出一个纯属算法的断崖。按最后一段的斜率把穿越点**外推**到三档之外，
    再交给 `_addressable` 的尾巴段线性走到零——两处配套，缺一处断崖就回来。
    """
    if all(a > 0 for a in adv):
        return float("-inf")
    if all(a <= 0 for a in adv):
        if len(adv) >= 2 and rates[-1] != rates[-2]:
            slope = (adv[-1] - adv[-2]) / (rates[-1] - rates[-2])
            if slope > 0:
                return rates[-1] + (-adv[-1]) / slope
        return float("inf")
    for i in range(len(adv) - 1):
        a0, a1 = adv[i], adv[i + 1]
        if a0 <= 0 < a1:
            span = a1 - a0
            return rates[i] + (rates[i + 1] - rates[i]) * (-a0 / span) if span else rates[i]
    return None


def _addressable(mix: list[tuple[float, float]], r_star: float | None) -> float:
    """资金成本高于 r* 的那部分车队占比。

    把三档当作车队分布上的三个点：资金成本 ≥ 低档的是全部（1.0），≥ 中档的是中＋高两档之和，
    ≥ 高档的只剩高档自己。两点之间线性插值。

    【最高一档必须带一条尾巴，否则会凭空造出一个台阶】
    如果"高档以上直接归零"，那么 r* 从略低于高档挪到略高于高档时，可服务份额会**一次性掉掉整个高档的权重**
    （按当前权重是 30 个百分点），下游渗透率随之出现一个纯属插值方式造成的断崖——那是算法的假象，不是车队的行为。
    真实情况是**最高一档本来就不是一个点**：个体司机与中小物流的资金成本是分散的，高档只是它的代表值。
    没有分布数据，就假定这条尾巴的宽度与下一档的间距相当（即延伸到 高档 ＋（高档 − 中档）），
    份额在尾巴上线性走到零。**这是一个声明的平滑约定，不是测算**；它不影响基准
    （基准处 r* 落在低档与中档之间），只影响价格拉得很远时那一段的形状。
    """
    if r_star is None or r_star == float("inf"):
        return 0.0
    if r_star == float("-inf"):
        return 1.0
    rates = [r for r, _ in mix]
    weights = [w for _, w in mix]
    total = sum(weights) or 1.0
    # S(r_i) ＝ 第 i 档及其以上的权重之和
    surv = [sum(weights[i:]) / total for i in range(len(weights))]
    if r_star <= rates[0]:
        return 1.0
    tail_end = rates[-1] + (rates[-1] - rates[-2] if len(rates) >= 2 else 0.0)
    if r_star >= tail_end:
        return 0.0
    if r_star >= rates[-1]:
        span = tail_end - rates[-1]
        if not span:
            return 0.0
        return surv[-1] * (1.0 - (r_star - rates[-1]) / span)
    for i in range(len(rates) - 1):
        if rates[i] <= r_star <= rates[i + 1]:
            span = rates[i + 1] - rates[i]
            if not span:
                return surv[i]
            t = (r_star - rates[i]) / span
            lo = 1.0 if i == 0 else surv[i]
            return lo + (surv[i + 1] - lo) * t
    return 0.0


def _km_grid(config: dict) -> list[tuple[float, float]]:
    """场景内日里程的分布：以场景代表里程为中心、左右各 spread 的均匀分布，取 points 个等权点。
    声明的平滑约定（没有分场景的里程分布统计），敏感性见 口径/车队总账 第五节。"""
    sm = config.get("share_model") or {}
    spread = float(sm.get("km_spread", 0.4))
    n = int(sm.get("km_points", 5))
    if n <= 1 or spread <= 0:
        return [(1.0, 1.0)]
    return [(1.0 - spread + 2.0 * spread * i / (n - 1), 1.0 / n) for i in range(n)]


def system_fraction(config: dict, cfg_sc: dict, tv_mw_year_wan: float, spot_relief_wan: float = 0.0) -> dict:
    """这个场景里，系统（电池银行）能以低于车队最便宜替代的成本服务的车占比。

    定价按车型套餐限价：每类车付它自己的最便宜替代，所以**谁会选换电只取决于系统成本能不能低于它的替代**，
    与代表车的两段价无关。逐车比较（日里程分布 × 车队资金成本三群）：
        换电的系统成本 ＝ 电池银行保本（车上电量 ×（1＋这类车分摊的周转比例），池里寿命，银行资金成本，免购置税）
        替代 ＝ min（车队自买：借 r、交购置税、车上寿命、自己卖旧电池；租赁商：7.5%、交购置税、车上寿命）
        净优势 ＝ 替代 − 换电系统成本 ＋ 兆瓦超充多停的时间价值（按里程等比）
    服务费两边跟平、电价两边相同，互相抵掉。"""
    from derived import (battery_hold_month, fleet_resale_ratio, retirement_recovery_ratio, sale_price_ratio,
                         terminal_battery_price, onboard_price_ratio, turnover_ratio)
    tco = config.get("tco_jpm") or {}
    life = config["battery_life_model"]
    sb = config.get("swap_business") or {}
    days = float(sb.get("operating_days") or 0.0)
    cap_y = float(life.get("calendar_cap_years") or 10.0)
    car_cycles = float(life["critical_cycles"])
    pool_cycles = car_cycles * float(life.get("pool_life_multiplier") or 1.0)
    price = terminal_battery_price(config)
    onb = onboard_price_ratio(config)
    tax = float(tco.get("purchase_tax_rate") or 0.0)
    r_bank = float(config["finance"]["wacc"])
    r_les = float(tco.get("lessor_capital_rate") or 0.0)
    rates = [float(tco.get(f"fleet_discount_rate_{t}") or 0.0) for t in _TIERS]
    mix_cfg = config.get("fleet_capital_mix") or {}
    mix = [(rates[i], float(mix_cfg.get(t) or 0.0)) for i, t in enumerate(_TIERS)]
    bank_res, fleet_res = retirement_recovery_ratio(config), fleet_resale_ratio(config)
    pool_hold = float(tco.get("pool_hold_rmb_kwh_year") or 0.0)
    fleet_hold = float(tco.get("fleet_battery_hold_rmb_kwh_year") or 0.0)
    band = float((config.get("price_response") or {}).get("lessor_band_wan") or 0.5)
    floor = float((config.get("price_response") or {}).get("response_floor") or 0.0)
    kwh = float(cfg_sc["onboard_battery_kwh"])
    regime = str(cfg_sc.get("charge_regime") or "megawatt")
    frac = frac_spot = 0.0
    pts = []
    for m, w in _km_grid(config):
        km = float(cfg_sc["daily_km"]) * m
        cpy = km * float(cfg_sc["energy_consumption_kwh_km"]) * days / kwh if kwh else 0.0
        if cpy <= 0:
            continue
        y_pool = min(pool_cycles / cpy, cap_y)
        y_car = min(car_cycles / cpy, cap_y)
        if regime in ("depot", "depot_rotation"):
            y_car = y_pool                 # 场站慢充不伤电池
        turn = turnover_ratio(config, cfg_sc, km)
        bank = 12.0 * battery_hold_month(kwh * (1.0 + turn), price, 0.0, r_bank, y_pool, bank_res, pool_hold,
                                         sale_price_ratio(config, y_pool)) / 1e4
        les = 12.0 * battery_hold_month(kwh, price * onb, tax, r_les, y_car, bank_res, pool_hold,
                                        sale_price_ratio(config, y_car)) / 1e4
        own = [12.0 * battery_hold_month(kwh, price * onb, tax, r, y_car, fleet_res, fleet_hold,
                                         sale_price_ratio(config, y_car)) / 1e4 for r in rates]
        tv = tv_mw_year_wan * m
        adv = [o + tv - bank for o in own]
        adv_les = les + tv - bank
        f_les = max(0.0, min(1.0, 1.0 + adv_les / band))
        a = max(floor, _addressable(mix, _break_even_rate(rates, adv)) * f_les)
        frac += w * a
        # 压力档：充电服务费停在价格战现价（充电每年少付 spot_relief，按里程等比），替代更便宜
        rel = spot_relief_wan * m
        f_les_s = max(0.0, min(1.0, 1.0 + (adv_les - rel) / band))
        frac_spot += w * max(floor, _addressable(mix, _break_even_rate(rates, [x - rel for x in adv])) * f_les_s)
        pts.append({"km": km, "bank_wan": bank, "lessor_wan": les, "own_wan": own, "tv_wan": tv, "fraction": a})
    return {"fraction": frac, "fraction_spot": frac_spot, "points": pts}


def compute_response(config: dict, heavy) -> dict | None:
    """给出每个重卡场景的"算得过账的车队占比"与份额。heavy 为 tco.build_scene_economics 的结果。

    返回 None 表示这条链没接上（缺配置），调用方按天花板直接用、并在页面标出，绝不静默拍一个数。
    """
    mix_cfg = config.get("fleet_capital_mix")
    tco = config.get("tco_jpm") or {}
    if heavy is None or not mix_cfg:
        return None
    rates = [float(tco.get(f"fleet_discount_rate_{t}") or 0.0) for t in _TIERS]
    mix = [(rates[i], float(mix_cfg.get(t) or 0.0)) for i, t in enumerate(_TIERS)]
    floor = float((config.get("price_response") or {}).get("response_floor") or 0.0)
    heavy_scenes = {s.get("name"): s for s in
                    (config.get("vehicles", {}).get("heavy", {}).get("scenes", []) or [])}
    scenes: dict = {}
    pen = pen_spot = ceil_w = 0.0
    for field, name in _FIELDS:
        sc = getattr(heavy, field, None)
        cfg_sc = heavy_scenes.get(name)
        if sc is None or cfg_sc is None:
            continue
        # 【2026-09-25d】车队选"最便宜的非换电路"：自己买（①，随资金成本变）与超充＋租赁（②，与资金成本无关）取对换电更不利的那个
        les = getattr(sc, "adv_lease", None)
        les_spot = getattr(sc, "adv_lease_spot", None)
        adv_now = [getattr(sc, f"adv_mw_{t}", 0.0) for t in _TIERS]
        # 压力档：充电服务费不在均衡价、而是价格战现价撑满整个持有期（tco.py 已给出这组净优势）
        adv_spot = [getattr(sc, f"adv_mw_spot_{t}", 0.0) for t in _TIERS]
        # 对手②与车队资金成本无关：对全体车队同时成立。换电打平或更便宜（≥0）时全部留下（限价定价：打平算换电赢）；
        # 比租赁商贵时在一个宽 band 的区间里线性流失到零——band 是声明的平滑约定（与 _addressable 的尾巴同理），不是测算。
        band = float((config.get("price_response") or {}).get("lessor_band_wan") or 0.5)
        f_now = 1.0 if les is None else max(0.0, min(1.0, 1.0 + les / band))
        f_spot = 1.0 if les_spot is None else max(0.0, min(1.0, 1.0 + les_spot / band))
        a_now = max(floor, _addressable(mix, _break_even_rate(rates, adv_now)) * f_now)
        a_spot = max(floor, _addressable(mix, _break_even_rate(rates, adv_spot)) * f_spot)
        # 【2026-09-24】删去 09-23 的 share_price_insensitive（份额恒为 1）：多班倒车的替代品是
        # 自备两套电池场站轮换，由 tco.py 的 charge_regime="depot_rotation" 表达，份额照常算。
        ceiling = float(cfg_sc.get("swap_share_ceiling", cfg_sc.get("swap_penetration")) or 0.0)
        w = float(cfg_sc.get("weight") or 0.0)
        # 【2026-09-26】份额 ＝ 可及比例（天花板字段，现义：短途＝多班倒封闭场景占比，中长途＝干线运力覆盖）
        #   × 系统能以低于替代的成本服务的车占比（逐车：里程分布 × 资金成本三群）。代表车在现行两段价下的账（a_now）只作读数。
        _relief = float(getattr(sc, "gap_service_spot_year_wan", 0.0) or 0.0) - float(getattr(sc, "gap_service_year_wan", 0.0) or 0.0)
        sysf = system_fraction(config, cfg_sc, float(getattr(sc, "tv_mw_year_wan", 0.0) or 0.0), _relief)
        a_sys = sysf["fraction"]
        a_spot = sysf["fraction_spot"]
        scenes[name] = {
            "ceiling": ceiling,
            "addressable": a_sys,
            "addressable_tariff": a_now,
            "system_points": sysf["points"],
            "penetration": min(1.0, ceiling * a_sys),
            "addressable_spot": a_spot,
            # 现价压力档的占比相对基准剩几成（名字沿用旧读数"份额乘数"）
            "multiplier": a_sys,
            "multiplier_spot": (a_spot / a_sys) if a_sys else 0.0,
            "lessor_factor": f_now,
        }
        pen += w * scenes[name]["penetration"]
        pen_spot += w * min(1.0, ceiling * a_spot)
        ceil_w += w * ceiling
    if not scenes:
        return None
    # 【2026-09-25f · 供给侧】站网能服务多少车：兑现年换电重卡（全体运营商）的日换电需求不能超过站网能力。
    # 站网能力 ＝ 兑现年全体运营商重卡换电站数 × 单站规划能力（次/日）；站数 ＝ 2026 年底存量 ＋ 年新建 × 年数。
    # 需求超过能力时，各场景份额按同一比例压下（天花板仍是上限）。口径：口径/车辆与站数_推算方法 供给侧一节。
    pen_demand = pen
    net = network_limit(config, scenes, heavy_scenes)
    if net is not None:
        f = net["factor"]
        pen = pen_spot = 0.0
        for name, info in scenes.items():
            w = float(heavy_scenes[name].get("weight") or 0.0)
            info["penetration_demand"] = info["penetration"]
            info["penetration"] = info["penetration"] * f
            pen += w * info["penetration"]
            pen_spot += w * min(1.0, info["ceiling"] * info["addressable_spot"]) * f
    return {
        "scenes": scenes,
        "weighted_penetration": pen,
        "weighted_penetration_spot": pen_spot,
        "weighted_ceiling": ceil_w,
        "network": net,
        "weighted_penetration_demand": pen_demand,
    }


def network_limit(config: dict, scenes: dict, heavy_scenes: dict) -> dict | None:
    """兑现年站网能力对换电重卡份额的约束（全体运营商口径）。"""
    sup = config.get("supply_network")
    if not sup:
        return None
    heavy = config.get("vehicles", {}).get("heavy", {}) or {}
    years = [int(y) for y in (config.get("construction") or {}).get("years", [])]
    nev = list(heavy.get("nev_rates") or [])
    if not years or len(nev) != len(years):
        return None
    annual = float(heavy.get("stock_wan") or 0.0) / float(heavy.get("replacement_cycle_years") or 1.0)
    bev = float(heavy.get("pure_electric_share") or 1.0)
    usable = float((config.get("swap_business") or {}).get("usable_energy_factor") or 0.8)
    demand = trucks = 0.0
    by = {}
    for name, info in scenes.items():
        sc = heavy_scenes[name]
        cum_ev = sum(annual * r * bev for r in nev) * float(sc.get("weight") or 0.0)
        freq = float(sc["daily_km"]) * float(sc["energy_consumption_kwh_km"]) / (float(sc["onboard_battery_kwh"]) * usable)
        t = cum_ev * info["penetration"]
        trucks += t
        demand += t * freq
        by[name] = {"cum_ev_wan": cum_ev, "swap_trucks_wan": t, "swaps_per_day": freq}
    n_years = years[-1] - int(sup.get("base_year", 2026))
    base = float(sup["stations_base_all"])
    plan = base + float(sup["qiji_plan_2030"]) - float(sup["qiji_stations_base"])   # 已公布规划下的兑现年站数
    cap_station = float(config["stations"]["qiji75_trunk"]["planning_daily_capacity"])
    demand_wan = demand                               # 万辆 × 次/日 ＝ 万次/日
    need = demand_wan * 1e4 / cap_station             # 按需求建要的站（全体运营商）
    factor_plan = min(1.0, plan * cap_station / 1e4 / demand_wan) if demand_wan > 0 else 1.0
    mode = sup.get("mode", "endogenous")
    factor = factor_plan if mode == "plan" else 1.0   # 内生：过门槛就按需求建；闸门在 model 层核对（gate_check）
    stations = plan if mode == "plan" else max(need, base)
    return {"factor": factor, "factor_plan": factor_plan, "mode": mode, "stations_2030": stations,
            "stations_plan_2030": plan, "stations_needed": need, "capacity_wan_day": stations * cap_station / 1e4,
            "demand_wan_day": demand_wan, "swap_trucks_demand_wan": trucks, "by_scene": by,
            "build_needed_per_year": (need - base) / n_years if n_years else 0.0,
            "build_plan_per_year": (plan - base) / n_years if n_years else 0.0}


def applied_config(config: dict, response: dict | None) -> dict:
    """把"天花板 × 算得过账的占比"写进重卡三场景的 swap_penetration（深拷贝，不改入参）。

    链没接上（response 为 None）时，份额直接取天花板——页面上"算得过账的占比"读数会缺，看得见。
    """
    out = deepcopy(config)
    scenes = (response or {}).get("scenes", {})
    for sc in out.get("vehicles", {}).get("heavy", {}).get("scenes", []) or []:
        ceiling = float(sc.get("swap_share_ceiling", sc.get("swap_penetration")) or 0.0)
        info = scenes.get(sc.get("name"))
        sc["swap_penetration"] = info["penetration"] if info else ceiling
    return out


def effective_config(config: dict) -> tuple[dict, dict | None]:
    """装配前的一站式入口：算用户账 → 算占比 → 写份额。model.py 与 tracker.py 共用，口径只有一个家。"""
    from tco import build_scene_economics   # 局部引入，避免 tco ↔ price_response 循环
    response = compute_response(config, build_scene_economics(config))
    return applied_config(config, response), response

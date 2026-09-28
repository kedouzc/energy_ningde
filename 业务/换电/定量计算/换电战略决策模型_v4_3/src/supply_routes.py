"""补能四条路线的供给成本（A3，2026-09-28g）：纯路线、各按标准规格建站，比每千瓦与每度电。

口径：口径/补能三路线_供给成本.md；框架：口径/补能路线比较_总框架.md。
- 资源账（系统口径，不管谁出钱）：设备、电气（箱变与柜、外线、电缆）、土建、场地、人员、运维、保险、电损；
  换电另加站内电池的持有成本（按电池银行保本价，entities.turnover_rent_rmb_kwh_month）。
- 资本回收按系统 WACC：机电设备按 equipment_life_years，电气与土建按 infra_life_years。
- 规划最优：给定"用户每小时时间价值 w"，选利用率使"每度电的站成本 ＋ 每度电的排队时间成本"最小。
  充电站多桩共用一条队（M/M/c，按服务时长变异系数做 M/G/c 近似修正）；换电一条工位（M/D/1），另受电量上限约束。
- w 目前取现行模型的临时值（A4 用"补运力成本"替换）。
本模块只驱动口径文档的供给层读数，不进主链读数（A5 接入）。
"""
from __future__ import annotations

import math

ROUTES_CHARGE = ("conventional", "highpower", "megawatt")
ROUTES = ROUTES_CHARGE + ("swap",)


def _crf(r: float, n: float) -> float:
    return r / (1.0 - (1.0 + r) ** -n) if r > 0 else 1.0 / n


def _erlang_c(c: int, rho: float) -> float:
    a = c * rho
    s_ = sum(a ** k / math.factorial(k) for k in range(c))
    top = a ** c / math.factorial(c) / (1.0 - rho)
    return top / (s_ + top)


def mgc_wait_hours(c: int, rho: float, service_h: float, cv: float) -> float:
    """M/G/c 平均排队（小时）：Erlang C 的 M/M/c 值 × (1＋cv²)/2。"""
    if rho >= 1.0:
        return float("inf")
    return _erlang_c(c, rho) * service_h / (c * (1.0 - rho)) * (1.0 + cv * cv) / 2.0


def mgc_queue_at_level(c: int, rho: float, level: float) -> int:
    """M/M/c 下排队车数的分位数：P(Lq ≥ k) ＝ P_w × ρ^k（保守，未做 M/G/c 修正）。"""
    pw = _erlang_c(c, rho)
    if pw <= 1.0 - level:
        return 0
    return int(math.ceil(math.log((1.0 - level) / pw) / math.log(rho)))


def md1_queue_at_level(rho: float, level: float, n_max: int = 60) -> int:
    """M/D/1 排队车数的分位数（离开时刻嵌入马氏链，数值解）。"""
    a = [math.exp(-rho)]
    for k in range(1, n_max):
        a.append(a[-1] * rho / k)
    p = [0.0] * n_max
    p[0] = 1.0 - rho
    for j in range(n_max - 1):
        s_ = p[j] - p[0] * a[j] - sum(p[i] * a[j - i + 1] for i in range(1, j + 1))
        p[j + 1] = s_ / a[0]
        if sum(p[: j + 2]) >= level:
            return max(0, j)          # 系统内 ≤ j＋1 辆 → 排队 ≤ j 辆
    return n_max


def provisional_wait_cost(config: dict) -> float:
    """排队时间价值（元/时）：各类车的补运力成本（demand_routes.time_value），按各类车的补能电量加权。
    同一座站服务各类车，排一分钟队的代价按来站的电量结构平均。"""
    import demand_routes as DR
    num = den = 0.0
    for i, sc in enumerate(config["vehicles"]["heavy"]["scenes"]):
        e = float(sc["weight"]) * float(sc["daily_km"]) * float(sc["energy_consumption_kwh_km"])
        num += e * DR.time_value(config, i)["w"]
        den += e
    return num / den


def _common(config: dict) -> dict:
    s = config["supply_routes"]
    return {k: (v if not isinstance(v, dict) else None) for k, v in s.items()}


def station(config: dict, key: str) -> dict:
    """单站的投资（万元）与年固定成本（万元/年，未含随电量变的电损与排队区租金）。"""
    S = config["supply_routes"]
    R = S[key]
    r = float(config["finance"]["wacc"])
    n_eq, n_in = float(S["equipment_life_years"]), float(S["infra_life_years"])
    kva = float(R["kva"])
    transformer = kva * float(S["transformer_rmb_per_kva"]) / 1e4 + int(R["transformer_units"]) * float(S["cabinet_wan_per_unit"])
    external = float(S["external_line_wan"])
    out = {"key": key, "label": R["label"], "kva": kva}
    if key == "swap":
        st = config["stations"]["qiji75_trunk"]
        power_kw = kva                                  # 换电站的"千瓦"取接入容量
        cable = power_kw * float(S["cable_rmb_per_kw"]) / 1e4
        area = float(S["swap_building_m2"]) + float(S["swap_corridor_width_m"]) * (2 * float(S["swap_approach_m"]) + 2 * float(S["end_aisle_m"]))
        blocks, bkwh = float(st["inventory_blocks"]), float(st["block_kwh"])
        import entities
        from derived import battery_price_rmb_kwh
        bat_kwh = blocks * bkwh
        bat_value = bat_kwh * battery_price_rmb_kwh(config, int(config["meta"]["base_year"]) if "meta" in config and "base_year" in config["meta"] else 2026) / 1e4
        bat_hold = bat_kwh * entities.turnover_rent_rmb_kwh_month(config) * 12.0 / 1e4
        om = float(R["om_rate"]) * float(R["equipment_wan"])
        out.update(power_kw=power_kw, bays=1, battery_kwh=bat_kwh, battery_value_wan=bat_value, battery_hold_wan=bat_hold)
    else:
        power_kw = float(R["pile_kw"]) * int(R["piles"])
        cable = power_kw * float(S["cable_rmb_per_kw"]) / 1e4
        area = int(R["piles"]) * float(S["bay_width_m"]) * (float(S["bay_length_m"]) + 2 * float(S["end_aisle_m"])) + float(S["charge_equipment_pad_m2"])
        bat_value = bat_hold = 0.0
        out.update(power_kw=power_kw, bays=int(R["piles"]), battery_kwh=0.0, battery_value_wan=0.0, battery_hold_wan=0.0)
    civil = area * float(S["civil_rmb_per_m2"]) / 1e4
    equipment = float(R["equipment_wan"])
    capex = equipment + transformer + external + cable + civil
    if key != "swap":
        om = float(R["om_rate"]) * capex
    capital = equipment * _crf(r, n_eq) + (transformer + external + cable + civil) * _crf(r, n_in)
    rent = area * float(S["land_rent_rmb_m2_month"]) * 12.0 / 1e4
    insurance = float(S["insurance_rate"]) * (capex + bat_value)
    staff = float(R["fte"]) * float(S["attendant_cost_wan_per_fte"])
    fixed = capital + rent + staff + om + insurance + bat_hold
    out.update(equipment_wan=equipment, transformer_wan=transformer, external_wan=external, cable_wan=cable,
               civil_wan=civil, area_m2=area, capex_wan=capex, capex_per_kw=capex * 1e4 / power_kw,
               capital_wan=capital, rent_wan=rent, staff_wan=staff, fte=float(R["fte"]), om_wan=om,
               insurance_wan=insurance, fixed_wan=fixed)
    return out


def swap_constraints(config: dict) -> dict:
    """换电标准站的两道上限：工位（排队论之前的物理上限）与电量（接入容量 × 充电窗口 ÷ 每次净补电量）。"""
    st = config["stations"]["qiji75_trunk"]
    R = config["supply_routes"]["swap"]
    sb = config["swap_business"]
    hours = float(st["operating_hours_day"])
    mu = 3600.0 / float(st["swap_duration_seconds"])
    lane = hours * mu
    e_swap = int(R["blocks_per_swap"]) * float(st["block_kwh"]) * float(sb["usable_energy_factor"])
    pf = 0.92
    energy_16 = float(R["kva"]) * pf * hours / e_swap
    energy_24 = float(R["kva"]) * pf * 24.0 / e_swap
    return {"lane": lane, "mu": mu, "hours": hours, "e_swap": e_swap, "energy": energy_16, "energy_24h": energy_24,
            "pf": pf, "cap": min(lane, energy_16), "binding": "工位" if lane <= energy_16 else "电量"}


def _power_price(config: dict) -> float:
    return float(config["swap_business"]["valley_power_price_rmb_kwh"])


def cost_at(config: dict, key: str, rho: float, w: float | None = None) -> dict:
    """在给定时间利用率 ρ 下：年电量、每度电站成本（含电损与排队区租金）、每度电排队时间成本。"""
    S = config["supply_routes"]
    w = provisional_wait_cost(config) if w is None else w
    st_ = station(config, key)
    loss = float(config["charging_station"]["loss_rate"]) * _power_price(config)
    lvl = float(S["queue_service_level"])
    if key == "swap":
        c = swap_constraints(config)
        swaps_day = c["lane"] * rho
        kwh_year = swaps_day * c["e_swap"] * float(config["swap_business"]["operating_days"])
        wq_h = rho / (2.0 * c["mu"] * (1.0 - rho))
        e_session = c["e_swap"]
        qn = md1_queue_at_level(rho, lvl)
        sessions_day = swaps_day
        feasible = swaps_day <= c["energy"] + 1e-9
        energy_util = kwh_year / (st_["kva"] * 8760.0)
    else:
        R = S[key]
        cpiles = int(R["piles"])
        s_h = float(R["session_minutes"]) / 60.0
        e_session = float(R["pile_kw"]) * float(S["charge_power_factor"]) * s_h
        hours = float(S["charge_operating_hours"])
        sessions_day = cpiles * rho * hours / s_h
        kwh_year = sessions_day * e_session * 365.0
        wq_h = mgc_wait_hours(cpiles, rho, s_h, float(S["charge_service_cv"]))
        qn = mgc_queue_at_level(cpiles, rho, lvl)
        feasible = True
        energy_util = kwh_year / (st_["power_kw"] * 8760.0)
    q_rent = qn * float(S["queue_m2_per_truck"]) * float(S["land_rent_rmb_m2_month"]) * 12.0 / 1e4
    q_civil = qn * float(S["queue_m2_per_truck"]) * float(S["civil_rmb_per_m2"]) / 1e4 * _crf(float(config["finance"]["wacc"]), float(S["infra_life_years"]))
    station_cost = (st_["fixed_wan"] + q_rent + q_civil) * 1e4 / kwh_year + loss if kwh_year > 0 else float("inf")
    wait_cost = w * wq_h / e_session
    return {"rho": rho, "sessions_day": sessions_day, "kwh_year": kwh_year, "energy_util": energy_util,
            "station_cost": station_cost, "wait_cost": wait_cost, "total": station_cost + wait_cost,
            "wait_min": wq_h * 60.0, "queue_trucks": qn, "feasible": feasible, "w": w}


def planner_optimum(config: dict, key: str, w: float | None = None) -> dict:
    """规划最优：在可行域里扫 ρ，使每度电的"站成本 ＋ 排队时间成本"最小。"""
    w = provisional_wait_cost(config) if w is None else w
    best = None
    for i in range(5, 96):
        res = cost_at(config, key, i / 100.0, w)
        if not res["feasible"]:
            break
        if best is None or res["total"] < best["total"]:
            best = res
    return best


def summary(config: dict) -> dict:
    w = provisional_wait_cost(config)
    return {"w": w, "stations": {k: station(config, k) for k in ROUTES},
            "optimum": {k: planner_optimum(config, k, w) for k in ROUTES},
            "swap_constraints": swap_constraints(config)}

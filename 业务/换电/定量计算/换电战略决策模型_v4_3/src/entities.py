"""站与电池银行分拆：同一个系统，两个投资主体，内部结算。

【为什么要拆】判断"换电能不能赢"看全系统的账；落地时换电站与电池银行要的投入要素不同
（站：站址、电网接入、运维人手；电池银行：长期低成本资金、电池运维与处置），是两类出资人。
所以"站按需求建"的前提不只是系统过门槛，还要**结算之后两个主体各自过自己的门槛**——
站层过不了，合作方不来，网就铺不开。

【分拆与结算原则】（沿用 定性分析/宁德时代_超换一体站_财务模型_修正版.md 第三部分）
1. 收入按服务提供者归属：换电服务费全归换电站；用户电池租金、峰谷套利、辅助服务（来自电池资产）归电池银行。
2. 成本按资产使用者承担：站体折旧、人工、场租、电损归换电站；全部电池（车上 ＋ 站内周转）归电池银行。
3. 周转电池由电池银行持有，**不向换电站收租**：它是电池银行提供"随用随换"租赁服务必须备的库存
   （跨站流通，站买断等于替别人养电池），成本已含在用户电池租金里——租金上沿与电池银行保本价都按
   "车上电量 ×（1＋周转比例）"算。换电站只做换电服务、收服务费，不承担周转电池。
4. 平台软件（找站、调度、监控、数据）由电池银行提供，换电站按站付技术服务费（[entities] tech_fee_wan_station_year）；
   这是调节两边收益分配的旋钮，可行区间随读数给出。
内部结算只是在两个主体之间搬钱，系统合计不变——程序断言这一点。

【门槛】换电站：轻资产运营、独立融资，取 12%（超换一体站模型"换电站目标 IRR 12–15%"的下沿）；
电池银行：系统 WACC（配置 finance.wacc）。回报按"税后现金流覆盖资本回收"反解，与系统覆盖倍数同一口径。
"""
from __future__ import annotations

import math


def _crf(r: float, n: float) -> float:
    return r / (1.0 - (1.0 + r) ** -n) if r > 0 else 1.0 / n


def _coverage(ebitda: float, capital: float, r: float, n: float, tax: float) -> float:
    """税后覆盖倍数：EBITDA ÷ 在回报 r 下回收资本所需的 EBITDA（折旧按直线计税盾）。"""
    if capital <= 0:
        return float("inf")
    need = (capital * _crf(r, n) - capital / n * tax) / (1.0 - tax)
    return ebitda / need if need > 0 else float("inf")


def _irr(ebitda: float, capital: float, n: float, tax: float) -> float:
    """反解：覆盖倍数恰为 1 的回报率。"""
    if capital <= 0 or ebitda <= 0:
        return float("nan")
    lo, hi = 1e-4, 1.5
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if _coverage(ebitda, capital, mid, n, tax) > 1.0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def turnover_rent_rmb_kwh_month(config: dict) -> float:
    """周转电池租金（元/kWh·月）＝ 电池银行持有站内电池的保本价：兑现年电池价、银行资金成本、池里寿命（中途代表车的循环强度）。"""
    from derived import (battery_hold_month, retirement_recovery_ratio, sale_price_ratio,
                         scene_cycles_per_year, terminal_battery_price)
    life = config["battery_life_model"]
    pool_cycles = float(life["critical_cycles"]) * float(life.get("pool_life_multiplier") or 1.0)
    scenes = {s["name"]: s for s in config["vehicles"]["heavy"]["scenes"]}
    sc = scenes.get((config.get("swap_business") or {}).get("rent_ceiling_floor_scene", "中途"))
    cpy = scene_cycles_per_year(config, sc) if sc else 0.0
    years = min(pool_cycles / cpy, float(life.get("calendar_cap_years") or 10.0)) if cpy else float(life.get("calendar_cap_years") or 10.0)
    tco = config.get("tco_jpm") or {}
    return battery_hold_month(1.0, terminal_battery_price(config), 0.0, float(config["finance"]["wacc"]), years,
                              retirement_recovery_ratio(config), float(tco.get("pool_hold_rmb_kwh_year") or 0.0),
                              sale_price_ratio(config, years))


def split(config: dict, snapshot) -> dict:
    """按池拆出换电站与电池银行两本账（兑现年稳态），并给出各自的回报与门槛判断。"""
    sb = snapshot.swap_business
    cx = snapshot.capex
    fin = config["finance"]
    ent = config.get("entities") or {}
    tax = float(fin["tax_rate"])
    n = float(fin.get("model_horizon_years") or 15)
    wacc = float(fin["wacc"])
    r_station = float(ent.get("station_hurdle", 0.12))
    # 周转电池不向换电站收租：它是电池银行为提供"随用随换"的租赁服务必须备的库存，成本已含在用户电池租金里
    # （租金上沿与电池银行保本价都按"车上电量 ×（1＋周转比例）"算）。再向站收一次，等于电池银行向两头各收一遍。
    # 保留保本价的读数，供对照（若周转电池改由站持有，站要多背多少）。
    rate_ref = turnover_rent_rmb_kwh_month(config)
    rate = float(ent.get("turnover_rent_charged", 0.0)) * rate_ref
    # 技术服务费（换电站 → 电池银行，万元/站·年）：APP 平台、电池监控调度、运营技术支持、数据服务打包价。
    # 它是两个主体之间调收益分配的旋钮——调它，让两边都过门槛（见返回值里的可行区间）。
    fee_wan = float(ent.get("tech_fee_wan_station_year", 3.5))
    pools: dict = {}
    n_total = 0.0
    tot = {k: 0.0 for k in ("st_rev", "st_opex", "st_settle", "st_ebitda", "st_capital",
                            "bk_rev", "bk_opex", "bk_ebitda", "bk_capreq", "bk_dep", "sys_ebitda")}
    for pk, p in sb.pool_operations.items():
        body = float(cx.station_body_total_by_pool_yi.get(pk, 0.0))
        turnover = float(p.station_battery_gwh) * rate * 12.0 / 100.0          # GWh × 元/kWh·月 × 12 ÷ 100 ＝ 亿元/年
        st_rev = float(p.service_revenue_yi)
        st_opex = float(p.energy_cost_yi) + float(p.station_rent_yi) + float(p.labor_yi)
        n_st = float(cx.station_targets.get(pk, 0.0))
        tech_fee = n_st * fee_wan / 1e4                                          # 万元/站·年 × 站数 ÷ 1e4 ＝ 亿元/年
        st_settle = turnover + tech_fee
        st_ebitda = st_rev - st_opex - st_settle
        bk_rev = float(p.battery_rent_yi) + float(p.arbitrage_yi) + float(p.ancillary_yi) + st_settle
        bk_opex = (float(p.software_opex_yi) + float(p.insurance_yi) + float(p.pooling_maintenance_yi)
                   + float(p.warehouse_logistics_yi))
        bk_ebitda = bk_rev - bk_opex
        sys_ebitda = float(p.ebitda_yi)
        assert abs(st_ebitda + bk_ebitda - sys_ebitda) < 1e-6 * max(1.0, abs(sys_ebitda)), \
            f"{pk}：内部结算没有配平（站 {st_ebitda} ＋ 银行 {bk_ebitda} ≠ 系统 {sys_ebitda}）"
        # 电池银行的资本回收要求 ＝ 系统的年资本要求 − 站体那一份（站体按 WACC 在寿命期内回收）
        bk_capreq = float(p.required_fcff_yi) - body * _crf(wacc, n)
        bk_dep = float(p.depreciation_yi) - body / n
        bk_need = (bk_capreq - bk_dep * tax) / (1.0 - tax)
        n_total += n_st
        pools[pk] = {
            "station_revenue_yi": st_rev, "station_opex_yi": st_opex, "turnover_rent_yi": turnover,
            "tech_fee_yi": tech_fee, "stations": n_st, "station_ebitda_yi": st_ebitda, "station_capital_yi": body,
            "station_irr": _irr(st_ebitda, body, n, tax),
            "bank_revenue_yi": bk_rev, "bank_opex_yi": bk_opex, "bank_ebitda_yi": bk_ebitda,
            "bank_coverage": bk_ebitda / bk_need if bk_need > 0 else float("inf"),
        }
        for k, v in (("st_rev", st_rev), ("st_opex", st_opex), ("st_settle", st_settle), ("st_ebitda", st_ebitda),
                     ("st_capital", body), ("bk_rev", bk_rev), ("bk_opex", bk_opex), ("bk_ebitda", bk_ebitda),
                     ("bk_capreq", bk_capreq), ("bk_dep", bk_dep), ("sys_ebitda", sys_ebitda)):
            tot[k] += v
    bk_need = (tot["bk_capreq"] - tot["bk_dep"] * tax) / (1.0 - tax)
    bank_cov = tot["bk_ebitda"] / bk_need if bk_need > 0 else float("inf")
    station_irr = _irr(tot["st_ebitda"], tot["st_capital"], n, tax)
    # 电池银行回报：把覆盖倍数按系统同一口径换成回报（CRF 反解，寿命取模型期限）
    bank_irr = _irr_from_coverage(bank_cov, wacc, n)
    # 站层能承受的最低服务费：刚好让换电站回报等于它的门槛（其余不变）
    energy = sum(float(p.annual_energy_yi_kwh) for p in sb.pool_operations.values())
    need_st = (tot["st_capital"] * _crf(r_station, n) - tot["st_capital"] / n * tax) / (1.0 - tax)
    # 可行结算：结算是两个主体谈出来的，不是物理约束。只要站层超出自己门槛的那部分，够补电池银行离门槛的缺口，
    # 就存在一个让两边都过门槛的结算（例如站分担一部分周转电池或站址改建的钱）。闸门看的是这个。
    bank_short = max(0.0, bk_need - tot["bk_ebitda"])
    station_surplus = tot["st_ebitda"] - need_st
    fee_now = float((config.get("swap_business") or {}).get("service_fee_rmb_kwh") or 0.0)
    # 技术服务费的可行区间（万元/站·年）：下限让电池银行刚过门槛，上限让换电站刚过门槛
    fee_min = fee_wan + (bk_need - tot["bk_ebitda"]) * 1e4 / n_total if n_total else float("nan")
    fee_max = fee_wan + station_surplus * 1e4 / n_total if n_total else float("nan")
    fee_floor = fee_now - (tot["st_ebitda"] - need_st) / energy if energy else float("nan")
    return {
        "turnover_rent_rmb_kwh_month": rate, "turnover_rent_ref_rmb_kwh_month": rate_ref,
        "station_hurdle": r_station, "bank_hurdle": wacc,
        "station_ebitda_yi": tot["st_ebitda"], "station_revenue_yi": tot["st_rev"],
        "station_opex_yi": tot["st_opex"], "station_settlement_yi": tot["st_settle"],
        "station_capital_yi": tot["st_capital"], "station_irr": station_irr,
        "station_pass": station_irr >= r_station,
        "bank_ebitda_yi": tot["bk_ebitda"], "bank_revenue_yi": tot["bk_rev"], "bank_opex_yi": tot["bk_opex"],
        "bank_coverage": bank_cov, "bank_irr": bank_irr, "bank_pass": bank_cov >= 1.0,
        "system_ebitda_yi": tot["sys_ebitda"],
        "service_fee_rmb_kwh": fee_now, "station_fee_floor_rmb_kwh": fee_floor,
        "bank_shortfall_yi": bank_short, "station_surplus_yi": station_surplus,
        "feasible": station_surplus >= bank_short,
        "tech_fee_wan": fee_wan, "tech_fee_min_wan": fee_min, "tech_fee_max_wan": fee_max, "stations": n_total,
        "pools": pools,
    }


def _irr_from_coverage(cov: float, wacc: float, n: float) -> float:
    if not math.isfinite(cov):
        return float("nan")
    target = cov * _crf(wacc, n)
    lo, hi = 1e-4, 1.5
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if _crf(mid, n) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0

"""口径文档的现算值：口径/*.src.md 里的表与算式中间量由本模块算，注入由 src/inject.py 统一做（与叙述同一个注入器）。

为什么：口径是「状态」文件，数字必须与模型当下的计算一致。手抄的数一改参数就过期，
而过期没人发现（2026-09-25 车队总账的旧电池卖价就是这样）。所以口径里凡是"模型算出来的数"，
一律写占位符 {{名}}，由本模块从配置与模型现算后注入；只有口径自己的取值（③类，如"取中段"）才手写。

占位符来源两处：
  1. 本模块的计算表 VALUES（车队总账要用的保本价、上沿、拆解、临界线等，与 derived／tco 同一套函数）；
  2. build/facts.json 里的读数（按中文名，由 inject 查）。
找不到的占位符 → 构建失败。
"""
from __future__ import annotations

import copy
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "口径"
PH = re.compile(r"\{\{([^{}]+)\}\}")


def _f(x: float, d: int = 0) -> str:
    return f"{x:,.{d}f}"


def _pct(x: float, d: int = 1) -> str:
    return f"{x * 100:.{d}f}%"


def _irr_from_cov(cov: float, wacc: float = 0.075, n: int = 15) -> float:
    crf = lambda r: r / (1 - (1 + r) ** -n)
    t = cov * crf(wacc)
    lo, hi = 0.0, 0.6
    for _ in range(80):
        m = (lo + hi) / 2
        if crf(m) < t:
            lo = m
        else:
            hi = m
    return lo


def _tier_cfg(config: dict, tier: str) -> dict:
    c = copy.deepcopy(config)
    v = c["drivers"]["battery_life"][tier]
    for k in ("critical_cycles", "pool_life_multiplier"):
        c["battery_life_model"][k] = v[k]
    for k in ("battery_rent_rmb_kwh_month", "battery_rent_per_kwh_rmb"):
        c["swap_business"][k] = v[k]
    return c


def ledger_values(config: dict) -> dict[str, str]:
    """车队总账要用的全部数（中性＝基线；三档＝只换寿命与随之联动的租金）。"""
    from derived import (battery_hold_month as _bhm, battery_price_rmb_kwh, fleet_resale_ratio,
                         rent_ceiling, retirement_recovery_ratio, scene_cycles_per_year, _crf, _sinking,
                         sale_price_ratio, terminal_battery_price, onboard_price_ratio, terminal_year,
                         turnover_ratio)
    from charging import equilibrium_service_fee, supercharge_capex_per_kw

    V: dict[str, str] = {}
    tco = config["tco_jpm"]
    sb = config["swap_business"]
    life = config["battery_life_model"]
    curve = config["construction"]["battery_price_curve"]
    scenes = {s["name"]: s for s in config["vehicles"]["heavy"]["scenes"]}
    price = terminal_battery_price(config)          # 换电块（电池银行）按兑现年买入价
    onb = onboard_price_ratio(config)               # 车上超充电池 ÷ 换电块
    tax = float(tco["purchase_tax_rate"])
    r_bank = float(config["finance"]["wacc"])
    r_les = float(tco["lessor_capital_rate"])
    bank_res = retirement_recovery_ratio(config)
    fleet_res = fleet_resale_ratio(config)
    pool_hold = float(tco["pool_hold_rmb_kwh_year"])
    fleet_hold = float(tco["fleet_battery_hold_rmb_kwh_year"])
    cap = float(life["calendar_cap_years"])
    pool_cycles = float(life["critical_cycles"]) * float(life["pool_life_multiplier"])
    rates = [float(tco[f"fleet_discount_rate_{t}"]) for t in ("low", "mid", "high")]
    days = float(sb["operating_days"])

    # —— 输入 ——
    V["电池价"] = _f(price)
    _p0 = battery_price_rmb_kwh(config, float(config["meta"]["reference_year"]))
    V["基准年电池价"] = _f(_p0)
    V["基准年"] = f"{float(config['meta']['reference_year']):.0f}"
    V["不含电池的车价"] = f"{(float(tco['purchase_price']) - 500.0 * _p0) / 1e4:.1f}"
    V["电池买入年"] = f"{terminal_year(config):.0f}"
    V["车上电池价比"] = f"{onb:.2f}"
    V["购置税"] = _pct(tax, 0)
    V["银行资金成本"] = _pct(r_bank, 1)
    V["租赁商资金成本"] = _pct(r_les, 1)
    V["车队资金成本三群"] = "／".join(_pct(r, 0) for r in rates)
    V["储能对动力价格比"] = f"{float(curve['storage_to_power_price_ratio']):.2f}"
    V["退役剩余容量"] = _pct(float(curve["retirement_soh"]), 0)
    V["二手流动性折价"] = f"{float(curve['secondary_market_discount']):.2f}"
    V["零散卖折扣"] = f"{float(tco['fleet_scatter_discount']):.2f}"
    V["银行旧电池卖价"] = _pct(bank_res, 1)
    V["车队旧电池卖价"] = _pct(fleet_res, 1)
    V["池保险维护"] = f"{pool_hold:.2f}"
    V["车队保险维护"] = _f(fleet_hold)
    V["池里次数"] = _f(pool_cycles)
    V["日历上限"] = _f(cap)
    V["用户综合电价"] = f"{float(sb['valley_power_price_rmb_kwh']) + float(sb['grid_spread_rmb_kwh']):.2f}"
    V["谷电价"] = f"{float(sb['valley_power_price_rmb_kwh']):.2f}"
    V["峰谷价差"] = f"{float(sb['grid_spread_rmb_kwh']):.2f}"

    turn = {}
    for n, s in scenes.items():
        kwh = float(s["onboard_battery_kwh"])
        daily = float(s["daily_km"]) * float(s["energy_consumption_kwh_km"])
        per_day = daily / (kwh * float(sb["usable_energy_factor"]))
        served = float(config["stations"]["qiji75_trunk"]["planning_daily_capacity"]) / per_day
        turn[n] = turnover_ratio(config, s)
        V[f"{n}每天用电"] = _f(daily)
        V[f"{n}每年循环"] = _f(scene_cycles_per_year(config, s))
        V[f"{n}当月用电"] = _f(daily * days / 12)
        V[f"{n}周转比例"] = _pct(turn[n], 1)
        V[f"{n}每天换几次"] = f"{per_day:.2f}"
        V[f"{n}一站服务车数"] = _f(served)

    def battery_hold_month(kwh, price, t, r, y, res, ins):   # 同名包一层：旧电池卖价基数对齐到买入价
        return _bhm(kwh, price, t, r, y, res, ins, sale_price_ratio(config, y))

    # —— 保本价（年金法，与 derived.rent_ceiling 同一函数）——
    def bank(n: str) -> float:
        s = scenes[n]
        kwh = float(s["onboard_battery_kwh"]) * (1 + turn[n])
        yrs = min(pool_cycles / scene_cycles_per_year(config, s), cap)
        return battery_hold_month(kwh, price, 0.0, r_bank, yrs, bank_res, pool_hold)

    def lessor(n: str, car: float, t: float = tax, r: float = r_les) -> float:
        s = scenes[n]
        yrs = min(car / scene_cycles_per_year(config, s), cap)
        return battery_hold_month(float(s["onboard_battery_kwh"]), price * onb, t, r, yrs, bank_res, pool_hold)

    def selfbuy(n: str, car: float, r: float) -> float:
        s = scenes[n]
        yrs = min(car / scene_cycles_per_year(config, s), cap)
        return battery_hold_month(float(s["onboard_battery_kwh"]), price * onb, tax, r, yrs, fleet_res, fleet_hold)

    tiers = ("悲观", "中性", "乐观")
    cars = {t: float(config["drivers"]["battery_life"][t]["critical_cycles"]) for t in tiers}
    for t in tiers:
        V[f"车上次数{t}"] = _f(cars[t])
        V[f"少活{t}"] = _pct(1 - cars[t] / pool_cycles, 0)
        tc = _tier_cfg(config, t)
        rc = rent_ceiling(tc)
        V[f"租金保底{t}"] = f"{float(tc['swap_business']['battery_rent_rmb_kwh_month']):.2f}"
        V[f"租金超出价{t}"] = f"{float(tc['swap_business']['battery_rent_per_kwh_rmb']):.3f}"

    for n in scenes:
        V[f"{n}银行保本"] = _f(bank(n))

    # 上沿表
    rows = ["| 元/车·月 | 电池银行保本（下沿） | 租赁商保本 | 车队自买 借 " + "／".join(_pct(r, 0) for r in rates)
            + " | 上沿（最便宜替代） | 折成租金 |", "|---|---|---|---|---|---|"]
    gap_rows = ["| 场景 | 电池银行保本 | 租赁商保本 悲观／中性／乐观 | 让出空间 悲观／中性／乐观 |", "|---|---|---|---|"]
    for t in tiers:
        rows.append(f"| **{t}**（车上 {_f(cars[t])}） | | | | | |")
        for n, s in scenes.items():
            les = lessor(n, cars[t]); sl = [selfbuy(n, cars[t], r) for r in rates]
            ceil = min(les, sl[0]); who = "租赁商" if les <= sl[0] else f"自买 {_pct(rates[0], 0)}"
            if n == sb.get("rent_ceiling_overage_scene", "长途"):
                conv = f"超出价 {ceil / (float(s['daily_km']) * float(s['energy_consumption_kwh_km']) * days / 12):.3f} 元/度"
            else:
                conv = f"保底 {ceil / float(s['onboard_battery_kwh']):.2f} 元/度·月"
            rows.append(f"| {n} | {_f(bank(n))} | {_f(les)} | " + "／".join(_f(x) for x in sl) + f" | {_f(ceil)}（{who}） | {conv} |")
    V["表:上沿"] = "\n".join(rows)
    for n in scenes:
        les = [lessor(n, cars[t]) for t in tiers]
        gap_rows.append(f"| {n} | {_f(bank(n))} | " + "／".join(_f(x) for x in les) + " | "
                        + "／".join(_f(x - bank(n)) for x in les) + " |")
    V["表:让出空间"] = "\n".join(gap_rows)

    # 典型车（中途、中性）
    car = cars["中性"]; s = scenes["中途"]; kwh = float(s["onboard_battery_kwh"]); cpy = scene_cycles_per_year(config, s)
    y_car = min(car / cpy, cap); y_pool = min(pool_cycles / cpy, cap)
    V["中途车上年数"] = f"{y_car:.2f}"
    V["中途池里年数"] = f"{pool_cycles / cpy:.1f}"
    V["中途车上卖出价比"] = f"{sale_price_ratio(config, y_car):.2f}"
    V["中途池里卖出价比"] = f"{sale_price_ratio(config, y_pool):.2f}"
    V["银行旧电池卖价·占买入价"] = _pct(bank_res * sale_price_ratio(config, y_car), 1)
    _c1 = copy.deepcopy(config); _c1["tco_jpm"]["fleet_scatter_discount"] = 1.0
    V["零散卖折扣取1时保底租金"] = f"{rent_ceiling(_c1)['floor']:.2f}"
    V["车队旧电池卖价·占买入价"] = _pct(fleet_res * sale_price_ratio(config, y_car), 1)
    V["中途含税电池价"] = _f(kwh * price * (1 + tax))
    a = _crf(r_les, y_car); b = bank_res * sale_price_ratio(config, y_car) * _sinking(r_les, y_car)
    V["租赁商系数"] = f"{a:.4f}"; V["租赁商折回"] = f"{b:.4f}"
    V["租赁商资金年"] = _f(kwh * price * (1 + tax) * (a - b)); V["租赁商保险年"] = _f(kwh * pool_hold)
    V["中途租赁商保本"] = _f(lessor("中途", car))
    r9 = rates[1]; a9 = _crf(r9, y_car); b9 = fleet_res * sale_price_ratio(config, y_car) * _sinking(r9, y_car)
    V["自买9系数"] = f"{a9:.4f}"; V["自买9折回"] = f"{b9:.4f}"
    V["自买9资金年"] = _f(kwh * price * (1 + tax) * (a9 - b9)); V["自买9保险年"] = _f(kwh * fleet_hold)
    V["中途自买9"] = _f(selfbuy("中途", car, r9))
    hold = kwh * (1 + turn["中途"]); ab = _crf(r_bank, y_pool); bb = bank_res * sale_price_ratio(config, y_pool) * _sinking(r_bank, y_pool)
    V["中途持有度数"] = f"{hold:.1f}"; V["银行系数"] = f"{ab:.4f}"; V["银行折回"] = f"{bb:.4f}"
    V["银行资金年"] = _f(hold * price * (ab - bb)); V["银行保险年"] = _f(hold * pool_hold)

    # 逐项替换
    def step(n: str) -> list[float]:
        s = scenes[n]; k = float(s["onboard_battery_kwh"]); c = scene_cycles_per_year(config, s)
        def m(r, t, ins, res, cyc, tu):
            y = min(cyc / c, cap); kk = k * (1 + tu)
            return battery_hold_month(kk, price, t, r, y, res, ins)
        return [m(r9, tax, fleet_hold, fleet_res, car, 0), m(r_bank, tax, fleet_hold, fleet_res, car, 0),
                m(r_bank, 0, fleet_hold, fleet_res, car, 0), m(r_bank, 0, pool_hold, fleet_res, car, 0),
                m(r_bank, 0, pool_hold, bank_res, car, 0), m(r_bank, 0, pool_hold, bank_res, pool_cycles, 0),
                m(r_bank, 0, pool_hold, bank_res, pool_cycles, turn[n])]
    sm, sl = step("中途"), step("长途")
    labels = ["资金成本 " + _pct(r9, 0) + " → " + _pct(r_bank, 1), "电池不交购置税",
              f"保险维护 {_f(fleet_hold)} → {pool_hold:.2f} 元/度·年", f"旧电池卖价 {_pct(fleet_res, 1)} → {_pct(bank_res, 1)}",
              f"站里温和充电，寿命 {_f(car)} → {_f(pool_cycles)} 次", "多备周转电池"]
    kinds = ["资金｜给得了", "政策｜**给不了**（充电车要交）", "规模｜给得了", "规模｜给得了", "技术（延寿）｜**给不了**", "换电的代价｜租赁商不用付"]
    tb = ["| 替换步骤 | 中途 | 长途 | 属于哪一块 | 租赁商给不给得了 |", "|---|---|---|---|---|",
          f"| 车队自己买（借 {_pct(r9, 0)}） | {_f(sm[0])} | {_f(sl[0])} | — | — |"]
    for i in range(6):
        k1, k2 = kinds[i].split("｜")
        tb.append(f"| {labels[i]} | {sm[i+1]-sm[i]:+,.0f} | {sl[i+1]-sl[i]:+,.0f} | {k1} | {k2} |")
    tb.append(f"| **电池银行** | **{_f(sm[6])}** | **{_f(sl[6])}** | | |")
    V["表:逐项替换"] = "\n".join(tb)
    # 对租赁商的净优势拆解（中性）
    for n in ("中途", "长途"):
        les = lessor(n, car); les_notax = lessor(n, car, 0.0)
        s_ = scenes[n]; k = float(s_["onboard_battery_kwh"]); c = scene_cycles_per_year(config, s_)
        pool_plain = battery_hold_month(k, price, 0.0, r_les, min(pool_cycles / c, cap), bank_res, pool_hold)
        V[f"{n}税"] = _f(les - les_notax); V[f"{n}延寿"] = _f(les_notax - pool_plain)
        V[f"{n}周转"] = _f(bank(n) - pool_plain); V[f"{n}让出中性"] = _f(les - bank(n))
    for rr, tag in ((0.06, "6"), (0.09, "9")):
        V[f"租赁商敏感{tag}"] = "、".join(f"{n} {_f(lessor(n, car, r=rr))}" for n in scenes)

    # 临界少活
    crit = ["| 场景 | 临界少活几成（租赁商交 " + _pct(tax, 0) + " 购置税） | 临界车上次数 | 临界少活几成（购置税优势取消） |", "|---|---|---|---|"]
    for n in scenes:
        out = []
        for t in (tax, 0.0):
            lo, hi = 0.0, 0.95
            for _ in range(60):
                m = (lo + hi) / 2
                if lessor(n, pool_cycles * (1 - m), t) > bank(n):
                    hi = m
                else:
                    lo = m
            out.append(lo)
        crit.append(f"| {n} | {_pct(out[0])} | {_f(pool_cycles * (1 - out[0]))} | {_pct(out[1])} |")
    V["表:临界少活"] = "\n".join(crit)

    # 现行租金下各场景实付与上沿
    fl = float(sb["battery_rent_rmb_kwh_month"]); ov = float(sb["battery_rent_per_kwh_rmb"])
    pay = ["| 场景 | 实付 ＝ max(保底 × 度数, 超出价 × 当月用电) | 最便宜替代（中性） | 差 |", "|---|---|---|---|"]
    for n, s in scenes.items():
        k = float(s["onboard_battery_kwh"]); use = float(s["daily_km"]) * float(s["energy_consumption_kwh_km"]) * days / 12
        p = max(fl * k, ov * use); ceil = min(lessor(n, car), selfbuy(n, car, rates[0]))
        pay.append(f"| {n} | max({_f(fl * k)}, {_f(ov * use)}) ＝ {_f(p)} | {_f(ceil)} | {p - ceil:+,.0f} |")
    V["表:实付"] = "\n".join(pay)
    V["保底"] = f"{fl:.4f}"; V["超出价"] = f"{ov:.4f}"

    # 多班倒对兆瓦超充
    s = scenes["短途"]; k = float(s["onboard_battery_kwh"]); daily = float(s["daily_km"]) * float(s["energy_consumption_kwh_km"])
    sess = daily / (k * float(tco["charge_soc_window"])); extra = sess * (float(tco["megawatt_session_minutes"]) - float(tco["swap_minutes"])) / 60
    hours = extra * days
    V["短途每天补能次数"] = f"{sess:.2f}"; V["超充每次多停分钟"] = _f(float(tco["megawatt_session_minutes"]) - float(tco["swap_minutes"]))
    V["短途每天多停"] = f"{extra:.2f}"; V["短途一年多停"] = _f(hours)
    mrow = ["| | " + " | ".join(tiers) + " |", "|---|---|---|---|"]
    prem = []
    for t in tiers:
        tc = _tier_cfg(config, t); f_ = float(tc["swap_business"]["battery_rent_rmb_kwh_month"]); o_ = float(tc["swap_business"]["battery_rent_per_kwh_rmb"])
        p = max(f_ * k, o_ * daily * days / 12); prem.append(p - lessor("短途", cars[t]))
    mrow.append("| 换电每月比超充＋租赁多付（元） | " + " | ".join(_f(x) for x in prem) + " |")
    mrow.append("| 折成每少停一小时（元/小时） | " + " | ".join(_f(x * 12 / hours) for x in prem) + " |")
    V["表:多班倒"] = "\n".join(mrow)
    buy = float(tco["purchase_price"]) * (1 + tax) - float(tco["purchase_subsidy"])
    truck = buy * _crf(rates[1], 8) + float(tco["maintenance"])
    wage = 11500.0
    V["一车年车钱"] = f"{truck / 1e4:.1f}"
    V["两班每小时"] = _f((truck + 2 * wage * 12) / (20 * days)); V["三班每小时"] = _f((truck + 3 * wage * 12) / (21 * days))

    # 充电服务费
    V["超充每千瓦造价"] = _f(supercharge_capex_per_kw(config))
    cs = config["charging_station"]
    V["常规每千瓦造价"] = _f(float(cs["capex_rmb_per_kw"]))
    fee = ["| 利用率 | 常规快充均衡价 | 超充均衡价 | 超充只够付现金成本的价 |", "|---|---|---|---|"]
    for u in (0.15, 0.18, 0.22, 0.27, 0.32, 0.40):
        e1 = equilibrium_service_fee(config, u, kind="conventional")["equilibrium_fee"]
        e2 = equilibrium_service_fee(config, u)
        fee.append(f"| {_pct(u, 0)} | {e1:.3f} | {e2['equilibrium_fee']:.3f} | {e2['cash_fee']:.3f} |")
    V["表:服务费"] = "\n".join(fee)
    # 超充利用率更高时（市场出清、站变少变忙），均衡价降到哪
    urow = ["| 超充站能量利用率 | 22%（中性） | 27%（悲观） | 35% | 50% |", "|---|---|---|---|---|",
            "| 超充均衡服务费（元/度） | " + " | ".join(f"{equilibrium_service_fee(config, u)['equilibrium_fee']:.3f}" for u in (0.22, 0.27, 0.35, 0.50)) + " |"]
    V["表:超充利用率与均衡价"] = "\n".join(urow)
    # 三条路线的博弈：兆瓦超充的价上限 ＝ 常规快充均衡价 ＋ 车队愿为少停的时间多付的每度钱
    from tco import build_scene_economics as _bse
    _h = _bse(config)
    conv = equilibrium_service_fee(config, kind="conventional")["equilibrium_fee"]
    mwc = equilibrium_service_fee(config)["equilibrium_fee"]
    grow = ["| 场景 | 常规快充均衡价 | 少停时间值多少（元/度） | 兆瓦超充价的上限 | 兆瓦超充自己的均衡价 | 谁定兆瓦超充的价 |", "|---|---|---|---|---|---|"]
    for f, sc in zip(("short", "mid", "long"), config["vehicles"]["heavy"]["scenes"]):
        o = getattr(_h, f)
        kwh_y = float(sc["daily_km"]) * float(sc["energy_consumption_kwh_km"]) * float(config["swap_business"]["operating_days"])
        prem = (o.tv_year_wan - o.tv_mw_year_wan) * 1e4 / kwh_y if kwh_y else 0.0
        cap = conv + prem
        who = "自己的成本（上限不起作用）" if mwc < cap else "**常规快充＋时间价值**"
        grow.append(f"| {sc['name']} | {conv:.3f} | {prem:.3f} | {cap:.3f} | {mwc:.3f} | {who} |")
    V["表:三路博弈"] = "\n".join(grow)
    V["充电服务费"] = f"{float(tco['charge_service_fee_rmb_kwh']):.4f}"
    V["换电服务费"] = f"{float(sb['service_fee_rmb_kwh']):.4f}"
    c2 = copy.deepcopy(config); c2["charging_station"]["capex_rmb_per_kw"] = 1500.0 / (1 + float(cs["supercharge_equipment_share"]) * (float(cs["supercharge_equipment_price_ratio"]) - 1))
    V["超充1500敏感"] = f"{equilibrium_service_fee(c2)['equilibrium_fee']:.3f}"
    return V


def model_values(config: dict) -> dict[str, str]:
    """三情景与寿命敏感性的模型读数（只换寿命及随之联动的租金）。"""
    from config_loader import apply_scenario
    from derived import rent_ceiling
    from lab import read_metrics
    from model import build_model
    V: dict[str, str] = {}
    drv = {k: v for k, v in config["drivers"].items() if isinstance(v, dict) and v.get("scenario_axis", True)}
    rows = ["| | 悲观 | 中性 | 乐观 |", "|---|---|---|---|"]
    res = {}
    ent = {}
    import entities
    for t in ("悲观", "中性", "乐观"):
        c = copy.deepcopy(config)
        kw = apply_scenario(c, drv, t)
        snap = build_model(c, **kw)
        v = read_metrics(snap, c, strict=False)
        res[t] = v
        ent[t] = entities.split(c, snap)
    # 租金上沿若改用基准年电池价，中性宁德归属现金流折现高多少（对照，不进基准）
    import derived as _d
    _orig = _d.terminal_year
    try:
        _d.terminal_year = lambda c_, y=float(config["meta"]["reference_year"]): y
        _rc = _d.rent_ceiling(config)
    finally:
        _d.terminal_year = _orig
    _c0 = copy.deepcopy(config)
    _c0["swap_business"]["battery_rent_rmb_kwh_month"] = _rc["floor"]
    _c0["swap_business"]["battery_rent_per_kwh_rmb"] = _rc["overage"]
    _v0 = read_metrics(build_model(_c0), _c0, strict=False)
    V["基准年电池价时现金流折现高出"] = _pct(_v0["val.catl_dcf_perpetual"] / res["中性"]["val.catl_dcf_perpetual"] - 1.0, 0)
    # 车上超充电池 ÷ 换电块单价比：租金上沿、份额、宁德归属现金流折现（中性，其余不变）
    orow = ["| 车上电池 ÷ 换电块 单价比 | 租金保底（元/度·月） | 换电占纯电重卡 | 宁德归属现金流折现（亿） |", "|---|---|---|---|"]
    for ratio in (0.90, 1.00, 1.05, 1.10):
        _c = copy.deepcopy(config)
        _c["tco_jpm"]["onboard_battery_price_ratio"] = ratio
        _r = _d.rent_ceiling(_c)
        _c["swap_business"]["battery_rent_rmb_kwh_month"] = _r["floor"]
        _c["swap_business"]["battery_rent_per_kwh_rmb"] = _r["overage"]
        _v = read_metrics(build_model(_c), _c, strict=False)
        tag = f"**{ratio:.2f}（现行）**" if abs(ratio - float(config["tco_jpm"].get("onboard_battery_price_ratio", 1.0))) < 1e-9 else f"{ratio:.2f}"
        orow.append(f"| {tag} | {_r['floor']:.2f} | {_v['ops.weighted_swap_penetration']:.1f}% | {_f(_v['val.catl_dcf_perpetual'])} |")
    V["表:车上电池单价比"] = "\n".join(orow)
    e = ent["中性"]
    V["周转电池保本价"] = f"{e['turnover_rent_ref_rmb_kwh_month']:.2f}"
    V["换电站门槛"] = _pct(e["station_hurdle"], 1)
    V["电池银行门槛"] = _pct(e["bank_hurdle"], 1)
    V["站层最低服务费"] = f"{e['station_fee_floor_rmb_kwh']:.3f}"
    V["现行服务费"] = f"{e['service_fee_rmb_kwh']:.3f}"
    V["技术服务费"] = f"{e['tech_fee_wan']:.1f}"
    V["悲观技术服务费下限"] = f"{max(0.0, ent['悲观']['tech_fee_min_wan']):.1f}"
    V["悲观技术服务费上限"] = f"{ent['悲观']['tech_fee_max_wan']:.0f}"
    er = ["| 亿元/年（中性） | 换电站 | 电池银行 | 合计＝系统 |", "|---|---|---|---|",
          f"| 对外收入 | 服务费 {_f(e['station_revenue_yi'])} | 电池租金＋峰谷套利＋辅助服务 {_f(e['bank_revenue_yi'] - e['station_settlement_yi'])} | {_f(e['station_revenue_yi'] + e['bank_revenue_yi'] - e['station_settlement_yi'])} |",
          f"| 内部结算（站 → 银行：技术服务费） | −{_f(e['station_settlement_yi'])} | ＋{_f(e['station_settlement_yi'])} | 0 |",
          f"| 运营成本 | 电损、场租、人工 {_f(e['station_opex_yi'])} | 软件、保险、池化维护、仓储物流 {_f(e['bank_opex_yi'])} | {_f(e['station_opex_yi'] + e['bank_opex_yi'])} |",
          f"| EBITDA | {_f(e['station_ebitda_yi'])} | {_f(e['bank_ebitda_yi'])} | {_f(e['system_ebitda_yi'])} |",
          f"| 投入资本 | 站体 {_f(e['station_capital_yi'])} | 全部电池（车上＋周转，按全周期资本要求） | — |"]
    V["表:分拆账"] = "\n".join(er)
    tr = ["| | 悲观 | 中性 | 乐观 |", "|---|---|---|---|",
          "| 换电站回报（门槛＝资源方投超充的回报 " + _pct(e["station_hurdle"], 1) + "） | " + " | ".join(_pct(ent[t]["station_irr"]) for t in ent) + " |",
          "| 电池银行回报（门槛 " + _pct(e["bank_hurdle"], 1) + "） | " + " | ".join(_pct(ent[t]["bank_irr"]) for t in ent) + " |",
          "| 电池银行覆盖倍数 | " + " | ".join(f"{ent[t]['bank_coverage']:.2f}" for t in ent) + " |",
          "| 站层能承受的最低服务费（元/度） | " + " | ".join(f"{ent[t]['station_fee_floor_rmb_kwh']:.3f}" for t in ent) + " |",
          "| 按现行结算两个主体都过门槛 | " + " | ".join("是" if ent[t]["station_pass"] and ent[t]["bank_pass"] else "**否**" for t in ent) + " |",
          "| 电池银行离门槛的缺口（亿元/年） | " + " | ".join(_f(ent[t]["bank_shortfall_yi"]) for t in ent) + " |",
          "| 换电站超出门槛的富余（亿元/年） | " + " | ".join(_f(ent[t]["station_surplus_yi"]) for t in ent) + " |",
          "| 技术服务费可行区间（万元/站·年；下限＝电池银行刚过门槛，上限＝换电站刚过门槛） | " + " | ".join(f"{max(0.0, ent[t]['tech_fee_min_wan']):.1f}～{ent[t]['tech_fee_max_wan']:.0f}" for t in ent) + " |",
          "| 存在让两边都过的结算（闸门） | " + " | ".join("是" if ent[t]["feasible"] else "**否**" for t in ent) + " |"]
    V["表:分拆三情景"] = "\n".join(tr)
    pr = ["| 池 | 换电站回报 | 电池银行覆盖倍数 |", "|---|---|---|"]
    names = {"qiji75_short": "骐骥短途", "qiji75_trunk": "骐骥干线", "choco25_passenger": "巧克力乘用", "choco35_city": "巧克力城配"}
    for pk, p_ in e["pools"].items():
        pr.append(f"| {names.get(pk, pk)} | {_pct(p_['station_irr'])} | {p_['bank_coverage']:.2f} |")
    V["表:分拆分池"] = "\n".join(pr)
    rows.append("| 全投资回报 | " + " | ".join(_pct(_irr_from_cov(res[t]["swap.coverage"])) for t in res) + " |")
    rows.append("| EBITDA 覆盖倍数 | " + " | ".join(f"{res[t]['swap.coverage']:.2f}" for t in res) + " |")
    rows.append("| 换电占纯电重卡份额 | " + " | ".join(f"{res[t]['ops.weighted_swap_penetration']:.1f}%" for t in res) + " |")
    rows.append("| EBITDA（亿） | " + " | ".join(_f(res[t]["swap.ebitda"]) for t in res) + " |")
    rows.append("| 宁德归属现金流折现（亿） | " + " | ".join(_f(res[t]["val.catl_dcf_perpetual"]) for t in res) + " |")
    V["表:三情景"] = "\n".join(rows)
    V["中性回报"] = _pct(_irr_from_cov(res["中性"]["swap.coverage"]))
    V["悲观回报"] = _pct(_irr_from_cov(res["悲观"]["swap.coverage"]))
    V["悲观覆盖"] = f"{res['悲观']['swap.coverage']:.2f}"

    # 池里水平敏感性（比例不动，租金按各自上沿重推）
    base_short = 1 - config["battery_life_model"]["critical_cycles"] / (
        config["battery_life_model"]["critical_cycles"] * config["battery_life_model"]["pool_life_multiplier"])
    srows = ["| 池里水平 | 车上 | 租金上沿（保底／超出价） | 全投资回报 | 份额 | 宁德归属现金流折现（亿） |", "|---|---|---|---|---|---|"]
    _pool_now = config["battery_life_model"]["critical_cycles"] * config["battery_life_model"]["pool_life_multiplier"]
    for pool, tag in ((4000.0, "4,000"), (None, f"{_pool_now:,.0f}（现行）"), (6000.0, "6,000"), ("noext", "去掉延寿（池里＝车上）")):
        c = copy.deepcopy(config)
        lm = c["battery_life_model"]
        if pool == "noext":
            lm["pool_life_multiplier"] = 1.0
        elif pool is not None:
            lm["critical_cycles"] = pool * (1 - base_short); lm["pool_life_multiplier"] = 1 / (1 - base_short)
        rc = rent_ceiling(c)
        if pool != "noext":
            c["swap_business"]["battery_rent_rmb_kwh_month"] = rc["floor"]; c["swap_business"]["battery_rent_per_kwh_rmb"] = rc["overage"]
        c["drivers"]["battery_life"]["中性"] = {"critical_cycles": lm["critical_cycles"], "pool_life_multiplier": lm["pool_life_multiplier"],
                                               "battery_rent_rmb_kwh_month": c["swap_business"]["battery_rent_rmb_kwh_month"],
                                               "battery_rent_per_kwh_rmb": c["swap_business"]["battery_rent_per_kwh_rmb"]}
        d2 = {k: v for k, v in c["drivers"].items() if isinstance(v, dict) and v.get("scenario_axis", True)}
        kw = apply_scenario(c, d2, "中性")
        v = read_metrics(build_model(c, **kw), c, strict=False)
        srows.append(f"| {tag} | {_f(lm['critical_cycles'])} | {float(c['swap_business']['battery_rent_rmb_kwh_month']):.2f}／{float(c['swap_business']['battery_rent_per_kwh_rmb']):.3f} | "
                     f"{_pct(_irr_from_cov(v['swap.coverage']))} | {v['ops.weighted_swap_penetration']:.1f}% | {_f(v['val.catl_dcf_perpetual'])} |")
    V["表:池里敏感"] = "\n".join(srows)
    return V


def supply_values(config: dict) -> dict[str, str]:
    """供给侧：站数内生（过门槛按需求建）；闸门、可行性（需求要的年新建 vs 已公布规划）、覆盖上界。"""
    from config_loader import apply_scenario
    from lab import read_metrics
    from model import build_model, supply_gate
    V: dict[str, str] = {}
    drv = {k: v for k, v in config["drivers"].items() if isinstance(v, dict) and v.get("scenario_axis", True)}
    years = [int(y) for y in config["construction"]["years"]]
    heavy = config["vehicles"]["heavy"]
    sup = config["supply_network"]
    annual = float(heavy["stock_wan"]) / float(heavy["replacement_cycle_years"])
    cap = float(config["stations"]["qiji75_trunk"]["planning_daily_capacity"])
    body = float(config["stations"]["qiji75_trunk"]["station_body_capex_wan"])
    hurdle = float(sup.get("hurdle_coverage", 1.0))
    V["重卡年销量"] = _f(annual)
    V["电动化路径"] = "／".join(_pct(r, 0) for r in heavy["nev_rates"])
    V["单站规划能力"] = _f(cap)
    V["存量站数"] = _f(float(sup["stations_base_all"]))
    V["骐骥存量站数"] = _f(float(sup["qiji_stations_base"]))
    V["骐骥2030规划站数"] = _f(float(sup["qiji_plan_2030"]))
    V["干线运力覆盖目标"] = _pct(float(sup["trunk_coverage_target"]), 0)
    V["闸门覆盖倍数"] = f"{hurdle:.1f}"
    V["站体造价"] = _f(body)
    cols: dict[str, list[str]] = {k: [] for k in ("cov", "gate", "dem", "need", "catl", "plan", "needb", "planb", "mult", "fplan", "sh", "capex", "trucks")}
    for t in ("悲观", "中性", "乐观"):
        c = copy.deepcopy(config)
        kw = apply_scenario(c, drv, t)
        gated = supply_gate(c, **kw)
        m = read_metrics(build_model(c, **kw), c, strict=False)
        passed = gated["supply_network"]["mode"] == "endogenous"
        from price_response import compute_response
        from tco import build_scene_economics
        r = compute_response(gated, build_scene_economics(gated))
        n = r["network"]
        _cs = {sc["name"]: float(sc.get("catl_swap_share") or 0.0) for sc in gated["vehicles"]["heavy"]["scenes"]}
        _w = {k: v["swap_trucks_wan"] * v["swaps_per_day"] for k, v in n["by_scene"].items()}
        share_catl = sum(_w[k] * _cs[k] for k in _w) / sum(_w.values()) if sum(_w.values()) else 0.0
        cols["cov"].append(f"{m['swap.coverage']:.2f}")
        cols["gate"].append("通过" if passed else "**不过**")
        cols["dem"].append(_pct(r["weighted_penetration_demand"]))
        cols["need"].append(_f(n["stations_needed"]))
        cols["catl"].append(_f(n["stations_needed"] * share_catl))
        cols["plan"].append(_f(n["stations_plan_2030"]))
        cols["needb"].append(_f(n["build_needed_per_year"]))
        cols["planb"].append(_f(n["build_plan_per_year"]))
        cols["mult"].append(f"{n['build_needed_per_year'] / n['build_plan_per_year']:.1f}" if n["build_plan_per_year"] else "—")
        cols["fplan"].append(_pct(n["factor_plan"], 0))
        cols["sh"].append(_pct(r["weighted_penetration"]))
        cols["capex"].append(_f(n["stations_needed"] * body / 1e4))
        cols["trucks"].append(f"{n['swap_trucks_demand_wan'] * n['factor']:.0f}")
        if t == "中性":
            V["需求所需站数·中性"] = _f(n["stations_needed"])
            V["需求要的年新建·中性"] = _f(n["build_needed_per_year"])
            V["规划年新建"] = _f(n["build_plan_per_year"])
            V["需求对规划的倍数·中性"] = f"{n['build_needed_per_year'] / n['build_plan_per_year']:.1f}"
            V["规划站网能服务的比例·中性"] = _pct(n["factor_plan"], 0)
            V["规划隐含份额·中性"] = _pct(n["factor_plan"] * r["weighted_penetration_demand"])
            V["规划站数"] = _f(n["stations_plan_2030"])
            V["宁德所需站数·中性"] = _f(n["stations_needed"] * share_catl)
            V["站体投资·中性"] = _f(n["stations_needed"] * body / 1e4)
            # 分年：按需求所需站数 vs 已公布规划（线性铺）
            hs = {sc["name"]: sc for sc in heavy["scenes"]}
            usable = float(c["swap_business"]["usable_energy_factor"])
            rows = ["| 年末 | 当年纯电重卡销量（万辆） | 累计换电重卡（万辆） | 按需求要的站（座） | 已公布规划（座） | 规划 ÷ 需要 |", "|---|---|---|---|---|---|"]
            swaps = trucks_cum = 0.0
            base_y = int(sup["base_year"]); base = float(sup["stations_base_all"])
            for i, y in enumerate(years):
                ev = annual * float(heavy["nev_rates"][i]) * float(heavy.get("pure_electric_share") or 1.0)
                for name, info in r["scenes"].items():
                    sc = hs[name]
                    f_ = float(sc["daily_km"]) * float(sc["energy_consumption_kwh_km"]) / (float(sc["onboard_battery_kwh"]) * usable)
                    add = ev * float(sc["weight"]) * info.get("penetration_demand", info["penetration"])
                    trucks_cum += add; swaps += add * f_
                need_y = swaps * 1e4 / cap
                plan_y = base + (n["stations_plan_2030"] - base) * (y - base_y) / (years[-1] - base_y)
                rows.append(f"| {y} | {ev:.1f} | {trucks_cum:.1f} | {_f(need_y)} | {_f(plan_y)} | {_pct(min(9.99, plan_y / need_y), 0)} |")
            V["表:供给分年"] = "\n".join(rows)
            hs0 = hs; days = float(c["swap_business"]["operating_days"])
            e = sum(v["swap_trucks_wan"] * n["factor"] * float(hs0[k]["daily_km"]) * float(hs0[k]["energy_consumption_kwh_km"]) * days
                    for k, v in n["by_scene"].items())
            V["兑现年换电重卡·中性"] = f"{n['swap_trucks_demand_wan'] * n['factor']:.0f} 万辆"
            V["兑现年重卡换电电量·中性"] = f"{e / 1e4:,.0f} 亿度"
            per = [float(x["daily_km"]) * float(x["energy_consumption_kwh_km"]) * days / 1e4 for x in heavy["scenes"]]
            V["每车年用电·场景区间"] = f"{min(per):.0f}–{max(per):.0f} 万度"
    rows = ["| | 悲观 | 中性 | 乐观 |", "|---|---|---|---|"]
    for label, k in (("兑现年 EBITDA 覆盖倍数", "cov"), ("闸门（覆盖倍数 ≥ " + f"{hurdle:.1f}" + "）", "gate"),
                     ("换电占纯电重卡·需求侧", "dem"), ("按需求要的站（全体运营商）", "need"), ("其中宁德（按各场景换电次数加权的宁德份额）", "catl"),
                     ("已公布规划（全体运营商）", "plan"), ("按需求要的年新建（座/年）", "needb"), ("已公布规划的年新建（座/年）", "planb"),
                     ("需求 ÷ 规划（倍）", "mult"), ("规划站网能服务需求的比例", "fplan"),
                     ("**换电占纯电重卡（现行）**", "sh"), ("站体投资·全体运营商（亿，不含电池）", "capex"),
                     ("兑现年换电重卡（万辆，全体运营商）", "trucks")):
        rows.append(f"| {label} | " + " | ".join(cols[k]) + " |")
    V["表:供给三情景"] = "\n".join(rows)
    return V


def share_values(config: dict) -> dict[str, str]:
    """份额：可及比例 × 系统成本低于替代的车占比。逐车读数与敏感性。"""
    from price_response import compute_response
    from tco import build_scene_economics
    V: dict[str, str] = {}

    def run(c):
        return compute_response(c, build_scene_economics(c))
    r = run(config)
    sm = config["share_model"]
    V["里程分布半宽"] = _pct(float(sm["km_spread"]), 0)
    V["里程分布点数"] = f"{int(sm['km_points'])}"
    rows = ["| 场景 | 日里程（公里） | 电池银行保本（含周转） | 租赁商 | 车队自买 借 " + "／".join(_pct(float(config["tco_jpm"][f"fleet_discount_rate_{t}"]), 0) for t in ("low", "mid", "high"))
            + " | 兆瓦多停的时间价值 | 选换电的占比 |", "|---|---|---|---|---|---|---|"]
    for n, info in r["scenes"].items():
        for p in info["system_points"]:
            rows.append(f"| {n} | {_f(p['km'])} | {p['bank_wan']:.2f} | {p['lessor_wan']:.2f} | "
                        + "／".join(f"{x:.2f}" for x in p["own_wan"]) + f" | {p['tv_wan']:.2f} | {_pct(p['fraction'], 0)} |")
    V["表:逐车系统成本"] = "\n".join(rows)
    srow = ["| 场景 | 可及比例 | 系统成本低于替代的车占比 | 份额 |", "|---|---|---|---|"]
    for n, info in r["scenes"].items():
        srow.append(f"| {n} | {_pct(info['ceiling'], 0)} | {_pct(info['addressable'], 0)} | {_pct(info['penetration'])} |")
    srow.append(f"| **加权** | | | **{_pct(r['weighted_penetration_demand'])}** |")
    V["表:份额拆解"] = "\n".join(srow)
    sens = ["| 改动（其余中性） | 换电占纯电重卡 |", "|---|---|", f"| 现行 | {_pct(r['weighted_penetration_demand'])} |"]
    for label, fn in (("里程分布半宽 20%", lambda c: c["share_model"].__setitem__("km_spread", 0.2)),
                      ("里程分布半宽 80%", lambda c: c["share_model"].__setitem__("km_spread", 0.8)),
                      ("车上电池比换电块便宜 10%（价比 0.90）", lambda c: c["tco_jpm"].__setitem__("onboard_battery_price_ratio", 0.90)),
                      ("车上电池比换电块便宜 15%（价比 0.85）", lambda c: c["tco_jpm"].__setitem__("onboard_battery_price_ratio", 0.85)),
                      ("车上电池比换电块贵 10%（价比 1.10）", lambda c: c["tco_jpm"].__setitem__("onboard_battery_price_ratio", 1.10)),
                      ("去掉延寿（池里＝车上）", lambda c: c["battery_life_model"].__setitem__("pool_life_multiplier", 1.0))):
        c = copy.deepcopy(config); fn(c)
        sens.append(f"| {label} | {_pct(run(c)['weighted_penetration_demand'])} |")
    V["表:份额敏感"] = "\n".join(sens)
    return V


def _erlang_c_wait(c: int, rho: float, service_min: float) -> float:
    """M/M/c 平均排队（分钟）：c 个桩共用一条队，每桩利用率 rho，单次服务 service_min 分钟。"""
    a = c * rho
    s_ = sum(a ** k / math.factorial(k) for k in range(c))
    top = a ** c / math.factorial(c) / (1 - rho)
    pw = top / (s_ + top)
    return pw * service_min / (c * (1 - rho))


def queue_values(config: dict) -> dict[str, str]:
    """换电工位的最优利用率（排队论）与超充的同口径对照。"""
    from derived import swap_station_hour_cost, optimal_swap_utilization
    from tco import build_scene_economics
    V: dict[str, str] = {}
    st = config["stations"]["qiji75_trunk"]
    sb = config["swap_business"]
    tco = config["tco_jpm"]
    days = float(sb["operating_days"])
    usable = float(sb["usable_energy_factor"])
    swap_min = float(st["swap_duration_seconds"]) / 60.0
    mu = 60.0 / swap_min
    lane_max = float(st["operating_hours_day"]) * mu
    h = build_scene_economics(config)
    num = den = 0.0
    for f, sc in zip(("short", "mid", "long"), config["vehicles"]["heavy"]["scenes"]):
        stop = getattr(h, f).extra_stop_hours_day
        freq = float(sc["daily_km"]) * float(sc["energy_consumption_kwh_km"]) / (float(sc["onboard_battery_kwh"]) * usable)
        wgt = float(sc["weight"]) * freq
        num += wgt * float(tco["annual_gain_swap"]) / (stop * days)
        den += wgt
    w = num / den
    C = swap_station_hour_cost(config)
    rho = optimal_swap_utilization(C["per_hour"], w)
    cap = float(st["planning_daily_capacity"])
    if abs(cap - math.floor(lane_max * rho)) > 1.0:
        raise SystemExit(f"单站规划能力 {cap} 与最优利用率推出的 {lane_max * rho:.1f} 不一致：改 stations.*.planning_daily_capacity")
    V["工位上限"] = _f(lane_max)
    V["工位每小时全成本"] = _f(C["per_hour"])
    V["工位年成本明细"] = "站体资本回收 {:.0f}、设备保险 {:.1f}、场租 {:.0f}、人工 {:.1f}、站内周转电池持有 {:.0f}（万元/年）".format(
        C["capital"] / 1e4, C["insurance"] / 1e4, C["site"] / 1e4, C["labor"] / 1e4, C["turnover"] / 1e4)
    V["年运营小时"] = _f(C["hours_year"])
    V["每车小时时间成本"] = _f(w)
    V["最优利用率"] = f"{rho:.2f}"
    V["最优利用率(三位)"] = f"{rho:.3f}"
    V["最优利用率下日换电次数"] = f"{lane_max * rho:.1f}"
    _rho0 = optimal_swap_utilization((C["total_year"] - C["turnover"]) / C["hours_year"], w)
    V["不计周转电池时最优利用率"] = f"{_rho0:.2f}"
    V["不计周转电池时日换电次数"] = _f(math.floor(lane_max * _rho0))
    rows = ["| 利用率 ρ | 日换电次数 | 平均排队车辆 | 平均排队（分钟） | 排队＋换电（分钟） | 每次换电：工位成本＋排队时间成本（元） |", "|---|---|---|---|---|---|"]
    for r in (0.6, 0.7, rho, 0.8, 0.9):
        lq = r * r / (2 * (1 - r))
        wq = r / (2 * mu * (1 - r)) * 60
        cost = C["per_hour"] / (mu * r) + w * wq / 60
        tag = f"**{r:.2f}（最优）**" if r == rho else f"{r:.2f}"
        rows.append(f"| {tag} | {lane_max * r:.0f} | {lq:.1f} | {wq:.0f} | {wq + swap_min:.0f} | {cost:.0f} |")
    V["表:利用率与成本"] = "\n".join(rows)
    mw = float(tco["megawatt_session_minutes"])
    piles = 26
    qrows = ["| 利用率 | 换电一条工位（M/D/1，5 分钟） | 超充单桩（M/M/1，" + f"{mw:.0f}" + " 分钟） | 超充站 " + str(piles) + " 桩共用一条队（M/M/c） |", "|---|---|---|---|"]
    for r in (0.7, 0.8, 0.9):
        qrows.append(f"| {r:.1f} | 排队 {r / (2 * mu * (1 - r)) * 60:.0f} 分钟，合计 {r / (2 * mu * (1 - r)) * 60 + swap_min:.0f} 分钟 | "
                     f"排队 {r / (1 - r) * mw:.0f} 分钟，合计 {r / (1 - r) * mw + mw:.0f} 分钟 | "
                     f"排队 {_erlang_c_wait(piles, r, mw):.1f} 分钟，合计 {_erlang_c_wait(piles, r, mw) + mw:.0f} 分钟 |")
    V["表:排队对照"] = "\n".join(qrows)
    V["超充参照桩数"] = str(piles)
    return V


def supply_route_values(config: dict) -> dict[str, str]:
    """A3：补能四条路线的供给成本表（src/supply_routes.py）。"""
    import copy
    import supply_routes as SR
    V: dict[str, str] = {}
    sm = SR.summary(config)
    st, op = sm["stations"], sm["optimum"]
    ks = SR.ROUTES
    head = "| 项（万元） | " + " | ".join(st[k]["label"] for k in ks) + " |"
    rows = [head, "|---" * (len(ks) + 1) + "|"]
    def row(name, fn):
        rows.append(f"| {name} | " + " | ".join(fn(st[k]) for k in ks) + " |")
    row("接入容量（kVA）", lambda d: _f(d["kva"]))
    row("功率（kW；换电取接入容量）", lambda d: _f(d["power_kw"]))
    row("① 设备", lambda d: _f(d["equipment_wan"]))
    row("② 站内电池（价值，归电池银行）", lambda d: _f(d["battery_value_wan"]) if d["battery_value_wan"] else "无")
    row("③ 箱变与柜", lambda d: _f(d["transformer_wan"]))
    row("④ 外线接入", lambda d: _f(d["external_wan"]))
    row("⑤ 站内电缆", lambda d: _f(d["cable_wan"]))
    row("⑥ 土建与硬化（不含排队区）", lambda d: _f(d["civil_wan"], 1))
    row("站投资合计（不含电池）", lambda d: "**" + _f(d["capex_wan"]) + "**")
    row("每千瓦投资（元/kW）", lambda d: _f(d["capex_per_kw"]))
    row("⑦ 占地（㎡，不含排队区）", lambda d: _f(d["area_m2"]))
    row("年：资本回收", lambda d: _f(d["capital_wan"], 1))
    row("年：⑧ 场地租金", lambda d: _f(d["rent_wan"], 1))
    row("年：⑨ 人员", lambda d: _f(d["staff_wan"], 1))
    row("年：⑩ 运维与保险", lambda d: _f(d["om_wan"] + d["insurance_wan"], 1))
    row("年：站内电池持有（电池银行保本价）", lambda d: _f(d["battery_hold_wan"], 1) if d["battery_hold_wan"] else "无")
    row("年固定成本合计", lambda d: "**" + _f(d["fixed_wan"], 1) + "**")
    V["表:供给_单站"] = "\n".join(rows)
    orow = ["| 路线 | 规划最优利用率（时间） | 日服务车次 | 电量利用率 | 平均排队（分钟） | 95% 排队车数 | 每度电站成本（元） | 每度电排队时间成本（元） | 合计（元/度） |",
            "|---|---|---|---|---|---|---|---|---|"]
    for k in ks:
        o = op[k]
        orow.append(f"| {st[k]['label']} | {o['rho']:.2f} | {o['sessions_day']:.0f} | {_pct(o['energy_util'], 0)} | {o['wait_min']:.0f} | {o['queue_trucks']} | "
                    f"{o['station_cost']:.3f} | {o['wait_cost']:.3f} | **{o['total']:.3f}** |")
    V["表:供给_规划最优"] = "\n".join(orow)
    crow = ["| 时间利用率 | " + " | ".join(st[k]["label"] for k in ks) + " |", "|---" * (len(ks) + 1) + "|"]
    for u in (0.1, 0.2, 0.3, 0.5, 0.7):
        cells = []
        for k in ks:
            r_ = SR.cost_at(config, k, u, sm["w"])
            cells.append(f"{r_['station_cost']:.3f}（电量 {_pct(r_['energy_util'], 0)}）" if r_["feasible"] else "超出电量上限")
        crow.append(f"| {u:.0%} | " + " | ".join(cells) + " |")
    V["表:供给_成本曲线"] = "\n".join(crow)
    c = sm["swap_constraints"]
    V["换电工位上限"] = _f(c["lane"])
    V["换电电量上限"] = _f(c["energy"])
    V["换电电量上限24h"] = _f(c["energy_24h"])
    V["换电每次净补电量"] = _f(c["e_swap"])
    V["换电绑定约束"] = c["binding"]
    V["换电规划最优车次"] = _f(op["swap"]["sessions_day"])
    V["临时时间价值"] = _f(sm["w"])
    # 兆瓦站规模敏感：同样的终端单价、每车位占地与人员，站越大、每站固定项摊得越薄
    mrow = ["| 兆瓦站规模 | 接入（kVA） | 站投资（万元） | 每千瓦投资（元/kW） | 时间利用率 20% 时每度电站成本（元） | 规划最优时每度电站成本（元） |", "|---|---|---|---|---|---|"]
    for piles, kva, units in ((2, 2500, 1), (4, 5000, 2), (6, 7500, 3)):
        cc = copy.deepcopy(config)
        m = cc["supply_routes"]["megawatt"]
        m["equipment_wan"] = float(m["equipment_wan"]) / int(m["piles"]) * piles
        m["piles"], m["kva"], m["transformer_units"] = piles, float(kva), units
        s_ = SR.station(cc, "megawatt")
        o_ = SR.planner_optimum(cc, "megawatt", sm["w"])
        mrow.append(f"| {piles} × 1 MW | {kva:,} | {s_['capex_wan']:.0f} | {s_['capex_per_kw']:,.0f} | {SR.cost_at(cc, 'megawatt', 0.2, sm['w'])['station_cost']:.3f} | {o_['station_cost']:.3f} |")
    V["表:供给_兆瓦规模"] = "\n".join(mrow)
    return V


def values(config: dict) -> dict[str, str]:
    """口径文档可用的现算值（表与算式中间量）。注入由 src/inject.py 统一做（与叙述同一个注入器）。"""
    V = ledger_values(config)
    V.update(supply_values(config))
    V.update(share_values(config))
    V.update(queue_values(config))
    V.update(model_values(config))
    V.update(supply_route_values(config))
    return V

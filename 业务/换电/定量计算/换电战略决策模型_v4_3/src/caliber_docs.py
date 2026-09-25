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
                         sale_price_ratio)
    from charging import equilibrium_service_fee, supercharge_capex_per_kw

    V: dict[str, str] = {}
    tco = config["tco_jpm"]
    sb = config["swap_business"]
    life = config["battery_life_model"]
    curve = config["construction"]["battery_price_curve"]
    scenes = {s["name"]: s for s in config["vehicles"]["heavy"]["scenes"]}
    price = battery_price_rmb_kwh(config, float(config["meta"]["reference_year"]))
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
        per_day = daily / (kwh * 0.8)
        served = 192.0 / per_day
        turn[n] = 4104.0 / (served * kwh)
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
        return battery_hold_month(float(s["onboard_battery_kwh"]), price, t, r, yrs, bank_res, pool_hold)

    def selfbuy(n: str, car: float, r: float) -> float:
        s = scenes[n]
        yrs = min(car / scene_cycles_per_year(config, s), cap)
        return battery_hold_month(float(s["onboard_battery_kwh"]), price, tax, r, yrs, fleet_res, fleet_hold)

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
    for t in ("悲观", "中性", "乐观"):
        c = copy.deepcopy(config)
        kw = apply_scenario(c, drv, t)
        v = read_metrics(build_model(c, **kw), c, strict=False)
        res[t] = v
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
    for pool, tag in ((4000.0, "4,000"), (None, "现行"), (6000.0, "6,000"), ("noext", "去掉延寿（池里＝车上）")):
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
            # 覆盖上界：天花板 ÷ 干线运力覆盖目标 ＝ 覆盖区内要做到的换电占比
            cov = float(sup["trunk_coverage_target"])
            crow = ["| 场景 | 天花板 | ÷ 覆盖 " + _pct(cov, 0) + " ＝ 覆盖区内要做到的换电占比 |", "|---|---|---|"]
            for sc in heavy["scenes"]:
                ce = float(sc["swap_share_ceiling"])
                crow.append(f"| {sc['name']} | {_pct(ce, 0)} | {_pct(ce / cov, 0)} |")
            V["表:覆盖上界"] = "\n".join(crow)
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


def values(config: dict) -> dict[str, str]:
    """口径文档可用的现算值（表与算式中间量）。注入由 src/inject.py 统一做（与叙述同一个注入器）。"""
    V = ledger_values(config)
    V.update(supply_values(config))
    V.update(model_values(config))
    return V

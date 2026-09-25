"""派生量计算：电池价格路径、全生命周期资本因子、换电频次、电池寿命、站能力。

变更历史
--------
v4.2.2（2026-08-29）
- 【新增】battery_life_years(config, frequency_per_day)：按2000次循环临界点÷年循环次数、
  与日历寿命封顶取min推算电池寿命，替代各车型硬编码。
- 【新增】LEGACY_V32_VEHICLE_LIFE_YEARS / LEGACY_V32_STATION_LIFE_YEARS：v3.2遗留硬编码
  寿命常量，不参与基准测算，仅供附录A.2新旧口径对比重跑。保留在代码而非配置，因其属于
  "口径定义"而非"可调参数"；并注明它与模型自身频次参数不自洽。
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class LifecycleFactors:
    capital_multiplier: float
    terminal_residual_ratio: float
    replacement_pv_ratio: float


@dataclass(frozen=True)
class TerminalResidualDetails:
    horizon_price_ratio: float
    terminal_batch_age_years: float
    terminal_batch_soh: float
    secondary_market_discount: float
    terminal_residual_ratio: float


def battery_price_rmb_kwh(config: dict, year: float) -> float:
    """按三阶段价格曲线返回任意年份的动力电池价格。"""
    curve = config["construction"]["battery_price_curve"]
    base = curve["base_price_rmb_kwh"]
    platform_end = float(curve["platform_end_year"])
    rapid_end = float(curve["rapid_decline_end_year"])
    if year <= platform_end:
        return base
    rapid_years = max(0.0, min(year, rapid_end) - platform_end)
    slow_years = max(0.0, year - rapid_end)
    return (
        base
        * (1.0 - curve["rapid_annual_decline_rate"]) ** rapid_years
        * (1.0 - curve["slow_annual_decline_rate"]) ** slow_years
    )


def annual_battery_price_path(config: dict) -> dict[int, float]:
    return {
        year: battery_price_rmb_kwh(config, year)
        for year in config["construction"]["years"]
    }


def retirement_recovery_ratio(config: dict) -> float:
    """退役时卖旧电池的回收额/同年新电池价格。"""
    curve = config["construction"]["battery_price_curve"]
    return (
        curve["storage_to_power_price_ratio"]
        * curve["retirement_soh"]
        * curve["secondary_market_discount"]
    )


def terminal_residual_details(
    config: dict, install_year: float, life_years: float
) -> TerminalResidualDetails:
    """拆出15年末共同价格因子与末批在役年龄/SOH，避免把二者混为一谈。

    【2026-09-03，经用户复核后修正】末代批次在模型horizon结束时仍在役、仍是换电电池，
    没有发生退役、没有转去做储能——因此不适用 storage_to_power_price_ratio
    （储能/动力价格比 0.917）：那一项只描述"退役电池降级卖给储能市场"这一具体转换，
    对应公式见 retirement_recovery_ratio()，专供期中更换回收使用，末代不适用。

    但 secondary_market_discount（二手转售折价）适用，理由与"是否发生真实交易"无关：
    这是 DCF 的期末资产残值（Terminal/Salvage Value）——项目分析期结束时，这批仍在役的
    换电电池对于「接盘方」或「二手市场」具有公允价值，理应作为期末现金流入计入 NPV
    （标准项目财务处理，不需要真的完成一次处置动作才能确认）。既然这份价值最终要以
    "变现假设"计入现金流，就该背上二手市场的流动性折价——买方不会按新电池同等价格
    收一批旧电池。公式：残值 = 期末同代新换电电池价（重置成本）× 实际SOH × 二手交易折扣。
    见 DECISIONS.md「2026-09-03 · 末代残值不再降级储能」。
    """
    horizon = config["finance"]["model_horizon_years"]
    horizon_year = install_year + horizon
    completed_cycles = math.floor((horizon - 1e-9) / life_years)
    last_install_year = install_year + completed_cycles * life_years
    age = horizon_year - last_install_year
    curve = config["construction"]["battery_price_curve"]
    soh = max(
        curve["retirement_soh"],
        1.0 - curve["annual_soh_decline_rate"] * age,
    )
    price_ratio = (
        battery_price_rmb_kwh(config, horizon_year)
        / battery_price_rmb_kwh(config, install_year)
    )
    discount = curve["secondary_market_discount"]
    residual = price_ratio * soh * discount
    return TerminalResidualDetails(
        horizon_price_ratio=price_ratio,
        terminal_batch_age_years=age,
        terminal_batch_soh=soh,
        secondary_market_discount=discount,
        terminal_residual_ratio=residual,
    )


def _terminal_residual_ratio(config: dict, install_year: float, life_years: float) -> float:
    """15年末在役批可回收价值相对初装成本的比例。"""
    return terminal_residual_details(
        config, install_year, life_years
    ).terminal_residual_ratio


def lifecycle_factors(config: dict, install_year: float, life_years: float) -> LifecycleFactors:
    """由价格、寿命、WACC逐次推导EAC式全周期资本倍数与期末残值。"""
    horizon = config["finance"]["model_horizon_years"]
    wacc = config["finance"]["wacc"]
    initial_price = battery_price_rmb_kwh(config, install_year)
    recovery_ratio = retirement_recovery_ratio(config)
    replacement_pv = 0.0
    cycle = 1
    while cycle * life_years < horizon - 1e-9:
        elapsed = cycle * life_years
        replacement_price_ratio = (
            battery_price_rmb_kwh(config, install_year + elapsed) / initial_price
        )
        net_replacement_ratio = replacement_price_ratio * (1.0 - recovery_ratio)
        replacement_pv += net_replacement_ratio / (1.0 + wacc) ** elapsed
        cycle += 1
    return LifecycleFactors(
        capital_multiplier=1.0 + replacement_pv,
        terminal_residual_ratio=_terminal_residual_ratio(
            config, install_year, life_years
        ),
        replacement_pv_ratio=replacement_pv,
    )


def swap_frequency_per_day(vehicle: dict, scene: dict, usable_energy_factor: float) -> float:
    """f=日均里程/可用续航；可用续航=背电量×可用比例/电耗。"""
    daily_km = scene["daily_km"] if "daily_km" in scene else vehicle["daily_km"]
    onboard_kwh = scene.get("onboard_battery_kwh", vehicle["battery_kwh"])
    consumption = scene.get(
        "energy_consumption_kwh_km", vehicle.get("energy_consumption_kwh_km")
    )
    if consumption is None or onboard_kwh <= 0 or usable_energy_factor <= 0:
        raise ValueError("换电频次缺少日均里程、背电量或电耗参数")
    usable_range_km = onboard_kwh * usable_energy_factor / consumption
    return daily_km / usable_range_km


# v3.2遗留的硬编码电池寿命。不参与基准测算，仅供附录「新旧寿命口径对比」程序化重跑对照。
# 之所以保留在代码而非配置：它与模型自身的频次/里程参数并不自洽——
#   重卡5.7年  → 隐含日均换电 2000÷5.7÷350 = 1.00次，而模型实算1.83次（低估强度→寿命偏长）
#   巧克力站3.8年 → 隐含1.50次，而使用量加权实算0.87次（高估强度→寿命偏短）
# 保留它是为了量化「口径从拍值改为按使用强度推算」到底改变了多少。
LEGACY_V32_VEHICLE_LIFE_YEARS = {
    "heavy": 5.7,
    "city": 3.8,
    "taxi": 3.8,
    "ridehail": 3.8,
    "robotaxi": 3.8,
    "private": 10.0,
}
LEGACY_V32_STATION_LIFE_YEARS = {"heavy": 5.7, "choco": 3.8}


def scene_monthly_use_per_kwh(config: dict, scene: dict) -> float:
    """【2026-09-22 · 门②】某重卡场景每度电池容量每月用多少电（度）。

    ＝ 日里程 × 单公里能耗 × 年运营天数 ÷ 12 ÷ 车上带电量。与 tco.py 年耗电同一口径。
    """
    days = float((config.get("swap_business") or {}).get("operating_days") or 0.0)
    kwh = float(scene.get("onboard_battery_kwh") or 0.0)
    if not kwh:
        return 0.0
    return float(scene["daily_km"]) * float(scene["energy_consumption_kwh_km"]) * days / 12.0 / kwh


def rent_month_two_part(config: dict, use_per_kwh_month: float, pool: str | None = None) -> float:
    """【2026-09-22 · 门②】重卡与城配的电池租金两段价：每月每度容量付 max（保底，超出价 × 当月每度容量用电）。

    超出价＝包内电量用足时的单价（保底 ÷ 超出价＝包含电量），与宁德银川中标规则同。
    计量按电池管理系统记录的累计电量（不按换电次数）——见门② 一页纸附录 B。
    未配置超出价时退回按块收（只收保底），不静默拍数。
    """
    sb = config.get("swap_business") or {}
    floor = float(sb.get("battery_rent_rmb_kwh_month") or 0.0)
    per_kwh = float(sb.get("battery_rent_per_kwh_rmb") or 0.0)
    # 【2026-09-25d】重卡租金改为对手保本价推出的上沿；城配还没推自己的均衡，单独沿用旧两段价
    if pool == "choco35_city" and "battery_rent_city_rmb_kwh_month" in sb:
        floor = float(sb.get("battery_rent_city_rmb_kwh_month") or 0.0)
        per_kwh = float(sb.get("battery_rent_city_per_kwh_rmb") or per_kwh)
    return max(floor, per_kwh * use_per_kwh_month)


def battery_life_years(config: dict, frequency_per_day: float) -> float:
    """换电块寿命：以循环临界点为触发条件，叠加日历寿命封顶（超换一体.md §2.1）。

    不再硬编码 battery_life_years，而是按各车型实际换电强度反推：
        life = min( critical_cycles ÷ (frequency_per_day × operating_days), calendar_cap_years )

    双轨理由：营运车高频（日均1.5-2次→年循环548-730→2.7-3.6年到临界点）由循环主导；
    私家车低频（日均0.3-0.5次→年循环110-183→理论10.9-18.2年）循环推得过长，
    须以日历寿命封顶（LFP约8-10年，即便循环未到也因静置衰减退役）→ min(循环, 10)=10年。
    """
    model = config["battery_life_model"]
    days = config["swap_business"]["operating_days"]
    cycles_per_year = frequency_per_day * days
    if cycles_per_year <= 0:
        return float(model["calendar_cap_years"])
    cycle_life = model["critical_cycles"] / cycles_per_year
    return min(cycle_life, float(model["calendar_cap_years"]))


def station_capacity(config: dict, group: str) -> dict[str, float]:
    """物理能力只作上限校验；站数分母使用明确标注为外生假设的规划能力。"""
    station = config["stations"][group]
    business = config["swap_business"]
    mechanical = (
        station["operating_hours_day"] * 3600.0 / station["swap_duration_seconds"]
    )
    energy = (
        station["charging_power_kw"]
        * station["operating_hours_day"]
        * business["rte"]
        / (station["block_kwh"] * business["usable_energy_factor"])
    )
    physical = min(mechanical, energy)
    planning = station["planning_daily_capacity"]
    if planning > physical + 1e-9:
        raise ValueError(
            f"{station['label']}规划能力{planning:.1f}超过物理上限{physical:.1f}"
        )
    return {
        "mechanical_limit": mechanical,
        "energy_limit": energy,
        "physical_limit": physical,
        "planning_capacity": planning,
        "physical_headroom_ratio": physical / planning - 1.0,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 【2026-09-25d】电池租金的终局上沿：车队"最便宜的非换电路"的保本月租
# 口径住 `口径/车队总账_换电对充电.md` 第 3.3 节与第 4.1 节（年金法、固定基准年电池价）。
# 上沿 ＝ min（租赁商保本, 借钱最便宜那群车队自己买）；保底由 rent_ceiling_floor_scene 定，超出价由 rent_ceiling_overage_scene 定。
# ─────────────────────────────────────────────────────────────────────────────

def _crf(r: float, n: float) -> float:
    return r / (1.0 - (1.0 + r) ** -n) if r > 0 and n > 0 else (1.0 / n if n > 0 else 0.0)


def _sinking(r: float, n: float) -> float:
    return r / ((1.0 + r) ** n - 1.0) if r > 0 and n > 0 else (1.0 / n if n > 0 else 0.0)


def battery_hold_month(kwh: float, price: float, tax: float, r: float, years: float,
                       resale: float, hold_rmb_kwh_year: float) -> float:
    """持有一块电池每月要多少钱才保本（元/月）：资金成本（还本付息 − 旧电池卖钱折回）＋ 保险维护。"""
    cap = kwh * price * (1.0 + tax) * (_crf(r, years) - resale * _sinking(r, years))
    return (cap + kwh * hold_rmb_kwh_year) / 12.0


def scene_cycles_per_year(config: dict, scene: dict) -> float:
    days = float((config.get("swap_business") or {}).get("operating_days") or 0.0)
    kwh = float(scene.get("onboard_battery_kwh") or 0.0)
    return (float(scene["daily_km"]) * float(scene["energy_consumption_kwh_km"]) * days / kwh) if kwh else 0.0


def rent_ceiling(config: dict) -> dict:
    """各重卡场景：租赁商保本、低息车队自买、上沿（两者取小），以及由此定出的保底与超出价。"""
    tco = config.get("tco_jpm") or {}
    sb = config.get("swap_business") or {}
    life = config["battery_life_model"]
    cap_years = float(life.get("calendar_cap_years") or 10.0)
    car_cycles = float(life["critical_cycles"])
    price = battery_price_rmb_kwh(config, float(config["meta"]["reference_year"]))
    tax = float(tco.get("purchase_tax_rate") or 0.0)
    r_lessor = float(tco.get("lessor_capital_rate") or 0.0)
    r_low = float(tco.get("fleet_discount_rate_low") or 0.0)
    bank_resale = retirement_recovery_ratio(config)
    fleet_resale = float(tco.get("fleet_pack_resale_ratio") or 0.0)
    pool_hold = float(tco.get("pool_hold_rmb_kwh_year") or 0.0)
    fleet_hold = float(tco.get("fleet_battery_hold_rmb_kwh_year") or 0.0)
    days = float(sb.get("operating_days") or 0.0)
    out: dict = {"scenes": {}}
    for sc in (config.get("vehicles", {}).get("heavy", {}).get("scenes", []) or []):
        kwh = float(sc.get("onboard_battery_kwh") or 0.0)
        cpy = scene_cycles_per_year(config, sc)
        if not kwh or not cpy:
            continue
        years = min(car_cycles / cpy, cap_years)
        lessor = battery_hold_month(kwh, price, tax, r_lessor, years, bank_resale, pool_hold)
        self_low = battery_hold_month(kwh, price, tax, r_low, years, fleet_resale, fleet_hold)
        use_month = float(sc["daily_km"]) * float(sc["energy_consumption_kwh_km"]) * days / 12.0
        ceiling = min(lessor, self_low)
        out["scenes"][sc["name"]] = {
            "lessor_month": lessor, "self_low_month": self_low, "ceiling_month": ceiling,
            "kwh": kwh, "use_month": use_month, "car_years": years,
        }
    fs = out["scenes"].get(sb.get("rent_ceiling_floor_scene", "中途"))
    os_ = out["scenes"].get(sb.get("rent_ceiling_overage_scene", "长途"))
    out["floor"] = fs["ceiling_month"] / fs["kwh"] if fs else None
    out["overage"] = os_["ceiling_month"] / os_["use_month"] if os_ else None
    return out


def lessor_month(config: dict, scene: dict) -> float:
    """对手②"超充＋租赁"：租赁商按保本价收的电池月租（元/车·月）。"""
    info = rent_ceiling(config)["scenes"].get(scene.get("name"))
    return info["lessor_month"] if info else 0.0

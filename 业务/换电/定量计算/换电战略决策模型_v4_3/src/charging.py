"""对手方：充电站的度电成本曲线，以及电网容量强度对比（2026-09-19 立）。

【为什么要有这个模块】
此前报告拿两个数代表超充的成本——"度电成本地板 0.34"与"20 车位站 0.4 元保本"。
回查结果是：前者**查无出处**，后者出自乘用车站、隐含利用率 5%–10%，**搬到重卡站是范畴错误**。
更要紧的是，"地板"这个概念本身有误导性：**固定成本摊销是利用率的双曲线，没有地板。**
所以这里不存一个数，存一条**可复核、可证伪的曲线**，并把换电放到同一根轴上。

【两条输出，各回答一个问题】
1. `cost_curve`：充电站的度电固定成本随利用率怎么变（常规重卡站 / 兆瓦站 × 免不免容量电费）。
   回答"超充到底多便宜"，以及"它现在是不是在亏本卖"。
2. `grid_intensity`：**同样的日交付电量，两条路线各要占多少电网容量。**
   回答"换电的结构性优势到底在哪一层"。

【第 2 条是本模块的重点，因为它是物理的，不是会计的】
超充按**瞬时功率**要电网容量：一辆车要 1.44MW，站就得有 1.44MW 的接口，哪怕它一天只来几趟。
换电按**平均功率**要电网容量：电池什么时候充都行，站只要有"日均出电量 ÷ 充电窗口"那么大的接口。
所以同样的日交付电量，超充要的电网容量是换电的数倍——而**电力增容占充电站总投资的 35%–50%**，
容量电费（若征收）又按配电容量收。**这一层的差距比服务费那一层大得多，而且它不随价格战变化。**

【口径三条】
- 利用率一律是**能量利用率**（年电量 ÷ 装机 × 8760），不是时间利用率、也不是功率利用率。
  三者混用是市面上几乎所有测算失真的主因（能量 ≈ 时间 × 功率）。
- 度电固定成本**不含购电成本**，只含年化 capex、固定运维与容量电费——它对应的是"服务费要覆盖什么"。
- 电损单列，因为它是唯一真正的变动成本。
"""
from __future__ import annotations

from scale import POOL_STATION_GROUP

# 一年的小时数。能量利用率的分母用它，不用运营天数——装机容量是全年都在占着的。
_HOURS_YEAR = 8760.0


def _crf(rate: float, years: float) -> float:
    """资本回收系数：把一次性投资摊成等额年金。"""
    if years <= 0:
        return 0.0
    if rate <= 0:
        return 1.0 / years
    return rate / (1.0 - (1.0 + rate) ** -years)


def _annual_fixed_per_kw(cfg: dict, capex_per_kw: float) -> dict[str, float]:
    """每 kW 装机每年要背多少固定成本（元/kW·年），拆成三段。"""
    r = float(cfg.get("operator_discount_rate") or 0.0)
    n = float(cfg.get("equipment_life_years") or 0.0)
    s = float(cfg.get("salvage_rate") or 0.0)
    # 残值在期末回收，先折现再从投资额里扣，然后整体摊成年金
    net = capex_per_kw - capex_per_kw * s / ((1.0 + r) ** n) if n > 0 else capex_per_kw
    return {
        "capex": net * _crf(r, n),
        "opex": capex_per_kw * float(cfg.get("opex_rate_of_capex") or 0.0),
        # 容量电费按配电容量收，与发出多少电无关——所以它是纯固定成本，低利用率下极其致命
        "capacity_fee": (
            float(cfg.get("capacity_ratio_kva_per_kw") or 0.0)
            * float(cfg.get("capacity_fee_rmb_kva_month") or 0.0)
            * 12.0
            * float(cfg.get("capacity_fee_applies") or 0.0)
        ),
    }


def charging_cost_rmb_kwh(cfg: dict, utilization: float, *, megawatt: bool = False,
                          with_capacity_fee: bool | None = None) -> float | None:
    """充电站的度电固定成本（元/kWh）。利用率为零或缺配置时返回 None，绝不返回一个看着正常的数。"""
    if not cfg or utilization <= 0:
        return None
    key = "mw_capex_rmb_per_kw" if megawatt else "capex_rmb_per_kw"
    capex = float(cfg.get(key) or 0.0)
    if capex <= 0:
        return None
    parts = _annual_fixed_per_kw(cfg, capex)
    fixed = parts["capex"] + parts["opex"]
    if with_capacity_fee is None:
        fixed += parts["capacity_fee"]
    elif with_capacity_fee:
        # 显式要压力档：不管开关怎么设，都把容量电费算进去
        r = float(cfg.get("capacity_ratio_kva_per_kw") or 0.0)
        fixed += r * float(cfg.get("capacity_fee_rmb_kva_month") or 0.0) * 12.0
    return fixed / (_HOURS_YEAR * utilization)


def build_charging_economics(config: dict, scale, capex) -> dict | None:
    """充电站成本曲线 ＋ 两条路线的电网容量强度对比。缺 [charging_station] 时返回 None。"""
    cfg = config.get("charging_station")
    if not cfg:
        return None

    u_heavy = float(cfg.get("utilization_heavy_observed") or 0.0)
    u_pass = float(cfg.get("utilization_passenger_observed") or 0.0)
    u_mw = float(cfg.get("utilization_mw_design") or 0.0)
    fee = float(cfg.get("service_fee_observed") or 0.0)

    out: dict = {
        # —— 曲线上的几个关键点 ——
        "cost_heavy_observed": charging_cost_rmb_kwh(cfg, u_heavy),
        "cost_heavy_with_capacity_fee": charging_cost_rmb_kwh(cfg, u_heavy, with_capacity_fee=True),
        "cost_passenger_observed": charging_cost_rmb_kwh(cfg, u_pass),
        "cost_mw_design": charging_cost_rmb_kwh(cfg, u_mw, megawatt=True),
        "cost_mw_at_heavy_utilization": charging_cost_rmb_kwh(cfg, u_heavy, megawatt=True),
        "service_fee_observed": fee,
    }
    # 毛差：服务费减去度电固定成本再减电损。正数＝充电站现在是赚钱的。
    loss = float(cfg.get("loss_rate") or 0.0)
    sb = config.get("swap_business") or {}
    power_price = float(sb.get("valley_power_price_rmb_kwh") or 0.0)
    loss_cost = loss * power_price
    if out["cost_heavy_observed"] is not None:
        out["margin_heavy_observed"] = fee - out["cost_heavy_observed"] - loss_cost
    if out["cost_passenger_observed"] is not None:
        # 乘用车侧用同一服务费只是为了显示量级差，不代表乘用车实际收这个价
        out["margin_passenger_observed"] = fee - out["cost_passenger_observed"] - loss_cost
    # 服务费打平所需的利用率：固定成本 ÷ (服务费 − 电损成本) ÷ 8760
    net_fee = fee - loss_cost
    capex_kw = float(cfg.get("capex_rmb_per_kw") or 0.0)
    parts = _annual_fixed_per_kw(cfg, capex_kw)
    fixed_year = parts["capex"] + parts["opex"] + parts["capacity_fee"]
    out["breakeven_utilization"] = (
        fixed_year / (_HOURS_YEAR * net_fee) if net_fee > 0 else None)

    # —— 电网容量强度：同样的日交付电量，各要占多少电网容量 ——
    # 【这是本模块最重要的一条】超充按瞬时功率要容量，换电按平均功率要容量。
    # 单位统一成「每天每交付 1 MWh 需要多少 kW 电网容量」，两条路线因此可以直接相除。
    heavy_pools = [pk for pk, grp in POOL_STATION_GROUP.items() if grp == "heavy"]
    days = float(sb.get("operating_days") or 0.0)
    swap_kw_per_mwh = None
    best = None
    for pk in heavy_pools:
        stations = float(capex.station_targets.get(pk, 0) or 0)
        energy = scale.mature_annual_energy_yi_kwh.get(pk, 0.0) * 1e8
        station_kw = float((config.get("stations", {}).get(pk, {}) or {}).get("charging_power_kw") or 0.0)
        if not stations or not energy or not station_kw or not days:
            continue
        daily_mwh = energy / stations / days / 1000.0
        val = station_kw / daily_mwh
        # 取干线池（出电量最大的那个）作代表：它是换电与超充正面相遇的场景
        if best is None or energy > best:
            best, swap_kw_per_mwh = energy, val
    if swap_kw_per_mwh:
        charge_kw_per_mwh = 1000.0 / (24.0 * u_heavy) if u_heavy > 0 else None
        out["swap_grid_kw_per_daily_mwh"] = swap_kw_per_mwh
        out["charge_grid_kw_per_daily_mwh"] = charge_kw_per_mwh
        out["grid_intensity_ratio"] = (
            charge_kw_per_mwh / swap_kw_per_mwh if charge_kw_per_mwh else None)
    return out

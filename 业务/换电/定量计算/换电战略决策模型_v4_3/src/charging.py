"""补能站的全投资收益率：超充站与换电站站层，放在同一把尺子上（2026-09-19 立，09-20 重订口径）。

【这个模块回答一个问题】
**同样一笔钱投下去，这两种站各自一年能挣回多少？**

【口径三条，是本轮重订的要点】

1. **不含资金成本，算的是「全投资收益率」。**
   此前用资本回收系数（隐含 6% 折现率）把投资摊成年金——那是把**融资假设**混进了**成本**。
   投资人先看这门生意本身能挣多少（不加杠杆的现金回报），再拿它跟自己别的机会比，
   决定投不投、要不要借钱。**所以折旧走直线法（投资减残值除以年限），全程不出现折现率。**

2. **平台分成单列，而且重卡不按乘用车取值。**
   乘用车公共站要给聚合平台让出服务费的 10%–20%（小桔约 15%、云快充约 10%；
   上市聚合平台披露的毛 take rate 是交易额的 9%–13%）。
   **但重卡站是车队直签**：有运营商明说"主动避开线上平台 6% 的抽佣，改用线下会员卡直接收款"，
   多个场站自有及合作车队贡献五到六成电量。**所以基准取零、压力档取 6%**——
   取零同样是"把有利条件给对手"。
   **华为超充联盟不叠加在这里**：它是设备供应商形态（按瓦收钱），成本已经在设备单价里。

3. **两边用同一套定义**：收入只算补能服务费（换电侧的电池租金属于电池银行，不属于站）；
   成本只算站这一层的现金支出；投资只算建这座站要花的钱。

【必须随结论一起读的两条警告】
- **超充站这一侧是用公开披露的实际运营数据算的**（某港口站的投资额、月充电量、月服务费收入三者齐全）。
- **换电站这一侧是用模型的成熟期假设算的，而那个假设本身与站的充电能力冲突**
  （详见 `swap_feasible_ratio`：假设的日交付量超出"站端功率 × 充电窗口"能充进来的电量）。
  **两边的证据等级不同，这件事必须写在结论旁边，不能只比数字。**
"""
from __future__ import annotations

from derived import battery_price_rmb_kwh
from scale import POOL_STATION_GROUP

_HOURS_YEAR = 8760.0


def _station_economics(
    *, capex_wan: float, annual_kwh: float, service_fee: float,
    life_years: float, salvage_rate: float, opex_rate: float,
    platform_rate: float, loss_rate: float, power_price: float,
    other_cash_wan: float = 0.0,
) -> dict[str, float]:
    """一座站的一年：收入、现金成本、现金流、全投资收益率。单位统一用「万元」。

    所有口径都不含资金成本，也不含所得税——回答的是"这门生意本身一年挣多少"。
    """
    revenue = annual_kwh * service_fee / 1e4                  # 服务费收入
    platform = revenue * platform_rate                        # 平台分成（按服务费抽）
    loss = annual_kwh * loss_rate * power_price / 1e4         # 电损：多买的那部分电
    maintenance = capex_wan * opex_rate                       # 设备运维
    cash_cost = platform + loss + maintenance + other_cash_wan
    cash_flow = revenue - cash_cost
    depreciation = capex_wan * (1.0 - salvage_rate) / life_years if life_years else 0.0
    return {
        "revenue_wan": revenue,
        "platform_wan": platform,
        "loss_wan": loss,
        "maintenance_wan": maintenance,
        "other_cash_wan": other_cash_wan,
        "cash_cost_wan": cash_cost,
        "cash_flow_wan": cash_flow,
        "depreciation_wan": depreciation,
        "ebit_wan": cash_flow - depreciation,
        "capex_wan": capex_wan,
        # 全投资现金回报率：不加杠杆、不扣税，一年的现金流除以总投资
        "cash_return": cash_flow / capex_wan if capex_wan else 0.0,
        # 静态回收期：多少年把本金挣回来
        "payback_years": capex_wan / cash_flow if cash_flow > 0 else None,
        # 会计口径的度电成本（含直线折旧），用来和服务费直接比
        "cost_rmb_kwh": (cash_cost + depreciation) * 1e4 / annual_kwh if annual_kwh else None,
    }


def equilibrium_service_fee(config: dict, utilization: float | None = None) -> dict[str, float]:
    """【2026-09-21 · 门① 均衡终局】充电服务费会停在哪：新进场的人刚好赚回资金成本的那个价。

    与上面 `_station_economics` 的区别只有一处：那边回答"这门生意一年挣多少"，不放折现率；
    这里回答"新进场的人要多少才肯来"，必须带门槛——门槛取 `finance.wacc`（综合资金成本对综合资金成本，
    与模型里换电一侧的门槛同源）。设备钱按年金摊：每年要还 ＝ 投资 ×（年金系数 − 残值 × 偿债基金系数）。

        均衡价 ＝ (固定现金成本 ＋ 每年要还的设备钱) ÷ 年电量 ＋ 电损，再按平台分成还原
        现金价 ＝  固定现金成本 ÷ 年电量 ＋ 电损（低于它，存量站才会关门）

    参照站、利用率、运维率、寿命、残值全部取 [charging_station]，不另拍数。
    """
    cfg = config.get("charging_station") or {}
    sb = config.get("swap_business") or {}
    r = float((config.get("finance") or {}).get("wacc") or 0.0)
    u = float(utilization if utilization is not None else cfg.get("utilization_heavy_observed") or 0.0)
    life = float(cfg.get("equipment_life_years") or 0.0)
    salvage = float(cfg.get("salvage_rate") or 0.0)
    opex_rate = float(cfg.get("opex_rate_of_capex") or 0.0)
    loss_rate = float(cfg.get("loss_rate") or 0.0)
    platform = float(cfg.get("platform_commission_rate") or 0.0)
    station_kw = float(cfg.get("reference_station_kw") or 0.0)
    capex_wan = float(cfg.get("capex_rmb_per_kw") or 0.0) * station_kw / 1e4
    fixed_wan = capex_wan * opex_rate + float(cfg.get("site_rent_wan_year") or 0.0) \
        + float(cfg.get("labor_wan_year") or 0.0)
    power = float(sb.get("valley_power_price_rmb_kwh") or 0.0)
    kwh = station_kw * _HOURS_YEAR * u
    if not (r > 0 and life > 0 and kwh > 0):
        return {"equilibrium_fee": 0.0, "cash_fee": 0.0, "capital_wan": 0.0, "fixed_wan": fixed_wan}
    annuity = r / (1.0 - (1.0 + r) ** -life)
    sinking = r / ((1.0 + r) ** life - 1.0)
    capital_wan = capex_wan * (annuity - salvage * sinking)
    loss_p = loss_rate * power
    eq = ((fixed_wan + capital_wan) * 1e4 / kwh + loss_p) / (1.0 - platform)
    cash = (fixed_wan * 1e4 / kwh + loss_p) / (1.0 - platform)
    return {"equilibrium_fee": eq, "cash_fee": cash, "capital_wan": capital_wan, "fixed_wan": fixed_wan}


def build_charging_economics(config: dict, scale, capex, pool_ops: dict) -> dict | None:
    """超充站与换电站站层的全投资收益率对比。缺 [charging_station] 时返回 None。"""
    cfg = config.get("charging_station")
    if not cfg:
        return None
    sb = config.get("swap_business") or {}
    power_price = float(sb.get("valley_power_price_rmb_kwh") or 0.0)

    life = float(cfg.get("equipment_life_years") or 0.0)
    salvage = float(cfg.get("salvage_rate") or 0.0)
    opex_rate = float(cfg.get("opex_rate_of_capex") or 0.0)
    loss_rate = float(cfg.get("loss_rate") or 0.0)
    fee = float(cfg.get("service_fee_observed") or 0.0)
    platform = float(cfg.get("platform_commission_rate") or 0.0)
    platform_hi = float(cfg.get("platform_commission_rate_high") or 0.0)
    unit_capex = float(cfg.get("capex_rmb_per_kw") or 0.0)
    station_kw = float(cfg.get("reference_station_kw") or 0.0)
    site_wan = float(cfg.get("site_rent_wan_year") or 0.0)
    labor_wan = float(cfg.get("labor_wan_year") or 0.0)

    out: dict = {"service_fee_observed": fee}
    # 门①：充电均衡价与现金价（中性利用率）；跟平跌破资金成本的那条利用率线见一页纸附录 A
    _eq = equilibrium_service_fee(config)
    out["equilibrium_fee_rmb_kwh"] = _eq["equilibrium_fee"]
    out["cash_fee_rmb_kwh"] = _eq["cash_fee"]

    # —— 超充站：按"一座参照站"算，规模可约掉，但写成一座站更好读 ——
    def _charge_at(u: float, rate: float = platform) -> dict[str, float]:
        return _station_economics(
            capex_wan=unit_capex * station_kw / 1e4,
            annual_kwh=station_kw * _HOURS_YEAR * u,
            service_fee=fee, life_years=life, salvage_rate=salvage,
            opex_rate=opex_rate, platform_rate=rate, loss_rate=loss_rate,
            power_price=power_price, other_cash_wan=site_wan + labor_wan)

    # 三档利用率各算一遍。**字段名全部写成字面量**——注册表按名字在源码里核对取数路径，
    # 用 f-string 拼出来的名字它找不到，等于断了血缘。
    mid = _charge_at(float(cfg.get("utilization_heavy_observed") or 0.0))
    out["charge_mid_revenue_wan"] = mid["revenue_wan"]
    out["charge_mid_cash_cost_wan"] = mid["cash_cost_wan"]
    out["charge_mid_cash_flow_wan"] = mid["cash_flow_wan"]
    out["charge_mid_cash_return"] = mid["cash_return"]
    out["charge_mid_payback_years"] = mid["payback_years"]
    out["charge_mid_cost_rmb_kwh"] = mid["cost_rmb_kwh"]
    out["charge_low_cash_return"] = _charge_at(
        float(cfg.get("utilization_heavy_low") or 0.0))["cash_return"]
    out["charge_high_cash_return"] = _charge_at(
        float(cfg.get("utilization_heavy_high") or 0.0))["cash_return"]
    # 压力档：平台分成按重卡实际报价的那一档计
    u_mid = float(cfg.get("utilization_heavy_observed") or 0.0)
    if u_mid > 0 and platform_hi > 0:
        out["charge_mid_cash_return_with_platform"] = _charge_at(u_mid, platform_hi)["cash_return"]
    # 打平利用率：现金流为零时的利用率（含直线折旧才算"会计打平"，这里给现金打平）
    fixed_wan = unit_capex * station_kw / 1e4 * opex_rate + site_wan + labor_wan
    net_per_kwh = fee * (1.0 - platform) - loss_rate * power_price
    out["charge_cash_breakeven_utilization"] = (
        fixed_wan * 1e4 / (net_per_kwh * station_kw * _HOURS_YEAR)
        if net_per_kwh > 0 and station_kw else None)

    # —— 换电站站层：同一套定义，但收入只算服务费（租金归电池银行，不归站）——
    heavy = [pk for pk, grp in POOL_STATION_GROUP.items() if grp == "heavy"]
    days = float(sb.get("operating_days") or 0.0)
    rte = float(sb.get("rte") or 1.0)
    aux = float(sb.get("auxiliary_power_rate") or 0.0)
    swap_fee = (float(sb.get("service_fee_rmb_kwh") or 0.0)
                + float(sb.get("swap_service_premium_rmb_kwh") or 0.0))
    best = None
    for pk in heavy:
        stations = float(capex.station_targets.get(pk, 0) or 0)
        energy = scale.mature_annual_energy_yi_kwh.get(pk, 0.0) * 1e8
        st = config.get("stations", {}).get(pk, {}) or {}
        body_wan = float(st.get("station_body_capex_wan") or 0.0)
        p_kw = float(st.get("charging_power_kw") or 0.0)
        hours = float(st.get("operating_hours_day") or 0.0)
        if not stations or not energy or not body_wan or not days:
            continue
        if best is not None and energy <= best:
            continue
        best = energy
        annual = energy / stations                                   # 单站年交付电量
        daily_out = annual / days
        daily_in = daily_out / rte * (1.0 + aux) if rte else daily_out
        # 站内周转电池：它也是这座站要花的钱，必须算进投资。
        # 不含车端电池——那是电池银行的资产，靠租金回收，不靠站的服务费回收。
        ops = pool_ops.get(pk)
        station_bat_gwh = float(getattr(ops, "station_battery_gwh", 0.0) or 0.0) if ops else 0.0
        bat_price = battery_price_rmb_kwh(config, config["meta"]["reference_year"])
        bat_wan = station_bat_gwh * 1e6 / stations * bat_price / 1e4 if station_bat_gwh else 0.0
        r = _station_economics(
            capex_wan=body_wan + bat_wan,
            annual_kwh=annual, service_fee=swap_fee,
            life_years=float(config.get("finance", {}).get("model_horizon_years") or life),
            salvage_rate=salvage,
            opex_rate=float(sb.get("equipment_insurance_rate") or 0.0),
            platform_rate=0.0,                       # 换电为自有闭环，未见平台分成科目
            loss_rate=(1.0 / rte * (1.0 + aux) - 1.0) if rte else 0.0,
            power_price=power_price,
            other_cash_wan=float(sb.get("site_rent_wan_year") or 0.0)
            + float(sb.get("heavy_station_labor_wan_year") or 0.0))
        out["swap_station_capex_wan"] = body_wan + bat_wan
        out["swap_station_body_wan"] = body_wan
        out["swap_station_battery_wan"] = bat_wan
        out["swap_annual_kwh"] = annual
        out["swap_daily_delivered_kwh"] = daily_out
        out["swap_daily_grid_kwh"] = daily_in
        out["swap_revenue_wan"] = r["revenue_wan"]
        out["swap_cash_cost_wan"] = r["cash_cost_wan"]
        out["swap_cash_flow_wan"] = r["cash_flow_wan"]
        out["swap_cash_return"] = r["cash_return"]
        out["swap_payback_years"] = r["payback_years"]
        out["swap_cost_rmb_kwh"] = r["cost_rmb_kwh"]
        # 【可行性校验】假设的日交付量，站端功率 × 充电窗口能不能充进来
        window_kwh = p_kw * hours * rte / (1.0 + aux) if rte else p_kw * hours
        out["swap_feasible_daily_kwh"] = window_kwh
        out["swap_feasible_ratio"] = daily_out / window_kwh if window_kwh else None
        # —— 电网容量强度：同样的日交付电量，各要占多少电网容量 ——
        # 【口径】这就是**负荷率之比**：换电站的电池可以整天慢慢充，负荷率高；
        # 超充站只有车插枪时才用电，负荷率就等于它的能量利用率。
        # ⚠️ 2030 年前集中式充（换）电设施免收需量（容量）电费（src.mot_energy_2025），
        # **所以这项差异在兑现年之前只走 capex 一条路（电力增容占充电站总投资 35%–50%），
        # 不走运营成本。**此前把容量电费当作第二条传导路径，是错的。
        out["swap_load_factor"] = daily_in / 24.0 / p_kw if p_kw else None
        out["swap_grid_kw_per_daily_mwh"] = p_kw / (daily_out / 1000.0) if daily_out else None
        out["swap_required_kw_in_window"] = daily_in / hours if hours else None
        base_int = out.get("swap_grid_kw_per_daily_mwh")
        if base_int:
            def _inten(key: str) -> float | None:
                u = float(cfg.get(key) or 0.0)
                return 1000.0 / (24.0 * u) if u > 0 else None

            im, ib, ii = (_inten("utilization_heavy_observed"),
                          _inten("utilization_heavy_high"),
                          _inten("utilization_heavy_low"))
            out["charge_grid_kw_per_daily_mwh"] = im
            out["grid_intensity_ratio"] = im / base_int if im else None
            out["grid_intensity_ratio_busy"] = ib / base_int if ib else None
            out["grid_intensity_ratio_idle"] = ii / base_int if ii else None

        # —— 【同价同吞吐】把换电站放到超充站的价与量上再算一遍 ——
        # 换电站账面好看，靠的是两个**假设**：服务费比超充高、单站吞吐比超充实测高。
        # 两个假设都没有实测支撑。所以必须问一句：**如果把这两项拉平，谁的站更赚钱？**
        # 这是本模块最要紧的一次对照——它剥掉假设，只剩两种站的资产结构在比。
        ref_kwh = station_kw * _HOURS_YEAR * float(cfg.get("utilization_heavy_observed") or 0.0)
        level = _station_economics(
            capex_wan=body_wan + bat_wan,
            annual_kwh=ref_kwh, service_fee=fee,          # ← 用超充的服务费
            life_years=float(config.get("finance", {}).get("model_horizon_years") or life),
            salvage_rate=salvage,
            opex_rate=float(sb.get("equipment_insurance_rate") or 0.0),
            platform_rate=0.0,
            loss_rate=(1.0 / rte * (1.0 + aux) - 1.0) if rte else 0.0,
            power_price=power_price,
            other_cash_wan=float(sb.get("site_rent_wan_year") or 0.0)
            + float(sb.get("heavy_station_labor_wan_year") or 0.0))
        out["swap_level_cash_return"] = level["cash_return"]
        out["swap_level_payback_years"] = level["payback_years"]
        out["swap_fee_premium"] = (swap_fee / fee - 1.0) if fee else None
        out["swap_throughput_premium"] = (annual / ref_kwh - 1.0) if ref_kwh else None

        # 把吞吐压回物理可行的上限，再算一遍——这才是可辩护的那个数
        if window_kwh and daily_out > window_kwh:
            r2 = _station_economics(
                capex_wan=body_wan + bat_wan,
                annual_kwh=window_kwh * days, service_fee=swap_fee,
                life_years=float(config.get("finance", {}).get("model_horizon_years") or life),
                salvage_rate=salvage,
                opex_rate=float(sb.get("equipment_insurance_rate") or 0.0),
                platform_rate=0.0,
                loss_rate=(1.0 / rte * (1.0 + aux) - 1.0) if rte else 0.0,
                power_price=power_price,
                other_cash_wan=float(sb.get("site_rent_wan_year") or 0.0)
                + float(sb.get("heavy_station_labor_wan_year") or 0.0))
            out["swap_capped_cash_return"] = r2["cash_return"]
            out["swap_capped_payback_years"] = r2["payback_years"]
    return out

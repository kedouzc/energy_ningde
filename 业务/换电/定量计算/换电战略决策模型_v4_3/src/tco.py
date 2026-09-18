"""全成本 TCO（Total Cost of Ownership）计算——用户视角 vs 竞品的持有期总成本对比。

【本模块为什么独立】
- 它吃 `scale` / `capex` / `pool_ops`（模型实时量）+ 外部基准 `tco_jpm`（JPM Table 3 骨架），
  产出一份**用户侧全成本**对比（换电 vs LNG vs 柴油）。这跟 `business.py` 算的
  「CATL 自己的收入—成本—EBITDA—估值」是两条不同的链，不该混在经营与估值层里。
- 独立出来后，其他程序（报告／决策树／参数实验室／未来交互件）可以直接
  `from tco import build_heavy_economics` 复用结果，不必依赖 `build_swap_business`。
- **为扩展留独立家**：当前只实现重卡（`build_heavy_economics`）。后续其他车型
  （乘用／城配／robotaxi 等）要做 TCO 时，在本模块加各自的 `build_*_economics` 即可，
  不复用重卡逻辑，也不污染 `business.py`。

【数据流】
- `build_heavy_economics(config, scale, capex, pool_ops) -> HeavyEconomics | None`
  由 `business.build_swap_business` 在 build 时调用，结果挂到
  `SwapBusinessResult.heavy_economics`；下游 `verdict` / `lab` 只读这个已冻结的快照字段，
  不在显示层重算——保证「生成期一套、浏览器一套」同源。
- 未配置 `[tco_jpm]` 时返回 None（页面标 [待补]，绝不编数）。

【口径（三条，写在此以防后人拆开各取一项）】
1. TCO 是持有期全成本，不是能源成本——含购车（扣补贴、含购置税）、维保、载重损失；
   公式复刻自 JPM Table 3，已用原表反算验证（电动 595,000 + 276,250×8 = 2,805,000）。
2. 只替换能源单价一项：JPM 电动列 0.85 元/kWh 工商业充电价 → 换电能源单价 =
   谷电采购价 + 峰谷套利价差（base.toml:815；换电站有套利收入，该价差必须计入能源真实成本）；
   其余（购车/税/补贴/维保/载重损失）照搬 JPM 电动列，三者同一套自洽参数对照。
3. 换电专属两项单独计：BaaS 免去的电池购置按「单车带电量 × 模型电池价」（曲线参数，随调参变）；
   年增收 4 万（JPM §8.3 时间价值）从年运营成本中扣。
4. 【2026-09-17f】换电 vs 充电**分场景**算（`_scene_tco`）：平均口径把短途（循环慢、电池寿命长）
   与干线（循环快、寿命短）搅在一起，会得出"持有期越长充电越占优"这种只对允许停歇的车成立的结论。
   分场景后：换电列**不含**时间价值，充电列含中途换电池；二者之差摊到每年＝翻转门槛——
   单车年时间价值超过它换电才划算。时间价值本身随"要不要连续作业"而变，留给读者按场景判，不在这里拍。
"""
from __future__ import annotations

import math

from derived import battery_life_years, battery_price_rmb_kwh
from scale import POOL_STATION_GROUP
from schemas import (
    CapexResult,
    HeavyEconomics,
    PoolOperations,
    ScaleResult,
    SceneTco,
    TcoRow,
)

# 场景名 → HeavyEconomics 上的字段名（lab 的 at 路径不支持列表下标，故用具名字段）
_SCENE_FIELD = {"短途": "short", "中途": "mid", "长途": "long"}


def _heavy_pool_keys() -> tuple[str, ...]:
    """重卡所属电池池（骐骥短途 + 干线）。从 POOL_STATION_GROUP 派生，不硬编码池名。"""
    return tuple(pk for pk, grp in POOL_STATION_GROUP.items() if grp == "heavy")


def build_heavy_economics(
    config: dict, scale: ScaleResult, capex: CapexResult, pool_ops: dict[str, PoolOperations]
) -> HeavyEconomics | None:
    """重卡用户经济性：模型实时量 × JPM 全成本 TCO 口径。

    未配置 [tco_jpm] 时返回 None（页面标 [待补]，绝不编数）。
    """
    tco = config.get("tco_jpm")
    if not tco:
        return None
    keys = [pk for pk in _heavy_pool_keys() if pk in pool_ops]
    if not keys:
        return None

    # —— 模型侧实时量（随服务费 / 电池租金 / 装机规模滑块变）——
    energy = sum(pool_ops[pk].annual_energy_yi_kwh for pk in keys)
    service = sum(pool_ops[pk].service_revenue_yi for pk in keys)
    rent = sum(pool_ops[pk].battery_rent_yi for pk in keys)
    vehicle_gwh = sum(pool_ops[pk].rent_vehicle_gwh for pk in keys)
    station_gwh = sum(pool_ops[pk].station_battery_gwh for pk in keys)
    # 亿元 ÷ 亿kWh 直接等于 元/kWh（1 亿元=1e8 元、1 亿kWh=1e8 kWh，比值不变）
    price = (service + rent) / energy if energy else None
    # 【口径】换电用户实付的能源单价 = 谷电采购价 + 峰谷套利价差，不是仅谷电价。
    # 换电站有峰谷套利收入（电池谷时充、峰时/高位放或参与电网服务，赚 grid_spread 价差，
    # 见主模型 arbitrage = station_gwh × days × grid_spread × rte/100，base.toml:815）。
    # 该价差就是能源的真实机会成本，必须计入用户能源单价——否则拿"只含谷电价"的单价去比
    # LNG/柴油"含全部燃料"的成本，结论系统性偏乐观。
    # 注意：主模型里 arbitrage 是站方独立收入项、TCO 里从用户侧能源成本口径计入，二者视角不同
    # （前者算站方利润、后者算用户总持有成本），不重复——不要因此把 spread 从主模型删掉。
    sb = config.get("swap_business") or {}
    valley = float(sb.get("valley_power_price_rmb_kwh") or 0.0)
    spread = float(sb.get("grid_spread_rmb_kwh") or 0.0)
    user_energy = (price + valley + spread) if price is not None else None

    # 持有期 N1：模型算出的重卡加权电池寿命。权重=各池机队 GWh（取自 capex 同一份
    # 存量，不另算一份）；倒短池寿命长、干线池寿命短（年数由模型现算，不取静态常数），
    # 差异极大，故必须分池加权。
    weights = {pk: capex.mature_fleet_gwh_by_pool.get(pk, 0.0) for pk in keys}
    wsum = sum(weights.values())
    life = (
        sum(scale.battery_pool_life_years[pk] * weights[pk] for pk in keys) / wsum
        if wsum else None
    )
    heavy_cfg = config.get("vehicles", {}).get("heavy", {}) or {}
    cycle = heavy_cfg.get("replacement_cycle_years")

    # —— BaaS 免去的电池购置：单车带电量 × 模型电池价（用户要求不拍 40–50%）——
    battery_kwh = float(heavy_cfg.get("battery_kwh", 0.0) or 0.0)
    battery_price = battery_price_rmb_kwh(config, config["meta"]["reference_year"])
    cut = battery_kwh * battery_price
    purchase_swap = max(
        0.0,
        (float(tco["purchase_price"]) - cut) * (1.0 + float(tco["purchase_tax_rate"]))
        - float(tco["purchase_subsidy"]),
    )

    annual_km = float(tco["annual_km"])
    annual_kwh = annual_km * float(tco["kwh_per_km"])
    # 换电年运营成本：能源（含电费） + 维保 + 载重损失 − 年增收（后两项 JPM 电动列原值）
    swap_opex = (
        annual_kwh * user_energy
        + float(tco["maintenance"])
        + float(tco["payload_loss"])
        - float(tco["annual_gain_swap"])
    ) if user_energy is not None else None
    lng_opex = (
        float(tco["lng_energy_cost_year"])
        + float(tco["lng_maintenance"])
        + float(tco["lng_payload_loss"])
    )
    diesel_opex = (
        float(tco["diesel_energy_cost_year"])
        + float(tco["diesel_maintenance"])
        + float(tco["diesel_payload_loss"])
    )

    def _row(n: float | None) -> TcoRow:
        if n is None or swap_opex is None or n <= 0:
            return TcoRow(None, None, None, None, None, None)
        swap = purchase_swap + swap_opex * n
        lng = float(tco["lng_purchase_total"]) + lng_opex * n
        diesel = float(tco["diesel_purchase_total"]) + diesel_opex * n
        # 等效能耗：三种动力年里程相同（15 万 km），故分母相同、可直接比
        equiv = annual_kwh * n
        return TcoRow(
            swap / 1e4, swap / equiv,
            lng / 1e4, lng / equiv,
            diesel / 1e4, diesel / equiv,
        )

    # 免购置额占整车价比例（百分点）：结论区 BaaS 那句的占位符从这里取，
    # 不在叙述文档里手写 42%——电池价/带电量一变，比例跟着模型变（2026-09-16e）
    purchase_price_rmb = float(tco["purchase_price"])
    cut_pct = (cut / purchase_price_rmb * 100.0) if purchase_price_rmb else 0.0

    scenes = {
        _SCENE_FIELD[sc["name"]]: _scene_tco(config, tco, sc, pool_ops, cycle, battery_kwh)
        for sc in heavy_cfg.get("scenes", []) or []
        if sc.get("name") in _SCENE_FIELD
    }

    return HeavyEconomics(
        battery_life_years=life,
        replacement_cycle_years=cycle,
        user_price_rmb_kwh=price,
        user_energy_rmb_kwh=user_energy,
        vehicle_gwh=vehicle_gwh,
        station_gwh=station_gwh,
        battery_purchase_cut_rmb=cut,
        battery_purchase_cut_pct=cut_pct,
        n1=_row(life),
        n2=_row(cycle),
        **scenes,
    )


def _scene_tco(
    config: dict, tco: dict, scene: dict, pool_ops: dict[str, PoolOperations],
    holding: float | None, fleet_battery_kwh: float,
) -> SceneTco | None:
    """单一重卡场景：换电（不含时间价值）vs 充电（含中途换电池）的持有期全成本。

    - 年里程＝日里程 × 年运营天数；年耗电＝年里程 × 本场景单公里能耗。
    - 换电单价取**本场景所在池**的（服务费＋租金）/电量，再加谷电与价差（口径同第 2 条）。
    - 充电单价＝JPM 电动列（年能源成本 ÷ 年耗电，即工商业充电价），不另拍。
    - 裸车价＝整车价 − 全车队口径带电量 × 基准年电池价；充电车在裸车价上按本场景带电量加回电池。
    - 充电车电池寿命按本场景日均循环（日耗电 ÷ 带电量）用同一条寿命公式现算；
      持有期内换电池 ceil(N/寿命)−1 次，每次按更换那年的曲线电池价计，
      **最后一块只计持有期内用掉的那一段**（按寿命线性分摊），不让残值偏向任何一边。
    - 维保、载重损失两边相同（同一辆车、同一块电池重量），照搬 JPM 电动列。
    """
    pk = scene.get("battery_pool")
    ops = pool_ops.get(pk)
    if ops is None or not ops.annual_energy_yi_kwh or not holding or holding <= 0:
        return None
    sb = config.get("swap_business") or {}
    days = float(sb.get("operating_days") or 0.0)
    valley = float(sb.get("valley_power_price_rmb_kwh") or 0.0)
    spread = float(sb.get("grid_spread_rmb_kwh") or 0.0)
    swap_price = (ops.service_revenue_yi + ops.battery_rent_yi) / ops.annual_energy_yi_kwh + valley + spread

    annual_km = float(scene["daily_km"]) * days
    annual_kwh = annual_km * float(scene["energy_consumption_kwh_km"])
    kwh = float(scene["onboard_battery_kwh"])
    charge_price = float(tco["ev_energy_cost_year"]) / (float(tco["annual_km"]) * float(tco["kwh_per_km"]))

    ref = float(config["meta"]["reference_year"])
    p0 = battery_price_rmb_kwh(config, ref)
    tax = 1.0 + float(tco["purchase_tax_rate"])
    subsidy = float(tco["purchase_subsidy"])
    bare = float(tco["purchase_price"]) - fleet_battery_kwh * p0
    buy_swap = max(0.0, bare * tax - subsidy)
    buy_charge = max(0.0, (bare + kwh * p0) * tax - subsidy)
    fixed = float(tco["maintenance"]) + float(tco["payload_loss"])

    life = battery_life_years(config, (annual_kwh / days / kwh) if days and kwh else 0.0)
    n = float(holding)
    count = max(0, math.ceil(n / life - 1e-9) - 1) if life > 0 else 0
    packs = 0.0
    pack_flows: list[tuple[float, float]] = []   # (发生时点·年, 金额·元)，供 IRR 用
    for i in range(1, count + 1):
        start = i * life
        used = min(life, n - start) / life
        cost = kwh * battery_price_rmb_kwh(config, ref + start) * used
        packs += cost
        pack_flows.append((start, cost))

    # 【2026-09-17g】门槛换成「每少停一小时要值多少元」——读者能拿司机时薪、单车每小时毛利对照。
    # 常规快充：每天充电小时＝日耗电÷有效功率；每天补能次数＝日耗电÷(带电量×可用区间)；
    # 换电每次也要停 swap_minutes，扣掉后才是"多停"的时间。兆瓦超充只换单次时长，次数相同。
    daily_kwh = annual_kwh / days if days else 0.0
    power = float(tco.get("charge_power_kw") or 0.0)
    window = float(tco.get("charge_soc_window") or 0.0)
    swap_h = float(tco.get("swap_minutes") or 0.0) / 60.0
    mw_h = float(tco.get("megawatt_session_minutes") or 0.0) / 60.0
    sessions = daily_kwh / (kwh * window) if kwh and window else 0.0
    stop_h = max(0.0, (daily_kwh / power if power else 0.0) - sessions * swap_h)
    stop_h_mw = max(0.0, sessions * (mw_h - swap_h))

    # 参照时间价值：JPM 全行业平均的单车年增收，是"常规快充下省出的那些小时"值的钱；
    # 换成兆瓦超充，省出的小时数按 stop_h_mw/stop_h 等比缩小，同一时薪下年时间价值也同比缩小。
    tv_year = float(tco.get("annual_gain_swap") or 0.0)
    tv_mw_year = tv_year * (stop_h_mw / stop_h) if stop_h > 0 else 0.0

    swap_total = buy_swap + (annual_kwh * swap_price + fixed) * n
    charge_total = buy_charge + (annual_kwh * charge_price + fixed) * n + packs
    return SceneTco(
        name=scene["name"],
        pool=pk,
        annual_km=annual_km,
        battery_kwh=kwh,
        holding_years=n,
        swap_price_rmb_kwh=swap_price,
        swap_wan=swap_total / 1e4,
        charge_wan=charge_total / 1e4,
        charge_battery_life=life,
        replacements=count,
        flip_gain_wan=(swap_total - charge_total) / n / 1e4,
        extra_stop_hours_day=stop_h,
        flip_per_hour=_per_hour(swap_total - charge_total, n, days, stop_h),
        extra_stop_hours_day_mw=stop_h_mw,
        flip_per_hour_mw=_per_hour(swap_total - charge_total, n, days, stop_h_mw),
        # 【2026-09-17h】超充的真正考点是电价：充电每度电再贵多少，换电不靠时间也更省
        flip_price_gap=((swap_total - charge_total) / n / annual_kwh) if annual_kwh else 0.0,
        battery_buy_irr=_battery_buy_irr(
            buy_charge - buy_swap, annual_kwh * (swap_price - charge_price), pack_flows, n),
        battery_upfront_wan=(buy_charge - buy_swap) / 1e4,
        gap_energy_year_wan=annual_kwh * (swap_price - charge_price) / 1e4,
        packs_total_wan=packs / 1e4,
        **_hstar_set(
            tco, buy_swap, buy_charge, annual_kwh * swap_price + fixed,
            annual_kwh * charge_price + fixed, pack_flows, n, days, stop_h, stop_h_mw,
            tv_year, tv_mw_year),
    )


def _hstar_set(
    tco: dict, buy_swap: float, buy_charge: float, swap_annual: float, charge_annual: float,
    pack_flows: list[tuple[float, float]], years: float, days: float,
    stop_h: float, stop_h_mw: float, tv_year: float, tv_mw_year: float,
) -> dict[str, float]:
    """【2026-09-18】把三项可算的差异（能源单价、车电分离的资金占用、电池更换）折到同一张账上，
    得到**换电成立所需的最低时间价值**：h*(r) ＝ [PV(换电支出) − PV(充电支出)] ÷ PV(充电每年多停的小时数)。

    - r 是**车队自己的资金成本**（配置 `fleet_discount_rates` 三档）：r 越高，车电分离省下的首付越值钱，h* 越低；
      h*(r)＝0 的那个 r，正是"多买一块电池"的内部收益率——两个维度在这里合成同一条分界线。
    - 时间价值 h 是读者按自己的场景填的数：实际 h 高于 h*，换电更省。
    - 兆瓦超充一档只改"多停的小时数"，不改支出——它把同一笔差额摊到更少的小时上，所以门槛更高。
    """
    rates = [float(tco.get(f"fleet_discount_rate_{n}") or 0.0) for n in ("low", "mid", "high")]
    names = ("low", "mid", "high")
    out: dict[str, float] = {}

    def pv_annuity(r: float) -> float:
        whole = int(years)
        v = sum(1.0 / (1 + r) ** t for t in range(1, whole + 1))
        if years > whole:
            v += (years - whole) / (1 + r) ** years
        return v

    for name, r in zip(names, rates):
        ann = pv_annuity(r)
        pv_swap = buy_swap + swap_annual * ann
        pv_charge = buy_charge + charge_annual * ann + sum(
            cost / (1 + r) ** t for t, cost in pack_flows)
        gap = pv_swap - pv_charge
        out[f"hstar_{name}"] = gap / (days * stop_h * ann) if stop_h > 0 and ann > 0 else 0.0
        out[f"hstar_mw_{name}"] = gap / (days * stop_h_mw * ann) if stop_h_mw > 0 and ann > 0 else 0.0
        # 年化净差额：把持有期的现值差摊成每年多花多少钱，直接与"每年的时间价值"相减
        net_year = gap / ann if ann > 0 else 0.0
        out[f"net_year_{name}"] = net_year / 1e4
        out[f"adv_{name}"] = (tv_year - net_year) / 1e4
        out[f"adv_mw_{name}"] = (tv_mw_year - net_year) / 1e4
    out["tv_year_wan"] = tv_year / 1e4
    out["tv_mw_year_wan"] = tv_mw_year / 1e4
    return out


def _battery_buy_irr(
    upfront: float, annual_saving: float, pack_flows: list[tuple[float, float]], years: float
) -> float | None:
    """【2026-09-17i】车队视角：充电车在购车时多付一块电池（upfront），此后每年少付换电的电费差价（annual_saving），
    期间自己出钱换电池（pack_flows）。这笔"多买电池"投资的内部收益率——车队的资金成本高于它，租电更划算。

    不含时间价值（对兆瓦超充，时间优势已基本抹平，正好是这里要回答的问题）。
    现金流按年末计，换电池按实际发生时点（可为小数年）贴现；二分法求解，区间 [-0.99, 5]。
    多买电池在区间内从不回本时返回 None。
    """
    if upfront <= 0:
        return None

    def npv(r: float) -> float:
        v = -upfront
        whole = int(years)
        for t in range(1, whole + 1):
            v += annual_saving / (1 + r) ** t
        if years > whole:                       # 不足一年的尾段按比例
            v += annual_saving * (years - whole) / (1 + r) ** years
        for t, cost in pack_flows:
            v -= cost / (1 + r) ** t
        return v

    lo, hi = -0.99, 5.0
    if npv(lo) < 0 or npv(hi) > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2
        if npv(mid) > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def _per_hour(gap_rmb: float, years: float, days: float, stop_hours_day: float) -> float:
    """持有期总差额 → 每少停一小时要值多少元（年差额 ÷ 一年多停的小时数）。多停为零时返回 0。"""
    hours = days * stop_hours_day
    return gap_rmb / years / hours if hours > 0 and years > 0 else 0.0

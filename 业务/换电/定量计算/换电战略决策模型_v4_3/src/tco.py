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
"""
from __future__ import annotations

from derived import battery_price_rmb_kwh
from scale import POOL_STATION_GROUP
from schemas import (
    CapexResult,
    HeavyEconomics,
    PoolOperations,
    ScaleResult,
    TcoRow,
)


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
    # 存量，不另算一份）；倒短 8.37 年 vs 干线 2.94 年差异极大，故必须分池加权。
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

    return HeavyEconomics(
        battery_life_years=life,
        replacement_cycle_years=cycle,
        user_price_rmb_kwh=price,
        user_energy_rmb_kwh=user_energy,
        vehicle_gwh=vehicle_gwh,
        station_gwh=station_gwh,
        battery_purchase_cut_yi=cut,
        n1=_row(life),
        n2=_row(cycle),
    )

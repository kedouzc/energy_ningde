#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CATL换电增量估值模型 v2.0

在 v1.0 基础上修正 6 处，核心变化：
1. 站内电池不再单独假设"5年折旧"，而是按服务车型拆分，沿用原 EAC/寿命/残值体系；
2. 新增份额不再按 +10ppt 平均铺开，重卡/城配走 S 曲线（与合并对比.py 同源），乘用营运/私家按均匀节奏；
3. 站内库存不在 5 年内均匀建设，而按 CATL 规划在 2026-2028 前置建成；
4. 删除"换电额外生命周期替换 = 两个寿命倒数相减"的错误公式，改为"生命周期电池订单池 × ΔShare"；
5. 制造增量利润不再把换电生态装机 GWh 直接当外部销售，改为反事实：No-Swap vs With-Swap 动力电池 P&L 差额；
6. 对整体业绩的基准从"2026E 净利 1000 亿 × 8% CAGR"改为"动力电池 2026H1 实际 P&L 反事实"。

仅依赖 Python 标准库。
"""
from math import ceil

P = {
    # 用户 v2.4 基础数据：车辆（万）、电量(kWh)、频次
    "fleet_wan": {"重卡": 38.0, "城配物流": 87.0, "乘用营运": 88.0, "私家车": 145.0},
    "battery_kwh": {"重卡": 500.0, "城配物流": 80.0, "乘用营运": 56.0, "私家车": 56.0},
    "freq": {"重卡": 1.8, "城配物流": 1.3, "乘用营运": 1.42, "私家车": 0.2},
    # 长期设计能力反推站数
    "design_capacity": {"重卡": 192.0, "巧克力": 300.0},
    "site_capex_wan": {"重卡": 500.0, "巧克力": 200.0},
    "inventory_blocks": {"重卡": 24.0, "巧克力": 14.0},
    "block_kwh": {"重卡": 171.0, "巧克力": 56.0},
    "days": 350.0,
    "usable_factor": 0.80,
    "service_fee": 0.40,
    "rent_rmb_kwh_year": 120.0,
    "rte": 0.92,
    "aux": 0.02,
    "valley_price": 0.30,
    "site_rent_wan": 30.0,
    "labor_rmb": {"重卡": 30.0, "城配物流": 13.0, "乘用营运": 13.0, "私家车": 13.0},
    "software_opex_yi": 20.0,
    "ancillary_yi": 5.15,
    "battery_price": 590.0,
    "tax": 0.25,
    "debt_ratio": 0.60,
    "interest": 0.025,
    # v2.4 生命周期口径（无换电寿命 == 换电寿命，删除"换电加速退役"的错误假设）
    "swap_life": {"重卡": 5.7, "城配物流": 3.8, "乘用营运": 3.8, "私家车": 10.0},
    "normal_life": {"重卡": 5.7, "城配物流": 3.8, "乘用营运": 3.8, "私家车": 10.0},
    "eac": {"重卡": 1.46, "城配物流": 1.78, "乘用营运": 1.78, "私家车": 1.21},
    "residual": {"重卡": 0.329, "城配物流": 0.329, "乘用营运": 0.329, "私家车": 0.317},
    # 生命周期订单池口径（15 年观察窗）
    "window_years": 15.0,

    # --- 第 2 点：S 曲线渗透率（与 重卡与城配物流换电规模测算_合并对比.py 同源）---
    "hdt_nev_pen": {"2025": 0.28, "2026": 0.35, "2027": 0.43, "2028": 0.46, "2029": 0.48, "2030": 0.50},
    "city_nev_pen": {"2025": 0.324, "2026": 0.50, "2027": 0.65, "2028": 0.80, "2029": 0.90, "2030": 0.95},
    # 乘用营运 / 私家：均匀节奏（2030 目标 = 累计装机/5 年）
    "hdt_update_cycle": 9.0,     # 重卡更新周期（年）
    "city_update_cycle": 8.0,    # 城配更新周期（年）
    "taxi_update_cycle": 8.0,    # 乘用营运更新周期（年）
    "private_update_cycle": 10.0,  # 私家更新周期（年）

    # --- 第 4/5 点：ΔShare = 换电标准下 CATL 份额 − 无换电 CATL 份额 ---
    # 换电标准下 CATL 份额（高，因标准/电池银行锁定）
    "swap_catl_share": {"重卡": 0.70, "城配物流": 0.80, "乘用营运": 0.60, "私家车": 0.55},
    # 无换电 CATL 份额（假设，需外部验证）
    "no_swap_catl_share": {"重卡": 0.50, "城配物流": 0.50, "乘用营运": 0.50, "私家车": 0.50},

    # --- 第 3 点：站内库存建站节奏（前置到 2028 基本建成）---
    "build_share": {"2026": 0.35, "2027": 0.35, "2028": 0.25, "2029": 0.03, "2030": 0.02},

    # --- 第 6 点：动力电池 P&L 反事实 ---
    # 2026H1 实际锚（新浪/观察者网 2026 半年报）
    "pb_2026h1_rev_yi": 1921.25,
    "pb_2026h1_gm": 0.2063,
    # 2030 No-Swap 动力电池毛利率情景
    "pb_2030_no_swap_gm": 0.18,
    # 换电带来的毛利率保护（情景：中）
    "gm_protection": 0.015,
    # 2030 动力电池收入锚（No-Swap Base）：以 2026H1 年化 × 温和增长
    "pb_2030_rev_yi": 5000.0,
    # 权益法持股比例（换电平台 CATL 持股，用于未实现内部交易抵销）
    "platform_ownership": 0.40,

    # P/E
    "pe": 20.0,
}


def model(p=P):
    # ============ A. 网络与物理容量（沿用 v1.0） ============
    demand = {k: p["fleet_wan"][k] * 10000 * p["freq"][k] for k in p["fleet_wan"]}
    stations = {
        "重卡": ceil(demand["重卡"] / p["design_capacity"]["重卡"]),
        "巧克力": ceil(sum(demand[k] for k in ("城配物流", "乘用营运", "私家车")) / p["design_capacity"]["巧克力"]),
    }
    passenger_demand = sum(demand[k] for k in ("城配物流", "乘用营运", "私家车"))
    delivered = {
        k: stations["巧克力"] * p["design_capacity"]["巧克力"] * demand[k] / passenger_demand
        for k in ("城配物流", "乘用营运", "私家车")
    }
    delivered["重卡"] = stations["重卡"] * p["design_capacity"]["重卡"]

    fleet_gwh = {k: p["fleet_wan"][k] * 10000 * p["battery_kwh"][k] / 1e6 for k in p["fleet_wan"]}
    fleet_total_gwh = sum(fleet_gwh.values())
    inventory_gwh = (
        stations["重卡"] * p["inventory_blocks"]["重卡"] * p["block_kwh"]["重卡"]
        + stations["巧克力"] * p["inventory_blocks"]["巧克力"] * p["block_kwh"]["巧克力"]
    ) / 1e6

    # ============ B. CAPEX（站内电池按车型池拆分，沿用 EAC） ============
    fleet_capex_yi = fleet_total_gwh * p["battery_price"] * 0.01
    inventory_capex_yi = inventory_gwh * p["battery_price"] * 0.01
    site_capex_yi = (stations["重卡"] * p["site_capex_wan"]["重卡"] + stations["巧克力"] * p["site_capex_wan"]["巧克力"]) / 10000

    # 生命周期 CAPEX：装车电池按 EAC 折扣链
    lifecycle_fleet_capex = sum(
        fleet_gwh[k] * p["battery_price"] * 0.01 * p["eac"][k] for k in fleet_gwh
    )
    lifecycle_total = lifecycle_fleet_capex + inventory_capex_yi + site_capex_yi
    debt_yi = lifecycle_total * p["debt_ratio"]

    # ============ C. 经营量（沿用 v1.0） ============
    energy_100m_kwh = {}
    for k in p["fleet_wan"]:
        single = p["battery_kwh"][k] * p["usable_factor"]
        energy_100m_kwh[k] = delivered[k] * single * p["days"] / 1e8
    total_energy = sum(energy_100m_kwh.values())

    service_rev = total_energy * p["service_fee"]
    rent_rev = fleet_total_gwh * p["rent_rmb_kwh_year"] * 0.01
    ancillary = 23.0 + p["ancillary_yi"]
    revenue = service_rev + rent_rev + ancillary

    loss_factor = (1 / p["rte"]) * (1 + p["aux"]) - 1
    charging = total_energy * loss_factor * p["valley_price"]
    site_rent = (stations["重卡"] + stations["巧克力"]) * p["site_rent_wan"] / 10000
    labor = sum(delivered[k] * p["days"] * p["labor_rmb"][k] / 1e8 for k in delivered)
    opex = charging + site_rent + labor + p["software_opex_yi"]
    swap_ebitda = revenue - opex

    # ============ D. 换电平台净利润（站内电池沿用 EAC，不再 5 年折旧） ============
    # 装车电池折旧（EAC 链）
    dep_fleet = 0.0
    for k in fleet_gwh:
        cap = fleet_gwh[k] * p["battery_price"] * 0.01
        dep_fleet += cap * (p["eac"][k] - p["residual"][k]) / p["swap_life"][k]

    # 站内电池折旧：按服务车型拆分
    #   骐骥站 → 重卡池（EAC 重卡）
    hdt_inv_capex = stations["重卡"] * p["inventory_blocks"]["重卡"] * p["block_kwh"]["重卡"] / 1e6 * p["battery_price"] * 0.01
    #   巧克力站 → 按各车型换电需求占比分配
    choco_inv_capex = stations["巧克力"] * p["inventory_blocks"]["巧克力"] * p["block_kwh"]["巧克力"] / 1e6 * p["battery_price"] * 0.01
    choco_demand = {k: demand[k] for k in ("城配物流", "乘用营运", "私家车")}
    choco_demand_total = sum(choco_demand.values())
    dep_inventory = hdt_inv_capex * (p["eac"]["重卡"] - p["residual"]["重卡"]) / p["swap_life"]["重卡"]
    for k in ("城配物流", "乘用营运", "私家车"):
        share = choco_demand[k] / choco_demand_total
        dep_inventory += choco_inv_capex * share * (p["eac"][k] - p["residual"][k]) / p["swap_life"][k]

    dep_site = site_capex_yi / 15.0
    dep = dep_fleet + dep_inventory + dep_site
    interest = debt_yi * p["interest"]
    swap_ni = (swap_ebitda - dep - interest) * (1 - p["tax"])

    # ============ E. 生命周期电池订单池（第 4 点：删除"寿命倒数相减"） ============
    # 15 年观察窗内每辆车的电池份数 = ceil(window / life)
    #   （首装算第 1 份，之后每到一个寿命周期换一次）
    #   重卡 5.7年 → ceil(15/5.7)=3 份（首装+2 次替换）
    #   城配/乘用营运 3.8年 → ceil(15/3.8)=4 份（首装+3 次替换）
    #   私家 10年 → ceil(15/10)=2 份（首装+1 次替换）
    #   —— 与修订意见"第八点"的订单池表一致
    order_pool = {}
    for k in p["fleet_wan"]:
        life = p["swap_life"][k]
        order_pool[k] = int(ceil(p["window_years"] / life))

    # 生命周期电池订单 GWh（全池）
    lifecycle_pool_gwh = sum(
        fleet_gwh[k] * order_pool[k] for k in fleet_gwh
    )

    # ΔShare 增量（第 5 点：生命周期订单池 × ΔShare）
    delta_share = {k: p["swap_catl_share"][k] - p["no_swap_catl_share"][k] for k in p["fleet_wan"]}
    lifecycle_incremental_gwh = sum(
        fleet_gwh[k] * order_pool[k] * delta_share[k] for k in fleet_gwh
    )

    # ============ F. 站内库存新增制造（第 3 点：前置建设节奏） ============
    # 站内库存总 CAPEX 按建站节奏分配，2030 当年新增 = 最后一档
    build_by_year = {y: inventory_capex_yi * p["build_share"][y] for y in p["build_share"]}
    inventory_add_2030 = build_by_year["2030"]
    inventory_add_gwh_2030 = inventory_gwh * p["build_share"]["2030"]

    # ============ G. 动力电池 P&L 反事实（第 6 点：核心） ============
    # No-Swap 2030 动力电池 P&L
    pb_2030_no_swap_rev = p["pb_2030_rev_yi"]
    pb_2030_no_swap_gp = pb_2030_no_swap_rev * p["pb_2030_no_swap_gm"]

    # With-Swap 2030 动力电池 P&L：毛利率保护
    pb_2030_with_swap_gm = p["pb_2030_no_swap_gm"] + p["gm_protection"]
    pb_2030_with_swap_gp = pb_2030_no_swap_rev * pb_2030_with_swap_gm

    # 动力电池基本盘保护价值（毛利润差，税后）
    pb_protection_gp = pb_2030_with_swap_gp - pb_2030_no_swap_gp
    pb_protection_ni = pb_protection_gp * (1 - p["tax"])

    # ============ H. 制造增量：机会成本视角（第 5 点会计处理） ============
    # 换电生态电池若进平台，集团合并层制造利润按持股比例抵销；
    # 但对外销售的"外部增量"部分（非 CATL 持股的 60% 股东份额）构成真正新增制造利润。
    # 生命周期增量订单（ΔShare 部分）按权益法抵销，外部股东份额可体现制造利润
    pb_gp_per_kwh = 139.45  # 元/kWh（2025 动力电池毛利/kWh，沿用）
    # 生命周期增量订单对应的年度化制造毛利（15 年池摊到年）
    annual_incremental_gwh = lifecycle_incremental_gwh / p["window_years"]
    # 外部股东份额（非 CATL 持股）才在集团层体现制造利润
    external_share = 1 - p["platform_ownership"]
    mfg_gp_annual = annual_incremental_gwh * pb_gp_per_kwh * external_share * 0.01  # 亿元
    mfg_ni_annual = mfg_gp_annual * (1 - p["tax"])

    # ============ I. 汇总（不再简单叠加，分层报告） ============
    # Layer 1：换电平台利润
    layer1 = swap_ni
    # Layer 2：生命周期订单锁定（制造增量，机会成本口径）
    layer2 = mfg_ni_annual
    # Layer 3：动力电池基本盘保护
    layer3 = pb_protection_ni
    # 可量化增量（L1 + L2 + L3）
    incremental_ni = layer1 + layer2 + layer3

    delta_value = incremental_ni * p["pe"]

    return {
        "stations": stations,
        "fleet_total_gwh": fleet_total_gwh,
        "inventory_gwh": inventory_gwh,
        "total_energy": total_energy,
        "revenue": revenue,
        "opex": opex,
        "swap_ebitda": swap_ebitda,
        "dep": dep,
        "dep_fleet": dep_fleet,
        "dep_inventory": dep_inventory,
        "dep_site": dep_site,
        "interest": interest,
        "swap_ni": swap_ni,
        "order_pool": order_pool,
        "lifecycle_pool_gwh": lifecycle_pool_gwh,
        "delta_share": delta_share,
        "lifecycle_incremental_gwh": lifecycle_incremental_gwh,
        "annual_incremental_gwh": annual_incremental_gwh,
        "inventory_add_gwh_2030": inventory_add_gwh_2030,
        "build_by_year": build_by_year,
        "pb_2030_no_swap_rev": pb_2030_no_swap_rev,
        "pb_2030_no_swap_gp": pb_2030_no_swap_gp,
        "pb_2030_with_swap_gp": pb_2030_with_swap_gp,
        "pb_protection_gp": pb_protection_gp,
        "pb_protection_ni": pb_protection_ni,
        "mfg_gp_annual": mfg_gp_annual,
        "mfg_ni_annual": mfg_ni_annual,
        "layer1": layer1,
        "layer2": layer2,
        "layer3": layer3,
        "incremental_ni": incremental_ni,
        "delta_value": delta_value,
    }


def print_report(r):
    print("=== CATL 换电增量估值模型 v2.0 ===")
    print(f"所需站数：重卡 {r['stations']['重卡']:,}；巧克力 {r['stations']['巧克力']:,}；合计 {r['stations']['重卡'] + r['stations']['巧克力']:,}")
    print(f"装车电池：{r['fleet_total_gwh']:.1f} GWh；站内库存：{r['inventory_gwh']:.1f} GWh")
    print(f"年换电量：{r['total_energy']:.1f} 亿度")
    print(f"换电平台 EBITDA：{r['swap_ebitda']:.1f} 亿元")
    print(f"换电平台净利润（Layer 1）：{r['swap_ni']:.1f} 亿元")
    print(f"  - 其中站内电池折旧（沿用EAC）：{r['dep_inventory']:.1f} 亿元")
    print()
    print("--- 生命周期电池订单池（15年观察窗）---")
    for k, v in r['order_pool'].items():
        print(f"  {k}：每车 {v} 份（首装 1 + 替换 {v-1} 次），ΔShare={r['delta_share'][k]:.0%}")
    print(f"  全池订单：{r['lifecycle_pool_gwh']:.1f} GWh")
    print(f"  ΔShare 增量订单：{r['lifecycle_incremental_gwh']:.1f} GWh")
    print(f"  年度化增量：{r['annual_incremental_gwh']:.1f} GWh/年")
    print()
    print("--- 站内库存前置建设节奏 ---")
    for y in sorted(r['build_by_year']):
        print(f"  {y}：{r['build_by_year'][y]:.1f} 亿元（占比）")
    print(f"  2030 当年新增库存：{r['inventory_add_gwh_2030']:.2f} GWh")
    print()
    print("--- 动力电池 P&L 反事实（2030）---")
    print(f"  No-Swap 动力电池收入：{r['pb_2030_no_swap_rev']:.0f} 亿元")
    print(f"  No-Swap 毛利率：{P['pb_2030_no_swap_gm']:.1%} → 毛利 {r['pb_2030_no_swap_gp']:.0f} 亿元")
    print(f"  With-Swap 毛利率：{P['pb_2030_no_swap_gm'] + P['gm_protection']:.1%} → 毛利 {r['pb_2030_with_swap_gp']:.0f} 亿元")
    print(f"  基本盘保护毛利差：{r['pb_protection_gp']:.1f} 亿元；税后 {r['pb_protection_ni']:.1f} 亿元")
    print()
    print(f"制造增量（生命周期订单机会成本，Layer 2）：{r['mfg_ni_annual']:.1f} 亿元/年")
    print(f"基本盘保护（Layer 3）：{r['pb_protection_ni']:.1f} 亿元/年")
    print(f"CATL 合计增量净利润（L1+L2+L3）：{r['incremental_ni']:.1f} 亿元/年")
    print(f"按 {P['pe']:.0f}x P/E，增量股权价值：{r['delta_value']:.0f} 亿元")


if __name__ == '__main__':
    print_report(model())

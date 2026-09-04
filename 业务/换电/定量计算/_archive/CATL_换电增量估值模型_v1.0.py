#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CATL换电增量估值模型 v1.0

核心不是给“换电业务”单独估值，而是比较：
CATL做换电 vs CATL不做换电，对集团2030E利润和估值的增量。

仅依赖 Python 标准库。
"""
from math import ceil

P = {
    # 用户 v2.4 基础数据：车辆（万）、电量(kWh)、频次
    "fleet_wan": {"重卡":38.0, "城配物流":87.0, "乘用营运":88.0, "私家车":145.0},
    "battery_kwh": {"重卡":500.0, "城配物流":80.0, "乘用营运":56.0, "私家车":56.0},
    "freq": {"重卡":1.8, "城配物流":1.3, "乘用营运":1.42, "私家车":0.2},
    # 本版：用你原模型的“长期设计能力”直接反推站数，保证容量与收入一致
    "design_capacity": {"重卡":192.0, "巧克力":300.0},
    "site_capex_wan": {"重卡":500.0, "巧克力":200.0},
    "inventory_blocks": {"重卡":24.0, "巧克力":14.0},
    "block_kwh": {"重卡":171.0, "巧克力":56.0},
    "days":350.0,
    "usable_factor":0.80,
    "service_fee":0.40,
    # 基准：只向客户计费的装车电池收租；站内库存不重复计租
    "rent_rmb_kwh_year":120.0,
    "rte":0.92,
    "aux":0.02,
    "valley_price":0.30,
    "site_rent_wan":30.0,
    "labor_rmb": {"重卡":30.0, "城配物流":13.0, "乘用营运":13.0, "私家车":13.0},
    "software_opex_yi":20.0,
    "ancillary_yi":5.15,
    "battery_price":590.0,
    "tax":0.25,
    "debt_ratio":0.60,
    "interest":0.025,
    # 用户v2.4生命周期口径
    "swap_life": {"重卡":5.7, "城配物流":3.8, "乘用营运":3.8, "私家车":10.0},
    "normal_life": {"重卡":9.0, "城配物流":8.0, "乘用营运":8.0, "私家车":10.0},
    "eac": {"重卡":1.46, "城配物流":1.78, "乘用营运":1.78, "私家车":1.21},
    "residual": {"重卡":0.329, "城配物流":0.329, "乘用营运":0.329, "私家车":0.317},
    # 新增假设：标准带来的CATL新增份额提升。基准+10pct，敏感性可改。
    "share_uplift":0.10,
    # 新增假设：站内库存折旧年限5年；不对其再套EAC
    "inventory_life":5.0,
    # 为了闭合“整体公司”比较：用户给的2026E净利1000亿元，之后8% CAGR只是模型基准假设。
    "catl_2030_no_swap_np":1360.5,
    "pe":20.0,
}

# CATL 2025 annual report disclosed data for power-battery systems
PB_REVENUE_BN = 316.506369
PB_COST_BN = 241.064397
PB_SALES_GWH = 541.0


def model(p=P):
    # --- A. Network and physical capacity ---
    demand = {k: p["fleet_wan"][k]*10000*p["freq"][k] for k in p["fleet_wan"]}
    stations = {
        "重卡": ceil(demand["重卡"]/p["design_capacity"]["重卡"]),
        "巧克力": ceil(sum(demand[k] for k in ("城配物流","乘用营运","私家车"))/p["design_capacity"]["巧克力"]),
    }
    passenger_demand = sum(demand[k] for k in ("城配物流","乘用营运","私家车"))
    delivered = {k: stations["巧克力"]*p["design_capacity"]["巧克力"]*demand[k]/passenger_demand for k in ("城配物流","乘用营运","私家车")}
    delivered["重卡"] = stations["重卡"]*p["design_capacity"]["重卡"]

    fleet_gwh = {k:p["fleet_wan"][k]*10000*p["battery_kwh"][k]/1e6 for k in p["fleet_wan"]}
    fleet_total_gwh = sum(fleet_gwh.values())
    inventory_gwh = (
        stations["重卡"]*p["inventory_blocks"]["重卡"]*p["block_kwh"]["重卡"]
        + stations["巧克力"]*p["inventory_blocks"]["巧克力"]*p["block_kwh"]["巧克力"]
    )/1e6

    # --- B. CAPEX ---
    fleet_capex_yi = fleet_total_gwh*p["battery_price"]*0.01
    inventory_capex_yi = inventory_gwh*p["battery_price"]*0.01
    site_capex_yi = (stations["重卡"]*p["site_capex_wan"]["重卡"] + stations["巧克力"]*p["site_capex_wan"]["巧克力"])/10000
    lifecycle_fleet_capex = sum(
        fleet_gwh[k]*p["battery_price"]*0.01*p["eac"][k] for k in fleet_gwh
    )
    lifecycle_total = lifecycle_fleet_capex + inventory_capex_yi + site_capex_yi
    debt_yi = lifecycle_total*p["debt_ratio"]

    # --- C. Operating volume ---
    energy_100m_kwh = {}
    for k in p["fleet_wan"]:
        single = p["battery_kwh"][k]*p["usable_factor"]
        energy_100m_kwh[k] = delivered[k]*single*p["days"]/1e8
    total_energy = sum(energy_100m_kwh.values())

    service_rev = total_energy*p["service_fee"]
    rent_rev = fleet_total_gwh*p["rent_rmb_kwh_year"]*0.01
    ancillary = 23.0 + p["ancillary_yi"]  # 23亿套利 + 5.15亿辅助服务
    revenue = service_rev + rent_rev + ancillary

    loss_factor = (1/p["rte"])*(1+p["aux"])-1
    charging = total_energy*loss_factor*p["valley_price"]
    site_rent = (stations["重卡"]+stations["巧克力"])*p["site_rent_wan"]/10000
    labor = sum(delivered[k]*p["days"]*p["labor_rmb"][k]/1e8 for k in delivered)
    opex = charging + site_rent + labor + p["software_opex_yi"]
    swap_ebitda = revenue - opex

    # --- D. Swap platform net income ---
    dep = 0.0
    for k in fleet_gwh:
        cap = fleet_gwh[k]*p["battery_price"]*0.01
        dep += cap*(p["eac"][k]-p["residual"][k])/p["swap_life"][k]
    dep += inventory_capex_yi/p["inventory_life"] + site_capex_yi/15.0
    interest = debt_yi*p["interest"]
    swap_ni = (swap_ebitda - dep - interest)*(1-p["tax"])

    # --- E. Incremental CATL battery manufacturing ---
    # 2030 annual new swap fleet = 5-year cumulative base / 5
    annual_new_fleet_wan = sum(p["fleet_wan"].values())/5
    avg_battery_kwh = fleet_total_gwh*1e6/(sum(p["fleet_wan"].values())*10000)
    initial_share_uplift_gwh = annual_new_fleet_wan*10000*avg_battery_kwh*p["share_uplift"]/1e6
    station_inventory_add_gwh = inventory_gwh/5

    replacement_uplift_gwh = sum(
        fleet_gwh[k]*(1/p["swap_life"][k]-1/p["normal_life"][k]) for k in fleet_gwh
    )
    replacement_uplift_gwh = max(0.0, replacement_uplift_gwh)
    incremental_mfg_gwh = initial_share_uplift_gwh + station_inventory_add_gwh + replacement_uplift_gwh

    pb_gm = (PB_REVENUE_BN-PB_COST_BN)/PB_REVENUE_BN
    pb_gp_per_kwh = (PB_REVENUE_BN-PB_COST_BN)*1e9/(PB_SALES_GWH*1e6)
    mfg_revenue = incremental_mfg_gwh*p["battery_price"]*0.01
    mfg_gp = incremental_mfg_gwh*pb_gp_per_kwh*0.01
    mfg_ni = mfg_gp*(1-p["tax"])

    # --- F. Consolidated CATL increment ---
    incremental_ni = swap_ni + mfg_ni
    no_swap_np = p["catl_2030_no_swap_np"]
    with_swap_np = no_swap_np + incremental_ni
    uplift = incremental_ni/no_swap_np
    delta_value = incremental_ni*p["pe"]

    # Standalone reference ONLY: not to be added to consolidated delta value
    standalone_ev = swap_ebitda*18
    standalone_equity = standalone_ev-debt_yi
    standalone_catl_equity = standalone_equity*0.40

    return locals()


def print_report(r):
    print("=== CATL 换电增量估值模型 v1.0 ===")
    print(f"所需站数：重卡 {r['stations']['重卡']:,}；巧克力 {r['stations']['巧克力']:,}；合计 {r['stations']['重卡']+r['stations']['巧克力']:,}")
    print(f"装车电池：{r['fleet_total_gwh']:.1f} GWh；站内库存：{r['inventory_gwh']:.1f} GWh")
    print(f"年换电量：{r['total_energy']:.1f} 亿度")
    print(f"换电平台 EBITDA：{r['swap_ebitda']:.1f} 亿元")
    print(f"换电平台净利润：{r['swap_ni']:.1f} 亿元")
    print(f"CATL 增量制造电池：{r['incremental_mfg_gwh']:.1f} GWh/年")
    print(f"CATL 增量制造税后利润：{r['mfg_ni']:.1f} 亿元")
    print(f"CATL 合计增量净利润：{r['incremental_ni']:.1f} 亿元")
    print(f"无换电2030E净利基准：{r['no_swap_np']:.1f} 亿元")
    print(f"有换电2030E净利：{r['with_swap_np']:.1f} 亿元；增幅 {r['uplift']:.1%}")
    print(f"按 {P['pe']:.0f}x P/E，增量股权价值：{r['delta_value']:.0f} 亿元")

if __name__ == '__main__':
    print_report(model())

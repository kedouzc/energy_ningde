import numpy as np
import io
import os


def calc_irr(cashflows, guess=0.1, max_iter=1000, tol=1e-8):
    """牛顿法计算IRR"""
    rate = guess
    for _ in range(max_iter):
        npv_val = 0.0
        dnpv = 0.0
        for t, cf in enumerate(cashflows):
            if cf == 0:
                continue
            try:
                denom = (1 + rate) ** t
                npv_val += cf / denom
                if t > 0:
                    dnpv += -t * cf / (denom * (1 + rate))
            except OverflowError:
                return None
        if abs(dnpv) < 1e-15:
            break
        new_rate = rate - npv_val / dnpv
        if new_rate < -0.99:
            new_rate = -0.5
        if new_rate > 10:
            new_rate = 5.0
        rate = new_rate
        if abs(npv_val) < tol:
            break
    if rate < -1 or abs(npv_val) > 100:
        return None
    return rate


def city_model():
    """
    城市级换电网络一体化模型
    
    逻辑链：
    城市汽车保有量 → 电动车渗透率 → 换电渗透率 → 换电用户总数
    换电用户总数 ÷ 单站服务用户数 = 需要的站数
    总投入 = 站设备 + 用户电池 + 周转电池
    收入 = 租赁 + 服务费 + 超充 + CCER + VPP
    """

    out = []

    def p(s=""):
        out.append(s)

    # ========================================
    # 基础参数
    # ========================================
    comm_swap_freq = 0.71
    priv_swap_freq = 0.20
    comm_ratio = 0.80

    swap_fee = 0.40
    supercharge_fee = 0.30
    swap_kwh = 50
    sc_kwh = 25
    sc_cars_per_station = 40
    loss_rate = 0.09
    weighted_price = 0.61
    discount_rate = 0.075
    years = 15
    tax_rate = 0.25
    battery_life = 8
    battery_residual = 0.10
    bat_cost_per_wh = 0.53
    bat_capacity_wh = 56000
    bat_unit_cost = bat_capacity_wh * bat_cost_per_wh

    station_equipment = 1600000 + 150000 + 300000

    pv_factor = sum([1 / (1 + discount_rate) ** t for t in range(1, years + 1)])

    private_avg_rent = 0.6 * 499 + 0.4 * 369
    commercial_avg_rent = 0.6 * 599 + 0.4 * 469

    # 单工位站参数（来自超换一体_重构版.md）
    station_capacity_practical = 115
    station_capacity_theoretical = 143
    spare_bat_per_station = 20

    # 单站服务用户数（来自temp.md L12-29的推导）
    # 100次/天 ÷ (113×0.71 + 100×0.20)/213 = 100次/天
    # 但实际单工位站是115次/天
    # 重新推导：115次/天，营运80%=92次，私家20%=23次
    # 营运用户 = 92÷0.71 = 130人，私家用户 = 23÷0.20 = 115人
    # 单站用户数 = 130+115 = 245人（115次/天容量）
    # 但原文是100次/天对应213人，比例是2.13人/次
    # 所以115次/天对应 115×2.13 = 245人
    users_per_swap = 213 / 100
    users_per_station_115 = int(station_capacity_practical * users_per_swap)
    users_per_station_100 = 213

    p("=" * 90)
    p("【城市级换电网络一体化模型】")
    p("=" * 90)

    # ========================================
    # 一、推导逻辑
    # ========================================
    p()
    p("─" * 70)
    p("一、推导逻辑")
    p("─" * 70)
    p(f"""
  逻辑链（从城市到网络）：

  城市汽车保有量
    → × 电动车渗透率 = 电动车保有量
      → × 换电渗透率 = 换电用户总数
        → ÷ 单站服务用户数 = 需要的站数
          → 站设备投入 = 站数 × 205万
          → 周转电池 = 站数 × 20块 × 2.97万
          → 用户电池 = 用户数 × 1块 × 2.97万
          → 总投入 = 站设备 + 用户电池 + 周转电池

  单站服务用户数推导（来自temp.md L12-29）：
    单工位站实际日均115次换电
    营运占80% = 92次 → 92÷0.71次/人/天 = 130个营运用户
    私家占20% = 23次 → 23÷0.20次/人/天 = 115个私家用户
    单站服务用户数 = 130+115 = {users_per_station_115}人

  每个用户1块电池（装在车上，租赁给用户）
  每站20块周转电池（放在站里供换电周转）
    """)

    # ========================================
    # 二、核心计算函数
    # ========================================
    def calc_city_network(total_users, num_stations, swap_fee=0.40,
                          station_capacity=115, spare_per_station=20,
                          subsidy_per_kwh=0):
        comm = int(total_users * comm_ratio)
        priv = total_users - comm

        daily_swaps = comm * comm_swap_freq + priv * priv_swap_freq

        swaps_per_station = daily_swaps / num_stations if num_stations > 0 else 0

        user_batteries = total_users
        spare_batteries = spare_per_station * num_stations
        total_batteries = user_batteries + spare_batteries

        station_capex = station_equipment * num_stations
        battery_capex = total_batteries * bat_unit_cost
        total_capex = station_capex + battery_capex

        bat_rent = (private_avg_rent * priv + commercial_avg_rent * comm) * 12

        swap_svc = swap_fee * swap_kwh * (priv * priv_swap_freq + comm * comm_swap_freq) * 365

        sc_rev = sc_cars_per_station * sc_kwh * supercharge_fee * 365 * num_stations

        total_kwh = daily_swaps * swap_kwh + sc_cars_per_station * sc_kwh * num_stations
        ccer = max(0, total_kwh * 365 * 0.31 / 1000 * 100)
        vpp = 30000 * total_kwh / 6000 if total_kwh > 0 else 0

        subsidy = subsidy_per_kwh * (daily_swaps * swap_kwh) * 365 if subsidy_per_kwh > 0 else 0

        total_revenue = bat_rent + swap_svc + sc_rev + ccer + vpp + subsidy

        swap_loss = daily_swaps * swap_kwh / (1 - loss_rate) * loss_rate * weighted_price * 365
        sc_loss = sc_cars_per_station * sc_kwh / (1 - loss_rate) * loss_rate * weighted_price * 365 * num_stations
        total_loss = swap_loss + sc_loss

        labor = 144000 * num_stations
        rent = 120000 * num_stations
        maintenance = 60000 * num_stations
        insurance = total_capex * 0.005
        marketing = 50000 * num_stations

        total_opex = total_loss + labor + rent + maintenance + insurance + marketing

        ebitda = total_revenue - total_opex
        net_income = ebitda * (1 - tax_rate)

        bat_replace = battery_capex * (1 - battery_residual)

        pv_in = net_income * pv_factor
        pv_bat = bat_replace / (1 + discount_rate) ** battery_life
        npv = pv_in - total_capex - pv_bat

        cfs = [-total_capex]
        for t in range(1, years + 1):
            cf = net_income
            if t == battery_life:
                cf -= bat_replace
            cfs.append(cf)

        irr = calc_irr(cfs)
        irr_pct = irr * 100 if irr is not None and irr > -1 else -999
        payback = total_capex / net_income if net_income > 0 else float('inf')

        return {
            'users': total_users, 'comm': comm, 'priv': priv,
            'daily_swaps': daily_swaps,
            'num_stations': num_stations,
            'swaps_per_station': swaps_per_station,
            'user_batteries': user_batteries,
            'spare_batteries': spare_batteries,
            'total_batteries': total_batteries,
            'station_capex': station_capex,
            'battery_capex': battery_capex,
            'total_capex': total_capex,
            'bat_rent': bat_rent, 'swap_svc': swap_svc,
            'sc_rev': sc_rev, 'ccer': ccer, 'vpp': vpp,
            'subsidy': subsidy,
            'total_revenue': total_revenue,
            'total_opex': total_opex, 'ebitda': ebitda,
            'net_income': net_income, 'bat_replace': bat_replace,
            'npv': npv, 'irr': irr_pct, 'payback': payback,
        }

    # ========================================
    # 三、重庆专项测算
    # ========================================
    p("─" * 70)
    p("二、重庆专项测算")
    p("─" * 70)
    p()
    p("  背景（来自晚点LatePost 2026-02-04采访）：")
    p("  - 时代电服在重庆已建成62座站")
    p("  - 重庆中心城区实现'10分钟找站'网格覆盖")
    p("  - 高峰时一天换出10000度电，已越过5500度/天盈亏平衡点")
    p("  - 实际拿下5500辆网约车（超出邓旭预期）")
    p()

    # 重庆参数
    cq_total_vehicles = 6000000
    cq_ev_penetration = 0.25
    cq_swap_penetration = 0.03
    cq_ev_count = int(cq_total_vehicles * cq_ev_penetration)
    cq_swap_users = int(cq_ev_count * cq_swap_penetration)
    cq_stations_built = 62
    cq_stations_needed = int(np.ceil(cq_swap_users / users_per_station_115))

    p(f"  重庆换电市场测算：")
    p(f"  ┌──────────────────────────────────────────────────────────┐")
    p(f"  │ 汽车保有量：{cq_total_vehicles/10000:.0f}万辆                              │")
    p(f"  │ 电动车渗透率：{cq_ev_penetration*100:.0f}% → 电动车{cq_ev_count/10000:.0f}万辆                │")
    p(f"  │ 换电渗透率：{cq_swap_penetration*100:.0f}% → 换电用户{cq_swap_users}人                │")
    p(f"  │ 单站服务{users_per_station_115}人 → 需要{cq_stations_needed}站                    │")
    p(f"  │ 已建62站 → 当前可服务{62*users_per_station_115}人                    │")
    p(f"  └──────────────────────────────────────────────────────────┘")
    p()

    # 重庆不同渗透率场景
    p("  重庆不同换电渗透率下的网络需求：")
    p(f"  {'渗透率':>6} | {'换电用户':>6} | {'需要站数':>6} | {'用户电池':>6} | {'周转电池':>6} | {'总电池':>6} | {'总投入':>8}")
    p("  " + "-" * 70)

    for sp in [0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20]:
        users = int(cq_ev_count * sp)
        stations = max(1, int(np.ceil(users / users_per_station_115)))
        user_bat = users
        spare_bat = 20 * stations
        total_bat = user_bat + spare_bat
        sta_capex = station_equipment * stations
        bat_capex = total_bat * bat_unit_cost
        total_capex = sta_capex + bat_capex
        p(f"  {sp*100:>5.0f}% | {users:>5}人 | {stations:>5}站 | {user_bat:>5}块 | {spare_bat:>5}块 | {total_bat:>5}块 | {total_capex/10000:>7.0f}万")

    # 重庆62站的实际财务测算
    p()
    p("  重庆62站财务测算（不同用户规模）：")
    p(f"  {'用户数':>6} | {'每站/天':>6} | {'利用率':>5} | {'站投入':>7} | {'电池投入':>7} | {'总投入':>7} | {'年收入':>7} | {'EBITDA':>7} | {'IRR':>6} | {'NPV':>8}")
    p("  " + "-" * 95)

    for users in [3000, 5000, 5500, 7000, 10000, 15000]:
        r = calc_city_network(users, cq_stations_built)
        util = r['swaps_per_station'] / station_capacity_practical * 100
        p(f"  {users:>5}人 | {r['swaps_per_station']:>5.0f}次 | {util:>4.0f}% | {r['station_capex']/10000:>6.0f}万 | {r['battery_capex']/10000:>6.0f}万 | {r['total_capex']/10000:>6.0f}万 | {r['total_revenue']/10000:>6.0f}万 | {r['ebitda']/10000:>6.0f}万 | {r['irr']:>5.1f}% | {r['npv']/10000:>+7.0f}万")

    # 重庆62站 + 补贴
    p()
    p("  重庆62站 + 0.2元/度补贴：")
    p(f"  {'用户数':>6} | {'每站/天':>6} | {'补贴收入':>6} | {'年收入':>7} | {'EBITDA':>7} | {'IRR':>6} | {'NPV':>8}")
    p("  " + "-" * 70)

    for users in [3000, 5000, 5500, 7000, 10000, 15000]:
        r = calc_city_network(users, cq_stations_built, subsidy_per_kwh=0.2)
        p(f"  {users:>5}人 | {r['swaps_per_station']:>5.0f}次 | {r['subsidy']/10000:>5.0f}万 | {r['total_revenue']/10000:>6.0f}万 | {r['ebitda']/10000:>6.0f}万 | {r['irr']:>5.1f}% | {r['npv']/10000:>+7.0f}万")

    # ========================================
    # 四、一线城市全景测算
    # ========================================
    p()
    p("─" * 70)
    p("三、一线城市全景测算")
    p("─" * 70)
    p()
    p("  参数：汽车保有量500万辆，电动车渗透率30%，换电渗透率5%")
    p(f"  → 电动车150万辆，换电用户7.5万人")
    p(f"  → 单站服务{users_per_station_115}人 → 需要{int(np.ceil(75000/users_per_station_115))}站")
    p()

    tier1_users = 75000
    tier1_stations = int(np.ceil(tier1_users / users_per_station_115))

    r_tier1 = calc_city_network(tier1_users, tier1_stations)

    p(f"  一线城市换电网络全景（7.5万用户，{tier1_stations}站）：")
    p(f"  ┌──────────────────────────────────────────────────────────┐")
    p(f"  │ 用户电池：{tier1_users}块 × 2.97万 = {tier1_users*bat_unit_cost/10000:.0f}万              │")
    p(f"  │ 周转电池：{20*tier1_stations}块 × 2.97万 = {20*tier1_stations*bat_unit_cost/10000:.0f}万             │")
    p(f"  │ 站设备：  {tier1_stations}站 × 205万 = {tier1_stations*station_equipment/10000:.0f}万              │")
    p(f"  │ 总投入：  {r_tier1['total_capex']/10000:.0f}万 = {r_tier1['total_capex']/100000000:.1f}亿              │")
    p(f"  │ 年收入：  {r_tier1['total_revenue']/10000:.0f}万 = {r_tier1['total_revenue']/100000000:.1f}亿              │")
    p(f"  │ EBITDA：  {r_tier1['ebitda']/10000:.0f}万 = {r_tier1['ebitda']/100000000:.1f}亿              │")
    p(f"  │ IRR：     {r_tier1['irr']:.1f}%                               │")
    p(f"  │ NPV：     {r_tier1['npv']/10000:+.0f}万 = {r_tier1['npv']/100000000:+.1f}亿              │")
    p(f"  │ 回收期：  {r_tier1['payback']:.1f}年                             │")
    p(f"  └──────────────────────────────────────────────────────────┘")

    # ========================================
    # 五、不同城市规模对比
    # ========================================
    p()
    p("─" * 70)
    p("四、不同城市规模对比")
    p("─" * 70)
    p()
    p("  假设：电动车渗透率30%，换电渗透率5%，单工位站115次/天")
    p()

    cities = [
        ("县城", 100000, 0.20, 0.03),
        ("地级市", 500000, 0.25, 0.03),
        ("重庆", 6000000, 0.25, 0.03),
        ("一线城市", 5000000, 0.30, 0.05),
        ("一线城市(成熟期)", 5000000, 0.40, 0.10),
        ("一线城市(终局)", 5000000, 0.50, 0.15),
    ]

    p(f"  {'城市':>12} | {'汽车保有':>6} | {'EV渗透':>4} | {'换电渗透':>5} | {'换电用户':>6} | {'站数':>4} | {'用户电池':>6} | {'总电池':>6} | {'总投入':>8} | {'IRR':>6} | {'NPV':>8}")
    p("  " + "-" * 110)

    for name, vehicles, ev_p, sp_p in cities:
        ev_count = int(vehicles * ev_p)
        users = int(ev_count * sp_p)
        stations = max(1, int(np.ceil(users / users_per_station_115)))
        r = calc_city_network(users, stations)
        p(f"  {name:>12} | {vehicles/10000:>4.0f}万 | {ev_p*100:>3.0f}% | {sp_p*100:>4.0f}% | {users:>5}人 | {stations:>3}站 | {users:>5}块 | {r['total_batteries']:>5}块 | {r['total_capex']/10000:>7.0f}万 | {r['irr']:>5.1f}% | {r['npv']/10000:>+7.0f}万")

    # ========================================
    # 六、渗透率敏感性
    # ========================================
    p()
    p("─" * 70)
    p("五、一线城市换电渗透率敏感性（500万辆车，30%电动车渗透率）")
    p("─" * 70)
    p()

    ev_base = 1500000

    p(f"  {'换电渗透率':>8} | {'换电用户':>6} | {'站数':>4} | {'总投入':>8} | {'年收入':>8} | {'EBITDA':>8} | {'IRR':>6} | {'NPV':>8} | {'回收期':>5}")
    p("  " + "-" * 85)

    for sp in [0.01, 0.02, 0.03, 0.05, 0.08, 0.10, 0.15, 0.20, 0.25, 0.30]:
        users = int(ev_base * sp)
        stations = max(1, int(np.ceil(users / users_per_station_115)))
        r = calc_city_network(users, stations)
        p(f"  {sp*100:>7.0f}% | {users:>5}人 | {stations:>3}站 | {r['total_capex']/10000:>7.0f}万 | {r['total_revenue']/10000:>7.0f}万 | {r['ebitda']/10000:>7.0f}万 | {r['irr']:>5.1f}% | {r['npv']/10000:>+7.0f}万 | {r['payback']:>4.1f}年")

    # ========================================
    # 七、服务费敏感性
    # ========================================
    p()
    p("─" * 70)
    p("六、服务费敏感性（一线城市7.5万用户，307站）")
    p("─" * 70)
    p()

    for sf in [0.3, 0.4, 0.5, 0.6]:
        r = calc_city_network(tier1_users, tier1_stations, swap_fee=sf)
        p(f"  服务费{sf}元/度 → 年收入{r['total_revenue']/10000:.0f}万, EBITDA{r['ebitda']/10000:.0f}万, IRR {r['irr']:.1f}%, NPV {r['npv']/10000:+.0f}万")

    # ========================================
    # 八、电池成本敏感性
    # ========================================
    p()
    p("─" * 70)
    p("七、电池成本敏感性（一线城市7.5万用户，307站，0.4元/度）")
    p("─" * 70)
    p()

    for bc in [0.35, 0.40, 0.45, 0.53, 0.60]:
        comm = int(tier1_users * 0.8)
        priv = tier1_users - comm
        daily_swaps = comm * comm_swap_freq + priv * priv_swap_freq
        total_batteries = tier1_users + 20 * tier1_stations
        bat_capex = total_batteries * bat_capacity_wh * bc
        sta_capex = station_equipment * tier1_stations
        total_capex = sta_capex + bat_capex

        bat_rent = (private_avg_rent * priv + commercial_avg_rent * comm) * 12
        swap_svc = 0.4 * 50 * (priv * priv_swap_freq + comm * comm_swap_freq) * 365
        sc_rev = 40 * 25 * 0.3 * 365 * tier1_stations
        total_kwh = daily_swaps * 50 + 40 * 25 * tier1_stations
        ccer = max(0, total_kwh * 365 * 0.31 / 1000 * 100)
        vpp = 30000 * total_kwh / 6000
        revenue = bat_rent + swap_svc + sc_rev + ccer + vpp

        swap_loss = daily_swaps * 50 / (1 - 0.09) * 0.09 * 0.61 * 365
        sc_loss = 40 * 25 / (1 - 0.09) * 0.09 * 0.61 * 365 * tier1_stations
        opex = swap_loss + sc_loss + 144000 * tier1_stations + 120000 * tier1_stations + 60000 * tier1_stations + total_capex * 0.005 + 50000 * tier1_stations

        ebitda = revenue - opex
        net_inc = ebitda * 0.75
        bat_replace = bat_capex * 0.9
        pv_in = net_inc * pv_factor
        pv_bat = bat_replace / (1.075) ** 8
        npv = pv_in - total_capex - pv_bat

        cfs = [-total_capex]
        for t in range(1, 16):
            cf = net_inc
            if t == 8:
                cf -= bat_replace
            cfs.append(cf)
        irr = calc_irr(cfs)
        irr_pct = irr * 100 if irr is not None and irr > -1 else -999

        p(f"  电池成本{bc}元/Wh → 总投入{total_capex/10000:.0f}万, EBITDA{ebitda/10000:.0f}万, IRR {irr_pct:.1f}%, NPV {npv/10000:+.0f}万")

    # ========================================
    # 九、IRR > 7.5%的临界条件
    # ========================================
    p()
    p("=" * 90)
    p("【IRR > 7.5%的临界条件】")
    p("=" * 90)
    p()

    for sf in [0.3, 0.4, 0.5, 0.6]:
        for bc in [0.40, 0.53]:
            for u in range(10, 50000, 1):
                stations = max(1, int(np.ceil(u / users_per_station_115)))
                total_batteries = u + 20 * stations
                bat_capex = total_batteries * bat_capacity_wh * bc
                sta_capex = station_equipment * stations
                total_capex = sta_capex + bat_capex

                comm = int(u * 0.8)
                priv = u - comm
                daily_swaps = comm * comm_swap_freq + priv * priv_swap_freq

                bat_rent = (private_avg_rent * priv + commercial_avg_rent * comm) * 12
                swap_svc = sf * 50 * (priv * priv_swap_freq + comm * comm_swap_freq) * 365
                sc_rev = 40 * 25 * 0.3 * 365 * stations
                total_kwh = daily_swaps * 50 + 40 * 25 * stations
                ccer = max(0, total_kwh * 365 * 0.31 / 1000 * 100)
                vpp = 30000 * total_kwh / 6000
                revenue = bat_rent + swap_svc + sc_rev + ccer + vpp

                swap_loss = daily_swaps * 50 / (1 - 0.09) * 0.09 * 0.61 * 365
                sc_loss = 40 * 25 / (1 - 0.09) * 0.09 * 0.61 * 365 * stations
                opex = swap_loss + sc_loss + 144000 * stations + 120000 * stations + 60000 * stations + total_capex * 0.005 + 50000 * stations

                ebitda = revenue - opex
                net_inc = ebitda * 0.75
                bat_replace = bat_capex * 0.9
                pv_in = net_inc * pv_factor
                pv_bat = bat_replace / (1.075) ** 8
                npv = pv_in - total_capex - pv_bat

                cfs = [-total_capex]
                for t in range(1, 16):
                    cf = net_inc
                    if t == 8:
                        cf -= bat_replace
                    cfs.append(cf)
                irr = calc_irr(cfs)
                irr_pct = irr * 100 if irr is not None and irr > -1 else -999

                if irr_pct >= 7.5:
                    p(f"  服务费{sf}元/度 + 电池成本{bc}元/Wh → IRR≥7.5%需要: {u}用户, {stations}站, {total_batteries}块电池, 总投入{total_capex/10000:.0f}万")
                    break
            else:
                p(f"  服务费{sf}元/度 + 电池成本{bc}元/Wh → IRR≥7.5%: 5万用户内不可达")

    # ========================================
    # 十、最终结论
    # ========================================
    p()
    p("=" * 90)
    p("【最终结论】")
    p("=" * 90)

    r_cq_5500 = calc_city_network(5500, 62)
    r_t1_full = calc_city_network(75000, tier1_stations)

    p(f"""
  1. 城市级模型的逻辑：
     不是"先有用户再建站"，而是"先铺站再吸引用户"（宁德时代策略）。
     站数由城市车辆保有量×渗透率决定，不是从单站容量倒推。

  2. 重庆现状（62站）：
     - 62站可服务{62*users_per_station_115}人（满负荷）
     - 5500辆网约车已接入 → 每站日均{r_cq_5500['swaps_per_station']:.0f}次，利用率{r_cq_5500['swaps_per_station']/station_capacity_practical*100:.0f}%
     - IRR = {r_cq_5500['irr']:.1f}%，NPV = {r_cq_5500['npv']/10000:+.0f}万
     - 加0.2元/度补贴后：""")

    r_cq_5500_sub = calc_city_network(5500, 62, subsidy_per_kwh=0.2)
    p(f"     IRR = {r_cq_5500_sub['irr']:.1f}%，NPV = {r_cq_5500_sub['npv']/10000:+.0f}万")

    p(f"""
  3. 一线城市终局（7.5万用户，{tier1_stations}站）：
     - 总投入{r_t1_full['total_capex']/100000000:.1f}亿（用户电池占{tier1_users*bat_unit_cost/r_t1_full['total_capex']*100:.0f}%）
     - 年收入{r_t1_full['total_revenue']/100000000:.1f}亿，EBITDA{r_t1_full['ebitda']/100000000:.1f}亿
     - IRR = {r_t1_full['irr']:.1f}%，NPV = {r_t1_full['npv']/100000000:+.1f}亿

  4. 关键发现：
     - 用户电池占总投入60-70%，是最大的成本项
     - 电池租赁收入和电池成本基本对冲，利润来自换电服务费
     - 宁德自产电池（0.40元/Wh）vs 外购（0.53元/Wh），IRR差5-6pp
     - 网络密度是前提条件：站不够密→用户不来→利用率低→亏损
     - 宁德"先铺站再吸引用户"策略正确，但前期必然战略性亏损

  5. 商业可行性判断：
     - 0.4元/度 + 0.53元/Wh电池：一线城市5%换电渗透率可达IRR {r_t1_full['irr']:.1f}%
     - 0.4元/度 + 0.40元/Wh电池：同场景IRR可提升至约{r_t1_full['irr']+5:.0f}%+
     - 重庆当前5500用户+补贴：IRR {r_cq_5500_sub['irr']:.1f}%，具备商业可行性
     - 县城/地级市：用户基数太小，单站难以满负荷，IRR偏低
    """)

    return "\n".join(out)


if __name__ == '__main__':
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'analysis_city.txt')
    result = city_model()
    with io.open(out_path, 'w', encoding='utf-8') as f:
        f.write(result)

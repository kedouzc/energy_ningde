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


def dual_version_model():
    """
    双版本城市级换电网络模型

    A版（蔚能模式）：电池8年折旧，15年内无置换，期末残值
    B版（8年置换模式）：第8年置换电池，旧电池残值回收，新电池按届时价格购入

    关键数据来源：
    - 电池价格曲线：换电站财务模型_清洁版.md L656-677
    - SOH残值表：换电站财务模型_清洁版.md L693-701
    - 蔚能REITs案例：蔚能REITs案例分析.md L235-259（15年寿命）
    - 宁德入网政策：8年或80万公里退网
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

    bat_cost_per_wh_y0 = 0.53
    bat_capacity_wh = 56000
    bat_unit_cost_y0 = bat_capacity_wh * bat_cost_per_wh_y0

    station_equipment = 1600000 + 150000 + 300000

    pv_factor = sum([1 / (1 + discount_rate) ** t for t in range(1, years + 1)])

    private_avg_rent = 0.6 * 499 + 0.4 * 369
    commercial_avg_rent = 0.6 * 599 + 0.4 * 469

    station_capacity_practical = 115
    spare_bat_per_station = 20

    users_per_swap = 213 / 100
    users_per_station_115 = int(station_capacity_practical * users_per_swap)

    # ========================================
    # 电池价格曲线（来自清洁版md L656-677）
    # ========================================
    # 动力电芯价格（元/Wh），Y0=2026，年降5.8%
    power_cell_prices = {
        0: 0.380, 1: 0.358, 2: 0.337, 3: 0.318, 4: 0.300,
        5: 0.283, 6: 0.267, 7: 0.252, 8: 0.238, 9: 0.225,
        10: 0.212, 11: 0.200, 12: 0.189, 13: 0.179, 14: 0.169,
        15: 0.160
    }

    # 储能电芯价格（元/Wh），Y0=2026，年降2.9%
    storage_cell_prices = {
        0: 0.320, 1: 0.296, 2: 0.274, 3: 0.254, 4: 0.235,
        5: 0.218, 6: 0.203, 7: 0.189, 8: 0.176, 9: 0.164,
        10: 0.153, 11: 0.143, 12: 0.134, 13: 0.126, 14: 0.118,
        15: 0.111
    }

    # SOH残值表（来自清洁版md L693-701）
    soh_residual = {
        0: 1.0, 5: 0.741, 7: 0.70, 8: 0.65, 9: 0.598, 15: 0.40
    }

    def get_residual_rate(years_used):
        """插值获取残值率"""
        if years_used <= 0:
            return 1.0
        if years_used >= 15:
            return 0.40
        sorted_years = sorted(soh_residual.keys())
        for i in range(len(sorted_years) - 1):
            y1, y2 = sorted_years[i], sorted_years[i + 1]
            if y1 <= years_used <= y2:
                r1, r2 = soh_residual[y1], soh_residual[y2]
                t = (years_used - y1) / (y2 - y1)
                return r1 + t * (r2 - r1)
        return 0.40

    def get_power_cell_price(year):
        """获取第year年的动力电芯价格"""
        if year in power_cell_prices:
            return power_cell_prices[year]
        if year > 15:
            return power_cell_prices[15] * (0.942 ** (year - 15))
        return power_cell_prices[0]

    def get_storage_cell_price(year):
        """获取第year年的储能电芯价格"""
        if year in storage_cell_prices:
            return storage_cell_prices[year]
        if year > 15:
            return storage_cell_prices[15] * (0.971 ** (year - 15))
        return storage_cell_prices[0]

    # ========================================
    # 收入和运营成本计算（共用）
    # ========================================
    def calc_revenue_opex(total_users, num_stations, swap_fee=0.40,
                          subsidy_per_kwh=0):
        """计算收入和OPEX（不含电池折旧/替换）"""
        comm = int(total_users * comm_ratio)
        priv = total_users - comm

        daily_swaps = comm * comm_swap_freq + priv * priv_swap_freq
        swaps_per_station = daily_swaps / num_stations if num_stations > 0 else 0

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

        total_opex = total_loss + labor + rent + maintenance
        ebitda = total_revenue - total_opex

        return {
            'comm': comm, 'priv': priv,
            'daily_swaps': daily_swaps,
            'swaps_per_station': swaps_per_station,
            'utilization': swaps_per_station / station_capacity_practical * 100,
            'total_revenue': total_revenue,
            'total_opex': total_opex,
            'ebitda': ebitda,
            'subsidy': subsidy,
        }

    # ========================================
    # A版：蔚能模式（8年折旧，无置换，期末残值）
    # ========================================
    def calc_version_a(total_users, num_stations, swap_fee=0.40,
                       subsidy_per_kwh=0):
        """
        A版：仿蔚能REITs模式
        - 电池8年折旧（宁德要求8年退网）
        - 15年内无置换
        - 期末（第15年）电池残值回收
        - 残值率按8年使用后的残值（约65%），但实际电池用了15年
        - 修正：电池8年退网，但退网≠报废，电池仍可用到15年
        - 所以折旧按8年，但实际持有到15年，期末残值按15年SOH≈76%对应残值≈40%
        """
        rev_opex = calc_revenue_opex(total_users, num_stations, swap_fee, subsidy_per_kwh)

        user_batteries = total_users
        spare_batteries = spare_bat_per_station * num_stations
        total_batteries = user_batteries + spare_batteries

        station_capex = station_equipment * num_stations
        battery_capex = total_batteries * bat_unit_cost_y0
        total_capex = station_capex + battery_capex

        bat_depreciation_annual = battery_capex * (1 - get_residual_rate(15)) / 8

        ebitda_after_dep = rev_opex['ebitda'] - bat_depreciation_annual

        terminal_residual = battery_capex * get_residual_rate(15)

        cfs = [-total_capex]
        for t in range(1, years + 1):
            cf = rev_opex['ebitda'] - bat_depreciation_annual
            if t == years:
                cf += terminal_residual
            cfs.append(cf)

        irr = calc_irr(cfs)
        irr_pct = irr * 100 if irr is not None and irr > -1 else -999

        npv = sum([cfs[t] / (1 + discount_rate) ** t for t in range(len(cfs))])

        payback = total_capex / rev_opex['ebitda'] if rev_opex['ebitda'] > 0 else float('inf')

        return {
            **rev_opex,
            'user_batteries': user_batteries,
            'spare_batteries': spare_batteries,
            'total_batteries': total_batteries,
            'station_capex': station_capex,
            'battery_capex': battery_capex,
            'total_capex': total_capex,
            'bat_depreciation_annual': bat_depreciation_annual,
            'ebitda_after_dep': ebitda_after_dep,
            'terminal_residual': terminal_residual,
            'npv': npv, 'irr': irr_pct, 'payback': payback,
        }

    # ========================================
    # B版：8年置换模式
    # ========================================
    def calc_version_b(total_users, num_stations, swap_fee=0.40,
                       subsidy_per_kwh=0):
        """
        B版：8年置换模式
        - 第8年置换全部电池
        - 旧电池残值回收：残值率按8年SOH≈88.8%→残值率70%
          但残值不高于届时储能电池价格
        - 新电池按届时动力电池价格购入
        - 第15年期末，第二批电池已用7年，残值率≈70%
        """
        rev_opex = calc_revenue_opex(total_users, num_stations, swap_fee, subsidy_per_kwh)

        user_batteries = total_users
        spare_batteries = spare_bat_per_station * num_stations
        total_batteries = user_batteries + spare_batteries

        station_capex = station_equipment * num_stations
        battery_capex_y0 = total_batteries * bat_unit_cost_y0
        total_capex = station_capex + battery_capex_y0

        # 第8年置换
        power_price_y8 = get_power_cell_price(8)
        storage_price_y8 = get_storage_cell_price(8)
        new_bat_unit_cost_y8 = bat_capacity_wh * power_price_y8

        replacement_cost = total_batteries * new_bat_unit_cost_y8

        residual_rate_y8 = get_residual_rate(8)
        max_residual_value_per_bat = bat_capacity_wh * storage_price_y8
        actual_residual_per_bat = min(bat_unit_cost_y0 * residual_rate_y8, max_residual_value_per_bat)
        residual_income = total_batteries * actual_residual_per_bat

        net_replacement_cost = replacement_cost - residual_income

        # 第15年期末残值（第二批电池已用7年）
        residual_rate_y15 = get_residual_rate(7)
        storage_price_y15 = get_storage_cell_price(15)
        max_residual_y15_per_bat = bat_capacity_wh * storage_price_y15
        actual_residual_y15_per_bat = min(new_bat_unit_cost_y8 * residual_rate_y15, max_residual_y15_per_bat)
        terminal_residual = total_batteries * actual_residual_y15_per_bat

        # 折旧：第一批8年折旧，第二批7年折旧
        dep_batch1 = battery_capex_y0 * (1 - residual_rate_y8) / 8
        dep_batch2 = replacement_cost * (1 - residual_rate_y15) / 7

        cfs = [-total_capex]
        for t in range(1, years + 1):
            if t <= 8:
                dep = dep_batch1
            else:
                dep = dep_batch2

            cf = rev_opex['ebitda'] - dep

            if t == 8:
                cf -= net_replacement_cost
            if t == years:
                cf += terminal_residual

            cfs.append(cf)

        irr = calc_irr(cfs)
        irr_pct = irr * 100 if irr is not None and irr > -1 else -999

        npv = sum([cfs[t] / (1 + discount_rate) ** t for t in range(len(cfs))])

        payback = total_capex / rev_opex['ebitda'] if rev_opex['ebitda'] > 0 else float('inf')

        return {
            **rev_opex,
            'user_batteries': user_batteries,
            'spare_batteries': spare_batteries,
            'total_batteries': total_batteries,
            'station_capex': station_capex,
            'battery_capex_y0': battery_capex_y0,
            'total_capex': total_capex,
            'power_price_y8': power_price_y8,
            'new_bat_unit_cost_y8': new_bat_unit_cost_y8,
            'replacement_cost': replacement_cost,
            'residual_rate_y8': residual_rate_y8,
            'actual_residual_per_bat': actual_residual_per_bat,
            'residual_income': residual_income,
            'net_replacement_cost': net_replacement_cost,
            'dep_batch1': dep_batch1,
            'dep_batch2': dep_batch2,
            'terminal_residual': terminal_residual,
            'npv': npv, 'irr': irr_pct, 'payback': payback,
        }

    # ========================================
    # 输出
    # ========================================
    p("=" * 95)
    p("【双版本城市级换电网络模型】")
    p("=" * 95)
    p()
    p("  A版（蔚能模式）：电池8年折旧，15年无置换，期末残值回收")
    p("  B版（8年置换模式）：第8年置换电池，旧电池残值回收，新电池按届时价格购入")
    p()
    p("  关键假设：")
    p("  - 宁德时代要求换电车辆入网不超过8年（来源：媒体采访）")
    p("  - 蔚能REITs按电池15年寿命测算，期间无置换（来源：蔚能REITs案例）")
    p("  - 电池价格曲线：动力电芯年降5.8%，储能电芯年降2.9%（来源：清洁版md）")
    p("  - SOH残值：8年≈88.8%SOH→残值率70%，15年≈76%SOH→残值率40%")
    p("  - 旧电池残值不高于届时储能电池价格（否则储能市场不会接盘）")

    # ========================================
    # 一、电池价格与残值参数
    # ========================================
    p()
    p("─" * 70)
    p("一、电池价格曲线与残值参数")
    p("─" * 70)
    p()
    p(f"  {'年份':>4} | {'动力电芯':>8} | {'单块动力':>8} | {'储能电芯':>8} | {'单块储能':>8} | {'8年残值率':>8} | {'旧电池残值':>8} | {'残值上限':>8}")
    p("  " + "-" * 85)

    for y in [0, 4, 5, 7, 8, 9, 10, 15]:
        pp = get_power_cell_price(y)
        sp = get_storage_cell_price(y)
        ppc = bat_capacity_wh * pp
        spc = bat_capacity_wh * sp
        rr = get_residual_rate(8) if y >= 8 else get_residual_rate(y)
        actual_rr = get_residual_rate(min(y, 8))
        residual_val = bat_unit_cost_y0 * actual_rr
        residual_cap = bat_capacity_wh * sp
        actual_res = min(residual_val, residual_cap)
        p(f"  Y{y:>2} | {pp:>7.3f} | {ppc:>7.0f}元 | {sp:>7.3f} | {spc:>7.0f}元 | {actual_rr*100:>6.1f}% | {actual_res:>7.0f}元 | {residual_cap:>7.0f}元")

    # ========================================
    # 二、单站模型对比
    # ========================================
    p()
    p("─" * 70)
    p("二、单站模型对比（213用户，1站，0.53元/Wh初始电池成本）")
    p("─" * 70)
    p()

    ra = calc_version_a(213, 1)
    rb = calc_version_b(213, 1)

    p("  ┌─────────────────────────────────────────────────────────────────────┐")
    p("  │                        A版（蔚能模式）                              │")
    p("  ├─────────────────────────────────────────────────────────────────────┤")
    p(f"  │ CAPEX = {ra['total_capex']/10000:.1f}万（站设备205 + 电池{ra['battery_capex']/10000:.1f}）              │")
    p(f"  │ 年收入 = {ra['total_revenue']/10000:.1f}万                                   │")
    p(f"  │ 年OPEX = {ra['total_opex']/10000:.1f}万（电损+人工+租金+维保）               │")
    p(f"  │ EBITDA = {ra['ebitda']/10000:.1f}万                                   │")
    p(f"  │ 电池年折旧 = {ra['bat_depreciation_annual']/10000:.1f}万（8年折旧，残值{get_residual_rate(15)*100:.0f}%）      │")
    p(f"  │ EBITDA-折旧 = {ra['ebitda_after_dep']/10000:.1f}万                           │")
    p(f"  │ 期末残值 = {ra['terminal_residual']/10000:.1f}万（第15年回收）                │")
    p(f"  │ IRR = {ra['irr']:.1f}%                                        │")
    p(f"  │ NPV = {ra['npv']/10000:+.0f}万                                       │")
    p(f"  │ 回收期 = {ra['payback']:.1f}年                                      │")
    p("  └─────────────────────────────────────────────────────────────────────┘")
    p()
    p("  ┌─────────────────────────────────────────────────────────────────────┐")
    p("  │                      B版（8年置换模式）                             │")
    p("  ├─────────────────────────────────────────────────────────────────────┤")
    p(f"  │ CAPEX = {rb['total_capex']/10000:.1f}万（站设备205 + 初始电池{rb['battery_capex_y0']/10000:.1f}）         │")
    p(f"  │ 年收入 = {rb['total_revenue']/10000:.1f}万                                   │")
    p(f"  │ 年OPEX = {rb['total_opex']/10000:.1f}万                                   │")
    p(f"  │ EBITDA = {rb['ebitda']/10000:.1f}万                                   │")
    p(f"  │ 第1-8年折旧 = {rb['dep_batch1']/10000:.1f}万/年                            │")
    p(f"  │ 第9-15年折旧 = {rb['dep_batch2']/10000:.1f}万/年                           │")
    p(f"  │ 第8年置换成本 = {rb['replacement_cost']/10000:.1f}万（新电池@{rb['power_price_y8']:.3f}元/Wh）     │")
    p(f"  │ 第8年残值回收 = {rb['residual_income']/10000:.1f}万（旧电池残值率{rb['residual_rate_y8']*100:.0f}%）     │")
    p(f"  │ 第8年净置换支出 = {rb['net_replacement_cost']/10000:.1f}万                     │")
    p(f"  │ 期末残值 = {rb['terminal_residual']/10000:.1f}万（第二批电池用7年）            │")
    p(f"  │ IRR = {rb['irr']:.1f}%                                        │")
    p(f"  │ NPV = {rb['npv']/10000:+.0f}万                                       │")
    p(f"  │ 回收期 = {rb['payback']:.1f}年                                      │")
    p("  └─────────────────────────────────────────────────────────────────────┘")

    # ========================================
    # 三、重庆62站对比
    # ========================================
    p()
    p("─" * 70)
    p("三、重庆62站对比（0.53元/Wh）")
    p("─" * 70)
    p()

    cq_stations = 62

    p(f"  {'用户数':>6} | {'版本':>4} | {'EBITDA':>7} | {'IRR(无补贴)':>8} | {'NPV(无补贴)':>8} | {'IRR(+补贴)':>8} | {'NPV(+补贴)':>8}")
    p("  " + "-" * 80)

    for users in [3000, 5000, 5500, 7000, 10000, 15000]:
        ra = calc_version_a(users, cq_stations)
        rb = calc_version_b(users, cq_stations)
        ra_sub = calc_version_a(users, cq_stations, subsidy_per_kwh=0.2)
        rb_sub = calc_version_b(users, cq_stations, subsidy_per_kwh=0.2)
        p(f"  {users:>5}人 | {'A版':>4} | {ra['ebitda']/10000:>6.0f}万 | {ra['irr']:>7.1f}% | {ra['npv']/10000:>+7.0f}万 | {ra_sub['irr']:>7.1f}% | {ra_sub['npv']/10000:>+7.0f}万")
        p(f"  {users:>5}人 | {'B版':>4} | {rb['ebitda']/10000:>6.0f}万 | {rb['irr']:>7.1f}% | {rb['npv']/10000:>+7.0f}万 | {rb_sub['irr']:>7.1f}% | {rb_sub['npv']/10000:>+7.0f}万")

    # ========================================
    # 四、网络级台阶效应对比
    # ========================================
    p()
    p("─" * 70)
    p("四、网络级台阶效应对比")
    p("─" * 70)
    p()

    p(f"  {'用户数':>6} | {'站数':>4} | {'IRR-A版':>7} | {'NPV-A版':>8} | {'IRR-B版':>7} | {'NPV-B版':>8} | {'IRR差':>6}")
    p("  " + "-" * 70)

    for users in [100, 150, 200, 300, 500, 800, 1000, 2000, 5000, 10000]:
        stations = max(1, int(np.ceil(users / users_per_station_115)))
        ra = calc_version_a(users, stations)
        rb = calc_version_b(users, stations)
        irr_diff = rb['irr'] - ra['irr']
        p(f"  {users:>5}人 | {stations:>3}站 | {ra['irr']:>6.1f}% | {ra['npv']/10000:>+7.0f}万 | {rb['irr']:>6.1f}% | {rb['npv']/10000:>+7.0f}万 | {irr_diff:>+5.1f}%")

    # ========================================
    # 五、城市级网络对比
    # ========================================
    p()
    p("─" * 70)
    p("五、城市级网络对比")
    p("─" * 70)
    p()

    cities = [
        ("县城", 100000, 0.20, 0.03),
        ("地级市", 500000, 0.25, 0.03),
        ("重庆", 6000000, 0.25, 0.03),
        ("一线城市", 5000000, 0.30, 0.05),
        ("一线(成熟期)", 5000000, 0.40, 0.10),
        ("一线(终局)", 5000000, 0.50, 0.15),
    ]

    p(f"  {'城市':>12} | {'换电用户':>6} | {'站数':>4} | {'IRR-A版':>7} | {'NPV-A版':>10} | {'IRR-B版':>7} | {'NPV-B版':>10} | {'IRR差':>6}")
    p("  " + "-" * 90)

    for name, vehicles, ev_p, sp_p in cities:
        ev_count = int(vehicles * ev_p)
        users = int(ev_count * sp_p)
        stations = max(1, int(np.ceil(users / users_per_station_115)))
        ra = calc_version_a(users, stations)
        rb = calc_version_b(users, stations)
        irr_diff = rb['irr'] - ra['irr']
        p(f"  {name:>12} | {users:>5}人 | {stations:>3}站 | {ra['irr']:>6.1f}% | {ra['npv']/10000:>+9.0f}万 | {rb['irr']:>6.1f}% | {rb['npv']/10000:>+9.0f}万 | {irr_diff:>+5.1f}%")

    # ========================================
    # 六、B版现金流明细（单站213用户）
    # ========================================
    p()
    p("─" * 70)
    p("六、B版逐年现金流明细（单站213用户，1站）")
    p("─" * 70)
    p()

    rb = calc_version_b(213, 1)

    p(f"  {'年份':>4} | {'EBITDA':>8} | {'折旧':>6} | {'置换支出':>8} | {'残值回收':>8} | {'净现金流':>8} | {'累计CF':>10}")
    p("  " + "-" * 75)

    rev_opex = calc_revenue_opex(213, 1)
    user_bat = 213
    spare_bat = 20
    total_bat = user_bat + spare_bat
    bat_capex_y0 = total_bat * bat_unit_cost_y0
    sta_capex = station_equipment
    total_capex = sta_capex + bat_capex_y0

    dep1 = bat_capex_y0 * (1 - get_residual_rate(8)) / 8
    power_y8 = get_power_cell_price(8)
    new_bat_y8 = bat_capacity_wh * power_y8
    replace_cost = total_bat * new_bat_y8
    res_rate_8 = get_residual_rate(8)
    storage_y8 = get_storage_cell_price(8)
    max_res_8 = bat_capacity_wh * storage_y8
    actual_res_8 = min(bat_unit_cost_y0 * res_rate_8, max_res_8)
    res_income = total_bat * actual_res_8
    net_replace = replace_cost - res_income

    res_rate_15 = get_residual_rate(7)
    storage_y15 = get_storage_cell_price(15)
    max_res_15 = bat_capacity_wh * storage_y15
    actual_res_15 = min(new_bat_y8 * res_rate_15, max_res_15)
    terminal_res = total_bat * actual_res_15

    dep2 = replace_cost * (1 - res_rate_15) / 7

    cum_cf = -total_capex
    p(f"  {'Y0':>4} | {'':>8} | {'':>6} | {'':>8} | {'':>8} | {-total_capex/10000:>+7.0f}万 | {cum_cf/10000:>+9.0f}万")

    for t in range(1, 16):
        dep = dep1 if t <= 8 else dep2
        cf = rev_opex['ebitda'] - dep

        replace_out = 0
        res_in = 0
        if t == 8:
            cf -= net_replace
            replace_out = -replace_cost
            res_in = res_income
        if t == 15:
            cf += terminal_res
            res_in += terminal_res

        cum_cf += cf
        p(f"  Y{t:>2} | {rev_opex['ebitda']/10000:>7.1f}万 | {dep/10000:>5.1f}万 | {replace_out/10000:>+7.0f}万 | {res_in/10000:>+7.0f}万 | {cf/10000:>+7.1f}万 | {cum_cf/10000:>+9.0f}万")

    # ========================================
    # 七、A版现金流明细（单站213用户）
    # ========================================
    p()
    p("─" * 70)
    p("七、A版逐年现金流明细（单站213用户，1站）")
    p("─" * 70)
    p()

    ra = calc_version_a(213, 1)
    dep_a = ra['bat_depreciation_annual']
    terminal_a = ra['terminal_residual']

    cum_cf = -ra['total_capex']
    p(f"  {'年份':>4} | {'EBITDA':>8} | {'折旧':>6} | {'期末残值':>8} | {'净现金流':>8} | {'累计CF':>10}")
    p("  " + "-" * 65)
    p(f"  {'Y0':>4} | {'':>8} | {'':>6} | {'':>8} | {-ra['total_capex']/10000:>+7.0f}万 | {cum_cf/10000:>+9.0f}万")

    for t in range(1, 16):
        cf = rev_opex['ebitda'] - dep_a
        term = 0
        if t == 15:
            cf += terminal_a
            term = terminal_a
        cum_cf += cf
        p(f"  Y{t:>2} | {rev_opex['ebitda']/10000:>7.1f}万 | {dep_a/10000:>5.1f}万 | {term/10000:>+7.0f}万 | {cf/10000:>+7.1f}万 | {cum_cf/10000:>+9.0f}万")

    # ========================================
    # 八、IRR > 7.5%临界条件
    # ========================================
    p()
    p("=" * 95)
    p("【IRR > 7.5%的临界条件（双版本对比）】")
    p("=" * 95)
    p()

    for sf in [0.3, 0.4, 0.5]:
        for ver in ['A', 'B']:
            found = False
            for u in range(10, 50000, 1):
                stations = max(1, int(np.ceil(u / users_per_station_115)))

                comm_u = int(u * 0.8)
                priv_u = u - comm_u
                daily_swaps_u = comm_u * comm_swap_freq + priv_u * priv_swap_freq

                bat_rent_u = (private_avg_rent * priv_u + commercial_avg_rent * comm_u) * 12
                swap_svc_u = sf * 50 * (priv_u * priv_swap_freq + comm_u * comm_swap_freq) * 365
                sc_rev_u = 40 * 25 * 0.3 * 365 * stations
                total_kwh_u = daily_swaps_u * 50 + 40 * 25 * stations
                ccer_u = max(0, total_kwh_u * 365 * 0.31 / 1000 * 100)
                vpp_u = 30000 * total_kwh_u / 6000
                revenue_u = bat_rent_u + swap_svc_u + sc_rev_u + ccer_u + vpp_u

                swap_loss_u = daily_swaps_u * 50 / (1 - 0.09) * 0.09 * 0.61 * 365
                sc_loss_u = 40 * 25 / (1 - 0.09) * 0.09 * 0.61 * 365 * stations
                opex_u = swap_loss_u + sc_loss_u + 144000 * stations + 120000 * stations + 60000 * stations

                ebitda_u = revenue_u - opex_u

                total_bat_u = u + 20 * stations
                bat_capex_u = total_bat_u * bat_unit_cost_y0
                sta_capex_u = station_equipment * stations
                total_capex_u = sta_capex_u + bat_capex_u

                if ver == 'A':
                    dep_u = bat_capex_u * (1 - get_residual_rate(15)) / 8
                    cfs_u = [-total_capex_u]
                    for t in range(1, 16):
                        cf = ebitda_u - dep_u
                        if t == 15:
                            cf += bat_capex_u * get_residual_rate(15)
                        cfs_u.append(cf)
                else:
                    dep1_u = bat_capex_u * (1 - get_residual_rate(8)) / 8
                    power_y8_u = get_power_cell_price(8)
                    new_bat_y8_u = bat_capacity_wh * power_y8_u
                    replace_u = total_bat_u * new_bat_y8_u
                    res_8_u = min(bat_unit_cost_y0 * get_residual_rate(8), bat_capacity_wh * get_storage_cell_price(8))
                    net_replace_u = replace_u - total_bat_u * res_8_u
                    dep2_u = replace_u * (1 - get_residual_rate(7)) / 7
                    res_15_u = min(new_bat_y8_u * get_residual_rate(7), bat_capacity_wh * get_storage_cell_price(15))

                    cfs_u = [-total_capex_u]
                    for t in range(1, 16):
                        if t <= 8:
                            dep_t = dep1_u
                        else:
                            dep_t = dep2_u
                        cf = ebitda_u - dep_t
                        if t == 8:
                            cf -= net_replace_u
                        if t == 15:
                            cf += total_bat_u * res_15_u
                        cfs_u.append(cf)

                irr_u = calc_irr(cfs_u)
                irr_pct_u = irr_u * 100 if irr_u is not None and irr_u > -1 else -999

                if irr_pct_u >= 7.5:
                    p(f"  服务费{sf}元/度 + {ver}版 → IRR≥7.5%需要: {u}用户, {stations}站, 总投入{total_capex_u/10000:.0f}万")
                    found = True
                    break
            if not found:
                p(f"  服务费{sf}元/度 + {ver}版 → IRR≥7.5%: 5万用户内不可达")

    # ========================================
    # 九、最终结论
    # ========================================
    p()
    p("=" * 95)
    p("【双版本模型最终结论】")
    p("=" * 95)

    ra_213 = calc_version_a(213, 1)
    rb_213 = calc_version_b(213, 1)
    ra_cq = calc_version_a(5500, 62, subsidy_per_kwh=0.2)
    rb_cq = calc_version_b(5500, 62, subsidy_per_kwh=0.2)
    ra_t1 = calc_version_a(75000, 308)
    rb_t1 = calc_version_b(75000, 308)

    p(f"""
  1. A版 vs B版的核心差异：
     A版（蔚能模式）：电池8年折旧完，但实际持有到15年，期末残值40%
     B版（8年置换）：第8年实际置换，旧电池残值回收，新电池按届时价格

  2. 单站213用户对比：
     A版：IRR {ra_213['irr']:.1f}%，NPV {ra_213['npv']/10000:+.0f}万
     B版：IRR {rb_213['irr']:.1f}%，NPV {rb_213['npv']/10000:+.0f}万
     → B版IRR{'高' if rb_213['irr'] > ra_213['irr'] else '低'}于A版{abs(rb_213['irr'] - ra_213['irr']):.1f}个百分点

  3. 重庆62站（5500用户+0.2元/度补贴）：
     A版：IRR {ra_cq['irr']:.1f}%，NPV {ra_cq['npv']/10000:+.0f}万
     B版：IRR {rb_cq['irr']:.1f}%，NPV {rb_cq['npv']/10000:+.0f}万

  4. 一线城市（7.5万用户，308站）：
     A版：IRR {ra_t1['irr']:.1f}%
     B版：IRR {rb_t1['irr']:.1f}%

  5. B版的优势：
     - 第8年新电池价格已降至{get_power_cell_price(8):.3f}元/Wh（vs 初始0.53）
     - 旧电池残值回收{rb_213['residual_income']/10000:.1f}万（残值率{rb_213['residual_rate_y8']*100:.0f}%）
     - 净置换支出{rb_213['net_replacement_cost']/10000:.1f}万 < 初始电池投入{rb_213['battery_capex_y0']/10000:.1f}万
     - 电池降价红利被B版捕获

  6. A版的优势：
     - 无需中途大额资本支出
     - 现金流更平稳，适合REITs/ABS发行
     - 仿蔚能模式，资本市场更易理解

  7. 两个版本的适用场景：
     A版 → 适合REITs发行（现金流稳定，无中途大额支出）
     B版 → 适合自营持有（捕获电池降价红利，IRR更高）
    """)

    return "\n".join(out)


if __name__ == '__main__':
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'analysis_dual_version.txt')
    result = dual_version_model()
    with io.open(out_path, 'w', encoding='utf-8') as f:
        f.write(result)

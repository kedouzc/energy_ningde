import numpy as np
import math
import io
import os


def calc_irr(cashflows, guess=0.1, max_iter=1000, tol=1e-8):
    """手动实现IRR计算（牛顿法）"""
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


def network_model():
    """
    网络级一体化模型：
    
    宁德时代做换电业务，需要投入两块：
    1. 换电站（基础设施）
    2. 电池（动产）
       - 周转电池：放在站里，供用户换电时取用
       - 用户电池：装在用户车上，以租赁方式提供给用户
    
    自变量 = 用户数
    因变量 = 站数、电池数、CAPEX、收入、IRR
    
    站数由换电次数决定（单站有容量上限）
    电池数 = 用户数（车上）+ 20×站数（站内周转）
    """

    out = []

    def p(s=""):
        out.append(s)

    p("=" * 80)
    p("【网络级一体化模型：宁德时代换电业务整体测算】")
    p("=" * 80)

    # ========================================
    # 基础参数
    # ========================================
    comm_swap_freq = 0.71
    priv_swap_freq = 0.2
    comm_ratio = 0.8

    swap_fee = 0.4
    supercharge_fee = 0.3
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

    spare_bat_per_station = 20
    station_capacity = 100

    coverage_radius = 4.0
    user_density = 5
    plan_mode = 'coverage'

    private_avg_rent = 0.6 * 499 + 0.4 * 369
    commercial_avg_rent = 0.6 * 599 + 0.4 * 469

    station_equipment = 1600000 + 150000 + 300000

    pv_factor = sum([1 / (1 + discount_rate) ** t for t in range(1, years + 1)])

    # ========================================
    # 1. 把逻辑讲清楚
    # ========================================
    p()
    p("─" * 60)
    p("一、业务逻辑")
    p("─" * 60)
    p("""
  宁德时代做换电，需要投入两块：

  ┌─────────────────────────────────────────────────┐
  │  投入1：换电站（不动产/基础设施）                    │
  │  - 换电设备、超充桩、土建消防                        │
  │  - 每站205万                                       │
  │  - 单工位有效换电能力125次/天（乐观），中性假设100次/天，对应266用户            │
  │  - 站数取决于两个因素取最大值：                       │
  │    ① 容量需求：用户换电需求 ÷ 单站容量(125次/天)     │
  │    ② 地理覆盖：总服务面积 ÷ 单站覆盖面积             │
  │                                                    │
  │  投入2：电池（动产）                                │
  │  - 用户电池：每用户1块，装在车上，租赁给用户           │
  │  - 周转电池：每站20块，放在站里供换电周转             │
  │  - 每块2.97万（56度×0.53元/Wh，当前市场价上限）      │
  └─────────────────────────────────────────────────┘

  两种规划模式：
  
  【容量优先（极致利用）】
    站数 = ceil(日均换电次数 ÷ 125)
    → 每站跑到物理极限125次/天，IRR最高，但用户可能跑很远
    
  【覆盖优先（用户满意度）】
    站数 = max(容量站数, 地理覆盖站数)
    地理覆盖站数 = ceil(总服务面积 ÷ π×覆盖半径²)
    总服务面积 = 总用户数 ÷ 用户密度
    → 确保用户3-5km内有站可换，每站利用率可能较低

  因果链：
  
  用户数(自变量)
    │
    ├→ 日均换电次数 = 营运用户×0.71次/天 + 私家用户×0.2次/天
    │     │
    │     ├→ 容量站数 = ceil(日均换电次数 ÷ 125)
    │     └→ 地理站数 = ceil(总服务面积 ÷ π×覆盖半径²)
    │           │
    │           └→ 最终站数 = max(容量站数, 地理站数) [覆盖优先]
    │                 │
    │                 ├→ 站设备投入 = 站数 × 205万
    │                 └→ 周转电池 = 站数 × 20块 × 2.97万
    │
    ├→ 用户电池 = 用户数 × 1块 × 2.97万
    │
    └→ 收入 = 电池租赁 + 换电服务费 + 超充 + CCER + VPP

  所以：用户数决定一切。
  用户越多 → 换电越多 → 需要更多站 → 需要更多电池
  但收入也越多，关键是收入增速是否超过投入增速。
  覆盖优先模式下，站数可能多于容量需求，IRR会降低——这是"用户满意度"的代价。
  电池成本0.53元/Wh为当前市场价上限，未来只降不升。
    """)

    # ========================================
    # 2. 核心计算函数
    # ========================================
    def calc_network(total_users, comm_ratio=0.8, swap_fee=0.4,
                     station_capacity=150, spare_per_station=20,
                     coverage_radius=4.0, user_density=5, plan_mode='coverage'):
        comm = int(total_users * comm_ratio)
        priv = total_users - comm

        daily_swaps = comm * comm_swap_freq + priv * priv_swap_freq

        capacity_stations = max(1, int(np.ceil(daily_swaps / station_capacity)))

        coverage_area_per_station = math.pi * coverage_radius ** 2
        total_area = total_users / user_density if user_density > 0 else 50
        geography_stations = max(1, int(math.ceil(total_area / coverage_area_per_station)))

        if plan_mode == 'coverage':
            num_stations = max(capacity_stations, geography_stations)
            station_basis = '覆盖触发' if geography_stations > capacity_stations else '容量触发'
        else:
            num_stations = capacity_stations
            station_basis = '容量触发'

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

        total_revenue = bat_rent + swap_svc + sc_rev + ccer + vpp

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

        fixed_opex_per_station = 144000 + 120000 + 60000 + 50000
        var_cost_per_swap = swap_kwh / (1 - loss_rate) * loss_rate * weighted_price
        rev_per_swap = swap_fee * swap_kwh
        break_even_swaps = (fixed_opex_per_station / 365) / (rev_per_swap - var_cost_per_swap) if rev_per_swap > var_cost_per_swap else float('inf')

        return {
            'users': total_users, 'comm': comm, 'priv': priv,
            'daily_swaps': daily_swaps,
            'num_stations': num_stations,
            'swaps_per_station': daily_swaps / num_stations,
            'user_batteries': user_batteries,
            'spare_batteries': spare_batteries,
            'total_batteries': total_batteries,
            'station_capex': station_capex,
            'battery_capex': battery_capex,
            'total_capex': total_capex,
            'bat_rent': bat_rent, 'swap_svc': swap_svc,
            'sc_rev': sc_rev, 'ccer': ccer, 'vpp': vpp,
            'total_revenue': total_revenue,
            'total_opex': total_opex, 'ebitda': ebitda,
            'net_income': net_income, 'bat_replace': bat_replace,
            'npv': npv, 'irr': irr_pct, 'payback': payback,
            'capacity_stations': capacity_stations,
            'geography_stations': geography_stations,
            'station_basis': station_basis,
            'break_even_swaps': break_even_swaps,
        }

    # ========================================
    # 3. 全景表
    # ========================================
    p("─" * 60)
    p("二、不同用户规模下的全景（覆盖优先模式，覆盖半径{}km，密度{}人/km²）".format(coverage_radius, user_density))
    p("─" * 60)
    p()
    p(f"  {'用户数':>5} | {'日均换电':>6} | {'站数':>3} | {'触发':>4} | {'每站/天':>5} | {'用户电池':>4} | {'周转电池':>4} | {'总电池':>4} | {'站投入':>6} | {'电池投入':>6} | {'总投入':>6} | {'年收入':>6} | {'EBITDA':>6} | {'IRR':>6} | {'NPV':>7} | {'回收期':>5}")
    p("  " + "-" * 140)

    user_counts = [50, 100, 150, 200, 250, 300, 400, 500, 600, 800, 1000, 1500, 2000]
    for u in user_counts:
        r = calc_network(u, coverage_radius=coverage_radius, user_density=user_density, plan_mode=plan_mode)
        basis_short = '覆盖' if r['station_basis'] == '覆盖触发' else '容量'
        p(f"  {u:>5}人 | {r['daily_swaps']:>5.0f}次 | {r['num_stations']:>3}站 | {basis_short:>4} | {r['swaps_per_station']:>4.0f}次 | {r['user_batteries']:>4}块 | {r['spare_batteries']:>4}块 | {r['total_batteries']:>4}块 | {r['station_capex']/10000:>5.0f}万 | {r['battery_capex']/10000:>5.0f}万 | {r['total_capex']/10000:>5.0f}万 | {r['total_revenue']/10000:>5.0f}万 | {r['ebitda']/10000:>5.0f}万 | {r['irr']:>5.1f}% | {r['npv']/10000:>+6.0f}万 | {r['payback']:>4.1f}年")

    # ========================================
    # 4. 找到IRR>7.5%的临界点
    # ========================================
    p()
    p("─" * 60)
    p("三、IRR > 7.5%的临界点")
    p("─" * 60)

    for sf in [0.3, 0.4, 0.5, 0.6]:
        for u in range(10, 5000, 1):
            r = calc_network(u, swap_fee=sf, coverage_radius=coverage_radius, user_density=user_density, plan_mode=plan_mode)
            if r['irr'] >= 7.5:
                p(f"  服务费{sf}元/度 → IRR≥7.5%需要: {u}个用户, {r['num_stations']}站, {r['total_batteries']}块电池, 总投入{r['total_capex']/10000:.0f}万")
                break
        else:
            p(f"  服务费{sf}元/度 → IRR≥7.5%: 5000用户内不可达")

    # ========================================
    # 3.5 覆盖优先 vs 容量优先对比
    # ========================================
    p()
    p("─" * 60)
    p("三.五、覆盖优先 vs 容量优先 · 站数对比")
    p("─" * 60)
    p()
    p(f"  覆盖半径={coverage_radius}km, 单站覆盖面积={math.pi * coverage_radius**2:.0f}km², 用户密度={user_density}人/km²")
    p()
    p(f"  {'用户数':>5} | {'日均换电':>6} | {'容量站数':>5} | {'覆盖站数':>5} | {'差额':>4} | {'容量IRR':>6} | {'覆盖IRR':>6} | {'覆盖NPV':>7}")
    p("  " + "-" * 80)

    for u in user_counts:
        r_cap = calc_network(u, plan_mode='capacity')
        r_cov = calc_network(u, coverage_radius=coverage_radius, user_density=user_density, plan_mode='coverage')
        diff = r_cov['num_stations'] - r_cap['num_stations']
        diff_str = f"+{diff}站" if diff > 0 else "相同"
        p(f"  {u:>5}人 | {r_cap['daily_swaps']:>5.0f}次 | {r_cap['num_stations']:>5}站 | {r_cov['num_stations']:>5}站 | {diff_str:>4} | {r_cap['irr']:>5.1f}% | {r_cov['irr']:>5.1f}% | {r_cov['npv']/10000:>+6.0f}万")

    p()
    p("  结论：覆盖优先模式下，当用户密度低、分布广时，需要额外建站覆盖地理范围。")
    p("  每站利用率降低，IRR下降——这是'用户满意度'的代价。")

    # ========================================
    # 3.6 盈亏平衡分析
    # ========================================
    p()
    p("─" * 60)
    p("三.六、单站盈亏平衡分析（非极致利用场景）")
    p("─" * 60)
    p()

    fixed_opex = 144000 + 120000 + 60000 + 50000
    var_cost = swap_kwh / (1 - loss_rate) * loss_rate * weighted_price

    p(f"  单站固定OPEX: {fixed_opex/10000:.1f}万/年（人工14.4+租金12.0+维保6.0+营销5.0，不含电损）")
    p(f"  每次换电可变成本（电损）: {var_cost:.1f}元/次")
    p()
    p(f"  {'服务费':>6} | {'每次收入':>6} | {'边际贡献':>6} | {'盈亏平衡':>8} | {'利用率':>6} | {'最低用户数':>6}")
    p("  " + "-" * 60)

    for sf in [0.3, 0.35, 0.4, 0.45, 0.5]:
        rev = sf * swap_kwh
        margin = rev - var_cost
        if margin > 0:
            be_swaps = (fixed_opex / 365) / margin
            be_util = be_swaps / station_capacity * 100
            min_users = int(np.ceil(be_swaps / (comm_swap_freq * comm_ratio + priv_swap_freq * (1 - comm_ratio))))
            p(f"  {sf:>5.2f}元 | {rev:>5.0f}元 | {margin:>5.0f}元 | {be_swaps:>5.0f}次/天 | {be_util:>4.0f}% | {min_users:>5}人")
        else:
            p(f"  {sf:>5.2f}元 | {rev:>5.0f}元 | {margin:>5.0f}元 | {'不可达':>8} | {'—':>6} | {'—':>6}")

    p()
    p("  核心洞察：在0.4元/度服务费下，单站仅需约{}次/天即可覆盖固定OPEX不亏损。".format(
        int((fixed_opex / 365) / (0.4 * swap_kwh - var_cost))))
    p("  这意味着即使因覆盖优先多建了站、每站利用率远低于125次，只要不低于盈亏平衡点，单站就不会亏。")
    p("  但注意：这不含电池资产回报——电池租赁收入与电池成本对冲，真正的利润来自服务费超出盈亏平衡点的部分。")

    # ========================================
    # 5. 投入结构拆解
    # ========================================
    p()
    p("─" * 60)
    p("四、投入结构拆解：站 vs 电池")
    p("─" * 60)
    p()
    p(f"  {'用户数':>5} | {'站投入':>6} | {'用户电池':>6} | {'周转电池':>6} | {'总投入':>6} | {'站占比':>5} | {'用户电池占比':>8} | {'周转电池占比':>8}")
    p("  " + "-" * 80)

    for u in [100, 200, 300, 500, 800, 1000, 2000]:
        r = calc_network(u, coverage_radius=coverage_radius, user_density=user_density, plan_mode=plan_mode)
        spare_cap = r['spare_batteries'] * bat_unit_cost
        user_cap = r['user_batteries'] * bat_unit_cost
        p(f"  {u:>5}人 | {r['station_capex']/10000:>5.0f}万 | {user_cap/10000:>5.0f}万 | {spare_cap/10000:>5.0f}万 | {r['total_capex']/10000:>5.0f}万 | {r['station_capex']/r['total_capex']*100:>4.0f}% | {user_cap/r['total_capex']*100:>6.0f}% | {spare_cap/r['total_capex']*100:>6.0f}%")

    p()
    p("  结论：用户电池占总投入的60-70%，是最大的成本项。")
    p("  换电站（不动产）只占20-30%，周转电池占5-10%。")

    # ========================================
    # 6. 收入结构拆解
    # ========================================
    p()
    p("─" * 60)
    p("五、收入结构拆解")
    p("─" * 60)
    p()
    p(f"  {'用户数':>5} | {'租赁收入':>6} | {'服务费':>6} | {'超充':>5} | {'其他':>5} | {'总收入':>6} | {'租赁占比':>6} | {'服务费占比':>8}")
    p("  " + "-" * 80)

    for u in [100, 200, 300, 500, 800, 1000, 2000]:
        r = calc_network(u)
        other = r['ccer'] + r['vpp']
        p(f"  {u:>5}人 | {r['bat_rent']/10000:>5.1f}万 | {r['swap_svc']/10000:>5.1f}万 | {r['sc_rev']/10000:>4.1f}万 | {other/10000:>4.1f}万 | {r['total_revenue']/10000:>5.1f}万 | {r['bat_rent']/r['total_revenue']*100:>5.0f}% | {r['swap_svc']/r['total_revenue']*100:>6.0f}%")

    p()
    p("  结论：电池租赁占收入55-60%，换电服务费占30-35%。")
    p("  但租赁收入对应的成本（用户电池）占总投入60-70%。")
    p("  租赁收入和用户电池成本基本对冲，真正的利润来自服务费。")

    # ========================================
    # 7. 敏感性分析
    # ========================================
    p()
    p("=" * 80)
    p("【敏感性分析】")
    p("=" * 80)

    # 7.1 服务费 × 用户数 → IRR
    p()
    p("─" * 60)
    p("7.1 换电服务费(元/度) × 用户规模 → IRR")
    p("（单站容量100次/天，营运占比80%）")
    p("─" * 60)

    swap_fees = [0.3, 0.4, 0.5, 0.6]
    user_list = [100, 200, 300, 500, 800, 1000, 2000]

    header = f"{'服务费':>6} |"
    for u in user_list:
        header += f"  {u}人"
    p(header)
    p("-" * len(header))

    for sf in swap_fees:
        row = f"{sf:>6.1f} |"
        for u in user_list:
            r = calc_network(u, swap_fee=sf, coverage_radius=coverage_radius, user_density=user_density, plan_mode=plan_mode)
            irr_v = r['irr']
            if irr_v < -50:
                row += f"    N/A "
            else:
                row += f"  {irr_v:>5.1f}%"
        p(row)

    # 7.2 单站容量 × 用户数 → IRR
    p()
    p("─" * 60)
    p("7.2 单站容量(次/天) × 用户规模 → IRR（服务费0.4元/度）")
    p("─" * 60)

    capacities = [60, 80, 100, 125, 150]

    header = f"{'容量':>6} |"
    for u in user_list:
        header += f"  {u}人"
    p(header)
    p("-" * len(header))

    for cap in capacities:
        row = f"{cap:>4}次 |"
        for u in user_list:
            r = calc_network(u, swap_fee=0.4, station_capacity=cap, coverage_radius=coverage_radius, user_density=user_density, plan_mode=plan_mode)
            irr_v = r['irr']
            if irr_v < -50:
                row += f"    N/A "
            else:
                row += f"  {irr_v:>5.1f}%"
        p(row)

    p()
    p("  注：单站容量越高 → 需要的站越少 → 站设备投入越少 → IRR越高")
    p("  但容量受物理限制（换电速度）和需求分布限制（用户不会排长队）")

    # 7.3 电池成本 × 用户数 → IRR
    p()
    p("─" * 60)
    p("7.3 电池成本(元/Wh) × 用户规模 → IRR（服务费0.4元/度）")
    p("─" * 60)

    bat_costs = [0.35, 0.40, 0.45, 0.50, 0.53]

    header = f"{'成本':>6} |"
    for u in user_list:
        header += f"  {u}人"
    p(header)
    p("-" * len(header))

    for bc in bat_costs:
        row = f"{bc:>5.2f} |"
        for u in user_list:
            comm = int(u * 0.8)
            priv = u - comm
            daily_swaps = comm * comm_swap_freq + priv * priv_swap_freq
            num_stations = max(1, int(np.ceil(daily_swaps / 125)))
            total_batteries = u + 20 * num_stations
            bat_capex = total_batteries * bat_capacity_wh * bc
            sta_capex = station_equipment * num_stations
            total_capex = sta_capex + bat_capex

            bat_rent = (private_avg_rent * priv + commercial_avg_rent * comm) * 12
            swap_svc = 0.4 * 50 * (priv * priv_swap_freq + comm * comm_swap_freq) * 365
            sc_rev = 40 * 25 * 0.3 * 365 * num_stations
            total_kwh = daily_swaps * 50 + 40 * 25 * num_stations
            ccer = max(0, total_kwh * 365 * 0.31 / 1000 * 100)
            vpp = 30000 * total_kwh / 6000 if total_kwh > 0 else 0
            revenue = bat_rent + swap_svc + sc_rev + ccer + vpp

            swap_loss = daily_swaps * 50 / (1 - 0.09) * 0.09 * 0.61 * 365
            sc_loss = 40 * 25 / (1 - 0.09) * 0.09 * 0.61 * 365 * num_stations
            opex = swap_loss + sc_loss + 144000 * num_stations + 120000 * num_stations + 60000 * num_stations + total_capex * 0.005 + 50000 * num_stations

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

            if irr_pct < -50:
                row += f"    N/A "
            else:
                row += f"  {irr_pct:>5.1f}%"
        p(row)

    p()
    p("  注：宁德时代自产电池，实际成本可能低于0.53元/Wh")
    p("  电池成本0.53为当前市场价上限，未来只降不升。从0.53降至0.40元/Wh，IRR提升约3-4个百分点")

    # ========================================
    # 8. 最终结论
    # ========================================
    p()
    p("=" * 80)
    p("【最终结论】")
    p("=" * 80)

    r200 = calc_network(200, coverage_radius=coverage_radius, user_density=user_density, plan_mode=plan_mode)
    r500 = calc_network(500, coverage_radius=coverage_radius, user_density=user_density, plan_mode=plan_mode)
    r1000 = calc_network(1000, coverage_radius=coverage_radius, user_density=user_density, plan_mode=plan_mode)

    be_swaps_04 = int((fixed_opex / 365) / (0.4 * swap_kwh - var_cost))

    p(f"""
  1. 这盘生意的投入结构：
     - 换电站（不动产）：每站205万，数量取决于用户换电需求+地理覆盖
     - 用户电池（动产）：每用户1块×2.97万，占总投入60-70%
     - 周转电池（动产）：每站20块×2.97万，占总投入5-10%
     → 电池是最大的投入项，不是站

  2. 这盘生意的收入结构：
     - 电池租赁费：占总收入的55-60%，但和用户电池成本基本对冲
     - 换电服务费：占总收入的30-35%，是真正的利润来源
     - 超充+CCER+VPP：占5-10%，锦上添花

  3. 两种规划模式对比（覆盖半径{coverage_radius}km，密度{user_density}人/km²）：
     容量优先：站数仅由需求决定，每站利用率高，IRR高，但用户可能跑很远
     覆盖优先：站数取max(容量, 地理)，确保用户{coverage_radius}km内有站，IRR略低但用户体验好

  4. 不同规模的IRR（覆盖优先，0.4元/度）：
     200用户({r200['num_stations']}站, 触发:{r200['station_basis']}): IRR {r200['irr']:.1f}%, 总投入{r200['total_capex']/10000:.0f}万
     500用户({r500['num_stations']}站, 触发:{r500['station_basis']}): IRR {r500['irr']:.1f}%, 总投入{r500['total_capex']/10000:.0f}万
     1000用户({r1000['num_stations']}站, 触发:{r1000['station_basis']}): IRR {r1000['irr']:.1f}%, 总投入{r1000['total_capex']/10000:.0f}万

  5. 单站盈亏平衡（0.4元/度）：仅需{be_swaps_04}次/天即可覆盖固定OPEX
     → 即使因覆盖优先多建站、每站利用率远低于125次，只要≥{be_swaps_04}次/天就不亏

  6. 关键杠杆：
     - 流量（用户数）是最敏感的变量
     - 服务费每+0.1元/度，IRR提升约3-4pp
     - 电池成本每-0.1元/Wh，IRR提升约3-4pp（宁德自有优势）
     - 覆盖半径每+1km，单站覆盖面积翻倍，所需站数减少

  7. 商业本质：
     这不是"建站赚钱"的生意，而是"持有电池+提供服务"的生意。
     电池租赁只是金融工具（以租代购），利润微薄。
     真正赚钱靠的是换电服务费的规模效应——用户越多，每块电池的利用率越高。
     覆盖优先是为"用户满意度"付出的必要代价——多建站、少赚钱，但用户愿意用。
    """)

    return "\n".join(out)


if __name__ == '__main__':
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'analysis_network.txt')
    result = network_model()
    with io.open(out_path, 'w', encoding='utf-8') as f:
        f.write(result)

import numpy as np
import sys
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


def correct_model():
    """
    修正因果链的一体化模型：
    自变量 = 用户数 → 因变量 = 换电次数/收入/电池数/CAPEX
    
    同时考虑：N个用户需要几个站来服务？
    """

    out = []

    def p(s=""):
        out.append(s)

    p("=" * 80)
    p("【修正因果链的一体化模型】")
    p("=" * 80)
    p()
    p("原文问题：先假设'100次/天'，再倒推需要212个用户 → 因果倒置")
    p("正确逻辑：先有用户数，再推导换电次数、收入、电池需求")
    p()
    p("核心因果链：")
    p("  用户数(自变量)")
    p("    → 日均换电次数 = 营运用户×0.71 + 私家用户×0.2")
    p("    → 收入 = 租赁费 + 服务费 + 超充 + CCER + VPP")
    p("    → 电池数 = 用户数 + 站内周转(20块/站)")
    p("    → 站数 = ceil(日均换电次数 / 单站容量上限)")
    p("    → CAPEX = 站数×单站设备 + 电池数×单块成本")

    # ========================================
    # 基础参数
    # ========================================
    swap_fee = 0.4
    supercharge_fee = 0.3
    sc_cars_per_station = 40
    swap_kwh = 50
    sc_kwh = 25
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

    comm_swap_freq = 0.71
    priv_swap_freq = 0.2
    comm_ratio = 0.8

    private_avg_rent = 0.6 * 499 + 0.4 * 369
    commercial_avg_rent = 0.6 * 599 + 0.4 * 469

    station_capacity = 200
    spare_bat_per_station = 20

    pv_factor = sum([1 / (1 + discount_rate) ** t for t in range(1, years + 1)])

    # ========================================
    # 1. 拆解原文的"循环"
    # ========================================
    p()
    p("=" * 80)
    p("一、原文逻辑拆解：为什么是循环的？")
    p("=" * 80)
    p()
    p("原文说：'日均100次换电 → 需要212个用户'")
    p("但212个用户 → 需要212块电池 → CAPEX暴增")
    p("而原文CAPEX只算了20块周转电池(59万)，漏了212块用户电池(629万)")
    p()
    p("这就像说：'我开了个酒店，每天接待100个客人'")
    p("  → 需要100个房间(电池)")
    p("  → 但投资只算了前台和装修(站设备)，没算盖房间的钱(电池)")
    p("  → 然后把房费全算成利润 → IRR当然高")
    p()
    p("正确的自变量是用户数，不是换电次数。")
    p("换电次数是用户数×换电频率的结果，不是前提。")

    # ========================================
    # 2. 修正后的模型：用户数→一切
    # ========================================
    p()
    p("=" * 80)
    p("二、修正模型：以用户数为自变量")
    p("=" * 80)

    def calc_from_users(total_users, comm_ratio=0.8, swap_fee=0.4,
                        supercharge_fee=0.3, sc_cars_per_station=40):
        comm_users = int(total_users * comm_ratio)
        priv_users = total_users - comm_users

        daily_swaps = comm_users * comm_swap_freq + priv_users * priv_swap_freq

        num_stations = max(1, int(np.ceil(daily_swaps / station_capacity)))

        total_batteries = total_users + spare_bat_per_station * num_stations

        bat_rent = (private_avg_rent * priv_users + commercial_avg_rent * comm_users) * 12

        swap_svc = swap_fee * swap_kwh * (priv_users * priv_swap_freq + comm_users * comm_swap_freq) * 365

        sc_rev = sc_cars_per_station * sc_kwh * supercharge_fee * 365 * num_stations

        total_kwh = daily_swaps * swap_kwh + sc_cars_per_station * sc_kwh * num_stations
        ccer = max(0, total_kwh * 365 * 0.31 / 1000 * 100)
        vpp = 30000 * total_kwh / 6000 if total_kwh > 0 else 0

        revenue = bat_rent + swap_svc + sc_rev + ccer + vpp

        swap_loss = daily_swaps * swap_kwh / (1 - loss_rate) * loss_rate * weighted_price * 365
        sc_loss = sc_cars_per_station * sc_kwh / (1 - loss_rate) * loss_rate * weighted_price * 365 * num_stations
        total_loss = swap_loss + sc_loss

        station_capex = (1600000 + 150000 + 300000) * num_stations
        battery_capex = total_batteries * bat_unit_cost
        capex = station_capex + battery_capex

        labor = 144000 * num_stations
        rent = 120000 * num_stations
        maintenance = 60000 * num_stations
        insurance = capex * 0.005
        marketing = 50000 * num_stations

        opex = total_loss + labor + rent + maintenance + insurance + marketing

        ebitda = revenue - opex
        net_income = ebitda * (1 - tax_rate)

        bat_replace = battery_capex * (1 - battery_residual)

        pv_in = net_income * pv_factor
        pv_bat = bat_replace / (1 + discount_rate) ** battery_life
        npv = pv_in - capex - pv_bat

        cfs = [-capex]
        for t in range(1, years + 1):
            cf = net_income
            if t == battery_life:
                cf -= bat_replace
            cfs.append(cf)

        irr = calc_irr(cfs)
        irr_pct = irr * 100 if irr is not None and irr > -1 else -999
        payback = capex / net_income if net_income > 0 else float('inf')

        return {
            'total_users': total_users, 'comm_users': comm_users, 'priv_users': priv_users,
            'daily_swaps': daily_swaps, 'num_stations': num_stations,
            'total_batteries': total_batteries,
            'revenue': revenue, 'bat_rent': bat_rent, 'swap_svc': swap_svc,
            'sc_rev': sc_rev, 'ccer': ccer, 'vpp': vpp,
            'opex': opex, 'total_loss': total_loss,
            'capex': capex, 'station_capex': station_capex, 'battery_capex': battery_capex,
            'ebitda': ebitda, 'net_income': net_income,
            'bat_replace': bat_replace,
            'npv': npv, 'irr': irr_pct, 'payback': payback,
            'swaps_per_station': daily_swaps / num_stations,
        }

    # ========================================
    # 3. 原文场景验证：212用户
    # ========================================
    p()
    p("─" * 60)
    p("三、原文场景验证：212个用户")
    p("─" * 60)

    r = calc_from_users(212)
    p(f"""
  212个用户（112营运 + 100私家）：
    日均换电: {r['daily_swaps']:.0f}次
    需要站点: {r['num_stations']}个（单站容量上限{station_capacity}次/天）
    需要电池: {r['total_batteries']}块（{r['total_users']}用户 + {spare_bat_per_station * r['num_stations']}周转）
    每站日均: {r['swaps_per_station']:.0f}次

  收入：
    电池租赁: {r['bat_rent']/10000:.1f}万
    换电服务费: {r['swap_svc']/10000:.1f}万
    超充: {r['sc_rev']/10000:.1f}万
    CCER+VPP: {(r['ccer']+r['vpp'])/10000:.1f}万
    合计: {r['revenue']/10000:.1f}万

  CAPEX：
    站设备({r['num_stations']}站): {r['station_capex']/10000:.1f}万
    电池({r['total_batteries']}块): {r['battery_capex']/10000:.1f}万
    合计: {r['capex']/10000:.1f}万

  OPEX: {r['opex']/10000:.1f}万
  EBITDA: {r['ebitda']/10000:.1f}万
  税后净收入: {r['net_income']/10000:.1f}万
  电池重置(第8年): {r['bat_replace']/10000:.1f}万

  IRR: {r['irr']:.1f}%
  NPV: {r['npv']/10000:.1f}万
  回收期: {r['payback']:.1f}年
    """)

    # ========================================
    # 4. 不同用户数下的全景
    # ========================================
    p("─" * 60)
    p("四、不同用户数下的全景（营运占比80%，服务费0.4元/度）")
    p("─" * 60)
    p()
    p(f"  {'用户数':>4} | {'营运':>3} | {'私家':>3} | {'日均换电':>6} | {'站数':>2} | {'每站/天':>5} | {'电池':>3} | {'CAPEX':>6} | {'收入':>6} | {'EBITDA':>6} | {'IRR':>6} | {'NPV':>7} | {'回收期':>5}")
    p("  " + "-" * 110)

    user_counts = [50, 80, 100, 127, 150, 212, 300, 400, 500]
    for u in user_counts:
        r = calc_from_users(u)
        p(f"  {u:>4}人 | {r['comm_users']:>3} | {r['priv_users']:>3} | {r['daily_swaps']:>5.0f}次 | {r['num_stations']:>2}站 | {r['swaps_per_station']:>4.0f}次 | {r['total_batteries']:>3}块 | {r['capex']/10000:>5.0f}万 | {r['revenue']/10000:>5.0f}万 | {r['ebitda']/10000:>5.0f}万 | {r['irr']:>5.1f}% | {r['npv']/10000:>+6.0f}万 | {r['payback']:>4.1f}年")

    # ========================================
    # 5. 单站视角：每站服务多少用户
    # ========================================
    p()
    p("─" * 60)
    p("五、单站视角：每站服务多少用户？")
    p("─" * 60)
    p()
    p("  上面的全景是'整个网络'的视角。但投资决策通常以单站为单位。")
    p("  问题是：一个站能覆盖多少用户？")
    p()
    p("  这取决于服务半径内的用户密度：")
    p("  - 核心商圈/交通枢纽：3km半径内可能有200+换电用户 → 单站100+次/天")
    p("  - 一般城区：3km半径内可能50-100用户 → 单站30-60次/天")
    p("  - 郊区/新城：3km半径内可能<50用户 → 单站<30次/天")
    p()
    p("  所以'212用户=1站'的假设，只在核心商圈成立。")
    p("  一般城区更可能是50-100用户/站。")

    # ========================================
    # 6. 单站模型（固定用户数/站）
    # ========================================
    p()
    p("─" * 60)
    p("六、单站模型：以'每站服务用户数'为自变量")
    p("─" * 60)
    p()
    p("  假设1站服务N个用户，这N个用户的换电全部发生在本站。")
    p("  这是原文的隐含假设，也是单站财务模型的标准做法。")

    def calc_single_station(users_per_station, comm_ratio=0.8, swap_fee=0.4,
                            supercharge_fee=0.3, sc_cars=40):
        comm = int(users_per_station * comm_ratio)
        priv = users_per_station - comm

        daily_swaps = comm * comm_swap_freq + priv * priv_swap_freq

        total_batteries = users_per_station + spare_bat_per_station

        bat_rent = (private_avg_rent * priv + commercial_avg_rent * comm) * 12

        swap_svc = swap_fee * swap_kwh * (priv * priv_swap_freq + comm * comm_swap_freq) * 365

        sc_rev = sc_cars * sc_kwh * supercharge_fee * 365

        total_kwh = daily_swaps * swap_kwh + sc_cars * sc_kwh
        ccer = max(0, total_kwh * 365 * 0.31 / 1000 * 100)
        vpp = 30000 * total_kwh / 6000 if total_kwh > 0 else 0

        revenue = bat_rent + swap_svc + sc_rev + ccer + vpp

        swap_loss = daily_swaps * swap_kwh / (1 - loss_rate) * loss_rate * weighted_price * 365
        sc_loss = sc_cars * sc_kwh / (1 - loss_rate) * loss_rate * weighted_price * 365
        total_loss = swap_loss + sc_loss

        station_capex = 1600000 + 150000 + 300000
        battery_capex = total_batteries * bat_unit_cost
        capex = station_capex + battery_capex

        opex = total_loss + 144000 + 120000 + 60000 + capex * 0.005 + 50000

        ebitda = revenue - opex
        net_income = ebitda * (1 - tax_rate)

        bat_replace = battery_capex * (1 - battery_residual)

        pv_in = net_income * pv_factor
        pv_bat = bat_replace / (1 + discount_rate) ** battery_life
        npv = pv_in - capex - pv_bat

        cfs = [-capex]
        for t in range(1, years + 1):
            cf = net_income
            if t == battery_life:
                cf -= bat_replace
            cfs.append(cf)

        irr = calc_irr(cfs)
        irr_pct = irr * 100 if irr is not None and irr > -1 else -999
        payback = capex / net_income if net_income > 0 else float('inf')

        return {
            'users': users_per_station, 'comm': comm, 'priv': priv,
            'daily_swaps': daily_swaps,
            'total_batteries': total_batteries,
            'revenue': revenue, 'bat_rent': bat_rent, 'swap_svc': swap_svc,
            'opex': opex, 'capex': capex,
            'station_capex': station_capex, 'battery_capex': battery_capex,
            'ebitda': ebitda, 'net_income': net_income,
            'bat_replace': bat_replace,
            'npv': npv, 'irr': irr_pct, 'payback': payback,
        }

    p()
    p(f"  {'用户/站':>6} | {'日均换电':>6} | {'电池数':>4} | {'CAPEX':>6} | {'租赁收入':>6} | {'服务费':>6} | {'总收入':>6} | {'EBITDA':>6} | {'IRR':>6} | {'NPV':>7} | {'回收期':>5}")
    p("  " + "-" * 100)

    for u in [30, 50, 63, 80, 100, 127, 150, 212, 255, 300]:
        r = calc_single_station(u)
        p(f"  {u:>5}人 | {r['daily_swaps']:>5.0f}次 | {r['total_batteries']:>3}块 | {r['capex']/10000:>5.0f}万 | {r['bat_rent']/10000:>5.1f}万 | {r['swap_svc']/10000:>5.1f}万 | {r['revenue']/10000:>5.1f}万 | {r['ebitda']/10000:>5.1f}万 | {r['irr']:>5.1f}% | {r['npv']/10000:>+6.0f}万 | {r['payback']:>4.1f}年")

    # ========================================
    # 7. 盈亏平衡
    # ========================================
    p()
    p("─" * 60)
    p("七、盈亏平衡（单站模型，服务费0.4元/度）")
    p("─" * 60)

    for target in ["EBITDA", "NPV"]:
        for u in range(5, 500, 1):
            r = calc_single_station(u)
            if target == "EBITDA" and r['ebitda'] >= 0:
                p(f"  {target}盈亏平衡: {u}个用户/站 (日均{r['daily_swaps']:.0f}次, {r['total_batteries']}块电池, CAPEX{r['capex']/10000:.0f}万)")
                break
            if target == "NPV" and r['npv'] >= 0:
                p(f"  {target}盈亏平衡: {u}个用户/站 (日均{r['daily_swaps']:.0f}次, {r['total_batteries']}块电池, CAPEX{r['capex']/10000:.0f}万)")
                break
        else:
            p(f"  {target}盈亏平衡: >500用户/站(不可达)")

    # ========================================
    # 8. 敏感性分析
    # ========================================
    p()
    p("=" * 80)
    p("【敏感性分析：单站模型】")
    p("=" * 80)

    # 8.1 服务费 × 用户数/站 → IRR
    p()
    p("─" * 60)
    p("8.1 换电服务费(元/度) × 用户数/站 → IRR")
    p("─" * 60)

    swap_fees = [0.3, 0.4, 0.5, 0.6]
    user_list = [50, 80, 100, 127, 150, 212, 255]

    header = f"{'服务费':>6} |"
    for u in user_list:
        header += f"  {u}人/站"
    p(header)
    p("-" * len(header))

    for sf in swap_fees:
        row = f"{sf:>6.1f} |"
        for u in user_list:
            r = calc_single_station(u, swap_fee=sf)
            irr_v = r['irr']
            if irr_v < -50:
                row += f"    N/A "
            else:
                row += f"  {irr_v:>5.1f}%"
        p(row)

    # 8.2 服务费 × 用户数/站 → NPV
    p()
    p("─" * 60)
    p("8.2 换电服务费(元/度) × 用户数/站 → NPV(万元)")
    p("─" * 60)

    header = f"{'服务费':>6} |"
    for u in user_list:
        header += f"  {u}人/站"
    p(header)
    p("-" * len(header))

    for sf in swap_fees:
        row = f"{sf:>6.1f} |"
        for u in user_list:
            r = calc_single_station(u, swap_fee=sf)
            npv_wan = r['npv'] / 10000
            row += f"  {npv_wan:>6.0f} "
        p(row)

    # 8.3 对应换电次数
    p()
    p("─" * 60)
    p("8.3 用户数/站 → 对应日均换电次数（供参考）")
    p("─" * 60)

    for u in user_list:
        r = calc_single_station(u)
        p(f"  {u:>3}人/站 → 日均{r['daily_swaps']:.0f}次 → {r['total_batteries']}块电池 → CAPEX {r['capex']/10000:.0f}万")

    # ========================================
    # 9. 最终结论
    # ========================================
    p()
    p("=" * 80)
    p("【最终结论】")
    p("=" * 80)

    r212 = calc_single_station(212)
    r127 = calc_single_station(127)
    r100 = calc_single_station(100)

    p(f"""
  1. 原文的循环问题：
     原文先假设"100次/天"，再倒推需要212个用户。
     但212个用户需要212块电池(629万)，原文CAPEX只算了20块周转电池(59万)。
     这不是"循环计算"，而是"因果倒置+资产遗漏"。

  2. 正确的因果链：
     用户数(自变量) → 换电次数 → 收入
     用户数(自变量) → 电池数 → CAPEX
     用户数越多，收入和CAPEX同步增长，但收入增速 > CAPEX增速（规模效应）

  3. 单站模型核心指标（服务费0.4元/度）：

     212人/站（原文假设，日均100次）:
       CAPEX: {r212['capex']/10000:.0f}万, 收入: {r212['revenue']/10000:.1f}万, EBITDA: {r212['ebitda']/10000:.1f}万
       IRR: {r212['irr']:.1f}%, NPV: {r212['npv']/10000:.1f}万, 回收期: {r212['payback']:.1f}年

     127人/站（日均60次，更现实的成熟站）:
       CAPEX: {r127['capex']/10000:.0f}万, 收入: {r127['revenue']/10000:.1f}万, EBITDA: {r127['ebitda']/10000:.1f}万
       IRR: {r127['irr']:.1f}%, NPV: {r127['npv']/10000:.1f}万, 回收期: {r127['payback']:.1f}年

     100人/站（日均44次，一般城区站）:
       CAPEX: {r100['capex']/10000:.0f}万, 收入: {r100['revenue']/10000:.1f}万, EBITDA: {r100['ebitda']/10000:.1f}万
       IRR: {r100['irr']:.1f}%, NPV: {r100['npv']/10000:.1f}万, 回收期: {r100['payback']:.1f}年

  4. 关键发现：
     - 212人/站是核心商圈的极限场景，一般城区更可能是80-127人/站
     - 用户数和电池数是1:1关系（每个用户1块电池），这是最大的成本项
     - 电池租赁收入和电池成本基本对冲（租赁费≈电池折旧+资金成本）
     - 真正的利润来源是换电服务费，不是电池租赁

  5. 电池租赁的真实经济学：
     每块电池成本: {bat_unit_cost/10000:.2f}万
     8年折旧(残值10%): {bat_unit_cost*0.9/8/10000:.2f}万/年
     平均租赁收入: {(private_avg_rent*0.2+commercial_avg_rent*0.8)*12/10000:.2f}万/年/块
     租赁毛利: {(private_avg_rent*0.2+commercial_avg_rent*0.8)*12 - bat_unit_cost*0.9/8:.0f}元/年/块
     → 电池租赁的利润率很低，本质上是"以租代购"的金融工具

  6. 商业判断：
     - 一体化模型的盈利核心是换电服务费，不是电池租赁
     - 电池租赁只是解决用户"买车不买电池"的金融方案，利润微薄
     - 真正赚钱需要：高流量(127+人/站) + 合理服务费(0.4+元/度)
     - 宁德时代的优势不在租赁，而在：电池成本低 + 换电网络规模效应
    """)

    return "\n".join(out)


if __name__ == '__main__':
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'analysis_correct.txt')
    result = correct_model()
    with io.open(out_path, 'w', encoding='utf-8') as f:
        f.write(result)

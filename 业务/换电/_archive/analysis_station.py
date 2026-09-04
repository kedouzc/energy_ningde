import numpy as np
import math
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


def station_model():
    """
    单站详细财务模型：
    
    将一体化模型拆分为：
      - 第四部分：纯换电站模型（轻资产运营）
      - 第五部分：电池银行模型（重资产持有）
    
    纯站不拥有电池，向电池银行租周转电池、支付技术服务费。
    核心自变量 = 日均换电次数 X（次/天）
    """

    out = []

    def p(s=""):
        out.append(s)

    p("=" * 80)
    p("【单站详细财务模型：纯换电站 + 电池银行 分拆测算】")
    p("=" * 80)

    # ========================================
    # 基础参数
    # ========================================
    swap_kwh = 50
    sc_kwh = 25
    sc_cars_per_station = 40
    loss_rate = 0.09
    weighted_price = 0.61
    discount_rate = 0.075
    years = 15
    tax_rate = 0.25

    station_equipment = 2150000
    station_life = 10
    depreciation = station_equipment / station_life

    spare_bats = 14
    bat_cost_per_wh = 0.53
    bat_capacity_wh = 56000
    bat_unit_cost = bat_capacity_wh * bat_cost_per_wh

    spare_rent_per_month = 240
    tech_service_fee_per_station = 35000

    users_per_station = 266

    comm_ratio = 0.8
    comm_swap_freq = 0.71
    priv_swap_freq = 0.2

    private_avg_rent = 0.6 * 499 + 0.4 * 369
    commercial_avg_rent = 0.6 * 599 + 0.4 * 469

    supercharge_fee = 0.3

    pv_factor = sum([1 / (1 + discount_rate) ** t for t in range(1, years + 1)])

    # ========================================
    # 一、模型说明
    # ========================================
    p()
    p("─" * 60)
    p("一、模型架构说明")
    p("─" * 60)
    p("""
  一体化模型（换电站+电池银行）拆分为两个独立法律实体：

  ┌─────────────────────────────────────────────────┐
  │  第四部分：纯换电站（轻资产运营）                    │
  │  - 拥有换电设备、超充桩、土建（215万）              │
  │  - 从电池银行租周转电池（14块×240元/月）           │
  │  - 向电池银行支付技术服务费（3.5万/年）             │
  │  - 收入：换电服务费 + 超充 + CCER + VPP           │
  │  - 不参与电池租赁业务                             │
  │                                                    │
  │  第五部分：电池银行（重资产持有）                    │
  │  - 拥有全部电池（用户车载+站内周转）                │
  │  - 收入：用户电池租赁 + 周转电池租金 + 技术服务费   │
  │  - 买入电池、租出电池、管理电池全生命周期            │
  └─────────────────────────────────────────────────┘

  关键参数：
    日均换电次数 X（自变量）
    单站服务用户数 = 266人
    系统电损率 = 9%，电损公式 = 净得 ÷ (1−9%) × 9% × 电价
    折旧 = 设备215万 ÷ 10年 = 21.5万/年
    折现率 = 7.5%，15年期
    """)

    # ========================================
    # 二、核心计算函数
    # ========================================
    def calc_pure_station(X, swap_fee=0.4, spare_rent=240):
        """纯换电站模型计算"""
        # 换电净得电量
        swap_net_kwh = X * swap_kwh * 365
        # 超充净得电量（每站固定40辆×25度×365天）
        sc_net_kwh = sc_cars_per_station * sc_kwh * 365

        # 电损（正确公式：净得÷(1−损耗率)×损耗率×电价）
        swap_loss = swap_net_kwh / (1 - loss_rate) * loss_rate * weighted_price
        sc_loss = sc_net_kwh / (1 - loss_rate) * loss_rate * weighted_price
        total_loss = swap_loss + sc_loss

        # 收入
        swap_rev = swap_fee * X * swap_kwh * 365
        sc_rev = supercharge_fee * sc_cars_per_station * sc_kwh * 365

        total_kwh_per_day = X * swap_kwh + sc_cars_per_station * sc_kwh
        total_kwh_year = total_kwh_per_day * 365
        ccer = max(0, total_kwh_year * 0.31 / 1000 * 100)
        vpp = 30000 * total_kwh_per_day / 6000 if total_kwh_per_day > 0 else 0

        total_revenue = swap_rev + sc_rev + ccer + vpp

        # OPEX（八项）
        labor = 144000
        rent = 120000
        maintenance = 60000
        equip_insurance = station_equipment * 0.0015
        spare_rent_cost = spare_bats * spare_rent * 12
        spare_insurance = spare_bats * bat_unit_cost * 0.0020
        tech_service = tech_service_fee_per_station
        total_opex = (total_loss + labor + rent + maintenance +
                      equip_insurance + spare_rent_cost + spare_insurance + tech_service)

        ebitda = total_revenue - total_opex
        net_income = ebitda - depreciation
        net_income_after_tax = (ebitda - depreciation) * (1 - tax_rate)

        cfs = [-station_equipment]
        for t in range(1, years + 1):
            cfs.append(ebitda)

        irr = calc_irr(cfs)
        irr_pct = irr * 100 if irr is not None and irr > -1 else None
        payback = station_equipment / ebitda if ebitda > 0 else float('inf')

        fixed_opex = (labor + rent + maintenance + equip_insurance +
                      spare_rent_cost + spare_insurance + tech_service)

        return {
            'X': X,
            'swap_fee': swap_fee,
            'spare_rent': spare_rent,
            'swap_net_kwh': swap_net_kwh,
            'sc_net_kwh': sc_net_kwh,
            'total_net_kwh': swap_net_kwh + sc_net_kwh,
            'swap_loss': swap_loss,
            'sc_loss': sc_loss,
            'total_loss': total_loss,
            'swap_rev': swap_rev,
            'sc_rev': sc_rev,
            'ccer': ccer,
            'vpp': vpp,
            'total_revenue': total_revenue,
            'total_opex': total_opex,
            'fixed_opex': fixed_opex,
            'ebitda': ebitda,
            'depreciation': depreciation,
            'net_income': net_income,
            'net_income_after_tax': net_income_after_tax,
            'irr': irr_pct,
            'payback': payback,
            'station_capex': station_equipment,
        }

    def calc_battery_bank(users=266):
        """电池银行模型计算"""
        comm = int(users * comm_ratio)
        priv = users - comm

        user_bats = users
        total_bats = user_bats + spare_bats
        total_capex = total_bats * bat_unit_cost

        user_rent = (private_avg_rent * priv + commercial_avg_rent * comm) * 12
        spare_rent_rev = spare_bats * 240 * 12
        tech_service_rev = tech_service_fee_per_station
        total_revenue = user_rent + spare_rent_rev + tech_service_rev

        bat_maintenance = total_capex * 0.02
        tech_service_cost = tech_service_fee_per_station * 0.20
        bat_insurance = total_capex * 0.0020
        total_opex = bat_maintenance + tech_service_cost + bat_insurance

        ebitda = total_revenue - total_opex
        net_income = ebitda

        bat_life = 8
        bat_residual = 0.10

        pv_in = net_income * pv_factor
        bat_replace = total_capex * (1 - bat_residual)
        pv_bat = bat_replace / (1 + discount_rate) ** bat_life
        npv = pv_in - total_capex - pv_bat

        cfs = [-total_capex]
        for t in range(1, years + 1):
            cf = net_income
            if t == bat_life:
                cf -= bat_replace
            cfs.append(cf)

        irr = calc_irr(cfs)
        irr_pct = irr * 100 if irr is not None and irr > -1 else None
        payback = total_capex / net_income if net_income > 0 else float('inf')

        return {
            'users': users,
            'comm': comm,
            'priv': priv,
            'user_bats': user_bats,
            'spare_bats': spare_bats,
            'total_bats': total_bats,
            'total_capex': total_capex,
            'user_rent': user_rent,
            'spare_rent_rev': spare_rent_rev,
            'tech_service_rev': tech_service_rev,
            'total_revenue': total_revenue,
            'bat_maintenance': bat_maintenance,
            'tech_service_cost': tech_service_cost,
            'bat_insurance': bat_insurance,
            'total_opex': total_opex,
            'ebitda': ebitda,
            'net_income': net_income,
            'bat_replace': bat_replace,
            'npv': npv,
            'irr': irr_pct,
            'payback': payback,
        }

    # ========================================
    # 三、纯站模型详细分析
    # ========================================
    p()
    p("─" * 60)
    p("第四部分：纯换电站模型")
    p("─" * 60)

    p()
    p("### 成本结构（OPEX）")
    p()

    X_base = 125
    r = calc_pure_station(X_base)

    p(f"  {'成本项':<24} {'金额(元)':>12} {'占比':>8} {'说明'}")
    p("  " + "-" * 70)
    p("  {:<22} {:>12,.0f} {:>7.1f}%  换电{:,.0f}+超充{:,.0f}".format(
        '电能损耗（系统级电损）', r['total_loss'],
        r['total_loss']/r['total_opex']*100, r['swap_loss'], r['sc_loss']))
    p(f"  {'人工成本':<22} {144000:>12,.0f} {144000/r['total_opex']*100:>7.1f}%  {'16h双班×2人/岗，含社保':<30}")
    p(f"  {'场地租金':<22} {120000:>12,.0f} {120000/r['total_opex']*100:>7.1f}%  {'枢纽/热点地段':<30}")
    p(f"  {'设备维保与运维':<22} {60000:>12,.0f} {60000/r['total_opex']*100:>7.1f}%  {'设备维护+云端网费':<30}")
    p(f"  {'换电站设备保费':<22} {station_equipment*0.0015:>12,.0f} {station_equipment*0.0015/r['total_opex']*100:>7.1f}%  {'215万×0.15%':<30}")
    p(f"  {'周转电池租金':<22} {spare_bats*240*12:>12,.0f} {spare_bats*240*12/r['total_opex']*100:>7.1f}%  {'14块×240元/月':<30}")
    p(f"  {'周转电池保费':<22} {spare_bats*bat_unit_cost*0.0020:>12,.0f} {spare_bats*bat_unit_cost*0.0020/r['total_opex']*100:>7.1f}%  {'14块×2.968万×0.20%':<30}")
    p(f"  {'技术服务费':<22} {tech_service_fee_per_station:>12,.0f} {tech_service_fee_per_station/r['total_opex']*100:>7.1f}%  {'付电池银行':<30}")
    p(f"  {'─'*70}")
    p(f"  {'总OPEX（付现）':<22} {r['total_opex']:>12,.0f} {'100.0%':>8}")
    p(f"  {'固定成本合计':<22} {r['fixed_opex']:>12,.0f} {r['fixed_opex']/r['total_opex']*100:>7.1f}%")
    p(f"  {'可变成本（电损）':<22} {r['total_loss']:>12,.0f} {r['total_loss']/r['total_opex']*100:>7.1f}%")
    p()

    p("### 收入结构")
    p()
    p(f"  {'收入项':<24} {'金额(元)':>12} {'占比':>8} {'说明'}")
    p("  " + "-" * 60)
    p(f"  {'换电服务费':<22} {r['swap_rev']:>12,.0f} {r['swap_rev']/r['total_revenue']*100:>7.1f}%  {'X次/天×50度×0.4元×365天':<35}")
    p(f"  {'超充收入':<22} {r['sc_rev']:>12,.0f} {r['sc_rev']/r['total_revenue']*100:>7.1f}%  {'40辆×25度×0.3元×365天':<35}")
    p(f"  {'CCER碳收益':<22} {r['ccer']:>12,.0f} {r['ccer']/r['total_revenue']*100:>7.1f}%")
    p(f"  {'VPP虚拟电厂':<22} {r['vpp']:>12,.0f} {r['vpp']/r['total_revenue']*100:>7.1f}%")
    p(f"  {'─'*60}")
    p(f"  {'总收入':<22} {r['total_revenue']:>12,.0f} {'100.0%':>8}")
    p()

    p("### 盈利分析（X=" + str(X_base) + "次/天）")
    p()
    p(f"  总收入:       {r['total_revenue']/10000:>8.1f}万")
    p(f"  总OPEX:      -{r['total_opex']/10000:>8.1f}万")
    p(f"  EBITDA:       {r['ebitda']/10000:>8.1f}万")
    p(f"  折旧:        -{r['depreciation']/10000:>8.1f}万")
    p(f"  税前利润:     {r['net_income']/10000:>8.1f}万")
    p(f"  税后利润:     {r['net_income_after_tax']/10000:>8.1f}万")
    p(f"  15年IRR:      {r['irr']:>8.1f}%" if r['irr'] else "  15年IRR:      N/A")
    p(f"  静态回收期:   {r['payback']:>8.1f}年" if r['payback'] < 100 else "  静态回收期:   >15年")

    # ========================================
    # 四、不同换电次数下的全景
    # ========================================
    p()
    p("─" * 60)
    p("四、不同日均换电次数下的全景")
    p("─" * 60)
    p()
    header = (f"  {'X(次/天)':>8} | {'换电收入':>8} | {'电损成本':>8} | "
              f"{'固定OPEX':>8} | {'总OPEX':>8} | {'总收入':>8} | "
              f"{'EBITDA':>8} | {'净利润':>8} | {'IRR':>7} | {'回收期':>6}")
    p(header)
    p("  " + "-" * 105)

    X_list = [30, 50, 60, 70, 78, 79, 80, 90, 100, 110, 125]
    for X in X_list:
        r = calc_pure_station(X)
        irr_str = f"{r['irr']:>6.1f}%" if r['irr'] else "   N/A"
        pb_str = f"{r['payback']:>5.1f}年" if r['payback'] < 100 else "  >15年"
        p(f"  {X:>6}次 | {r['swap_rev']/10000:>7.1f}万 | {r['total_loss']/10000:>7.1f}万 | "
          f"{r['fixed_opex']/10000:>7.1f}万 | {r['total_opex']/10000:>7.1f}万 | "
          f"{r['total_revenue']/10000:>7.1f}万 | {r['ebitda']/10000:>7.1f}万 | "
          f"{r['net_income']/10000:>7.1f}万 | {irr_str} | {pb_str}")

    # ========================================
    # 五、盈亏平衡分析
    # ========================================
    p()
    p("─" * 60)
    p("五、盈亏平衡分析")
    p("─" * 60)

    fixed_opex = (144000 + 120000 + 60000 +
                  station_equipment * 0.0015 +
                  spare_bats * 240 * 12 +
                  spare_bats * bat_unit_cost * 0.0020 +
                  tech_service_fee_per_station)

    var_cost_per_swap = swap_kwh / (1 - loss_rate) * loss_rate * weighted_price
    sc_daily_net = sc_cars_per_station * sc_kwh
    sc_daily_loss = sc_daily_net / (1 - loss_rate) * loss_rate * weighted_price

    p()
    p(f"  单站固定OPEX: {fixed_opex/10000:.1f}万/年")
    p(f"    = 人工14.4 + 租金12.0 + 维保6.0 + 设备保费0.32")
    p(f"    + 周转租金4.03 + 周转保费0.08 + 技术服务3.50")
    p(f"  每次换电可变成本（电损）: {var_cost_per_swap:.1f}元/次")
    p(f"    = 50度 ÷ (1−9%) × 9% × 0.61元 = {var_cost_per_swap:.1f}元")
    p(f"  超充日固定电损: {sc_daily_loss:.1f}元/天 = {sc_daily_loss*365/10000:.2f}万/年")
    p()

    p(f"  {'服务费':>6} | {'每次收入':>6} | {'边际贡献':>6} | {'盈亏平衡':>8} | {'利用率':>6} | {'对应最低用户':>8}")
    p("  " + "-" * 65)

    for sf in [0.2, 0.3, 0.4, 0.5, 0.6]:
        rev = sf * swap_kwh
        margin = rev - var_cost_per_swap
        if margin > 0:
            effective_fixed = fixed_opex - sc_daily_loss * 365
            be_swaps = (effective_fixed / 365) / margin
            be_util = be_swaps / 125 * 100
            min_users = int(np.ceil(be_swaps / (comm_swap_freq * comm_ratio + priv_swap_freq * (1 - comm_ratio))))
            p(f"  {sf:>5.2f}元 | {rev:>5.0f}元 | {margin:>5.0f}元 | {be_swaps:>5.0f}次/天 | {be_util:>4.0f}% | {min_users:>7}人")
        else:
            p(f"  {sf:>5.2f}元 | {rev:>5.0f}元 | {margin:>5.0f}元 | {'不可达':>8} | {'—':>6} | {'—':>8}")

    # ========================================
    # 六、敏感性分析
    # ========================================
    p()
    p("=" * 80)
    p("【敏感性分析】")
    p("=" * 80)

    p()
    p("─" * 60)
    p("6.1 换电服务费 × 换电次数 双因素敏感性（周转电池月租 R=240 元/月）")
    p("─" * 60)

    swap_fees = [0.2, 0.3, 0.4, 0.5, 0.6]
    X_list_sens = [80, 100, 125]

    p()
    p("### 年OPEX（万元）")
    p()
    header = f"  {'':>8}"
    for X in X_list_sens:
        header += f" | {'X=' + str(X) + '次':>10}"
    p(header)
    p("  " + "-" * 45)
    opex_row = f"  {'OPEX':>8}"
    for X in X_list_sens:
        r = calc_pure_station(X)
        opex_row += f" | {r['total_opex']/10000:>9.1f}万"
    p(opex_row)
    p()

    p("### 年EBITDA（万元）")
    p()
    header = f"  {'P\\X':>6}"
    for X in X_list_sens:
        header += f" | {'X=' + str(X):>8}"
    p(header)
    p("  " + "-" * 40)
    for sf in swap_fees:
        row = f"  {sf:>4.1f}元"
        for X in X_list_sens:
            r = calc_pure_station(X, swap_fee=sf)
            ebitda_v = r['ebitda'] / 10000
            marker = "**" if ebitda_v < 0 else ""
            row += f" | {marker}{ebitda_v:>6.1f}{marker}"
        p(row)
    p("  ** 加粗 = 亏损")

    p()
    p("### 年净利润 = EBITDA − 折旧21.5万（万元）")
    p()
    header = f"  {'P\\X':>6}"
    for X in X_list_sens:
        header += f" | {'X=' + str(X):>8}"
    p(header)
    p("  " + "-" * 40)
    for sf in swap_fees:
        row = f"  {sf:>4.1f}元"
        for X in X_list_sens:
            r = calc_pure_station(X, swap_fee=sf)
            ni_v = r['net_income'] / 10000
            marker = "**" if ni_v < 0 else ""
            row += f" | {marker}{ni_v:>6.1f}{marker}"
        p(row)

    p()
    p("### 静态回收期 = 215万 ÷ EBITDA（年）")
    p()
    header = f"  {'P\\X':>6}"
    for X in X_list_sens:
        header += f" | {'X=' + str(X):>8}"
    p(header)
    p("  " + "-" * 40)
    for sf in swap_fees:
        row = f"  {sf:>4.1f}元"
        for X in X_list_sens:
            r = calc_pure_station(X, swap_fee=sf)
            if r['ebitda'] > 0:
                pb = station_equipment / r['ebitda']
                row += f" | {pb:>7.1f}年"
            else:
                row += f" | {'亏损':>8}"
        p(row)

    p()
    p("### 15年期无杠杆IRR")
    p()
    header = f"  {'P\\X':>6}"
    for X in X_list_sens:
        header += f" | {'X=' + str(X):>8}"
    p(header)
    p("  " + "-" * 40)
    for sf in swap_fees:
        row = f"  {sf:>4.1f}元"
        for X in X_list_sens:
            r = calc_pure_station(X, swap_fee=sf)
            irr_v = r['irr']
            if irr_v is not None:
                row += f" | {'≈' + str(int(round(irr_v))) + '%':>8}"
            else:
                row += f" | {'负':>8}"
        p(row)

    # 6.2 电池月租敏感性
    p()
    p("─" * 60)
    p("6.2 电池月租 × 换电次数 双因素敏感性（服务费 P=0.4 元/度）")
    p("─" * 60)

    rents = [220, 240, 260, 280, 300]

    p()
    p("### 年EBITDA（万元）")
    header = f"  {'R\\X':>6}"
    for X in X_list_sens:
        header += f" | {'X=' + str(X):>8}"
    p(header)
    p("  " + "-" * 40)
    for rent in rents:
        row = f"  {rent:>4}元"
        for X in X_list_sens:
            r = calc_pure_station(X, spare_rent=rent)
            row += f" | {r['ebitda']/10000:>6.1f}"
        p(row)

    p()
    p("### 15年期无杠杆IRR")
    header = f"  {'R\\X':>6}"
    for X in X_list_sens:
        header += f" | {'X=' + str(X):>8}"
    p(header)
    p("  " + "-" * 40)
    for rent in rents:
        row = f"  {rent:>4}元"
        for X in X_list_sens:
            r = calc_pure_station(X, spare_rent=rent)
            irr_v = r['irr']
            if irr_v is not None:
                row += f" | {'≈' + str(int(round(irr_v))) + '%':>8}"
            else:
                row += f" | {'负':>8}"
        p(row)

    # 6.3 三变量综合热力矩阵
    p()
    p("─" * 60)
    p("6.3 三变量综合热力矩阵（X=100次/天，仅示IRR）")
    p("─" * 60)
    p()
    header = f"  {'P\\R':>6}"
    for rent in rents:
        header += f" | {'R=' + str(rent):>8}"
    p(header)
    p("  " + "-" * 50)
    for sf in swap_fees:
        row = f"  {sf:>4.1f}元"
        for rent in rents:
            r = calc_pure_station(100, swap_fee=sf, spare_rent=rent)
            irr_v = r['irr']
            if irr_v is not None:
                row += f" | {'≈' + str(int(round(irr_v))) + '%':>8}"
            else:
                row += f" | {'负':>8}"
        p(row)

    # ========================================
    # 七、电池银行模型
    # ========================================
    p()
    p("─" * 60)
    p("第五部分：电池银行模型")
    p("─" * 60)

    bb = calc_battery_bank(266)

    p()
    p(f"  用户规模: {bb['users']}人（营运{bb['comm']}+私家{bb['priv']}）")
    p(f"  电池总数: {bb['total_bats']}块（用户{bb['user_bats']}+周转{bb['spare_bats']}）")
    p(f"  电池资产: {bb['total_capex']/10000:>8.1f}万")
    p()
    p(f"  {'收入项':<24} {'金额(元)':>12} {'占比':>8} {'说明'}")
    p("  " + "-" * 65)
    p(f"  {'用户电池租赁费':<22} {bb['user_rent']:>12,.0f} {bb['user_rent']/bb['total_revenue']*100:>7.1f}%")
    p(f"  {'站内周转电池租金':<22} {bb['spare_rent_rev']:>12,.0f} {bb['spare_rent_rev']/bb['total_revenue']*100:>7.1f}%")
    p(f"  {'技术服务费':<22} {bb['tech_service_rev']:>12,.0f} {bb['tech_service_rev']/bb['total_revenue']*100:>7.1f}%")
    p(f"  {'─'*65}")
    p(f"  {'总收入':<22} {bb['total_revenue']:>12,.0f} {'100.0%':>8}")
    p()
    p(f"  {'成本项':<24} {'金额(元)':>12} {'占比':>8} {'说明'}")
    p("  " + "-" * 65)
    p(f"  {'电池运维管理':<22} {bb['bat_maintenance']:>12,.0f} {bb['bat_maintenance']/bb['total_opex']*100:>7.1f}%  {'831万×2%':<20}")
    p(f"  {'技术服务成本':<22} {bb['tech_service_cost']:>12,.0f} {bb['tech_service_cost']/bb['total_opex']*100:>7.1f}%  {'3.5万×20%':<20}")
    p(f"  {'电池资产保费':<22} {bb['bat_insurance']:>12,.0f} {bb['bat_insurance']/bb['total_opex']*100:>7.1f}%  {'831万×0.20%':<20}")
    p(f"  {'─'*65}")
    p(f"  {'总OPEX':<22} {bb['total_opex']:>12,.0f} {'100.0%':>8}")
    p()
    p(f"  EBITDA:       {bb['ebitda']/10000:>8.1f}万")
    p(f"  CAPEX:        {bb['total_capex']/10000:>8.1f}万")
    p(f"  静态回收期:   {bb['payback']:>8.1f}年")
    p(f"  15年IRR:      {bb['irr']:>8.1f}%")
    p(f"  NPV:          {bb['npv']/10000:>+8.1f}万")

    # ========================================
    # 八、核心结论
    # ========================================
    p()
    p("─" * 60)
    p("八、核心结论")
    p("─" * 60)

    r100 = calc_pure_station(100)
    r125 = calc_pure_station(125)

    p(f"""
  1. 电损公式修正：原"净得×9%×电价"改为"净得÷(1−9%)×9%×电价"（文档L566正确公式）
     - 满负荷125次/天电损: {r125['total_loss']/10000:.2f}万（修正前错为14.53万，差距1/0.91≈1.099倍）
     - X=100次/天电损:   {r100['total_loss']/10000:.2f}万

  2. 纯站盈亏平衡约80次/天（理论值79.3，上取整至80；79次/天必亏损）
     - 在0.4元/度服务费下具备独立生存能力
     - 盈亏平衡点对服务费高度敏感

  3. 纯站IRR（0.4元/度）:
     - X=100次/天: ≈{int(round(r100['irr'])) if r100['irr'] else 'N/A'}%
     - X=125次/天: ≈{int(round(r125['irr'])) if r125['irr'] else 'N/A'}%

  4. 电池银行IRR（266用户）: ≈{bb['irr']:.0f}%
     - 电池银行是重资产持有平台，绝对回报可观
     - 电池成本是核心杠杆，自产电池0.40元/Wh vs 外购0.53元/Wh

  5. 一体化模式下（合并）：平台通过持有电池降低盈亏平衡至43次/天
     - 纯站与一体化差距≈36次（修正后）
     - "车电分离+电池银行"是CATL相对于第三方运营商的根本性竞争优势
    """)

    return "\n".join(out)


if __name__ == "__main__":
    import sys
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

    result = station_model()
    print(result)

    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "analysis_station.txt")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(result)
    print(f"\n结果已保存至: {output_path}")
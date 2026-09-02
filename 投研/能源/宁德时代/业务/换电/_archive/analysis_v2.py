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


def recalculate():
    """
    修正逻辑后的重新计算：
    - 单站模型：收入只含服务费，CAPEX只含站内设备+20块周转电池
    - 电池租赁收入属于电池银行，不属于单站
    """

    out_lines = []

    def p(s=""):
        out_lines.append(s)

    p("=" * 80)
    p("【修正逻辑后的重新计算】")
    p("=" * 80)

    p()
    p("核心修正：电池归属逻辑")
    p("─" * 60)
    p("""
  212块用户电池在车里跑，在整个网络中流转，不是单站资产。
  电池租赁收入（499/599元/月）付给电池银行，不是付给单站。

  正确的单站模型：
  - 收入 = 换电服务费 + 超充服务费 + CCER + VPP（不含电池租赁）
  - CAPEX = 设备 + 20块周转电池（不含用户电池）
  - OPEX = 电损 + 人工 + 租金 + 维保 + 保险 + 营销

  对比三种模型：
  A. 原文模型：收入含租赁 + CAPEX不含用户电池（错误：收入多算）
  B. 我之前的修正：收入含租赁 + CAPEX含212块用户电池（错误：电池不在站里）
  C. 正确模型：收入不含租赁 + CAPEX不含用户电池（正确：各归各）
    """)

    # ========================================
    # 模型C：正确的单站模型
    # ========================================
    p("=" * 80)
    p("【模型C：正确的单站模型（补能站独立核算）】")
    p("=" * 80)

    swap_fee = 0.4
    supercharge_fee = 0.3
    daily_swaps = 100
    daily_sc_cars = 40
    swap_kwh = 50
    sc_kwh_per_car = 25
    loss_rate = 0.09
    weighted_price = 0.61
    discount_rate = 0.075
    years = 15
    tax_rate = 0.25

    private_users = 100
    commercial_users = 112

    p()
    p("─" * 60)
    p("1. 收入（不含电池租赁）")
    p("─" * 60)

    swap_service_annual = (swap_fee * swap_kwh * (0.2 * private_users + 0.71 * commercial_users)) * 365
    supercharge_annual = daily_sc_cars * sc_kwh_per_car * supercharge_fee * 365

    total_kwh_daily = daily_swaps * swap_kwh + daily_sc_cars * sc_kwh_per_car
    ccer = max(0, total_kwh_daily * 365 * 0.31 / 1000 * 100)
    vpp = 30000 * total_kwh_daily / 6000

    total_revenue_no_rent = swap_service_annual + supercharge_annual + ccer + vpp

    p(f"  换电服务费: {swap_service_annual:>10,.0f}元 ({swap_service_annual/10000:.1f}万)")
    p(f"  超充服务费: {supercharge_annual:>10,.0f}元 ({supercharge_annual/10000:.1f}万)")
    p(f"  CCER:       {ccer:>10,.0f}元 ({ccer/10000:.1f}万)")
    p(f"  VPP:        {vpp:>10,.0f}元 ({vpp/10000:.1f}万)")
    p(f"  ─────────────────────")
    p(f"  合计:       {total_revenue_no_rent:>10,.0f}元 ({total_revenue_no_rent/10000:.1f}万)")

    battery_rent_annual = (0.6 * 499 + 0.4 * 369) * private_users * 12 + (0.6 * 599 + 0.4 * 469) * commercial_users * 12
    p(f"\n  对比：电池租赁收入(属电池银行): {battery_rent_annual:>10,.0f}元 ({battery_rent_annual/10000:.1f}万)")
    p(f"  原文总收入(含租赁): {total_revenue_no_rent + battery_rent_annual:>10,.0f}元")
    p(f"  修正后总收入(不含租赁): {total_revenue_no_rent:>10,.0f}元")
    p(f"  收入减少: {battery_rent_annual/10000:.1f}万/年 ({battery_rent_annual/(total_revenue_no_rent + battery_rent_annual)*100:.1f}%)")

    p()
    p("─" * 60)
    p("2. CAPEX（不含用户电池）")
    p("─" * 60)

    swap_equipment = 1600000
    supercharge_equipment = 150000
    civil_works = 300000
    spare_batteries = 20 * 56 * 1000 * 0.53

    capex = swap_equipment + supercharge_equipment + civil_works + spare_batteries
    capex_no_battery = swap_equipment + supercharge_equipment + civil_works

    p(f"  换电设备:     {swap_equipment:>10,.0f}元")
    p(f"  超充桩:       {supercharge_equipment:>10,.0f}元")
    p(f"  土建消防:     {civil_works:>10,.0f}元")
    p(f"  周转电池(20块): {spare_batteries:>10,.0f}元")
    p(f"  ─────────────────────")
    p(f"  CAPEX合计:    {capex:>10,.0f}元 ({capex/10000:.1f}万)")
    p(f"\n  对比：若周转电池由电池银行持有(租赁)")
    p(f"  CAPEX(不含电池): {capex_no_battery:>10,.0f}元 ({capex_no_battery/10000:.1f}万)")

    p()
    p("─" * 60)
    p("3. OPEX")
    p("─" * 60)

    swap_loss = daily_swaps * swap_kwh / (1 - loss_rate) * loss_rate * weighted_price * 365
    sc_loss = daily_sc_cars * sc_kwh_per_car / (1 - loss_rate) * loss_rate * weighted_price * 365
    total_loss = swap_loss + sc_loss

    labor = 144000
    rent = 120000
    maintenance = 60000
    insurance = capex * 0.005
    marketing = 50000

    opex_with_bat_rent = total_loss + labor + rent + maintenance + insurance + marketing + 20 * 500 * 12
    opex_without_bat_rent = total_loss + labor + rent + maintenance + insurance + marketing

    p(f"  电损:     {total_loss:>10,.0f}元 ({total_loss/10000:.1f}万)")
    p(f"  人工:     {labor:>10,.0f}元")
    p(f"  场地租金: {rent:>10,.0f}元")
    p(f"  维保:     {maintenance:>10,.0f}元")
    p(f"  保险:     {insurance:>10,.0f}元")
    p(f"  营销:     {marketing:>10,.0f}元")
    p(f"  ─────────────────────")
    p(f"  OPEX(周转电池自持): {opex_without_bat_rent:>10,.0f}元 ({opex_without_bat_rent/10000:.1f}万)")
    p(f"  +周转电池租金(若租赁): {20*500*12:>10,.0f}元")
    p(f"  OPEX(周转电池租赁): {opex_with_bat_rent:>10,.0f}元 ({opex_with_bat_rent/10000:.1f}万)")

    p()
    p("─" * 60)
    p("4. 三种情景对比")
    p("─" * 60)

    scenarios = [
        ("C1: 自持周转电池", capex, opex_without_bat_rent, total_revenue_no_rent),
        ("C2: 租赁周转电池", capex_no_battery, opex_with_bat_rent, total_revenue_no_rent),
        ("原文: 含电池租赁收入", capex, 469327, total_revenue_no_rent + battery_rent_annual),
    ]

    pv_factor = sum([1 / (1 + discount_rate) ** t for t in range(1, years + 1)])

    for name, cap, op, rev in scenarios:
        ebitda = rev - op
        net_inc = ebitda * (1 - tax_rate)

        bat_replace = spare_batteries * 0.9
        pv_in = net_inc * pv_factor
        pv_bat = bat_replace / (1 + discount_rate) ** 8 if "自持" in name else 0
        npv = pv_in - cap - pv_bat

        cfs = [-cap]
        for t in range(1, years + 1):
            cf = net_inc
            if t == 8 and "自持" in name:
                cf -= bat_replace
            cfs.append(cf)

        irr = calc_irr(cfs)
        irr_pct = irr * 100 if irr is not None else -999
        payback = cap / net_inc if net_inc > 0 else float('inf')

        p(f"\n  【{name}】")
        p(f"    CAPEX: {cap/10000:.1f}万, OPEX: {op/10000:.1f}万, 收入: {rev/10000:.1f}万")
        p(f"    EBITDA: {ebitda/10000:.1f}万, 税后: {net_inc/10000:.1f}万")
        p(f"    NPV: {npv/10000:.1f}万, IRR: {irr_pct:.1f}%, 回收期: {payback:.1f}年")

    # ========================================
    # 敏感性分析
    # ========================================
    p()
    p("=" * 80)
    p("【敏感性分析：正确的单站模型（C1：自持周转电池）】")
    p("=" * 80)

    def full_calc_station(daily_swaps, swap_fee, supercharge_fee, daily_sc_cars=40,
                          battery_self_owned=True):
        swap_kwh = 50
        sc_kwh = 25
        loss_rate = 0.09
        w_price = 0.61

        comm = max(1, int(daily_swaps * 0.8 / 0.71)) if daily_swaps > 0 else 0
        priv = max(1, int(daily_swaps * 0.2 / 0.2)) if daily_swaps > 0 else 0
        if daily_swaps == 0:
            comm, priv = 0, 0

        swap_service = swap_fee * swap_kwh * (0.2 * priv + 0.71 * comm) * 365 if daily_swaps > 0 else 0
        sc_revenue = daily_sc_cars * sc_kwh * supercharge_fee * 365

        total_kwh = daily_swaps * swap_kwh + daily_sc_cars * sc_kwh
        ccer = max(0, total_kwh * 365 * 0.31 / 1000 * 100)
        vpp = 30000 * total_kwh / 6000 if total_kwh > 0 else 0

        revenue = swap_service + sc_revenue + ccer + vpp

        swap_loss = daily_swaps * swap_kwh / (1 - loss_rate) * loss_rate * w_price * 365 if daily_swaps > 0 else 0
        sc_loss = daily_sc_cars * sc_kwh / (1 - loss_rate) * loss_rate * w_price * 365
        total_loss = swap_loss + sc_loss

        if battery_self_owned:
            cap = 1600000 + 150000 + 300000 + 20 * 56 * 1000 * 0.53
            bat_rent = 0
        else:
            cap = 1600000 + 150000 + 300000
            bat_rent = 20 * 500 * 12

        opex = total_loss + 144000 + 120000 + 60000 + cap * 0.005 + 50000 + bat_rent

        ebitda = revenue - opex
        net_inc = ebitda * 0.75

        bat_replace = 20 * 56 * 1000 * 0.53 * 0.9 if battery_self_owned else 0
        pv_in = net_inc * pv_factor
        pv_bat = bat_replace / (1.075) ** 8
        npv = pv_in - cap - pv_bat

        cfs = [-cap]
        for t in range(1, 16):
            cf = net_inc
            if t == 8 and battery_self_owned:
                cf -= bat_replace
            cfs.append(cf)

        irr = calc_irr(cfs)
        irr_pct = irr * 100 if irr is not None and irr > -1 else -999

        payback = cap / net_inc if net_inc > 0 else float('inf')

        return {
            'ebitda': ebitda, 'npv': npv, 'irr': irr_pct,
            'payback': payback, 'revenue': revenue, 'opex': opex,
            'capex': cap, 'comm': comm, 'priv': priv,
            'net_inc': net_inc
        }

    # 5.1 换电服务费 × 日均换电次数 → IRR
    p()
    p("─" * 60)
    p("5.1 换电服务费(元/度) × 日均换电次数 → IRR")
    p("（单站模型：收入不含电池租赁，CAPEX含20块周转电池）")
    p("─" * 60)

    swap_fees = [0.2, 0.3, 0.4, 0.5, 0.6]
    daily_swaps_list = [30, 50, 60, 80, 100, 120]

    header = f"{'服务费':>6} |"
    for ds in daily_swaps_list:
        header += f"  {ds}次/天"
    p(header)
    p("-" * len(header))

    for sf in swap_fees:
        row = f"{sf:>6.1f} |"
        for ds in daily_swaps_list:
            r = full_calc_station(ds, sf, 0.3, 40, True)
            irr = r['irr']
            if irr < -50:
                row += f"    N/A "
            else:
                row += f"  {irr:>5.1f}%"
        p(row)

    # 5.2 换电服务费 × 日均换电次数 → NPV(万元)
    p()
    p("─" * 60)
    p("5.2 换电服务费(元/度) × 日均换电次数 → NPV(万元)")
    p("─" * 60)

    header = f"{'服务费':>6} |"
    for ds in daily_swaps_list:
        header += f"  {ds}次/天"
    p(header)
    p("-" * len(header))

    for sf in swap_fees:
        row = f"{sf:>6.1f} |"
        for ds in daily_swaps_list:
            r = full_calc_station(ds, sf, 0.3, 40, True)
            npv_wan = r['npv'] / 10000
            row += f"  {npv_wan:>6.0f} "
        p(row)

    # 5.3 超充服务费 × 超充车辆数 → IRR
    p()
    p("─" * 60)
    p("5.3 超充服务费(元/度) × 日均超充车辆数 → IRR")
    p("（换电基准: 60次/天, 换电服务费0.4元/度）")
    p("─" * 60)

    sc_fees = [0.2, 0.25, 0.3, 0.35, 0.4]
    sc_cars_list = [10, 20, 30, 40, 50]

    header = f"{'超充费':>6} |"
    for sc in sc_cars_list:
        header += f"  {sc}辆/天"
    p(header)
    p("-" * len(header))

    for scf in sc_fees:
        row = f"{scf:>6.2f} |"
        for sc in sc_cars_list:
            r = full_calc_station(60, 0.4, scf, sc, True)
            irr = r['irr']
            if irr < -50:
                row += f"    N/A "
            else:
                row += f"  {irr:>5.1f}%"
        p(row)

    # 5.4 回收期
    p()
    p("─" * 60)
    p("5.4 换电服务费 × 日均换电次数 → 静态回收期(年)")
    p("─" * 60)

    header = f"{'服务费':>6} |"
    for ds in daily_swaps_list:
        header += f"  {ds}次/天"
    p(header)
    p("-" * len(header))

    for sf in swap_fees:
        row = f"{sf:>6.1f} |"
        for ds in daily_swaps_list:
            r = full_calc_station(ds, sf, 0.3, 40, True)
            pb = r['payback']
            if pb > 50:
                row += f"   >50年 "
            else:
                row += f"  {pb:>5.1f}年"
        p(row)

    # 5.5 盈亏平衡
    p()
    p("─" * 60)
    p("5.5 盈亏平衡点（单站模型）")
    p("─" * 60)

    for sf in [0.3, 0.4, 0.5]:
        for target in ["EBITDA", "NPV"]:
            for x in range(5, 300, 1):
                r = full_calc_station(x, sf, 0.3, 40, True)
                if target == "EBITDA" and r['ebitda'] >= 0:
                    p(f"  换电服务费{sf}元/度 → EBITDA盈亏平衡: 日均{x}次")
                    break
                if target == "NPV" and r['npv'] >= 0:
                    p(f"  换电服务费{sf}元/度 → NPV盈亏平衡: 日均{x}次")
                    break
            else:
                p(f"  换电服务费{sf}元/度 → {target}盈亏平衡: >300次/天(不可达)")

    # ========================================
    # 关键结论
    # ========================================
    p()
    p("=" * 80)
    p("【关键结论（修正后）】")
    p("=" * 80)

    r100 = full_calc_station(100, 0.4, 0.3, 40, True)
    r60 = full_calc_station(60, 0.4, 0.3, 40, True)
    r80 = full_calc_station(80, 0.4, 0.3, 40, True)

    p(f"""
  1. 我之前的分析有误：把212块用户电池(629万)加进单站CAPEX是错的。
     用户电池在车里跑，属于整个网络的共享资产池，不能归到单站。

  2. 原文的真正错误是：把属于电池银行的租赁收入(127.2万/年)
     算进了单站的收入。正确做法是：
     - 电池租赁收入 → 归电池银行
     - 换电服务费 → 归补能站

  3. 修正后（收入不含电池租赁），单站核心指标：

     日均100次 + 0.4元/度:
       EBITDA: {r100['ebitda']/10000:.1f}万, IRR: {r100['irr']:.1f}%, NPV: {r100['npv']/10000:.1f}万, 回收期: {r100['payback']:.1f}年

     日均80次 + 0.4元/度:
       EBITDA: {r80['ebitda']/10000:.1f}万, IRR: {r80['irr']:.1f}%, NPV: {r80['npv']/10000:.1f}万, 回收期: {r80['payback']:.1f}年

     日均60次 + 0.4元/度:
       EBITDA: {r60['ebitda']/10000:.1f}万, IRR: {r60['irr']:.1f}%, NPV: {r60['npv']/10000:.1f}万, 回收期: {r60['payback']:.1f}年

  4. 与原文对比：
     原文: IRR 65%, NPV +1268万, 回收期1.5年（含电池租赁收入）
     修正: IRR {r100['irr']:.1f}%, NPV {r100['npv']/10000:.1f}万, 回收期{r100['payback']:.1f}年（不含电池租赁收入）

  5. 合理判断：
     - 单站IRR {r60['irr']:.1f}%-{r100['irr']:.1f}%（60-100次/天），属于基础设施级回报
     - 电池银行是另一个独立资产包，ROE取决于租金与电池成本差
     - 两者分离后各自回报合理，但绝非"1.5年回本、IRR 65%"的暴利
     - 原文第五部分的分离模型方向正确，但一体化模型(Part 1-3)的收入归属有误
    """)

    return "\n".join(out_lines)


if __name__ == '__main__':
    out_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'analysis_result_v2.txt')
    result = recalculate()
    with io.open(out_path, 'w', encoding='utf-8') as f:
        f.write(result)

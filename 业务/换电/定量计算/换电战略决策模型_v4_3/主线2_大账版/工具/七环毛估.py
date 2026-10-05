# -*- coding: utf-8 -*-
"""七环毛估：把 01_逻辑七环.md 第 3、4、5、7 环的数用同一套参数算一遍。

研究者只读 MD；本脚本只是核对算术、给沙盘出 JSON。每个参数的来源写在 01_逻辑七环.md 的表里。
运行：python3 七环毛估.py  → 打印各环表格，写出 七环结论数.json
"""
import json, math, os

# ---------- 参数（来源见 01_逻辑七环.md 第 3 环"基础数"表） ----------
D = 350                 # 年运营天数
P_C = 510.0             # 充电车电池包 元/度（TrendForce 2026-08）
TAX = 0.05              # 充电车电池随车交购置税 5%（换电电池分开开票不交）
P_S = 590.0             # 换电块 元/度（510 × 1.15）
N = 5000                # 池里循环寿命
CAL = 12                # 日历寿命（年）
TIERS = [0.0, 0.2, 0.5] # 换电比车上充电多交付 0/20/50%
R_RIVAL = 0.075         # 对手正常回报
R_FUND = 0.03           # 出钱人回报（压力 0.05）
R_STRESS = 0.05
GIVE = 0.02             # 让利车队 元/度

# 站（元/度，收益率 0，已扣储能套利；计算书 3.1/3.4）
ST_SWAP = 0.068
ST_FAST = 0.080
ST_MW = 0.098
SALES_KW = 2555         # 每千瓦设备一年卖 7.3 × 350 度

def annuity(r, n):
    return r / (1 - (1 + r) ** (-n))

A10 = annuity(R_RIVAL, 10)
A20 = annuity(R_RIVAL, 20)
# 对手站含 7.5% 回报的加价（元/度）：投资按年金摊回比按寿命摊回多出的部分
UP_FAST = 865 * (0.325 * (A10 - 0.10) + 0.675 * (A20 - 0.05)) / SALES_KW
UP_MW = 1639 * (0.607 * (A10 - 0.10) + 0.393 * (A20 - 0.05)) / SALES_KW
UP_STOR = 1254 * (A10 - 0.10) / SALES_KW   # 配储能每千瓦 1,254 元，10 年
ST_FAST_R = ST_FAST + UP_FAST + UP_STOR
ST_MW_R = ST_MW + UP_MW + UP_STOR
# 不配储能的对照
ST_FAST_R_NOSTOR = 0.114 + UP_FAST
ST_MW_R_NOSTOR = 0.132 + UP_MW

# 换电站
SW_INV = 874.8e4        # 站投资（不含电池）
ROT_INV = 24 * 171 * P_S   # 周转电池 242.1 万
SW_SALES = 30000 * D    # 每站每年 1,050 万度
SW_DEP = 68.74e4        # 每站每年折旧（设备 500/10 + 其余 374.8/20）
SW_MAINT = 25e4         # 维修 设备 × 5%
VAR = 0.035             # 电损与自用电 5% × 0.70
ST_SWAP_MARG = VAR + SW_MAINT / (4104 * SALES_KW)   # 蹭站的边际站成本

KWH_SWAP = 400          # 每次换电度数（513 × 80%）
FAST_KW = 400; MW_KW = 1200; SWAP_MIN = 5; REST_MIN = 20

def time_cost(minutes, value, kwh, rest=True):
    m = max(0.0, minutes - REST_MIN) if rest else minutes
    return m / 60 * value / kwh

def rival_battery(pack, daily, fast_share, x, ret):
    """充电车电池每度（元/度）：途中快充那部分按 N/(1+x) 次算，其余慢充不伤；寿命取小{12 年, 等效循环}"""
    dmg_cycles_day = daily * ((1 - fast_share) + fast_share * (1 + x)) / pack
    life = min(CAL, N / (dmg_cycles_day * D))
    per = pack * P_C * (1 + TAX) / (life * D * daily)
    if ret:
        per *= annuity(R_RIVAL, life) * life
    return per, life

blocks = {}

def block(name, daily, pack, fast_share, swap_share, tval, rest, swap_batt, st_swap, inv_per_swapkwh, kwh_per_event):
    """daily：每车每天用电；swap_share：过站电占比；电池项按每度过站的电摊（÷ swap_share）"""
    out = {"name": name, "tiers": []}
    for x in TIERS:
        rb0, life0 = rival_battery(pack, daily, fast_share, 0.0, False)
        rbx0, lifex = rival_battery(pack, daily, fast_share, x, False)
        rbx, _ = rival_battery(pack, daily, fast_share, x, True)
        k = 1 / swap_share   # 每度过站的电背多少度的电池
        # 对手：取超充、普快里便宜的
        ev = kwh_per_event
        t_mw = time_cost(ev / MW_KW * 60, tval, ev, rest)
        t_fast = time_cost(ev / FAST_KW * 60, tval, ev, rest)
        t_swap = time_cost(SWAP_MIN, tval, ev, rest)
        mw = ST_MW_R + rbx * k + t_mw
        fast = ST_FAST_R + rbx * k + t_fast
        rival = min(mw, fast)
        rival_name = "超充" if mw <= fast else "普快"
        rst = ST_MW_R if mw <= fast else ST_FAST_R
        rt = t_mw if mw <= fast else t_fast
        swap = st_swap + swap_batt * k + t_swap
        gap = rival - swap
        inv = inv_per_swapkwh
        rent = inv * R_FUND
        rent5 = inv * R_STRESS
        left = gap - rent - GIVE
        left5 = gap - rent5 - GIVE
        # 价格战压力档：对手全投资收益率 0（站不含回报、电池按寿命摊回）
        rival0 = min(ST_MW + rbx0 * k + t_mw, ST_FAST + rbx0 * k + t_fast)
        gap0 = rival0 - swap
        left0 = gap0 - rent - GIVE
        # 回本年数：投资 ÷ 每年收回的现金（换电自己的折旧 ＋ 差价 − 让利）
        dep = swap_batt * k + (SW_DEP / SW_SALES if st_swap == ST_SWAP else 0.0)
        payback = inv / (dep + gap - GIVE)
        out["tiers"].append({
            "gap0": gap0, "left0": left0, "payback": payback, "dep": dep,
            "x": x, "rival": rival_name,
            "rival_station": rst, "rival_battery_per_swapkwh": rbx * k, "rival_time": rt,
            "rival_total": rival, "mw_total": mw, "fast_total": fast,
            "swap_station": st_swap, "swap_battery_per_swapkwh": swap_batt * k, "swap_time": t_swap,
            "swap_total": swap, "gap": gap,
            "gap_station": rst - st_swap, "gap_time": rt - t_swap,
            "gap_batt_premium_tax": (rb0 - swap_batt) * k,
            "gap_batt_life": (rbx0 - rb0) * k,
            "gap_batt_return": (rbx - rbx0) * k,
            "rival_life": lifex, "inv": inv, "roi": gap / inv, "rent": rent, "left": left,
            "rent5": rent5, "left5": left5,
        })
    blocks[name] = out
    return out

# 接力：每天 2,000 度，3 块 513 度，全部途中补，全过站；时间 50 元/时，扣法定休息
inv_relay = P_S * 513 / (2000 * D) + ROT_INV / SW_SALES + SW_INV / SW_SALES
block("接力", 2000, 513, 1.0, 1.0, 50, True, P_S / N, ST_SWAP, inv_relay, KWH_SWAP)
# 多班倒：每天 390 度（13.65 万度 ÷ 350），2 块 342 度，全部途中补；无法定休息，时间全额；池子放老（日历先到），换电电池含周转 0.142
mb_batt = (77 * 342 + 4104) * P_S / (CAL * SW_SALES)   # 每站 77 辆车上 ＋ 24 块周转，12 年
inv_mb = P_S * 342 / (390 * D) + ROT_INV / SW_SALES + SW_INV / SW_SALES
block("多班倒", 390, 342, 1.0, 1.0, 50, False, mb_batt, ST_SWAP, inv_mb, 274)
# 要停的车（蹭站）：每天 700 度，白天换 400、夜里慢充 300；时间 33 元/时，扣法定休息
inv_stop = P_S * 513 / (400 * D)
block("要停的车_蹭站", 700, 513, 400 / 700, 400 / 700, 33, True, P_S / N, ST_SWAP_MARG, inv_stop, KWH_SWAP)
inv_stop_new = inv_stop + ROT_INV / SW_SALES + SW_INV / SW_SALES
block("要停的车_另建站", 700, 513, 400 / 700, 400 / 700, 33, True, P_S / N, ST_SWAP, inv_stop_new, KWH_SWAP)

# ---------- 2030 年规模与估值（第 5、7 环） ----------
VOL = {"接力": 700, "多班倒": 300, "要停的车": 1000, "城配乘用": 350, "私家车": 90}   # 亿度（过站）
CITY_LEFT = [0.02, 0.04, 0.07]   # 城配、营运乘用：没有算账的判断值（七环原值）
PRIV_LEFT = [0.0, 0.0, 0.0]      # 私家车：按 3% 收租后约 0
MKT_CAP = 13500                  # 宁德市值 亿元（2026-09-30 约 1.33–1.38 万亿）
PE_MGR = 25
PE_LOCK = 25
PE_BASE = 15                     # 基线里本来就有的那份重卡电池，按市场现在给宁德的倍数
BASE_SHARE = 0.6                 # 没有换电时宁德本来能拿到的重卡电池份额（2025 年 1–7 月实测 63.8%，方得网 2025-09-25）
PROFIT_PER_KWH = 100             # 每度容量净利 元（2025 年 722 亿 ÷ 661 吉瓦时 ≈ 109）
FEE_RATE = 0.01                  # 管理费率（黑石一类约 1%，七环第 7 环合理性检验）
PE_SPREAD = 15                   # 资金价差部分按宁德现在的倍数（前向约 14 倍）

def lock_gwh(vol):
    relay = vol["接力"] / N * 1e8 / 1e6          # 吉瓦时：亿度 ÷ 5,000 次
    stop = vol["要停的车"] * 700 / 400 / N * 1e8 / 1e6
    mb_trucks = vol["多班倒"] * 1e8 / (390 * D)
    mb_st = vol["多班倒"] * 1e8 / SW_SALES
    mb = (mb_trucks * 342 + mb_st * 4104) / CAL / 1e6
    return relay + stop + mb

res = {"params": {"天数": D, "充电车电池": P_C, "换电块": P_S, "购置税": TAX, "对手回报": R_RIVAL,
                  "出钱人回报": R_FUND, "让利": GIVE,
                  "对手站含回报": {"普快": ST_FAST_R, "超充": ST_MW_R, "普快不配储": ST_FAST_R_NOSTOR, "超充不配储": ST_MW_R_NOSTOR},
                  "站加价": {"普快": UP_FAST, "超充": UP_MW, "储能": UP_STOR},
                  "蹭站边际站成本": ST_SWAP_MARG},
       "blocks": blocks}

val = []
for i, x in enumerate(TIERS):
    left = {
        "接力": blocks["接力"]["tiers"][i]["left"],
        "多班倒": blocks["多班倒"]["tiers"][i]["left"],
        "要停的车": blocks["要停的车_蹭站"]["tiers"][i]["left"],
        "城配乘用": CITY_LEFT[i], "私家车": PRIV_LEFT[i]}
    left5 = {
        "接力": blocks["接力"]["tiers"][i]["left5"],
        "多班倒": blocks["多班倒"]["tiers"][i]["left5"],
        "要停的车": blocks["要停的车_蹭站"]["tiers"][i]["left5"],
        "城配乘用": 0.0, "私家车": 0.0}   # 压力档：城配、营运乘用的判断值同步归零（审稿意见）
    left0 = {
        "接力": blocks["接力"]["tiers"][i]["left0"],
        "多班倒": blocks["多班倒"]["tiers"][i]["left0"],
        "要停的车": blocks["要停的车_蹭站"]["tiers"][i]["left0"],
        "城配乘用": 0.0, "私家车": 0.0}
    sys_pre0 = sum(VOL[k] * left0[k] for k in VOL)
    sys_pre = sum(VOL[k] * left[k] for k in VOL)            # 亿元
    sys_pre5 = sum(VOL[k] * left5[k] for k in VOL)
    gwh = lock_gwh(VOL)
    lock_profit = gwh * PROFIT_PER_KWH / 100              # 亿元：吉瓦时 × 元/度 ÷ 100
    mgr = sys_pre * 0.75 * PE_MGR
    mgr5 = sys_pre5 * 0.75 * PE_MGR
    lock_full = lock_profit * PE_LOCK
    lock_incr = lock_profit * PE_LOCK - BASE_SHARE * lock_profit * PE_BASE
    pie = sum(VOL[k] * blocks[b]["tiers"][i]["gap"] for k, b in [("接力", "接力"), ("多班倒", "多班倒"), ("要停的车", "要停的车_蹭站")])
    inv = sum(VOL[k] * blocks[b]["tiers"][i]["inv"] for k, b in [("接力", "接力"), ("多班倒", "多班倒"), ("要停的车", "要停的车_蹭站")])
    fee = min(sys_pre, FEE_RATE * inv)
    spread = sys_pre - fee
    mgr_fee = fee * 0.75 * PE_MGR
    spread_v = spread * 0.75 * PE_SPREAD
    main = mgr_fee + spread_v + lock_incr
    fee5 = min(sys_pre5, FEE_RATE * inv); spread5 = sys_pre5 - fee5
    main5 = fee5 * 0.75 * PE_MGR + spread5 * 0.75 * PE_SPREAD + lock_incr
    if sys_pre0 > 0:
        f0 = min(sys_pre0, FEE_RATE * inv); main0 = f0 * 0.75 * PE_MGR + (sys_pre0 - f0) * 0.75 * PE_SPREAD + lock_incr
    else:
        main0 = sys_pre0 * 0.75 * PE_SPREAD + lock_incr
    val.append({"x": x, "sys_pre0": sys_pre0, "main0": main0, "pct_main0": main0 / MKT_CAP, "fee": fee, "spread": spread, "mgr_fee": mgr_fee, "spread_v": spread_v,
                "main": main, "pct_main": main / MKT_CAP, "main5": main5, "pct_main5": main5 / MKT_CAP,
                "left_per_kwh": left, "sys_pre": sys_pre, "sys_pre5": sys_pre5,
                "lock_gwh": gwh, "lock_profit": lock_profit, "mgr": mgr, "mgr5": mgr5,
                "lock_full": lock_full, "lock_incr": lock_incr,
                "total_incr": mgr + lock_incr, "total_full": mgr + lock_full,
                "pct_incr": (mgr + lock_incr) / MKT_CAP, "pct_full": (mgr + lock_full) / MKT_CAP,
                "pie_heavy": pie, "inv_heavy": inv, "roi_heavy": pie / inv})
res["valuation_2030"] = val

# 站数、投资、电池（中性，三档相同）
st_base = (VOL["接力"] + VOL["多班倒"]) * 1e8 / SW_SALES
st_trunk = VOL["接力"] * 1e8 / SW_SALES
spare = st_trunk * 115
need = VOL["要停的车"] * 1e8 / KWH_SWAP / D
relay_trucks = VOL["接力"] * 1e8 / (2000 * D)
mb_trucks = VOL["多班倒"] * 1e8 / (390 * D)
stop_trucks = VOL["要停的车"] * 1e8 / (400 * D)
batt_gwh = (relay_trucks * 513 + mb_trucks * 342 + stop_trucks * 513 + st_base * 4104) / 1e6
res["network_2030"] = {"基本盘站": st_base, "干线站": st_trunk, "干线站余量车次每天": spare, "要停的车要的车次每天": need,
                       "接力车": relay_trucks, "多班倒车": mb_trucks, "要停的车": stop_trucks,
                       "站投资亿": st_base * SW_INV / 1e8, "周转电池亿": st_base * ROT_INV / 1e8,
                       "车上电池亿": (relay_trucks * 513 + mb_trucks * 342 + stop_trucks * 513) * P_S / 1e8,
                       "锁住的电池吉瓦时": batt_gwh,
                       "另建四分之一的站": VOL["要停的车"] * 0.25 * 1e8 / SW_SALES}

# 2035
v35 = res["valuation_2030"][1]
avg_left = v35["sys_pre"] / sum(VOL.values())
sys35 = 5500 * avg_left
HEAVY35 = 4500 / 2000   # 2035 年重卡换电 4,500 亿度 ÷ 2030 年 2,000（锁住的制造与投资只按重卡放大）
lock35_gwh = lock_gwh({k: v * HEAVY35 for k, v in VOL.items() if k in ("接力", "多班倒", "要停的车")} | {"城配乘用": 0, "私家车": 0})
lock35 = lock35_gwh * PROFIT_PER_KWH / 100
mgr35 = sys35 * 0.75 * PE_MGR
lock35_incr = lock35 * PE_LOCK - BASE_SHARE * lock35 * PE_BASE
inv35 = res["valuation_2030"][1]["inv_heavy"] * HEAVY35
fee35 = min(sys35, FEE_RATE * inv35)
main35 = fee35 * 0.75 * PE_MGR + (sys35 - fee35) * 0.75 * PE_SPREAD + lock35_incr
full35 = sys35 * 0.75 * PE_MGR + lock35 * PE_LOCK
res["y2035"] = {"full": full35, "full_share": full35 / MKT_CAP, "inv": inv35, "fee": fee35, "main": main35, "main_share": main35 / MKT_CAP,"avg_left": avg_left, "sys_pre": sys35, "lock_gwh": lock35_gwh, "lock_profit": lock35,
                "mgr": mgr35, "lock_incr": lock35_incr, "lock_full": lock35 * PE_LOCK,
                "total_incr": mgr35 + lock35_incr, "share_of_today": (mgr35 + lock35_incr) / MKT_CAP}
# 反算
need_after_tax = MKT_CAP / PE_MGR
res["reverse"] = {"税后": need_after_tax, "税前": need_after_tax / 0.75,
                  "度数_亿_只算体系": need_after_tax / 0.75 / avg_left,
                  "度数_亿_主口径": 5500 * MKT_CAP / main35,
                  "度数_亿_上沿": 5500 * MKT_CAP / full35}

def fmt(v, d=3):
    return f"{v:.{d}f}"

if __name__ == "__main__":
    p = res["params"]
    print("对手站含回报：普快", fmt(ST_FAST_R), "超充", fmt(ST_MW_R), " 加价 普快", fmt(UP_FAST), "超充", fmt(UP_MW), "储能", fmt(UP_STOR))
    print("不配储能：普快", fmt(ST_FAST_R_NOSTOR), "超充", fmt(ST_MW_R_NOSTOR), " 蹭站边际", fmt(ST_SWAP_MARG))
    for name, b in blocks.items():
        print("\n==", name)
        for t in b["tiers"]:
            print(f" x={t['x']:.0%} 对手={t['rival']} 对手合计={fmt(t['rival_total'])}(超充{fmt(t['mw_total'])}/普快{fmt(t['fast_total'])}) "
                  f"站{fmt(t['rival_station'])} 电池{fmt(t['rival_battery_per_swapkwh'])} 时间{fmt(t['rival_time'])} 寿命{t['rival_life']:.1f}年 | "
                  f"换电 站{fmt(t['swap_station'])} 电池{fmt(t['swap_battery_per_swapkwh'])} 时间{fmt(t['swap_time'])} 合计{fmt(t['swap_total'])} | "
                  f"差价{fmt(t['gap'])} 价格战差价{fmt(t['gap0'])} 价格战留{fmt(t['left0'])} 回本{t['payback']:.1f}年 [站{fmt(t['gap_station'])} 时间{fmt(t['gap_time'])} 溢价税{fmt(t['gap_batt_premium_tax'])} 延寿{fmt(t['gap_batt_life'])} 对手回报{fmt(t['gap_batt_return'])}] "
                  f"投资{fmt(t['inv'],2)} 收益率{t['roi']:.1%} 租金{fmt(t['rent'])} 留{fmt(t['left'])} (5%:{fmt(t['left5'])})")
    print("\n== 2030 估值")
    for v in val:
        print(f" x={v['x']:.0%} 价格战体系{v['sys_pre0']:.0f}→{v['main0']:.0f}({v['pct_main0']:.0%}) 主口径{v['main']:.0f}({v['pct_main']:.0%}; 5%:{v['main5']:.0f} {v['pct_main5']:.0%}) 管理费{v['fee']:.0f}→{v['mgr_fee']:.0f} 资金价差{v['spread']:.0f}→{v['spread_v']:.0f} | 体系税前{v['sys_pre']:.0f}亿(5%:{v['sys_pre5']:.0f}) 锁住{v['lock_gwh']:.0f}GWh→{v['lock_profit']:.0f}亿 "
              f"管理人{v['mgr']:.0f}(5%:{v['mgr5']:.0f}) 锁住制造 全额{v['lock_full']:.0f}/增量{v['lock_incr']:.0f} "
              f"合计增量{v['total_incr']:.0f}({v['pct_incr']:.0%}) 全额{v['total_full']:.0f}({v['pct_full']:.0%}) "
              f"重卡蛋糕{v['pie_heavy']:.0f}亿 投资{v['inv_heavy']:.0f}亿 收益率{v['roi_heavy']:.1%}")
    print("\n== 网络", {k: round(v, 1) for k, v in res["network_2030"].items()})
    print("== 2035", {k: round(v, 3) for k, v in res["y2035"].items()})
    print("== 反算", {k: round(v, 1) for k, v in res["reverse"].items()})
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "七环结论数.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    print("写出", out)


# ---------- 复核补充（2026-10-05 独立审稿后加）：同口径回报、年金租金、宁德自持、蹭站损失储能回血 ----------
def solve_irr(f, lo=-0.5, hi=1.0):
    for _ in range(200):
        mid = (lo + hi) / 2
        if f(mid) > 0: lo = mid
        else: hi = mid
    return (lo + hi) / 2

def excess(r, assets):
    """一组资产每度一年的"回报部分"：按 r 年金摊回比按寿命直线摊回多出来的（元/度）"""
    return sum(inv * (annuity(r, life) - 1 / life) if r != 0 else 0.0 for inv, life in assets)

ST_EQ = 500 / 874.8
def station_assets(per):   # 站：设备 10 年、其余 20 年
    return [(per * ST_EQ, 10), (per * (1 - ST_EQ), 20)]

SW_PER = SW_INV / SW_SALES
ROT_PER = ROT_INV / SW_SALES
ASSETS = {
    "接力": [(P_S * 513 / (2000 * D) + ROT_PER, (P_S * 513 / (2000 * D) + ROT_PER) / (P_S / N))] + station_assets(SW_PER),
    "多班倒": [(P_S * 342 / (390 * D) + ROT_PER, CAL)] + station_assets(SW_PER),
    "要停的车_蹭站": [(P_S * 513 / (400 * D), (P_S * 513 / (400 * D)) / (P_S / N * 700 / 400))],
    "要停的车_另建站": [(P_S * 513 / (400 * D), (P_S * 513 / (400 * D)) / (P_S / N * 700 / 400)), (ROT_PER, 5.6)] + station_assets(SW_PER),
}
RIVAL_INV = {}
for name, daily, pack, k in [("接力", 2000, 513, 1.0), ("多班倒", 390, 342, 1.0), ("要停的车_蹭站", 700, 513, 700 / 400), ("要停的车_另建站", 700, 513, 700 / 400)]:
    RIVAL_INV[name] = (1639 + 1254) / SALES_KW + pack * P_C * (1 + TAX) / (daily * D) * k

R_SELF = 0.075
chk = {}
for name, b in blocks.items():
    rows = []
    for t in b["tiers"]:
        a = ASSETS[name]
        irr = solve_irr(lambda r: t["gap"] - excess(r, a))
        rent3a = excess(R_FUND, a); rent5a = excess(R_STRESS, a); rent_self = excess(R_SELF, a)
        b_ret = t["gap"] - (t["gap_station"] - (t["rival_station"] - ST_MW) + t["gap_time"] + t["gap_batt_premium_tax"] + t["gap_batt_life"])
        rows.append({"x": t["x"], "irr_swap": irr, "rival_roi_simple": b_ret / RIVAL_INV[name], "swap_roi_simple": t["gap"] / t["inv"],
                     "funder_irr_of_rent3": solve_irr(lambda r: t["rent"] - excess(r, a)),
                     "funder_irr_of_rent5": solve_irr(lambda r: t["rent5"] - excess(r, a)),
                     "rent3_annuity": rent3a, "left3_annuity": t["gap"] - rent3a - GIVE,
                     "left_self": t["gap"] - rent_self - GIVE, "lives": [round(l, 1) for _, l in a]})
    chk[name] = rows

def sys_from(key, city):
    out = []
    for i in range(3):
        v = VOL["接力"] * chk["接力"][i][key] + VOL["多班倒"] * chk["多班倒"][i][key] + VOL["要停的车"] * chk["要停的车_蹭站"][i][key] + VOL["城配乘用"] * city[i]
        out.append(v)
    return out

sys_ann = sys_from("left3_annuity", CITY_LEFT)
sys_self = sys_from("left_self", [0, 0, 0])
alt = []
for i in range(3):
    v = res["valuation_2030"][i]
    fee = min(sys_ann[i], FEE_RATE * v["inv_heavy"])
    main_ann = fee * 0.75 * PE_MGR + (sys_ann[i] - fee) * 0.75 * PE_SPREAD + v["lock_incr"]
    main_self = sys_self[i] * 0.75 * PE_SPREAD + v["lock_incr"]
    alt.append({"sys_ann": sys_ann[i], "main_ann": main_ann, "pct_ann": main_ann / MKT_CAP,
                "sys_self": sys_self[i], "main_self": main_self, "pct_self": main_self / MKT_CAP,
                "after_tax_total": v["sys_pre"] * 0.75 + v["lock_profit"]})
# 蹭站把站跑到近满、基本盘的储能回血被吃掉的上限
per_station_piggy = res["network_2030"]["要停的车要的车次每天"] / res["network_2030"]["干线站"] * KWH_SWAP
arb_loss = 0.074 * 30000 / per_station_piggy
res["复核"] = {"chk": chk, "alt": alt, "蹭站每站每天度数": per_station_piggy, "蹭站储能回血损失上限_元每度": arb_loss,
               "蹭站储能回血损失_体系亿": arb_loss * VOL["要停的车"],
               "2035税后合计": res["y2035"]["sys_pre"] * 0.75 + res["y2035"]["lock_profit"]}

if __name__ == "__main__":
    for name, rows in chk.items():
        print("复核", name, [{k: (round(v, 4) if isinstance(v, float) else v) for k, v in r.items()} for r in rows])
    print("复核 alt", [{k: round(v, 3) for k, v in a.items()} for a in alt])
    print("复核 蹭站", round(per_station_piggy), round(arb_loss, 4), round(arb_loss * VOL["要停的车"], 1), "2035税后", round(res["复核"]["2035税后合计"], 1))
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "七环结论数.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)

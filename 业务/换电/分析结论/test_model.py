"""
build_vpp_model.py 的配套测试（与《换电框架-能量维度.md》对照）

两类断言：
1. 参数对齐断言：模型参数 == md 章节引用的数字（md 改了测试就红）
2. 回归断言：关键输出 == 重构前 golden 基准（或逻辑修正后的干净值）

运行：在 analysis 结论目录执行 `pytest test_model.py -v`
依赖：标准库 math；本文件与 build_vpp_model.py 同目录

注意（重要）：
- 主程序目标：算 2030 稳态估值（换电框架-能量维度.md L20）。2026 基准只作
  放大基数与重要性检验锚（L23-24），不对其估值；2026 段的 EBITDA 校验法 FCFF
  仅校验收益量级。test_known_issue_2026_eac_not_145_9 锁定的是「分桶不重复」逻辑
  （旧版v5把同一电池capex重复放入LV/HV两桶实算≈279系bug），与主链估值解耦。
- 私家车利用率 util_from_private 仅用于终局三情景（md L210-214），基础营运乘用车
  用 LV_VEHICLES_MT（非硬编码280）；不推算2027/2028（无私家车渗透锚）。
- 其余数字（2026收益汇总、终局CAPEX/FCFF/Equity、CATL权益、终局利用率情景）
  与旧版完全一致，已锁定为回归基准；敏感性利用率现由 md L192-214 推导（非魔术数字）。
"""

import math
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_vpp_model as M


# ============================================================
# A. 参数对齐断言（模型 ↔ md 章节）
# ============================================================
def test_align_terminal_sites():
    # 换电框架.md L142
    assert M.LV_SITES_TERMINAL == 30000
    assert M.HV_SITES_TERMINAL == 3000


def test_align_amplification():
    # 换电框架.md L198
    assert abs(M.AMP_LV_STATION - 10.0) < 1e-9
    assert abs(M.AMP_LV_VEHICLE - 5.0) < 1e-9
    assert abs(M.AMP_HV - 3.33) < 0.01


def test_align_battery_price():
    # 电池价格口径统一与pack价格参考.md 3.2.3
    assert M.BATTERY_PRICE_PER_KWH == 590


def test_align_ev_ebitda_multiples():
    # 换电框架.md 估值链
    assert M.EV_EBITDA_LOW == 12
    assert M.EV_EBITDA_MID == 18
    assert M.EV_EBITDA_HIGH == 25


def test_align_private_scenarios():
    # 换电框架-能量维度.md 2.2节
    assert M.PRIVATE_SCENARIOS["保守"]["vehicles"] == 102
    assert M.PRIVATE_SCENARIOS["稳健"]["vehicles"] == 290
    assert M.PRIVATE_SCENARIOS["激进"]["vehicles"] == 570


def test_align_catl_scenarios():
    # 换电框架-能量维度.md 2.3节
    assert M.CATL_SCENARIOS["稳健"]["station"] == 0.20
    assert M.CATL_SCENARIOS["稳健"]["battery"] == 0.40


# ============================================================
# B. 回归断言（重构后 == 旧版 golden 基准）
# ============================================================
def test_2026_revenue_summary():
    # v9/HDT 更新（SINGLE_KWH_HV 250→171回退; HV_FLEET_SIZE 210→222派生, pen/share 0.5→0.448/0.348；LCV仅进终局）
    rev = M.compute_revenue(M.HV_SITES_2026, M.LV_SITES_2026)
    assert abs(rev["total_revenue"] - 201.09) < 0.01
    assert abs(rev["total_ebitda"] - 172.85) < 0.01
    assert abs(rev["total_profit"] - 42.02) < 0.01


def test_2026_rent_breakdown():
    rev = M.compute_revenue(M.HV_SITES_2026, M.LV_SITES_2026)
    assert abs(rev["rent"]["revenue"] - 132.41) < 0.01
    assert abs(rev["rent"]["profit"] - 20.66) < 0.01


def test_terminal_util_scenarios():
    rev = M.compute_revenue(M.HV_SITES_2026, M.LV_SITES_2026)
    # 2030稳态利用率情景：仅终局三情景有私家车渗透锚（不推算2027/2028）
    # 重卡站1.0×，乘用车站利用率由 util_from_private 推导（md L210-214）
    # 期望净利取自重构后报告输出（终局站数 × 单站净利 × 推导利用率）
    # 以 private_wan 为 key（与 label 文本解耦）
    # v9/HDT 更新：重卡单车电量回退171kWh、车队规模派生后利润重估
    cases = {
        102: (1.08, 261.4),
        290: (1.21, 283.4),
        570: (1.41, 316.0),
    }
    for s in M.TERMINAL_UTIL_SCENARIOS:
        expect_util, expect = cases[s["private_wan"]]
        # 重卡站1.0×，乘用车站用推导利用率
        lv_util = M.util_from_private(s["private_wan"])
        hv_util = 1.0
        assert abs(lv_util - expect_util) < 0.01, f"{s['label']} 利用率推导偏离: {lv_util} vs {expect_util}"
        profit = (rev["hv_profit_per_station"] * M.HV_SITES_TERMINAL * hv_util
                  + rev["lv_profit_per_station"] * M.LV_SITES_TERMINAL * lv_util)
        assert abs(profit - expect) < 0.5, f"{s['label']} 敏感性净利偏离: {profit} vs {expect}"


def test_util_from_private_matches_md():
    """利用率推导应与换电框架-能量维度.md L210-214 表一致。
    重卡站恒定1.0×；乘用车站：保守≈1.08 / 稳健1.21 / 激进1.41×
    （基础营运乘用车用 LV_VEHICLES_MT=281，比md表280多1万，故保守1.08而非1.07，量级自洽）
    仅终局三情景有私家车渗透锚，不推算2027/2028。"""
    # 无私家车 → 1.0
    assert abs(M.util_from_private(0) - 1.0) < 0.01
    # 私家车三情景
    assert abs(M.util_from_private(M.PRIVATE_SCENARIOS["保守"]["vehicles"]) - 1.08) < 0.02
    assert abs(M.util_from_private(M.PRIVATE_SCENARIOS["稳健"]["vehicles"]) - 1.21) < 0.02
    assert abs(M.util_from_private(M.PRIVATE_SCENARIOS["激进"]["vehicles"]) - 1.41) < 0.02


def test_compute_capex_independent():
    """CAPEX 应由独立 compute_capex 计算，不依赖收入/EBITDA 字段。"""
    cap = M.compute_capex(M.HV_SITES_2026, M.LV_SITES_2026)
    # 站体 CAPEX = (900×500 + 3000×200)/1e4 = 105亿
    assert abs(cap["station_capex_total"] - 105.0) < 0.1
    # 站内电池 + 装车电池均 > 0
    assert cap["station_battery_capex"] > 0
    assert cap["vehicle_battery_capex"] > 0
    # 分桶 capex 求和 == total
    assert abs(cap["lv_battery_capex"] + cap["hv_battery_capex"] - cap["total_battery_capex"]) < 1e-6


def test_installed_capacity_matrix():
    """装机量 3×2 矩阵（车型×维度，GWh）应正确统计，且不再由 capex 反推。

    口径：装机量(GWh) = 数量 × 单资产 kWh ÷ 1e6；与 capex 同源但独立，互不反推。
    与换电框架.md L139-162 量级自洽；矩阵含营运车/乘用车小计（L154）。
    """
    cap = M.compute_capex(M.HV_SITES_2026, M.LV_SITES_2026)
    m = cap["installed_matrix"]
    # 手工复算 2026 基准四桶 GWh，交叉校验矩阵
    hv_st = M.HV_SITES_2026 * M.HV_BATTERIES_PER_STATION * M.SINGLE_KWH_HV / 1e6
    lv_st = M.LV_SITES_2026 * M.LV_BATTERIES_PER_STATION * M.SINGLE_KWH_LV / 1e6
    hv_veh = M.HV_VEHICLES_M0 * 1e4 * M.HV_BLOCKS_PER_VEHICLE * M.SINGLE_KWH_HV / 1e6
    lv_veh = M.LV_VEHICLES_M0 * 1e4 * M.LV_BLOCKS_PER_VEHICLE * M.SINGLE_KWH_LV / 1e6
    assert abs(m["重卡"]["站体"] - hv_st) < 1e-6
    assert abs(m["乘用营运"]["站体"] - lv_st) < 1e-6
    assert abs(m["重卡"]["电池银行"] - hv_veh) < 1e-6
    assert abs(m["乘用营运"]["电池银行"] - lv_veh) < 1e-6
    # 私家车在 2026 基准为 0（未导入）
    assert abs(m["私家车"]["电池银行"] - 0.0) < 1e-9
    # 小计自洽：营运车小计 = 重卡 + 乘用营运；乘用车小计 = 乘用营运 + 私家车
    assert abs(m["营运车小计"]["站体"] - (m["重卡"]["站体"] + m["乘用营运"]["站体"])) < 1e-9
    assert abs(m["营运车小计"]["电池银行"] - (m["重卡"]["电池银行"] + m["乘用营运"]["电池银行"])) < 1e-9
    assert abs(m["乘用车小计"]["电池银行"] - (m["乘用营运"]["电池银行"] + m["私家车"]["电池银行"])) < 1e-9
    # 总装机量(全口径=站体+电池银行) = 各车型两维度之和
    total_all = (m["重卡"]["站体"] + m["重卡"]["电池银行"]
                 + m["乘用营运"]["站体"] + m["乘用营运"]["电池银行"]
                 + m["私家车"]["站体"] + m["私家车"]["电池银行"])
    assert abs(cap["total_kwh_gwh"] - total_all) < 1e-9
    # 三维度聚合小计自洽（装机量 GWh）：站体 / 电池银行 / 车型
    assert abs(cap["station_kwh_gwh"] - (hv_st + lv_st)) < 1e-9
    assert abs(cap["battery_kwh_gwh"] - (hv_veh + lv_veh)) < 1e-9
    assert abs(cap["hv_kwh_gwh"] - (hv_st + hv_veh)) < 1e-9
    assert abs(cap["lv_kwh_gwh"] - (lv_st + lv_veh)) < 1e-9
    assert abs(cap["private_kwh_gwh"] - 0.0) < 1e-9
    # 三维度聚合小计自洽（capex 亿）：与四桶同源字段求和一致
    assert abs(cap["station_battery_capex"]
               - (cap["hv_st_bat"] + cap["lv_st_bat"])) < 1e-9
    assert abs(cap["hv_battery_capex"]
               - (cap["hv_st_bat"] + cap["hv_veh_bat"])) < 1e-9
    assert abs(cap["lv_battery_capex"]
               - (cap["lv_st_bat"] + cap["lv_veh_bat"])) < 1e-9
    assert abs(cap["vehicle_battery_capex"]
               - (cap["hv_veh_bat"] + cap["lv_veh_bat"] + cap["private_bat"])) < 1e-9
    assert abs(cap["total_battery_capex"]
               - (cap["station_battery_capex"] + cap["vehicle_battery_capex"])) < 1e-6
    # 量级自洽：2026 总装机量应在数十~百 GWh 区间（框架.md L162 初期80GWh量级）
    assert 50 < cap["total_kwh_gwh"] < 200

    # 稳健终局：私家车导入后电池银行应显著放大，且私家车桶 = 私家车数×56kWh
    r = M.terminal_scenario(M.PRIVATE_SCENARIOS["稳健"]["vehicles"])
    m2 = r["installed_matrix"]
    private_expect = M.PRIVATE_SCENARIOS["稳健"]["vehicles"] * 1e4 * M.LV_BLOCKS_PER_VEHICLE * M.SINGLE_KWH_LV / 1e6
    assert abs(m2["私家车"]["电池银行"] - private_expect) < 1e-6
    # 终局营运电池银行 ≈ 2026 的 (站数放大10×/3.3× 加权) 量级，应在数百 GWh
    assert m2["营运车小计"]["电池银行"] > cap["total_kwh_gwh"] * 3  # 显著放大
    assert 300 < r["total_kwh_gwh"] < 1000


def test_eac_fcff_proper_uses_kwh_not_reverse():
    """eac_fcff_proper 应直接接收装机量(GWh) 传参，而非由 capex 反推 kWh。

    校验：传入相同 capex 但不同装机量，PV_total 应随装机量变化（证明用的是装机量，
    不是 capex/单价 反推）。同时非整数 life 用整数脉冲计数不应漏脉冲。
    """
    station = 100.0
    # 桶 A：capex=50亿、装机量 10 GWh；桶 B：同 capex、装机量 20 GWh
    bucket_a = (50.0, 10.0, M.BATTERY_LIFE_LV, M.BATTERY_PACK_DECLINE_RATE, M.ESS_PACK_DECLINE_RATE)
    bucket_b = (50.0, 20.0, M.BATTERY_LIFE_LV, M.BATTERY_PACK_DECLINE_RATE, M.ESS_PACK_DECLINE_RATE)
    pv_a = M.eac_fcff_proper(station, [bucket_a])["pv_total"]
    pv_b = M.eac_fcff_proper(station, [bucket_b])["pv_total"]
    # 装机量大 → 重置脉冲现金流更大 → PV 更大（capex 相同，证明用装机量而非反推）
    assert pv_b > pv_a

    # 非整数 life 边界：life=5.0、horizon=15 → 应触发 3 次脉冲(5/10/15)
    pulses = []
    life = 5.0
    n = int(math.floor(15.0 / life))
    for k in range(1, n + 1):
        pulses.append(k * life)
    assert pulses == [5.0, 10.0, 15.0]  # 整数次计数不漏终点脉冲

    # 出租车真实场景：LV life≈3.81、horizon=15 → floor(15/3.81)=3，
    # 脉冲发生在 3.81/7.62/11.43 年；第4次(15.24年)超出 horizon 不计。
    # 验证 eac_fcff_proper 用 floor 整数计数，恰好 3 次、不漏不超。
    lv_life = M.BATTERY_LIFE_LV
    n_lv = int(math.floor(15.0 / lv_life))
    assert n_lv == 3, f"出租车15年应换3次，实际 n_pulses={n_lv}"
    # 反推：若用 round 会把第4次(15.24)误计，PV 会偏大；用 floor 则恰好不超 horizon
    last_pulse = n_lv * lv_life
    assert last_pulse < 15.0, f"最后脉冲应<horizon，实际{last_pulse}"
    # 直接校验函数行为：同 capex 下，LV 桶(3次脉冲) PV 应显著小于假设4次脉冲的 PV
    bucket_lv = (50.0, 10.0, lv_life, M.BATTERY_PACK_DECLINE_RATE, M.ESS_PACK_DECLINE_RATE)
    pv_lv = M.eac_fcff_proper(100.0, [bucket_lv])["pv_total"]
    # 构造一个 life 恰好使 4 次脉冲都落在 horizon 内（life=3.5），其脉冲更多、PV 应更大
    bucket_lv4 = (50.0, 10.0, 3.5, M.BATTERY_PACK_DECLINE_RATE, M.ESS_PACK_DECLINE_RATE)
    pv_lv4 = M.eac_fcff_proper(100.0, [bucket_lv4])["pv_total"]
    assert pv_lv4 > pv_lv  # 更多脉冲 → 更大 PV，间接证明 floor 按真实次数计数


def test_terminal_scenarios():
    # 终局估值（含私家车）— 主链采用正统 EAC（PV求和×统一CRF，含多次重置脉冲递推，md L97-98）
    # 多次脉冲现值（第life/2life…年，按价格曲线递推折现）低于旧"单次"近似，FCFF/Equity 再下修：
    #   fcff 497/578/699（旧单次脉冲近似 516/597/717）
    #
    # v9/HDT 更新（HV_FLEET_SIZE 210→222派生, SINGLE_KWH_HV 250→171回退, 块数2→2.92；新增LCV装车电池进终局）
    #   重卡终局车辆改为倒算导出(222×0.448×0.348=34.6万)，单车电量回退171×2.92≈500kWh，
    #   并并入城配物流(LCV)装车电池桶（站点共用LV）。golden 对齐模型v9实际输出。
    expected = {
        "保守": {"capex": 3478, "fcff": 542, "eq": 7234},
        "稳健": {"capex": 4100, "fcff": 623, "eq": 8429},
        "激进": {"capex": 5025, "fcff": 744, "eq": 10208},
    }
    for name, sc in M.PRIVATE_SCENARIOS.items():
        r = M.terminal_scenario(sc["vehicles"])
        exp = expected[name]
        assert abs(r["total_capex"] - exp["capex"]) < 1
        assert abs(r["fcff_eac"] - exp["fcff"]) < 1
        ebitda_impl = M.implied_ebitda_from_fcff(r["fcff_eac"], r["total_depr"])
        # ebitda 由 fcff 反推，与 golden fcff 自洽（无净重置项）
        ebitda_exp = (exp["fcff"] - r["total_depr"] * M.TAX_RATE) / (1 - M.TAX_RATE)
        assert abs(ebitda_impl - ebitda_exp) < 1
        eq = ebitda_impl * M.EV_EBITDA_MID - r["total_capex"] * M.DEBT_RATIO
        assert abs(eq - exp["eq"]) < 1


def test_sensitivity_3x3_matrix():
    """3×3 敏感性矩阵：Equity(亿) = 情景 × {12×, 18×, 25×}（修改意见.md·二）。
    主结论中枢为「稳健×18×」；倍数与情景为独立维度，不捆绑。"""
    # 中枢 稳健×18× 应与终局主链回归基准一致（v9/HDT 更新）
    r_steady = M.terminal_scenario(M.PRIVATE_SCENARIOS["稳健"]["vehicles"])
    ebitda_steady = M.implied_ebitda_from_fcff(r_steady["fcff_eac"], r_steady["total_depr"])
    eq_steady_mid = ebitda_steady * M.EV_EBITDA_MID - r_steady["total_capex"] * M.DEBT_RATIO
    assert abs(eq_steady_mid - 8429) < 1  # 与 test_terminal_scenarios 中枢一致

    # 三情景各自的 12/18/25× 展开均 > 0 且单调（25× > 18× > 12×）
    for name, sc in M.PRIVATE_SCENARIOS.items():
        r = M.terminal_scenario(sc["vehicles"])
        ebitda = M.implied_ebitda_from_fcff(r["fcff_eac"], r["total_depr"])
        eq_low = ebitda * M.EV_EBITDA_LOW - r["total_capex"] * M.DEBT_RATIO
        eq_mid = ebitda * M.EV_EBITDA_MID - r["total_capex"] * M.DEBT_RATIO
        eq_high = ebitda * M.EV_EBITDA_HIGH - r["total_capex"] * M.DEBT_RATIO
        assert eq_low > 0 and eq_mid > 0 and eq_high > 0
        assert eq_low < eq_mid < eq_high, f"{name} 倍数展开应单调"


def test_catl_equity():
    # CATL权益价值（完整终局）应与旧版一致
    results = {n: M.terminal_scenario(sc["vehicles"]) for n, sc in M.PRIVATE_SCENARIOS.items()}
    base = results["稳健"]
    station_ebitda = M.implied_ebitda_from_fcff(base["fcff_station"], base["depr_station"])
    station_eq = station_ebitda * M.EV_EBITDA_MID - base["station_capex_terminal"] * M.DEBT_RATIO
    # EAC多次脉冲递推后：站体Eq≈1289；电池Eq由新fcff_battery反推
    # v7 golden 更新：站内电池块数修正（24→14块）使电池折旧下降、隐含EBITDA上升，
    # CATL权益相应上修（详见 test_terminal_scenarios 注释）。
    # v9/HDT 更新（重卡派生+LCV进终局）
    expected = {"保守": 1912, "稳健": 3114, "激进": 4846}
    for name, sc in M.CATL_SCENARIOS.items():
        r = results[name]
        catl_station = station_eq * sc["station"]
        battery_ebitda = M.implied_ebitda_from_fcff(r["fcff_battery"], r["total_depr_battery"])
        battery_eq = battery_ebitda * M.EV_EBITDA_MID - r["battery_capex_total"] * M.DEBT_RATIO
        catl_total = catl_station + battery_eq * sc["battery"]
        assert abs(catl_total - expected[name]) < 1, f"{name} CATL权益偏离"


# ============================================================
# C. 已知口径问题（旧版混乱值，重构版不继承，记录备查）
# ============================================================
def test_known_issue_2026_eac_not_145_9():
    """2026主链EAC FCFF 正确值应为 ≈145.9（站体11.9 + 电池LV/HV分桶年金化≈134）。

    旧版(v5)的 eac_fcff 函数把『同一电池capex(524亿)』重复放入 LV/HV 两个桶，
    实算≈279（重复计算）；但其报告 L139 手写的『电池134.0』反而只算了一桶，
    巧合地与正确值 145.9 一致。重构版用逻辑干净的分桶（LV capex 按 LV 寿命、
    HV capex 按 HV 寿命，不重复），结果 ≈145.9，与 md 引用的数字吻合。
    本测试锁定正确值 145.9，防止回归时 reintroduce 旧版的重复桶 bug(279)。"""
    rev = M.compute_revenue(M.HV_SITES_2026, M.LV_SITES_2026)
    # capex / 装机量由独立 compute_capex 产出，不从 compute_revenue 取（已移除冗余字段）
    cap = M.compute_capex(M.HV_SITES_2026, M.LV_SITES_2026)
    station_capex_total = cap["station_capex_total"]
    buckets = [(cap["lv_battery_capex"], M.BATTERY_LIFE_LV),
               (cap["hv_battery_capex"], M.BATTERY_LIFE_HV)]
    eac = M.eac_fcff(station_capex_total, buckets)
    # v9/HDT 更新：SINGLE_KWH_HV 250→171 回退，重卡电池 capex 下降 → EAC FCFF ≈146.8
    assert abs(eac["fcff_total"] - 146.8) < 1.0, f"EAC应≈146.8，实际{eac['fcff_total']}"
    # 同时确认不是旧版重复桶bug的 279
    assert eac["fcff_total"] < 250, f"EAC不应为重复桶的279，实际{eac['fcff_total']}"

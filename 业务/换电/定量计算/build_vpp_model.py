"""
宁德时代换电业务·能量维度收益计算模型（v9 / HDT 倒算版）

目标：算 **2030 年稳态估值**。2026 只作放大基数与重要性检验锚，不对其估值。
配套文档：《换电框架-能量维度.md》《换电框架.md》

═══════════════════════════════════════════════════════════════════════
一、数据流（DATA FLOW）—— 一张图看懂整个模型怎么算
───────────────────────────────────────────────────────────────────────

  【§1 参数区 CONFIG】所有自变量（站数/车辆/单价/寿命/IRR/倍数…）
        │  全部前置、集中管理，改一处联动全模型
        ▼
  【§2 派生参数 DERIVED】由主参数算出，不可手改
        （终局车辆 mt、初期车辆 m0、放大倍数、CRF、电池寿命）
        │
        ├──────────────── 投入侧（主链，估值只走这条）────────────────┐
        │                                                              │
        ▼                                                              │
  build_asset_bank(站数, 车辆数, 私家车)   ← §4 唯一 CAPEX 口径          │
        │  五桶资产：重卡站内/乘用站内/重卡装车/乘用装车/私家车装车      │
        │  每桶同时产出：装机量(GWh) + CAPEX(亿)，同源但互不反推         │
        ▼                                                              │
  eac_fcff_proper(站体CAPEX, 电池分桶)   ← §5 正统 EAC                  │
        │  PV = 站体 + Σ(电池初始投入 + 各次重置脉冲折现)               │
        │  FCFF_EAC = PV × CRF(7.5%, 15年)                              │
        ▼                                                              │
  implied_ebitda_from_fcff(FCFF, 折旧)   ← §5 反推隐含 EBITDA           │
        │  EBITDA =(FCFF − 折旧×税率)/(1−税率)   【绝不加净重置】        │
        ▼                                                              │
  EV = EBITDA × {12/18/25×} ;  Equity = EV − CAPEX×60%                  │
        │                                                              │
        ▼                                                              │
  CATL权益 = 站体Eq×站自持% + 电池Eq×电池自持%                          │
                                                                       │
        ├──────────────── 收益侧（仅校验，不进主链估值）──────────────┘
        ▼
  compute_revenue(站数)  ← §6 五条收入线正算（套利/服务费/租金/需求响应/调频）
        │  产出 2026 基准 EBITDA 172亿、单站净利（供利用率放大用）
        ▼
  ebitda_check(收益, 资产)  ← §7 经营方校验：FCFF = EBITDA − 税 − 净重置
        （与主链 EAC 交叉验证，差异即「要求回报 vs 实际回报」的 gap）

───────────────────────────────────────────────────────────────────────
二、计算框架（两条链，绝不混用）
───────────────────────────────────────────────────────────────────────
  主链（资本方视角·下沿锚）：CAPEX → EAC → 隐含EBITDA → 市场倍数 → Equity
      · 净重置已在 EAC 的 PV 脉冲里年金化吸收
      · ⇒ 反推 EBITDA 时**绝不能再加净重置**（否则双重计算）
  校验链（经营方视角）：EBITDA正算 → −税 − 净重置 → FCFF
      · 净重置**只在这条链**出现

───────────────────────────────────────────────────────────────────────
三、调用逻辑（本文件自上而下的阅读顺序 = 实际执行顺序）
───────────────────────────────────────────────────────────────────────
  §1  CONFIG        全部自变量参数（改这里）
  §2  DERIVED       派生参数（自动算出）
  §3  UTILS         通用工具函数（crf_for / net_repl_unit_price / mgg）
  §4  ENGINE-资产   build_asset_bank → compute_capex（唯一 CAPEX 口径）
  §5  ENGINE-估值   eac_fcff_proper / implied_ebitda_from_fcff / terminal_scenario
  §6  ENGINE-收益   compute_revenue / util_from_private
  §7  VALIDATE      ebitda_check（校验链）
  §8  REPORT        main() → 按 md 章节顺序逐段打印
                    main 是总入口，先读 main 即知全局，细节再跳转各函数

  执行入口：main()
      ├─ report_params()            参数对齐
      ├─ report_revenue_2026()      → compute_revenue / compute_capex
      ├─ report_ebitda_check()      → ebitda_check
      ├─ report_installed_matrix()  → compute_capex / terminal_scenario
      ├─ report_terminal_valuation()→ terminal_scenario → eac_fcff_proper
      ├─ report_utilization()       → util_from_private
      └─ report_catl_equity()       → implied_ebitda_from_fcff

───────────────────────────────────────────────────────────────────────
四、v7 相对 v6 的修正（逻辑检查结论）
───────────────────────────────────────────────────────────────────────
  [BUG-1] terminal_scenario 里乘用车站内电池误用 HV_BATTERIES_PER_STATION(24块)，
          应为 LV_BATTERIES_PER_STATION(14块)。导致终局站内电池 CAPEX 虚高
          310.5亿（正确 211.4亿，md 2.1节表=212亿）。
          根因：CAPEX 有 compute_capex / terminal_scenario 两套并行代码。
          修复：统一收敛到 build_asset_bank，终局与2026共用同一口径，杜绝再分叉。
  [BUG-2] OPERATING_DEPRECIATION=516 是硬编码的营运折旧，与 CAPEX 脱钩——
          改参数（站数/单价/寿命）时折旧不联动。改为由资产桶实算。
  [BUG-3] compute_revenue 内 station_swaps_hv/lv=140 硬编码在函数体内，
          已提到参数区 BASE_2026_SWAPS_PER_STATION 统一管理。
  [清理]  删除死代码：HV_SITES_2026_to_use（占位空函数）、eac_fcff（已弃用旧法，
          仅 test_model.py 回归用，保留于 §5 末尾并标注）、未使用的 dataclass 导入、
          ratio 自除（x*18/x 恒等于18）等。
═══════════════════════════════════════════════════════════════════════
"""

import math

# ================================================================
# §1 CONFIG —— 全部自变量参数（唯一修改入口，勿在函数内散落硬编码）
# ================================================================

# ---- 1.1 站体 CAPEX（换电框架.md L130）----
STATION_CAPEX_PASSENGER = 200        # 万/座（乘用车/巧克力站）
STATION_CAPEX_HEAVY = 500            # 万/座（重卡/骐骥站）

# ---- 1.2 电池单价（电池价格口径统一与pack价格参考.md 3.2.3）----
BATTERY_PRICE_PER_KWH = 590          # 元/kWh（换电块LFP内部结算价，含制造毛利）
ESS_PACK_PRICE_PER_KWH_Y0 = 586      # 元/kWh（储能Pack售价Y0，与换电块差异<1%）
BATTERY_PACK_DECLINE_RATE = 0.058    # 动力电芯年复合降幅5.8%（BNEF中性）
ESS_PACK_DECLINE_RATE = 0.065        # 储能电芯年复合降幅6.5%（标准化高、降速快）

# ---- 1.3 电池规格与配置（换电框架.md L139-140、L145-146）----
SINGLE_KWH_LV = 56                   # kWh/块（25#，乘用车）
SINGLE_KWH_HV = 171                  # kWh/块（75#，重卡；时代换电标准块，不可调；2026-08-12由250回退）
SINGLE_KWH_LCV = 81                  # kWh/车（城配物流换电版，江淮81度，城配物流电动化.md）
LV_BATTERIES_PER_STATION = 14        # 块/站（乘用车站内周转，标配固定）
HV_BATTERIES_PER_STATION = 24        # 块/站（重卡站内周转）
LV_BLOCKS_PER_VEHICLE = 1            # 块/车（乘用车）
HV_BLOCKS_PER_VEHICLE = 2.92         # 块/车（重卡；500kWh÷171≈2.92，介于2.5~3之间，HDT增量单车500kWh）
LCV_BLOCKS_PER_VEHICLE = 1           # 块/车（城配物流换电，单电池81度）

# ---- 1.4 站数：初期 n0 / 终局 nt（换电框架.md L142-143）----
LV_SITES_2026 = 3000                 # 座
HV_SITES_2026 = 900                  # 座
LV_SITES_TERMINAL = 30000            # 座
HV_SITES_TERMINAL = 3000             # 座

# ---- 1.5 车辆：终局 mt = 保有量×换电占比×CATL份额（换电框架.md L147）----
LV_FLEET_SIZE = 439                  # 万辆（网约300+出租139，交通运输部2026-03）
LV_SWAP_PENETRATION_MT = 0.80        # 换电占比80%
LV_CATL_SHARE_MT = 0.80              # CATL份额80%
# ---- 1.5 重卡（HDT）终局车辆数：倒算推导（对齐 重卡HDT换电规模测算.xlsx，2026-08-12）----
# 自变量（手动输入，来自 Excel + 信源）：
HV_TOTAL_FLEET_2030 = 900          # 万辆，2030重卡保有量（政策目标）
HV_UPDATE_CYCLE = 9                # 年，重卡更新周期（历史8-10年中值）
HV_FORECAST_YEARS = 5              # 2026-2030 预测年数
HV_NEV_PEN_AVG = 0.444             # 2026-2030 NEV平均渗透率（S型曲线2025:0.28→2030:0.5均值）
HV_SWAP_PENETRATION_MT = 0.448     # 增量换电渗透率（a/b/c场景加权：0.38×0.3+0.5×0.5+0.12×0.7）
HV_CATL_SHARE_MT = 0.348           # 增量CATL市占率（a/b/c场景加权：0.38×0.3+0.5×0.3+0.12×0.7）
# 存量（2025已售）自变量：
HV_STOCK_2025_NEV = 23             # 万辆，2025 HDT NEV销量（GGII/第一商用车网22.4~23.11万取中值）
HV_STOCK_SWAP_PEN = 0.30           # 存量换电渗透率（全年6.76万辆）
HV_STOCK_CATL_SHARE = 0.10         # 存量CATL市占率（国电投启源芯动力在管电池推算）
# 推导（应变量）：
#   新能源重卡总销量(2026-2030) = 保有量÷更新周期 × 年数 × NEV平均渗透率
#   HV_FLEET_SIZE（作为 pen×share 分母）= 该总销量
HV_FLEET_SIZE = round(HV_TOTAL_FLEET_2030 / HV_UPDATE_CYCLE * HV_FORECAST_YEARS * HV_NEV_PEN_AVG, 1)  # 222万辆
HV_VEHICLES_STOCK = round(HV_STOCK_2025_NEV * HV_STOCK_SWAP_PEN * HV_STOCK_CATL_SHARE, 1)  # 0.7万辆（存量）

# ---- 1.5b 城配物流（LCV）换电：倒算推导（参考 城配物流电动化.md）----
# 换电站点暂假设与出租车/网约车等乘用车营运车（LV）共用 → 不新增站数、不新增站内周转电池。
# 带【经验假设】者非外部信源，待补。
LCV_FLEET_SIZE = 1200              # 万辆【经验假设·毛估估】城配物流车保有量(轻卡+微卡+轻客用于城配)，非外部信源
LCV_NEV_PEN_2030 = 0.30            # 【经验假设】2030 NEV渗透率(2025约10%拐点，受电池迭代/路权顾虑低于乘用车)
LCV_SWAP_PEN = 0.225               # 城配换电占比(论文区间20-25%中值，城配物流电动化.md)
LCV_CATL_SHARE = 0.60              # 【经验假设】CATL份额(巧克力在城配垄断但竞品存在)
LCV_SWAP_FREQ = 1.5                # 次/车/天【经验假设】高频城配子场景（同乘用营运）
LCV_MONTHLY_RENT = 867             # 元/月【经验假设】81度车电池租金(按56度599元等比≈867)

# 初期渗透率 p：m0 = mt × p（换电框架.md L152-153）
LV_PENETRATION_RATE = 0.20           # 乘用车初期渗透率20%
HV_PENETRATION_RATE = 0.30           # 重卡初期渗透率30%

# ---- 1.6 换电频次（换电框架.md L149，经验值；里程法仅作交叉校验）----
LV_SWAP_FREQ = 1.5                   # 次/车/天
# 里程法校验：450km/天×0.15kWh/km÷(1块×56kWh×80%)=67.5÷44.8=1.51≈1.5 ✓
HV_SWAP_FREQ = 1                     # 次/车/天
# 里程法校验：300km/天×1.2kWh/km÷(2.92块×171kWh×80%)=360÷399.5=0.90≈1.0（取整到1次/天）✓
PRIVATE_CAR_SWAP_FREQ = 0.3          # 次/车/天（日均80km÷44.8kWh≈0.3）
SWAP_EFFECTIVE_RATIO = 0.8           # 换电量系数（用户带20%余电来）
BASE_2026_SWAPS_PER_STATION = 140    # 次/站/天，2026单站基准（苏州106辆/站校验取值）
                                     # 既是利用率分母，也是2026服务费正算的单站频次

# ---- 1.7 运营参数 ----
OPERATING_DAYS = 350                 # 天/年
ARBITRAGE_PRICE = 0.6                # 元/kWh（峰谷价差）
SERVICE_PRICE = 0.4                  # 元/kWh（换电服务费单价）
HV_OPEX_PER_SWAP = 30                # 元/次（行业经验，待补信源）
LV_OPEX_PER_SWAP = 13                # 元/次（行业经验，待补信源）

# ---- 1.8 租金定价（换电框架-能量维度.md 6.4节③）----
LV_MONTHLY_RENT = 599                # 元/月（25#畅行包，56kWh→10.7元/kWh/月）
HV_RENT_PER_KWH_YEARLY = 160         # 元/kWh/年（云南临沧600kWh纯租金7800-8000元/月折算，取保守值）
RENTE_NET_MARGIN = 0.156             # 蔚能净利率15.6%（税后口径）

# ---- 1.9 需求响应 / 调频 VPP ----
HV_DR_CAPACITY = 152                 # kW（重卡站申报容量，链式折扣后）
LV_DR_CAPACITY = 25                  # kW（乘用车站）
DR_PRICE = 15                        # 元/kWh（江苏直控上限）
DR_HOURS = 200                       # 年响应时长(h)
AGC_PRICE_PER_KWH = 0.37             # 元/kWh（AGC调频，行业0.3-0.45中值）
AGC_HOURS_PER_YEAR = 350             # 年利用小时(h)
HV_VPP_CAPACITY = 450                # kW（重卡站满负荷10%保守）
LV_VPP_CAPACITY = 300                # kW（参考蔚来苏州68站单站294kW）

# ---- 1.10 资产寿命与残值 ----
STATION_LIFE_YEARS = 15              # 站体折旧年限
BATTERY_CYCLE_LIFE = 2000            # 电池循环寿命（到80% SOH）
BATTERY_LIFE_PRIVATE_CALENDAR = 10   # 私家车日历寿命约束(年，LFP年衰减1.5-2%)
BATTERY_SOH_RETIRE = 0.80            # 退役时SOH=80%
RESIDUAL_DISCOUNT = 0.60             # 旧电池转储能的二手折扣（保守）

# ---- 1.11 财务与估值参数 ----
IRR = 0.075                          # 目标IRR / WACC 7.5%
TAX_RATE = 0.25                      # 所得税率
DEBT_RATIO = 0.60                    # 债务占CAPEX 60%（Net Debt 账面值口径）
EV_EBITDA_LOW = 12                   # 下沿（纯能源基建，Brookfield）
EV_EBITDA_MID = 18                   # 中枢（能源科技+标准锁定溢价）
EV_EBITDA_HIGH = 25                  # 上沿（宁德科技+数据平台期权）
CATL_NET_INCOME_2026 = 950           # 亿（2026年化归母净利，机构一致预期中值）
CATL_MARKET_CAP = 20000              # 亿（宁德2万亿市值，占比口径）

# ---- 1.12 私家车三情景：终局增量保有量（换电框架-能量维度.md 2.2节）----
# 纯电口径剔除插混；渗透率已内化在 PRIVATE_CAR_SWAP_FREQ 中，故此处只需辆数。
PRIVATE_SCENARIOS = {
    "保守": {"vehicles": 102},       # 万辆，低端0%+中端3%+高端0%（CTC冲击）
    "稳健": {"vehicles": 290},       # 万辆，低端0%+中端5%+高端3%
    "激进": {"vehicles": 570},       # 万辆，低端3%+中端10%+高端5%
}

# ---- 1.13 CATL自持比例（换电框架-能量维度.md 2.3节）----
# 站体因土地/电网需让渡权益；电池银行需控制权，自持更高。
CATL_SCENARIOS = {
    "保守": {"station": 0.10, "battery": 0.30},
    "稳健": {"station": 0.20, "battery": 0.40},
    "激进": {"station": 0.30, "battery": 0.50},
}

# ---- 1.14 2030 稳态利用率情景（换电框架-能量维度.md L210-214）----
# 仅终局三情景有私家车渗透锚，不推算2027/2028。
# 重卡站利用率恒 1.0×；乘用车站利用率 = util_from_private(私家车万辆)。
HV_TERMINAL_UTIL = 1.0               # 重卡站终局利用率（车辆密度不变）
TERMINAL_UTIL_SCENARIOS = [
    {"label": "2030保守", "private_wan": PRIVATE_SCENARIOS["保守"]["vehicles"],
     "catl_ni": 950, "src": "私家车数量用于乘用车站利用率推导，净利950经验外推"},
    {"label": "2030稳健", "private_wan": PRIVATE_SCENARIOS["稳健"]["vehicles"],
     "catl_ni": 1100, "src": "私家车数量用于乘用车站利用率推导，净利1100经验外推"},
    {"label": "2030激进", "private_wan": PRIVATE_SCENARIOS["激进"]["vehicles"],
     "catl_ni": 1300, "src": "私家车数量用于乘用车站利用率推导，净利1300经验外推"},
]

# ---- 1.15 收益侧净利率/EBITDA率假设（换电框架-能量维度.md 6.4节）----
ARBITRAGE_EBITDA_MARGIN = 0.95       # 峰谷套利EBITDA率95%
DR_EBITDA_MARGIN = 1.00              # 需求响应EBITDA率100%（opex≈0）
VPP_EBITDA_MARGIN = 0.80             # 调频VPP EBITDA率80%（边际成本低）

# ---- 1.16 单位换算常量 ----
WAN = 1e4                            # 万
YI = 1e8                             # 亿
GWH_IN_KWH = 1e6                     # 1 GWh = 1e6 kWh

# ================================================================
# §2 DERIVED —— 派生参数（由 §1 自动算出，勿手改）
# ================================================================
# 终局车辆 mt = 保有量 × 换电占比 × CATL份额（换电框架.md L147）
LV_VEHICLES_MT = round(LV_FLEET_SIZE * LV_SWAP_PENETRATION_MT * LV_CATL_SHARE_MT, 1)  # 439×0.8×0.8=281.0万
# 重卡：HV_FLEET_SIZE=222(新能源重卡总销量) × 0.448 × 0.348 = 34.6万（增量；Excel整数35）
HV_VEHICLES_MT = round(HV_FLEET_SIZE * HV_SWAP_PENETRATION_MT * HV_CATL_SHARE_MT, 1)  # 222×0.448×0.348=34.6万

# 城配物流（LCV）终局换电车辆 = 城配保有量 × NEV渗透率 × 换电占比 × CATL份额（站点共用LV）
LCV_VEHICLES_MT = round(LCV_FLEET_SIZE * LCV_NEV_PEN_2030 * LCV_SWAP_PEN * LCV_CATL_SHARE, 1)

# 初期车辆 m0 = mt × p（换电框架.md L153）
LV_VEHICLES_M0 = round(LV_VEHICLES_MT * LV_PENETRATION_RATE, 1)    # 56.2万辆
HV_VEHICLES_M0 = round(HV_VEHICLES_MT * HV_PENETRATION_RATE, 1)    # 34.6×0.3=10.4万辆
LCV_VEHICLES_M0 = round(LCV_VEHICLES_MT * LV_PENETRATION_RATE, 1)  # 初期按乘用车渗透率近似

# 放大倍数 2026→2030（换电框架.md L198）
AMP_LV_STATION = LV_SITES_TERMINAL / LV_SITES_2026        # 3000→30000 = 10×
AMP_LV_VEHICLE = LV_VEHICLES_MT / LV_VEHICLES_M0          # 56→281万 = 5×
AMP_HV = HV_SITES_TERMINAL / HV_SITES_2026                # 900→3000 = 3.33×

# 资本回收系数 CRF(7.5%, 15年) = 0.1134（换电框架.md L108）
CRF = IRR / (1 - (1 + IRR) ** (-STATION_LIFE_YEARS))

# 电池折旧年限 = 循环寿命 ÷ 年换电次数
# 营运车按实际使用强度（SOH掉到80%退役）；私家车受日历寿命封顶。
BATTERY_LIFE_LV = BATTERY_CYCLE_LIFE / (LV_SWAP_FREQ * OPERATING_DAYS)       # ≈3.8年
BATTERY_LIFE_HV = BATTERY_CYCLE_LIFE / (HV_SWAP_FREQ * OPERATING_DAYS)       # ≈5.7年
BATTERY_LIFE_PRIVATE_CYCLE = BATTERY_CYCLE_LIFE / (PRIVATE_CAR_SWAP_FREQ * OPERATING_DAYS)  # ≈19年
BATTERY_LIFE_PRIVATE = min(BATTERY_LIFE_PRIVATE_CYCLE, BATTERY_LIFE_PRIVATE_CALENDAR)       # =10年
BATTERY_LIFE_LCV = BATTERY_CYCLE_LIFE / (LCV_SWAP_FREQ * OPERATING_DAYS)   # ≈3.8年（同乘用营运强度）

# 权威信源索引（供查证；满足可点击链接纪律）
SOURCES = {
    "巧克力换电月租官方价格(2024生态大会)":
        "https://www.163.com/dy/article/J0IEUN3L0519BMQA.html (今日头条,2026-6最新)",
    "巧克力换电电池规格(20#/25#)":
        "https://www.bjnews.com.cn/detail/1734696712129843.html (新京报)",
    "重卡电池租金(云南临沧600kWh纯租金7800-8000元/月)":
        "http://m.toutiao.com/group/7661896244545028650/ (头条)",
    "重卡电池租金(博研咨询600kWh月均5800元)":
        "https://www.docin.com/touch_new/preview_new.do?id=4934598304 (2026年锂电池租赁行业报告)",
    "重卡电池租金(经济观察报282kWh月租7000-8000元)":
        "https://www.cnenergynews.cn/article/4S7sTLlAo5j (经济观察报,2026-06-25)",
    "银川套餐(含电费,非纯租金,勿用)":
        "https://www.yoojia.com/article/10138959687614316498.html (有驾,2026-04-16) 套餐6000元含21000度电=电费+租金打包",
    "骐骥513度电池长租方案":
        "https://k.sina.com.cn/article_5182171545_134e1a9990200249cg.html (新浪)",
    "重庆样板站(52站/5500辆车)":
        "https://aitalo.com/index.php/2025/12/31/... (2024年底数据)",
    "国电投启源芯动力168次/天":
        "https://www.360che.com/news/250516/196952.html (卡车之家)",
    "苏州相城巧克力站(14仓/500kW/800次天)":
        "https://www.suzhou.gov.cn/.../a7073a928a6a4ea6af0f99997aa1ad03.shtml (苏州市政府)",
    "青海西宁站(1250kW/18车企)":
        "https://sft.qinghai.gov.cn/szfxx/content_95146 (青海省司法厅)",
    "深圳站(14仓/80kW每仓)":
        "https://www.360che.com/news/... (广东石油)",
    "全国统一电力市场意见(容量电价)":
        "https://www.gov.cn/gongbao/2026/issue_12586/202602/content_7059937.html",
    "江苏负荷快速响应(直控15元/kWh)":
        "https://fzggw.jiangsu.gov.cn/art/2026/6/2/art_51007_11779314.html (苏发改规发〔2026〕1号)",
    "浙江虚拟电厂(容量1元/kW·月)":
        "http://www.cnnes.cc/hangye/20250608/10914.html (储能中国网,引浙江发改委)",
    "浙江市场化电力响应细则":
        "https://www.zj.sgcc.com.cn/p1/2c9489129372599e019757c9181461be.html (国网浙江)",
    "四川需求侧响应(2026)":
        "https://fgw.sc.gov.cn/sfgw/tzgg/2026/6/18/... (川发改能源〔2026〕232号)",
    "江西需求响应(削峰3元/kWh)":
        "https://www.163.com/dy/article/L2CH20J105568W0A.html (北极星电力市场网)",
    "云南需求响应(24元/kW·次)":
        "https://www.163.com/dy/article/L2CH20J105568W0A.html (北极星)",
    "重卡换电站变压器(630~2500kVA)":
        "https://www.cnboda.cn/p/230.html + http://mp.weixin.qq.com/s?... (充换电研究院)",
    "巧克力站单仓80kW(官方)":
        "https://www.suzhou.gov.cn + https://k.sina.com.cn (广东石油)",
    "苏州换电虚拟电厂(68站VPP实测)":
        "https://www.suzhou.gov.cn/szsrmzf/szyw/202503/a60985e397184d0c9fbfb424db962de1.shtml",
    "超换一体站(2026超级科技日)":
        "https://www.qichejingwei.com/article-24830.html (汽车经纬网)",
    "蔚能2025财报(净利率15.6%)":
        "腾讯网/财联社：蔚能电池REITs全球首发；今日头条：武汉蔚能服务超55万用户",
}


# ================================================================
# §3 UTILS —— 通用工具函数（紧跟参数区，供后续所有计算复用）
# ================================================================
def mgg(x):
    """毛估估：保留1位小数（大额单位 万/百万/千万/亿 统一1位小数）。"""
    return round(x, 1)


def crf_for(rate, life):
    """资本回收系数 CRF(i, n) = i / (1 − (1+i)^−n)。"""
    return rate / (1 - (1 + rate) ** (-life))


def kwh_to_capex_yi(kwh_total, price_per_kwh=BATTERY_PRICE_PER_KWH):
    """装机量(kWh) → CAPEX(亿)。"""
    return kwh_total * price_per_kwh / YI


def net_repl_unit_price(year, decline_rate=BATTERY_PACK_DECLINE_RATE,
                        ess_decline_rate=ESS_PACK_DECLINE_RATE):
    """第 year 年末退役时的每 kWh 净重置价（元/kWh）。

    净重置 = 新电池价 − 旧电池转储能残值：
      · 新电池价(year) = 动力价 × (1−动力降幅)^year
      · 残值(year)     = 储能价 × (1−储能降幅)^year × SOH80% × 处置折扣60%
    供 EAC 重置脉冲（§5）与 EBITDA 校验（§7）共用，保证两条链口径一致。
    """
    new_batt = BATTERY_PRICE_PER_KWH * (1 - decline_rate) ** year
    residual = (ESS_PACK_PRICE_PER_KWH_Y0 * (1 - ess_decline_rate) ** year
                * BATTERY_SOH_RETIRE * RESIDUAL_DISCOUNT)
    return new_batt - residual

# ================================================================
# §4 ENGINE·资产 —— CAPEX 与装机量的【唯一】计算口径
# ================================================================
# 设计要点（v7 修复 BUG-1）：
#   v6 有 compute_capex（2026用）与 terminal_scenario（终局用）两套并行的
#   CAPEX 代码，终局那套把乘用车站内电池块数误写成 HV_BATTERIES_PER_STATION(24)，
#   导致站内电池 CAPEX 虚高 99亿。现全部收敛到 build_asset_bank 一个函数，
#   2026 与终局只是传参不同，从结构上杜绝口径分叉。
# ----------------------------------------------------------------
def build_asset_bank(hv_sites, lv_sites, hv_vehicles_wan, lv_vehicles_wan,
                     private_vehicles_wan=0.0, lcv_vehicles_wan=0.0):
    """构造资产桶（装机量 GWh + CAPEX 亿），是全模型 CAPEX 的唯一来源。

    桶 = 车型(重卡/乘用营运/城配物流/私家车) × 维度(站体周转电池/电池银行装车电池)，
    其中私家车与城配物流无专属站体（城配物流站点与乘用营运车 LV 共用）。

    口径（同源但互不反推，避免浮点误差）：
      · 站体桶装机量(kWh) = 站数 × 单站块数 × 单块kWh
      · 装车桶装机量(kWh) = 车辆数(万) × 1e4 × 单车块数 × 单块kWh
      · CAPEX(亿)         = 装机量(kWh) × 590元/kWh ÷ 1e8

    参数单位：站数=座；车辆数=万辆。
    返回：{桶名: {"gwh": 装机量, "capex": CAPEX亿, "life": 折旧年限}}
    """
    def bucket(kwh, life):
        return {"gwh": kwh / GWH_IN_KWH, "capex": kwh_to_capex_yi(kwh), "life": life}

    return {
        # 站体周转电池（站内备用块）
        "重卡站内": bucket(hv_sites * HV_BATTERIES_PER_STATION * SINGLE_KWH_HV,
                           BATTERY_LIFE_HV),
        "乘用站内": bucket(lv_sites * LV_BATTERIES_PER_STATION * SINGLE_KWH_LV,
                           BATTERY_LIFE_LV),   # ← BUG-1 修复点：14块，非24块
        # 电池银行装车电池（在车运行块）
        "重卡装车": bucket(hv_vehicles_wan * WAN * HV_BLOCKS_PER_VEHICLE * SINGLE_KWH_HV,
                           BATTERY_LIFE_HV),
        "乘用装车": bucket(lv_vehicles_wan * WAN * LV_BLOCKS_PER_VEHICLE * SINGLE_KWH_LV,
                           BATTERY_LIFE_LV),
        "城配装车": bucket(lcv_vehicles_wan * WAN * LCV_BLOCKS_PER_VEHICLE * SINGLE_KWH_LCV,
                           BATTERY_LIFE_LCV),  # 城配物流换电装车电池（站点共用LV）
        "私家装车": bucket(private_vehicles_wan * WAN * LV_BLOCKS_PER_VEHICLE * SINGLE_KWH_LV,
                           BATTERY_LIFE_PRIVATE),
    }


def station_capex_of(hv_sites, lv_sites):
    """站体（土建+设备）CAPEX（亿），与电池无关。"""
    return (hv_sites * STATION_CAPEX_HEAVY + lv_sites * STATION_CAPEX_PASSENGER) / WAN


def build_installed_matrix(bank):
    """由五桶资产构造 3×2 装机量矩阵（车型 × {站体, 电池银行}）+ 小计。

    小计口径（md L154）：
      · 营运车小计 = 重卡 + 乘用营运
      · 乘用车小计 = 乘用营运 + 私家车
    """
    m = {
        "重卡":     {"站体": bank["重卡站内"]["gwh"], "电池银行": bank["重卡装车"]["gwh"]},
        "乘用营运": {"站体": bank["乘用站内"]["gwh"], "电池银行": bank["乘用装车"]["gwh"]},
        "城配物流": {"站体": 0.0,                     "电池银行": bank["城配装车"]["gwh"]},
        "私家车":   {"站体": 0.0,                     "电池银行": bank["私家装车"]["gwh"]},
    }
    m["营运车小计"] = {
        "站体": m["重卡"]["站体"] + m["乘用营运"]["站体"] + m["城配物流"]["站体"],
        "电池银行": m["重卡"]["电池银行"] + m["乘用营运"]["电池银行"] + m["城配物流"]["电池银行"],
    }
    m["乘用车小计"] = {
        "站体": m["乘用营运"]["站体"] + m["私家车"]["站体"],
        "电池银行": m["乘用营运"]["电池银行"] + m["私家车"]["电池银行"],
    }
    return m


def battery_depreciation_of(bank, keys=None):
    """电池年折旧（亿）= Σ 各桶 CAPEX ÷ 该桶折旧年限。

    v7 修复 BUG-2：v6 用硬编码 OPERATING_DEPRECIATION=516，改参数不联动；
    现由资产桶实算，站数/单价/寿命任一变动都会自动传导。
    """
    keys = keys or list(bank.keys())
    return sum(bank[k]["capex"] / bank[k]["life"] for k in keys if bank[k]["life"] > 0)


def compute_capex(hv_sites, lv_sites, private_vehicles=0,
                  hv_vehicles_wan=None, lv_vehicles_wan=None, lcv_vehicles_wan=None):
    """CAPEX + 装机量聚合视图（对外稳定接口，供 report / test / 校验链取用）。

    默认用 2026 初期车辆 m0；传 hv/lv/lcv_vehicles_wan 可切换到终局 mt。
    主链数据流：compute_capex → eac_fcff_proper / ebitda_check。

    返回含：六桶 capex 与装机量、站体CAPEX、维度/车型聚合小计、3×2 矩阵。
    """
    hv_veh = HV_VEHICLES_M0 if hv_vehicles_wan is None else hv_vehicles_wan
    lv_veh = LV_VEHICLES_M0 if lv_vehicles_wan is None else lv_vehicles_wan
    lcv_veh = 0.0 if lcv_vehicles_wan is None else lcv_vehicles_wan  # 2026基准不含LCV；终局由terminal_scenario显式传入
    bank = build_asset_bank(hv_sites, lv_sites, hv_veh, lv_veh, private_vehicles, lcv_veh)

    hv_st, lv_st = bank["重卡站内"], bank["乘用站内"]
    hv_vh, lv_vh, lcv_vh, pv = bank["重卡装车"], bank["乘用装车"], bank["城配装车"], bank["私家装车"]

    station_battery_capex = hv_st["capex"] + lv_st["capex"]
    vehicle_battery_capex = hv_vh["capex"] + lv_vh["capex"] + lcv_vh["capex"] + pv["capex"]

    return {
        "bank": bank,
        # ---- 站体 CAPEX（亿，与电池无关）----
        "station_capex_total": station_capex_of(hv_sites, lv_sites),
        # ---- 电池 capex 聚合（亿）----
        "station_battery_capex": station_battery_capex,
        "vehicle_battery_capex": vehicle_battery_capex,
        "total_battery_capex": station_battery_capex + vehicle_battery_capex,
        "lv_battery_capex": lv_st["capex"] + lv_vh["capex"],
        "hv_battery_capex": hv_st["capex"] + hv_vh["capex"],
        "lcv_battery_capex": lcv_vh["capex"],
        "private_bat": pv["capex"],
        # ---- 六桶 capex（折旧/年金化直接取用）----
        "hv_st_bat": hv_st["capex"], "lv_st_bat": lv_st["capex"],
        "hv_veh_bat": hv_vh["capex"], "lv_veh_bat": lv_vh["capex"],
        "lcv_veh_bat": lcv_vh["capex"],
        # ---- 装机量聚合（GWh）----
        "station_kwh_gwh": hv_st["gwh"] + lv_st["gwh"],
        "battery_kwh_gwh": hv_vh["gwh"] + lv_vh["gwh"] + lcv_vh["gwh"] + pv["gwh"],
        "lv_kwh_gwh": lv_st["gwh"] + lv_vh["gwh"],
        "hv_kwh_gwh": hv_st["gwh"] + hv_vh["gwh"],
        "lcv_kwh_gwh": lcv_vh["gwh"],
        "private_kwh_gwh": pv["gwh"],
        "total_kwh_gwh": (hv_st["gwh"] + lv_st["gwh"]
                          + hv_vh["gwh"] + lv_vh["gwh"] + lcv_vh["gwh"] + pv["gwh"]),
        # ---- 六桶装机量（GWh）----
        "hv_st_kwh_gwh": hv_st["gwh"], "lv_st_kwh_gwh": lv_st["gwh"],
        "hv_veh_kwh_gwh": hv_vh["gwh"], "lv_veh_kwh_gwh": lv_vh["gwh"],
        "lcv_veh_kwh_gwh": lcv_vh["gwh"],
        # ---- 3×2 装机量矩阵 ----
        "installed_matrix": build_installed_matrix(bank),
    }


# ================================================================
# §5 ENGINE·估值 —— 主链：EAC → 隐含EBITDA → 市场倍数
# ================================================================
def eac_fcff_proper(station_capex, battery_buckets, horizon=STATION_LIFE_YEARS):
    """正统 EAC（md L97-98）：先按发生时点折现求 PV 总和，再整体 × 统一 CRF。

    = 年金化初始投资（等额本息思维）+ 折现叠加维持性脉冲（脉冲思维）。

    站体 t=0 一次投入、期内无更新；电池分桶，除 t=0 初始投入外，还在第
    life、2×life、… (≤horizon) 年发生重置脉冲（换电池）。每次脉冲现金流 =
    该桶装机量(GWh)×1e6 × net_repl_unit_price(t) ÷ 1e8（亿），折现到 t=0 累加。

    battery_buckets: [(capex亿, gwh装机量, life年), ...]
      · 装机量直接传入、不由 capex 反推（反推有浮点误差，且装机量本身是业务指标）
      · 脉冲次数 n = floor(horizon/life)，用 floor 而非 round 是为避开 life 非整数
        （LV≈3.81/HV≈5.71）时的边界歧义，确保不把超出 horizon 的那次重置计入
      · 兼容旧的 5 元组 (capex, gwh, life, decline_rate, ess_decline_rate)：
        降幅参数现已统一在 §1 参数区，多余项会被忽略（保证既有调用不报错）

    返回 dict(fcff_station, fcff_battery, fcff_total, pv_total, pv_station, pv_battery)
    """
    pv_station = station_capex                    # 站体：仅 t=0
    pv_battery = 0.0
    for bucket in battery_buckets:
        capex, gwh, life = bucket[0], bucket[1], bucket[2]
        if life <= 0:
            continue
        pv_battery += capex                       # 初始投入 t=0
        kwh_total = gwh * GWH_IN_KWH
        n_pulses = int(math.floor(horizon / life))
        for k in range(1, n_pulses + 1):
            t = k * life
            repl_cash = kwh_total * net_repl_unit_price(t) / YI   # 亿
            pv_battery += repl_cash / (1 + IRR) ** t
    pv_total = pv_station + pv_battery
    crf = crf_for(IRR, horizon)
    return {
        "fcff_station": pv_station * crf,
        "fcff_battery": pv_battery * crf,
        "fcff_total": pv_total * crf,
        "pv_total": pv_total,
        "pv_station": pv_station,
        "pv_battery": pv_battery,
    }


def implied_ebitda_from_fcff(fcff, total_depr):
    """主链反推隐含 EBITDA = (FCFF − 折旧×税率)/(1−税率)。

    ⚠ 无净重置项：净重置已在 EAC 的 PV 脉冲中年金化吸收，再加一次即双重计算。
    折旧在此仅作税盾桥接（非付现），与净重置无关。
    """
    return (fcff - total_depr * TAX_RATE) / (1 - TAX_RATE)


def terminal_scenario(private_vehicles):
    """【终局估值主链】2030 稳态，给定私家车保有量（万辆）算出全套投入侧指标。

    调用链：build_asset_bank → eac_fcff_proper → (report 侧再反推EBITDA/EV/Equity)

    分两条 EAC 线（站体与电池银行是两个不同投资主体，Equity 必须分列）：
      · 站体：30000 乘用站 + 3000 重卡站，按 15 年年金化
      · 电池银行：LV(3.8年)/HV(5.7年)/私家车(10年) 三桶，各含重置脉冲
    私家车只增装车电池 CAPEX（站数已固定，站体是"免费期权"）。
    """
    # ---- ① 资产桶（终局车辆用 mt，站数用终局站数；城配物流站点共用 LV，仅增装车电池）----
    bank = build_asset_bank(HV_SITES_TERMINAL, LV_SITES_TERMINAL,
                            HV_VEHICLES_MT, LV_VEHICLES_MT, private_vehicles, LCV_VEHICLES_MT)
    station_capex_terminal = station_capex_of(HV_SITES_TERMINAL, LV_SITES_TERMINAL)

    station_battery_operating = bank["重卡站内"]["capex"] + bank["乘用站内"]["capex"]
    vehicle_battery_operating = (bank["重卡装车"]["capex"] + bank["乘用装车"]["capex"]
                                 + bank["城配装车"]["capex"])
    battery_capex_operating = station_battery_operating + vehicle_battery_operating
    battery_capex_private = bank["私家装车"]["capex"]
    battery_capex_total = battery_capex_operating + battery_capex_private

    # ---- ② 电池分桶（按寿命归并：LV+城配 / HV / 私家车）----
    battery_buckets = [
        (bank["乘用站内"]["capex"] + bank["乘用装车"]["capex"] + bank["城配装车"]["capex"],
         bank["乘用站内"]["gwh"] + bank["乘用装车"]["gwh"] + bank["城配装车"]["gwh"], BATTERY_LIFE_LV),
        (bank["重卡站内"]["capex"] + bank["重卡装车"]["capex"],
         bank["重卡站内"]["gwh"] + bank["重卡装车"]["gwh"], BATTERY_LIFE_HV),
        (battery_capex_private, bank["私家装车"]["gwh"], BATTERY_LIFE_PRIVATE),
    ]

    # ---- ③ EAC 主链 ----
    eac = eac_fcff_proper(station_capex_terminal, battery_buckets)

    # ---- ④ 折旧（BUG-2 修复：由资产桶实算，不再硬编码 516）----
    depr_station = station_capex_terminal / STATION_LIFE_YEARS
    operating_depr = battery_depreciation_of(
        bank, ["重卡站内", "乘用站内", "重卡装车", "乘用装车", "城配装车"])
    private_depr = battery_depreciation_of(bank, ["私家装车"])
    total_depr_battery = operating_depr + private_depr

    return {
        "private_vehicles": private_vehicles,
        "bank": bank,
        # CAPEX
        "station_capex_terminal": station_capex_terminal,
        "station_battery_operating": station_battery_operating,
        "vehicle_battery_operating": vehicle_battery_operating,
        "battery_capex_operating": battery_capex_operating,
        "battery_capex_private": battery_capex_private,
        "battery_capex_total": battery_capex_total,
        "total_capex": station_capex_terminal + battery_capex_total,
        # 装机量
        "installed_matrix": build_installed_matrix(bank),
        "total_kwh_gwh": sum(b["gwh"] for b in bank.values()),
        # EAC 产出
        "fcff_station": eac["fcff_station"],
        "fcff_battery": eac["fcff_battery"],
        "fcff_eac": eac["fcff_total"],
        "pv_total": eac["pv_total"],
        # 折旧
        "depr_station": depr_station,
        "operating_depr": operating_depr,
        "private_depr": private_depr,
        "total_depr_battery": total_depr_battery,
        "total_depr": depr_station + total_depr_battery,
    }


def eac_fcff(station_capex, battery_buckets):
    """【已弃用·仅供回归测试】简化 EAC：各桶按自身寿命直接年金化后求和。

    未考虑未来重置脉冲的现值处理，故低估资本要求；现行主链是 eac_fcff_proper。
    保留原因：test_model.py 用它锁定"分桶不重复"逻辑（防止 reintroduce
    旧版把同一 capex 重复放入 LV/HV 两桶的 bug）。不参与任何报告输出。

    battery_buckets: [(capex亿, life年), ...]
    """
    fcff_station = station_capex * crf_for(IRR, STATION_LIFE_YEARS)
    fcff_battery = sum(c * crf_for(IRR, life) for c, life in battery_buckets if life > 0)
    return {
        "fcff_station": fcff_station,
        "fcff_battery": fcff_battery,
        "fcff_total": fcff_station + fcff_battery,
    }

# ================================================================
# §6 ENGINE·收益 —— 2026 基准五条收入线（仅作放大基数与校验，不进主链估值）
# ================================================================
def util_from_private(private_wan):
    """乘用车站利用率（换电框架-能量维度.md L192-214，替代旧 2.8× 魔术数字）。

    含义：私家车加入后，乘用车站单站换电次数相对 2026 基准(140次/天)的放大倍数。
      · 总车辆(万)   = LV_VEHICLES_MT + 私家车
      · 单站车辆     = 总车辆 / (乘用车站数/1e4)
      · 加权频次     = (营运车×1.5 + 私家车×0.3) / 总车辆
      · 单站换电/天  = 单站车辆 × 加权频次
      · 利用率       = 单站换电 / 140
    校验：private_wan=0 时 → 281/3≈93.7辆/站 ×1.5 = 140.6 → ≈1.0×（与基准自洽）。

    ⚠ 仅适用于 2030 稳态三情景（md L210-214）；2027/2028 无私家车渗透锚，不可外推。
    """
    total_cars = LV_VEHICLES_MT + private_wan
    cars_per_station = total_cars / (LV_SITES_TERMINAL / WAN)
    weighted_freq = (LV_VEHICLES_MT * LV_SWAP_FREQ
                     + private_wan * PRIVATE_CAR_SWAP_FREQ) / total_cars
    return cars_per_station * weighted_freq / BASE_2026_SWAPS_PER_STATION


def compute_revenue(hv_sites, lv_sites):
    """2026 基准收益正算（5条收入线），返回结构化 dict。

    口径统一为税后净利；EBITDA 按各业务规则倒推（详见 md 6.1/6.3 节口径说明）：
      ① 峰谷套利   ：EBITDA率95%，无折旧
      ② 换电服务费 ：收入−opex=EBITDA，再扣【仅站体折旧】后计税（站内电池折旧
                     归电池租金业务，避免与蔚能15.6%口径双重扣减）
      ③ 电池租金   ：蔚能15.6%已是税后净利率 → 倒推 EBITDA = 净利/0.75 + 全部电池折旧
      ④ 需求响应   ：EBITDA率100%（opex≈0）
      ⑤ 调频VPP    ：EBITDA率80%

    私家车不计入 2026 基准（终局由 terminal_scenario 处理）。
    """
    swap_kwh_hv = SINGLE_KWH_HV * SWAP_EFFECTIVE_RATIO      # 单次换电量 136.8 kWh
    swap_kwh_lv = SINGLE_KWH_LV * SWAP_EFFECTIVE_RATIO      # 单次换电量 44.8 kWh
    swaps = BASE_2026_SWAPS_PER_STATION                     # BUG-3 修复：不再函数内硬编码140

    # ---- ① 峰谷套利：单站日套利电量 = 站内块数 × 单块 × 80% ----
    arb_hv = (hv_sites * HV_BATTERIES_PER_STATION * SINGLE_KWH_HV * SWAP_EFFECTIVE_RATIO
              * OPERATING_DAYS * ARBITRAGE_PRICE) / YI
    arb_lv = (lv_sites * LV_BATTERIES_PER_STATION * SINGLE_KWH_LV * SWAP_EFFECTIVE_RATIO
              * OPERATING_DAYS * ARBITRAGE_PRICE) / YI
    total_arb = arb_hv + arb_lv
    arb_ebitda = total_arb * ARBITRAGE_EBITDA_MARGIN
    arb_profit = arb_ebitda * (1 - TAX_RATE)

    # ---- ② 换电服务费：单站年换电量 = 140次/天 × 单次换电量 × 350天 ----
    svc_hv = hv_sites * swaps * swap_kwh_hv * SERVICE_PRICE * OPERATING_DAYS / YI
    svc_lv = lv_sites * swaps * swap_kwh_lv * SERVICE_PRICE * OPERATING_DAYS / YI
    total_service = svc_hv + svc_lv
    total_opex = (hv_sites * swaps * OPERATING_DAYS * HV_OPEX_PER_SWAP
                  + lv_sites * swaps * OPERATING_DAYS * LV_OPEX_PER_SWAP) / YI
    station_dep = station_capex_of(hv_sites, lv_sites) / STATION_LIFE_YEARS
    service_ebitda = total_service - total_opex
    service_profit = (service_ebitda - station_dep) * (1 - TAX_RATE)   # 站体折旧作税盾

    # ---- ③ 电池租金（车主租金 + 站内租金）----
    lv_rent_annual = LV_MONTHLY_RENT * 12                              # 7188元/车/年
    hv_rent_block = SINGLE_KWH_HV * HV_RENT_PER_KWH_YEARLY             # 27360元/块/年
    lv_owner = LV_VEHICLES_M0 * WAN * lv_rent_annual / YI
    hv_owner = HV_VEHICLES_M0 * WAN * HV_BLOCKS_PER_VEHICLE * hv_rent_block / YI
    lv_station_rent = lv_sites * LV_BATTERIES_PER_STATION * lv_rent_annual / YI
    hv_station_rent = hv_sites * HV_BATTERIES_PER_STATION * hv_rent_block / YI
    total_rent = lv_owner + hv_owner + lv_station_rent + hv_station_rent
    rent_profit = total_rent * RENTE_NET_MARGIN

    # ---- ④ 需求响应：申报容量 × 容量电价 × 年响应时长 ----
    dr_hv = hv_sites * HV_DR_CAPACITY * DR_HOURS * DR_PRICE / YI
    dr_lv = lv_sites * LV_DR_CAPACITY * DR_HOURS * DR_PRICE / YI
    total_dr = dr_hv + dr_lv
    dr_ebitda = total_dr * DR_EBITDA_MARGIN
    dr_profit = dr_ebitda * (1 - TAX_RATE)

    # ---- ⑤ 调频 VPP：可申报容量 × 年利用小时 × 调频价 ----
    vpp_hv = hv_sites * HV_VPP_CAPACITY * AGC_HOURS_PER_YEAR * AGC_PRICE_PER_KWH / YI
    vpp_lv = lv_sites * LV_VPP_CAPACITY * AGC_HOURS_PER_YEAR * AGC_PRICE_PER_KWH / YI
    total_vpp = vpp_hv + vpp_lv
    vpp_ebitda = total_vpp * VPP_EBITDA_MARGIN
    vpp_profit = vpp_ebitda * (1 - TAX_RATE)

    # ---- 折旧（CAPEX 口径统一取自 §4 资产桶）----
    bank = build_asset_bank(hv_sites, lv_sites, HV_VEHICLES_M0, LV_VEHICLES_M0)
    battery_depreciation = battery_depreciation_of(bank)

    # ---- 汇总：电池租金 EBITDA 倒推需加回全部电池折旧（蔚能净利率已含折旧+税）----
    rent_ebitda = rent_profit / (1 - TAX_RATE) + battery_depreciation
    total_revenue = total_arb + total_service + total_rent + total_dr + total_vpp
    total_ebitda = arb_ebitda + service_ebitda + rent_ebitda + dr_ebitda + vpp_ebitda
    total_profit = arb_profit + service_profit + rent_profit + dr_profit + vpp_profit

    # ---- 单站净利（供终局利用率放大用）：按各业务在车型间的收入占比分摊 ----
    hv_rent_share = (hv_owner + hv_station_rent) / total_rent
    lv_rent_share = (lv_owner + lv_station_rent) / total_rent
    hv_profit = (arb_profit * arb_hv / total_arb + service_profit * svc_hv / total_service
                 + rent_profit * hv_rent_share + dr_profit * dr_hv / total_dr
                 + vpp_profit * vpp_hv / total_vpp)
    lv_profit = (arb_profit * arb_lv / total_arb + service_profit * svc_lv / total_service
                 + rent_profit * lv_rent_share + dr_profit * dr_lv / total_dr
                 + vpp_profit * vpp_lv / total_vpp)

    return {
        "hv_sites": hv_sites, "lv_sites": lv_sites,
        "arb": {"revenue": total_arb, "ebitda": arb_ebitda, "profit": arb_profit},
        "service": {"revenue": total_service, "ebitda": service_ebitda, "profit": service_profit},
        "rent": {"revenue": total_rent, "ebitda": rent_ebitda, "profit": rent_profit},
        "dr": {"revenue": total_dr, "ebitda": dr_ebitda, "profit": dr_profit},
        "vpp": {"revenue": total_vpp, "ebitda": vpp_ebitda, "profit": vpp_profit},
        "total_revenue": total_revenue,
        "total_ebitda": total_ebitda,
        "total_profit": total_profit,
        "battery_depreciation": battery_depreciation,
        "station_depreciation": station_dep,
        "hv_profit_per_station": hv_profit / hv_sites,
        "lv_profit_per_station": lv_profit / lv_sites,
    }


# ================================================================
# §7 VALIDATE —— 校验链（经营方视角，不污染主链）
# ================================================================
def ebitda_check(revenue, capex):
    """EBITDA 法校验：FCFF = EBITDA − 税 − 净重置（经营方"实际回报"视角）。

    与主链 EAC（资本方"要求回报"）对比，差异即两者的 gap。
    净重置 = 年退役量(kWh) × 该寿命年的净重置单价，退役量直接取装机量 ÷ 寿命。
    ⚠ 净重置只出现在这条校验链，绝不进主链（否则双重计算）。
    """
    ebitda = revenue["total_ebitda"]
    total_depr = revenue["battery_depreciation"] + revenue["station_depreciation"]
    net_repl = (capex["lv_kwh_gwh"] * GWH_IN_KWH / BATTERY_LIFE_LV
                * net_repl_unit_price(BATTERY_LIFE_LV)
                + capex["hv_kwh_gwh"] * GWH_IN_KWH / BATTERY_LIFE_HV
                * net_repl_unit_price(BATTERY_LIFE_HV)) / YI
    pretax = ebitda - total_depr
    tax = pretax * TAX_RATE
    return {
        "ebitda": ebitda, "depreciation": total_depr, "tax": tax,
        "net_repl": net_repl, "fcff": ebitda - tax - net_repl,
    }


def valuate(result, multiple):
    """由终局情景结果 + EV/EBITDA 倍数 → (隐含EBITDA, EV, Equity)。

    Equity = EV − Net Debt，Net Debt 用账面值 CAPEX×60%
    （WACC 7.5% 已隐含绿色信贷低利率优势，再用市场值会双重计算）。
    """
    ebitda = implied_ebitda_from_fcff(result["fcff_eac"], result["total_depr"])
    ev = ebitda * multiple
    return ebitda, ev, ev - result["total_capex"] * DEBT_RATIO

# ================================================================
# §8 REPORT —— 输出层（计算与输出解耦；main 是总入口，先读它即知全局）
# ================================================================
def main():
    """【总入口】按 md 章节顺序组织输出，每段对应一个 report_* 函数。

    执行顺序（= 阅读顺序）：
      ① 参数对齐      ② 2026基准收益   ③ 2026经营方校验
      ④ 装机量矩阵    ⑤ 终局主链估值   ⑥ 2030利用率情景   ⑦ CATL权益
    """
    print("=" * 70)
    print("宁德时代换电·能量维度模型（v7 重构）报告")
    print("=" * 70)

    # 全局共用的三份计算结果，一次算好、各段复用（避免重复计算与口径漂移）
    rev = compute_revenue(HV_SITES_2026, LV_SITES_2026)
    cap_2026 = compute_capex(HV_SITES_2026, LV_SITES_2026)
    results = {name: terminal_scenario(sc["vehicles"])
               for name, sc in PRIVATE_SCENARIOS.items()}

    report_params()
    report_revenue_2026(rev)
    report_ebitda_check(rev, cap_2026)
    report_installed_matrix(cap_2026, results["稳健"])
    report_terminal_valuation(results)
    report_utilization(rev)
    report_catl_equity(results)

    print("\n对齐检查完成。所有数字可追溯至两份md文件与 test_model.py 断言。")


# ---------------- ① 参数对齐 ----------------
def report_params():
    print("\n[参数对齐] 终局站数(框架.md L142): 乘用车%d 重卡%d" % (LV_SITES_TERMINAL, HV_SITES_TERMINAL))
    print("          放大倍数(L198): 乘用车站%.1f× 乘用车电池%.1f× 重卡%.1f×" %
          (AMP_LV_STATION, AMP_LV_VEHICLE, AMP_HV))
    print("          电池单价: %d元/kWh | 目标IRR: %.1f%% | EV/EBITDA: %d/%d/%d×" %
          (BATTERY_PRICE_PER_KWH, IRR * 100, EV_EBITDA_LOW, EV_EBITDA_MID, EV_EBITDA_HIGH))
    print("          电池寿命: 乘用%.1f年 / 重卡%.1f年 / 私家车%.0f年 | CRF(7.5%%,15y)=%.4f" %
          (BATTERY_LIFE_LV, BATTERY_LIFE_HV, BATTERY_LIFE_PRIVATE, CRF))


# ---------------- ② 2026 基准收益 ----------------
def report_revenue_2026(rev):
    print("\n" + "=" * 70)
    print("① 2026基准收益（重卡%d + 乘用车%d = %d座）—— 仅作放大基数，不估值" %
          (HV_SITES_2026, LV_SITES_2026, HV_SITES_2026 + LV_SITES_2026))
    print("=" * 70)
    print("%-16s %-12s %-12s %-14s %-10s" % ("项目", "收入(亿)", "EBITDA(亿)", "税后净利(亿)", "占宁德"))
    print("-" * 85)
    for name, key in [("峰谷套利", "arb"), ("换电服务费", "service"), ("电池租金", "rent"),
                      ("需求响应", "dr"), ("调频VPP", "vpp")]:
        d = rev[key]
        print("  %-14s %-12.2f %-12.2f %-14.2f %.2f%%" %
              (name, d["revenue"], d["ebitda"], d["profit"],
               d["profit"] / CATL_NET_INCOME_2026 * 100))
    print("-" * 85)
    print("  %-14s %-12.2f %-12.2f %-14.2f %.2f%%" %
          ("合计", rev["total_revenue"], rev["total_ebitda"], rev["total_profit"],
           rev["total_profit"] / CATL_NET_INCOME_2026 * 100))


# ---------------- ③ 2026 经营方校验 ----------------
def report_ebitda_check(rev, cap_2026):
    print("\n" + "=" * 70)
    print("② 2026基准·经营方校验（EBITDA法，仅锚，不做估值）")
    print("=" * 70)
    chk = ebitda_check(rev, cap_2026)
    print("  EBITDA法FCFF = %.1f亿 (EBITDA%.1f - 税%.1f - 净重置%.1f)" %
          (chk["fcff"], chk["ebitda"], chk["tax"], chk["net_repl"]))
    print("  [注] 2026为计算基础不估值；此FCFF仅校验收益量级，终局估值见下段。")


# ---------------- ④ 装机量矩阵 ----------------
def report_installed_matrix(cap_2026, r_steady):
    print("\n" + "=" * 70)
    print("③ 装机量 3×2 矩阵（GWh，换电业务形成的储能规模）")
    print("=" * 70)
    print("  [2026基准] 车型 × 维度（重卡=骐骥站 / 乘用营运=巧克力站 / 私家车仅装车）")
    _print_matrix(cap_2026["installed_matrix"], cap_2026["total_kwh_gwh"])
    print("  [稳健终局2030] 私家车导入后（站体免费期权，仅电池银行+私家车装车）")
    _print_matrix(r_steady["installed_matrix"], r_steady["total_kwh_gwh"])
    print("  说明：重卡+乘用营运=营运车小计；乘用营运+私家车=乘用车小计（md L154）")


def _print_matrix(m, total_gwh):
    """打印 3×2 装机量矩阵（车型 × {站体, 电池银行}）+ 小计行。"""
    print("    %-12s %-12s %-12s" % ("车型", "站体(GWh)", "电池银行(GWh)"))
    print("    " + "-" * 40)
    for name in ["重卡", "乘用营运", "私家车", "营运车小计", "乘用车小计"]:
        print("    %-12s %-12.1f %-12.1f" % (name, m[name]["站体"], m[name]["电池银行"]))
    print("    %-12s %-12.1f %-12.1f" %
          ("合计", m["营运车小计"]["站体"], m["营运车小计"]["电池银行"] + m["私家车"]["电池银行"]))
    print("    全口径总装机量(站体+电池银行) = %.1f GWh" % total_gwh)


# ---------------- ⑤ 终局主链估值 ----------------
def report_terminal_valuation(results):
    """主链：CRF/EAC → 隐含EBITDA → 市场法 EV/EBITDA → Equity。"""
    print("\n" + "=" * 70)
    print("④ 终局主链估值（2030稳态，CRF/EAC下沿锚 + 市场法EV/EBITDA）")
    print("=" * 70)

    steady = results["稳健"]
    print("\n[EAC口径] PV_total(站体+电池银行含重置脉冲折现) × CRF(7.5%%,15y=%.4f) = 等效年资本回收" % CRF)
    print("  PV_total(稳健) = %.0f亿 → ×CRF = FCFF_EAC %.0f亿（vs 完整CAPEX %.0f亿）" %
          (steady["pv_total"], steady["fcff_eac"], steady["total_capex"]))

    print("\n[主链明细 · 中枢18×] 完整CAPEX / FCFF_EAC / 隐含EBITDA / EV(18×) / Equity(18×) / DCF下沿Eq")
    print("%-8s %-12s %-12s %-12s %-12s %-12s %-12s" %
          ("情景", "完整CAPEX", "FCFF_EAC", "隐含EBITDA", "EV(18×)", "Equity", "DCF下沿Eq"))
    print("-" * 84)
    for name in PRIVATE_SCENARIOS:
        r = results[name]
        ebitda, ev_mid, eq_mid = valuate(r, EV_EBITDA_MID)
        eq_dcf = r["fcff_eac"] / IRR - r["total_capex"] * DEBT_RATIO
        print("  %-6s %-12.0f %-12.0f %-12.0f %-12.0f %-12.0f %-12.0f" %
              (name, r["total_capex"], r["fcff_eac"], ebitda, ev_mid, eq_mid, eq_dcf))

    # 3×3 敏感性矩阵：Equity = 情景 × 倍数（两个独立维度，不捆绑）
    print("\n[3×3 敏感性矩阵] Equity（亿）= 情景(rows) × EV/EBITDA倍数(cols)")
    print("  主结论引用「稳健×18×」一格作中枢；其余为敏感性带宽。")
    print("%-8s %-12s %-12s %-12s" % ("情景", "12×", "18×", "25×"))
    print("-" * 48)
    for name in PRIVATE_SCENARIOS:
        eqs = [valuate(results[name], m)[2]
               for m in (EV_EBITDA_LOW, EV_EBITDA_MID, EV_EBITDA_HIGH)]
        print("  %-6s %-12.0f %-12.0f %-12.0f" % (name, eqs[0], eqs[1], eqs[2]))

    # 对角线叙事（高渗透→护城河更深→理应更高倍数），仅标注、不作主结论
    print("\n  [对角线叙事·非主结论] 保守12× / 稳健18× / 激进25×：")
    diag = [valuate(results[n], m)[2] for n, m in
            (("保守", EV_EBITDA_LOW), ("稳健", EV_EBITDA_MID), ("激进", EV_EBITDA_HIGH))]
    print("    %-8s %-12.0f %-12.0f %-12.0f" % ("Equity", diag[0], diag[1], diag[2]))
    print("  [注] 市场倍数中枢%d×；DCF下沿EV=FCFF/7.5%%仅作 sanity check" % EV_EBITDA_MID)


# ---------------- ⑥ 2030 利用率情景 ----------------
def report_utilization(rev):
    """私家车 → 乘用车站利用率放大（md L210-214），重卡站恒 1.0×。"""
    print("\n" + "=" * 70)
    print("⑤ 2030稳态利用率情景（私家车→乘用车站利用率，重卡站恒1.0×）")
    print("=" * 70)
    print("%-26s %-10s %-10s %-12s %-10s" % ("情景", "私家车(万)", "乘用车站利用率", "净利(亿)", "占宁德"))
    print("-" * 72)
    for s in TERMINAL_UTIL_SCENARIOS:
        lv_util = util_from_private(s["private_wan"])
        profit = (rev["hv_profit_per_station"] * HV_SITES_TERMINAL * HV_TERMINAL_UTIL
                  + rev["lv_profit_per_station"] * LV_SITES_TERMINAL * lv_util)
        print("  %-24s %-10d %-10.2f %-12.1f %.1f%%" %
              (s["label"], s["private_wan"], lv_util, profit, profit / s["catl_ni"] * 100))
        print("       └ 假设来源: %s" % s["src"])


# ---------------- ⑦ CATL 权益 ----------------
def report_catl_equity(results):
    """站体与电池银行是两个投资主体，Equity 分列后各乘自持比例。"""
    print("\n" + "=" * 70)
    print("⑥ CATL权益价值（完整终局）")
    print("=" * 70)
    # 站体 Equity 与情景无关（站数固定），用稳健情景的站体 FCFF 计算
    base = results["稳健"]
    station_ebitda = implied_ebitda_from_fcff(base["fcff_station"], base["depr_station"])
    station_eq = station_ebitda * EV_EBITDA_MID - base["station_capex_terminal"] * DEBT_RATIO
    print("  站体Equity(18×): %.0f亿 (与情景无关，站数已固定)" % station_eq)
    print("%-8s %-14s %-14s %-14s %-10s" % ("情景", "电池Equity", "CATL站体", "CATL电池", "CATL合计"))
    print("-" * 76)
    for name, sc in CATL_SCENARIOS.items():
        r = results[name]
        battery_ebitda = implied_ebitda_from_fcff(r["fcff_battery"], r["total_depr_battery"])
        battery_eq = battery_ebitda * EV_EBITDA_MID - r["battery_capex_total"] * DEBT_RATIO
        catl_station = station_eq * sc["station"]
        catl_battery = battery_eq * sc["battery"]
        catl_total = catl_station + catl_battery
        print("  %-6s %-14.0f %-14.0f %-14.0f %-10.0f (占2万亿 %.1f%%)" %
              (name, battery_eq, catl_station, catl_battery, catl_total,
               catl_total / CATL_MARKET_CAP * 100))


if __name__ == "__main__":
    main()

/**
 * ============================================================
 * engine/constants.js — 工程物理常量 & 税务参数 & 价格体系
 * ============================================================
 * 本文件定义模型中所有"硬编码"的常量参数。
 * 调参逻辑：修改本文件中的数值即可全局生效，无需改动计算逻辑。
 *
 * 加载顺序：必须在 engine/index.js 之后加载（依赖 Engine 命名空间）
 * 对应MD文档：宁德时代_超换一体站_财务模型_修正版.md # 第1-2章、附录A
 * ============================================================
 */
var Engine = window.Engine || {};

// ============================================================
// 一、电池物理参数（巧克力25#电池块）
// ============================================================

/** 电池标称容量（kWh），巧克力25#电池块单块电量 */
Engine.BAT_CAP_KWH = 56;

/** 单次换入电量（kWh），SOC窗口约89.3%（起始SOC约5.7%，目标SOC约95%） */
Engine.SWAP_KWH_NET = 50;

/** 超充单车默认充电量（kWh） */
Engine.SC_KWH = 25;

/** 单站日均超充车辆数 */
Engine.SC_CARS_PER_STATION = 40;

/** 系统电损率 9%（充放电过程中的能量损耗） */
Engine.LOSS_RATE = 0.09;

/** 峰谷加权购电价（元/度），已考虑峰谷分时电价结构 */
Engine.WEIGHTED_PRICE = 0.61;

// ============================================================
// 二、电池SOH衰减与梯次利用（双轨制：营运车+私家车）
// 来源：超换一体.md # Step 0-2（三阶段非线性衰减曲线）
//      财务模型_修正版.md # 附录A.3（日历老化参考）
// ============================================================

/**
 * 双轨制SOH衰减模型
 *
 * 营运车（出租/网约车，占比68-75%）：
 *   - 日均换电1.5-2次，年循环548-730次
 *   - 3年达到2000次循环临界点，SOH≈83%
 *   - 3年后退出换电网络，进入储能环节
 *
 * 私家车（占比25-30%）：
 *   - 日均换电0.3-0.5次，年循环110-183次
 *   - 8年达到900-1500次循环，SOH≈88%
 *   - 8年后退出换电网络，进入储能环节
 *
 * 模型选择8年作为基准期（统计平均值，超换一体.md # Step 3）
 * 基准SOH取88%（私家车路径，更保守的残值估计）
 */

/** SOH衰减三阶段：基于循环次数（非日历年限） */
Engine.SOH_BY_CYCLE = [
  { cycles: 0,    soh: 1.00,  phase: '初始' },
  { cycles: 500,  soh: 0.95,  phase: '第一阶段：化成期（SEI膜形成）' },
  { cycles: 1000, soh: 0.90,  phase: '第二阶段：线性缓慢衰减' },
  { cycles: 1500, soh: 0.87,  phase: '第二阶段：线性缓慢衰减' },
  { cycles: 2000, soh: 0.83,  phase: '临界点：用户体感续航缩短，2000次循环' },
  { cycles: 2500, soh: 0.78,  phase: '第三阶段：加速衰减（电极微裂纹+锂枝晶）' },
  { cycles: 3000, soh: 0.70,  phase: '第三阶段：接近退役（工信部SOH<80%退役）' }
];

/** 营运车退出换电时的SOH（3年，约2000次循环） */
Engine.SOH_OPERATIONAL_EXIT = 0.83;

/** 营运车退出换电年限（年） */
Engine.SOH_OPERATIONAL_EXIT_YEAR = 3;

/** 私家车退出换电时的SOH（8年，约900-1500次循环，日历老化为主） */
Engine.SOH_PRIVATE_EXIT = 0.88;

/** 私家车退出换电年限（年），模型基准期 */
Engine.SOH_PRIVATE_EXIT_YEAR = 8;

/**
 * 模型基准SOH（第8年电池置换时使用）
 * 取88%（私家车路径），比日历老化表87.3%更保守地反映实际使用
 * 注意：若未来分车型计算，营运车应在第3年按83%置换
 */
Engine.BAT_SOH_Y8 = Engine.SOH_PRIVATE_EXIT;

/**
 * 综合折旧系数
 * 含义：旧电池用于储能市场的价值打折系数
 * 计算逻辑：BAT_SOH_Y8 × BAT_DEGRADE_FACTOR × BAT_ESS_AVAILABILITY
 *          = 0.88 × 0.63 × 0.55 ≈ 0.305（综合折扣约30.5%）
 */
Engine.BAT_DEGRADE_FACTOR = 0.63;

/** 储能市场可用度系数 55%（考虑电池一致性、安全性筛选后的可用比例，保守估计40-55%） */
Engine.BAT_ESS_AVAILABILITY = 0.55;

/** 第8年电池置换年份 */
Engine.BAT_REPLACE_YEAR = 8;

// ============================================================
// 三、税务模型常量
// ============================================================

/** 增值税率 13% — 换电、超充、电池租赁（有形动产/电力销售） */
Engine.VAT_13 = 0.13;

/** 增值税率 6% — 技术服务费、保费（现代服务业/金融保险） */
Engine.VAT_6 = 0.06;

/** 增值税率 9% — 场地租金（不动产租赁，一般纳税人） */
Engine.RENT_VAT = 0.09;

/** 附加税率 12% — 城市维护建设税+教育费附加 = 应交增值税×12% */
Engine.SURTAX = 0.12;

/** 企业所得税率 25% */
Engine.CIT = 0.25;

/** 社保费率 40%（五险一金企业缴纳部分） */
Engine.SOCIAL = 0.40;

/** 默认运营测算年限（年） */
Engine.YEARS = 15;

// ============================================================
// 四、折旧与残值参数
// ============================================================

/** 场站设备折旧年限（年） */
Engine.STATION_DEPRECIATION_YEARS = 10;

/** 电池15年末残值率 10% */
Engine.BAT_RESIDUAL = 0.10;

/**
 * 第8年末电池残值率 40%（旧电池回收参考值）
 * 注意：BAT_RESIDUAL_RATE_Y8 在当前模型中为"死代码"
 * 实际第8年残值使用梯次利用公式计算（见 BAT_SOH_Y8 等处）
 * 保留此常量供未来直接引用
 */
Engine.BAT_RESIDUAL_RATE_Y8 = 0.40;

// ============================================================



// 五、电池价格体系（pack级 · 15年时序数据）
// 严格按：电池价格口径统一与pack价格参考.md # 3.2.1
// 口径：25# LFP 56kWh 换电块，公允含税结算价
// ============================================================

/**
 * 电池价格口径说明
 *
 * 电芯(Cell)：0.34-0.38元/Wh（TrendForce 2026-05 LFP动力电芯现货）
 * Pack裸成本 = 电芯 + Pack加成（BMS+结构件+热管理+组装）
 * Pack含税价 = Pack裸成本 × 1.13（增值税）
 * 市场Pack价：0.50元/Wh（TrendForce LFP pack含税价，2026）
 * 换电块结算价 = 市场Pack价 × 换电附加系数(1.15-1.20)
 *   - 换电附加：机械锁止机构(10000次寿命) + 快换接口 + 强化BMS + 标准化外壳
 *   - 25# LFP 56kWh：32,480~33,600元/块（0.58~0.60元/Wh）
 * 年降幅：5.8%（BNEF 2025-12中性预测，动力电芯）
 */

/** 2026年基准市场Pack含税价（元/Wh），TrendForce 2026-05 */
Engine.MARKET_PACK_PRICE_Y0 = 0.50;

/** 换电块附加成本系数（下限），比普通pack高15% */
Engine.SWAP_COEFF_LOW = 1.15;

/** 换电块附加成本系数（上限），比普通pack高20% */
Engine.SWAP_COEFF_HIGH = 1.20;

/** 换电块附加成本系数（中性），取中值1.175 */
Engine.SWAP_COEFF_MID = 1.175;

/**
 * 15年电池价格时序生成函数
 * @param {number} t - 年份（0=2026, 1=2027, ..., 15=2041）
 * @returns {Object} { cellCost, packIntCost, packBareCost, packTaxCost, marketPackPrice, settlementPrice }
 *   所有价格单位：元/Wh
 */
Engine.getBatteryPriceByYear = function (t) {
  t = Math.min(t, 15);
  // 动力电芯年降5.8%
  var cellCost = 0.380 * Math.pow(1 - Engine.CELL_COST_DECLINE_RATE, t);
  // Pack加成：Y0=0.100，Y15=0.050，线性递减
  var packIntCost = 0.100 - (0.100 - 0.050) * (t / 15);
  // Pack裸成本 = 电芯 + 集成
  var packBareCost = cellCost + packIntCost;
  // Pack含税价（成本口径）= 裸成本 × 1.13
  var packTaxCost = packBareCost * 1.13;
  // 市场Pack价（市场口径）= 0.50 × (1-5.8%)^t
  var marketPackPrice = Engine.MARKET_PACK_PRICE_Y0 * Math.pow(1 - Engine.CELL_COST_DECLINE_RATE, t);
  // 换电块公允结算价 = 市场Pack价 × 换电附加系数（中性）
  var settlementPrice = marketPackPrice * Engine.SWAP_COEFF_MID;
  // 25# LFP 56kWh 单块结算价（元）
  var settlementPerBlock = settlementPrice * Engine.BAT_CAP_KWH;

  return {
    year: 2026 + t,
    cellCost: cellCost,                 // 电芯成本（元/Wh）
    packIntCost: packIntCost,           // Pack集成成本（元/Wh）
    packBareCost: packBareCost,         // Pack裸成本（元/Wh）
    packTaxCost: packTaxCost,           // Pack含税价·成本口径（元/Wh）
    marketPackPrice: marketPackPrice,   // 市场Pack价·含税（元/Wh）
    settlementPrice: settlementPrice,   // 换电块结算价·含税（元/Wh）
    settlementPerBlock: settlementPerBlock, // 25# 56kWh单块结算价（元）
    grossMargin: 0.22 - 0.005 * t       // 毛利率：22%→14.5%（线性）
  };
};

/**
 * 预计算15年电池价格数组（元/块，25# LFP 56kWh）
 * BAT_PRICE_BY_YEAR[t] = 第t年单块电池公允结算价（元）
 */
Engine.BAT_PRICE_BY_YEAR = [];
for (var t = 0; t <= 15; t++) {
  Engine.BAT_PRICE_BY_YEAR.push(Engine.getBatteryPriceByYear(t).settlementPerBlock);
}

/** 电芯成本默认值（元/Wh），2026E行业一致预期（保留兼容旧代码） */
Engine.DEFAULT_CELL_COST = 0.380;

/** Pack集成成本默认值（元/Wh），含BMS+结构件+组装（保留兼容旧代码） */
Engine.DEFAULT_PACK_INT_COST = 0.100;

/** 毛利率默认值（%），宁德时代硬件销售毛利率 */
Engine.DEFAULT_GROSS_MARGIN = 22;

/** 超充服务费（元/度） */
Engine.SC_FEE = 0.30;

// ============================================================
















// ===== AUTO-GEN: PRICE SECTION (DO NOT EDIT — generated by data/sync_prices.js) =====
// 五、电池价格体系（pack级 · 15年时序数据）— 本段由 sync_prices.js 自动生成，勿手改
// 严格按：电池价格口径统一与pack价格参考.md # 3.2
// 真源：电池价格口径统一与pack价格参考.md（v2.0.2 机制，自变量来自 .md，因变量由 battery_prices.js 推导）
// 生成时间：2026-08-17T15:27:18.140Z
// 三阶段：平台期(2026-2028,-1.3%/年) / 缓降期(2029-2033,-4.0%/年) / 慢降期(2034-2041,-2.8%/年)
// 修改价格请编辑 电池价格口径统一与pack价格参考.md 后重跑 node data/sync_prices.js

/** 价格基准与换电附加（元/Wh；来自 .md §3.1/§3.2） */
Engine.PRICE_Y0 = { cellLfp: 0.38, cellNmc: 0.59, packLfp: 0.51, packNmc: 0.77, swapLow: 1.15, swapMid: 1.175, swapHigh: 1.2, vat: 0.13 };

/** 三阶段外推（替代旧单一 5.8%/6.5% 年降；来自 .md §3.2 公式） */
Engine.PRICE_STAGES = [{"name":"平台期","from":2026,"to":2028,"annualChange":-0.013},{"name":"缓降期","from":2029,"to":2033,"annualChange":-0.04},{"name":"慢降期","from":2034,"to":2041,"annualChange":-0.0275}];

/** 动力电芯成本序列（元/Wh，t=0..15，三阶段推演） */
Engine.POWER_CELL_BY_YEAR = [0.38, 0.3751, 0.3702, 0.3554, 0.3412, 0.3276, 0.3145, 0.3019, 0.2936, 0.2855, 0.2776, 0.27, 0.2626, 0.2554, 0.2484, 0.2416];
/** 储能电芯成本序列（元/Wh，t=0..15） */
Engine.ESS_CELL_BY_YEAR = [0.38, 0.3751, 0.3702, 0.3554, 0.3412, 0.3276, 0.3145, 0.3019, 0.2936, 0.2855, 0.2776, 0.27, 0.2626, 0.2554, 0.2484, 0.2416];
/** 动力 Pack 集成成本序列（元/Wh，Y0→Y15 线性） */
Engine.POWER_PACK_INT_BY_YEAR = [0.1, 0.0967, 0.0933, 0.09, 0.0867, 0.0833, 0.08, 0.0767, 0.0733, 0.07, 0.0667, 0.0633, 0.06, 0.0567, 0.0533, 0.05];
/** 储能 Pack 集成成本序列（元/Wh） */
Engine.ESS_PACK_INT_BY_YEAR = [0.06, 0.0578, 0.0556, 0.0534, 0.0512, 0.049, 0.0468, 0.0446, 0.0424, 0.0402, 0.038, 0.0358, 0.0336, 0.0314, 0.0292, 0.027];
/** 动力毛利率序列（小数，22%→14.5%） */
Engine.POWER_GM_BY_YEAR = [0.22, 0.215, 0.21, 0.205, 0.2, 0.195, 0.19, 0.185, 0.18, 0.175, 0.17, 0.165, 0.16, 0.155, 0.15, 0.145];
/** 储能毛利率序列（小数，26.8%→15.5%） */
Engine.ESS_GM_BY_YEAR = [0.268, 0.2605, 0.2529, 0.2454, 0.2379, 0.2303, 0.2228, 0.2153, 0.2077, 0.2002, 0.1927, 0.1851, 0.1776, 0.1701, 0.1625, 0.155];

/** 市场 Pack 含税价（元/Wh，LFP/NMC，随三阶段联动；TrendFlow 口径） */
Engine.MARKET_PACK_BY_YEAR_LFP = [0.51, 0.5034, 0.4968, 0.477, 0.4579, 0.4397, 0.4221, 0.4052, 0.394, 0.3832, 0.3726, 0.3624, 0.3525, 0.3428, 0.3334, 0.3243];
Engine.MARKET_PACK_BY_YEAR_NMC = [0.77, 0.7601, 0.7501, 0.7202, 0.6914, 0.6638, 0.6373, 0.6118, 0.5949, 0.5785, 0.5625, 0.5471, 0.5321, 0.5175, 0.5033, 0.4896];
/** 宁德含税 Pack 价（元/Wh，LFP，电芯+集成+13%增值税；对应手册 §3.2.1 单块成本口径） */
Engine.PACK_TAX_BY_YEAR_LFP = [0.5424, 0.5331, 0.5238, 0.5033, 0.4835, 0.4643, 0.4458, 0.4278, 0.4146, 0.4017, 0.3891, 0.3766, 0.3645, 0.3527, 0.3409, 0.3295];
/** 换电业务结算价（元/Wh，= 市场 Pack × 1.175 附加，向客户收；区别于电池成本） */
Engine.SETTLE_BY_YEAR_LFP = [0.5993, 0.5915, 0.5837, 0.5605, 0.538, 0.5166, 0.496, 0.4761, 0.463, 0.4503, 0.4378, 0.4258, 0.4142, 0.4028, 0.3917, 0.3811];
Engine.SETTLE_BY_YEAR_NMC = [0.9048, 0.8931, 0.8814, 0.8462, 0.8124, 0.78, 0.7488, 0.7189, 0.699, 0.6797, 0.6609, 0.6428, 0.6252, 0.6081, 0.5914, 0.5753];
/** 25# 56kWh 单块电池成本（元/块，含税 Pack 口径，用于换电池；Y0≈30400） */
Engine.BLOCK_PRICE_BY_YEAR = [30374, 29854, 29333, 28185, 27076, 26001, 24965, 23957, 23218, 22495, 21790, 21090, 20412, 19751, 19090, 18452];

/** 兼容旧代码常量（v1.0 残留，已废弃——价格见上方数组） */
Engine.CELL_COST_DECLINE_RATE = 0.058; // deprecated
Engine.ESS_CELL_COST_DECLINE_RATE = 0.065; // deprecated
Engine.ESS_CELL_COST_Y0 = 0.38; // deprecated
Engine.MARKET_PACK_PRICE_Y0 = 0.51; // deprecated
Engine.SWAP_COEFF_LOW = 1.15;
Engine.SWAP_COEFF_MID = 1.175;
Engine.SWAP_COEFF_HIGH = 1.2;
Engine.DEFAULT_CELL_COST = 0.38;
Engine.DEFAULT_PACK_INT_COST = 0.1;
Engine.DEFAULT_GROSS_MARGIN = 22;

/**
 * 按年份取电池价格（表驱动，t=0..15）。所有数值来自上方 AUTO-GEN 数组。
 * 改价格请编辑 .md 并重跑 sync_prices.js，勿在此手写。
 */
Engine.getBatteryPriceByYear = function (t) {
  t = Math.min(Math.max(t, 0), 15);
  var cellCost = Engine.POWER_CELL_BY_YEAR[t];
  var packIntCost = Engine.POWER_PACK_INT_BY_YEAR[t];
  var packBareCost = cellCost + packIntCost;
  var packTaxCost = Math.round(packBareCost * (1 + Engine.PRICE_Y0.vat) * 10000) / 10000;
  var marketPackPrice = Engine.MARKET_PACK_BY_YEAR_LFP[t];
  var swapSettlementPrice = Engine.SETTLE_BY_YEAR_LFP[t];
  var settlementPerBlock = Engine.BLOCK_PRICE_BY_YEAR[t]; // 电池成本口径（含税Pack×56kWh，不含1.175附加）
  return {
    year: Engine.BASE_YEAR + t,
    cellCost: cellCost,
    packIntCost: packIntCost,
    packBareCost: packBareCost,
    packTaxCost: packTaxCost,
    marketPackPrice: marketPackPrice,
    swapSettlementPrice: swapSettlementPrice,
    settlementPerBlock: settlementPerBlock,
    grossMargin: Engine.POWER_GM_BY_YEAR[t]
  };
};

/** 预计算 15 年单块结算价（元/块，25# LFP 56kWh） */
Engine.BAT_PRICE_BY_YEAR = [30374, 29854, 29333, 28185, 27076, 26001, 24965, 23957, 23218, 22495, 21790, 21090, 20412, 19751, 19090, 18452];
// ===== END AUTO-GEN: PRICE SECTION =====

// 六、备电租赁价格体系（元/月/块）
// ============================================================

/** 备电租赁低价档（站端支付，IRR偏低仅覆盖运维） */
Engine.SPARE_RENT_LOW = 200;

/** 备电租赁中价档（推荐，平衡站端成本与银行收益） */
Engine.SPARE_RENT_MID = 240;

/** 备电租赁高价档（银行IRR充裕，站端成本上升） */
Engine.SPARE_RENT_HIGH = 280;

// ============================================================
// 七、运维成本参数
// ============================================================

/** 电池年维保费率 2%（占电池资产原值） */
Engine.BAT_MAINT_RATE = 0.02;

/** 技术服务费成本占比 20%（电池银行向换电站收取的技术服务费中，实际发生成本的比例） */
Engine.TECH_SERVICE_COST_RATIO = 0.20;

/** 设备保险费率 0.15%（占场站投资额） */
Engine.EQUIP_INSUR_RATE = 0.0015;

/** 电池保险费率 0.20%（占电池资产原值） */
Engine.BAT_INSUR_RATE = 0.0020;

/** 16h双班运维年费（元/年） */
Engine.MAINT_16H = 60000;

/** 24h全自动运维年费（元/年） */
Engine.MAINT_24H = 80000;

/** 换电操作员工资（元/月/人） */
Engine.STAFF_SWAP_MONTHLY = 8000;

/** 换电站双班制标配人数 */
Engine.STAFF_SWAP_COUNT = 2;

/** 社保附加倍数（工资×1.4 = 含社保人工成本） */
Engine.STAFF_SWAP_SOCIAL_MULTIPLIER = 1.4;

// ============================================================
// 八、运营规模参数
// ============================================================

/** 16h双班满负荷换电次数（次/天） */
Engine.MAX_SWAPS_16H = 125;

/** 爬坡因子：站点运营第1~4年分别达到满负荷的80%/100%/110%/120% */
Engine.RAMP_BY_AGE = [80, 100, 110, 120];

/** 期间费用率 8%（管理费用+销售费用占收入比） */
Engine.PERIOD_EXPENSE_RATE = 0.08;

/** 默认折现率 7.5% */
Engine.DEFAULT_DISCOUNT_RATE = 0.075;

/** 默认测算年限（年） */
Engine.YEARS_DEFAULT = 15;

/** 基准年份（估值分析用） */
Engine.BASE_YEAR = 2026;

// ============================================================
// 九、VPP（虚拟电厂）+ CCER（碳减排）参数
// ============================================================

/** VPP基础年收入（元/站），满负荷场景 */
Engine.VPP_BASE = 30000;

/** VPP基准日用电量（kWh），双班满负荷125次×26kWh + 超充1000度×4辆 */
Engine.VPP_BASE_KWH = 7250;

/** VPP基准超充车辆数 */
Engine.VPP_BASE_CARS = 4;

/** VPP基准每车日充电量（kWh） */
Engine.VPP_BASE_KWH_PER_CAR = 1000;

/** CCER碳价（元/吨CO2） */
Engine.CCER_RATE = 100;

/** 电力排放因子（kgCO2/kWh），电网基准线排放因子 */
Engine.EMISSION_FACTOR = 0.31;

// ============================================================
// 十、电池银行人力密度参数
// ============================================================

/** CATL平均年薪（元/年/人），不含社保 */
Engine.BANK_AVG_SALARY = 176400;

/** 蔚能基准人力密度：97人管理15万块电池（即 97/150000 ≈ 0.000647 人/块） */
Engine.BANK_BASE_STAFF_DENSITY = 97 / 150000;

// ============================================================
// 十一、用户结构参数（调和平均法）
// ============================================================

/** 营运车辆日均换电频率（次/天），约1.4天换一次 */
Engine.COMM_SWAP_FREQ = 0.71;

/** 私家车日均换电频率（次/天），约5天换一次 */
Engine.PRIV_SWAP_FREQ = 0.20;

/** 满载时营运用户占比（80%），用于线性插值计算实际占比 */
Engine.COMM_RATIO_FULL_LOAD = 0.80;

// ============================================================
// 十二、电池租赁价格体系（元/月）
// ============================================================

/** 电池租赁价格表（元/月），按用户类型×电池容量×套餐 */
Engine.RENT_PRICE = {
  priv20_fam: 369,           // 私家车20kWh家庭包月租
  priv20_unl: 469,           // 私家车20kWh不限次月租
  priv25_fam: 499,           // 私家车25kWh家庭包月租（基准）
  priv25_fam_first: 399,     // 私家车25kWh家庭包首年优惠价
  priv25_unl: 599,           // 私家车25kWh不限次月租
  comm20_unl: 469,           // 营运车20kWh不限次月租
  comm25_unl: 599            // 营运车25kWh不限次月租（基准）
};

// ============================================================
// 十三、制造利润里程碑（2026E各投行一致预期）
// ============================================================

/** 2026年制造利润基准值（亿元），对应~450GWh出货 */
Engine.MFG_BASE_PROFIT = 920;

/** 2028年建完产能后利润（亿元），对应~600GWh出货 */
Engine.MFG_BUILD_COMPLETE_PROFIT = 990;

/** 2030年满产利润（亿元），对应~900GWh出货 */
Engine.MFG_FULL_LOAD_PROFIT = 1190;

/** 2035年成熟利润（亿元），对应全球40%份额稳定期 */
Engine.MFG_MATURE_PROFIT = 1630;

// ============================================================
// 十四、关联方交易消除参数
// ============================================================

/**
 * 关联方交易消除（亿元）
 * yr7：电池租赁关联交易（7亿）
 * yr8：技术服务费关联交易（44亿）
 * yr9：其他关联交易（75亿）
 * 以上为2025年报中披露的关联交易预估数
 */
Engine.INTERCO_YR7 = 11;
Engine.INTERCO_YR8 = 44;
Engine.INTERCO_YR9 = 75;

// ============================================================
// 十五、内部结算价（分拆模型）
// 来源：宁德时代_超换一体站_财务模型_修正版.md 第三部分
// ============================================================

/**
 * 周转电池租赁价（元/月/块）
 * 换电站向电池银行租赁周转电池的月租金
 * 定价逻辑：覆盖电池银行资金成本+合理利差，双方平衡点
 */
Engine.INTERNAL_BAT_RENT_MONTHLY = 240;

/** 每站周转电池数量（块） */
Engine.INTERNAL_BAT_PER_STATION = 14;

/**
 * 技术服务费（元/年/站）
 * 换电站向电池银行支付：含APP/系统/健康监控/技术支持
 * 对标蔚能全包1.37万/年，本模型3.5万/年仅含系统支持
 */
Engine.INTERNAL_TECH_FEE_YEARLY = 35000;

/**
 * 每站年内部结算总额（元）= 周转电池租金 + 技术服务费
 * = 240 × 14 × 12 + 35000 = 40,320 + 35,000 = 75,320
 */
Engine.INTERNAL_SETTLEMENT_PER_STATION = Engine.INTERNAL_BAT_RENT_MONTHLY * Engine.INTERNAL_BAT_PER_STATION * 12 + Engine.INTERNAL_TECH_FEE_YEARLY;

// ============================================================
// 十六、向后兼容别名（旧名称 → 新名称映射）
// 说明：station.js 和 batteryBank.js 引用的常量名称基于旧版 constants.js，
//       以下别名确保旧代码无需修改即可运行。
// ============================================================

/** 租金增值税率（旧名 VAT_9，新名 RENT_VAT） */
Engine.VAT_9 = Engine.RENT_VAT;

/** 超充单次充电量（kWh），即 SC_KWH */
Engine.CHG_KWH = Engine.SC_KWH;

/** 超充服务费（元/kWh），包含购电价+服务费溢价 */
Engine.CHG_FEE = 0.80;

/** 功率线损系数 = 1 + 线损率 */
Engine.POWER_LINE_LOSS = 1 + Engine.LOSS_RATE;

/** 每块电池年仓储充电费（元/年/块），电池仓储充电、均衡维护的电力成本 */
Engine.BAT_ANNUAL_STORE_FEE = 200;

/** 电池银行人均年成本（元/年），即 BANK_AVG_SALARY */
Engine.BANK_STAFF_COST = Engine.BANK_AVG_SALARY;

/** CCER：单次换电碳减排量（tCO2/次）= 换电量(kWh) × 电力排放因子(kg/kWh) / 1000 */
Engine.CCER_DAILY_SWAP_CO2 = Engine.SWAP_KWH_NET * Engine.EMISSION_FACTOR / 1000;

/** CCER：碳价（元/tCO2），即 CCER_RATE */
Engine.CCER_PRICE = Engine.CCER_RATE;

// ============================================================
// 十三、估值模型参数（两分法：制造+运营）
// ============================================================

// 来源：换电业务相变与估值影响.md §2 制造、运营两板块估值演变
// 数据为原始文档给出的里程碑假设值，非公式推导：
//   - 建设期（BASE_YEAR）：920亿（机构一致预期）
//   - 建成（利用率爬坡至~40%）：990亿
//   - 达产（满载运营）：1,185亿
//   - 成熟期（行业稳态）：1,633亿
// 注意：这些数字是业务里程碑对应的制造净利润假设，非按固定增长率递推。
 
/** 制造利润里程碑（亿元）—— 建设期/建成期/达产期/成熟期 */
Engine.MFG_BASE_PROFIT = 920;           // 建设期制造净利润（亿元）
Engine.MFG_BUILD_COMPLETE_PROFIT = 990; // 建成期制造净利润（亿元）
Engine.MFG_FULL_LOAD_PROFIT = 1190;     // 达产期制造净利润（亿元）
Engine.MFG_MATURE_PROFIT = 1630;        // 成熟期制造净利润（亿元）

/** 制造利润里程碑年份偏移（相对于 BASE_YEAR） */
Engine.MFG_BUILD_COMPLETE_OFFSET = 2;   // 建成年 = BASE_YEAR + 2
Engine.MFG_FULL_LOAD_OFFSET = 5;        // 达产年 = BASE_YEAR + 5
Engine.MFG_MATURE_OFFSET = 4;           // 成熟期 = BASE_YEAR + BAT_REPLACE_YEAR + 4

/** 制造PE衰减系数（相对于基准PE） */
Engine.MFG_PE_DECAY_BUILD = 0.95;       // 建成期 PE = 基准 × 0.95
Engine.MFG_PE_DECAY_SWAP = 0.90;        // 换电期 PE = 基准 × 0.90
Engine.MFG_PE_DECAY_TERMINAL = 0.76;    // 远期 PE = 基准 × 0.76
Engine.MFG_PE_TERMINAL_MIN = 15;        // 终端PE下限（锚定台积电）

/** 三阶段判定参数 */
Engine.PHASE2_STATION_THRESHOLD = 30000; // 阶段二触发阈值（站数）
Engine.PHASE2_UTILIZATION_FACTOR = 0.6;  // 阶段二利用率因子（稳态的60%）
Engine.PHASE2_UTILIZATION_MIN = 0.1;     // 阶段二利用率下限
Engine.PHASE2_UTILIZATION_MAX = 0.8;     // 阶段二利用率上限
Engine.PHASE3_RAMP_YEARS = 3;            // 阶段三：建成后爬坡年数

/** 三阶段默认PE（运营业务） */
Engine.PHASE1_OP_PE = 20;               // 阶段一：纯制造，运营PE无意义
Engine.PHASE2_OP_PE = 30;               // 阶段二：临界信号

/** 敏感性分析配置 */
Engine.SENSITIVITY_PE_OFFSET = 5;        // PE偏移幅度（±）
Engine.SENSITIVITY_SWAP_LEVELS = [80, 110, 120]; // 换电次数级别

/** 终期目标换电站数 */
Engine.TARGET_STATIONS = 100000;
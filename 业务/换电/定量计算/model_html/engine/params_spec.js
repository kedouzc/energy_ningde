/**
 * ============================================================
 * engine/params_spec.js — 参数范围定义 + 方向一致性约束
 * ============================================================
 * 本文件是自动调参系统的"合法性手册"。
 * - params_range：每个可调参数的范围、默认值、步长、类型
 * - consistency_rules：自变量之间的方向一致性约束（软约束）
 * - 调参时，Agent 每生成一组候选参数，先用本文件检查合法性
 *
 * 加载顺序：必须在 constants.js 之后加载
 * 对应MD文档：电池价格口径统一与pack价格参考.md / 超换一体.md
 * ============================================================
 */
var Engine = window.Engine || {};

// ============================================================
// 一、参数范围定义
// 说明：
//   type: 'continuous' | 'discrete' | 'computed' | 'fixed'
//   continuous = 连续值，在[min, max]间按step搜索
//   discrete   = 离散值，只能取 options 数组中的值
//   computed   = 由公式计算，不可直接调
//   fixed      = 固定值，不参与调参
//   priority   = 1(高) 2(中) 3(低)，敏感性分析时排序用
// ============================================================

Engine.PARAM_SPEC = {
  // ============================================================
  // A. 场景参数（可连续调节，来自权威预测范围）
  // ============================================================

  /** 日均换电次数（次/天），核心驱动变量 */
  dailySwaps: {
    type: 'continuous',
    min: 60,
    max: 160,
    default: 115,
    step: 5,
    priority: 1,
    unit: '次/天',
    description: '单站日均换电次数。悲观80/中性115/乐观135',
    source: '财务模型_修正版.md # 情景分析'
  },

  /** 峰谷加权购电价（元/度） */
  elecPrice: {
    type: 'continuous',
    min: 0.50,
    max: 0.70,
    default: 0.60,
    step: 0.01,
    priority: 1,
    unit: '元/度',
    description: '峰谷分时电价加权均价。中国电价相对稳定',
    source: '财务模型_修正版.md # 电价假设'
  },

  /** 超充服务费溢价（元/度） */
  chgFeePremium: {
    type: 'continuous',
    min: 0.05,
    max: 0.15,
    default: 0.10,
    step: 0.01,
    priority: 2,
    unit: '元/度',
    description: '超充服务费在购电价基础上的溢价。取决于竞争格局',
    source: '财务模型_修正版.md # 超充定价'
  },

  /** 场地月租金（元/平米/月） */
  rentSqrm: {
    type: 'continuous',
    min: 10,
    max: 25,
    default: 15,
    step: 1,
    priority: 2,
    unit: '元/平米/月',
    description: '城市中心15-25，郊区10-15。规模化后议价能力提升',
    source: '财务模型_修正版.md # 场地成本'
  },

  /** 家庭包占比（%） */
  famRatio: {
    type: 'continuous',
    min: 0.50,
    max: 0.95,
    default: 0.90,
    step: 0.05,
    priority: 1,
    unit: '%',
    description: 'BaaS用户中选择家庭包套餐的比例。悲观0.5/中性0.9',
    source: '财务模型_修正版.md # 用户结构'
  },

  /** 站点数量（个） */
  stationCount: {
    type: 'continuous',
    min: 500,
    max: 5000,
    default: 1000,
    step: 100,
    priority: 1,
    unit: '个',
    description: '换电站建设总数量。受资本开支和扩张节奏约束',
    source: '财务模型_修正版.md # 规模化假设'
  },

  /** 折现率（%） */
  discountRate: {
    type: 'continuous',
    min: 6.0,
    max: 8.5,
    default: 7.5,
    step: 0.25,
    priority: 1,
    unit: '%',
    description: '资金成本。能源类项目传统8%，近年降至6-7.5%',
    source: '财务模型_修正版.md # DCF假设'
  },

  /** 门槛收益率（%） */
  hurdleRate: {
    type: 'continuous',
    min: 6.0,
    max: 10.0,
    default: 8.0,
    step: 0.5,
    priority: 2,
    unit: '%',
    description: '投资门槛收益率。一体化IRR需超过此值才算成立',
    source: '行业惯例'
  },

  // ============================================================
  // B. 硬件规格参数（离散值，由机械装置决定）
  // ============================================================

  /** 每站电池数量（块） */
  batPerStation: {
    type: 'discrete',
    options: [5, 14, 30],
    default: 14,
    priority: 1,
    unit: '块',
    description: '5=小型站 / 14=标准站 / 30=大型站。巧克力换电块机械规格',
    source: '宁德时代官方规格'
  },

  /** 每站周转电池数量（块），内部结算用 */
  internalBatPerStation: {
    type: 'discrete',
    options: [5, 14, 30],
    default: 14,
    priority: 2,
    unit: '块',
    description: '与batPerStation一致，或独立设置（用于分拆结算）',
    source: '宁德时代官方规格'
  },

  // ============================================================
  // C. 内部结算参数（连续值，用于分拆利润分配）
  // ============================================================

  /** 周转电池月租（元/月/块） */
  internalBatRentMonthly: {
    type: 'continuous',
    min: 200,
    max: 360,
    default: 240,
    step: 10,
    priority: 1,
    unit: '元/月/块',
    description: '换电站向电池银行租赁周转电池的月租金。调节站vs银行利润分配',
    source: '财务模型_修正版.md # 第三部分 分拆逻辑'
  },

  /** 技术服务费（元/年/站） */
  internalTechFeeYearly: {
    type: 'continuous',
    min: 20000,
    max: 100000,
    default: 35000,
    step: 1000,
    priority: 1,
    unit: '元/年/站',
    description: '换电站向电池银行支付的技术服务费。对标蔚能1.37万/年',
    source: '财务模型_修正版.md # 第三部分 分拆逻辑'
  },

  // ============================================================
  // D. 电池残值参数（可在合理范围内微调）
  // ============================================================

  /** 综合折旧系数 */
  batDegradeFactor: {
    type: 'continuous',
    min: 0.55,
    max: 0.70,
    default: 0.63,
    step: 0.01,
    priority: 2,
    unit: '',
    description: '旧电池用于储能市场的价值打折系数',
    source: '财务模型_修正版.md # 附录A'
  },

  /** 储能市场可用度系数 */
  batEssAvailability: {
    type: 'continuous',
    min: 0.45,
    max: 0.65,
    default: 0.55,
    step: 0.01,
    priority: 2,
    unit: '',
    description: '考虑电池一致性、安全性筛选后的可用比例',
    source: '财务模型_修正版.md # 附录A'
  },

  // ============================================================
  // E. 电芯成本参数（时序数据，基准年可调）
  // ============================================================

  /** 电芯成本基准值（元/Wh），2026年 */
  batCellCostY0: {
    type: 'continuous',
    min: 0.30,
    max: 0.50,
    default: 0.38,
    step: 0.01,
    priority: 1,
    unit: '元/Wh',
    description: '2026年LFP动力电芯成本。TrendForce: 0.34-0.38；BNEF: 2035年0.29',
    source: '电池价格口径统一与pack价格参考.md'
  },

  /** 电芯年降幅（%） */
  cellCostDecline: {
    type: 'continuous',
    min: 3.0,
    max: 8.0,
    default: 5.8,
    step: 0.1,
    priority: 2,
    unit: '%/年',
    description: '年复合降幅。BNEF中性5.8%，乐观3%，悲观8%',
    source: 'BNEF 2025-12'
  },

  // ============================================================
  // F. 固定参数（不参与调参，仅供引用）
  // ============================================================

  sohPrivateExit: {
    type: 'fixed',
    value: 0.88,
    unit: '',
    description: '私家车退出换电时SOH（8年，日历老化为主）',
    source: '超换一体.md # Step 2'
  },

  sohOperationalExit: {
    type: 'fixed',
    value: 0.83,
    unit: '',
    description: '营运车退出换电时SOH（3年，循环次数为主）',
    source: '超换一体.md # Step 2'
  },

  batCapKwh: {
    type: 'fixed',
    value: 56,
    unit: 'kWh',
    description: '25#巧克力换电块电池容量',
    source: '宁德时代官方规格'
  },

  swapCoeffMid: {
    type: 'fixed',
    value: 1.175,
    unit: '',
    description: '换电块附加成本系数（中性），市场Pack价×1.175=结算价',
    source: '电池价格口径统一与pack价格参考.md'
  }
};

// ============================================================
// 二、方向一致性约束（软约束）
// 说明：这些不是数学公式，而是"如果A变大了，B也应该同方向变"的逻辑一致性要求。
// 调参引擎在生成候选参数后，调用 checkConsistency() 检查是否违反约束。
// 违反任一约束的候选参数将被排除。
// ============================================================

Engine.CONSISTENCY_RULES = [
  {
    id: 'network_effect',
    description: '站点密度越高，单站日均换电次数越高（网络效应）',
    condition: function (p, base) {
      // 如果stationCount高于基准，dailySwaps不应低于基准
      if (p.stationCount > base.stationCount && p.dailySwaps < base.dailySwaps) {
        return { valid: false, reason: '站点数增加但日均换电反而下降，违反网络效应' };
      }
      return { valid: true };
    }
  },
  {
    id: 'supercharge_network',
    description: '站点密度越高，超充车辆数越多（网络效应）',
    condition: function (p, base) {
      if (p.stationCount > base.stationCount && p.SC_CARS_PER_STATION < base.SC_CARS_PER_STATION) {
        return { valid: false, reason: '站点数增加但超充车辆反而下降，违反网络效应' };
      }
      return { valid: true };
    }
  },
  {
    id: 'battery_turnover',
    description: '日均换电越高，需要更多周转电池',
    condition: function (p, base) {
      if (p.dailySwaps > base.dailySwaps && p.batPerStation < base.batPerStation) {
        return { valid: false, reason: '换电次数增加但电池数减少，不符合周转逻辑' };
      }
      return { valid: true };
    }
  },
  {
    id: 'energy_demand_correlation',
    description: '日均换电与超充车辆数正相关（补能总需求一致性）',
    condition: function (p, base) {
      var dailySwapsChange = (p.dailySwaps - base.dailySwaps) / base.dailySwaps;
      var scChange = (p.SC_CARS_PER_STATION - base.SC_CARS_PER_STATION) / base.SC_CARS_PER_STATION;
      // 方向不一致（一个涨一个跌）且偏离超过15%，视为违反
      if (dailySwapsChange * scChange < 0 && Math.abs(dailySwapsChange) > 0.15 && Math.abs(scChange) > 0.15) {
        return { valid: false, reason: '换电和超充需求的变动方向相反且幅度较大，不符合补能总需求一致性' };
      }
      return { valid: true };
    }
  },
  {
    id: 'cost_margin_tradeoff',
    description: '电芯成本下降时，毛利率应有上升空间（或至少不降）',
    condition: function (p, base) {
      if (p.batCellCostY0 < base.batCellCostY0 && p.batGrossMargin < base.batGrossMargin) {
        return { valid: false, reason: '电芯成本下降但毛利率反而下降，不符合成本-毛利逻辑' };
      }
      return { valid: true };
    }
  },
  {
    id: 'scale_rent_bargain',
    description: '站点规模越大，租金议价能力越强',
    condition: function (p, base) {
      if (p.stationCount > base.stationCount && p.rentSqrm > base.rentSqrm) {
        return { valid: false, reason: '站点增多但租金反而上涨，违反规模化议价逻辑' };
      }
      return { valid: true };
    }
  },
  {
    id: 'family_premium',
    description: '家庭包占比越高，用户平均月租越高',
    condition: function (p, base) {
      if (p.famRatio > base.famRatio && p.avgMonthlyRent < base.avgMonthlyRent) {
        return { valid: false, reason: '家庭包占比增加但平均月租下降，不符合定价逻辑' };
      }
      return { valid: true };
    }
  },
  {
    id: 'bat_per_station_discrete',
    description: '每站电池数只能是 5/14/30 三个离散值',
    condition: function (p) {
      var valid = [5, 14, 30].indexOf(p.batPerStation) !== -1;
      if (!valid) {
        return { valid: false, reason: 'batPerStation=' + p.batPerStation + ' 不在允许值[5, 14, 30]中' };
      }
      return { valid: true };
    }
  },
  {
    id: 'internal_bat_per_station_discrete',
    description: '每站周转电池数只能是 5/14/30 三个离散值',
    condition: function (p) {
      var valid = [5, 14, 30].indexOf(p.internalBatPerStation) !== -1;
      if (!valid) {
        return { valid: false, reason: 'internalBatPerStation=' + p.internalBatPerStation + ' 不在允许值[5, 14, 30]中' };
      }
      return { valid: true };
    }
  }
];

// ============================================================
// 三、合法性检查函数
// ============================================================

/**
 * 检查一组候选参数是否违反方向一致性约束
 * @param {Object} p - 候选参数对象
 * @param {Object} base - 基准参数（默认值）
 * @returns {Object} { valid: boolean, violations: Array }
 */
Engine.checkConsistency = function (p, base) {
  base = base || Engine.getDefaultParams();
  var violations = [];

  for (var i = 0; i < Engine.CONSISTENCY_RULES.length; i++) {
    var rule = Engine.CONSISTENCY_RULES[i];
    var result = rule.condition(p, base);
    if (!result.valid) {
      violations.push({ ruleId: rule.id, description: rule.description, reason: result.reason });
    }
  }

  return {
    valid: violations.length === 0,
    violations: violations
  };
};

/**
 * 获取默认参数对象（以PARAM_SPEC中的default值填充）
 * @returns {Object} 默认参数
 */
Engine.getDefaultParams = function () {
  var params = {};
  var keys = Object.keys(Engine.PARAM_SPEC);
  for (var i = 0; i < keys.length; i++) {
    var key = keys[i];
    var spec = Engine.PARAM_SPEC[key];
    if (spec.type === 'fixed') {
      params[key] = spec.value;
    } else if (spec.type === 'discrete') {
      params[key] = spec.default;
    } else if (spec.type === 'continuous') {
      params[key] = spec.default;
    }
  }
  return params;
};

/**
 * 获取所有可调参数列表（排除computed和fixed类型）
 * @returns {Array} 可调参数名称数组
 */
Engine.getTunableParams = function () {
  var tunable = [];
  var keys = Object.keys(Engine.PARAM_SPEC);
  for (var i = 0; i < keys.length; i++) {
    var spec = Engine.PARAM_SPEC[keys[i]];
    if (spec.type === 'continuous' || spec.type === 'discrete') {
      tunable.push(keys[i]);
    }
  }
  return tunable;
};
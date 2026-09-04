/**
 * ============================================================
 * engine/valuation.js — 估值模型（SOTP 主锚定 + 交叉验证）
 * ============================================================
 *
 * 估值方法论：
 *   1. 主锚定：分部估值法（SOTP），将制造与运营业务分离估值
 *      - 电池制造业务（PE 15-20x，参考宁德时代/DK/比亚迪生产端）
 *      - 资产运营业务（PE 8-12x，参考蔚能/中石油/中石化运营端）
 *   2. 交叉验证：DCF / PE / PB 作为可比参照
 *      - DCF：基于自由现金流折现，验证长期盈利可持续性
 *      - PE：基于可比公司市盈率，验证市场情绪合理性
 *      - PB：基于净资产，验证资产价值支撑
 *   3. 估值范围：综合各方法，输出可接受区间（下限~上限）
 *
 * 加载顺序：在 constants.js 之后
 * ============================================================
 */
var Engine = window.Engine || {};

/**
 * 计算分部估值（SOTP — 主锚定方法）
 *
 * 将不同业务按各自适宜的 PE 倍数分别估值后加总
 *
 * @param {Array} segments - 业务分部数组，每项包含：
 *   { name: string, profit: number, pe: number, [description]: string }
 * @returns {Object} { total: 总估值, segments: 分部明细, method: 'SOTP' }
 *
 * 示例：
 *   calcSOTP([{name:'电池制造', profit:800, pe:15}, {name:'资产运营', profit:200, pe:8}])
 *   → { total: 13600, segments: [...], method: 'SOTP' }
 */
Engine.calcSOTP = function (segments) {
  var total = 0;
  var details = [];
  for (var i = 0; i < segments.length; i++) {
    var seg = segments[i];
    var value = seg.profit * seg.pe;
    total += value;
    details.push({
      name: seg.name,
      profit: seg.profit,
      pe: seg.pe,
      value: value,
      description: seg.description || ''
    });
  }
  return {
    total: total,
    segments: details,
    method: 'SOTP'
  };
};

/**
 * 计算 DCF 估值（交叉验证）
 *
 * 基于自由现金流折现和永续增长模型
 *
 * @param {Object} opts - DCF 参数
 *   opts.fcf           - 自由现金流数组（未来N年，亿元）
 *   opts.wacc          - 加权平均资本成本（小数，默认 0.09）
 *   opts.terminalGrowth - 永续增长率（小数，默认 0.025）
 *   opts.explicitYears - 显式预测期年数（默认与 fcf 长度一致）
 * @returns {Object} { method: 'DCF', value: 总估值, pvExplicit: 显式期现值, terminalValue: 终值现值 }
 */
Engine.calcDCF = function (opts) {
  var fcf = opts.fcf || [];
  var wacc = opts.wacc || 0.09;
  var terminalGrowth = opts.terminalGrowth || 0.025;
  var explicitYears = opts.explicitYears || fcf.length;

  var pvExplicit = 0;
  for (var i = 0; i < Math.min(explicitYears, fcf.length); i++) {
    pvExplicit += fcf[i] / Math.pow(1 + wacc, i + 1);
  }

  // 终值 = 最后一年FCF × (1 + g) / (WACC - g)
  var lastFCF = fcf[Math.min(explicitYears, fcf.length) - 1] || 0;
  var terminalValue = 0;
  if (wacc > terminalGrowth && lastFCF > 0) {
    terminalValue = (lastFCF * (1 + terminalGrowth)) / (wacc - terminalGrowth);
    terminalValue = terminalValue / Math.pow(1 + wacc, explicitYears);
  }

  return {
    method: 'DCF',
    value: pvExplicit + terminalValue,
    pvExplicit: pvExplicit,
    terminalValue: terminalValue,
    wacc: wacc,
    terminalGrowth: terminalGrowth
  };
};

/**
 * 计算 PE 估值（交叉验证）
 *
 * 基于可比公司市盈率 × 全年净利润
 *
 * @param {number} netProfit    - 全年净利润（亿元）
 * @param {Object} opts         - PE 参数
 *   opts.peLow  - 可比PE下限（默认 8）
 *   opts.peHigh - 可比PE上限（默认 20）
 * @returns {Object} { method: 'PE', valueLow, valueHigh, peLow, peHigh }
 */
Engine.calcPE = function (netProfit, opts) {
  opts = opts || {};
  var peLow  = opts.peLow || 8;
  var peHigh = opts.peHigh || 20;
  return {
    method: 'PE',
    valueLow: netProfit * peLow,
    valueHigh: netProfit * peHigh,
    peLow: peLow,
    peHigh: peHigh
  };
};

/**
 * 计算 PB 估值（交叉验证）
 *
 * 基于可比公司市净率 × 净资产
 *
 * @param {number} netAsset     - 净资产（亿元）
 * @param {Object} opts         - PB 参数
 *   opts.pbLow  - 可比PB下限（默认 0.8）
 *   opts.pbHigh - 可比PB上限（默认 2.0）
 * @returns {Object} { method: 'PB', valueLow, valueHigh, pbLow, pbHigh }
 */
Engine.calcPB = function (netAsset, opts) {
  opts = opts || {};
  var pbLow  = opts.pbLow || 0.8;
  var pbHigh = opts.pbHigh || 2.0;
  return {
    method: 'PB',
    valueLow: netAsset * pbLow,
    valueHigh: netAsset * pbHigh,
    pbLow: pbLow,
    pbHigh: pbHigh
  };
};

/**
 * 综合估值分析（主锚定 + 交叉验证）
 *
 * 核心逻辑：
 *   1. 以 SOTP 为主锚定值
 *   2. 以 DCF / PE / PB 为交叉验证
 *   3. 输出估值范围（下限 = min(各方法下限), 上限 = max(各方法上限)）
 *   4. 标注差异率（各交叉验证方法 vs 主锚定）
 *
 * @param {Object} opts - 估值参数
 *   opts.segments       - SOTP 分部数组（必填）：[{name, profit, pe}]
 *   opts.fcf            - DCF 自由现金流数组（可选）
 *   opts.wacc           - WACC（可选，默认 0.09）
 *   opts.terminalGrowth - 永续增长率（可选，默认 0.025）
 *   opts.netProfit      - 全年净利润（可选，PE 验证用）
 *   opts.peLow / opts.peHigh - PE 倍数范围（可选）
 *   opts.netAsset       - 净资产（可选，PB 验证用）
 *   opts.pbLow / opts.pbHigh - PB 倍数范围（可选）
 *
 * @returns {Object} 综合估值分析结果
 *   {
 *     anchor: { method: 'SOTP', value: number },
 *     crossChecks: [{ method, value, [valueLow], [valueHigh], deviation, note }],
 *     range: { low: number, high: number, mid: number }
 *   }
 *
 * 示例：
 *   analyzeValuation({
 *     segments: [{name:'制造', profit:800, pe:15}, {name:'运营', profit:200, pe:8}],
 *     fcf: [100, 120, 140, 160, 180],
 *     netProfit: 1000
 *   })
 *   → { anchor: { method: 'SOTP', value: 13600 }, crossChecks: [...], range: {...} }
 */
Engine.analyzeValuation = function (opts) {
  // 1. 主锚定：SOTP
  var sotp = Engine.calcSOTP(opts.segments || []);
  var anchorValue = sotp.total;

  var crossChecks = [];

  // 2. 交叉验证：DCF
  if (opts.fcf && opts.fcf.length > 0) {
    var dcf = Engine.calcDCF({
      fcf: opts.fcf,
      wacc: opts.wacc || 0.09,
      terminalGrowth: opts.terminalGrowth || 0.025
    });
    var dcfDeviation = anchorValue > 0 ? ((dcf.value - anchorValue) / anchorValue * 100) : 0;
    crossChecks.push({
      method: 'DCF',
      value: dcf.value,
      deviation: dcfDeviation,
      note: dcfDeviation > 20 ? 'DCF显著高于主锚定，需关注长期增长假设合理性' :
            dcfDeviation < -20 ? 'DCF显著低于主锚定，需关注短期盈利预测是否保守' :
            '与主锚定大致吻合'
    });
  }

  // 3. 交叉验证：PE
  if (typeof opts.netProfit !== 'undefined') {
    var pe = Engine.calcPE(opts.netProfit, { peLow: opts.peLow, peHigh: opts.peHigh });
    var peMid = (pe.valueLow + pe.valueHigh) / 2;
    var peDeviation = anchorValue > 0 ? ((peMid - anchorValue) / anchorValue * 100) : 0;
    crossChecks.push({
      method: 'PE',
      valueLow: pe.valueLow,
      valueHigh: pe.valueHigh,
      valueMid: peMid,
      deviation: peDeviation,
      note: anchorValue >= pe.valueLow && anchorValue <= pe.valueHigh ?
            '主锚定在PE可比区间内，估值合理' :
            anchorValue < pe.valueLow ? '主锚定低于PE可比下限，SOTP偏保守' :
            '主锚定高于PE可比上限，SOTP偏乐观'
    });
  }

  // 4. 交叉验证：PB
  if (typeof opts.netAsset !== 'undefined') {
    var pb = Engine.calcPB(opts.netAsset, { pbLow: opts.pbLow, pbHigh: opts.pbHigh });
    var pbMid = (pb.valueLow + pb.valueHigh) / 2;
    var pbDeviation = anchorValue > 0 ? ((pbMid - anchorValue) / anchorValue * 100) : 0;
    crossChecks.push({
      method: 'PB',
      valueLow: pb.valueLow,
      valueHigh: pb.valueHigh,
      valueMid: pbMid,
      deviation: pbDeviation,
      note: 'PB作为资产端交叉验证，通常不直接用于估值定价'
    });
  }

  // 5. 计算估值范围
  var allValues = [anchorValue];
  for (var i = 0; i < crossChecks.length; i++) {
    var cc = crossChecks[i];
    if (typeof cc.valueLow !== 'undefined') {
      allValues.push(cc.valueLow, cc.valueHigh);
    } else if (typeof cc.value !== 'undefined') {
      allValues.push(cc.value);
    }
  }
  var rangeLow  = Math.min.apply(null, allValues);
  var rangeHigh = Math.max.apply(null, allValues);
  var rangeMid  = (rangeLow + rangeHigh) / 2;

  return {
    anchor: { method: 'SOTP', value: anchorValue },
    crossChecks: crossChecks,
    range: {
      low: rangeLow,
      high: rangeHigh,
      mid: rangeMid,
      spread: anchorValue > 0 ? ((rangeHigh - rangeLow) / rangeLow * 100) : 0
    }
  };
};

/**
 * 电池银行盈亏平衡（日换电次数口径）：二分法找到PBT=0时的日换电次数
 * @param {Object} p - 参数对象
 * @returns {Object} { breakeven, breakeven_raw }
 */
Engine.calcBatteryBankBreakeven = function (p) {
  var maxX = p.op_mode === '24h' ? 140 : 125;
  var calcPBT = function (x) {
    var p2 = { ...p, daily_swaps: x };
    return Engine.calcBatteryBank(p2).yr1.pbt;
  };
  var pbtMax = calcPBT(maxX);
  var pbt0 = calcPBT(0);
  var be = Infinity, beRaw = Infinity;
  if (pbtMax > 0 && pbt0 < 0) {
    var lo = 0, hi = maxX;
    for (var i = 0; i < 50; i++) {
      var mid = (lo + hi) / 2;
      var pm = calcPBT(mid);
      if (Math.abs(pm) < 10) { lo = mid; break; }
      if (pm < 0) lo = mid; else hi = mid;
    }
    beRaw = (lo + hi) / 2;
    be = Math.ceil(beRaw);
  } else if (pbt0 >= 0) { beRaw = 0; be = 0; }
  return { breakeven: be, breakeven_raw: beRaw };
};

/**
 * 电池银行盈亏平衡（站点规模口径）：二分法找到PBT=0时的最小站点数
 * 电池银行是网络型业务，盈亏取决于固定团队成本能否被足够多的站点分摊
 * 自变量为total_stations（站点总数），团队规模按密度模型自动推算
 * @param {Object} p - 参数对象
 * @returns {Object} { breakeven, breakeven_raw }
 */
Engine.calcBatteryBankScaleBreakeven = function (p) {
  var minStns = 1;
  var maxStns = 200000;
  // 按指定站点规模计算电池银行PBT（强制使用密度模型推算团队，不绑定用户滑块值）
  var calcPBT = function (stns) {
    var p2 = { ...p, total_stations: stns, bank_team_size: 0 };
    return Engine.calcBatteryBank(p2).yr1.pbt;
  };
  var pbtMin = calcPBT(minStns);  // 1座站时每站分摊全部团队成本 → PBT必为负
  var pbtMax = calcPBT(maxStns);  // 20万站时每站分摊极低 → PBT应为正
  var be = Infinity, beRaw = Infinity;
  if (pbtMax > 0 && pbtMin < 0) {
    var lo = minStns, hi = maxStns;
    for (var i = 0; i < 50; i++) {
      var mid = Math.round((lo + hi) / 2);
      var pm = calcPBT(mid);
      if (Math.abs(pm) < 1000) { lo = mid; break; }
      if (pm < 0) lo = mid; else hi = mid;
    }
    beRaw = lo;
    be = Math.ceil((lo + hi) / 2);
  } else if (pbtMin >= 0) { beRaw = 1; be = 1; }  // 1座站也盈利（极端情况：站点投资极低或电池租金极高）
  return { breakeven: be, breakeven_raw: beRaw };
};

/**
 * 一体化盈亏平衡搜索：二分法找到PBT=0时的日换电次数
 * @param {Object} p - 参数对象
 * @returns {Object} { breakeven, breakeven_raw }
 */
Engine.calcIntegratedBreakeven = function (p) {
  var maxX = p.op_mode === '24h' ? 140 : 125;
  var calcPBT = function (x) {
    var p2 = { ...p, daily_swaps: x };
    return Engine.calcIntegrated(p2).yr1.pbt;
  };
  var pbtMax = calcPBT(maxX);
  var pbt0 = calcPBT(0);
  var be = Infinity, beRaw = Infinity;
  if (pbtMax > 0 && pbt0 < 0) {
    var lo = 0, hi = maxX;
    for (var i = 0; i < 50; i++) {
      var mid = (lo + hi) / 2;
      var pm = calcPBT(mid);
      if (Math.abs(pm) < 10) { lo = mid; break; }
      if (pm < 0) lo = mid; else hi = mid;
    }
    beRaw = (lo + hi) / 2;
    be = Math.ceil(beRaw);
  } else if (pbt0 >= 0) { beRaw = 0; be = 0; }
  return { breakeven: be, breakeven_raw: beRaw };
};

/**
 * 计算关联交易制造利润（按年映射）
 * 电池从工厂卖给电池银行是关联交易，合并报表时需抵消
 * @param {Object} p - 参数对象
 * @returns {Object} 年份 → 制造利润（亿元）的映射
 */
Engine.calcIntercompanyMfgProfit = function (p) {
  var neutral = Engine.calcMfgScenario('中性', p.total_stations, 100000);
  var result = {};
  for (var i = 0; i < neutral.rows.length; i++) {
    var r = neutral.rows[i];
    result[r.yrNum] = r.mfgProfit / 1e8;
  }
  var steadyYr = Engine.BASE_YEAR + Engine.BAT_REPLACE_YEAR + 4;
  if (!result[steadyYr]) {
    result[steadyYr] = neutral.profitReplace / 1e8;
  }
  return result;
};

// ============================================================
// 两分法估值（制造+运营）（含关联交易抵消）
// 核心逻辑：电池从工厂卖给电池银行是关联交易，合并报表时制造利润需抵消
// - 无换电：制造利润含所有电池（含换电电池作为第三方销售）
// - 有换电：制造利润需扣除关联交易部分，但新增运营利润
// 参数定义见 engine/constants.js §十三
// ============================================================

// 制造利润时间路径（亿元）
Engine.getMfgProfitPath = function () {
  var buildCompleteYr = Engine.BASE_YEAR + Engine.MFG_BUILD_COMPLETE_OFFSET;
  var fullLoadYr = Engine.BASE_YEAR + Engine.MFG_FULL_LOAD_OFFSET;
  var matureYr = Engine.BASE_YEAR + Engine.BAT_REPLACE_YEAR + Engine.MFG_MATURE_OFFSET;
  var path = {};
  path[Engine.BASE_YEAR] = Engine.MFG_BASE_PROFIT;
  path[buildCompleteYr] = Engine.MFG_BUILD_COMPLETE_PROFIT;
  path[fullLoadYr] = Engine.MFG_FULL_LOAD_PROFIT;
  path[matureYr] = Engine.MFG_MATURE_PROFIT;
  return path;
};

// 制造PE时间路径（动态，基于用户假设参数）
Engine.getMfgPEPath = function (mfgPeSlider) {
  var basePE = mfgPeSlider || 21;
  // 远期（2035年）锚定台积电17×，但最低不低于15×
  var terminalPE = Math.max(Engine.MFG_PE_TERMINAL_MIN, Math.round(basePE * Engine.MFG_PE_DECAY_TERMINAL)); // 21× → 16×
  var path = {};
  path[Engine.BASE_YEAR] = basePE;
  path[Engine.BASE_YEAR + Engine.MFG_BUILD_COMPLETE_OFFSET] = Math.round(basePE * Engine.MFG_PE_DECAY_BUILD);
  path[Engine.BASE_YEAR + Engine.BAT_REPLACE_YEAR] = Math.round(basePE * Engine.MFG_PE_DECAY_SWAP);
  path[Engine.BASE_YEAR + Engine.BAT_REPLACE_YEAR + Engine.MFG_MATURE_OFFSET] = terminalPE;
  return path;
};

// 通用插值函数（从路径对象中按年份插值）
function interpPath(path, yr) {
  var keys = Object.keys(path).map(Number).sort(function (a, b) { return a - b; });
  if (keys.length === 0) return 0;
  if (yr <= keys[0]) return path[keys[0]] || 0;
  if (yr >= keys[keys.length - 1]) return path[keys[keys.length - 1]] || 0;
  for (var i = 0; i < keys.length - 1; i++) {
    if (yr >= keys[i] && yr <= keys[i + 1]) {
      var t = (yr - keys[i]) / (keys[i + 1] - keys[i]);
      return (path[keys[i]] || 0) + t * ((path[keys[i + 1]] || 0) - (path[keys[i]] || 0));
    }
  }
  return path[keys[keys.length - 1]] || 0;
}

// 两分法估值（含关联交易抵消）
Engine.calcValuation = function (p) {
  var d = Engine.calcCombinedScaleRevenue(p);
  var neutral = d.multiScenario[1];
  var opProfit = neutral.catl_annual / 1e8; // 运营利润（亿元）

  var interco = Engine.calcIntercompanyMfgProfit(p);
  var mfgProfitPath = Engine.getMfgProfitPath();
  var mfgPEPath = Engine.getMfgPEPath(p.mfg_pe);

  // 三阶段估值跃迁
  // 阶段年份根据建设节奏动态判定
  var userOpPE = p.op_pe || 30;
  var pace = Engine.calcConstructionPace(p.total_stations, Engine.TARGET_STATIONS);

  // 动态判定阶段二年份：站数首次达到阈值
  var stage2Yr = Engine.BASE_YEAR + Engine.MFG_BUILD_COMPLETE_OFFSET;
  for (var pi = 0; pi < pace.length; pi++) {
    var totalSt = pace[pi].self + pace[pi].partner;
    if (totalSt >= Engine.PHASE2_STATION_THRESHOLD) {
      stage2Yr = parseInt(pace[pi].label);
      break;
    }
  }

  // 动态判定阶段三年份：实际建设完成年份 + 爬坡年数
  // 注意：pace数组包含延伸的稳态年份，需找到站数最后一次增长的年份
  var lastBuildYear = Engine.BASE_YEAR + Engine.MFG_BUILD_COMPLETE_OFFSET;
  for (var pi2 = 1; pi2 < pace.length; pi2++) {
    var prevTotal = pace[pi2 - 1].self + pace[pi2 - 1].partner;
    var currTotal = pace[pi2].self + pace[pi2].partner;
    if (currTotal > prevTotal) {
      lastBuildYear = parseInt(pace[pi2].label);
    } else {
      break; // 站数不再增长，建设完成
    }
  }
  var stage3Yr = lastBuildYear + Engine.PHASE3_RAMP_YEARS;

  // 阶段二运营利润比例：按站数达产比例线性插值
  // 逻辑：阶段二是临界信号年，此时站数刚阙值，利用率处于爬坡期
  // 运营利润 = 稳态运营利润 × (当前站数 / 最终站数) × 利用率折扣
  var stage2Stations = 0;
  for (var pi3 = 0; pi3 < pace.length; pi3++) {
    if (parseInt(pace[pi3].label) === stage2Yr) {
      stage2Stations = pace[pi3].self + pace[pi3].partner;
      break;
    }
  }
  var stage2OpProfitRatio = (stage2Stations / Engine.TARGET_STATIONS) * Engine.PHASE2_UTILIZATION_FACTOR;
  stage2OpProfitRatio = Math.max(Engine.PHASE2_UTILIZATION_MIN, Math.min(Engine.PHASE2_UTILIZATION_MAX, stage2OpProfitRatio));

  var stages = [
    { yr: Engine.BASE_YEAR, label: '阶段一：纯制造', mfgPE: interpPath(mfgPEPath, Engine.BASE_YEAR), opPE: Engine.PHASE1_OP_PE, opProfit: 0 },
    { yr: stage2Yr, label: '阶段二：临界信号', mfgPE: interpPath(mfgPEPath, stage2Yr), opPE: Engine.PHASE2_OP_PE, opProfit: opProfit * stage2OpProfitRatio },
    { yr: stage3Yr, label: '阶段三：相变完成', mfgPE: interpPath(mfgPEPath, stage3Yr), opPE: userOpPE, opProfit: opProfit }
  ];

  for (var s = 0; s < stages.length; s++) {
    var st = stages[s];
    // 无换电基线：制造利润含所有电池（换电电池作为第三方销售）
    st.mfgProfitGross = interpPath(mfgProfitPath, st.yr);
    // 关联交易抵消：电池卖给电池银行，合并报表时制造利润需扣除
    st.intercoProfit = interpPath(interco, st.yr);
    // 抵消后制造利润
    st.mfgProfit = st.mfgProfitGross - st.intercoProfit;
    st.mfgCap = st.mfgProfit * st.mfgPE;
    st.opCap = st.opProfit * st.opPE;
    st.totalCap = st.mfgCap + st.opCap;
    // 无换电基线市值（全部按制造PE估值）
    st.baselineCap = st.mfgProfitGross * st.mfgPE;
    // 相变增值
    st.phasePremium = st.totalCap - st.baselineCap;
  }

  // 敏感性矩阵：换电次数 × 运营PE → 总市值（万亿）
  var swapLevels = Engine.SENSITIVITY_SWAP_LEVELS;
  var swapLabels = ['悲观(' + swapLevels[0] + '次)', '中性(' + swapLevels[1] + '次)', '乐观(' + swapLevels[2] + '次)'];
  var peBase = p.op_pe || 30;
  var peOffset = Engine.SENSITIVITY_PE_OFFSET;
  var peLevels = [peBase - peOffset, peBase, peBase + peOffset];
  var peLabels = ['保守' + (peBase - peOffset) + '×', '中性' + peBase + '×', '乐观' + (peBase + peOffset) + '×'];
  // 稳态年抵消后制造市值
  var steadyStateValYear = Engine.BASE_YEAR + Engine.BAT_REPLACE_YEAR;
  var mfgProfitSteadyAdj = interpPath(mfgProfitPath, steadyStateValYear) - interpPath(interco, steadyStateValYear);
  var mfgCapSteady = mfgProfitSteadyAdj * interpPath(mfgPEPath, steadyStateValYear);
  // 无换电基线
  var baselineCapSteady = interpPath(mfgProfitPath, steadyStateValYear) * interpPath(mfgPEPath, steadyStateValYear);

  var sensitivity = [];
  for (var si = 0; si < swapLevels.length; si++) {
    var row = [];
    var pSwap = {};
    for (var k in p) { pSwap[k] = p[k]; }
    pSwap.daily_swaps = swapLevels[si];
    var dSwap = Engine.calcCombinedScaleRevenue(pSwap);
    var opProfitSwap = dSwap.multiScenario[1].catl_annual / 1e8;
    for (var pi = 0; pi < peLevels.length; pi++) {
      row.push(mfgCapSteady + opProfitSwap * peLevels[pi]);
    }
    sensitivity.push({ label: swapLabels[si], opProfit: opProfitSwap, values: row });
  }

  return { stages: stages, sensitivity: sensitivity, mfgCapSteady: mfgCapSteady, baselineCapSteady: baselineCapSteady, opProfit: opProfit, peLevels: peLevels, peLabels: peLabels, swapLabels: swapLabels, interco: interco };
};

// ============================================================
// 换电 EBITDA 估值（三口径 + 倍数敏感性）
// ------------------------------------------------------------
// 重要方法论修正（2026-08-19）：
//   初版曾把"控制权口径（整块 EBITDA 不扣债）"作为主锚，但深扒行业先例后发现
//   这是错的——无论控股还是 GP，母公司市值对应的利润基础都是"自己能分到的"，
//   不是控制的总利润：
//   1) 会计硬规则：权益法下按"被投资方归母净利润×持股"确认，不含少数股东损益
//      （https://www.zhihu.com/question/659361899）；合并报表虽并表100%但要扣少数股东损益。
//   2) YieldCo/NextEra：母公司【不合并】YieldCo EBITDA，只确认 ①dropdown出售对价
//      ②IDR分成(边际25-50%) ③股权分红（https://www.simplysafedividends.com/.../yieldcos）。
//   3) Brookfield BAM：市值按 Fee-Related Earnings（管理费+AUM+carry）给~18-22×，
//      【完全不并表】底层$1万亿资产（https://www.stocktitan.net/sec-filings/BAM/...）。
//   4) 三井/J-REIT：非轻资产转型，是加重资产+降杠杆，管理业务仅补充（4:4:2），
//      不能当轻资产托管先例（https://hfri.phbs.pku.edu.cn/info/1711/13811.htm）。
//   结论：宁德当前为"直接合股40%"法律形式，经济实质=分40%归母，与GP收carry趋同。
//   故【equity(40%)才是当前架构基准】；control_whole 仅作"未来退为GP轻资产"的
//   期权上限参考，绝非现状；gp_light 才是真正"轻资产估值"（管理费+carry+持股，非整块EV）。
//   参考：长城证券 YieldCo 研报 https://stock.finance.sina.com.cn/stock/go.php/vReport_Show/kind/lastest/rptid/770407328376/index.phtml
//
// @param {Object} opts
//   opts.ebitdaWhole   - 整块（合并）年 EBITDA，亿元
//   opts.projectDebt   - 项目层债务，亿元（equity 口径扣减）
//   opts.catlEquity    - 宁德在权益中占比（现状0.40；彻底退出后保留小股权，默认0.20）
//   opts.multiples     - 倍数数组，默认 [18,20,22,25]
//   opts.feeRate       - GP管理费占EV(资产规模)比，默认0.01（1%，参考凯德CLI全口径82bps取含调度溢价）
//   opts.hurdle        - carry计提基准收益率(cap rate)，默认0.06（6%，全市场储能要求回报）
//   opts.carryRate     - carry占"超额收益(EBITDA−EV×hurdle)"比，默认0.25（25%，取YieldCo IDR下限）
//   opts.exitEquity    - 退出前原持股（默认0.40，用于算一次性处置增益）
//   opts.capRate       - 用 cap rate 倒推 EV（替代倍数），默认null；若设值则 gp_light 改用 ev=ebitdaWhole/capRate
//                        取值参考：中国能源REITs收益率~8%(0.08)、储能要求回报6%(0.06)、谨慎10%(0.10)
//   opts.mode          - 'equity'（基准）| 'control_whole'（上限参考）| 'gp_light'（轻资产估值）
// @returns {Object} 三口径 × 各倍数矩阵 + 基准锚(equity@18) + gp_light 一次性/可持续拆分
// ============================================================
Engine.calcSwapEBITDAValuation = function (opts) {
  opts = opts || {};
  var ebitdaWhole = opts.ebitdaWhole || 528;     // 默认取 MD §五 营运车合计 EBITDA 528 亿
  var projectDebt = opts.projectDebt || 2147;    // 默认取 MD §五 债务 2,147 亿
  var catlEquity  = typeof opts.catlEquity !== 'undefined' ? opts.catlEquity : 0.20; // 退出后保留小股权
  var exitEquity  = typeof opts.exitEquity !== 'undefined' ? opts.exitEquity : 0.40; // 退出前原持股
  var multiples   = opts.multiples || [18, 20, 22, 25];
  var feeRate     = typeof opts.feeRate !== 'undefined' ? opts.feeRate : 0.01;   // 管理费按EV
  var hurdle      = typeof opts.hurdle !== 'undefined' ? opts.hurdle : 0.06;     // carry基准收益率
  var carryRate   = typeof opts.carryRate !== 'undefined' ? opts.carryRate : 0.25; // 超额分成率
  var capRate     = typeof opts.capRate !== 'undefined' ? opts.capRate : null;   // cap rate 倒推 EV
  var mode        = opts.mode || 'equity';

  // 口径一：权益法（当前合股40%，基准）——扣债后×宁德权益
  // 会计依据：母公司确认的=被投资方归母净利润×持股，不含少数股东损益
  var equity = multiples.map(function (m) {
    var ev = ebitdaWhole * m;
    var equityVal = ev - projectDebt;
    return {
      multiple: m, ev: ev, equityAfterDebt: equityVal,
      catlContribution: equityVal * (exitEquity)   // 现状按原持股40%计基准
    };
  });

  // 口径二：整块控制权（仅作"未来退为GP轻资产"的期权上限参考，非现状）
  var control_whole = multiples.map(function (m) {
    return { multiple: m, ev: ebitdaWhole * m, catlContribution: ebitdaWhole * m };
  });

  // 口径三：GP 轻资产估值（资产出表、保留小股权+GP身份）
  // 拆分"一次性处置增益(脉冲)"与"可持续经常性收入"两本账：
  //   一次性：宁德卖出 (exitEquity−catlEquity) 份额，按 EV 回收，减对应账面成本法 → 处置增益
  //   可持续：①管理费 = EV×feeRate（按资产规模收，非EBITDA）
  //           ②carry = max(0, EBITDA − EV×hurdle) × carryRate（仅超额部分，hurdle=6%）
  //           ③小股权分红 ≈ 年可分现金×catlEquity（宁德年可分现金见§五 ⑦）
  var annualCash = 193; // §五 ⑦宁德年可分现金（亿），来自营运车合计
  var initialCapex = 2429; // MD §五 初装CAPEX合计（亿），作成本法账面锚
  var gp_light = multiples.map(function (m) {
    // EV 来源：优先用 capRate 倒推；否则用倍数
    var ev = (capRate ? ebitdaWhole / capRate : ebitdaWhole * m);
    var soldRatio = exitEquity - catlEquity;
    var disposalGain = Math.max(0, ev * soldRatio - initialCapex * soldRatio); // 一次性（脉冲）
    var fee = ev * feeRate;                                  // 管理费按EV
    var excess = Math.max(0, ebitdaWhole - ev * hurdle);     // 超额收益基数
    var carry = excess * carryRate;                         // carry仅超额部分
    var equityDiv = annualCash * catlEquity;                 // 小股权分红
    return {
      multiple: m, ev: ev, capRate: capRate,
      disposalGain: disposalGain,        // 一次性（脉冲）
      fee: fee, carry: carry, equityDiv: equityDiv,
      recurring: fee + carry + equityDiv, // 可持续经常性
      catlContribution: disposalGain + (fee + carry + equityDiv) // 合计（注：处置增益为一次性，估值时应单独列示）
    };
  });

  // cap-rate 敏感性（0.06/0.08/0.10）：展示 EV、一次性处置增益、可持续经常性
  // 用于回应"中国能源REITs收益率~8%，是否从0.06调到0.08"
  var capSens = [0.06, 0.08, 0.10].map(function (cr) {
    var ev = ebitdaWhole / cr;
    var sold = exitEquity - catlEquity;
    return {
      capRate: cr, ev: ev,
      disposalGain: Math.max(0, ev * sold - initialCapex * sold),
      fee: ev * feeRate,
      carry: Math.max(0, ebitdaWhole - ev * hurdle) * carryRate,
      equityDiv: annualCash * catlEquity,
      recurring: ev * feeRate + Math.max(0, ebitdaWhole - ev * hurdle) * carryRate + annualCash * catlEquity
    };
  });

  // 基准锚：权益法 @18×（现状诚实口径，按原持股40%）
  var anchorEquity18 = Math.max(0, ebitdaWhole * 18 - projectDebt) * exitEquity;

  return {
    method: 'SwapEBITDA(' + mode + ')',
    inputs: { ebitdaWhole: ebitdaWhole, projectDebt: projectDebt, catlEquity: catlEquity,
              exitEquity: exitEquity, multiples: multiples, feeRate: feeRate,
              hurdle: hurdle, carryRate: carryRate, capRate: capRate },
    equity: equity,            // 当前合股40%（基准）
    control_whole: control_whole, // 整块期权上限（仅参考，非现状）
    gp_light: gp_light,        // 未来GP轻资产估值（一次性处置+可持续费）
    capSensitivity: capSens,   // cap-rate 敏感性（0.06/0.08/0.10）
    anchorEquity18: anchorEquity18,
    // 三口径 @18× 对比（gp_light 仅列可持续经常性，处置增益单列脉冲）
    comparison18: {
      equity: anchorEquity18,
      control_whole: ebitdaWhole * 18,
      gp_light_recurring: (function () {
        var ev = (capRate ? ebitdaWhole / capRate : ebitdaWhole * 18);
        return ev * feeRate + Math.max(0, ebitdaWhole - ev * hurdle) * carryRate + annualCash * catlEquity;
      })(),
      gp_light_disposal: (function () {
        var ev = (capRate ? ebitdaWhole / capRate : ebitdaWhole * 18), sold = exitEquity - catlEquity;
        return Math.max(0, ev * sold - 2429 * sold);
      })()
    }
  };
};
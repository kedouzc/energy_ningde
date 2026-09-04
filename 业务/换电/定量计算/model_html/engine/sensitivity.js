/**
 * ============================================================
 * engine/sensitivity.js — 敏感性分析引擎
 * ============================================================
 * 对每个可调参数做 ±10% 扰动，计算对 IRR 的影响幅度（弹性）。
 * 结果按影响力从大到小排序，供 optimizer 优先调影响力大的参数。
 *
 * 依赖：constants.js, params_spec.js, integrated.js, station.js, batteryBank.js
 * ============================================================
 */
var Engine = window.Engine || {};

/**
 * 敏感性分析主函数
 * @param {Object} baseParams - 基准参数，默认使用 ENGINE_PARAM_SPEC 的默认值
 * @param {number} perturbPct - 扰动幅度（%），默认10
 * @param {string} target - 分析目标：'integrated' | 'station' | 'bank'
 * @returns {Object} { analysis: Array, summary: Object }
 *   analysis: 每个参数的分析结果 [{ param, defaultVal, upVal, downVal, irrDefault, irrUp, irrDown, elasticity, rank }]
 *   summary: { topParams: [...], totalElapsed: ms }
 */
Engine.runSensitivity = function (baseParams, perturbPct, target) {
  perturbPct = perturbPct || 10;
  target = target || 'integrated';
  baseParams = baseParams || Engine.getDefaultParams();

  // 获取可调参数列表
  var tunableParams = Engine.getTunableParams();
  var results = [];
  var startTime = Date.now();

  // 先跑一次基准计算
  var baseResult = Engine.runCalc(baseParams, target);

  // 对每个参数做 ±perturbPct 扰动
  for (var i = 0; i < tunableParams.length; i++) {
    var paramName = tunableParams[i];
    var spec = Engine.PARAM_SPEC[paramName];
    if (!spec || spec.type === 'fixed' || spec.type === 'computed') continue;

    var defaultVal = baseParams[paramName] || spec.default;

    // 离散型参数：跳到下一个选项
    if (spec.type === 'discrete') {
      var options = spec.options;
      var idx = options.indexOf(defaultVal);
      var upVal = (idx < options.length - 1) ? options[idx + 1] : defaultVal;
      var downVal = (idx > 0) ? options[idx - 1] : defaultVal;

      var pUp = cloneParams(baseParams);
      pUp[paramName] = upVal;
      var resultUp = Engine.runCalc(pUp, target);

      var pDown = cloneParams(baseParams);
      pDown[paramName] = downVal;
      var resultDown = Engine.runCalc(pDown, target);

      results.push({
        param: paramName,
        type: 'discrete',
        defaultVal: defaultVal,
        upVal: upVal,
        downVal: downVal,
        irrDefault: baseResult.irr,
        irrUp: resultUp.irr,
        irrDown: resultDown.irr,
        irrDeltaUp: resultUp.irr - baseResult.irr,
        irrDeltaDown: resultDown.irr - baseResult.irr,
        npvDefault: baseResult.npv,
        npvUp: resultUp.npv,
        npvDown: resultDown.npv,
        description: spec.description,
        unit: spec.unit
      });
      continue;
    }

    // 连续型参数：按比例扰动，但限制在[min, max]范围内
    var upVal = Math.min(spec.max, defaultVal * (1 + perturbPct / 100));
    var downVal = Math.max(spec.min, defaultVal * (1 - perturbPct / 100));

    // 向上扰动
    var pUp = cloneParams(baseParams);
    pUp[paramName] = upVal;
    var resultUp = Engine.runCalc(pUp, target);

    // 向下扰动
    var pDown = cloneParams(baseParams);
    pDown[paramName] = downVal;
    var resultDown = Engine.runCalc(pDown, target);

    // 计算弹性：IRR变化% / 参数变化%
    var paramChangePct = ((upVal - defaultVal) / defaultVal) * 100;
    var irrChangePct = ((resultUp.irr - baseResult.irr) / Math.abs(baseResult.irr || 0.01)) * 100;
    var elasticity = (paramChangePct !== 0) ? irrChangePct / paramChangePct : 0;

    results.push({
      param: paramName,
      type: 'continuous',
      defaultVal: defaultVal,
      upVal: upVal,
      downVal: downVal,
      irrDefault: baseResult.irr,
      irrUp: resultUp.irr,
      irrDown: resultDown.irr,
      irrDeltaUp: resultUp.irr - baseResult.irr,
      irrDeltaDown: resultDown.irr - baseResult.irr,
      npvDefault: baseResult.npv,
      npvUp: resultUp.npv,
      npvDown: resultDown.npv,
      elasticity: elasticity,
      description: spec.description,
      unit: spec.unit
    });
  }

  // 按 IRR 变化幅度绝对值降序排列
  results.sort(function (a, b) {
    return Math.abs(b.irrDeltaUp) - Math.abs(a.irrDeltaUp);
  });

  var elapsed = Date.now() - startTime;

  return {
    analysis: results,
    summary: {
      target: target,
      baseIRR: baseResult.irr,
      baseNPV: baseResult.npv,
      totalParams: results.length,
      totalElapsedMs: elapsed,
      topParams: results.slice(0, 5).map(function (r) { return r.param; })
    }
  };
};

/**
 * 跑一次计算，返回 IRR 和 NPV
 * @param {Object} params - 参数对象
 * @param {string} target - 'integrated' | 'station' | 'bank'
 * @returns {Object} { irr, npv }
 */
Engine.runCalc = function (params, target) {
  // 将 params_spec 的参数映射到 calcIntegrated 需要的参数格式
  var p = buildCalcParams(params);

  // DEBUG: 打印关键参数
  console.log('[DEBUG runCalc] target=' + target);
  console.log('[DEBUG runCalc] daily_swaps=' + p.daily_swaps + ', fam_ratio=' + p.fam_ratio + ', total_stations=' + p.total_stations + ', discount_rate=' + p.discount_rate);
  console.log('[DEBUG runCalc] spare_bats=' + p.spare_bats + ', spare_rent=' + p.spare_rent + ', cell_cost=' + p.cell_cost + ', station_invest=' + p.station_invest);

  // 用一体化模型计算（根据 target 返回对应结果）
  var integrated = Engine.calcIntegrated(p);

  // DEBUG: 打印计算结果
  console.log('[DEBUG runCalc] integrated.irr=' + integrated.irr + ', integrated.npv=' + integrated.npv);
  console.log('[DEBUG runCalc] st.irr=' + (integrated.st ? integrated.st.irr : 'N/A') + ', bb.irr=' + (integrated.bb ? integrated.bb.irr : 'N/A'));
  console.log('[DEBUG runCalc] st.rev_excl=' + (integrated.st ? integrated.st.rev_excl : 'N/A') + ', bb.rev_excl=' + (integrated.bb ? integrated.bb.rev_excl : 'N/A'));
  console.log('[DEBUG runCalc] total_capex=' + integrated.total_capex + ', yr1.ncf=' + (integrated.yr1 ? integrated.yr1.ncf : 'N/A'));

  if (target === 'integrated') {
    return {
      irr: integrated.irr,
      npv: integrated.npv
    };
  } else if (target === 'station') {
    return {
      irr: integrated.st.irr,
      npv: integrated.st.npv
    };
  } else if (target === 'bank') {
    return {
      irr: integrated.bb.irr,
      npv: integrated.bb.npv
    };
  }

  return { irr: 0, npv: 0 };
};

/**
 * 将 params_spec 格式的参数转换为 calcIntegrated 需要的格式
 * @param {Object} params - params_spec 格式的参数
 * @returns {Object} - calcIntegrated 格式的参数
 */
function buildCalcParams(params) {
  // 将 params_spec 格式（camelCase）映射为 Engine.calcPureStation / calcBatteryBank 所需格式（snake_case）
  // 所有参数优先从 params 读取，未提供时使用中性默认值
  return {
    daily_swaps: params.dailySwaps || 115,
    swap_fee_val: (typeof params.swapFeeVal !== 'undefined') ? params.swapFeeVal : 0.40,
    spare_bats: params.internalBatPerStation || 14,
    spare_rent: params.internalBatRentMonthly || 240,
    tech_service: params.internalTechFeeYearly || 35000,
    station_invest: params.stationInvest || 215,
    op_mode: params.opMode || '16h',
    sc_cars_per_day: params.scCarsPerDay || 40,
    sc_kwh_per_car: params.scKwhPerCar || 40,
    sc_fee_val: (typeof params.scFeeVal !== 'undefined') ? params.scFeeVal : 0.30,
    fam_ratio: normalizeRatio(params.famRatio, 0.90),
    total_stations: params.stationCount || 1000,
    discount_rate: (params.discountRate || 7.5) / 100,  // 百分比 → 小数
    cell_cost: params.batCellCostY0 || 0.38,
    pack_integration_cost: params.packIntegrationCost || 0.100,
    gross_margin: params.grossMargin || 22,
    bat_replace_strategy: params.batReplaceStrategy || 'B',
    bank_team_size: (typeof params.bankTeamSize !== 'undefined') ? params.bankTeamSize : 0  // 0 = 自动根据密度模型推算
  };
}

/**
 * 浅拷贝参数对象
 * @param {Object} obj - 原始参数对象
 * @returns {Object} 拷贝后的对象
 */
function cloneParams(obj) {
  var copy = {};
  var keys = Object.keys(obj);
  for (var i = 0; i < keys.length; i++) {
    copy[keys[i]] = obj[keys[i]];
  }
  return copy;
}

/**
 * 归一化比例值：如果传入的是百分比（>1），自动除以 100
 * 这样无论 model.html 传 0.9 还是 90，都能正确解析
 * @param {number} val - 原始值
 * @param {number} defaultVal - 默认值
 * @returns {number} 归一化后的比例（0~1）
 */
function normalizeRatio(val, defaultVal) {
  if (val === undefined || val === null) return defaultVal;
  if (val > 1) return val / 100;            // 90 → 0.9
  // 处理双重除以100的情况：如 0.009 本应是 0.9
  if (val > 0 && val < 0.5 && val * 100 >= 0.5 && val * 100 <= 0.95) return val * 100;
  return val;
}

/**
 * 格式化敏感性分析结果为可读文本
 * @param {Object} sensitivityResult - runSensitivity 的返回值
 * @returns {string} 格式化的文本
 */
Engine.formatSensitivity = function (sensitivityResult) {
  var lines = [];
  lines.push('========================================');
  lines.push('敏感性分析结果（目标：' + sensitivityResult.summary.target + '）');
  lines.push('========================================');
  lines.push('基准IRR: ' + (sensitivityResult.summary.baseIRR * 100).toFixed(2) + '%');
  lines.push('基准NPV: ' + formatMoney(sensitivityResult.summary.baseNPV));
  lines.push('分析参数数: ' + sensitivityResult.summary.totalParams);
  lines.push('耗时: ' + sensitivityResult.summary.totalElapsedMs + 'ms');
  lines.push('');
  lines.push('排名  参数                    默认值      IRR变化(↑)    IRR变化(↓)    弹性  说明');
  lines.push('----  ----------------------  ----------  ------------  ------------  ----  ----------------------');

  for (var i = 0; i < sensitivityResult.analysis.length; i++) {
    var r = sensitivityResult.analysis[i];
    var rank = (i + 1).toString();
    var param = r.param.padEnd(22);
    var defaultStr = formatVal(r.defaultVal).padEnd(10);
    var upStr = formatPct(r.irrDeltaUp).padEnd(12);
    var downStr = formatPct(r.irrDeltaDown).padEnd(12);
    var elast = (r.elasticity !== undefined) ? r.elasticity.toFixed(3).padEnd(4) : 'N/A'.padEnd(4);
    var desc = (r.description || '').substring(0, 20);

    lines.push(rank.padEnd(4) + '  ' + param + '  ' + defaultStr + '  ' + upStr + '  ' + downStr + '  ' + elast + '  ' + desc);
  }

  lines.push('');
  lines.push('影响力TOP5: ' + sensitivityResult.summary.topParams.join(', '));
  return lines.join('\n');
};

// 格式化辅助函数
function formatPct(val) {
  if (val === undefined || val === null) return 'N/A'.padEnd(12);
  var sign = val >= 0 ? '+' : '';
  return (sign + (val * 100).toFixed(2) + '%').padEnd(12);
}

function formatVal(val) {
  if (typeof val === 'number') {
    if (Math.abs(val) >= 10000) return (val / 10000).toFixed(2) + '万';
    if (Math.abs(val) >= 1000) return val.toFixed(0);
    if (Math.abs(val) < 1) return val.toFixed(3);
    return val.toFixed(1);
  }
  return String(val);
}

function formatMoney(val) {
  if (val === undefined || val === null) return 'N/A';
  if (Math.abs(val) >= 100000000) return (val / 100000000).toFixed(2) + '亿';
  if (Math.abs(val) >= 10000) return (val / 10000).toFixed(2) + '万';
  return val.toFixed(0) + '元';
}
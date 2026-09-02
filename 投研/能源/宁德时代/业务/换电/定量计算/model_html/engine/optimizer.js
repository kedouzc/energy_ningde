/**
 * ============================================================
 * engine/optimizer.js — 自动调参引擎
 * ============================================================
 * 两层优化：
 *   第一层：自动调参使一体化模型成立（integrated IRR > hurdle）
 *   第二层：自动调内部结算参数使分拆后两边各自成立
 *
 * 核心逻辑：
 *   内部结算参数（周转电池月租、技术服务费）仅影响分部 IRR，
 *   不影响一体化 IRR（合并层面内部结算互相抵消）。
 *   因此第二层始终可以基于用户当前参数独立运行。
 *
 * 依赖：constants.js, params_spec.js, sensitivity.js, integrated.js
 * ============================================================
 */
var Engine = window.Engine || {};

/**
 * 运行自动调参（两层）
 * @param {Object} options - 配置选项
 *   options.baseParams       - 起始参数（默认使用 PARAM_SPEC 默认值）
 *   options.hurdleRate       - 一体化门槛收益率（默认 8.0%）
 *   options.stationHurdle    - 站门槛收益率（默认 8.0%）
 *   options.bankHurdle       - 银行门槛收益率（默认 6.0%）
 *   options.maxIterations    - 最大迭代次数（默认 500）
 *   options.layer1Only       - 只跑第一层（默认 false）
 *   options.verbose          - 输出详细日志（默认 false）
 * @returns {Object} 优化结果
 */
Engine.runOptimizer = function (options) {
  options = options || {};
  var baseParams = options.baseParams || Engine.getDefaultParams();
  var hurdleRate = (options.hurdleRate || 8.0) / 100;
  var stationHurdle = (options.stationHurdle || 8.0) / 100;
  var bankHurdle = (options.bankHurdle || 6.0) / 100;
  var maxIterations = options.maxIterations || 500;
  var layer1Only = options.layer1Only || false;
  var skipLayer1 = options.skipLayer1 || false;
  var verbose = options.verbose || false;

  var log = [];
  function addLog(msg) {
    log.push(msg);
    if (verbose) console.log('[Optimizer] ' + msg);
  }

  var startTime = Date.now();
  var currentParams = cloneParams(baseParams);

  // ============================================================
  // 第一步：检查初始参数是否已经可行
  // ============================================================
  addLog('=== 第一步：检查初始参数 ===');
  var initialCalc = Engine.runCalc(currentParams, 'integrated');
  addLog('初始一体化IRR: ' + (initialCalc.irr * 100).toFixed(2) + '%');
  addLog('门槛收益率: ' + (hurdleRate * 100).toFixed(2) + '%');

  if (skipLayer1) {
    addLog('跳过第一层（仅优化内部结算参数，不修改外部参数）。');
  } else if (initialCalc.irr > hurdleRate) {
    addLog('初始参数已满足一体化门槛！跳过第一层优化。');
  } else {
    // ============================================================
    // 第一层：自动调参使一体化模型成立
    // ============================================================
    addLog('=== 第一层：调参使一体化模型成立 ===');

    var sensitivity = Engine.runSensitivity(currentParams, 10, 'integrated');
    var priorityParams = sensitivity.analysis.map(function (r) { return r.param; });
    addLog('参数影响力排序: ' + priorityParams.join(' > '));

    var iteration = 0;
    var found = false;

    for (var i = 0; i < priorityParams.length && !found && iteration < maxIterations; i++) {
      var paramName = priorityParams[i];
      var spec = Engine.PARAM_SPEC[paramName];
      if (!spec || spec.type === 'fixed' || spec.type === 'computed') continue;

      addLog('搜索参数: ' + paramName + ' (' + spec.description + ')');

      if (spec.type === 'continuous') {
        var currentVal = currentParams[paramName] || spec.default;
        var step = spec.step;

        // 向上搜索
        for (var val = currentVal + step; val <= spec.max && !found && iteration < maxIterations; val += step) {
          iteration++;
          var testParams = cloneParams(currentParams);
          testParams[paramName] = val;

          var consistency = Engine.checkConsistency(testParams, baseParams);
          if (!consistency.valid) {
            if (verbose) addLog('  ' + paramName + '=' + val.toFixed(3) + ' 违反一致性: ' + consistency.violations[0].reason);
            continue;
          }

          var testResult = Engine.runCalc(testParams, 'integrated');
          if (testResult.irr > hurdleRate) {
            addLog('  ' + paramName + '=' + val.toFixed(3) + ' -> IRR=' + (testResult.irr * 100).toFixed(2) + '% ✓ 成立！');
            currentParams = testParams;
            found = true;
            break;
          }
        }

        // 向下搜索
        if (!found) {
          for (var val = currentVal - step; val >= spec.min && !found && iteration < maxIterations; val -= step) {
            iteration++;
            var testParams = cloneParams(currentParams);
            testParams[paramName] = val;

            var consistency = Engine.checkConsistency(testParams, baseParams);
            if (!consistency.valid) continue;

            var testResult = Engine.runCalc(testParams, 'integrated');
            if (testResult.irr > hurdleRate) {
              addLog('  ' + paramName + '=' + val.toFixed(3) + ' -> IRR=' + (testResult.irr * 100).toFixed(2) + '% ✓ 成立！');
              currentParams = testParams;
              found = true;
              break;
            }
          }
        }
      }

      if (spec.type === 'discrete' && !found) {
        var discOptions = spec.options;
        var currentIdx = discOptions.indexOf(currentParams[paramName] || spec.default);

        for (var j = 0; j < discOptions.length && !found && iteration < maxIterations; j++) {
          if (j === currentIdx) continue;
          iteration++;
          var testParams = cloneParams(currentParams);
          testParams[paramName] = discOptions[j];

          var consistency = Engine.checkConsistency(testParams, baseParams);
          if (!consistency.valid) continue;

          var testResult = Engine.runCalc(testParams, 'integrated');
          if (testResult.irr > hurdleRate) {
            addLog('  ' + paramName + '=' + discOptions[j] + ' -> IRR=' + (testResult.irr * 100).toFixed(2) + '% ✓ 成立！');
            currentParams = testParams;
            found = true;
            break;
          }
        }
      }
    }

    if (!found) {
      addLog('⚠ 第一层优化未找到可行解（迭代' + iteration + '次）。请放宽参数范围或降低门槛。');
    }
  }

  // 验证第一层结果
  var finalIntegrated = Engine.runCalc(currentParams, 'integrated');
  addLog('');
  addLog('=== 第一层结果 ===');
  addLog('一体化IRR: ' + (finalIntegrated.irr * 100).toFixed(2) + '%');
  addLog('一体化NPV: ' + formatMoney(finalIntegrated.npv));

  // ============================================================
  // 第二层：自动调内部结算参数使分拆后两边各自成立
  // ============================================================
  // 关键：内部结算参数不影响一体化 IRR，所以第二层始终基于
  // 用户当前参数（baseParams）独立运行，而非第一层修改后的 currentParams。
  // 这样确保一体化 IRR 不变，仅调整分部利润分配。
  //
  // 优化原则（按优先级）：
  //   1. 严格可行解：站IRR和银行IRR均≥门槛 → 选银行IRR最高的
  //      （银行通常是瓶颈，优先保障银行达标）
  //   2. 合理折中：站IRR≥门槛但银行未达标 → 选银行IRR最高的
  //      （站只要不低于门槛就行，降多少不重要）
  //   3. 不可行：站IRR会跌破门槛 → 不推荐调整
  //      （站是网络基础，不能牺牲站的生存能力）
  var layer2Result = null;

  if (!layer1Only) {
    addLog('');
    addLog('=== 第二层：调内部结算参数使分拆成立 ===');

    var bestSettlement = null;      // 严格可行解（双门槛均满足）
    var bestCompromise = null;      // 合理折中（站≥门槛，银行未达标）
    var settlementCount = 0;

    var rentSpec = Engine.PARAM_SPEC.internalBatRentMonthly;
    var techSpec = Engine.PARAM_SPEC.internalTechFeeYearly;

    // 使用 baseParams（用户当前参数），确保一体化 IRR 不变
    var layer2BaseParams = cloneParams(baseParams);

    // 当前分部 IRR（作为调整基准）
    var baseCalcP = buildCalcParams(layer2BaseParams);
    var baseIntegrated = Engine.calcIntegrated(baseCalcP);
    var baseStationIRR = baseIntegrated.st.irr;
    var baseBankIRR = baseIntegrated.bb.irr;

    addLog('当前分部IRR — 站: ' + (baseStationIRR * 100).toFixed(2) + '%, 银行: ' + (baseBankIRR * 100).toFixed(2) + '%');
    addLog('门槛 — 站≥' + (stationHurdle * 100).toFixed(1) + '%, 银行≥' + (bankHurdle * 100).toFixed(1) + '%');

    for (var rent = rentSpec.min; rent <= rentSpec.max; rent += rentSpec.step) {
      for (var fee = techSpec.min; fee <= techSpec.max; fee += techSpec.step) {
        settlementCount++;
        var testParams = cloneParams(layer2BaseParams);
        testParams.internalBatRentMonthly = rent;
        testParams.internalTechFeeYearly = fee;

        var calcP = buildCalcParams(testParams);
        var integrated = Engine.calcIntegrated(calcP);

        var stationIRR = integrated.st.irr;
        var bankIRR = integrated.bb.irr;

        // 站IRR跌破门槛 → 直接跳过（站是网络基础，不可牺牲）
        if (stationIRR < stationHurdle) continue;

        // 银行IRR必须有所改善（否则调整无意义）
        if (bankIRR <= baseBankIRR) continue;

        // 严格可行解：双门槛均满足
        if (bankIRR > bankHurdle) {
          if (verbose) {
            addLog('  可行解: rent=' + rent + ' fee=' + fee + ' 站=' + (stationIRR * 100).toFixed(2) + '% 银行=' + (bankIRR * 100).toFixed(2) + '%');
          }
          // 选银行IRR最高的（银行通常是瓶颈）
          if (!bestSettlement || bankIRR > bestSettlement.bankIRR) {
            bestSettlement = {
              internalBatRentMonthly: rent,
              internalTechFeeYearly: fee,
              stationIRR: stationIRR,
              bankIRR: bankIRR,
              stationDrop: baseStationIRR - stationIRR,
              bankGain: bankIRR - baseBankIRR,
              settlementPerStation: rent * (testParams.internalBatPerStation || 14) * 12 + fee
            };
          }
          continue;
        }

        // 合理折中：站≥门槛但银行未达标 → 选银行IRR最高的
        if (!bestCompromise || bankIRR > bestCompromise.bankIRR) {
          bestCompromise = {
            internalBatRentMonthly: rent,
            internalTechFeeYearly: fee,
            stationIRR: stationIRR,
            bankIRR: bankIRR,
            stationDrop: baseStationIRR - stationIRR,
            bankGain: bankIRR - baseBankIRR,
            settlementPerStation: rent * (testParams.internalBatPerStation || 14) * 12 + fee
          };
        }
      }
    }

    if (bestSettlement) {
      addLog('找到最优结算参数（共搜索' + settlementCount + '组）');
      addLog('  周转电池月租: ' + bestSettlement.internalBatRentMonthly + ' 元/月/块');
      addLog('  技术服务费: ' + bestSettlement.internalTechFeeYearly + ' 元/年/站');
      addLog('  每站年结算总额: ' + formatMoney(bestSettlement.settlementPerStation));
      addLog('  站 IRR: ' + (bestSettlement.stationIRR * 100).toFixed(2) + '%（下降' + (bestSettlement.stationDrop * 100).toFixed(1) + '个百分点，仍≥门槛）');
      addLog('  银行 IRR: ' + (bestSettlement.bankIRR * 100).toFixed(2) + '%（改善' + (bestSettlement.bankGain * 100).toFixed(1) + '个百分点）');

      layer2Result = bestSettlement;
    } else if (bestCompromise) {
      addLog('未找到双门槛可行解，返回合理折中方案（站IRR≥门槛，银行尽量改善）（共搜索' + settlementCount + '组）');
      addLog('  周转电池月租: ' + bestCompromise.internalBatRentMonthly + ' 元/月/块');
      addLog('  技术服务费: ' + bestCompromise.internalTechFeeYearly + ' 元/年/站');
      addLog('  每站年结算总额: ' + formatMoney(bestCompromise.settlementPerStation));
      addLog('  站 IRR: ' + (bestCompromise.stationIRR * 100).toFixed(2) + '%（下降' + (bestCompromise.stationDrop * 100).toFixed(1) + '个百分点，仍≥门槛）');
      addLog('  银行 IRR: ' + (bestCompromise.bankIRR * 100).toFixed(2) + '%（改善' + (bestCompromise.bankGain * 100).toFixed(1) + '个百分点，仍未达标）');

      bestCompromise.isCompromise = true;
      layer2Result = bestCompromise;
    } else {
      addLog('未找到合理方案（站IRR会跌破门槛' + (stationHurdle * 100).toFixed(1) + '%）。当前参数已是最优分配。');
    }
  }

  var elapsed = Date.now() - startTime;

  return {
    params: currentParams,
    integrated: {
      irr: finalIntegrated.irr,
      npv: finalIntegrated.npv,
      isViable: finalIntegrated.irr > hurdleRate
    },
    settlement: layer2Result,
    log: log,
    elapsedMs: elapsed
  };
};

/**
 * 格式化优化结果为可读文本
 * @param {Object} optimizerResult - runOptimizer 的返回值
 * @returns {string} 格式化的文本
 */
Engine.formatOptimizerResult = function (optimizerResult) {
  var r = optimizerResult;
  var lines = [];

  lines.push('========================================');
  lines.push('   自动调参结果');
  lines.push('========================================');
  lines.push('');

  // 第一层结果
  lines.push('【第一层：一体化模型】');
  lines.push('  一体化 IRR: ' + (r.integrated.irr * 100).toFixed(2) + '%');
  lines.push('  一体化 NPV: ' + formatMoney(r.integrated.npv));
  lines.push('  是否成立: ' + (r.integrated.isViable ? '✓ 成立' : '✗ 不成立'));
  lines.push('');

  // 第二层结果
  if (r.settlement) {
    lines.push('【第二层：分拆结算】' + (r.settlement.isCompromise ? ' ⚠ 折中方案（未同时满足双门槛）' : ''));
    lines.push('  周转电池月租: ' + r.settlement.internalBatRentMonthly + ' 元/月/块');
    lines.push('  技术服务费: ' + r.settlement.internalTechFeeYearly + ' 元/年/站');
    lines.push('  每站年结算总额: ' + formatMoney(r.settlement.settlementPerStation));
    lines.push('  站 IRR: ' + (r.settlement.stationIRR * 100).toFixed(2) + '%');
    lines.push('  银行 IRR: ' + (r.settlement.bankIRR * 100).toFixed(2) + '%');
    lines.push('');
  }

  return lines.join('\n');
};

// 格式化辅助函数
function formatMoney(val) {
  if (val === undefined || val === null) return 'N/A';
  if (Math.abs(val) >= 100000000) return (val / 100000000).toFixed(2) + '亿';
  if (Math.abs(val) >= 10000) return (val / 10000).toFixed(2) + '万';
  return val.toFixed(0) + '元';
}

function cloneParams(obj) {
  var copy = {};
  var keys = Object.keys(obj);
  for (var i = 0; i < keys.length; i++) {
    copy[keys[i]] = obj[keys[i]];
  }
  return copy;
}

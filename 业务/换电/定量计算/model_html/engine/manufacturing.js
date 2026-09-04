/**
 * ============================================================
 * engine/manufacturing.js — 电池制造利润测算
 * ============================================================
 *
 * 本文件测算换电电池制造业务的收入和利润：
 *   - 电芯价格逐年递减模型
 *   - 毛利率逐年递减模型
 *   - 按站龄cohort追踪全网电池需求（新增 + 利用率爬坡增量）
 *   - 稳态替换市场预测
 *
 * 加载顺序：在 constants.js, userStructure.js, scale.js 之后
 * ============================================================
 */
var Engine = window.Engine || {};

/** 根据年份计算电芯价格（元/Wh），每年递减
 * @param {number} yr      - 目标年份（如 2026）
 * @param {number} baseCost - 基准年电芯成本（元/Wh），默认取 Engine.DEFAULT_CELL_COST
 * @returns {number} 目标年份电芯成本（元/Wh）
 */
Engine.getCellPriceByYear = function (yr, baseCost) {
  var t = yr - Engine.BASE_YEAR;
  if (t <= 0) return baseCost || Engine.DEFAULT_CELL_COST;
  t = Math.min(t, 15);
  // 三阶段表驱动；若传自定义 baseCost，按真源相对路径外推
  if (baseCost && Math.abs(baseCost - Engine.POWER_CELL_BY_YEAR[0]) > 1e-9) {
    return baseCost * (Engine.POWER_CELL_BY_YEAR[t] / Engine.POWER_CELL_BY_YEAR[0]);
  }
  return Engine.POWER_CELL_BY_YEAR[t];
};

/** 根据年份计算毛利率（从基准年线性递减至远期锚定14.5%）
 * @param {number} yr     - 目标年份
 * @param {number} baseGm - 基准年毛利率（%），默认取 Engine.DEFAULT_GROSS_MARGIN
 * @returns {number} 目标年份毛利率（小数）
 */
Engine.getGrossMarginByYear = function (yr, baseGm) {
  baseGm = (baseGm || Engine.DEFAULT_GROSS_MARGIN) / 100;
  var years = yr - Engine.BASE_YEAR;
  if (years <= 0) return baseGm;
  var terminalGm = 0.145;
  var totalYears = 15;
  var gm = baseGm - (baseGm - terminalGm) * Math.min(years, totalYears) / totalYears;
  return Math.max(terminalGm, gm);
};

/** 根据站龄获取年末时点日均换电次数
 * @param {number} age - 站龄（0=建成当年，1=第2年...）
 * @returns {number} 年末时点日均换电次数
 */
Engine.getSwapsByAge = function (age) {
  var ramp = Engine.RAMP_BY_AGE;
  if (age >= ramp.length - 1) return ramp[ramp.length - 1];
  return ramp[age + 1];
};

/** 根据站龄获取全年平均日均换电次数（年初年末均值）
 * @param {number} age - 站龄
 * @returns {number} 全年平均日均换电次数
 */
Engine.getAvgSwapsByAge = function (age) {
  var ramp = Engine.RAMP_BY_AGE;
  if (age >= ramp.length - 1) return ramp[ramp.length - 1];
  return Math.round((ramp[age] + ramp[age + 1]) / 2);
};

/** 根据日均换电次数计算用户电池数
 * @param {number} X    - 日均换电次数
 * @param {number} maxX - 满载换电次数（默认120）
 * @returns {number} 单站用户电池数
 */
Engine.getUserBatsBySwaps = function (X, maxX) {
  maxX = maxX || 120;
  var users = Engine.calcUserStructure(X, maxX);
  return users.U;
};

/**
 * 计算换电电池制造利润（按站龄cohort模型）
 *
 * 每个新建站从建成起独立经历3年利用率爬坡，
 * 不同cohort在同一年有不同的利用率和电池需求。
 *
 * @param {string} name       - 情景名称（如'中性'、'乐观'、'悲观'）
 * @param {number} by2028     - 2028年目标站数
 * @param {number} final      - 终期目标站数（如 100000）
 * @param {number} periodRate - 期间费用率（小数），默认取 Engine.PERIOD_EXPENSE_RATE
 * @returns {Object} 逐年制造利润数据，含 rows、cumulBats、cumulMfgProfit、replaceBats、profitReplace
 */
Engine.calcMfgScenario = function (name, by2028, final, periodRate) {
  var pace = Engine.calcConstructionPace(by2028, final);
  var SPARE_BATS = 14;
  var maxX = 120;
  if (periodRate === undefined) periodRate = Engine.PERIOD_EXPENSE_RATE;

  var cumulBats = 0, cumulRevExcl = 0, cumulMfgProfit = 0;
  var rows = [];
  var cohorts = [];
  var lastBuildYear = 0;

  // 按年遍历建设节奏
  for (var i = 0; i < pace.length; i++) {
    var y = pace[i];
    var yrNum = parseInt(y.label);
    var totalStations = y.self + y.partner;
    var prevTotal = (i > 0) ? (pace[i - 1].self + pace[i - 1].partner) : 0;
    var newStations = totalStations - prevTotal;

    if (newStations > 0) {
      cohorts.push({ builtYear: yrNum, count: newStations });
      lastBuildYear = yrNum;
    }

    // 计算本年各cohort的电池需求
    var totalNewBats = 0;
    var cohortDetails = [];

    for (var c = 0; c < cohorts.length; c++) {
      var cohort = cohorts[c];
      var age = yrNum - cohort.builtYear;

      var X_start = (age === 0) ? Engine.RAMP_BY_AGE[0] : Engine.RAMP_BY_AGE[Math.min(age, Engine.RAMP_BY_AGE.length - 1)];
      var X_end = (age >= Engine.RAMP_BY_AGE.length - 1) ? Engine.RAMP_BY_AGE[Engine.RAMP_BY_AGE.length - 1] : Engine.RAMP_BY_AGE[age + 1];
      var X_avg = Math.round((X_start + X_end) / 2);

      var U_start = Engine.getUserBatsBySwaps(X_start, maxX);
      var U_end = Engine.getUserBatsBySwaps(X_end, maxX);
      var U_avg = Engine.getUserBatsBySwaps(X_avg, maxX);
      var batsPerStation_end = U_end + SPARE_BATS;

      var newBats, deltaU;
      if (age === 0) {
        newBats = cohort.count * batsPerStation_end;
        deltaU = U_end;
      } else {
        deltaU = U_end - U_start;
        newBats = cohort.count * deltaU;
      }
      newBats = Math.max(0, newBats);
      totalNewBats += newBats;

      cohortDetails.push({
        builtYear: cohort.builtYear, count: cohort.count, age: age,
        X_start: X_start, X_end: X_end, X_avg: X_avg,
        U_start: U_start, U_end: U_end, U_avg: U_avg,
        batsPerStation_end: batsPerStation_end, deltaU: deltaU, newBats: newBats
      });
    }

    cumulBats += totalNewBats;
    var cellCost = Engine.getCellPriceByYear(yrNum);
    var gm = Engine.getGrossMarginByYear(yrNum);
    var priceExcl = cellCost / (1 - gm);
    var batPriceExcl = priceExcl * Engine.BAT_CAP_KWH * 1000;
    var revExcl = totalNewBats * batPriceExcl;
    cumulRevExcl += revExcl;
    var netMargin = gm - periodRate;
    var mfgProfit = revExcl * netMargin;
    cumulMfgProfit += mfgProfit;

    // 全网加权平均利用率
    var totalSwaps = 0;
    for (var c2 = 0; c2 < cohorts.length; c2++) {
      var age2 = yrNum - cohorts[c2].builtYear;
      totalSwaps += cohorts[c2].count * Engine.getAvgSwapsByAge(age2);
    }
    var avgSwaps = totalStations > 0 ? Math.round(totalSwaps / totalStations) : 0;

    rows.push({
      yrNum: yrNum, totalStations: totalStations, newStations: newStations, avgSwaps: avgSwaps,
      totalNewBats: totalNewBats, cellCost: cellCost, gm: gm,
      priceExcl: priceExcl, batPriceExcl: batPriceExcl,
      revExcl: revExcl, netMargin: netMargin, mfgProfit: mfgProfit,
      cumulBats: cumulBats, cumulMfgProfit: cumulMfgProfit,
      cohortDetails: cohortDetails
    });

    if (lastBuildYear > 0 && yrNum >= lastBuildYear + 3) break;
  }

  // 延伸年份到最后一批站满4年（稳态）
  var lastRowYear = rows.length > 0 ? rows[rows.length - 1].yrNum : 0;
  var targetYear = lastBuildYear + 3;
  if (lastRowYear < targetYear) {
    var finalTotalStations = rows.length > 0 ? rows[rows.length - 1].totalStations : 0;
    for (var extYr = lastRowYear + 1; extYr <= targetYear; extYr++) {
      var extTotalNewBats = 0;
      var extCohortDetails = [];
      for (var ec = 0; ec < cohorts.length; ec++) {
        var extAge = extYr - cohorts[ec].builtYear;
        var extX_start = Engine.RAMP_BY_AGE[Math.min(extAge, Engine.RAMP_BY_AGE.length - 1)];
        var extX_end = (extAge >= Engine.RAMP_BY_AGE.length - 1) ? Engine.RAMP_BY_AGE[Engine.RAMP_BY_AGE.length - 1] : Engine.RAMP_BY_AGE[extAge + 1];
        var extU_start = Engine.getUserBatsBySwaps(extX_start, maxX);
        var extU_end = Engine.getUserBatsBySwaps(extX_end, maxX);
        var extDeltaU = extU_end - extU_start;
        if (extDeltaU > 0) {
          var extNewBats = cohorts[ec].count * extDeltaU;
          extTotalNewBats += extNewBats;
          extCohortDetails.push({
            builtYear: cohorts[ec].builtYear, count: cohorts[ec].count, age: extAge,
            X_start: extX_start, X_end: extX_end,
            X_avg: Math.round((extX_start + extX_end) / 2),
            U_start: extU_start, U_end: extU_end,
            batsPerStation_end: extU_end + SPARE_BATS,
            deltaU: extDeltaU, newBats: extNewBats
          });
        }
      }
      cumulBats += extTotalNewBats;
      var extCellCost = Engine.getCellPriceByYear(extYr);
      var extGm = Engine.getGrossMarginByYear(extYr);
      var extPriceExcl = extCellCost / (1 - extGm);
      var extBatPriceExcl = extPriceExcl * Engine.BAT_CAP_KWH * 1000;
      var extRevExcl = extTotalNewBats * extBatPriceExcl;
      cumulRevExcl += extRevExcl;
      var extNetMargin = extGm - periodRate;
      var extMfgProfit = extRevExcl * extNetMargin;
      cumulMfgProfit += extMfgProfit;

      var extTotalSwaps = 0;
      for (var ec2 = 0; ec2 < cohorts.length; ec2++) {
        extTotalSwaps += cohorts[ec2].count * Engine.getAvgSwapsByAge(extYr - cohorts[ec2].builtYear);
      }
      var extAvgSwaps = finalTotalStations > 0 ? Math.round(extTotalSwaps / finalTotalStations) : 0;

      rows.push({
        yrNum: extYr, totalStations: finalTotalStations, newStations: 0, avgSwaps: extAvgSwaps,
        totalNewBats: extTotalNewBats, cellCost: extCellCost, gm: extGm,
        priceExcl: extPriceExcl, batPriceExcl: extBatPriceExcl,
        revExcl: extRevExcl, netMargin: extNetMargin, mfgProfit: extMfgProfit,
        cumulBats: cumulBats, cumulMfgProfit: cumulMfgProfit,
        cohortDetails: extCohortDetails
      });
    }
  }

  // 稳态替换量：全网总电池 ÷ 电池寿命年数
  var steadyYr = Engine.BASE_YEAR + Engine.BAT_REPLACE_YEAR;
  var totalBatsSteady = 0;
  for (var c3 = 0; c3 < cohorts.length; c3++) {
    var ageSteady = steadyYr - cohorts[c3].builtYear;
    var XSteady = Engine.getSwapsByAge(ageSteady);
    var USteady = Engine.getUserBatsBySwaps(XSteady, maxX);
    totalBatsSteady += cohorts[c3].count * (USteady + SPARE_BATS);
  }
  var replaceBats = totalBatsSteady / Engine.BAT_REPLACE_YEAR;
  var cellCostSteady = Engine.getCellPriceByYear(steadyYr);
  var gmSteady = Engine.getGrossMarginByYear(steadyYr);
  var priceExclSteady = cellCostSteady / (1 - gmSteady);
  var batPriceExclSteady = priceExclSteady * Engine.BAT_CAP_KWH * 1000;
  var netMarginSteady = gmSteady - periodRate;
  var profitReplace = replaceBats * batPriceExclSteady * netMarginSteady;

  return {
    name: name, by2028: by2028, final: final,
    rows: rows, cumulBats: cumulBats, cumulRevExcl: cumulRevExcl,
    cumulMfgProfit: cumulMfgProfit,
    replaceBats: replaceBats, profitReplace: profitReplace,
    totalBatsSteady: totalBatsSteady, cohorts: cohorts
  };
};
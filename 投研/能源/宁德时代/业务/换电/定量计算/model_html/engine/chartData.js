/**
 * engine/chartData.js
 * 图表数据计算 —— 为 model.html 提供纯数据，不依赖 DOM
 * model.html 只负责拿数据后调用 Chart.js 渲染
 */

var Engine = Engine || {};

// ============================================================
// 盈亏平衡图数据
// ============================================================

/**
 * 获取盈亏平衡图数据
 * @param {object} p - 参数对象
 * @param {string} type - 图表类型：'station' | 'battery' | 'integrated'
 * @returns {object} { X_vals, datasets, title, beX }
 */
Engine.getBreakEvenChartData = function(p, type) {
  var st = Engine.calcPureStation(p);
  var maxX = st.max_swaps;
  var X_vals = [];
  var datasets = [];
  var title = '';

  if (type === 'station') {
    var rev_vals = [], opex_vals = [], ebitda_vals = [], totalCost_vals = [];
    for (var x = 0; x <= maxX; x += 5) {
      var p2 = Object.assign({}, p, { daily_swaps: x });
      var r = Engine.calcPureStation(p2);
      X_vals.push(x);
      rev_vals.push({ x: x, y: r.rev_excl / 10000 });
      opex_vals.push({ x: x, y: r.opex_excl / 10000 });
      ebitda_vals.push({ x: x, y: r.ebitda_excl / 10000 });
      var totalCost = r.opex_excl + r.depreciation + r.yr1.surtax;
      totalCost_vals.push({ x: x, y: totalCost / 10000 });
    }
    datasets.push(
      { label: '收入（不含税）', data: rev_vals, borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.08)', fill: true, tension: 0.3, pointRadius: 0 },
      { label: 'OPEX（不含税）', data: opex_vals, borderColor: '#f97316', borderDash: [5,3], tension: 0.3, pointRadius: 0 },
      { label: '总成本（OPEX+折旧+税金）', data: totalCost_vals, borderColor: '#dc2626', borderWidth: 2, borderDash: [8,4], tension: 0.3, pointRadius: 0 },
      { label: 'EBITDA（不含税）', data: ebitda_vals, borderColor: '#059669', borderWidth: 2, tension: 0.3, pointRadius: 0 }
    );
    title = '盈亏平衡≈' + st.breakeven_raw.toFixed(1) + '次/天（收入=总成本→PBT=0），取整=' + st.breakeven + '次，最大=' + st.max_swaps + '次/天';
  } else if (type === 'battery') {
    var bb = Engine.calcBatteryBank(p);
    var rev_vals = [], opex_vals = [], ebitda_vals = [], totalCost_vals = [];
    for (var x = 0; x <= maxX; x += 5) {
      var p2 = Object.assign({}, p, { daily_swaps: x });
      var r = Engine.calcBatteryBank(p2);
      X_vals.push(x);
      rev_vals.push({ x: x, y: r.rev_excl / 10000 });
      opex_vals.push({ x: x, y: r.opex_excl / 10000 });
      ebitda_vals.push({ x: x, y: r.ebitda_excl / 10000 });
      var totalCost = r.opex_excl + r.depreciation + r.yr1.surtax;
      totalCost_vals.push({ x: x, y: totalCost / 10000 });
    }
    datasets.push(
      { label: '收入（不含税）', data: rev_vals, borderColor: '#7c3aed', backgroundColor: 'rgba(124,58,237,0.08)', fill: true, tension: 0.3, pointRadius: 0 },
      { label: 'OPEX（不含税）', data: opex_vals, borderColor: '#f97316', borderDash: [5,3], tension: 0.3, pointRadius: 0 },
      { label: '总成本（OPEX+折旧+税金）', data: totalCost_vals, borderColor: '#dc2626', borderWidth: 2, borderDash: [8,4], tension: 0.3, pointRadius: 0 },
      { label: 'EBITDA（不含税）', data: ebitda_vals, borderColor: '#059669', borderWidth: 2, tension: 0.3, pointRadius: 0 }
    );
    title = '盈亏平衡=' + st.breakeven + '次/天，电池' + bb.total_bats + '块，资产' + (bb.total_capex/10000).toFixed(0) + '万';
  } else {
    var it = Engine.calcIntegrated(p);
    var rev_vals = [], opex_vals = [], ebitda_vals = [], totalCost_vals = [];
    for (var x = 0; x <= maxX; x += 5) {
      var p2 = Object.assign({}, p, { daily_swaps: x });
      var r = Engine.calcIntegrated(p2);
      X_vals.push(x);
      rev_vals.push({ x: x, y: r.total_rev_excl / 10000 });
      opex_vals.push({ x: x, y: r.total_opex_excl / 10000 });
      ebitda_vals.push({ x: x, y: r.ebitda_excl / 10000 });
      var totalCost = r.total_opex_excl + r.depreciation + r.yr1.surtax;
      totalCost_vals.push({ x: x, y: totalCost / 10000 });
    }
    datasets.push(
      { label: '收入（不含税）', data: rev_vals, borderColor: '#2563eb', backgroundColor: 'rgba(37,99,235,0.08)', fill: true, tension: 0.3, pointRadius: 0 },
      { label: 'OPEX（不含税）', data: opex_vals, borderColor: '#f97316', borderDash: [5,3], tension: 0.3, pointRadius: 0 },
      { label: '总成本（OPEX+折旧+税金）', data: totalCost_vals, borderColor: '#dc2626', borderWidth: 2, borderDash: [8,4], tension: 0.3, pointRadius: 0 },
      { label: 'EBITDA（不含税）', data: ebitda_vals, borderColor: '#059669', borderWidth: 2, tension: 0.3, pointRadius: 0 }
    );
    title = '盈亏平衡=' + st.breakeven + '次/天，总投入' + (it.total_capex/10000).toFixed(0) + '万';
  }

  return { X_vals: X_vals, datasets: datasets, title: title, maxX: maxX };
};

/**
 * 获取盈亏平衡标注点数据
 * @param {object} p - 参数对象
 * @param {string} type - 图表类型
 * @returns {object|null} { beX, beY, diffRatio } 或 null
 */
Engine.getBreakEvenPoint = function(p, type) {
  var beX, beY, diffRatio;
  var maxX = Engine.calcPureStation(p).max_swaps;

  if (type === 'station') {
    beX = Engine.calcPureStation(p).breakeven_raw;
  } else if (type === 'battery') {
    beX = Engine.calcBatteryBankBreakeven(p).breakeven_raw;
  } else {
    beX = Engine.calcIntegratedBreakeven(p).breakeven_raw;
  }

  if (!(beX > 0 && beX <= maxX)) return null;

  var p_be = Object.assign({}, p, { daily_swaps: beX });
  var r_be;
  if (type === 'station') {
    r_be = Engine.calcPureStation(p_be);
  } else if (type === 'battery') {
    r_be = Engine.calcBatteryBank(p_be);
  } else {
    r_be = Engine.calcIntegrated(p_be);
  }

  var beRev = (type === 'integrated' ? r_be.total_rev_excl : r_be.rev_excl) / 10000;
  var beCost = (type === 'integrated'
    ? (r_be.total_opex_excl + r_be.depreciation + r_be.yr1.surtax)
    : (r_be.opex_excl + r_be.depreciation + r_be.yr1.surtax)) / 10000;
  beY = (beRev + beCost) / 2;
  diffRatio = Math.abs(beRev - beCost) / Math.max(0.01, beY);

  return { beX: beX, beY: beY, diffRatio: diffRatio };
};

// ============================================================
// CATL 瀑布图数据
// ============================================================

/**
 * 获取 CATL 瀑布图数据
 * @param {object} p - 参数对象
 * @returns {object} { yearLabels, datasets, title }
 */
Engine.getWaterfallChartData = function(p) {
  var d = Engine.calcCombinedScaleRevenue(p);

  var yearLabels = [];
  var selfNpData = [];
  var partnerFeeData = [];
  var equityData = [];
  var bbData = [];

  for (var i = 0; i < d.annualData.length; i++) {
    var y = d.annualData[i];
    yearLabels.push(y.label);
    // 自持站税后净利润
    selfNpData.push(y.self_np / 1e8);
    // 合作站技术服务费 = 当年合作站数量 × 单站技术服务费(税后)
    var partnerFeeAnnual = y.partner * 35000 * (1 - Engine.TECH_SERVICE_COST_RATIO) / (1 + Engine.VAT_6);
    partnerFeeData.push(partnerFeeAnnual / 1e8);
    // 参股10%分红
    equityData.push(y.equity / 1e8);
    // 电池银行收益 = 单站电池银行净利润 × 总站数
    var bbNpPerStation = d.bb.yr1.np;
    var bbTotal = bbNpPerStation * (y.self + y.partner);
    bbData.push(bbTotal / 1e8);
  }

  var title = 'CATL换电业务净利润（' + Engine.BASE_YEAR + '-' + (Engine.BASE_YEAR + 9) + '年各年' + d.neutral.final / 10000 + '万座）';

  return {
    yearLabels: yearLabels,
    datasets: [
      { label: '电池银行收益', data: bbData, backgroundColor: '#93c5fd', borderRadius: 2 },
      { label: '自持站净利', data: selfNpData, backgroundColor: '#059669', borderRadius: 2 },
      { label: '合作站技术服务费', data: partnerFeeData, backgroundColor: '#10b981', borderRadius: 2 },
      { label: '参股10%分红', data: equityData, backgroundColor: '#d97706', borderRadius: 2 }
    ],
    title: title
  };
};
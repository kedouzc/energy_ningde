/**
 * ============================================================
 * engine/scale.js — 规模化推演（曲线拟合 + 阶段扩展）
 * ============================================================
 *
 * 本文件将单站模型放大到大规模场景：
 *   - 建设曲线：S型增长（Logistic），从初始站到目标站
 *   - 效率曲线：规模效应下单位成本下降
 *   - 阶段扩展：将15年单站模型扩展到实际建设周期
 *
 * 加载顺序：在 constants.js, station.js, batteryBank.js 之后
 * ============================================================
 */
var Engine = window.Engine || {};

/**
 * S型增长曲线（Logistic函数）
 *
 * 用于描述换电站建设数量的增长轨迹：
 *   初期慢 → 中期加速 → 后期趋近饱和
 *
 * 函数：f(t) = K / (1 + e^(-r*(t - t0)))
 *   K  = 最终饱和值（目标站数）
 *   r  = 增长率（越大越快）
 *   t0 = 拐点（增长速度最快的时刻）
 *
 * @param {number} t   - 时间（年）
 * @param {number} K   - 最终饱和值（最大站数）
 * @param {number} r   - 增长率（如 0.8）
 * @param {number} t0  - 拐点年份（如 5.0）
 * @returns {number} - 第t年的累计站点数
 *
 * 示例：
 *   logistic(5, 10000, 0.8, 5)  → 5000（拐点正好一半）
 *   logistic(10, 10000, 0.8, 5) → 约9820（接近饱和）
 */
Engine.logistic = function (t, K, r, t0) {
  return K / (1 + Math.exp(-r * (t - t0)));
};

/**
 * 规模化推演：从单站模型扩展到N站规模
 *
 * 计算过程：
 *   1. 使用Logistic曲线计算每年建站数量
 *   2. 每年新增站点按15年单站模型贡献利润
 *   3. 叠加计算：第t年的总利润 = Σ(第i年新建站的第t年利润)
 *   4. 规模化效应：单位成本随总站数增加而下降
 *
 * @param {Object} p - 参数对象
 *   p.targetStations  - 目标站数（如 10000）
 *   p.buildYears      - 建设周期（年），如 15
 *   p.logistic_r      - 增长率，如 0.8
 *   p.logistic_t0     - 拐点年份，如 5.0
 *   p.scaleFactor     - 规模化降本系数（%），如 0.85（成本降至85%）
 *   p.*               - 其他参数传递给 calcPureStation
 *
 * @returns {Object} 规模化模型，包含逐年站数、总利润、总IRR
 */
Engine.calcScale = function (p) {
  var targetStations = p.targetStations || 10000;
  var buildYears      = p.buildYears || 15;
  var logistic_r      = p.logistic_r || 0.8;
  var logistic_t0     = p.logistic_t0 || 5.0;
  var scaleFactor     = p.scaleFactor || 0.85;  // 规模化降本系数

  // ============================================================
  // 一、计算每年累计站点数（Logistic曲线）
  // ============================================================
  var cumulativeStations = [];
  var newStationsPerYear = [];
  for (var t = 1; t <= buildYears; t++) {
    var cum = Math.round(Engine.logistic(t, targetStations, logistic_r, logistic_t0));
    cumulativeStations.push(cum);
    var prev = t === 1 ? 0 : cumulativeStations[t - 2];
    newStationsPerYear.push(Math.max(0, cum - prev));
  }

  // ============================================================
  // 二、单站模型（基准）
  // ============================================================
  var stationModel = Engine.calcPureStationSimple(p);

  // ============================================================
  // 三、叠加计算：逐年总利润
  // ============================================================

  // 总利润数组（第1~15年，索引0~14）
  var totalNP = new Array(buildYears).fill(0);
  var totalNCF = new Array(buildYears).fill(0);

  // 对每个建站年份，叠加其利润贡献
  for (var buildYear = 0; buildYear < buildYears; buildYear++) {
    var newStations = newStationsPerYear[buildYear];
    if (newStations <= 0) continue;

    // 规模化降本：越晚建的站，单位成本越低
    var stationScale = 1.0 - (1.0 - scaleFactor) * (buildYear / buildYears);

    for (var opYear = 0; opYear < buildYears - buildYear; opYear++) {
      var idx = buildYear + opYear;
      if (idx >= buildYears) break;
      totalNP[idx]  += stationModel.annual[opYear].np  * newStations * stationScale;
      totalNCF[idx] += stationModel.annual[opYear].ncf * newStations * stationScale;
    }
  }

  // ============================================================
  // 四、总IRR/NPV
  // ============================================================

  // 总初始投资 = 所有新建站数 × 单站投资
  var stationInvPerStation = stationModel.cashflows[0];  // 负数
  var totalInvestment = 0;
  var totalCashflows2 = [];
  for (var t2 = 0; t2 < buildYears; t2++) {
    totalInvestment += newStationsPerYear[t2] * stationInvPerStation;
    totalCashflows2.push(totalNCF[t2]);
  }

  var discountRate = (p.discountRate || 7.5) / 100;
  var totalIRR = Engine.calcIRR(totalCashflows2);
  var totalNPV = Engine.calcNPV(totalCashflows2, discountRate);

  return {
    // 建设曲线
    build: {
      newPerYear: newStationsPerYear,
      cumulative: cumulativeStations,
      total: targetStations
    },
    // 单站模型
    station: stationModel,
    // 合并利润
    profit: {
      totalNP: totalNP,      // 逐年总净利润
      totalNCF: totalNCF,    // 逐年总净现金流
      totalInvestment: totalInvestment
    },
    // 财务指标
    financial: {
      irr: totalIRR,
      npv: totalNPV,
      totalRevenue: totalNP.reduce(function (a, b) { return a + b; }, 0)
    }
  };
};

/**
 * 建站节奏：计算自持站+合作站逐年建设计划
 *
 * 自持站：2025=520, 2026=1200, 2027=2500, 2028=4000（固定，此后不再增长）
 * 合作站：2025年500座（事实），2026-2028按22%→33%→45%递增至2028目标
 * 剩余合作站在2029年起分年建成
 *
 * @param {number} by2028Target - 2028年目标总站数
 * @param {number} finalTarget  - 终期目标总站数（如 100000）
 * @returns {Object[]} 逐年建设数据 [{yr, label, self, partner}, ...]
 */
Engine.calcConstructionPace = function (by2028Target, finalTarget) {
  var SELF = [520, 1200, 2500, 4000]; // 2025-2028各年累计

  var partner2028 = Math.max(0, by2028Target - SELF[3]);
  var partner2025 = 500;
  var partnerGap = partner2028 - partner2025;

  var p26 = partner2025 + Math.round(partnerGap * 0.22);
  var p27 = partner2025 + Math.round(partnerGap * 0.55);

  var years = [
    { yr: 1, label: '2025', self: SELF[0], partner: partner2025 },
    { yr: 2, label: '2026', self: SELF[1], partner: p26 },
    { yr: 3, label: '2027', self: SELF[2], partner: p27 },
    { yr: 4, label: '2028', self: SELF[3], partner: partner2028 },
  ];

  var finalPartner = finalTarget - SELF[3];
  var remaining = Math.max(0, finalPartner - partner2028);

  if (remaining > 0) {
    var buildYears = remaining >= 70000 ? 5 : 3;

    for (var i = 0; i < buildYears; i++) {
      var share;
      if (buildYears === 3) {
        share = (i === 0) ? 0.30 : (i === 1) ? 0.63 : 1.0;
      } else {
        share = (i + 1) / buildYears;
      }
      years.push({
        yr: 5 + i,
        label: (2024 + 5 + i).toString(),
        self: SELF[3],
        partner: partner2028 + Math.round(remaining * share)
      });
    }
    for (var j = buildYears; 5 + j <= 15; j++) {
      years.push({
        yr: 5 + j,
        label: (2024 + 5 + j).toString(),
        self: SELF[3],
        partner: finalPartner
      });
    }
  } else {
    for (var yr = 5; yr <= 15; yr++) {
      years.push({
        yr: yr,
        label: (2024 + yr).toString(),
        self: SELF[3],
        partner: finalPartner
      });
    }
  }

  return years;
};

/**
 * 规模化综合收入测算：多情景站点建设 + 盈利叠加
 *
 * 对三种情景（悲观/中性/乐观）分别进行：
 *   1. 调用 calcConstructionPace 生成建站节奏
 *   2. 调用 calcIntegrated 计算单站+电池银行收益
 *   3. 逐年叠加各批次站点利润
 *   4. 输出三情景对比 + 逐年现金流表
 *
 * @param {Object} p - 基础参数（含 daily_swaps, cell_cost 等）
 * @returns {Object} { multiScenario, annualData, it, st, bb, neutral }
 */
Engine.calcCombinedScaleRevenue = function (p) {
  // 先计算单站模型，再合并
  var st = Engine.calcPureStation(p);
  var bb = Engine.calcBatteryBank({
    st: st, fam_ratio: p.fam_ratio, spare_bats: p.spare_bats,
    spare_rent: p.spare_rent, bat_replace_strategy: p.bat_replace_strategy,
    total_stations: p.total_stations, discount_rate: p.discount_rate
  });
  var it = Engine.calcIntegrated({ st: st, bb: bb, discount_rate: p.discount_rate / 100 });

  var partner_fee_annual_single = 35000 * (1 - (Engine.TECH_SERVICE_COST_RATIO || 0.35));
  var equity_ratio = 0.10;
  var reits_pbv = 2.0, reits_ratio = 0.60;

  var FINAL_TOTAL = 100000;
  var SELF_STATIONS = 4000;

  var scenarios = [
    {
      name: '悲观', by2028: 30000, final: FINAL_TOTAL,
      daily_swaps: 80, cell_cost: 0.42, pack_integration_cost: 0.12, gross_margin: 24, spare_rent: 200
    },
    {
      name: '中性', by2028: p.total_stations || 50000, final: FINAL_TOTAL,
      daily_swaps: p.daily_swaps, cell_cost: p.cell_cost,
      pack_integration_cost: p.pack_integration_cost, gross_margin: p.gross_margin, spare_rent: p.spare_rent
    },
    {
      name: '乐观', by2028: 100000, final: FINAL_TOTAL,
      daily_swaps: 140, cell_cost: 0.35, pack_integration_cost: 0.08, gross_margin: 20, spare_rent: 280
    },
  ];

  var multiScenario = scenarios.map(function (s) {
    var sp = Object.assign({}, p, {
      daily_swaps: s.daily_swaps,
      cell_cost: s.cell_cost,
      pack_integration_cost: s.pack_integration_cost,
      gross_margin: s.gross_margin,
      spare_rent: s.spare_rent,
    });
    var sSt = Engine.calcPureStation(sp);
    var sBb = Engine.calcBatteryBank({
      st: sSt, fam_ratio: sp.fam_ratio, spare_bats: sp.spare_bats,
      spare_rent: sp.spare_rent, bat_replace_strategy: sp.bat_replace_strategy,
      total_stations: sp.total_stations, discount_rate: sp.discount_rate
    });
    var sIt = Engine.calcIntegrated({ st: sSt, bb: sBb, discount_rate: p.discount_rate / 100 });

    var partner = s.final - SELF_STATIONS;
    var self_ebitda = sIt.ebitda_excl * SELF_STATIONS;
    var partner_fee = partner_fee_annual_single * partner;
    var self_np_per_station = sSt.yr1 ? sSt.yr1.np : 0;
    var equity = self_np_per_station * SELF_STATIONS * (partner / SELF_STATIONS) * equity_ratio;
    var bb_np_per_station = sBb.yr1 ? sBb.yr1.np : 0;
    var bb_annual = bb_np_per_station * s.final;
    var catl_annual = self_ebitda + partner_fee + equity + bb_annual;
    var reits = sIt.total_capex * SELF_STATIONS * reits_pbv * reits_ratio;
    var baas_15yr = sIt.ebitda_excl * SELF_STATIONS * (1 - (Engine.CIT || 0.25)) * (Engine.YEARS || 15);
    var bb_15yr = bb_annual * (Engine.YEARS || 15);
    var total_15yr = reits + baas_15yr + bb_15yr + partner_fee * (Engine.YEARS || 15) + equity * (Engine.YEARS || 15);

    return {
      name: s.name, by2028: s.by2028, final: s.final,
      daily_swaps: s.daily_swaps, cell_cost: s.cell_cost,
      partner: partner, self_ebitda: self_ebitda, partner_fee: partner_fee,
      equity: equity, bb_annual: bb_annual, catl_annual: catl_annual,
      reits: reits, total_15yr: total_15yr,
      total: s.final, self: SELF_STATIONS,
      st_irr: sSt.irr, bb_irr: sBb.irr, it_irr: sIt.irr,
      st_ebitda: sSt.ebitda_excl, bb_ebitda: sBb.ebitda_excl,
      it_ebitda: sIt.ebitda_excl,
      st_np: sSt.yr1 ? sSt.yr1.np : 0,
      bb_np: sBb.yr1 ? sBb.yr1.np : 0,
    };
  });

  var neutral = scenarios[1];
  var pace = Engine.calcConstructionPace(neutral.by2028, neutral.final);

  var annualData = pace.map(function (y) {
    var par = y.partner;
    var slf = y.self;
    var yrIdx = y.yr - 1;
    var self_np = 0, equity_val = 0, bb_np = 0;
    for (var i = 0; i <= yrIdx; i++) {
      var opYear = yrIdx - i;
      if (opYear >= (Engine.YEARS || 15)) continue;
      var batchSelf = (i === 0) ? pace[0].self : (pace[i].self - pace[i - 1].self);
      var batchPartner = (i === 0) ? pace[0].partner : (pace[i].partner - pace[i - 1].partner);
      if (batchSelf < 0) batchSelf = 0;
      if (batchPartner < 0) batchPartner = 0;
      var stNpYear = (st.tax && st.tax.yearly && st.tax.yearly[opYear]) ? st.tax.yearly[opYear].np : 0;
      var bbNpYear = (bb.tax && bb.tax.yearly && bb.tax.yearly[opYear]) ? bb.tax.yearly[opYear].np : 0;
      self_np += stNpYear * batchSelf;
      equity_val += stNpYear * batchPartner * equity_ratio;
      bb_np += bbNpYear * (batchSelf + batchPartner);
    }
    var catl_total = self_np + equity_val + bb_np;
    var self_capex_cum = it.total_capex * slf;
    var reits_eligible_val = (y.yr === 4) ? (it.total_capex * slf * reits_pbv * reits_ratio) : 0;
    return {
      yr: y.yr, label: y.label, self: y.self, partner: y.partner,
      self_np: self_np, equity: equity_val, bb_np: bb_np,
      catl_total: catl_total, self_capex_cum: self_capex_cum,
      reits_eligible: reits_eligible_val
    };
  });

  return { multiScenario: multiScenario, annualData: annualData, it: it, st: st, bb: bb, neutral: neutral };
};
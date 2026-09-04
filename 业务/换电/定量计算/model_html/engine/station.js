/**
 * ============================================================
 * engine/station.js — 换电站单站模型（纯换电运营，含超充）
 * ============================================================
 *
 * 本文件计算换电站单体15年的财务模型，包括：
 *   - 收入：换电服务费 + 超充服务费 + CCER碳积分 + VPP虚拟电厂
 *   - 成本：电费 + 维保 + 人工 + 场地租金 + 保险 + 内部结算支出
 *   - 资产：设备投资 + 折旧
 *   - 用户结构：营运车 vs 私家车（调和平均法）
 *   - 税务：增值税 + 附加税 + 所得税（含租金9%税率）
 *   - 盈亏平衡：合并 + 换电独立 + 超充独立
 *   - 输出：IRR / NPV / 净利润 / 现金流 / 盈亏平衡点
 *
 * 加载顺序：在 constants.js, financial.js, tax.js, userStructure.js 之后
 * 对应MD文档：宁德时代_超换一体站_财务模型_修正版.md # 2.1 换电站单站模型
 * ============================================================
 */
var Engine = window.Engine || {};

/**
 * 计算换电站单站模型（纯换电运营，方案A：换电/超充分摊成本）
 *
 * 核心逻辑流程：
 *   1. 根据日均换电次数推导用户结构（营运车/私家车）
 *   2. 计算换电收入和超充收入（含CCER/VPP，按电量比例分摊）
 *   3. 共享成本按规则分摊（保险按投资额，租金/电损按收入比例）
 *   4. 计算税务（含租金9%增值税，资产进项一次性抵扣）
 *   5. 二分法求解合并盈亏平衡和换电独立盈亏平衡
 *   6. 计算IRR/NPV
 *
 * @param {Object} p - 参数对象，包含以下字段：
 *   p.swap_fee_val      - 换电服务费（元/度），含税，如 0.40
 *   p.spare_bats        - 周转电池数量（块），如 10
 *   p.spare_rent        - 周转电池租金（元/月/块），如 240
 *   p.tech_service      - 技术服务费（元/年/站），如 35000，付电池银行
 *   p.station_invest    - 站端投资（万元），含税，如 215
 *   p.daily_swaps       - 日均换电次数（次），如 115
 *   p.op_mode           - 运营模式，'16h' 或 '24h'
 *   p.sc_cars_per_day   - 日均超充车辆数（默认 40）
 *   p.sc_kwh_per_car    - 单次超充电量（kWh，默认 25）
 *   p.sc_fee_val        - 超充服务费（元/度，默认 0.30）
 *   p.discount_rate     - 折现率（小数，默认 0.075）
 *
 * @returns {Object} 包含收入、成本、现金流、IRR、NPV、盈亏平衡等完整单站模型
 */
Engine.calcPureStation = function (p) {
  // ============================================================
  // 一、参数解析
  // ============================================================
  var swap_fee       = p.swap_fee_val;
  var spare_bats     = p.spare_bats;
  var spare_rent     = p.spare_rent;
  var station_invest = p.station_invest * 10000;  // 万元→元，含税CAPEX
  var X              = p.daily_swaps;
  var op_mode        = p.op_mode || '16h';
  var max_swaps      = op_mode === '24h' ? 140 : 125;
  var sc_cars        = p.sc_cars_per_day || Engine.SC_CARS_PER_STATION;
  var sc_kwh         = p.sc_kwh_per_car || Engine.SC_KWH;
  var sc_fee         = p.sc_fee_val || Engine.SC_FEE;
  var discountRate   = (typeof p.discount_rate !== 'undefined') ? p.discount_rate : Engine.DEFAULT_DISCOUNT_RATE;
  var YEARS          = Engine.YEARS || 15;

  // 用户结构推导（调和平均法）
  var users      = Engine.calcUserStructure(X, max_swaps);
  var comm_users = users.comm;
  var priv_users = users.priv;
  var total_users = users.U;
  var comm_ratio  = users.p;

  var swap_net_kwh  = X * Engine.SWAP_KWH_NET * 365;
  var sc_net_kwh    = sc_cars * sc_kwh * 365;
  var total_kwh_day = X * Engine.SWAP_KWH_NET + sc_cars * sc_kwh;

  // ============================================================
  // 二、收入计算（含税）
  // ============================================================
  var swap_rev_incl = swap_fee * X * Engine.SWAP_KWH_NET * 365;       // 13% VAT
  var sc_rev_incl   = sc_fee * sc_cars * sc_kwh * 365;                 // 13% VAT

  // CCER和VPP按电量比例分摊给换电和超充
  var total_kwh_annual = swap_net_kwh + sc_net_kwh;
  var swap_kwh_ratio   = total_kwh_annual > 0 ? swap_net_kwh / total_kwh_annual : 0;
  var sc_kwh_ratio     = total_kwh_annual > 0 ? sc_net_kwh / total_kwh_annual : 0;

  var ccer_incl_total = total_kwh_day * 365 * Engine.EMISSION_FACTOR / 1000 * Engine.CCER_RATE;
  var vpp_incl_total  = total_kwh_day > 0 ? Engine.VPP_BASE * total_kwh_day / Engine.VPP_BASE_KWH : 0;
  var ccer_incl = ccer_incl_total;
  var vpp_incl  = vpp_incl_total;
  var total_revenue_incl = swap_rev_incl + sc_rev_incl + ccer_incl + vpp_incl;

  // ============================================================
  // 三、成本计算（含税 · 方案A：换电/超充专属+共享分摊）
  // ============================================================

  // 3.1 换电专属成本
  var swap_loss_incl = swap_net_kwh / (1 - Engine.LOSS_RATE) * Engine.LOSS_RATE * Engine.WEIGHTED_PRICE;
  var swap_elec_cost_incl = swap_net_kwh * 0.05 * Engine.WEIGHTED_PRICE;
  var spare_rent_cost_incl = spare_bats * spare_rent * 12;  // 13% VAT

  // 3.2 超充专属成本
  var sc_loss_incl = sc_net_kwh / (1 - Engine.LOSS_RATE) * Engine.LOSS_RATE * Engine.WEIGHTED_PRICE;
  var sc_elec_cost_incl = sc_net_kwh * 0.05 * Engine.WEIGHTED_PRICE;

  // 3.3 共享成本
  var total_loss_incl = swap_loss_incl + sc_loss_incl;
  var total_elec_cost_incl = swap_elec_cost_incl + sc_elec_cost_incl;

  // 人工 = 2人×月薪8000×(1+社保40%)×12月
  var labor = op_mode === '24h' ? 0 : Math.round(2 * Engine.STAFF_SWAP_MONTHLY * (1 + Engine.SOCIAL) * 12);

  // 场地租金 = 12万/年（含税9%）
  var rent_cost_incl = 120000;

  // 设备维保 = 6万/年（含税13%），24h模式8万/年
  var maint_incl = op_mode === '24h' ? 80000 : 60000;

  // 设备保费 = 站投资×0.15%（含税6%）
  var equip_insur_incl = station_invest * Engine.EQUIP_INSUR_RATE;

  // 技术服务费（含税6%）付电池银行，默认 35000
  var tech_service_incl = (typeof p.tech_service !== 'undefined') ? p.tech_service : 35000;

  // ============================================================
  // 四、共享成本分摊（方案A）
  // ============================================================
  // 建设成本相关：保险 → 按投资额分摊（换电100%）
  // 变动成本相关：租金、电损 → 按收入/电量分摊
  var total_rev_for_alloc = swap_rev_incl + sc_rev_incl;
  var swap_rev_ratio = total_rev_for_alloc > 0 ? swap_rev_incl / total_rev_for_alloc : 0;
  var sc_rev_ratio   = total_rev_for_alloc > 0 ? sc_rev_incl / total_rev_for_alloc : 0;

  // 建设成本相关共享成本：保险按投资额分摊（换电100%）
  var swap_equip_insur_incl = equip_insur_incl;
  var sc_equip_insur_incl   = 0;

  // 变动成本相关共享成本：租金按收入比例，电损按电量比例
  var swap_rent_incl      = rent_cost_incl * swap_rev_ratio;
  var sc_rent_incl        = rent_cost_incl * sc_rev_ratio;
  var swap_loss_alloc_incl  = total_loss_incl * swap_kwh_ratio;
  var sc_loss_alloc_incl    = total_loss_incl * sc_kwh_ratio;
  var swap_elec_alloc_incl  = total_elec_cost_incl * swap_kwh_ratio;
  var sc_elec_alloc_incl    = total_elec_cost_incl * sc_kwh_ratio;

  // 人工：换电业务专属（超充无人值守）
  var swap_labor = labor;
  var sc_labor   = 0;

  // 维保：换电设备维保为主
  var swap_maint_incl = maint_incl;
  var sc_maint_incl   = 0;

  // 换电总成本（含税）
  var swap_opex_incl = swap_loss_alloc_incl + swap_elec_alloc_incl + swap_labor + swap_rent_incl + swap_maint_incl + swap_equip_insur_incl + spare_rent_cost_incl + tech_service_incl;
  // 超充总成本（含税）
  var sc_opex_incl = sc_loss_alloc_incl + sc_elec_alloc_incl + sc_labor + sc_rent_incl + sc_maint_incl + sc_equip_insur_incl;
  // 合并总成本
  var total_opex_incl = swap_opex_incl + sc_opex_incl;

  // ============================================================
  // 五、税务分组（合并口径）
  // ============================================================
  var rev13 = swap_rev_incl + sc_rev_incl;
  var rev6  = ccer_incl + vpp_incl;

  // 含税OPEX按税率分
  var opex13 = total_loss_incl + total_elec_cost_incl + maint_incl + spare_rent_cost_incl;
  var opex6  = equip_insur_incl + tech_service_incl;
  var opexNoVAT = labor;

  // 租金进项税（9%税率）
  var rentVAT  = rent_cost_incl / (1 + Engine.RENT_VAT) * Engine.RENT_VAT;
  var rentExcl = rent_cost_incl - rentVAT;

  // 资产可抵扣进项（站设备含13%增值税）
  var assetInputVAT = station_invest / (1 + Engine.VAT_13) * Engine.VAT_13;
  var stationExcl   = station_invest - assetInputVAT;
  var depreciation  = stationExcl / Engine.STATION_DEPRECIATION_YEARS;

  var tax = Engine.calcYearlyTaxWithRent(rev13, rev6, opex13, opex6, opexNoVAT, rentExcl, rentVAT, assetInputVAT, depreciation);
  var ebitda_excl = tax.ebitda;
  var rev_excl    = tax.revExcl;
  var opex_excl   = tax.opexExcl;

  // ============================================================
  // 六、盈亏平衡计算（合并口径）
  // ============================================================
  // 二分法求解合并盈亏平衡点（税前利润=0）
  function calcSwapPBTatX(testX) {
    // 模仿calcPureStation中对testX的计算逻辑，但只需PBT
    var testSwapRevIncl = swap_fee * testX * Engine.SWAP_KWH_NET * 365;
    var testSwapLossIncl = testX * Engine.SWAP_KWH_NET * 365 / (1 - Engine.LOSS_RATE) * Engine.LOSS_RATE * Engine.WEIGHTED_PRICE;
    var testLossIncl = testSwapLossIncl + sc_loss_incl;
    var testElecCostIncl = (testX * Engine.SWAP_KWH_NET * 365 + sc_net_kwh) * 0.05 * Engine.WEIGHTED_PRICE;
    var testKwhDay = testX * Engine.SWAP_KWH_NET + sc_cars * sc_kwh;
    var testCcerIncl = testKwhDay * 365 * Engine.EMISSION_FACTOR / 1000 * Engine.CCER_RATE;
    var testVppIncl = testKwhDay > 0 ? Engine.VPP_BASE * testKwhDay / Engine.VPP_BASE_KWH : 0;
    // 含税收入
    var testRev13 = testSwapRevIncl + sc_rev_incl;
    var testRev6  = testCcerIncl + testVppIncl;
    var outVAT13_test = testRev13 / (1 + Engine.VAT_13) * Engine.VAT_13;
    var outVAT6_test  = testRev6 / (1 + Engine.VAT_6) * Engine.VAT_6;
    var outVAT_test = outVAT13_test + outVAT6_test;
    // 含税OPEX
    var opex13_test = testLossIncl + testElecCostIncl + maint_incl + spare_rent_cost_incl;
    var opex6_test  = equip_insur_incl + tech_service_incl;
    var inVAT13_test = opex13_test / (1 + Engine.VAT_13) * Engine.VAT_13;
    var inVAT6_test  = opex6_test / (1 + Engine.VAT_6) * Engine.VAT_6;
    var inVAT_opex_test = inVAT13_test + inVAT6_test + rentVAT;
    // 第1年含资产抵扣
    var inVATTotal_test = inVAT_opex_test + assetInputVAT;
    var vatPayable_test = Math.max(0, outVAT_test - inVATTotal_test);
    var surtax_test = vatPayable_test * Engine.SURTAX;
    // 不含税收入/成本
    var revExcl_test = (testRev13 / (1 + Engine.VAT_13)) + (testRev6 / (1 + Engine.VAT_6));
    var opexExcl_test = (opex13_test / (1 + Engine.VAT_13)) + (opex6_test / (1 + Engine.VAT_6)) + opexNoVAT + rentExcl;
    var ebitda_test = revExcl_test - opexExcl_test;
    var pbt_test = ebitda_test - depreciation - surtax_test;
    return pbt_test;
  }
  // 二分法求解合并盈亏平衡点
  var breakeven_max = max_swaps;
  var pbt_at_max = calcSwapPBTatX(breakeven_max);
  var pbt_at_0   = calcSwapPBTatX(0);
  var breakeven = Infinity, breakeven_raw = Infinity;
  if (pbt_at_max > 0 && pbt_at_0 < 0) {
    var lo = 0, hi = breakeven_max;
    for (var iter = 0; iter < 50; iter++) {
      var mid = (lo + hi) / 2;
      var pbt_mid = calcSwapPBTatX(mid);
      if (Math.abs(pbt_mid) < 10) { lo = mid; break; }
      if (pbt_mid < 0) lo = mid; else hi = mid;
    }
    breakeven_raw = (lo + hi) / 2;
    breakeven = Math.ceil(breakeven_raw);
  } else if (pbt_at_0 >= 0) {
    breakeven_raw = 0;
    breakeven = 0;
  }

  // ============================================================
  // 七、换电独立盈亏平衡（方案A）
  // ============================================================
  function calcSwapOnlyPBTatX(testX) {
    var testSwapRevIncl = swap_fee * testX * Engine.SWAP_KWH_NET * 365;
    var testSwapNetKwh = testX * Engine.SWAP_KWH_NET * 365;
    var testScNetKwh = sc_net_kwh;
    var testTotalKwh = testSwapNetKwh + testScNetKwh;
    var testSwapKwhRatio = testTotalKwh > 0 ? testSwapNetKwh / testTotalKwh : 0;
    var testScKwhRatio   = testTotalKwh > 0 ? testScNetKwh / testTotalKwh : 0;
    var testTotalRev = testSwapRevIncl + sc_rev_incl;
    var testSwapRevRatio = testTotalRev > 0 ? testSwapRevIncl / testTotalRev : 0;

    // 换电分摊成本
    var testSwapLoss = (testSwapNetKwh / (1 - Engine.LOSS_RATE) * Engine.LOSS_RATE * Engine.WEIGHTED_PRICE + testScNetKwh / (1 - Engine.LOSS_RATE) * Engine.LOSS_RATE * Engine.WEIGHTED_PRICE) * testSwapKwhRatio;
    var testSwapElec = (testSwapNetKwh + testScNetKwh) * 0.05 * Engine.WEIGHTED_PRICE * testSwapKwhRatio;
    var testSwapRent = rent_cost_incl * testSwapRevRatio;
    var testSwapMaint = maint_incl;
    var testSwapInsur = equip_insur_incl;
    var testSwapLabor = labor;
    var testSwapOpexIncl = testSwapLoss + testSwapElec + testSwapRent + testSwapMaint + testSwapInsur + testSwapLabor + spare_rent_cost_incl + tech_service_incl;

    // 换电收入不含税
    var testSwapRevExcl = testSwapRevIncl / (1 + Engine.VAT_13);
    var testSwapCcer = testTotalKwh > 0 ? (testTotalKwh * Engine.EMISSION_FACTOR / 1000 * Engine.CCER_RATE) * testSwapKwhRatio : 0;
    var testSwapVpp = testTotalKwh > 0 ? (Engine.VPP_BASE * (testTotalKwh / 365) / Engine.VPP_BASE_KWH) * testSwapKwhRatio : 0;
    var testSwapRev6Excl = (testSwapCcer + testSwapVpp) / (1 + Engine.VAT_6);
    var testSwapRevExclTotal = testSwapRevExcl + testSwapRev6Excl;

    // 换电成本不含税
    var testSwapOpex13 = testSwapLoss + testSwapElec + testSwapMaint + spare_rent_cost_incl;
    var testSwapOpex6  = testSwapInsur + tech_service_incl;
    var testSwapOpexExcl = testSwapOpex13 / (1 + Engine.VAT_13) + testSwapOpex6 / (1 + Engine.VAT_6) + testSwapLabor + testSwapRent / (1 + Engine.RENT_VAT);

    var testSwapEbitda = testSwapRevExclTotal - testSwapOpexExcl;
    var testSwapDepr = depreciation;

    // 增值税及附加（简化：按换电收入占比分摊合并增值税）
    var testOutVAT13 = (testSwapRevIncl + sc_rev_incl) / (1 + Engine.VAT_13) * Engine.VAT_13;
    var testOutVAT6  = (testTotalKwh * Engine.EMISSION_FACTOR / 1000 * Engine.CCER_RATE + (testTotalKwh > 0 ? Engine.VPP_BASE * (testTotalKwh / 365) / Engine.VPP_BASE_KWH : 0)) / (1 + Engine.VAT_6) * Engine.VAT_6;
    var testInVAT13  = (testSwapLoss + testSwapElec + testSwapMaint + spare_rent_cost_incl + sc_loss_incl + sc_elec_cost_incl) / (1 + Engine.VAT_13) * Engine.VAT_13;
    var testInVAT6   = (equip_insur_incl + tech_service_incl) / (1 + Engine.VAT_6) * Engine.VAT_6;
    var testRentVAT  = rent_cost_incl / (1 + Engine.RENT_VAT) * Engine.RENT_VAT;
    var testInVATTotal = testInVAT13 + testInVAT6 + testRentVAT + assetInputVAT;
    var testVatPayable = Math.max(0, testOutVAT13 + testOutVAT6 - testInVATTotal);
    var testSurtax = testVatPayable * Engine.SURTAX * testSwapRevRatio;

    var testSwapPBT = testSwapEbitda - testSwapDepr - testSurtax;
    return testSwapPBT;
  }

  // 超充独立盈亏平衡
  function calcSCOnlyPBT() {
    var scLossAlloc  = total_loss_incl * sc_kwh_ratio;
    var scElecAlloc  = total_elec_cost_incl * sc_kwh_ratio;
    var scRentAlloc  = rent_cost_incl * sc_rev_ratio;
    var scOpexIncl = scLossAlloc + scElecAlloc + scRentAlloc;

    var scRevExcl = sc_rev_incl / (1 + Engine.VAT_13);
    var scCcer = ccer_incl_total * sc_kwh_ratio;
    var scVpp  = vpp_incl_total * sc_kwh_ratio;
    var scRev6Excl = (scCcer + scVpp) / (1 + Engine.VAT_6);
    var scRevExclTotal = scRevExcl + scRev6Excl;

    var scOpexExcl = scLossAlloc / (1 + Engine.VAT_13) + scElecAlloc / (1 + Engine.VAT_13) + scRentAlloc / (1 + Engine.RENT_VAT);

    var scEbitda = scRevExclTotal - scOpexExcl;
    var scSurtax = tax.yearly[0].surtax * sc_rev_ratio;
    var scPBT = scEbitda - scSurtax;
    return scPBT;
  }

  // 换电独立盈亏平衡（二分法）
  var swap_breakeven = Infinity, swap_breakeven_raw = Infinity;
  var swapPbtAtMax = calcSwapOnlyPBTatX(max_swaps);
  var swapPbtAt0   = calcSwapOnlyPBTatX(0);
  if (swapPbtAtMax > 0 && swapPbtAt0 < 0) {
    var slo = 0, shi = max_swaps;
    for (var sIter = 0; sIter < 50; sIter++) {
      var smid = (slo + shi) / 2;
      var sPbtMid = calcSwapOnlyPBTatX(smid);
      if (Math.abs(sPbtMid) < 10) { slo = smid; break; }
      if (sPbtMid < 0) slo = smid; else shi = smid;
    }
    swap_breakeven_raw = (slo + shi) / 2;
    swap_breakeven = Math.ceil(swap_breakeven_raw);
  } else if (swapPbtAt0 >= 0) {
    swap_breakeven_raw = 0;
    swap_breakeven = 0;
  }

  // 超充独立盈亏
  var sc_pbt = calcSCOnlyPBT();
  var sc_profitable = sc_pbt > 0;

  // ============================================================
  // 八、边际贡献与固定成本（用于显示）
  // ============================================================
  var var_cost_per_swap = (Engine.SWAP_KWH_NET / (1 - Engine.LOSS_RATE) * Engine.LOSS_RATE * Engine.WEIGHTED_PRICE + Engine.SWAP_KWH_NET * 0.05 * Engine.WEIGHTED_PRICE) / (1 + Engine.VAT_13);
  var rev_per_swap_excl = swap_fee * Engine.SWAP_KWH_NET / (1 + Engine.VAT_13);
  var fixed_opex_excl = opex_excl - ((total_loss_incl + total_elec_cost_incl) / (1 + Engine.VAT_13));

  // ============================================================
  // 九、IRR / NPV 计算
  // ============================================================
  var cfs = [-station_invest];
  for (var t2 = 0; t2 < YEARS; t2++) cfs.push(tax.yearly[t2].ncf);
  var irr = Engine.calcIRR(cfs);
  var payback = tax.yearly[0].ncf > 0 ? station_invest / tax.yearly[0].ncf : Infinity;

  var npv_val = -station_invest;
  for (var t3 = 0; t3 < YEARS; t3++) {
    npv_val += tax.yearly[t3].ncf / Math.pow(1 + discountRate, t3 + 1);
  }

  // 净利率（取第1年）
  var yr1 = tax.yearly[0];
  var net_margin = rev_excl > 0 ? yr1.np / rev_excl : 0;

  // 累计净现金流（直接求和逐年ncf）
  var ncfSum = 0;
  for (var t = 0; t < YEARS; t++) { ncfSum += tax.yearly[t].ncf; }

  return {
    X: X, swap_fee: swap_fee, spare_bats: spare_bats, spare_rent: spare_rent,
    station_invest: station_invest, op_mode: op_mode, max_swaps: max_swaps,
    swap_net_kwh: swap_net_kwh, sc_net_kwh: sc_net_kwh,
    // 含税金额（用于显示）
    swap_loss_incl: swap_loss_incl, sc_loss_incl: sc_loss_incl,
    total_loss_incl: total_loss_incl, total_elec_cost_incl: total_elec_cost_incl,
    swap_rev_incl: swap_rev_incl, sc_rev_incl: sc_rev_incl,
    ccer_incl: ccer_incl, vpp_incl: vpp_incl, total_revenue_incl: total_revenue_incl,
    labor: labor, rent_cost_incl: rent_cost_incl, maint_incl: maint_incl,
    equip_insur_incl: equip_insur_incl,
    spare_rent_cost_incl: spare_rent_cost_incl, tech_service_incl: tech_service_incl,
    total_opex_incl: total_opex_incl,
    // 方案A：换电/超充分摊成本
    swap_opex_incl: swap_opex_incl, sc_opex_incl: sc_opex_incl,
    swap_rev_ratio: swap_rev_ratio, sc_rev_ratio: sc_rev_ratio,
    swap_kwh_ratio: swap_kwh_ratio, sc_kwh_ratio: sc_kwh_ratio,
    // 不含税金额
    rev_excl: rev_excl, opex_excl: opex_excl, ebitda_excl: ebitda_excl,
    depreciation: depreciation,
    fixed_opex_excl: fixed_opex_excl, rev_per_swap_excl: rev_per_swap_excl,
    var_cost_per_swap: var_cost_per_swap,
    // 税务
    tax: tax, yr1: yr1, net_margin: net_margin,
    // 计算值
    irr: irr, payback: payback, breakeven: breakeven, breakeven_raw: breakeven_raw,
    npv: npv_val, ncf_sum: ncfSum,
    // 方案A：独立盈亏平衡
    swap_breakeven: swap_breakeven, swap_breakeven_raw: swap_breakeven_raw,
    sc_pbt: sc_pbt, sc_profitable: sc_profitable,
    // 用户结构
    comm_users: comm_users, priv_users: priv_users, total_users: total_users,
    comm_ratio: comm_ratio,
    sc_cars: sc_cars, sc_kwh: sc_kwh, sc_fee: sc_fee
  };
};
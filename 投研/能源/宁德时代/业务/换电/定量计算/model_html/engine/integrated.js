/**
 * ============================================================
 * engine/integrated.js — 一体化运营模型（换电站 + 电池银行）
 * ============================================================
 *
 * 核心逻辑（先一体化 → 再分拆）：
 *
 *   【第一步】一体化全自持模型 —— 整盘生意先算总账
 *     把换电站和电池银行视为一个整体，合并所有资产/收入/成本，
 *     消除内部结算，计算整合后的IRR/NPV。
 *     如果一体化IRR > 门槛收益率，说明整盘生意成立。
 *
 *   【第二步】分拆定价 —— 通过内部结算价分配利润
 *     一体化成立后，通过两个内部结算参数，把利润
 *     在换电站和电池银行之间重新分配：
 *       - 周转电池租金：240元/月/块 → 站→银行
 *       - 技术服务费：3.5万/年/站 → 站→银行
 *     调整这两个参数使两边各自获得合理IRR。
 *     合并层面：内部结算互相抵消，不影响一体化总利润。
 *
 * 数据流方向：
 *   constants → station+batteryBank(单站) → integrated(合并) → scale+valuation
 *
 * 加载顺序：在 constants.js, station.js, batteryBank.js, tax.js 之后
 * 对应MD文档：宁德时代_超换一体站_财务模型_修正版.md
 * ============================================================
 */
var Engine = window.Engine || {};

/**
 * 计算一体化运营模型（合并换电站+电池银行，消除内部结算）
 *
 * 调用此函数前，需要先分别计算换电站和电池银行单站模型。
 *
 * @param {Object} p - 参数对象
 *   p.st              - 换电站单站模型结果（Engine.calcPureStation 的返回值）
 *   p.bb              - 电池银行单站模型结果（Engine.calcBatteryBank 的返回值）
 *   p.discount_rate   - 折现率（小数，默认 0.075）
 *
 * @returns {Object} 一体化模型，包含：
 *   .st, .bb           - 原始单站模型
 *   .total_rev_excl    - 合并不含税收入
 *   .total_opex_excl   - 合并不含税OPEX（已消除内部结算）
 *   .ebitda_excl       - 合并EBITDA
 *   .total_capex       - 合并总CAPEX
 *   .depreciation      - 合并折旧
 *   .irr               - 合并IRR
 *   .npv               - 合并NPV
 *   .yearly            - 逐年合并税务明细
 *   .internal_elim_excl - 内部结算消除金额
 */
Engine.calcIntegrated = function (p) {
  var st = p.st;
  var bb = p.bb;
  if (!st) {
    st = Engine.calcPureStation(p);  // 如果调用方未预计算，则自动从原始参数推算
  }
  if (!bb) {
    bb = Engine.calcBatteryBank({ ...p, st: st });  // 连带运转电池银行模型
  }
  var discountRate = (typeof p.discount_rate !== 'undefined') ? p.discount_rate : Engine.DEFAULT_DISCOUNT_RATE;
  var YEARS = Engine.YEARS || 15;

  // ============================================================
  // 一、合并收入与成本（消除内部结算）
  // ============================================================
  // 内部结算消除（不含税）：周转电池租金 + 技术服务费
  //   站付给银行 = 站成本 = 银行收入 → 合并层面同时消除收入端和成本端
  var internal_elim_excl = st.spare_rent_cost_incl / (1 + Engine.VAT_13) + st.tech_service_incl / (1 + Engine.VAT_6);

  // 注：tech_service_cost 已在 batteryBank.js 中改为按默认费率计算（固定成本），
  // 不再随内部结算参数变化，因此无需额外消除逻辑

  // 不含税合并：收入端消除银行内部结算收入，成本端消除站内部结算成本
  var total_rev_excl = st.rev_excl + bb.rev_excl - internal_elim_excl;
  var total_opex_excl = st.opex_excl + bb.opex_excl - internal_elim_excl;
  var ebitda_excl = total_rev_excl - total_opex_excl;

  // 合并CAPEX与折旧
  var total_capex_incl = st.station_invest + bb.total_capex;
  var depreciation = st.depreciation + bb.depreciation;

  // ============================================================
  // 二、合并税务计算（消除内部结算税务影响）
  // ============================================================
  // 合并销项税
  var stOut13 = st.swap_rev_incl / (1 + Engine.VAT_13) * Engine.VAT_13 + st.sc_rev_incl / (1 + Engine.VAT_13) * Engine.VAT_13;
  var stOut6  = st.ccer_incl / (1 + Engine.VAT_6) * Engine.VAT_6 + st.vpp_incl / (1 + Engine.VAT_6) * Engine.VAT_6;
  var bbOut13 = bb.user_rent_rev_incl / (1 + Engine.VAT_13) * Engine.VAT_13 + bb.spare_rent_rev_incl / (1 + Engine.VAT_13) * Engine.VAT_13;
  var bbOut6  = bb.tech_service_rev_incl / (1 + Engine.VAT_6) * Engine.VAT_6;

  // 内部结算消除：一方销项=另一方进项，互抵
  var internalOut13 = st.spare_rent_cost_incl / (1 + Engine.VAT_13) * Engine.VAT_13;
  var internalOut6  = st.tech_service_incl / (1 + Engine.VAT_6) * Engine.VAT_6;
  var outVAT = stOut13 + stOut6 + bbOut13 + bbOut6 - internalOut13 - internalOut6;

  // 合并进项税
  var stIn13 = (st.total_loss_incl + st.total_elec_cost_incl + st.maint_incl) / (1 + Engine.VAT_13) * Engine.VAT_13;
  var stIn6  = st.equip_insur_incl / (1 + Engine.VAT_6) * Engine.VAT_6;
  var bbIn13 = bb.bat_maint_incl / (1 + Engine.VAT_13) * Engine.VAT_13;
  var bbIn6  = (bb.tech_service_cost_incl + bb.bat_insur_incl) / (1 + Engine.VAT_6) * Engine.VAT_6;
  var rentIn = st.rent_cost_incl / (1 + Engine.RENT_VAT) * Engine.RENT_VAT;
  // 注：tech_service_cost 已改为固定成本，进项税无需额外消除
  var inVAT_opex = stIn13 + stIn6 + bbIn13 + bbIn6 + rentIn - internalOut13 - internalOut6;

  // 资产进项税
  var assetVAT_st = st.station_invest / (1 + Engine.VAT_13) * Engine.VAT_13;
  var assetVAT_bb = bb.total_capex / (1 + Engine.VAT_13) * Engine.VAT_13;
  var assetVAT = assetVAT_st + assetVAT_bb;

  // ============================================================
  // 三、逐年税务计算（含增值税留抵 + 电池置换税务）
  // ============================================================
  var carryFwd = 0;
  var yearly = [];
  for (var t = 1; t <= YEARS; t++) {
    var inVATTotal = inVAT_opex + carryFwd + (t === 1 ? assetVAT : 0);
    var vatPayable = Math.max(0, outVAT - inVATTotal);
    carryFwd = Math.max(0, inVATTotal - outVAT);

    var surtax_amt = vatPayable * Engine.SURTAX;
    var pbt = ebitda_excl - depreciation - surtax_amt;

    // 电池置换税务影响（新模型：多个年份可能有置换）
    var batReplaceCF = 0;
    if (bb.replaceTaxByYear && bb.replaceTaxByYear[t]) {
      batReplaceCF = bb.replaceTaxByYear[t];
    }

    var incomeTax = Math.max(0, pbt) * Engine.CIT;
    var np = pbt - incomeTax;
    var ncf = np + depreciation + batReplaceCF;

    yearly.push({
      t: t,
      vatPayable: vatPayable,
      surtax: surtax_amt,
      ebitda: ebitda_excl,
      pbt: pbt,
      incomeTax: incomeTax,
      np: np,
      ncf: ncf,
      batReplaceCF: batReplaceCF,
      outVAT: outVAT,
      inVATTotal: inVATTotal,
      carryFwd: carryFwd
    });
  }

  // 15年末残值回收（电池银行残值，换电站10年折旧无残值）
  var itResidualNCF = bb.residualNCF;

  // ============================================================
  // 四、IRR / NPV 计算
  // ============================================================
  var cfs = [-total_capex_incl];
  for (var t2 = 0; t2 < YEARS; t2++) {
    var cf_it = yearly[t2].ncf;
    if (t2 === YEARS - 1) cf_it += itResidualNCF;
    cfs.push(cf_it);
  }
  var irr = Engine.calcIRR(cfs);
  var payback = yearly[0].ncf > 0 ? total_capex_incl / yearly[0].ncf : Infinity;

  // NPV
  var npv_val = -total_capex_incl;
  for (var t3 = 1; t3 <= YEARS; t3++) {
    var cfNPV_it = yearly[t3 - 1].ncf;
    if (t3 === YEARS) cfNPV_it += itResidualNCF;
    npv_val += cfNPV_it / Math.pow(1 + discountRate, t3);
  }

  var yr1 = yearly[0];
  var net_margin = total_rev_excl > 0 ? yr1.np / total_rev_excl : 0;

  return {
    st: st, bb: bb,
    total_rev_excl: total_rev_excl,
    total_opex_excl: total_opex_excl,
    ebitda_excl: ebitda_excl,
    total_capex: total_capex_incl,
    depreciation: depreciation,
    irr: irr, payback: payback, npv: npv_val,
    yearly: yearly, yr1: yr1,
    net_margin: net_margin,
    internal_elim_excl: internal_elim_excl
  };
};
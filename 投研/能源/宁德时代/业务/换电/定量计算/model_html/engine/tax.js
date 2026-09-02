/**
 * ============================================================
 * engine/tax.js — 税务计算模块（增值税 + 附加税 + 所得税）
 * ============================================================
 *
 * 税务模型说明：
 *   中国税制下企业涉及三个主要税种：
 *   1. 增值税（VAT）— 销项税 - 进项税，不同业务适用不同税率
 *   2. 附加税 — 城市维护建设税+教育费附加 = 应交增值税 × 12%
 *   3. 企业所得税（CIT）— 应纳税所得额 × 25%
 *
 * 本文件提供两个函数：
 *   - calcYearlyTax()       不含租金场景（电池银行使用）
 *   - calcYearlyTaxWithRent() 含租金场景（换电站使用，租金9%税率）
 *
 * 加载顺序：在 constants.js 之后
 * ============================================================
 */
var Engine = window.Engine || {};

/**
 * 计算年度税务明细（不含租金场景）
 *
 * 适用场景：电池银行（电池租赁+技术服务费，无场地租金）
 *
 * 计算流程（每年循环）：
 *   1. 销项税 = (13%收入×13%) + (6%收入×6%)           ← 企业向客户收取的税
 *   2. 进项税 = (13%支出×13%) + (6%支出×6%)           ← 企业支付给供应商的税
 *   3. 应交增值税 = max(0, 销项税 - 进项税 - 上年留抵)  ← 抵扣链条
 *   4. 附加税 = 应交增值税 × 12%
 *   5. EBITDA（不含税）= 不含税收入 - 不含税支出
 *   6. 利润总额 = EBITDA - 折旧 - 附加税
 *   7. 所得税 = max(0, 利润总额) × 25%
 *   8. 净利润 = 利润总额 - 所得税
 *   9. 净现金流 = 净利润 + 折旧（折旧是非现金支出，加回）
 *
 * 增值税留抵机制：
 *   如果进项税 > 销项税，差额可结转下年继续抵扣（carryFwd）。
 *   这是资产密集型企业的常见特征——建设期大量设备采购产生进项税大于销项税。
 *
 * @param {number} revenueIncl13 - 适用13%税率的含税收入（换电/超充/电池租赁）
 * @param {number} revenueIncl6  - 适用6%税率的含税收入（技术服务费/VPP/CCER）
 * @param {number} opexIncl13    - 适用13%税率的含税运营支出（电费/维保/仓储物流）
 * @param {number} opexIncl6     - 适用6%税率的含税运营支出（保费/技术服务成本）
 * @param {number} opexNoVAT     - 不含增值税的支出（人工成本）
 * @param {number} assetInputVAT - 资产进项税（第一年设备采购的进项税，一次性抵扣）
 * @param {number} annualDepr    - 年折旧额
 * @returns {{revExcl, opexExcl, ebitda, yearly[]}} 含15年逐年的税务明细
 *
 * 对应MD文档：宁德时代_超换一体站_财务模型_修正版.md # 2.4 税务模型
 */
Engine.calcYearlyTax = function (revenueIncl13, revenueIncl6, opexIncl13, opexIncl6, opexNoVAT, assetInputVAT, annualDepr) {
  // 第一步：计算销项税（企业向客户收取的增值税）
  var outVAT13 = revenueIncl13 / (1 + Engine.VAT_13) * Engine.VAT_13;  // 13%税率对应的销项税
  var outVAT6  = revenueIncl6  / (1 + Engine.VAT_6)  * Engine.VAT_6;   // 6%税率对应的销项税
  var outVAT   = outVAT13 + outVAT6;  // 总销项税

  // 第二步：计算进项税（企业支付给供应商的增值税，可抵扣）
  var inVAT13  = opexIncl13 / (1 + Engine.VAT_13) * Engine.VAT_13;
  var inVAT6   = opexIncl6  / (1 + Engine.VAT_6)  * Engine.VAT_6;
  var inVAT_opex = inVAT13 + inVAT6;  // 运营支出对应的进项税

  // 第三步：计算不含税口径的收入与支出（用于EBITDA计算）
  //  含税价 → 不含税价：不含税 = 含税 / (1 + 税率)
  var revExcl  = (revenueIncl13 / (1 + Engine.VAT_13)) + (revenueIncl6 / (1 + Engine.VAT_6));
  var opexExcl = (opexIncl13    / (1 + Engine.VAT_13)) + (opexIncl6    / (1 + Engine.VAT_6)) + opexNoVAT;
  var ebitda   = revExcl - opexExcl;

  // 第四步：逐年计算税务明细
  var yearly = [];
  var carryFwd = 0;  // 增值税留抵余额（上年未抵扣完的进项税）

  for (var t = 1; t <= 15; t++) {
    // 总进项税 = 运营进项 + 上年留抵 +（第一年加资产进项）
    var inVATTotal = inVAT_opex + carryFwd + (t === 1 ? assetInputVAT : 0);

    // 应交增值税 = 销项 - 进项（负数时不用交，差额结转下年）
    var vatPayable = Math.max(0, outVAT - inVATTotal);
    carryFwd = Math.max(0, inVATTotal - outVAT);

    // 附加税 = 应交增值税 × 12%
    var surtax = vatPayable * Engine.SURTAX;

    // 利润总额 = EBITDA - 折旧 - 附加税
    var pbt = ebitda - annualDepr - surtax;

    // 所得税 = max(0, 利润总额) × 25%（亏损不交税）
    var incomeTax = Math.max(0, pbt) * Engine.CIT;

    // 净利润 = 利润总额 - 所得税
    var np = pbt - incomeTax;

    // 净现金流 = 净利润 + 折旧（折旧是会计摊销，不产生现金流出）
    var ncf = np + annualDepr;

    yearly.push({
      t: t,                  // 年份（1-15）
      vatPayable: vatPayable, // 应交增值税
      surtax: surtax,        // 附加税
      ebitda: ebitda,        // 息税折旧前利润
      pbt: pbt,              // 利润总额
      incomeTax: incomeTax,  // 所得税
      np: np,                // 净利润
      ncf: ncf,              // 净现金流（IRR计算输入）
      outVAT: outVAT,        // 销项税
      inVATTotal: inVATTotal, // 总进项税
      carryFwd: carryFwd     // 期末留抵余额
    });
  }

  return { revExcl: revExcl, opexExcl: opexExcl, ebitda: ebitda, yearly: yearly };
};

/**
 * 计算年度税务明细（含租金场景）
 *
 * 适用场景：换电站（含场地租金，租金适用9%增值税率）
 *
 * 与 calcYearlyTax 的区别：
 *   - 租金作为额外的含9%增值税的支出
 *   - 租金的进项税额外加入进项税计算
 *   - 租金的"不含税"部分单独计入opexExcl
 *
 * @param {number} rentExcl      - 租金不含税部分
 * @param {number} rentVAT       - 租金增值税（= 含税租金 / 1.09 × 0.09）
 * @param {number} assetInputVAT - 资产进项税（第一年抵扣）
 * @param {number} annualDepr    - 年折旧额
 *
 * 对应MD文档：与 calcYearlyTax 一致，仅增加租金处理
 */
Engine.calcYearlyTaxWithRent = function (revenueIncl13, revenueIncl6, opexIncl13, opexIncl6, opexNoVAT, rentExcl, rentVAT, assetInputVAT, annualDepr) {
  var outVAT13 = revenueIncl13 / (1 + Engine.VAT_13) * Engine.VAT_13;
  var outVAT6  = revenueIncl6  / (1 + Engine.VAT_6)  * Engine.VAT_6;
  var outVAT   = outVAT13 + outVAT6;

  // 租金的进项税（9%税率）加入总进项
  var inVAT13  = opexIncl13 / (1 + Engine.VAT_13) * Engine.VAT_13;
  var inVAT6   = opexIncl6  / (1 + Engine.VAT_6)  * Engine.VAT_6;
  var inVAT_opex = inVAT13 + inVAT6 + rentVAT;

  var revExcl  = (revenueIncl13 / (1 + Engine.VAT_13)) + (revenueIncl6 / (1 + Engine.VAT_6));
  // 租金的不含税部分单独计入opexExcl
  var opexExcl = (opexIncl13 / (1 + Engine.VAT_13)) + (opexIncl6 / (1 + Engine.VAT_6)) + opexNoVAT + rentExcl;
  var ebitda   = revExcl - opexExcl;

  var yearly = [];
  var carryFwd = 0;
  for (var t = 1; t <= 15; t++) {
    var inVATTotal = inVAT_opex + carryFwd + (t === 1 ? assetInputVAT : 0);
    var vatPayable = Math.max(0, outVAT - inVATTotal);
    carryFwd = Math.max(0, inVATTotal - outVAT);
    var surtax = vatPayable * Engine.SURTAX;
    var pbt = ebitda - annualDepr - surtax;
    var incomeTax = Math.max(0, pbt) * Engine.CIT;
    var np = pbt - incomeTax;
    var ncf = np + annualDepr;
    yearly.push({
      t: t, vatPayable: vatPayable, surtax: surtax, ebitda: ebitda,
      pbt: pbt, incomeTax: incomeTax, np: np, ncf: ncf,
      outVAT: outVAT, inVATTotal: inVATTotal, carryFwd: carryFwd
    });
  }

  return { revExcl: revExcl, opexExcl: opexExcl, ebitda: ebitda, yearly: yearly };
};

// ============================================================
// 辅助工具函数（已含税/不含税转换）
// ============================================================

/** 含税价 → 不含税价：不含税 = 含税 / (1 + 税率) */
Engine.exclTax = function (incl, rate) { return incl / (1 + rate); };

/** 含税价 → 增值税额：增值税 = 含税 / (1 + 税率) × 税率 */
Engine.calcVAT = function (incl, rate) { return Engine.exclTax(incl, rate) * rate; };

/** 与 calcVAT 同义，从含税价反推进项/销项增值税额 */
Engine.inclToVAT = function (incl, rate) { return Engine.exclTax(incl, rate) * rate; };
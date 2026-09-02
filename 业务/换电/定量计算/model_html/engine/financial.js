/**
 * ============================================================
 * engine/financial.js — 财务计算工具（IRR / NPV）
 * ============================================================
 * 本文件提供两个底层财务函数：IRR（内部收益率）和 NPV（净现值）。
 * 所有上层模型（换电站/电池银行/一体化）都调用这两个函数。
 *
 * IRR 算法：牛顿迭代法（Newton-Raphson），默认初始猜测 10%
 * 加载顺序：在 constants.js 之后
 * ============================================================
 */
var Engine = window.Engine || {};

/**
 * 计算内部收益率（IRR）
 *
 * @param {number[]} cashflows - 现金流数组，索引0为初始投资（负数），索引1~n为各期净现金流
 * @param {number} [guess=0.1] - 初始猜测值，默认 10%
 * @returns {number|null} - 年化 IRR（小数形式，如 0.15 = 15%），无解时返回 null
 *
 * 算法说明：
 *   - 使用牛顿迭代法：r_new = r - NPV(r) / NPV'(r)
 *   - 最多迭代 1000 次
 *   - 收敛条件：|NPV| < 1e-8
 *   - 如果现金流全正或全负（即不存在收益率），返回 null
 *   - 如果计算出的 IRR < -99% 或为 NaN，返回 null
 *
 * 示例：
 *   calcIRR([-100, 10, 10, 10, 10, 110])  // → ~0.10 (10%)
 */
Engine.calcIRR = function (cashflows, guess) {
  guess = guess || 0.1;

  // 检查现金流是否有正有负（IRR存在的必要条件）
  var hasPos = false, hasNeg = false;
  for (var i = 0; i < cashflows.length; i++) {
    if (cashflows[i] > 0) hasPos = true;
    if (cashflows[i] < 0) hasNeg = true;
  }
  if (!hasPos || !hasNeg) return null;

  var rate = guess;
  for (var iter = 0; iter < 1000; iter++) {
    // 计算 NPV 和 NPV 的一阶导数（用于牛顿迭代）
    var npv = 0, dnpv = 0;
    for (var t = 0; t < cashflows.length; t++) {
      var denom = Math.pow(1 + rate, t);
      npv += cashflows[t] / denom;
      if (t > 0) dnpv += -t * cashflows[t] / (denom * (1 + rate));
    }
    if (Math.abs(dnpv) < 1e-15) break;
    var newRate = rate - npv / dnpv;
    // 安全边界：防止迭代发散
    if (newRate < -0.99) newRate = -0.5;
    if (newRate > 10) newRate = 5;
    rate = newRate;
    if (Math.abs(npv) < 1e-8) break;
  }

  // 验证最终结果
  var finalNPV = 0;
  for (var t2 = 0; t2 < cashflows.length; t2++) {
    finalNPV += cashflows[t2] / Math.pow(1 + rate, t2);
  }
  if (Math.abs(finalNPV) > Math.abs(cashflows[0]) * 0.01) return null;
  if (rate < -0.99 || isNaN(rate) || !isFinite(rate)) return null;
  return rate;
};

/**
 * 计算净现值（NPV）
 *
 * @param {number[]} cashflows - 现金流数组，索引0为初始投资（负数），索引1~n为各期净现金流
 * @param {number} discountRate - 折现率（小数形式，如 0.075 = 7.5%）
 * @returns {number} - 净现值
 *
 * 公式：NPV = Σ CF_t / (1 + r)^t
 *
 * 示例：
 *   calcNPV([-100, 10, 10, 110], 0.075)  // → ~2.86
 */
Engine.calcNPV = function (cashflows, discountRate) {
  var npv = 0;
  for (var t = 0; t < cashflows.length; t++) {
    npv += cashflows[t] / Math.pow(1 + discountRate, t);
  }
  return npv;
};
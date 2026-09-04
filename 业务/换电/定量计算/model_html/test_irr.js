// 测试IRR计算逻辑 - 修复后版本
function calcIRR(cashflows, guess) {
  if (guess === undefined) guess = 0.1;
  // 前置检查：现金流必须存在符号变化，否则IRR无实数解
  var hasPos = false, hasNeg = false;
  for (var ci = 0; ci < cashflows.length; ci++) {
    if (cashflows[ci] > 0) hasPos = true;
    if (cashflows[ci] < 0) hasNeg = true;
  }
  if (!hasPos || !hasNeg) return null; // 全正或全负，IRR无实数解

  let rate = guess;
  for (let iter = 0; iter < 1000; iter++) {
    let npv = 0, dnpv = 0;
    for (let t = 0; t < cashflows.length; t++) {
      const denom = Math.pow(1 + rate, t);
      npv += cashflows[t] / denom;
      if (t > 0) dnpv += -t * cashflows[t] / (denom * (1 + rate));
    }
    if (Math.abs(dnpv) < 1e-15) break;
    let newRate = rate - npv / dnpv;
    if (newRate < -0.99) newRate = -0.5;
    if (newRate > 10) newRate = 5;
    rate = newRate;
    if (Math.abs(npv) < 1e-8) break;
  }
  // 收敛性验证
  var finalNPV = 0;
  for (let t = 0; t < cashflows.length; t++) {
    finalNPV += cashflows[t] / Math.pow(1 + rate, t);
  }
  if (Math.abs(finalNPV) > Math.abs(cashflows[0]) * 0.01) return null;
  if (rate < -0.99 || isNaN(rate) || !isFinite(rate)) return null;
  return rate;
}

// 测试1: 正常投资（负初始，正后续）
console.log("=== 测试1: 正常投资 ===");
var cfs1 = [-100, 20, 20, 20, 20, 20, 20, 20, 20, 20, 120];
console.log("IRR:", calcIRR(cfs1) !== null ? (calcIRR(cfs1) * 100).toFixed(1) + "%" : "null");

// 测试2: 全部正现金流（无初始投资）
console.log("\n=== 测试2: 全部正现金流 ===");
var cfs2 = [100, 20, 20, 20, 20, 20, 20, 20, 20, 20, 120];
console.log("IRR:", calcIRR(cfs2));

// 测试3: 全负现金流
console.log("\n=== 测试3: 全负现金流 ===");
var cfs3 = [-100, -10, -10, -10];
console.log("IRR:", calcIRR(cfs3));

// 测试4: 初始为0
console.log("\n=== 测试4: 初始为0 ===");
var cfs4 = [0, 100, 100, 100];
console.log("IRR:", calcIRR(cfs4));

// 测试5: 电池银行正常场景
console.log("\n=== 测试5: 电池银行正常场景 ===");
var batCost = 38942;
var annualRent = 529 * 12; // 6348
var residual = batCost * 0.10; // 3894
var cfs5 = [-batCost];
for (var t = 1; t < 15; t++) cfs5.push(annualRent);
cfs5.push(annualRent + residual);
console.log("IRR:", calcIRR(cfs5, 0.05) !== null ? (calcIRR(cfs5, 0.05) * 100).toFixed(1) + "%" : "null");

// 测试6: 悲观场景 - 换电站亏损
console.log("\n=== 测试6: 悲观换电站(亏损) ===");
var stationInvest = 2150000;
var cfs6 = [-stationInvest];
// 亏损场景：NCF为负
for (var t = 0; t < 15; t++) cfs6.push(-50000);
console.log("全负NCF IRR:", calcIRR(cfs6));

// 测试7: 悲观场景 - 部分NCF为正部分为负
console.log("\n=== 测试7: 混合NCF ===");
var cfs7 = [-2150000];
cfs7.push(50000); // 第1年小正
for (var t = 1; t < 15; t++) cfs7.push(-10000); // 后续为负
console.log("混合NCF IRR:", calcIRR(cfs7) !== null ? (calcIRR(cfs7) * 100).toFixed(1) + "%" : "null");

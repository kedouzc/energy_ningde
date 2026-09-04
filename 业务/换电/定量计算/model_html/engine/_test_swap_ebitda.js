const fs = require('fs');
const vm = require('vm');
const path = require('path');
const engineDir = __dirname;
const loadOrder = ['constants.js','userStructure.js','tax.js','financial.js','station.js','batteryBank.js','integrated.js','manufacturing.js','scale.js','rental.js','sensitivity.js','valuation.js'];
const sandbox = { console: console, Math: Math, Object: Object, Array: Array, JSON: JSON, window: {} };
vm.createContext(sandbox);
for (const f of loadOrder) {
  const fp = path.join(engineDir, f);
  if (!fs.existsSync(fp)) continue;
  let code = fs.readFileSync(fp, 'utf-8');
  code = code.replace(/var Engine = window\.Engine \|\| \{\};/g, 'window.Engine = window.Engine || {}; var Engine = window.Engine;');
  vm.runInContext(code, sandbox, { filename: f });
}
const Engine = sandbox.Engine;
// 彻底退出后：保留20%小股权，原持40%，管理费按EV=1%，hurdle=6%，carry=25%
const r = Engine.calcSwapEBITDAValuation({
  ebitdaWhole: 528, projectDebt: 2147, catlEquity: 0.20, exitEquity: 0.40,
  feeRate: 0.01, hurdle: 0.06, carryRate: 0.25, multiples: [18]
});
const g = r.gp_light[0];
console.log('=== GP轻资产(保留20%股权) @18× ===');
console.log('  整包EV            :', g.ev, '亿');
console.log('  一次性处置增益(脉冲):', g.disposalGain.toFixed(0), '亿  (卖出20%份额: EV×20% − 初装×20%)');
console.log('  可持续经常性合计   :', g.recurring.toFixed(0), '亿/年');
console.log('    其中 管理费(EV×1%):', g.fee.toFixed(0));
console.log('    其中 carry(超额)  :', g.carry.toFixed(0), ' (EBITDA−EV×6% =', (528 - g.ev*0.06).toFixed(0), ')');
console.log('    其中 小股权分红   :', g.equityDiv.toFixed(0), ' (年现金193×20%)');
console.log('\n=== 对照 ===');
console.log('  现状权益法@18×(持40%):', r.comparison18.equity.toFixed(0), '亿');
console.log('  整块上限参考@18×     :', r.comparison18.control_whole.toFixed(0), '亿');

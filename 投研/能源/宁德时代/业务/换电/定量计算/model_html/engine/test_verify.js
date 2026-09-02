var fs = require('fs');
var files = ['constants.js','financial.js','tax.js','rental.js','userStructure.js','station.js','batteryBank.js','integrated.js','scale.js','manufacturing.js'];
var ctx = { Engine: {} };

for (var i = 0; i < files.length; i++) {
  var code = fs.readFileSync(files[i], 'utf8');
  var fn = new Function('window', code);
  fn(ctx);
}

// Test calcConstructionPace
var pace = ctx.Engine.calcConstructionPace(50000, 100000);
console.log('=== calcConstructionPace ===');
console.log('Pace length:', pace.length);
console.log('First:', pace[0].label, 'self:', pace[0].self, 'partner:', pace[0].partner);
console.log('Last:', pace[pace.length-1].label, 'self:', pace[pace.length-1].self, 'partner:', pace[pace.length-1].partner);

// Test calcMfgScenario
var mfg = ctx.Engine.calcMfgScenario('中性', 50000, 100000);
console.log('\n=== calcMfgScenario ===');
console.log('Rows:', mfg.rows.length);
console.log('Cumul bats:', mfg.cumulBats.toFixed(0));
console.log('Cumul mfg profit:', (mfg.cumulMfgProfit/100000000).toFixed(2)+'亿');
console.log('Replace bats:', mfg.replaceBats.toFixed(0));
console.log('Replace profit:', (mfg.profitReplace/100000000).toFixed(2)+'亿');

// Test calcCombinedScaleRevenue
var p = {
  daily_swaps: 115, cell_cost: 0.38, pack_integration_cost: 0.10, gross_margin: 22,
  spare_rent: 240, total_stations: 50000, discount_rate: 7.5,
  swap_fee_val: 0.40, spare_bats: 14, station_invest: 215,
  op_mode: '16h', fam_ratio: 0.9, bat_replace_strategy: 'B'
};
var d = ctx.Engine.calcCombinedScaleRevenue(p);
console.log('\n=== calcCombinedScaleRevenue ===');
console.log('Multi-scenario count:', d.multiScenario.length);
console.log('Annual data rows:', d.annualData.length);
console.log('Neutral IRR:', (d.multiScenario[1].it_irr*100).toFixed(2)+'%');
console.log('Pessimistic IRR:', (d.multiScenario[0].it_irr*100).toFixed(2)+'%');
console.log('Optimistic IRR:', (d.multiScenario[2].it_irr*100).toFixed(2)+'%');
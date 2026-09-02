/**
 * 临时调试脚本：验证 calcIntegrated 是否正确返回数据
 */
var vm = require('vm');
var fs = require('fs');
var path = require('path');

var engineDir = __dirname;

// 创建沙箱
var sandbox = {
  window: {},
  console: console,
  setTimeout: setTimeout,
  Date: Date,
  Math: Math,
  JSON: JSON,
  Array: Array,
  Object: Object,
  String: String,
  Number: Number,
  Boolean: Boolean,
  parseInt: parseInt,
  parseFloat: parseFloat,
  isNaN: isNaN,
  Infinity: Infinity,
  NaN: NaN,
  undefined: undefined,
  RegExp: RegExp,
  Error: Error
};
sandbox.window = sandbox;
vm.createContext(sandbox);

var loadOrder = [
  'constants.js', 'financial.js', 'tax.js', 'rental.js', 'userStructure.js',
  'station.js', 'batteryBank.js', 'integrated.js', 'scale.js', 'valuation.js',
  'params_spec.js', 'sensitivity.js', 'optimizer.js'
];

for (var i = 0; i < loadOrder.length; i++) {
  var fp = path.join(engineDir, loadOrder[i]);
  if (!fs.existsSync(fp)) continue;
  var code = fs.readFileSync(fp, 'utf-8');
  code = code.replace(/var Engine = window\.Engine \|\| \{\};/g,
    'window.Engine = window.Engine || {}; var Engine = window.Engine;');
  vm.runInContext(code, sandbox, { filename: loadOrder[i] });
}

var Engine = sandbox.Engine;
console.log('Engine loaded, keys:', Object.keys(Engine).length);

// 检查关键常量
console.log('VAT_13:', Engine.VAT_13);
console.log('VAT_6:', Engine.VAT_6);
console.log('VAT_9:', Engine.VAT_9);
console.log('SURTAX:', Engine.SURTAX);
console.log('CIT:', Engine.CIT);
console.log('BAT_CAP_KWH:', Engine.BAT_CAP_KWH);
console.log('BAT_PRICE_PER_KWH:', Engine.BAT_PRICE_PER_KWH);
console.log('SWAP_SERVICE_FEE:', Engine.SWAP_SERVICE_FEE);
console.log('BAT_RESIDUAL_RATE:', Engine.BAT_RESIDUAL_RATE);
console.log('RENTAL_MONTHLY_FAM:', Engine.RENTAL_MONTHLY_FAM);
console.log('RENTAL_MONTHLY_BUS:', Engine.RENTAL_MONTHLY_BUS);
console.log('FAM_RATIO:', Engine.FAM_RATIO);
console.log('BUS_RATIO:', Engine.BUS_RATIO);
console.log('STATION_EQUIP:', Engine.STATION_EQUIP);
console.log('STATION_OTHER:', Engine.STATION_OTHER);
console.log('STATION_DEPR_YRS:', Engine.STATION_DEPR_YRS);
console.log('BAT_DEPR_YRS:', Engine.BAT_DEPR_YRS);
console.log('BAT_RESIDUAL_RATE:', Engine.BAT_RESIDUAL_RATE);
console.log('MANUAL_RENTAL_OVERRIDE:', Engine.MANUAL_RENTAL_OVERRIDE);
console.log('RENTAL_BASE_OVERRIDE:', Engine.RENTAL_BASE_OVERRIDE);
console.log('');
console.log('RENTAL_PER_BLOCK:', Engine.RENTAL_PER_BLOCK);
console.log('SWAP_FEE_PER_KWH:', Engine.SWAP_FEE_PER_KWH);
console.log('CHG_FEE_PER_KWH:', Engine.CHG_FEE_PER_KWH);
console.log('BAT_SELL_PRICE:', Engine.BAT_SELL_PRICE);
console.log('PRICE_PER_BLOCK:', Engine.PRICE_PER_BLOCK);
console.log('STATION_FIXED_COST:', Engine.STATION_FIXED_COST);
console.log('BAT_PER_STATION:', Engine.BAT_PER_STATION);
console.log('BAT_EXTRA:', Engine.BAT_EXTRA);
console.log('STATION_AREA:', Engine.STATION_AREA);
console.log('CCER_PRICE:', Engine.CCER_PRICE);
console.log('RENTAL_MONTHLY_PER_BAT:', Engine.RENTAL_MONTHLY_PER_BAT);
console.log('PLATFORM_MONTHLY:', Engine.PLATFORM_MONTHLY);
console.log('EXTERNAL_BAT_RENTAL:', Engine.EXTERNAL_BAT_RENTAL);
console.log('BAT_INSURANCE_RATE:', Engine.BAT_INSURANCE_RATE);
console.log('BAT_WARRANTY_RATE:', Engine.BAT_WARRANTY_RATE);
console.log('BAT_WAREHOUSE_RATE:', Engine.BAT_WAREHOUSE_RATE);
console.log('BAT_DEGRADE_FACTOR:', Engine.BAT_DEGRADE_FACTOR);
console.log('SOH_OPERATIONAL_EXIT:', Engine.SOH_OPERATIONAL_EXIT);
console.log('SOH_PRIVATE_EXIT:', Engine.SOH_PRIVATE_EXIT);

// 测试调用
var p = { dailySwaps: 115, stationCount: 1000, discountRate: 7.5 };

// 先单独测试 station 和 bank
var stationPure = Engine.calcPureStation(p);
var bankPure = Engine.calcBatteryBank(p);

console.log('=== Station (single) ===');
console.log('cashflows[0]:', stationPure.cashflows[0]);
console.log('cashflows[1]:', stationPure.cashflows[1]);
console.log('cashflows[2]:', stationPure.cashflows[2]);
console.log('cashflows length:', stationPure.cashflows.length);

console.log('');
console.log('=== Battery Bank ===');
console.log('cashflows[0]:', bankPure.cashflows[0]);
console.log('cashflows[1]:', bankPure.cashflows[1]);
console.log('cashflows[2]:', bankPure.cashflows[2]);
console.log('cashflows length:', bankPure.cashflows.length);

console.log('');
console.log('=== Station financial ===');
console.log('irr:', stationPure.financial.irr);
console.log('npv:', stationPure.financial.npv);

console.log('');
console.log('=== Bank financial ===');
console.log('irr:', bankPure.financial.irr);
console.log('npv:', bankPure.financial.npv);

var result = Engine.calcIntegrated(p);
console.log('');
console.log('=== Integrated ===');
console.log('integrated.irr:', result.integrated.irr);
console.log('integrated.npv:', result.integrated.npv);
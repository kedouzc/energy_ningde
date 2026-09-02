const fs = require('fs');
const path = require('path');
const vm = require('vm');

const P = require(path.join(__dirname, '宁德时代', 'data', 'battery_prices.js'));
const md = fs.readFileSync(path.join(__dirname, '宁德时代', 'data', '电池价格口径统一与pack价格参考.md'), 'utf8');
const { S, D } = P.fromMarkdown(md);
console.log('cellNmc(from md)=', S.anchors.nmcCellY0, 'marketNmc=', S.market.nmcY0);

// constants.js 用 var Engine = window.Engine || {}，需在全局上下文执行
global.window = global;
const CONST = path.join(__dirname, '宁德时代', '业务', '换电', '财务模型', 'engine', 'constants.js');
vm.runInThisContext(fs.readFileSync(CONST, 'utf8'), { filename: CONST });
const E = global.Engine;
console.log('Engine loaded?', !!E);
console.log('POWER_CELL_BY_YEAR[0..3]', E.POWER_CELL_BY_YEAR.slice(0, 4));
const p0 = E.getBatteryPriceByYear(0);
const p8 = E.getBatteryPriceByYear(8);
console.log('Y0 settlementPerBlock', p0.settlementPerBlock, 'marketPack', p0.marketPackPrice, 'cellNmc', E.PRICE_Y0.cellNmc);
console.log('Y8 settlementPerBlock', p8.settlementPerBlock, 'marketPack', p8.marketPackPrice);
console.log('BAT_PRICE_BY_YEAR[0..3]', E.BAT_PRICE_BY_YEAR.slice(0, 4));
console.log('BLOCK[0]=', E.BLOCK_PRICE_BY_YEAR[0], '(手册 30,400)');

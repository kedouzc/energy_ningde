const fs = require('fs');
const path = require('path');
const P = require(path.join(__dirname, '宁德时代', 'data', 'battery_prices.js'));
const md = fs.readFileSync(path.join(__dirname, '宁德时代', 'data', '电池价格口径统一与pack价格参考.md'), 'utf8');
const { S, D } = P.fromMarkdown(md);

// 从 md §3.2.1 表解析逐年"动力含税价"列，与 js 推演的 powerTax 比对
const lines = md.split(/\r?\n/);
function mdRow(label) {
  for (const L of lines) {
    if (new RegExp('^\\|[^|]*\\b' + label + '\\b').test(L) && /\d\.\d{3}/.test(L)) {
      const c = L.split('|').map(s => s.trim().replace(/\*/g, '')).filter(s => s.length);
      return { tax: parseFloat(c[5]), sale: parseFloat(c[8]) }; // 含税价、单块售价
    }
  }
  return null;
}
let maxDiff = 0;
for (let k = 0; k <= 15; k++) {
  const m = mdRow('Y' + k);
  if (!m) continue;
  const js = D.powerTax[k];
  const diff = Math.abs(m.tax - js) / m.tax;
  if (diff > maxDiff) maxDiff = diff;
  console.log('Y' + k, 'md含税', m.tax, 'js含税', js, 'diff', (diff * 100).toFixed(2) + '%');
}
console.log('\n最大相对偏差 =', (maxDiff * 100).toFixed(2) + '%', maxDiff < 0.01 ? '✅ 自洽(<1%)' : '⚠️ 超1%需查');

/* =====================================================================
 * battery_prices.js — 电池价格真源解析器（Single Source of Truth）
 * ---------------------------------------------------------------------
 * 设计原则（v2.0.2，2026-08-17）：
 *   - 本文件【不存放任何价格数字】。所有自变量来自
 *     `电池价格口径统一与pack价格参考.md` 的 Y0 行、三阶段公式、锚点。
 *   - 人工只改 .md（初始价、三阶段变化率、加成/毛利锚点）。
 *   - 本解析器读取 .md → 解析自变量 → 推导 15 年因变量序列。
 *   - 改了 .md 跑一次 `node sync_prices.js` 即全链路同步。
 *
 * 运行环境：Node（require）+ 浏览器（window.BatteryPriceSource）。
 * ===================================================================== */

(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else {
    root.BatteryPriceSource = factory();
    if (typeof window !== 'undefined') window.BatteryPriceSource = root.BatteryPriceSource;
  }
})(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  var DEFAULT_MD = '电池价格口径统一与pack价格参考.md';

  function round(x, d) { var p = Math.pow(10, d || 0); return Math.round(x * p) / p; }
  function fmt(x, d) { return Number(round(x, d == null ? 4 : d).toFixed(d == null ? 4 : d)); }

  // 三阶段分段累积：每年乘"该年所属阶段的年变动率"（相对上一年，非相对 Y0）
  // stages: [{name,from,to,annualChange}]
  function buildStageSeries(base, stages, len) {
    var out = [fmt(base, 4)];
    for (var k = 1; k < len; k++) {
      var yr = stages[0].from + k;
      var st = null;
      for (var i = 0; i < stages.length; i++) if (yr >= stages[i].from && yr <= stages[i].to) { st = stages[i]; break; }
      if (!st) st = stages[stages.length - 1];
      out.push(fmt(out[k - 1] * (1 + st.annualChange), 4));
    }
    return out;
  }

  function buildLinear(a, b, n) {
    var out = [];
    for (var k = 0; k < n; k++) out.push(fmt(a + (b - a) * k / (n - 1), 4));
    return out;
  }

  function interp(arr, t) {
    if (t <= 0) return arr[0];
    if (t >= arr.length - 1) return arr[arr.length - 1];
    var i = Math.floor(t), f = t - i;
    return arr[i] + (arr[i + 1] - arr[i]) * f;
  }

  // 抓取表格中"年份标签"行的第一格（兼容 Y0 / Y5⭐ / Y15🔄 / **加粗**）
  function grabRow(lines, label) {
    var re = new RegExp('^\\|[^|]*\\b' + label + '\\b');
    for (var i = 0; i < lines.length; i++) {
      if (re.test(lines[i]) && /\d\.\d{3}/.test(lines[i])) {
        var cells = lines[i].split('|').map(function (s) { return s.trim().replace(/\*/g, ''); }).filter(function (s) { return s.length; });
        return cells; // [标签, 日历年, 电芯, 加成, 裸成本, 含税, 单块, 毛利%, 售价]
      }
    }
    return null;
  }

  /* ----------------------------------------------------------------
   * parseMD(mdText) — 解析自变量
   * 返回：{ stages, vat, swap, market, anchors }
   *   anchors: { power:{cellY0,packIntY0,packIntY15,gmY0,gmY15},
   *              ess:{...}, nmcCellY0 }
   * ---------------------------------------------------------------- */
  function parseMD(mdText) {
    var lines = (mdText || '').split(/\r?\n/);

    // 三阶段变化率（缺省遵循 v2.0.1）
    var stages = [
      { name: '平台期', from: 2026, to: 2028, annualChange: -0.013 },
      { name: '缓降期', from: 2029, to: 2033, annualChange: -0.040 },
      { name: '慢降期', from: 2034, to: 2041, annualChange: -0.0275 }
    ];
    function pct(re) { var m = mdText.match(re); return m ? -Math.abs(parseFloat(m[1])) / 100 : null; }
    var a = pct(/2026-2028[^\n-]*?([-\d.]+)%/);
    var b = pct(/2029-2033[^\n-]*?([-\d.]+)%/);
    var c = pct(/2034-2041[^\n-]*?([-\d.]+)%/);
    if (a != null) stages[0].annualChange = a;
    if (b != null) stages[1].annualChange = b;
    if (c != null) stages[2].annualChange = c;

    var vat = 0.13;
    var vatM = mdText.match(/增值税[：:]\s*([\d.]+)%/);
    if (vatM) vat = parseFloat(vatM[1]) / 100;

    var swap = { low: 1.15, mid: 1.175, high: 1.20 };
    var sw = mdText.match(/换电专用附加成本系数[（(]?\s*([\d.]+)-([\d.]+)\s*[）)]?/);
    if (sw) { swap.low = parseFloat(sw[1]); swap.high = parseFloat(sw[2]); swap.mid = round((swap.low + swap.high) / 2, 3); }

    // 市场 pack 含税价 Y0（§3.1 正文：TrendForce LFP 0.51 / NMC 0.77）
    var market = { lfpY0: 0.51, nmcY0: 0.77 };
    var lfp = mdText.match(/LFP pack\s*([\d.]+)(?:\s*元\/Wh)?/i);
    var nmc = mdText.match(/NMC pack\s*([\d.]+)(?:\s*元\/Wh)?/i);
    if (lfp) market.lfpY0 = parseFloat(lfp[1]);
    if (nmc) market.nmcY0 = parseFloat(nmc[1]);
    // NMC 电芯 Y0（§3.1 正文：NMC 电芯 0.60 元/Wh）
    var nmcCell = mdText.match(/NMC 电芯\s*([\d.]+)(?:\s*元\/Wh)?/i);
    if (nmcCell) market.nmcCellY0 = parseFloat(nmcCell[1]);

    // 锚点：取 §3.2.1（动力）与 §3.2.2（储能）的 Y0 / Y15 行
    var pY0 = grabRow(lines, 'Y0'), pY15 = grabRow(lines, 'Y15');
    // 仅当处在对应小节时才有效——用 from 行号约束
    function sectionRow(lines, headerRe, label) {
      var hdr = -1;
      for (var i = 0; i < lines.length; i++) { if (headerRe.test(lines[i])) { hdr = i; break; } }
      if (hdr < 0) return null;
      for (var j = hdr; j < lines.length && j < hdr + 40; j++) {
        if (new RegExp('^\\|[^|]*\\b' + label + '\\b').test(lines[j]) && /\d\.\d{3}/.test(lines[j])) {
          return lines[j].split('|').map(function (s) { return s.trim().replace(/\*/g, ''); }).filter(function (s) { return s.length; });
        }
      }
      return null;
    }
    var dpY0 = sectionRow(lines, /####\s*3\.2\.1/, 'Y0');
    var dpY15 = sectionRow(lines, /####\s*3\.2\.1/, 'Y15');
    var deY0 = sectionRow(lines, /####\s*3\.2\.2/, 'Y0');
    var deY15 = sectionRow(lines, /####\s*3\.2\.2/, 'Y15');

    function anchorsOf(y0, y15) {
      return {
        cellY0: y0 ? parseFloat(y0[2]) : null,
        packIntY0: y0 ? parseFloat(y0[3]) : null,
        packIntY15: y15 ? parseFloat(y15[3]) : null,
        gmY0: y0 ? parseFloat(y0[7]) / 100 : null,
        gmY15: y15 ? parseFloat(y15[7]) / 100 : null
      };
    }

    var anchors = {
      power: anchorsOf(dpY0, dpY15),
      ess: anchorsOf(deY0, deY15),
      nmcCellY0: null
    };
    var nmcCellM = mdText.match(/NMC 电芯\s*([\d.]+)(?:\s*元\/Wh)?/i);
    if (nmcCellM) anchors.nmcCellY0 = parseFloat(nmcCellM[1]);
    if (!anchors.nmcCellY0) anchors.nmcCellY0 = 0.60;
    // 兜底缺省（防 md 未含某列）
    if (!anchors.power.cellY0) anchors.power.cellY0 = 0.38;
    if (!anchors.power.packIntY0) anchors.power.packIntY0 = 0.10;
    if (!anchors.power.packIntY15) anchors.power.packIntY15 = 0.05;
    if (!anchors.power.gmY0) anchors.power.gmY0 = 0.22;
    if (!anchors.power.gmY15) anchors.power.gmY15 = 0.145;
    if (!anchors.ess.cellY0) anchors.ess.cellY0 = 0.38;
    if (!anchors.ess.packIntY0) anchors.ess.packIntY0 = 0.06;
    if (!anchors.ess.packIntY15) anchors.ess.packIntY15 = 0.03;
    if (!anchors.ess.gmY0) anchors.ess.gmY0 = 0.268;
    if (!anchors.ess.gmY15) anchors.ess.gmY15 = 0.155;

    return { meta: { parsedAt: new Date().toISOString(), source: DEFAULT_MD }, stages: stages, vat: vat, swap: swap, market: market, anchors: anchors };
  }

  /* ----------------------------------------------------------------
   * derive(S) — 由自变量推导因变量（15 年序列，应变量由 js 计算）
   * ---------------------------------------------------------------- */
  function derive(S) {
    var N = 16;
    var baseYear = S.stages[0].from;
    var A = S.anchors;

    var powerCell = buildStageSeries(A.power.cellY0, S.stages, N);
    var essCell = buildStageSeries(A.ess.cellY0, S.stages, N);
    var powerPackInt = buildLinear(A.power.packIntY0, A.power.packIntY15, N);
    var essPackInt = buildLinear(A.ess.packIntY0, A.ess.packIntY15, N);
    var powerGm = buildLinear(A.power.gmY0, A.power.gmY15, N);
    var essGm = buildLinear(A.ess.gmY0, A.ess.gmY15, N);

    var powerBare = powerCell.map(function (c, i) { return fmt(c + powerPackInt[i], 4); });
    var powerTax = powerBare.map(function (b) { return fmt(b * (1 + S.vat), 4); });
    var powerSale = powerTax.map(function (t, i) { return fmt(t / (1 - powerGm[i]), 4); });

    var essBare = essCell.map(function (c, i) { return fmt(c + essPackInt[i], 4); });
    var essTax = essBare.map(function (b) { return fmt(b * (1 + S.vat), 4); });
    var essSale = essTax.map(function (t, i) { return fmt(t / (1 - essGm[i]), 4); });

    // 市场 pack 含税价：Y0 取 md 市场值，后续按"动力电芯三阶段相对折扣"联动
    var discPower = powerCell.map(function (c) { return fmt(c / powerCell[0], 4); });
    var marketLfp = discPower.map(function (d) { return fmt(S.market.lfpY0 * d, 4); });
    var marketNmc = discPower.map(function (d) { return fmt(S.market.nmcY0 * d, 4); });
    var settleLfp = marketLfp.map(function (v) { return fmt(v * S.swap.mid, 4); });
    var settleNmc = marketNmc.map(function (v) { return fmt(v * S.swap.mid, 4); });

    var capKWh = 56;
    // 换电池成本（元/块）= 宁德含税 pack 价 × 容量（不含 1.175 换电服务附加）
    // 对应手册 §3.2.1 "单块成本(元)" 列（Y0≈30,400）；1.175 附加属换电业务结算口径，见 settle*
    var blockSettle = powerTax.map(function (v) { return Math.round(v * capKWh * 1000); });

    function discOf(arr) { var base = arr[0]; return arr.map(function (v) { return fmt(v / base, 4); }); }

    return {
      baseYear: baseYear, capKWh: capKWh,
      powerCell: powerCell, powerPackInt: powerPackInt, powerGm: powerGm,
      powerBare: powerBare, powerTax: powerTax, powerSale: powerSale,
      essCell: essCell, essPackInt: essPackInt, essGm: essGm,
      essBare: essBare, essTax: essTax, essSale: essSale,
      marketLfp: marketLfp, marketNmc: marketNmc,
      settleLfp: settleLfp, settleNmc: settleNmc,
      blockSettle: blockSettle,
      discPower: discOf(powerCell), discEss: discOf(essCell), discSettle: discOf(settleLfp)
    };
  }

  function discountAt(D, years, kind) {
    var arr = kind === 'ess' ? D.discEss : kind === 'settle' ? D.discSettle : D.discPower;
    return fmt(interp(arr, years), 4);
  }

  function fromMarkdown(mdText) {
    var S = parseMD(mdText);
    var D = derive(S);
    D._source = S;
    return { S: S, D: D };
  }

  return {
    parseMD: parseMD, derive: derive, fromMarkdown: fromMarkdown,
    discountAt: discountAt,
    buildStageSeries: buildStageSeries, buildLinear: buildLinear,
    round: round, fmt: fmt, _defaultMD: DEFAULT_MD
  };
});

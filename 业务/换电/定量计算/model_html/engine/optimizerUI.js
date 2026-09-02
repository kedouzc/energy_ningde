/**
 * ============================================================
 * engine/optimizerUI.js — 敏感性分析与自动优化的UI交互逻辑
 * ============================================================
 *
 * 本文件从 model.html 中拆分而来，包含两个核心函数：
 *   - runSensitivityAnalysis()：敏感性分析，找出让一体化IRR达标的最小参数调整
 *   - runAutoOptimizer()：自动优化内部结算参数，使分部IRR达标
 *
 * 依赖：model.html 中的 getParams(), calcIntegrated(), buildCalcParams()
 * 加载顺序：在 model.html 的 <script> 之后加载
 * ============================================================
 */

/**
 * 敏感性分析：找出让一体化IRR达标的最小参数调整
 *
 * 用户可自设目标IRR，页面展示各参数的达标路径。
 * 参数筛选原则：
 *   - 仅包含决策者真正能影响的参数
 *   - 物理机械约束（如周转电池数）不纳入
 *   - 权威机构前瞻预测（如电芯成本、Pack集成成本）不纳入
 *   - 投资额保留但标注约束说明，供内部人士参考
 */
function runSensitivityAnalysis() {
  var resultDiv = document.getElementById('sensitivity_result');
  var targetIRR = parseFloat(document.getElementById('target_irr_input').value) / 100;
  if (isNaN(targetIRR) || targetIRR < 0.03 || targetIRR > 0.15) {
    resultDiv.innerHTML = '<span style="color:#e74c3c">请输入3%~15%之间的目标IRR</span>';
    return;
  }

  var sliderP = getParams();
  var baseIRR = calcIntegrated(sliderP).irr;

  // 已达标
  if (baseIRR >= targetIRR) {
    resultDiv.innerHTML = '<span style="color:#27ae60">✓ 当前一体化IRR ' + (baseIRR * 100).toFixed(2) + '% 已达到目标 ' + (targetIRR * 100).toFixed(1) + '%</span>';
    return;
  }

  // 根据运营模式确定日均换电次数业务上限（16h=125次，24h=140次）
  var dailySwapsBizMax = sliderP.op_mode === '24h' ? 140 : 125;

  // 待测参数：仅包含决策者可影响的参数
  // 筛选原则：物理约束不纳入、权威预测不纳入、投资额保留但加注释
  // 搜索范围 = 业务逻辑范围（min/max即为业务上下限），确保达标值始终在合理区间内
  var tests = [
    {key: 'daily_swaps', label: '日均换电次数', base: sliderP.daily_swaps, min: 80, max: dailySwapsBizMax, step: 5, dir: 1, unit: '次', note: '', sliderId: 'daily_swaps_slider', bizNote: '16h模式上限' + dailySwapsBizMax + '次'},
    {key: 'swap_fee_val', label: '换电服务费', base: sliderP.swap_fee_val, min: 0.20, max: 0.60, step: 0.02, dir: 1, unit: '元/kWh', note: '', sliderId: 'swap_fee_slider', bizNote: ''},
    {key: 'station_invest', label: '单站投资', base: sliderP.station_invest, min: 185, max: 245, step: 1, dir: -1, unit: '万', note: '⚠ 投资额受建设方案影响', sliderId: 'station_invest_slider', bizNote: '不含电池投资'},
    {key: 'sc_fee_val', label: '超充电价', base: sliderP.sc_fee_val, min: 0.20, max: 0.40, step: 0.01, dir: 1, unit: '元/kWh', note: '', sliderId: 'sc_fee_slider', bizNote: ''},
    {key: 'sc_cars_per_day', label: '超充车辆/站/天', base: sliderP.sc_cars_per_day, min: 20, max: 80, step: 5, dir: 1, unit: '辆', note: '', sliderId: 'sc_cars_slider', bizNote: ''},
    {key: 'total_stations', label: '总站数', base: sliderP.total_stations, min: 30000, max: 100000, step: 5000, dir: 1, unit: '座', note: '', sliderId: 'total_stations', bizNote: '2028年前建设目标'}
  ];

  var results = [];

  for (var i = 0; i < tests.length; i++) {
    var t = tests[i];
    var irr_at_min = null, irr_at_max = null;
    var targetVal = null;

    for (var v = t.min; v <= t.max + 0.0001; v += t.step) {
      var tp = Object.assign({}, sliderP);
      tp[t.key] = v;
      var irr = calcIntegrated(tp).irr;

      if (Math.abs(v - t.min) < 0.001) irr_at_min = irr;
      if (v + t.step > t.max + 0.0001) irr_at_max = irr;

      // 找到达标值：按利好方向首次突破目标
      if (irr >= targetIRR && targetVal === null) {
        targetVal = v;
      }
    }

    var sensitivity = Math.abs((irr_at_max - irr_at_min) * 100);
    var canReach = targetVal !== null;

    // 计算最佳方向值：无法单独达标时，取最有利方向的极值作为组合调参推荐
    var bestVal = (t.dir > 0) ? t.max : t.min;

    results.push({
      key: t.key, label: t.label, base: t.base, unit: t.unit, note: t.note,
      min_val: t.min, max_val: t.max, dir: t.dir, step: t.step,
      sliderId: t.sliderId, bizNote: t.bizNote,
      irr_at_min: irr_at_min, irr_at_max: irr_at_max,
      sensitivity: sensitivity,
      canReach: canReach,
      targetVal: targetVal,
      bestVal: bestVal
    });
  }

  // 按敏感度排序
  results.sort(function(a, b) { return b.sensitivity - a.sensitivity; });

  // 保存全局状态供组合调参使用
  window._sensResults = results;
  window._sensBaseParams = sliderP;
  window._sensTargetIRR = targetIRR;
  window._sensBaseIRR = baseIRR;

  // 渲染
  var html = '<div style="margin-bottom:8px">当前一体化IRR: <b>' + (baseIRR * 100).toFixed(2) + '%</b>，目标: <b>' + (targetIRR * 100).toFixed(1) + '%</b>，差距: <b style="color:#e67e22">' + ((targetIRR - baseIRR) * 100).toFixed(2) + '个百分点</b></div>';

  // 达标路径（单参数）
  var reachable = results.filter(function(r) { return r.canReach; });
  var unreachable = results.filter(function(r) { return !r.canReach; });

  if (reachable.length > 0) {
    html += '<div style="margin-bottom:6px"><b>✓ 单参数达标路径</b>（仅调一项即可达标，点击「应用」一键套用至假设参数并重新计算）</div>';
    html += '<table style="width:100%;border-collapse:collapse;font-size:12px">';
    html += '<tr style="border-bottom:1px solid var(--border);color:var(--muted)"><td style="padding:4px 6px;width:28px">组合</td><td style="padding:4px 6px">参数</td><td style="padding:4px 6px">当前值</td><td style="padding:4px 6px">数值范围</td><td style="padding:4px 6px">达标值</td><td style="padding:4px 6px">调整幅度</td><td style="padding:4px 6px">敏感度</td><td style="padding:4px 6px">用户选择</td><td style="padding:4px 6px">操作</td></tr>';
    for (var j = 0; j < reachable.length; j++) {
      var r = reachable[j];
      var change = r.targetVal - r.base;
      var changeStr = (change > 0 ? '+' : '') + (typeof r.base === 'number' && r.base < 1 ? change.toFixed(2) : Math.round(change));
      var pct = Math.abs(change / r.base * 100).toFixed(1);
      var rangeStr = (typeof r.min_val === 'number' && r.min_val < 1 ? r.min_val.toFixed(2) : r.min_val) + ' ~ ' + (typeof r.max_val === 'number' && r.max_val < 1 ? r.max_val.toFixed(2) : r.max_val) + ' ' + r.unit;
      var targetValDisplay = (typeof r.targetVal === 'number' && r.targetVal < 1 ? r.targetVal.toFixed(2) : r.targetVal);
      var inputId = 'sens_input_' + r.key;
      var stepAttr = r.base < 1 ? '0.01' : '1';
      html += '<tr style="border-bottom:1px solid var(--border)">';
      html += '<td style="padding:4px 6px;text-align:center"><input type="checkbox" class="sens-combo-cb" data-key="' + r.key + '" data-slider-id="' + r.sliderId + '"></td>';
      html += '<td style="padding:4px 6px">' + r.label + (r.note ? '<br><span style="font-size:11px;color:#888">' + r.note + '</span>' : '') + '</td>';
      html += '<td style="padding:4px 6px">' + (typeof r.base === 'number' && r.base < 1 ? r.base.toFixed(2) : r.base) + ' ' + r.unit + '</td>';
      html += '<td style="padding:4px 6px;color:var(--muted);font-size:11px;white-space:nowrap">' + rangeStr + (r.bizNote ? '<br><span style="color:#999">' + r.bizNote + '</span>' : '') + '</td>';
      html += '<td style="padding:4px 6px;color:#27ae60;font-weight:bold">' + targetValDisplay + ' ' + r.unit + '</td>';
      html += '<td style="padding:4px 6px;color:' + (change > 0 ? '#e67e22' : '#3498db') + '">' + changeStr + ' (' + pct + '%)</td>';
      html += '<td style="padding:4px 6px">' + r.sensitivity.toFixed(2) + '%</td>';
      html += '<td style="padding:4px 6px"><input type="number" id="' + inputId + '" value="' + targetValDisplay + '" step="' + stepAttr + '" min="' + r.min_val + '" max="' + r.max_val + '" style="width:72px;padding:2px 4px;border:1px solid var(--border);border-radius:3px;font-size:12px;text-align:center" placeholder="自定义"></td>';
      html += '<td style="padding:4px 6px"><button onclick="applySensitivityParam(\'' + r.key + '\',\'' + r.sliderId + '\',' + r.min_val + ',' + r.max_val + ',' + r.targetVal + ')" style="padding:3px 10px;background:var(--accent);color:#fff;border:none;border-radius:3px;cursor:pointer;font-size:11px;white-space:nowrap">应用</button></td>';
      html += '</tr>';
    }
    html += '</table>';
    html += '<div style="margin-top:4px;font-size:11px;color:var(--muted)">提示：在「用户选择」列输入自定义数值后点击「应用」，留空则采用推荐达标值。输入越界将提示并阻止应用。勾选「组合」列可参与下方组合调参。</div>';
  }

  if (unreachable.length > 0) {
    html += '<div style="margin-top:10px;margin-bottom:6px"><b>✗ 单独调整无法达标</b>（需组合调参，勾选后到下方组合调参区域预览效果）</div>';
    html += '<table style="width:100%;border-collapse:collapse;font-size:12px">';
    html += '<tr style="border-bottom:1px solid var(--border);color:var(--muted)"><td style="padding:4px 6px;width:28px">组合</td><td style="padding:4px 6px">参数</td><td style="padding:4px 6px">当前值</td><td style="padding:4px 6px">数值范围</td><td style="padding:4px 6px">推荐方向值</td><td style="padding:4px 6px">敏感度</td><td style="padding:4px 6px">用户选择</td></tr>';
    for (var k = 0; k < unreachable.length; k++) {
      var u = unreachable[k];
      var uRangeStr = (typeof u.min_val === 'number' && u.min_val < 1 ? u.min_val.toFixed(2) : u.min_val) + ' ~ ' + (typeof u.max_val === 'number' && u.max_val < 1 ? u.max_val.toFixed(2) : u.max_val) + ' ' + u.unit;
      var uBestDisplay = (typeof u.bestVal === 'number' && u.bestVal < 1 ? u.bestVal.toFixed(2) : u.bestVal);
      var uInputId = 'sens_input_' + u.key;
      var uStepAttr = u.base < 1 ? '0.01' : '1';
      var uChange = u.bestVal - u.base;
      var uChangeStr = (uChange > 0 ? '+' : '') + (typeof u.base === 'number' && u.base < 1 ? uChange.toFixed(2) : Math.round(uChange));
      html += '<tr style="border-bottom:1px solid var(--border)">';
      html += '<td style="padding:4px 6px;text-align:center"><input type="checkbox" class="sens-combo-cb" data-key="' + u.key + '" data-slider-id="' + u.sliderId + '" checked></td>';
      html += '<td style="padding:4px 6px">' + u.label + (u.note ? '<br><span style="font-size:11px;color:#888">' + u.note + '</span>' : '') + '</td>';
      html += '<td style="padding:4px 6px">' + (typeof u.base === 'number' && u.base < 1 ? u.base.toFixed(2) : u.base) + ' ' + u.unit + '</td>';
      html += '<td style="padding:4px 6px;color:var(--muted);font-size:11px;white-space:nowrap">' + uRangeStr + (u.bizNote ? '<br><span style="color:#999">' + u.bizNote + '</span>' : '') + '</td>';
      html += '<td style="padding:4px 6px;color:#e67e22;font-weight:bold">' + uBestDisplay + ' ' + u.unit + ' <span style="font-size:11px;color:#999">(' + uChangeStr + ')</span></td>';
      html += '<td style="padding:4px 6px">' + u.sensitivity.toFixed(2) + '%</td>';
      html += '<td style="padding:4px 6px"><input type="number" id="' + uInputId + '" value="' + uBestDisplay + '" step="' + uStepAttr + '" min="' + u.min_val + '" max="' + u.max_val + '" style="width:72px;padding:2px 4px;border:1px solid var(--border);border-radius:3px;font-size:12px;text-align:center" placeholder="自定义"></td>';
      html += '</tr>';
    }
    html += '</table>';
    html += '<div style="margin-top:4px;font-size:11px;color:var(--muted)">「推荐方向值」= 该参数在最有利方向的极值。单独无法达标，但与其他参数组合可能达成目标。已默认勾选，可在下方组合调参中预览。</div>';
  }

  // 组合调参面板（交互式：用户可自由勾选上方表格中的参数进行组合）
  html += '<div id="combo_panel" style="margin-top:12px;padding:12px;background:linear-gradient(135deg,#f0f8ff,#f5f0ff);border:1px solid #b0c4de;border-radius:8px">';
  html += '<div style="display:flex;align-items:center;gap:12px;margin-bottom:8px;flex-wrap:wrap">';
  html += '<b>🔧 组合调参</b>';
  html += '<span style="font-size:12px;color:var(--muted)">勾选上方表格中的参数（可跨表组合），设定各参数值后点击预览或应用</span>';
  html += '<div style="margin-left:auto;display:flex;gap:8px">';
  html += '<button onclick="previewComboIRR()" style="padding:5px 14px;background:#6c5ce7;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px">预览组合IRR</button>';
  html += '<button onclick="applyComboParams()" style="padding:5px 14px;background:var(--green);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:12px">一键应用组合</button>';
  html += '</div>';
  html += '</div>';
  html += '<div id="combo_preview" style="font-size:13px;color:var(--muted);min-height:20px">点击「预览组合IRR」查看勾选参数的组合效果，点击「一键应用组合」将所有勾选参数同时套用至假设参数。</div>';
  html += '</div>';

  resultDiv.innerHTML = html;
}

/**
 * 应用敏感性分析参数：将用户选择（或推荐达标值）一键套用至假设参数滑块，并自动重新计算
 * @param {string} key - 参数 key（如 'daily_swaps'）
 * @param {string} sliderId - 对应滑块/select 的 DOM ID
 * @param {number} bizMin - 业务下限
 * @param {number} bizMax - 业务上限
 * @param {number} recommendedVal - 推荐达标值（用户未输入时采用此值）
 */
function applySensitivityParam(key, sliderId, bizMin, bizMax, recommendedVal) {
  var inputEl = document.getElementById('sens_input_' + key);
  if (!inputEl) return;

  var rawVal = inputEl.value.trim();
  var useVal;

  if (rawVal === '') {
    // 用户未手动设定，采用推荐达标值
    useVal = recommendedVal;
  } else {
    useVal = parseFloat(rawVal);
    if (isNaN(useVal)) {
      flashInputError(inputEl, '请输入有效数值');
      return;
    }
    // 越界校验
    if (useVal < bizMin || useVal > bizMax) {
      flashInputError(inputEl, '数值越界！有效范围为 ' + bizMin + ' ~ ' + bizMax);
      return;
    }
  }

  var el = document.getElementById(sliderId);
  if (!el) return;

  if (el.tagName === 'SELECT') {
    // select 类型：取最接近的 option
    var bestOpt = null, bestDiff = Infinity;
    for (var i = 0; i < el.options.length; i++) {
      var optVal = parseFloat(el.options[i].value);
      var diff = Math.abs(optVal - useVal);
      if (diff < bestDiff) { bestDiff = diff; bestOpt = el.options[i].value; }
    }
    if (bestDiff / useVal > 0.3) {
      flashInputError(inputEl, '最接近的可选值为 ' + bestOpt + '，偏差过大，请确认');
    }
    el.value = bestOpt;
  } else {
    // range 滑块：clamp 到 [min, max]
    var sliderMin = parseFloat(el.min);
    var sliderMax = parseFloat(el.max);
    useVal = Math.max(sliderMin, Math.min(sliderMax, useVal));
    el.value = useVal;
  }

  // 触发刷新
  console.log('[applySensitivityParam] key=' + key + ', sliderId=' + sliderId + ', useVal=' + useVal + ' → 触发刷新');
  el.dispatchEvent(new Event('input'));
  el.dispatchEvent(new Event('change'));
  if (typeof refreshAll === 'function') {
    refreshAll();
  }

  // 反馈提示
  showApplyToast('已应用「' + key + '」= ' + useVal + '，模型已重新计算');
}

/**
 * 预览组合调参效果：读取所有勾选参数的用户输入值，计算组合IRR
 * 不修改滑块，仅展示预览结果
 */
function previewComboIRR() {
  var results = window._sensResults;
  var baseParams = window._sensBaseParams;
  var targetIRR = window._sensTargetIRR;
  var baseIRR = window._sensBaseIRR;
  if (!results || !baseParams) return;

  var checkboxes = document.querySelectorAll('.sens-combo-cb');
  var checkedParams = [];
  var errors = [];

  for (var i = 0; i < checkboxes.length; i++) {
    if (!checkboxes[i].checked) continue;
    var key = checkboxes[i].dataset.key;
    var sliderId = checkboxes[i].dataset.sliderId;
    var r = null;
    for (var j = 0; j < results.length; j++) {
      if (results[j].key === key) { r = results[j]; break; }
    }
    if (!r) continue;

    var inputEl = document.getElementById('sens_input_' + key);
    if (!inputEl) continue;
    var rawVal = inputEl.value.trim();
    var useVal;
    if (rawVal === '') {
      useVal = r.canReach ? r.targetVal : r.bestVal;
    } else {
      useVal = parseFloat(rawVal);
      if (isNaN(useVal)) {
        errors.push(r.label + '：无效数值');
        continue;
      }
      if (useVal < r.min_val || useVal > r.max_val) {
        errors.push(r.label + '：越界（' + r.min_val + '~' + r.max_val + '）');
        continue;
      }
    }
    checkedParams.push({ key: key, label: r.label, val: useVal, unit: r.unit, sliderId: sliderId, base: r.base });
  }

  var previewDiv = document.getElementById('combo_preview');
  if (checkedParams.length === 0) {
    previewDiv.innerHTML = '<span style="color:#e74c3c">⚠ 请至少勾选一个参数</span>';
    return;
  }

  if (errors.length > 0) {
    previewDiv.innerHTML = '<span style="color:#e74c3c">⚠ 部分参数有误：<br>' + errors.join('<br>') + '</span>';
    return;
  }

  // 计算组合IRR
  var comboP = Object.assign({}, baseParams);
  for (var k = 0; k < checkedParams.length; k++) {
    comboP[checkedParams[k].key] = checkedParams[k].val;
  }
  var comboIRR = calcIntegrated(comboP).irr;

  // 渲染预览结果
  var html = '<div style="background:#fff;padding:10px;border-radius:6px;border:1px solid #e0e0e0">';
  html += '<div style="margin-bottom:8px"><b>组合参数（' + checkedParams.length + '项）：</b></div>';
  html += '<table style="width:100%;border-collapse:collapse;font-size:12px;margin-bottom:8px">';
  html += '<tr style="border-bottom:1px solid #eee;color:#888"><td style="padding:3px 6px">参数</td><td style="padding:3px 6px">原始值</td><td style="padding:3px 6px">组合值</td><td style="padding:3px 6px">变化</td></tr>';
  for (var m = 0; m < checkedParams.length; m++) {
    var cp = checkedParams[m];
    var chg = cp.val - cp.base;
    var chgStr = (chg > 0 ? '+' : '') + (typeof cp.base === 'number' && cp.base < 1 ? chg.toFixed(2) : Math.round(chg));
    var baseDisplay = (typeof cp.base === 'number' && cp.base < 1 ? cp.base.toFixed(2) : cp.base);
    var valDisplay = (typeof cp.val === 'number' && cp.val < 1 ? cp.val.toFixed(2) : cp.val);
    html += '<tr style="border-bottom:1px solid #f5f5f5">';
    html += '<td style="padding:3px 6px">' + cp.label + '</td>';
    html += '<td style="padding:3px 6px;color:#888">' + baseDisplay + ' ' + cp.unit + '</td>';
    html += '<td style="padding:3px 6px;font-weight:bold">' + valDisplay + ' ' + cp.unit + '</td>';
    html += '<td style="padding:3px 6px;color:' + (chg > 0 ? '#e67e22' : (chg < 0 ? '#3498db' : '#999')) + '">' + chgStr + '</td>';
    html += '</tr>';
  }
  html += '</table>';
  var irrPct = (comboIRR * 100).toFixed(2);
  var targetPct = (targetIRR * 100).toFixed(1);
  var basePct = (baseIRR * 100).toFixed(2);
  var reachColor = comboIRR >= targetIRR ? '#27ae60' : '#e74c3c';
  var reachIcon = comboIRR >= targetIRR ? '✓' : '✗';
  html += '<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">';
  html += '<span>原始IRR：<b>' + basePct + '%</b></span>';
  html += '<span>→</span>';
  html += '<span>组合IRR：<b style="color:' + reachColor + ';font-size:15px">' + irrPct + '%</b></span>';
  html += '<span>目标：<b>' + targetPct + '%</b></span>';
  html += '<span style="color:' + reachColor + ';font-weight:bold">' + reachIcon + (comboIRR >= targetIRR ? ' 已达标！' : ' 未达标，请调整参数') + '</span>';
  html += '</div>';
  html += '<div style="margin-top:6px;font-size:11px;color:#888">预览结果不修改实际参数。点击「一键应用组合」将上述参数全部套用至假设参数并重新计算。</div>';
  html += '</div>';
  previewDiv.innerHTML = html;
}

/**
 * 一键应用组合调参：将所有勾选参数的用户输入值同时套用至假设参数滑块，并重新计算
 */
function applyComboParams() {
  var results = window._sensResults;
  var baseParams = window._sensBaseParams;
  if (!results || !baseParams) return;

  var checkboxes = document.querySelectorAll('.sens-combo-cb');
  var toApply = [];
  var errors = [];

  for (var i = 0; i < checkboxes.length; i++) {
    if (!checkboxes[i].checked) continue;
    var key = checkboxes[i].dataset.key;
    var sliderId = checkboxes[i].dataset.sliderId;
    var r = null;
    for (var j = 0; j < results.length; j++) {
      if (results[j].key === key) { r = results[j]; break; }
    }
    if (!r) continue;

    var inputEl = document.getElementById('sens_input_' + key);
    if (!inputEl) continue;
    var rawVal = inputEl.value.trim();
    var useVal;
    if (rawVal === '') {
      useVal = r.canReach ? r.targetVal : r.bestVal;
    } else {
      useVal = parseFloat(rawVal);
      if (isNaN(useVal)) { errors.push(r.label + '：无效数值'); continue; }
      if (useVal < r.min_val || useVal > r.max_val) { errors.push(r.label + '：越界'); continue; }
    }
    toApply.push({ sliderId: sliderId, key: key, label: r.label, val: useVal });
  }

  if (toApply.length === 0) {
    showApplyToast('请至少勾选一个参数');
    return;
  }

  if (errors.length > 0) {
    var previewDiv = document.getElementById('combo_preview');
    if (previewDiv) {
      previewDiv.innerHTML = '<span style="color:#e74c3c">⚠ 部分参数有误，无法应用：<br>' + errors.join('<br>') + '</span>';
    }
    return;
  }

  // 依次设置所有滑块（不逐个触发刷新，最后统一刷新）
  for (var k = 0; k < toApply.length; k++) {
    var el = document.getElementById(toApply[k].sliderId);
    if (!el) continue;
    var applyVal = toApply[k].val;

    if (el.tagName === 'SELECT') {
      var bestOpt = null, bestDiff = Infinity;
      for (var s = 0; s < el.options.length; s++) {
        var optVal = parseFloat(el.options[s].value);
        var diff = Math.abs(optVal - applyVal);
        if (diff < bestDiff) { bestDiff = diff; bestOpt = el.options[s].value; }
      }
      el.value = bestOpt;
    } else {
      var sMin = parseFloat(el.min);
      var sMax = parseFloat(el.max);
      applyVal = Math.max(sMin, Math.min(sMax, applyVal));
      el.value = applyVal;
    }
  }

  // 统一触发一次刷新：dispatch 事件 + 显式调用 refreshAll 兜底
  console.log('[applyComboParams] 应用 ' + toApply.length + ' 个参数 → 触发刷新');
  if (toApply.length > 0) {
    var firstEl = document.getElementById(toApply[0].sliderId);
    if (firstEl) {
      firstEl.dispatchEvent(new Event('input'));
      firstEl.dispatchEvent(new Event('change'));
    }
  }
  if (typeof refreshAll === 'function') {
    refreshAll();
  }

  var labels = toApply.map(function(t) { return t.label; }).join('、');
  showApplyToast('已应用组合（' + toApply.length + '项：' + labels + '），模型已重新计算');
}

/**
 * 输入框错误闪烁提示
 */
function flashInputError(inputEl, msg) {
  inputEl.style.borderColor = '#e74c3c';
  inputEl.style.backgroundColor = '#fdf2f2';
  var hint = inputEl.parentNode.querySelector('.sens-err-hint');
  if (!hint) {
    hint = document.createElement('span');
    hint.className = 'sens-err-hint';
    hint.style.cssText = 'display:block;color:#e74c3c;font-size:11px;margin-top:2px';
    inputEl.parentNode.appendChild(hint);
  }
  hint.textContent = '⚠ ' + msg;
  setTimeout(function() {
    inputEl.style.borderColor = '';
    inputEl.style.backgroundColor = '';
    if (hint) hint.remove();
  }, 3000);
}

/**
 * 应用成功轻提示
 */
function showApplyToast(msg) {
  var toast = document.createElement('div');
  toast.textContent = '✓ ' + msg;
  toast.style.cssText = 'position:fixed;top:20px;right:20px;z-index:99999;background:#27ae60;color:#fff;padding:10px 20px;border-radius:6px;font-size:13px;box-shadow:0 4px 12px rgba(0,0,0,.2);opacity:0;transition:opacity .3s';
  document.body.appendChild(toast);
  requestAnimationFrame(function() { toast.style.opacity = '1'; });
  setTimeout(function() {
    toast.style.opacity = '0';
    setTimeout(function() { toast.remove(); }, 300);
  }, 2000);
}

/**
 * 自动优化内部结算参数（浏览器端运行）
 *
 * 说明：读取当前滑块参数 → 映射到 PARAM_SPEC 格式 → 调用 Engine.runOptimizer()
 *       → 在页面展示最优的周转电池租金和技术服务费
 * 关键：仅调整内部结算参数，不修改外部参数，一体化IRR保持不变
 */
function runAutoOptimizer() {
  var btn = document.getElementById('opt_btn');
  var resultDiv = document.getElementById('opt_result');

  // 禁用按钮，显示加载状态
  btn.disabled = true;
  btn.textContent = '⏳ 正在优化...';
  resultDiv.className = 'opt-result show';
  resultDiv.innerHTML = '<span class="warn">正在运行自动调参，请稍候...</span>';

  // 使用 setTimeout 让 UI 有时间更新
  setTimeout(function () {
    try {
      // 读取当前滑块参数
      var sliderP = getParams();

      // 保存优化前的主报告结果，用于对比
      // KPI dashboard 中：第1个card=一体化IRR, 第3个card=站IRR, 第4个card=银行IRR
      var kpiCards = document.querySelectorAll('#kpi_dashboard .kpi-card .value');
      var preOptKPI = {
        integratedIRR: kpiCards[0] ? parseFloat(kpiCards[0].textContent) || 0 : 0,
        stationIRR: kpiCards[2] ? parseFloat(kpiCards[2].textContent) || 0 : 0,
        bankIRR: kpiCards[3] ? parseFloat(kpiCards[3].textContent) || 0 : 0
      };
      var preOptRent = sliderP.spare_rent;
      var preOptTechFee = sliderP.tech_service;

      // 映射到 PARAM_SPEC 格式（params_spec.js 定义的 key）
      // 必须包含所有 slider 参数，确保 buildCalcParams 不使用不匹配的硬编码值
      // 关键：内部结算参数从 slider 读取当前值，而非 Engine 常量，确保优化起点与用户实际设置一致
      var baseParams = {
        dailySwaps: sliderP.daily_swaps,
        elecPrice: 0.60,
        chgFeePremium: 0.10,
        rentSqrm: sliderP.station_invest ? 15 : 15,
        famRatio: sliderP.fam_ratio,
        stationCount: sliderP.total_stations,
        batPerStation: sliderP.spare_bats || 14,
        discountRate: sliderP.discount_rate,
        hurdleRate: sliderP.discount_rate + 0.5,
        batCellCostY0: sliderP.cell_cost,
        cellCostDecline: 5.8,
        batDegradeFactor: Engine.BAT_DEGRADE_FACTOR || 0.63,
        batEssAvailability: Engine.BAT_ESS_AVAILABILITY || 0.55,
        internalBatRentMonthly: sliderP.spare_rent,
        internalTechFeeYearly: sliderP.tech_service,
        internalBatPerStation: sliderP.spare_bats || 14,
        // 以下参数从 slider 同步，确保与主模型一致
        swapFeeVal: sliderP.swap_fee_val,
        stationInvest: sliderP.station_invest,
        opMode: sliderP.op_mode,
        scCarsPerDay: sliderP.sc_cars_per_day,
        scKwhPerCar: sliderP.sc_kwh_per_car,
        scFeeVal: sliderP.sc_fee_val,
        bankTeamSize: sliderP.bank_team_size,
        packIntegrationCost: sliderP.pack_integration_cost,
        grossMargin: sliderP.gross_margin,
        batReplaceStrategy: sliderP.bat_replace_strategy
      };

      // 运行自动调参（仅优化内部结算，不修改外部参数）
      var result = Engine.runOptimizer({
        baseParams: baseParams,
        hurdleRate: sliderP.discount_rate,
        stationHurdle: sliderP.discount_rate,
        bankHurdle: sliderP.discount_rate,  // 银行IRR门槛与站IRR一致，确保双主体均盈利
        skipLayer1: true,  // 跳过第一层，不修改外部参数，一体化IRR保持不变
        verbose: false
      });

      // 格式化并显示结果
      var formatted = Engine.formatOptimizerResult(result);

      // 着色：IRR 值用绿色/红色标记
      formatted = formatted.replace(/(\d+\.\d+%)/g, '<span class="good">$1</span>');
      formatted = formatted.replace(/✓/g, '<span class="good">✓</span>');
      formatted = formatted.replace(/✗/g, '<span class="bad">✗</span>');
      formatted = formatted.replace(/⚠/g, '<span class="warn">⚠</span>');

      resultDiv.innerHTML = '<div class="title">🔧 自动调参结果</div>' + formatted.replace(/\n/g, '<br>');

      // 如果找到了最优结算参数，显示对比（不自动覆盖用户设定）
      if (result.settlement) {
        var postOptRent = result.settlement.internalBatRentMonthly;
        var postOptTechFee = result.settlement.internalTechFeeYearly;

        // 使用 baseParams（用户当前参数），与优化器第二层一致，确保一体化 IRR 不变
        var calcP = buildCalcParams(Object.assign({}, baseParams, {
          internalBatRentMonthly: postOptRent,
          internalTechFeeYearly: postOptTechFee
        }));
        var optIntegrated = Engine.calcIntegrated(calcP);
        var postOptStationIRR = (optIntegrated.st.irr * 100).toFixed(1);
        var postOptBankIRR = (optIntegrated.bb.irr * 100).toFixed(1);
        var postOptIntegratedIRR = (optIntegrated.irr * 100).toFixed(1);

        // 存储三档对比的全局状态（供 applyOptimizerParam 调用）
        window._optCompare = {
          discountRate: sliderP.discount_rate,
          baseParams: baseParams,
          before: { rent: preOptRent, techFee: preOptTechFee, integratedIRR: preOptKPI.integratedIRR, stationIRR: preOptKPI.stationIRR, bankIRR: preOptKPI.bankIRR },
          recommended: { rent: postOptRent, techFee: postOptTechFee, integratedIRR: parseFloat(postOptIntegratedIRR), stationIRR: parseFloat(postOptStationIRR), bankIRR: parseFloat(postOptBankIRR) }
        };

        var comparisonHtml = '<div style="margin-top:12px;padding:10px;background:#f0f4ff;border-radius:6px;font-size:13px;line-height:1.8">';
        comparisonHtml += '<b>📊 优化建议对比与快捷应用：</b><br>';
        comparisonHtml += '<span style="font-size:12px;color:#888">可直接采用推荐值，或在业务有效范围内输入自定义数值。两个参数都确认后，点击底部「一键应用」同时生效。</span><br>';

        // 业务范围：从 params_spec.js 动态读取，不随推荐值漂移
        var rentSpec = Engine.PARAM_SPEC.internalBatRentMonthly;
        var techSpec = Engine.PARAM_SPEC.internalTechFeeYearly;
        var RENT_MIN = rentSpec.min, RENT_MAX = rentSpec.max;
        var TECH_MIN = techSpec.min, TECH_MAX = techSpec.max;

        // 周转电池月租 — 可编辑
        comparisonHtml += '<div style="display:flex;align-items:center;gap:8px;margin:6px 0;flex-wrap:wrap">';
        comparisonHtml += '<span>周转电池月租：</span>';
        comparisonHtml += '<span style="color:#888">' + preOptRent + '</span> → ';
        comparisonHtml += '<b style="color:' + (postOptRent !== preOptRent ? '#e67e22' : '#666') + '">' + postOptRent + '</b> <span style="color:#888;font-size:12px">元/月/块</span>';
        comparisonHtml += '<input type="number" id="opt_input_rent" value="' + postOptRent + '" step="10" min="' + RENT_MIN + '" max="' + RENT_MAX + '" style="width:70px;padding:2px 4px;border:1px solid var(--border);border-radius:3px;font-size:12px;text-align:center">';
        comparisonHtml += '<span style="font-size:11px;color:#999">范围 ' + RENT_MIN + '~' + RENT_MAX + '</span>';
        comparisonHtml += '</div>';

        // 技术服务费 — 可编辑
        comparisonHtml += '<div style="display:flex;align-items:center;gap:8px;margin:6px 0;flex-wrap:wrap">';
        comparisonHtml += '<span>技术服务费：</span>';
        comparisonHtml += '<span style="color:#888">' + (preOptTechFee / 10000).toFixed(2) + '万</span> → ';
        comparisonHtml += '<b style="color:' + (postOptTechFee !== preOptTechFee ? '#e67e22' : '#666') + '">' + (postOptTechFee / 10000).toFixed(2) + '万</b> <span style="color:#888;font-size:12px">元/站/年</span>';
        comparisonHtml += '<input type="number" id="opt_input_tech" value="' + postOptTechFee + '" step="1000" min="' + TECH_MIN + '" max="' + TECH_MAX + '" style="width:80px;padding:2px 4px;border:1px solid var(--border);border-radius:3px;font-size:12px;text-align:center">';
        comparisonHtml += '<span style="font-size:11px;color:#999">范围 ' + (TECH_MIN / 10000).toFixed(0) + '~' + (TECH_MAX / 10000).toFixed(0) + '万</span>';
        comparisonHtml += '</div>';

        // 统一应用按钮
        comparisonHtml += '<div style="margin:10px 0 6px">';
        comparisonHtml += '<button onclick="applyOptimizerParamsBoth(' + preOptRent + ',' + postOptRent + ',' + RENT_MIN + ',' + RENT_MAX + ',' + preOptTechFee + ',' + postOptTechFee + ',' + TECH_MIN + ',' + TECH_MAX + ')" style="padding:6px 24px;background:var(--green);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;font-weight:600">一键应用以上参数</button>';
        comparisonHtml += '<span style="margin-left:10px;font-size:12px;color:#888">将两个参数同时套用至假设参数，自动刷新全部计算结果</span>';
        comparisonHtml += '</div>';

        comparisonHtml += '<hr style="border:none;border-top:1px dashed #ccc;margin:8px 0">';
        comparisonHtml += '<div style="font-size:12px;color:var(--muted);margin-bottom:4px">优化前 → 推荐值 → <span style="color:var(--green);font-weight:600">应用后</span></div>';
        comparisonHtml += '一体化IRR：' + preOptKPI.integratedIRR.toFixed(1) + '% → ' + postOptIntegratedIRR + '% → <span id="opt_after_intg" style="color:#999">待应用</span><br>';
        comparisonHtml += '站IRR：' + preOptKPI.stationIRR.toFixed(1) + '% → <b style="color:' + (parseFloat(postOptStationIRR) >= sliderP.discount_rate ? '#27ae60' : '#e74c3c') + '">' + postOptStationIRR + '%</b> → <span id="opt_after_st" style="color:#999">待应用</span><br>';
        comparisonHtml += '银行IRR：' + preOptKPI.bankIRR.toFixed(1) + '% → <b style="color:' + (parseFloat(postOptBankIRR) >= sliderP.discount_rate ? '#27ae60' : '#e74c3c') + '">' + postOptBankIRR + '%</b> → <span id="opt_after_bb" style="color:#999">待应用</span>';
        comparisonHtml += '</div>';

        var statusMsg = result.settlement.isCompromise
          ? '<br><span class="warn">⚠ 折中方案：银行IRR仍未达标（≥' + sliderP.discount_rate + '%），但已尽量改善。</span><br><span style="font-size:12px;color:#888">建议：使用上方「敏感性分析」继续提升一体化IRR，一体化IRR越高，银行达标空间越大。</span>'
          : '<br><span class="good">✓ 找到同时满足双门槛的结算方案！</span>';
        statusMsg += '<br><span style="font-size:12px;color:#888">调整上方两个输入框的数值后，点击「一键应用以上参数」同时生效，第三列显示应用后的实际IRR。</span>';
        resultDiv.innerHTML += statusMsg + comparisonHtml;
      } else {
        // 无合理方案：站IRR会跌破门槛
        var noChangeHtml = '<div style="margin-top:12px;padding:10px;background:#fff8f0;border-radius:6px;font-size:13px;line-height:1.8">';
        if (preOptKPI.integratedIRR < sliderP.discount_rate) {
          // 一体化IRR不达标 → 先解决一体化问题
          noChangeHtml += '<b>📊 结论：一体化IRR未达标，无法进行分拆优化</b><br>';
          noChangeHtml += '当前一体化IRR仅' + preOptKPI.integratedIRR.toFixed(1) + '%，低于门槛' + sliderP.discount_rate + '%。<br>';
          noChangeHtml += '请先使用上方<b>「敏感性分析」</b>，调整外部参数（如换电服务费、日均换电次数等）使一体化IRR达标，<br>';
          noChangeHtml += '然后再回来点击「自动优化内部结算」，让两个业务分部也同时达标。';
        } else {
          // 一体化达标但分拆后站会跌破门槛 → 一体化IRR不够高
          noChangeHtml += '<b>📊 结论：一体化IRR不够高，无法支撑双方都达标</b><br>';
          noChangeHtml += '当前一体化IRR为' + preOptKPI.integratedIRR.toFixed(1) + '%，虽然已达标，但利润空间不足以让换电站和电池银行同时达标。<br>';
          noChangeHtml += '调整内部结算参数会让换电站IRR跌破门槛' + sliderP.discount_rate + '%。<br>';
          noChangeHtml += '建议：继续使用<b>「敏感性分析」</b>提升一体化IRR（如提高换电服务费或日均换电次数），<br>';
          noChangeHtml += '一体化IRR越高，分拆后双方同时达标的空间越大。';
        }
        noChangeHtml += '</div>';
        resultDiv.innerHTML += noChangeHtml;
      }
    } catch (e) {
      resultDiv.innerHTML = '<span class="bad">优化出错：' + e.message + '</span>';
      console.error('Auto optimizer error:', e);
    }

    // 恢复按钮
    btn.disabled = false;
    btn.textContent = '优化';
  }, 100);
}

/**
 * 应用优化器推荐参数：将用户选择（或推荐值）套用至假设参数滑块，并自动刷新计算
 * @param {string} sliderId - 滑块 DOM ID
 * @param {number} currentVal - 当前值
 * @param {number} recommendedVal - 推荐值
 * @param {string} inputId - 用户输入框 DOM ID
 * @param {number} rangeMin - 允许范围下限（当前值与推荐值之间的较小值）
 * @param {number} rangeMax - 允许范围上限（当前值与推荐值之间的较大值）
 * @param {number} step - 步长（用于四舍五入）
 */
function applyOptimizerParam(sliderId, currentVal, recommendedVal, inputId, rangeMin, rangeMax, step) {
  var inputEl = document.getElementById(inputId);
  if (!inputEl) return;

  var rawVal = inputEl.value.trim();
  var useVal;

  if (rawVal === '') {
    useVal = recommendedVal;
  } else {
    useVal = parseFloat(rawVal);
    if (isNaN(useVal)) {
      flashInputError(inputEl, '请输入有效数值');
      return;
    }
    // 范围校验：允许介于当前值与推荐值之间
    if (useVal < rangeMin || useVal > rangeMax) {
      flashInputError(inputEl, '数值超出允许范围 ' + rangeMin + ' ~ ' + rangeMax);
      return;
    }
  }

  // 按步长对齐
  if (step && step > 0) {
    useVal = Math.round(useVal / step) * step;
  }

  var slider = document.getElementById(sliderId);
  if (!slider) return;

  // clamp 到滑块范围
  var sliderMin = parseFloat(slider.min);
  var sliderMax = parseFloat(slider.max);
  useVal = Math.max(sliderMin, Math.min(sliderMax, useVal));
  slider.value = useVal;

  // 触发刷新：先 dispatch 事件（触发 bindEvents 中注册的 refreshAll），
  // 再显式调用 refreshAll 作为兜底，确保 KPI 仪表盘等全局数据同步更新
  console.log('[applyOptimizerParam] sliderId=' + sliderId + ', useVal=' + useVal + ' → 触发刷新');
  slider.dispatchEvent(new Event('input'));
  slider.dispatchEvent(new Event('change'));
  if (typeof refreshAll === 'function') {
    refreshAll();
  }

  // 轻提示
  var label = sliderId === 'spare_rent_slider' ? '周转电池月租' : '技术服务费';
  showApplyToast('已应用「' + label + '」= ' + useVal + '，模型已重新计算');

  // 计算并展示三档对比
  showOpt3WayCompare();
}

/**
 * 一键应用两个内部结算参数（周转电池月租 + 技术服务费）
 * 用户在两个输入框中分别设定数值后，点击一次按钮同时套用至假设参数滑块
 * @param {number} preRent - 优化前周转电池月租
 * @param {number} recRent - 推荐周转电池月租
 * @param {number} rentMin - 月租允许下限
 * @param {number} rentMax - 月租允许上限
 * @param {number} preTech - 优化前技术服务费
 * @param {number} recTech - 推荐技术服务费
 * @param {number} techMin - 技术服务费允许下限
 * @param {number} techMax - 技术服务费允许上限
 */
function applyOptimizerParamsBoth(preRent, recRent, rentMin, rentMax, preTech, recTech, techMin, techMax) {
  var rentInput = document.getElementById('opt_input_rent');
  var techInput = document.getElementById('opt_input_tech');
  if (!rentInput || !techInput) return;

  // 解析周转电池月租
  var rentRaw = rentInput.value.trim();
  var useRent;
  if (rentRaw === '') {
    useRent = recRent;
  } else {
    useRent = parseFloat(rentRaw);
    if (isNaN(useRent)) {
      flashInputError(rentInput, '请输入有效数值');
      return;
    }
    if (useRent < rentMin || useRent > rentMax) {
      flashInputError(rentInput, '数值超出允许范围 ' + rentMin + ' ~ ' + rentMax);
      return;
    }
  }
  useRent = Math.round(useRent / 10) * 10; // 按步长10对齐

  // 解析技术服务费
  var techRaw = techInput.value.trim();
  var useTech;
  if (techRaw === '') {
    useTech = recTech;
  } else {
    useTech = parseFloat(techRaw);
    if (isNaN(useTech)) {
      flashInputError(techInput, '请输入有效数值');
      return;
    }
    if (useTech < techMin || useTech > techMax) {
      flashInputError(techInput, '数值超出允许范围 ' + techMin + ' ~ ' + techMax);
      return;
    }
  }
  useTech = Math.round(useTech / 1000) * 1000; // 按步长1000对齐

  // 同时设置两个滑块
  var rentSlider = document.getElementById('spare_rent_slider');
  var techSlider = document.getElementById('tech_service_slider');
  if (!rentSlider || !techSlider) return;

  var rentSMin = parseFloat(rentSlider.min), rentSMax = parseFloat(rentSlider.max);
  var techSMin = parseFloat(techSlider.min), techSMax = parseFloat(techSlider.max);
  useRent = Math.max(rentSMin, Math.min(rentSMax, useRent));
  useTech = Math.max(techSMin, Math.min(techSMax, useTech));

  rentSlider.value = useRent;
  techSlider.value = useTech;

  // 触发一次刷新（只需触发一个滑块的事件，refreshAll 会读取所有滑块值）
  console.log('[applyOptimizerParamsBoth] rent=' + useRent + ', tech=' + useTech + ' → 触发刷新');
  rentSlider.dispatchEvent(new Event('input'));
  rentSlider.dispatchEvent(new Event('change'));
  if (typeof refreshAll === 'function') {
    refreshAll();
  }

  // 轻提示
  showApplyToast('已应用：周转电池月租=' + useRent + '，技术服务费=' + (useTech / 10000).toFixed(1) + '万，模型已重新计算');

  // 计算并展示三档对比
  showOpt3WayCompare();
}

/**
 * 更新应用后的IRR：将三行IRR对比的第三段（"待应用"占位符）替换为实际计算值
 * 从滑块读取当前实际值（已被 applyOptimizerParamsBoth 设置并触发 refreshAll）
 */
function showOpt3WayCompare() {
  var state = window._optCompare;
  if (!state) return;

  // 三个 span 的 id
  var intgEl = document.getElementById('opt_after_intg');
  var stEl = document.getElementById('opt_after_st');
  var bbEl = document.getElementById('opt_after_bb');
  if (!intgEl || !stEl || !bbEl) return;

  // 从滑块读取当前实际值（已被应用并触发 refreshAll）
  var rentSlider = document.getElementById('spare_rent_slider');
  var techSlider = document.getElementById('tech_service_slider');
  if (!rentSlider || !techSlider) return;

  var userRent = parseInt(rentSlider.value);
  var userTech = parseInt(techSlider.value);

  // 计算用户自定义组合的IRR
  var calcP = buildCalcParams(Object.assign({}, state.baseParams, {
    internalBatRentMonthly: userRent,
    internalTechFeeYearly: userTech
  }));
  var userIntegrated = Engine.calcIntegrated(calcP);
  var hurdle = state.discountRate / 100;  // discountRate 存的是百分比(7.5)，IRR 是小数(0.075)

  // 格式化：达标绿色✓，未达标红色✗
  function fmt(irr) {
    var pct = (irr * 100).toFixed(1);
    var ok = irr >= hurdle;
    var color = ok ? '#27ae60' : '#e74c3c';
    return '<b style="color:' + color + '">' + pct + '%</b><span style="color:' + color + ';font-size:11px"> ' + (ok ? '✓' : '✗') + '</span>';
  }

  intgEl.innerHTML = fmt(userIntegrated.irr);
  intgEl.style.color = '';
  stEl.innerHTML = fmt(userIntegrated.st.irr);
  stEl.style.color = '';
  bbEl.innerHTML = fmt(userIntegrated.bb.irr);
  bbEl.style.color = '';
}

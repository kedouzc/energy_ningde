/**
 * ============================================================
 * engine/paramPanel.js — 动态参数面板生成器
 * ============================================================
 * 从 PARAM_PANEL_SPEC 元数据自动生成参数面板 HTML，
 * 替代 model.html 中硬编码的 buildParamPanel() 模板。
 *
 * 设计原则：
 *   1. 新增参数只需在 PARAM_PANEL_SPEC 中添加一条记录
 *   2. 自动生成 slider / select / 预设标签
 *   3. model.html 只需调用 Engine.buildParamPanel() 获取 HTML
 * ============================================================
 */
var Engine = window.Engine || {};

// ============================================================
// 参数面板元数据定义
// 每个参数包含：
//   id        - DOM 元素 ID（slider/select）
//   label     - 显示标签（支持 HTML）
//   type      - 'range' | 'select'
//   min       - range 最小值
//   max       - range 最大值
//   step      - range 步长
//   default   - 默认值
//   unit      - 单位
//   desc      - 描述（灰色小字）
//   presets   - 预设标签 [{ label, val }]
//   options   - select 选项 [{ val, label }]
//   section   - 所属分组
//   valId     - 显示当前值的 <b> 元素 ID
//   valFormat - 值格式化函数名
// ============================================================

Engine.PARAM_PANEL_SPEC = {
  // ==========================================================
  // Section ① 业务成立核心参数
  // ==========================================================
  sections: [
    {
      id: 'core',
      title: '① 业务成立核心参数 — 一体化运营测算',
      style: 'grid-column:1/-1',
      params: [
        {
          id: 'swap_fee_slider',
          label: '换电服务费',
          type: 'range',
          min: 0.20, max: 0.60, step: 0.01, default: 0.40,
          unit: '元/度',
          desc: '（悲观0.2反映重庆2025年促销；乐观0.6对齐蔚能）',
          valId: 'val_swap_fee',
          valFormat: 'toFixed2',
          presets: [
            { label: '悲观0.20', val: '0.20' },
            { label: '中性0.40', val: '0.40' },
            { label: '乐观0.60', val: '0.60' }
          ]
        },
        {
          id: 'daily_swaps_slider',
          label: '日均换电次数',
          type: 'range',
          min: 60, max: 200, step: 1, default: 115,
          unit: '次/天',
          desc: '（核心求解变量，受运营模式约束，最小值60）',
          valId: 'val_daily_swaps',
          valFormat: 'int',
          presets: [
            { label: '悲观80', val: '80' },
            { label: '中性115', val: '115' },
            { label: '乐观140', val: '140' }
          ],
          extra: '<span id="btn_breakeven" style="color:var(--amber);cursor:pointer;font-weight:600">盈亏平衡<b id="lbl_breakeven"></b></span><span id="btn_fullload" style="color:var(--green);cursor:pointer;font-weight:600">满负荷<b id="lbl_fullload"></b></span>'
        },
        {
          id: 'op_mode',
          label: '运营模式',
          type: 'select',
          default: '16h',
          valId: 'val_op_mode',
          valFormat: 'opModeLabel',
          options: [
            { val: '16h', label: '16h双班倒 · 满负荷' + (Engine.MAX_SWAPS_16H || 125) + '次/天 · 人工' + ((Engine.STAFF_SWAP_COUNT || 3) * (Engine.STAFF_SWAP_MONTHLY || 8000) * (Engine.STAFF_SWAP_SOCIAL_MULTIPLIER || 1.4) * 12 / 10000).toFixed(1) + '万' },
            { val: '24h', label: '24h全自动无人值守 · 满负荷140次/天 · 人工0万' }
          ],
          desc: '（24h需全自动无人值守技术成熟）'
        },
        {
          id: 'fam_ratio_slider',
          label: '换电用户结构',
          type: 'range',
          min: 50, max: 95, step: 5, default: 90,
          unit: '%',
          valId: 'val_rent_label',
          valFormat: 'famRatioLabel',
          presets: [
            { label: '悲观50%', val: '50' },
            { label: '中性90%', val: '90' },
            { label: '乐观95%', val: '95' }
          ]
        },
        {
          id: 'station_invest_slider',
          label: '单站投资额',
          type: 'range',
          min: 185, max: 245, step: 1, default: 215,
          unit: '万',
          desc: '（不含电池）',
          valId: 'val_station_invest',
          valFormat: 'int',
          presets: [
            { label: '乐观185', val: '185' },
            { label: '中性215', val: '215' },
            { label: '悲观245', val: '245' }
          ]
        },
        {
          id: 'bat_replace_strategy',
          label: '电池置换策略',
          type: 'select',
          default: 'A',
          valId: 'val_bat_replace',
          valFormat: 'batReplaceLabel',
          options: [
            { val: 'A', label: 'A版 · 电池寿命15年（无置换）' },
            { val: 'B', label: 'B版 · 第8年置换（考虑新购电池成本和旧电池回收价值）' }
          ],
          desc: '（A版无置换B版第8年置换净回收172万）'
        },
        {
          id: 'years_slider',
          label: '运营测算年限',
          type: 'range',
          min: 15, max: 20, step: 1, default: 15,
          unit: '年',
          desc: '（换电站折旧10年，电池银行折旧15年）',
          valId: 'val_years',
          valFormat: 'int',
          presets: [
            { label: '15年', val: '15' },
            { label: '20年', val: '20' }
          ]
        },
        {
          id: 'discount_rate_slider',
          label: '折现率(WACC)',
          type: 'range',
          min: 5.0, max: 12.0, step: 0.5, default: 7.5,
          unit: '%',
          desc: '（NPV计算用，IRR≥WACC方可投资）',
          valId: 'val_discount_rate',
          valFormat: 'toFixed1',
          presets: [
            { label: '乐观5%', val: '5.0' },
            { label: '中性7.5%', val: '7.5' },
            { label: '悲观10%', val: '10.0' }
          ]
        },
        {
          id: 'spare_bats',
          label: '周转电池数量',
          type: 'select',
          default: '14',
          valId: 'val_spare',
          valFormat: 'int',
          options: [
            { val: '14', label: '14块（标准站·单工位）' },
            { val: '30', label: '30块（大型站·双工位/高周转）' }
          ],
          unit: '块',
          desc: '（对齐巧克力换电站机械设置）'
        }
      ]
    },

    // ==========================================================
    // Section ② 换电站/电池银行关键参数 — 分拆结算
    // ==========================================================
    {
      id: 'settlement',
      title: '② 换电站/电池银行关键参数 — 分拆结算',
      style: 'grid-column:1/-1;border-top:2px solid var(--accent);padding-top:14px;margin-top:6px',
      params: [
        {
          id: 'spare_rent_slider',
          label: '周转电池月租',
          type: 'range',
          min: 200, max: 360, step: 10, default: 240,
          unit: '元/块/月',
          valId: 'val_spare_rent',
          valFormat: 'int',
          presets: [
            { label: '低价200', val: '200' },
            { label: '中性240', val: '240' },
            { label: '高价360', val: '360' }
          ]
        },
        {
          id: 'tech_service_slider',
          label: '技术服务费',
          type: 'range',
          min: 20000, max: 100000, step: 1000, default: 35000,
          unit: '元/站/年',
          valId: 'val_tech_service',
          valFormat: 'int',
          presets: [
            { label: '低价2万', val: '20000' },
            { label: '中性3.5万', val: '35000' },
            { label: '高价10万', val: '100000' }
          ]
        },
        {
          id: 'bank_team_size_slider',
          label: '电池银行团队规模',
          type: 'range',
          min: 800, max: 3000, step: 5, default: 1365,
          valId: 'val_bank_team_size',
          valFormat: 'int',
          presets: [
            { label: '精简1000', val: '1000' },
            { label: '中性1365', val: '1365' },
            { label: '保守2000', val: '2000' }
          ]
        }
      ]
    },

    // ==========================================================
    // Section ③ 超充业务假设参数
    // ==========================================================
    {
      id: 'supercharge',
      title: '③ 超充业务假设参数（站点已含2根超充桩，投资已含桩成本）',
      style: 'grid-column:1/-1;border-top:2px solid var(--green);padding-top:14px;margin-top:6px',
      params: [
        {
          id: 'sc_cars_slider',
          label: '日均充车辆数',
          type: 'range',
          min: 20, max: 80, step: 5, default: 40,
          unit: '辆/天',
          valId: 'val_sc_cars',
          valFormat: 'int',
          presets: [
            { label: '悲观20', val: '20' },
            { label: '中性40', val: '40' },
            { label: '乐观60', val: '60' }
          ]
        },
        {
          id: 'sc_kwh_slider',
          label: '单车充电量',
          type: 'range',
          min: 20, max: 70, step: 5, default: 40,
          unit: '度/次',
          valId: 'val_sc_kwh',
          valFormat: 'int',
          presets: [
            { label: '悲观20', val: '20' },
            { label: '中性40', val: '40' },
            { label: '乐观50', val: '50' }
          ]
        },
        {
          id: 'sc_fee_slider',
          label: '超充服务费',
          type: 'range',
          min: 0.20, max: 0.40, step: 0.01, default: 0.30,
          unit: '元/度',
          valId: 'val_sc_fee',
          valFormat: 'toFixed2',
          presets: [
            { label: '悲观0.20', val: '0.20' },
            { label: '中性0.30', val: '0.30' },
            { label: '乐观0.40', val: '0.40' }
          ]
        }
      ]
    },

    // ==========================================================
    // Section ④ 换电站建设进度与网络规模
    // ==========================================================
    {
      id: 'scale',
      title: '④ 换电站建设进度与网络规模（2028年前）',
      style: 'grid-column:1/-1;border-top:2px solid var(--amber);padding-top:14px;margin-top:6px',
      params: [
        {
          id: 'total_stations',
          label: '换电站总数（2028年前）',
          type: 'select',
          default: '50000',
          valId: 'val_total_stations',
          valFormat: 'stationCount',
          unit: '座',
          options: [
            { val: '30000', label: '悲观 · 3万座' },
            { val: '50000', label: '中性 · 5万座' },
            { val: '100000', label: '乐观 · 10万座（2026年科技日宣布目标）' }
          ]
        },
        {
          id: '_self_station_info',
          label: 'CATL自建站 <b>4000</b> 座：',
          type: 'info',
          desc: '2025年520→2026年1200→2027年2500→2028年4000逐步到位'
        }
      ]
    },

    // ==========================================================
    // Section ⑤ 估值参数
    // ==========================================================
    {
      id: 'valuation_params',
      title: '⑤ 估值参数',
      style: 'grid-column:1/-1;border-top:2px solid var(--accent);padding-top:14px;margin-top:6px',
      params: [
        {
          id: 'mfg_pe_slider',
          label: '制造业务估值倍数：PE',
          type: 'range',
          min: 17, max: 25, step: 1, default: 21,
          valId: 'val_mfg_pe',
          valFormat: 'int',
          desc: '（远期锚定台积电17-22×）',
          presets: [
            { label: '悲观17×', val: '17' },
            { label: '中性21×', val: '21' },
            { label: '乐观25×', val: '25' }
          ]
        },
        {
          id: 'op_pe_slider',
          label: '换电业务估值倍数：PE',
          type: 'range',
          min: 20, max: 45, step: 5, default: 30,
          valId: 'val_op_pe',
          valFormat: 'int',
          desc: '（远期高于金融资管30×）',
          presets: [
            { label: '悲观25×', val: '25' },
            { label: '中性30×', val: '30' },
            { label: '乐观35×', val: '35' }
          ]
        },
        {
          id: '_mfg_section_label',
          label: '制造利润里程碑预测（亿元，建设期920亿为一致预期，不可调）',
          type: 'info',
          style: 'grid-column:1/-1;border-top:1px solid var(--border);padding-top:10px;margin-top:2px',
          labelStyle: 'font-weight:600;color:var(--accent)'
        },
        {
          id: 'mfg_build_profit_slider',
          label: '建成期净利润',
          type: 'range',
          min: 700, max: 1300, step: 10, default: 990,
          unit: '亿',
          desc: '（利用率爬坡至~40%）',
          valId: 'val_mfg_build_profit',
          valFormat: 'int',
          presets: [
            { label: '悲观850', val: '850' },
            { label: '中性990', val: '990' },
            { label: '乐观1200', val: '1200' }
          ]
        },
        {
          id: 'mfg_full_profit_slider',
          label: '达产期净利润',
          type: 'range',
          min: 800, max: 1500, step: 10, default: 1190,
          unit: '亿',
          desc: '（满载运营）',
          valId: 'val_mfg_full_profit',
          valFormat: 'int',
          presets: [
            { label: '悲观1000', val: '1000' },
            { label: '中性1190', val: '1190' },
            { label: '乐观1400', val: '1400' }
          ]
        },
        {
          id: 'mfg_mature_profit_slider',
          label: '成熟期净利润',
          type: 'range',
          min: 1000, max: 2000, step: 10, default: 1630,
          unit: '亿',
          desc: '（行业稳态）',
          valId: 'val_mfg_mature_profit',
          valFormat: 'int',
          presets: [
            { label: '悲观1400', val: '1400' },
            { label: '中性1630', val: '1630' },
            { label: '乐观1900', val: '1900' }
          ]
        }
      ]
    },

    // ==========================================================
    // Section ⑥ 电池价格基准参数
    // ==========================================================
    {
      id: 'battery_price',
      title: '⑥ 电池价格基准参数（元/Wh口径）',
      style: 'grid-column:1/-1;border-top:2px solid var(--accent);padding-top:14px;margin-top:6px',
      params: [
        {
          id: 'cell_cost_slider',
          label: '动力电芯成本',
          type: 'range',
          min: 0.30, max: 0.45, step: 0.01, default: 0.380,
          unit: '元/Wh',
          desc: '（TrendForce 2026-05）',
          valId: 'val_cell_cost',
          valFormat: 'toFixed3',
          presets: [
            { label: '悲观0.42', val: '0.42' },
            { label: '中性0.38', val: '0.380' },
            { label: '乐观0.35', val: '0.35' }
          ]
        },
        {
          id: 'pack_integration_cost_slider',
          label: 'Pack集成成本',
          type: 'range',
          min: 0.08, max: 0.14, step: 0.01, default: 0.100,
          unit: '元/Wh',
          desc: '（含换电专用附加）',
          valId: 'val_pack_integration_cost',
          valFormat: 'toFixed3',
          presets: [
            { label: '悲观0.12', val: '0.12' },
            { label: '中性0.10', val: '0.100' },
            { label: '乐观0.08', val: '0.08' }
          ]
        },
        {
          id: 'gross_margin_slider',
          label: '动力Pack毛利率',
          type: 'range',
          min: 15, max: 28, step: 1, default: 22,
          unit: '%',
          desc: '（CATL 2025年报 23.84%）',
          valId: 'val_gross_margin',
          valFormat: 'toFixed1',
          presets: [
            { label: '悲观18', val: '18' },
            { label: '中性22', val: '22' },
            { label: '乐观25', val: '25' }
          ]
        },
        {
          id: 'period_expense_rate_slider',
          label: '期间费用率',
          type: 'range',
          min: 5, max: 12, step: 1, default: 8,
          unit: '%',
          desc: '（销售+管理+研发）',
          valId: 'val_period_expense_rate',
          valFormat: 'toFixed1',
          presets: [
            { label: '悲观10', val: '10' },
            { label: '中性8', val: '8' },
            { label: '乐观6', val: '6' }
          ]
        }
      ]
    }
  ],

  // ==========================================================
  // 值格式化函数映射
  // ==========================================================
  formatFns: {
    'toFixed2': function(v) { return parseFloat(v).toFixed(2); },
    'toFixed1': function(v) { return parseFloat(v).toFixed(1); },
    'toFixed3': function(v) { return parseFloat(v).toFixed(3); },
    'int': function(v) { return parseInt(v); },
    'opModeLabel': function(v) { return v === '24h' ? '24h全自动无人值守' : '16h双班倒'; },
    'batReplaceLabel': function(v) { return v === 'B' ? 'B版（第8年置换）' : 'A版（15年无置换）'; },
    'famRatioLabel': function(v) {
      v = parseInt(v);
      return '家庭包占比' + v + '% · 加权—元/月';
    },
    'stationCount': function(v) {
      v = parseInt(v);
      return v >= 10000 ? (v / 10000).toFixed(1) + '万' : v;
    }
  }
};

/**
 * 构建参数面板 HTML
 * @returns {string} 完整的参数面板 HTML
 */
Engine.buildParamPanel = function() {
  var spec = Engine.PARAM_PANEL_SPEC;
  var html = '';

  html += '<h2 class="collapsible-header collapsed" onclick="toggleSection(this)">';
  html += '<span class="arrow">▼</span> ⚙️ 假设参数：默认中性设置';
  html += '<span style="float:right;font-size:12px;font-weight:400">';
  html += '<button onclick="event.stopPropagation();applyPreset(\'pessimistic\')" style="padding:4px 12px;border:1px solid var(--red);color:var(--red);background:transparent;border-radius:4px;cursor:pointer;font-size:12px;margin-left:6px">一键悲观</button>';
  html += '<button onclick="event.stopPropagation();applyPreset(\'neutral\')" style="padding:4px 12px;border:1px solid var(--accent);color:var(--accent);background:transparent;border-radius:4px;cursor:pointer;font-size:12px;margin-left:6px">一键中性</button>';
  html += '<button onclick="event.stopPropagation();applyPreset(\'optimistic\')" style="padding:4px 12px;border:1px solid var(--green);color:var(--green);background:transparent;border-radius:4px;cursor:pointer;font-size:12px;margin-left:6px">一键乐观</button>';
  html += '</span></h2>';
  html += '<div class="collapsible-body collapsed">';
  html += '<p class="note" style="margin-bottom:8px">详细设置方式：点击选项卡、拖动滑块</p>';
  html += '<div class="param-grid">';

  // 遍历所有 section
  for (var si = 0; si < spec.sections.length; si++) {
    var section = spec.sections[si];

    // Section 标题
    html += '<div class="param-item" style="' + section.style + '">';
    html += '<h3>' + section.title + '</h3>';
    html += '</div>';

    // 遍历 section 内的参数
    for (var pi = 0; pi < section.params.length; pi++) {
      var param = section.params[pi];
      html += buildParamItem(param);
    }
  }

  html += '</div></div>';
  return html;
};

/**
 * 构建单个参数项的 HTML
 * @param {object} param - 参数定义
 * @returns {string} HTML 字符串
 */
function buildParamItem(param) {
  var html = '';

  // info 类型：纯信息展示
  if (param.type === 'info') {
    html += '<div class="param-item" style="' + (param.style || '') + '">';
    html += '<label style="' + (param.labelStyle || '') + '">' + param.label;
    if (param.desc) html += '<br> <span style="color:var(--muted);font-size:14px">' + param.desc + '</span>';
    html += '</label>';
    html += '</div>';
    return html;
  }

  // range 和 select 类型
  html += '<div class="param-item">';

  // Label
  var formatFn = Engine.PARAM_PANEL_SPEC.formatFns[param.valFormat];
  var defaultDisplay = formatFn ? formatFn(param.default) : param.default;
  html += '<label>' + param.label + ' <b id="' + param.valId + '">' + defaultDisplay + '</b>';
  if (param.unit) html += ' ' + param.unit;
  if (param.desc) html += ' <span style="color:var(--muted);font-size:11px">' + param.desc + '</span>';
  html += '</label>';

  if (param.type === 'range') {
    // Slider
    html += '<input type="range" id="' + param.id + '" min="' + param.min + '" max="' + param.max + '" step="' + param.step + '" value="' + param.default + '">';

    // Preset labels
    if (param.presets && param.presets.length > 0) {
      html += '<div class="preset-labels">';
      for (var i = 0; i < param.presets.length; i++) {
        var preset = param.presets[i];
        var isActive = String(preset.val) === String(param.default);
        html += '<span data-slider="' + param.id + '" data-val="' + preset.val + '"' + (isActive ? ' class="active"' : '') + '>' + preset.label + '</span>';
      }
      html += '</div>';
    }

    // Extra content (e.g. breakeven/fullload buttons)
    if (param.extra) {
      html += param.extra;
    }
  } else if (param.type === 'select') {
    html += '<select id="' + param.id + '">';
    for (var j = 0; j < param.options.length; j++) {
      var opt = param.options[j];
      var selected = String(opt.val) === String(param.default) ? ' selected' : '';
      html += '<option value="' + opt.val + '"' + selected + '>' + opt.label + '</option>';
    }
    html += '</select>';
  }

  html += '</div>';
  return html;
}
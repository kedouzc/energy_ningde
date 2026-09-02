/**
 * engine/presets.js
 * 预设情景参数 —— 悲观/中性/乐观三组参数值
 * 所有预设值均受 params_spec.js 中定义的 min/max 约束
 * 若预设值超出范围，applyPreset 会自动 clamp 到边界
 */

var Engine = Engine || {};

// ============================================================
// 预设情景参数
// ============================================================

Engine.PRESETS = {
  /** 悲观情景 */
  pessimistic: {
    swap_fee_slider: 0.20,
    daily_swaps_slider: 80,
    fam_ratio_slider: 50,
    station_invest_slider: 245,
    spare_rent_slider: 200,
    bank_team_size_slider: 2000,
    sc_cars_slider: 20,
    sc_kwh_slider: 20,
    sc_fee_slider: 0.20,
    op_mode: '16h',
    bat_replace_strategy: 'A',
    spare_bats: '14',
    years_slider: 15,
    total_stations: '30000',
    op_pe_slider: 25,
    mfg_pe_slider: 17,
    mfg_build_profit_slider: 850,
    mfg_full_profit_slider: 1000,
    mfg_mature_profit_slider: 1400,
    cell_cost_slider: 0.42,
    pack_integration_cost_slider: 0.12,
    gross_margin_slider: 18,
    period_expense_rate_slider: 10,
    discount_rate_slider: 10.0
  },

  /** 中性情景（基准） */
  neutral: {
    swap_fee_slider: 0.40,
    daily_swaps_slider: 115,
    fam_ratio_slider: 90,
    station_invest_slider: 215,
    spare_rent_slider: 240,
    bank_team_size_slider: 1365,
    sc_cars_slider: 40,
    sc_kwh_slider: 40,
    sc_fee_slider: 0.30,
    op_mode: '16h',
    bat_replace_strategy: 'A',
    spare_bats: '14',
    years_slider: 15,
    total_stations: '50000',
    op_pe_slider: 30,
    mfg_pe_slider: 21,
    mfg_build_profit_slider: 990,
    mfg_full_profit_slider: 1190,
    mfg_mature_profit_slider: 1630,
    cell_cost_slider: 0.380,
    pack_integration_cost_slider: 0.100,
    gross_margin_slider: 22,
    period_expense_rate_slider: 8,
    discount_rate_slider: 7.5
  },

  /** 乐观情景 */
  optimistic: {
    swap_fee_slider: 0.60,
    daily_swaps_slider: 120,
    fam_ratio_slider: 95,
    station_invest_slider: 185,
    spare_rent_slider: 300,
    bank_team_size_slider: 1000,
    sc_cars_slider: 60,
    sc_kwh_slider: 50,
    sc_fee_slider: 0.4,
    op_mode: '16h',
    bat_replace_strategy: 'A',
    spare_bats: '14',
    years_slider: 15,
    total_stations: '100000',
    op_pe_slider: 40,
    mfg_pe_slider: 25,
    mfg_build_profit_slider: 1200,
    mfg_full_profit_slider: 1400,
    mfg_mature_profit_slider: 1900,
    cell_cost_slider: 0.35,
    pack_integration_cost_slider: 0.08,
    gross_margin_slider: 25,
    period_expense_rate_slider: 6,
    discount_rate_slider: 5.0
  }
};

/**
 * 应用预设情景，并校验参数值是否在 params_spec 定义的范围内
 * 若超出范围，自动 clamp 到边界
 * @param {string} presetName - 预设名称 (pessimistic/neutral/optimistic)
 * @returns {object|null} 校验后的参数值，若预设不存在则返回 null
 */
Engine.applyPreset = function(presetName) {
  var values = Engine.PRESETS[presetName];
  if (!values) return null;

  // 对每个参数值进行范围校验
  var checked = {};
  for (var key in values) {
    var val = values[key];
    var spec = Engine.PARAM_SPEC && Engine.PARAM_SPEC[key];
    if (spec) {
      // 数值型参数：校验 min/max
      if (typeof val === 'number') {
        if (typeof spec.min === 'number' && val < spec.min) val = spec.min;
        if (typeof spec.max === 'number' && val > spec.max) val = spec.max;
      }
    }
    checked[key] = val;
  }
  return checked;
};

/**
 * 获取指定预设的参数值（未经校验的原始值）
 * @param {string} presetName - 预设名称
 * @returns {object|null} 原始参数值
 */
Engine.getPreset = function(presetName) {
  return Engine.PRESETS[presetName] || null;
};
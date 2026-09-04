/**
 * ============================================================
 * engine/rental.js — 电池租赁权重与加权价格计算
 * ============================================================
 *
 * 核心逻辑：
 *   电池银行向用户收取月租，价格取决于：
 *   - 用户类型（营运/私家）
 *   - 电池容量（20kWh/25kWh）
 *   - 套餐（家庭包/不限次）
 *
 * 本文件解决两个问题：
 *   1. calcRentalWeights()  — 给定家庭包占比，计算各套餐的选择权重
 *   2. calcWeightedRent()   — 给定用户数量，计算加权平均月租
 *
 * 加载顺序：在 constants.js 之后
 * ============================================================
 */
var Engine = window.Engine || {};

/**
 * 计算租赁套餐的选择权重分布
 *
 * 根据家庭包占比（famRatio），通过线性插值确定三类锚点的权重：
 *   - 50% 家庭包：偏基础配置，多数选25kWh方案
 *   - 90% 家庭包：偏家庭配置，多数选家庭包
 *   - 95% 家庭包：极端家庭配置，多数选20kWh方案
 *
 * 权重含义：
 *   priv_p20 / priv_p25  — 私家车选20kWh/25kWh的比例
 *   fam20 / fam25         — 私家车内选家庭包的比例
 *   c_p25c / c_p20c       — 营运车选25kWh/20kWh的比例
 *
 * 示例：
 *   famRatio=0.9 → 90%家庭包场景 → 私家车50%选20kWh, 90%选家庭包
 *
 * @param {number} famRatio - 家庭包占比（0.5~0.95）
 * @returns {{priv: {p20,p25,fam20,fam25}, comm: {p25c,p20c,fam25c}, label: string}}
 *
 * 对应MD文档：宁德时代_超换一体站_财务模型_修正版.md # 3.3 租赁定价模型
 */
Engine.calcRentalWeights = function (famRatio) {
  var r = Math.max(0.5, Math.min(0.95, famRatio));

  // 三个锚点（离散状态下的权重分布）
  var anchors = {
    0.5:  { priv_p20: 0.5, priv_p25: 0.5, fam20: 0.5, fam25: 0.5, c_p25c: 0.8, c_p20c: 0.2 },
    0.9:  { priv_p20: 0.5, priv_p25: 0.5, fam20: 0.9, fam25: 0.9, c_p25c: 0.7, c_p20c: 0.3 },
    0.95: { priv_p20: 0.7, priv_p25: 0.3, fam20: 0.95, fam25: 0.95, c_p25c: 0.6, c_p20c: 0.4 },
  };

  // 确定当前famRatio落在哪个区间，线性插值
  var lo = 0.5, hi = 0.9;
  if (r > 0.9) { lo = 0.9; hi = 0.95; }
  var t = (r - lo) / (hi - lo);
  var loA = anchors[lo], hiA = anchors[hi];
  function lerp(a, b) { return a + (b - a) * t; }

  return {
    priv: {
      p20: lerp(loA.priv_p20, hiA.priv_p20),
      p25: lerp(loA.priv_p25, hiA.priv_p25),
      fam20: lerp(loA.fam20, hiA.fam20),
      fam25: lerp(loA.fam25, hiA.fam25),
    },
    comm: {
      p25c: lerp(loA.c_p25c, hiA.c_p25c),
      p20c: lerp(loA.c_p20c, hiA.c_p20c),
      fam25c: 0.0,  // 营运车目前无家庭包
    },
    label: '家庭包占比' + (r * 100).toFixed(0) + '%'
  };
};

/**
 * 计算加权平均电池月租
 *
 * 计算公式：
 *   - 私家车月租 = p20×(20kWh方案加权价) + p25×(25kWh方案加权价)
 *   - 营运车月租 = p25c×comm25 + p20c×comm20
 *   - 加权平均 = (私家用户×私家月租 + 营运用户×营运月租) / 总用户数
 *
 * 25kWh家庭包首年优惠（-30%）：
 *   - 新车第一年选择家庭包可享受30%折扣
 *   - 模型假设平均折扣30%（存量用户中首年占比30%）
 *
 * @param {number} famRatio   - 家庭包占比（0.5~0.95），决定权重分布
 * @param {number} priv_count - 私家车用户数量（辆）
 * @param {number} comm_count - 营运车用户数量（辆）
 * @returns {{priv_avg, comm_avg, weighted, label, detail}}
 */
Engine.calcWeightedRent = function (famRatio, priv_count, comm_count) {
  var priv_cnt = priv_count || 125;
  var comm_cnt = comm_count || 141;
  var w = Engine.calcRentalWeights(famRatio);

  // 家庭包首年平均折扣（存量用户中首年用户占比×30%）
  var fam25_discount = 0.30;

  // 20kWh私家车：家庭包 vs 不限次，加权平均
  var priv_20 = w.priv.fam20 * Engine.RENT_PRICE.priv20_fam +
                (1 - w.priv.fam20) * Engine.RENT_PRICE.priv20_unl;

  // 25kWh私家车：家庭包（含首年优惠） vs 不限次
  var fam25_eff = w.priv.fam25 *
                  ((1 - fam25_discount) * Engine.RENT_PRICE.priv25_fam +
                   fam25_discount * Engine.RENT_PRICE.priv25_fam_first) +
                  (1 - w.priv.fam25) * Engine.RENT_PRICE.priv25_unl;

  // 私家车加权月租 = p20×20方案 + p25×25方案
  var priv_avg = w.priv.p20 * priv_20 + w.priv.p25 * fam25_eff;

  // 营运车加权月租
  var comm_avg = w.comm.p25c * Engine.RENT_PRICE.comm25_unl +
                 w.comm.p20c * Engine.RENT_PRICE.comm20_unl;

  // 总加权平均
  var total_users = priv_cnt + comm_cnt;
  var weighted = (priv_cnt * priv_avg + comm_cnt * comm_avg) / total_users;

  return {
    priv_avg: Math.round(priv_avg),      // 私家车平均月租（元）
    comm_avg: Math.round(comm_avg),      // 营运车平均月租（元）
    weighted: Math.round(weighted),      // 总加权平均月租（元）
    label: w.label + ' · 加权' + Math.round(weighted) + '元/月',
    detail: {
      priv_20: priv_20, priv_25: fam25_eff,
      priv_avg: priv_avg, comm_avg: comm_avg, weighted: weighted,
      p20: w.priv.p20, p25: w.priv.p25,
      fam20: w.priv.fam20, fam25: w.priv.fam25,
      p25c: w.comm.p25c, p20c: w.comm.p20c,
      fam25_discount: fam25_discount
    }
  };
};

/**
 * 计算单块电池的制造成本（含税）
 *
 * 成本构成：
 *   裸成本 = 电芯成本(元/Wh) + Pack集成成本(元/Wh)
 *   不含税售价 = 裸成本 / (1 - 毛利率)
 *   含税售价 = 不含税售价 × (1 + 13%)
 *   单块电池含税价 = 含税售价 × 56kWh × 1000
 *
 * @param {number} cellCost     - 电芯成本（元/Wh），默认 0.380
 * @param {number} packIntCost  - Pack集成成本（元/Wh），默认 0.100
 * @param {number} grossMargin  - 毛利率（%），默认 22
 * @returns {number} - 单块电池含税售价（元）
 *
 * 示例：
 *   calcBatUnitCost(0.38, 0.10, 22)  → 约 34,800 元/块
 */
Engine.calcBatUnitCost = function (cellCost, packIntCost, grossMargin) {
  var packBareCost = cellCost + packIntCost;    // 裸成本(元/Wh)
  var priceExcl = packBareCost / (1 - grossMargin / 100);  // 不含税售价(元/Wh)
  var priceIncl = priceExcl * (1 + Engine.VAT_13);          // 含税售价(元/Wh)
  return priceIncl * Engine.BAT_CAP_KWH * 1000;            // 单块含税价(元)
};
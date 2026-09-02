/**
 * ============================================================
 * 换电重估报告 · 参数配置文件 config.js
 * ============================================================
 * 定位：纯数据，不做计算。所有参数严格对齐
 *   《换电毛估估_折扣链与总表_v2.4.md》（稳健★口径）
 *   与《重卡与城配物流换电规模测算_合并对比.py》。
 *
 * 分离原则：参数（config.js）与逻辑（engine.js）严格分离。
 * 信源标注：外部信源 / 经验假设 / 沿用v2.4（三档）。
 * ============================================================
 */

var SwapConfig = (function () {
  'use strict';

  // ============================================================
  // 一、换电车辆（万辆）—— 分母，来自 v2.4 §2.2 五层漏斗
  // ============================================================
  var fleetWan = {
    重卡:     { value: 38,  source: 'v2.4§2.2·重卡三层过滤' },
    城配物流: { value: 87,  source: 'v2.4§2.2·城配高频子集' },
    乘用营运: { value: 88,  source: 'v2.4§2.2·出租21+网约17+Robotaxi50' },
    私家车:   { value: 145, source: 'v2.4§2.2·私家车累计净增中枢' },
  };

  // ============================================================
  // 二、单车带电量（kWh）与余电折扣
  // ============================================================
  var batteryKwh = {
    重卡:     { value: 500, source: 'v2.4§2.2·重卡长续航增量口径(JPM)' },
    城配物流: { value: 80,  source: 'v2.4§2.2·太平洋汽车' },
    乘用营运: { value: 56,  source: 'v2.4§2.2·巧克力25#标准块' },
    私家车:   { value: 56,  source: 'v2.4§2.2·巧克力标准块' },
  };
  var usableFactor = { value: 0.80, source: 'v2.4§2.4·余电折扣0.8' };

  // ============================================================
  // 三、换电频次 f（次/天）—— v2.4 §2.4
  // ============================================================
  var freq = {
    重卡:     { value: 1.8,  source: 'v2.4§2.4·三场景加权(短0.7/中1.7/长2.7)' },
    城配物流: { value: 1.3,  source: 'v2.4§2.4·300km/237续航' },
    乘用营运: { value: 1.42, source: 'v2.4§2.4·出租1.5+网约1.1+Robotaxi1.5加权' },
    私家车:   { value: 0.2,  source: 'v2.4§2.4·60km/300续航' },
  };

  // ============================================================
  // 四、站数（座）与站体参数—— v2.4 §2.4 官方规划口径
  // ============================================================
  // 站数取官方规划口径（非反推）：骐骥3000 + 巧克力8000 = 11000
  var stationCount = {
    骐骥:   { value: 3000, source: 'v2.4§2.4·官方规划(15万km高速÷100km×2)' },
    巧克力: { value: 8000, source: 'v2.4§2.4·营运车需站数反推≈8000' },
  };
  // 单站物理参数（v2.4 §2.3 权威口径）
  var stationInventory = {
    骐骥: {
      blocks: 24, kwhPerBlock: 171,
      power: 4500,           // 满负荷功率 kW
      netCharge: 136.8,      // 单次净补电量（度）= 171×0.8
      swapTime: 300,         // 换电时长（秒）
      source: 'v2.4§2.3·骐骥24工位×171kWh',
    },
    巧克力: {
      blocks: 14, kwhPerBlock: 56,
      power: 1120,           // 满负荷功率 kW
      netCharge: 44.8,       // 单次净补电量（度）= 56×0.8
      swapTime: 100,         // 换电时长（秒）
      source: 'v2.4§2.3·巧克力14块×56kWh',
    },
  };
  // 单站投资（万/座）
  var siteCapexWan = {
    骐骥:   { value: 500, source: 'v2.4§2.1·骐骥站体投资' },
    巧克力: { value: 200, source: 'v2.4§2.1·巧克力站体投资' },
  };
  // 单站设计能力（次/天）
  var designCapacity = {
    骐骥:   { value: 192, source: 'v2.4§2.3·骐骥官方16h工位口径' },
    巧克力: { value: 300, source: 'v2.4§2.3·巧克力自设(552×54%)' },
  };

  // ============================================================
  // 五、度电成本与定价
  // ============================================================
  var batteryPrice = { value: 590, unit: '元/kWh', source: 'v2.4§2.1·度电成本' };
  var serviceFee = { value: 0.40, unit: '元/度', source: 'v2.4§2.1·度电服务费(净额法)' };
  var rentRmbKwhYear = { value: 120, unit: '元/kWh·年', source: 'v2.4§2.1·装车电池租金(综合~10元/月)' };
  var days = { value: 350, unit: '天/年', source: 'v2.4§3.2·保守350天' };

  // ============================================================
  // 六、经营成本参数（v2.4 §3.2）
  // ============================================================
  var valleyPrice = { value: 0.30, unit: '元/度', source: 'v2.4§2.1·谷电价(经验假设)' };
  var rte = { value: 0.92, unit: '', source: 'v2.4§3.2·RTE锂电90-95%中值' };
  var aux = { value: 0.02, unit: '', source: 'v2.4§3.2·厂用电率' };
  var siteRentWan = { value: 30, unit: '万/站·年', source: 'v2.4§2.1·场租(经验假设)' };
  var laborRmb = {
    重卡:     { value: 30, source: 'v2.4§3.2·重卡单次成本' },
    城配物流: { value: 13, source: 'v2.4§3.2·乘用单次成本' },
    乘用营运: { value: 13, source: 'v2.4§3.2·乘用单次成本' },
    私家车:   { value: 13, source: 'v2.4§3.2·乘用单次成本' },
  };
  var softwareOpexYi = { value: 20, unit: '亿元', source: 'v2.4§3.2·软件调度固定20亿' };
  // 峰谷套利：站内周转装机×天数×峰谷差×RTE÷100，每天只计1次
  var peakValleyGap = { value: 0.40, unit: '元/kWh', source: 'v2.4§3.2·谷0.3→峰0.7' };
  // 辅助服务（容量补偿+max(需求响应,调频VPP)）
  var ancillaryYi = { value: 5.15, unit: '亿元', source: 'v2.4§3.2·辅助服务合计' };

  // ============================================================
  // 七、资本链参数（v2.4 §3.1）—— 门槛EBITDA与估值
  // ============================================================
  var eac = {  // EAC放大倍数（1+净重置比例）
    重卡:     { value: 1.46, source: 'v2.4§1.2.1·重卡EAC' },
    城配物流: { value: 1.78, source: 'v2.4§1.2.1·城配EAC' },
    乘用营运: { value: 1.78, source: 'v2.4§1.2.1·乘用EAC' },
    私家车:   { value: 1.21, source: 'v2.4§1.2.1·私家EAC' },
  };
  var swapLife = {  // 电池寿命（年）
    重卡:     { value: 5.7,  source: 'v2.4§1.2.1·重卡寿命' },
    城配物流: { value: 3.8,  source: 'v2.4§1.2.1·城配寿命' },
    乘用营运: { value: 3.8,  source: 'v2.4§1.2.1·乘用寿命' },
    私家车:   { value: 10.0, source: 'v2.4§1.2.1·私家寿命' },
  };
  var residualRate = {  // 期末残值率
    重卡:     { value: 0.329, source: 'v2.4§3.1·电池价格变动计算' },
    城配物流: { value: 0.329, source: 'v2.4§3.1·电池价格变动计算' },
    乘用营运: { value: 0.329, source: 'v2.4§3.1·电池价格变动计算' },
    私家车:   { value: 0.317, source: 'v2.4§3.1·电池价格变动计算' },
  };
  var crf = { value: 0.15, source: 'v2.4§1.2.2·期望收益率10-15%中值' };
  var evEbitda = { value: 18, unit: '×', source: 'v2.4§4.1·EV/EBITDA中枢18×' };
  var debtRatio = { value: 0.60, source: 'v2.4§3.1·资本结构股40%+债60%' };
  var interest = { value: 0.025, source: 'v2.4§3.1·债务年息2.5%(绿债)' };
  var catlEquityShare = { value: 0.40, source: 'v2.4§3.1·CATL自持40%' };
  var stationLife = { value: 15, unit: '年', source: 'v2.4§3.1·站体15年折旧' };
  var taxRate = { value: 0.25, unit: '', source: '外部信源·企业所得税率' };

  // ============================================================
  // 八、增量估值新增参数（CATL_换电增量估值模型.md，非v2.4）
  // ============================================================
  var windowYears = { value: 15, unit: '年', source: '经验假设·订单池观察窗15年' };
  // 换电标准下 CATL 份额（高，因标准/电池银行锁定）
  var swapShare = {
    重卡:     { value: 0.70, source: '经验假设·换电标准锁定' },
    城配物流: { value: 0.80, source: '经验假设·换电标准锁定' },
    乘用营运: { value: 0.60, source: '经验假设·换电标准锁定' },
    私家车:   { value: 0.55, source: '经验假设·换电标准锁定' },
  };
  // 无换电 CATL 份额（假设，需外部验证）
  var noSwapShare = {
    重卡:     { value: 0.50, source: '经验假设·需外部验证' },
    城配物流: { value: 0.50, source: '经验假设·需外部验证' },
    乘用营运: { value: 0.50, source: '经验假设·需外部验证' },
    私家车:   { value: 0.50, source: '经验假设·需外部验证' },
  };
  // ΔShare = 换电份额 − 无换电份额
  var deltaShare = {
    重卡:     { value: 0.20, source: '= 换电70% − 无换电50%' },
    城配物流: { value: 0.30, source: '= 换电80% − 无换电50%' },
    乘用营运: { value: 0.10, source: '= 换电60% − 无换电50%' },
    私家车:   { value: 0.05, source: '= 换电55% − 无换电50%' },
  };
  var gpPerKwh = { value: 139.45, unit: '元/kWh', source: '外部信源·2025年报(316.5亿/241.1亿/541GWh)' };
  var platformOwnership = { value: 0.40, source: '经验假设·换电平台CATL持股' };
  var pbRevenue2030 = { value: 5000, unit: '亿元', source: '经验假设·2030动力电池收入锚' };
  var noSwapGm = { value: 0.18, source: '经验假设·无换电毛利率18%' };
  var gmProtection = { value: 0.015, source: '经验假设·毛利率保护+1.5ppt' };
  var pe = { value: 20, unit: '×', source: '外部信源·整体PE≈20×(2万亿/2026E 1000亿净利)', range: [18, 25] };

  // ============================================================
  // 九、逐年后渗节奏（增量模型新增，用于关联交易抵消演示）
  // ============================================================
  // 说明：换电站2028基本建成；电池随车型逐年渗透（非2029归零）
  var batteryBuildShare = {
    2026: { value: 0.15, source: '经验假设·渗透曲线' },
    2027: { value: 0.30, source: '经验假设·渗透曲线' },
    2028: { value: 0.30, source: '经验假设·渗透曲线' },
    2029: { value: 0.15, source: '经验假设·渗透曲线' },
    2030: { value: 0.10, source: '经验假设·渗透曲线' },
  };

  // ============================================================
  // 导出：扁平化 value 供 engine 计算
  // ============================================================
  function flatten(obj) {
    var out = {};
    for (var k in obj) {
      if (obj[k] && typeof obj[k] === 'object' && 'value' in obj[k]) {
        out[k] = obj[k].value;
      } else if (obj[k] && typeof obj[k] === 'object') {
        out[k] = flatten(obj[k]);
      } else {
        out[k] = obj[k];
      }
    }
    return out;
  }

  return {
    meta: {
      fleetWan: fleetWan, batteryKwh: batteryKwh, freq: freq,
      stationCount: stationCount, stationInventory: stationInventory,
      siteCapexWan: siteCapexWan, designCapacity: designCapacity,
      batteryPrice: batteryPrice, serviceFee: serviceFee, rentRmbKwhYear: rentRmbKwhYear,
      days: days, usableFactor: usableFactor,
      valleyPrice: valleyPrice, rte: rte, aux: aux, siteRentWan: siteRentWan,
      laborRmb: laborRmb, softwareOpexYi: softwareOpexYi,
      peakValleyGap: peakValleyGap, ancillaryYi: ancillaryYi,
      eac: eac, swapLife: swapLife, residualRate: residualRate,
      crf: crf, evEbitda: evEbitda, debtRatio: debtRatio, interest: interest,
      catlEquityShare: catlEquityShare, stationLife: stationLife, taxRate: taxRate,
      windowYears: windowYears, swapShare: swapShare, noSwapShare: noSwapShare,
      deltaShare: deltaShare, gpPerKwh: gpPerKwh,
      platformOwnership: platformOwnership, pbRevenue2030: pbRevenue2030,
      noSwapGm: noSwapGm, gmProtection: gmProtection, pe: pe,
      batteryBuildShare: batteryBuildShare,
    },
    values: flatten({
      fleetWan: fleetWan, batteryKwh: batteryKwh, freq: freq,
      stationCount: stationCount, stationInventory: stationInventory,
      siteCapexWan: siteCapexWan, designCapacity: designCapacity,
      batteryPrice: batteryPrice, serviceFee: serviceFee, rentRmbKwhYear: rentRmbKwhYear,
      days: days, usableFactor: usableFactor,
      valleyPrice: valleyPrice, rte: rte, aux: aux, siteRentWan: siteRentWan,
      laborRmb: laborRmb, softwareOpexYi: softwareOpexYi,
      peakValleyGap: peakValleyGap, ancillaryYi: ancillaryYi,
      eac: eac, swapLife: swapLife, residualRate: residualRate,
      crf: crf, evEbitda: evEbitda, debtRatio: debtRatio, interest: interest,
      catlEquityShare: catlEquityShare, stationLife: stationLife, taxRate: taxRate,
      windowYears: windowYears, swapShare: swapShare, noSwapShare: noSwapShare,
      deltaShare: deltaShare, gpPerKwh: gpPerKwh,
      platformOwnership: platformOwnership, pbRevenue2030: pbRevenue2030,
      noSwapGm: noSwapGm, gmProtection: gmProtection, pe: pe,
      batteryBuildShare: batteryBuildShare,
    }),
  };
})();

if (typeof module !== 'undefined' && module.exports) {
  module.exports = SwapConfig;
}

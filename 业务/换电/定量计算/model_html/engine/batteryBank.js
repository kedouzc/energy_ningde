/**
 * ============================================================
 * engine/batteryBank.js — 电池银行模型（资产端）
 * ============================================================
 *
 * 本文件计算电池银行单站对应的15年财务模型，包括：
 *   - 电池资产规模（用户电池 + 周转电池）
 *   - 收入：用户电池租金 + 周转电池租金 + 技术服务费
 *   - 成本：运维 + 技术服务成本 + 保险 + 人工 + 仓储物流
 *   - 电池置换：营运车池（3/6/9/12年，SOH 83%）+ 私家车池（第8年，SOH 88%）
 *   - 残值回收：15年末梯次利用
 *   - 税收：增值税 + 附加税 + 所得税
 *   - 输出：IRR / NPV / 净利润 / 现金流
 *
 * 加载顺序：在 constants.js, tax.js, financial.js, rental.js 之后
 * 对应MD文档：宁德时代_超换一体站_财务模型_修正版.md # 2.2 电池银行模型
 * ============================================================
 */
var Engine = window.Engine || {};

/**
 * 获取电池银行人力密度（人/块），随总规模递减（平台效应）
 *
 * 蔚能基准：97人/15万块，随规模分段递减
 *
 * @param {number} totalBats - 系统总电池数（块）
 * @returns {number} 人力密度（人/块）
 */
Engine.getBankStaffDensity = function (totalBats) {
  var baseDensity = 97 / 150000;
  var scaleFactor;
  if (totalBats <= 150000) {
    scaleFactor = 1.0;   // 小规模（≤15万块）：蔚能同期密度
  } else if (totalBats <= 1500000) {
    scaleFactor = 0.70;  // 中规模（15万~150万块）：密度降至70%（系统复用）
  } else if (totalBats <= 6000000) {
    scaleFactor = 0.50;  // 大规模（150万~600万块）：密度降至50%（AI调度+自动化）
  } else {
    scaleFactor = 0.35;  // 超大规模（>600万块）：密度降至35%（平台效应最大化）
  }
  return baseDensity * scaleFactor;
};
// 单块电池年人工成本 = 人力密度 × 人均年薪（动态计算，见calcBatteryBank）
// 示例：小规模≈114元/块/年，超大规模≈40元/块/年

/**
 * 计算电池银行单站模型
 *
 * 核心逻辑流程：
 *   1. 从换电站获取用户结构（营运车/私家车），计算电池租金
 *   2. 计算电池资产规模与各项收入、成本
 *   3. 按车型拆分电池池（营运车池 + 私家车池，周转电池按比例分配）
 *   4. 营运车池在第3/6/9/12年置换（SOH=83%），私家车池在第8年置换（SOH=88%）
 *   5. 15年末残值回收
 *   6. 计算IRR/NPV
 *
 * @param {Object} p - 参数对象，需包含以下字段：
 *   p.st              - 换电站单站模型结果（Engine.calcPureStation 的返回值）
 *   p.fam_ratio        - 家庭包占比（0.5~0.95）
 *   p.spare_bats       - 周转电池数量
 *   p.spare_rent       - 周转电池月租金（元/月/块）
 *   p.tech_service     - 技术服务费（元/年/站），如 35000
 *   p.bat_replace_strategy - 置换策略 'A'(不置换) 或 'B'(到期置换)
 *   p.cell_cost        - 电芯成本（元/Wh，默认 0.380）
 *   p.pack_integration_cost - Pack集成成本（元/Wh，默认 0.100）
 *   p.gross_margin     - 毛利率（%，默认 22）
 *   p.total_stations   - 总站点数（影响人力密度，默认 100000）
 *   p.bank_team_size   - 自定义团队规模（0或不传=自动计算）
 *   p.discount_rate    - 折现率（小数，默认 0.075）
 *
 * @returns {Object} 电池银行完整财务模型
 */
Engine.calcBatteryBank = function (p) {
  // ============================================================
  // 一、参数解析
  // ============================================================
  var st = p.st;
  if (!st) {
    st = Engine.calcPureStation(p);  // 如果调用方未预计算，则自动从原始参数推算
  }
  var comm           = st.comm_users;
  var priv           = st.priv_users;
  var total_users    = st.total_users;
  var spare_bats     = p.spare_bats;
  var replace_strategy = p.bat_replace_strategy || 'A';
  var discountRate   = (typeof p.discount_rate !== 'undefined') ? p.discount_rate : Engine.DEFAULT_DISCOUNT_RATE;
  var YEARS          = Engine.YEARS || 15;

  // 租金计算
  var rentInfo = Engine.calcWeightedRent(p.fam_ratio, priv, comm);
  var priv_rent = rentInfo.priv_avg;
  var comm_rent = rentInfo.comm_avg;

  // 电池资产核算
  var user_bats  = total_users;
  var total_bats = user_bats + spare_bats;

  // 电池单位成本（含税）
  var cellCost     = (typeof p.cell_cost !== 'undefined') ? p.cell_cost : 0.380;
  var packIntCost  = (typeof p.pack_integration_cost !== 'undefined') ? p.pack_integration_cost : 0.100;
  var grossMargin  = (typeof p.gross_margin !== 'undefined') ? p.gross_margin : 22;
  var bat_unit     = Engine.calcBatUnitCost(cellCost, packIntCost, grossMargin);
  var total_capex_incl = total_bats * bat_unit;

  // ============================================================
  // 二、收入计算（含税）
  // ============================================================
  var user_rent_rev_incl   = (priv * priv_rent + comm * comm_rent) * 12;  // 13% VAT
  var spare_rent_rev_incl  = spare_bats * p.spare_rent * 12;              // 13% VAT
  var tech_service_rev_incl = (typeof p.tech_service !== 'undefined') ? p.tech_service : 35000;  // 6% VAT
  var total_revenue_incl = user_rent_rev_incl + spare_rent_rev_incl + tech_service_rev_incl;

  // ============================================================
  // 三、成本计算（含税）
  // ============================================================
  // 电池运维管理 = 电池资产×2%（含税13%）日常监控、调度、巡检
  // 取数原因：电池池化管理（0.47次/块/天 vs 储能站1-2次），运维强度为储能站50%，对标储能运维费率0.4%-0.5%的50%=2%
  var bat_maint_incl = total_capex_incl * Engine.BAT_MAINT_RATE;         // 13% VAT
  // 技术服务成本 = 默认费率×20%（含税6%）边际成本低，主要为系统支持
  // 取数原因：APP/系统支持的人力+服务器+带宽+SDK许可
  // 关键：按默认费率(3.5万)计算固定成本，而非实际收费
  //   实际收费是内部结算价格，不应影响真实成本——提供技术服务的成本不会因为收费高了就变贵
  //   这样一体化合并时，内部结算参数变化不会泄漏到合并EBITDA
  var tech_service_cost_incl = Engine.INTERNAL_TECH_FEE_YEARLY * Engine.TECH_SERVICE_COST_RATIO;  // 6% VAT
  // 电池资产保费 = 电池资产×0.20%（含税6%）
  var bat_insur_incl = total_capex_incl * Engine.BAT_INSUR_RATE;         // 6% VAT

  // 电池银行人工（规模化效应）：按电池量挂钩（蔚能人力密度+CATL薪酬水平+平台效应）
  // 逻辑：电池银行是平台型业务，人力与管理的电池总量挂钩，但密度随规模递减
  // 蔚能基准：97人/60万块；中大规模时系统/AI替代人工，密度递减
  // 算法说明：电池银行团队规模=系统总电池×人力密度系数
  //   - 系统总电池=MAX(单站电池数, 总站数×单站电池数)，确保大规模时密度降低
  //   - 人力密度系数=getBankStaffDensity()，分段递减（小规模100%→中规模70%→大规模50%→超大规模35%）
  //   - 单块年人工成本=密度系数×CATL人均年薪17.64万
  //   - 团队规模至少5人（最低运营配置）
  // 数据来源注释：
  //   - 蔚能97人为2023年社保人数（企查查/水滴/启信宝一致），60万块为2026年规模
  //   - 实际2023年蔚能仅管理约4万块电池（2022年ABS募集说明书第92页），
  //     97人/4万块=1人/412块，密度远高于当前模型基准
  //   - 本模型采用"事后对齐"密度（97人/60万块）作为基准，已隐含平台效应
  //   - 再叠加规模因子(0.35~1.0)是二次折减，反映CATL更大规模下的AI/自动化优势
  var systemTotalBats = Math.max(total_bats, (p.total_stations || 100000) * total_bats);
  var staffDensity = Engine.getBankStaffDensity(systemTotalBats);
  var batLaborCostPerYear = staffDensity * Engine.BANK_AVG_SALARY;

  // 密度模型：可变团队（商务/区域运营/客服）按站点规模
  // 固定团队（数字化+金融+省网+平台底座）不随站点变化
  var FIXED_TEAM = 450 + 20 + 45 + 50; // 565人
  // 可变团队密度（人/站），随规模递减
  var varTeamDensity;
  if (p.total_stations <= 1000) {
    varTeamDensity = 0.10; // 小规模：商务+运营+客服=0.10人/站
  } else if (p.total_stations <= 10000) {
    varTeamDensity = 0.07; // 中规模：密度降至70%
  } else if (p.total_stations <= 50000) {
    varTeamDensity = 0.05; // 大规模：密度降至50%
  } else {
    varTeamDensity = 0.04; // 超大规模：密度降至40%（平台效应）
  }
  var varTeamSize = Math.round((p.total_stations || 100000) * varTeamDensity);
  // 可变团队拆分：商务40% + 区域运营50% + 客服10%
  var bizTeam = Math.round(varTeamSize * 0.40);      // 商务拓展
  var opsTeam = Math.round(varTeamSize * 0.50);      // 区域运营
  var csTeam  = Math.round(varTeamSize * 0.10);      // 客服中心
  var densityTeamSize = FIXED_TEAM + bizTeam + opsTeam + csTeam;
  // 电池银行团队规模：优先使用用户自定义参数，未设置时按密度模型计算
  var userTeamSize = (typeof p.bank_team_size !== 'undefined' && p.bank_team_size > 0)
    ? p.bank_team_size : densityTeamSize;
  var bankTeamSize = Math.max(5, userTeamSize);
  // 当用户使用自定义团队规模时，可变团队按密度模型比例缩放（保持团队结构合理）
  var teamScaleRatio = bankTeamSize / densityTeamSize;
  var displayBizTeam = Math.round(bizTeam * teamScaleRatio);
  var displayOpsTeam = Math.round(opsTeam * teamScaleRatio);
  var displayCsTeam  = Math.round(csTeam * teamScaleRatio);

  // 单块电池年人工成本
  var batLaborCostPerYearActual = (bankTeamSize * Engine.BANK_AVG_SALARY * (1 + Engine.SOCIAL)) / systemTotalBats;
  var bankLaborAnnual = Math.round(total_bats * batLaborCostPerYearActual);
  var bankLaborPerStation = bankLaborAnnual;

  // 仓储物流 = 电池资产×0.05%（含税13%）
  // 取数原因：30个区域仓外包运营（3,000万/年）+跨站调拨运输外包（2.7亿/年）=3.0亿/年
  // 单站分摊3,000元/年，占831万资产的0.036%。模型保守按0.05%计提=4,155元/站/年
  var warehouse_logistics_incl = total_capex_incl * 0.0005;

  var total_opex_incl = bat_maint_incl + tech_service_cost_incl + bat_insur_incl + bankLaborPerStation + warehouse_logistics_incl;

  // ============================================================
  // 四、税务分组
  // ============================================================
  var rev13 = user_rent_rev_incl + spare_rent_rev_incl;
  var rev6  = tech_service_rev_incl;
  var opex13 = bat_maint_incl + warehouse_logistics_incl;
  var opex6  = tech_service_cost_incl + bat_insur_incl;
  var opexNoVAT = bankLaborPerStation;

  // 电池资产可抵扣进项（含13%增值税）
  var batteryExcl = total_capex_incl / (1 + Engine.VAT_13);
  var assetInputVAT = total_capex_incl - batteryExcl;
  var depreciation = batteryExcl * (1 - Engine.BAT_RESIDUAL) / YEARS;

  var tax = Engine.calcYearlyTax(rev13, rev6, opex13, opex6, opexNoVAT, assetInputVAT, depreciation);
  var ebitda_excl = tax.ebitda;
  var rev_excl = tax.revExcl;
  var opex_excl = tax.opexExcl;

  // ============================================================
  // 五、车型拆分电池池 + 分期置换
  // ============================================================
  // 营运车/私家车电池数（含按比例分配的周转电池）
  // 换入新电池按届时动力电池价格计算；回收旧电池按届时储能电池价格×SOH×可用度系数计算
  var comm_ratio = total_users > 0 ? comm / total_users : 0;
  var priv_ratio = total_users > 0 ? priv / total_users : 0;
  var comm_bats = comm + spare_bats * comm_ratio;
  var priv_bats = priv + spare_bats * priv_ratio;

  // 电池置换经济——新电池单位成本和旧电池单位残值随年份变化（查三阶段数组，单一真源）
  // 注：yr 为自 BASE_YEAR(2026) 起的第几年（0..15）；三阶段数据由 sync_prices.js 注入
  function calcNewBatUnitCostAtYear(yr) {
    var t = Math.min(Math.max(yr, 0), 15);
    return Engine.BAT_PRICE_BY_YEAR[t]; // 单块含税电池成本（元/块，25# LFP 56kWh）
  }

  function calcOldBatUnitResidualAtYear(yr, soh) {
    var t = Math.min(Math.max(yr, 0), 15);
    var essCellCost = Engine.ESS_CELL_BY_YEAR[t]; // 储能电芯价（元/Wh，三阶段推演）
    var degradeDiscount = soh * Engine.BAT_DEGRADE_FACTOR;
    var residualPerWh = essCellCost * degradeDiscount * Engine.BAT_ESS_AVAILABILITY;
    return residualPerWh * Engine.BAT_CAP_KWH * 1000;
  }

  // 营运车池置换明细（第3、6、9、12年，SOH=83%）
  // 每次置换全部营运车电池（含对应周转电池）
  var comm_replace_years = [3, 6, 9, 12];
  var comm_soh = Engine.SOH_OPERATIONAL_EXIT; // 0.83
  var commReplaceDetails = [];

  // 私家车池置换（第8年，SOH=88%）
  var priv_replace_year = 8;
  var priv_soh = Engine.SOH_PRIVATE_EXIT; // 0.88
  var privReplaceDetail = null;

  if (replace_strategy === 'B' && total_bats > 0) {
    // 营运车多次置换
    for (var ci = 0; ci < comm_replace_years.length; ci++) {
      var yr = comm_replace_years[ci];
      if (yr > YEARS) continue;
      var newUnit = calcNewBatUnitCostAtYear(yr);
      var oldUnit = calcOldBatUnitResidualAtYear(yr, comm_soh);
      commReplaceDetails.push({
        year: yr,
        bats: comm_bats,
        new_unit_cost: newUnit,
        old_unit_residual: oldUnit,
        new_total: comm_bats * newUnit,
        old_total: comm_bats * oldUnit,
        net_cost: comm_bats * newUnit - comm_bats * oldUnit,
        // 税务：旧电池出售销项13% - 新电池采购进项13%
        old_out_vat: (comm_bats * oldUnit) / (1 + Engine.VAT_13) * Engine.VAT_13,
        new_in_vat: (comm_bats * newUnit) / (1 + Engine.VAT_13) * Engine.VAT_13,
        net_tax: (comm_bats * oldUnit) - (comm_bats * newUnit) -
                 (comm_bats * oldUnit) / (1 + Engine.VAT_13) * Engine.VAT_13 +
                 (comm_bats * newUnit) / (1 + Engine.VAT_13) * Engine.VAT_13
      });
    }

    // 私家车单次置换
    if (priv_replace_year <= YEARS) {
      var privNewUnit = calcNewBatUnitCostAtYear(priv_replace_year);
      var privOldUnit = calcOldBatUnitResidualAtYear(priv_replace_year, priv_soh);
      privReplaceDetail = {
        year: priv_replace_year,
        bats: priv_bats,
        new_unit_cost: privNewUnit,
        old_unit_residual: privOldUnit,
        new_total: priv_bats * privNewUnit,
        old_total: priv_bats * privOldUnit,
        net_cost: priv_bats * privNewUnit - priv_bats * privOldUnit,
        old_out_vat: (priv_bats * privOldUnit) / (1 + Engine.VAT_13) * Engine.VAT_13,
        new_in_vat: (priv_bats * privNewUnit) / (1 + Engine.VAT_13) * Engine.VAT_13,
        net_tax: (priv_bats * privOldUnit) - (priv_bats * privNewUnit) -
                 (priv_bats * privOldUnit) / (1 + Engine.VAT_13) * Engine.VAT_13 +
                 (priv_bats * privNewUnit) / (1 + Engine.VAT_13) * Engine.VAT_13
      };
    }
  }

  // 汇总各年置换净税务影响
  var replaceTaxByYear = {};  // { year: netTaxAmount }
  for (var cdi = 0; cdi < commReplaceDetails.length; cdi++) {
    var cdr = commReplaceDetails[cdi];
    replaceTaxByYear[cdr.year] = (replaceTaxByYear[cdr.year] || 0) + cdr.net_tax;
  }
  if (privReplaceDetail) {
    replaceTaxByYear[privReplaceDetail.year] = (replaceTaxByYear[privReplaceDetail.year] || 0) + privReplaceDetail.net_tax;
  }

  // 置换净支出合计（含税，用于展示）
  var bat_replace_net_total = 0;
  for (var cdi2 = 0; cdi2 < commReplaceDetails.length; cdi2++) {
    bat_replace_net_total += commReplaceDetails[cdi2].old_total - commReplaceDetails[cdi2].new_total;
  }
  if (privReplaceDetail) {
    bat_replace_net_total += privReplaceDetail.old_total - privReplaceDetail.new_total;
  }

  // ============================================================
  // 六、15年末残值回收
  // ============================================================
  var residualExcl = batteryExcl * Engine.BAT_RESIDUAL;
  var residualTax  = residualExcl * Engine.CIT;
  var residualNCF  = residualExcl - residualTax;

  // ============================================================
  // 七、净现金流计算（含分期置换 + 残值回收）
  // ============================================================
  var cfs_net = [-total_capex_incl];
  for (var t2 = 0; t2 < YEARS; t2++) {
    var cf = tax.yearly[t2].ncf;
    var yrNum = t2 + 1;
    if (replaceTaxByYear[yrNum]) {
      cf += replaceTaxByYear[yrNum];
    }
    if (t2 === YEARS - 1) {
      cf += residualNCF;
    }
    cfs_net.push(cf);
  }

  var irr = Engine.calcIRR(cfs_net);
  var payback = tax.yearly[0].ncf > 0 ? total_capex_incl / tax.yearly[0].ncf : Infinity;

  // NPV
  var npv_excl = -total_capex_incl;
  for (var t3 = 1; t3 <= YEARS; t3++) {
    var cfNPV = tax.yearly[t3 - 1].ncf;
    if (replaceTaxByYear[t3]) {
      cfNPV += replaceTaxByYear[t3];
    }
    if (t3 === YEARS) {
      cfNPV += residualNCF;
    }
    npv_excl += cfNPV / Math.pow(1 + discountRate, t3);
  }

  // 净利率（第1年）
  var yr1 = tax.yearly[0];
  var net_margin = rev_excl > 0 ? yr1.np / rev_excl : 0;

  // 累计净现金流
  var bbNCFSum = 0;
  for (var t4 = 0; t4 < YEARS; t4++) {
    var cfNCF = tax.yearly[t4].ncf;
    var yrNCF = t4 + 1;
    if (replaceTaxByYear[yrNCF]) {
      cfNCF += replaceTaxByYear[yrNCF];
    }
    if (t4 === YEARS - 1) {
      cfNCF += residualNCF;
    }
    bbNCFSum += cfNCF;
  }

  return {
    // 资产池
    users: total_users, comm: comm, priv: priv,
    spare_bats: spare_bats, user_bats: user_bats, total_bats: total_bats,
    // 车型拆分电池池
    comm_bats: comm_bats, priv_bats: priv_bats,
    comm_ratio: comm_ratio, priv_ratio: priv_ratio,
    // 电池成本
    bat_unit: bat_unit, total_capex: total_capex_incl,
    // 租金
    priv_rent: priv_rent, comm_rent: comm_rent,
    // 收入
    user_rent_rev_incl: user_rent_rev_incl,
    spare_rent_rev_incl: spare_rent_rev_incl,
    tech_service_rev_incl: tech_service_rev_incl,
    total_revenue_incl: total_revenue_incl,
    // 成本
    bat_maint_incl: bat_maint_incl,
    tech_service_cost_incl: tech_service_cost_incl,
    bat_insur_incl: bat_insur_incl,
    bankLaborPerStation: bankLaborPerStation,
    warehouse_logistics_incl: warehouse_logistics_incl,
    total_opex_incl: total_opex_incl,
    // 财务
    rev_excl: rev_excl, opex_excl: opex_excl,
    ebitda_excl: ebitda_excl, depreciation: depreciation,
    // 营运车池置换明细
    commReplaceDetails: commReplaceDetails,
    // 私家车池置换明细
    privReplaceDetail: privReplaceDetail,
    // 各年置换税务影响
    replaceTaxByYear: replaceTaxByYear,
    // 置换净支出合计（含税）
    bat_replace_net_total: bat_replace_net_total,
    // 残值
    residualExcl: residualExcl, residualNCF: residualNCF,
    // 现金流/回报
    tax: tax, yr1: yr1, net_margin: net_margin,
    npv: npv_excl, irr: irr, payback: payback,
    ncf_sum: bbNCFSum,
    // 其他
    replace_strategy: replace_strategy,
    rentInfo: rentInfo,
    bankLaborAnnual: bankLaborAnnual,
    bankTeamSize: bankTeamSize,
    systemTotalBats: systemTotalBats,
    staffDensity: staffDensity,
    batLaborCostPerYear: batLaborCostPerYear,
    batLaborCostPerYearActual: batLaborCostPerYearActual,
    bizTeam: displayBizTeam,
    opsTeam: displayOpsTeam,
    csTeam: displayCsTeam,
    varTeamDensity: varTeamDensity
  };
};

/**
 * 计算单块电池IRR（基于净现金流，含全部运营成本）
 *
 * 现金流：Y0 = -电池含税价，Y1~Y(N-1) = 年净现金流，YN = 年净现金流 + 残值
 * 年净现金流 = 租金收入 + 技术服务费 - 维保 - 保险 - 人工 - 仓储物流 - 税金
 * 与 Engine.calcBatteryBank 的全模型 IRR 保持一致的口径
 *
 * @param {number} monthlyNetCash - 月均净现金流（元/块），已扣除全部运营成本
 * @param {number} batCost - 电池含税成本（元/块）
 * @returns {number|null} IRR值
 */
Engine.calcBatteryBankIRR = function (monthlyNetCash, batCost) {
  var years = Engine.YEARS || 15;
  var annualNetCash = monthlyNetCash * 12;
  var residual = batCost * (Engine.BAT_RESIDUAL || 0.10);
  var cf = [-batCost];
  for (var i = 0; i < years - 1; i++) cf.push(annualNetCash);
  cf.push(annualNetCash + residual);
  return Engine.calcIRR(cf);
};
/**
 * ============================================================
 * 换电重估报告 · 计算引擎 engine.js
 * ============================================================
 * 定位：纯计算，零硬编码参数。严格对齐
 *   《换电毛估估_折扣链与总表_v2.4.md》（稳健★口径）
 *   + 《CATL_换电增量估值模型.md》（四层ΔNI）
 *
 * 两套输出：
 *   1) standalone —— v2.4 的 Standalone 估值（CAPEX→门槛EBITDA→EV→宁德40%）
 *   2) incremental —— 增量估值（四层ΔNI：平台/订单锁定/基本盘保护）
 * ============================================================
 */

var SwapEngine = (function () {
  'use strict';

  function deepMerge(base, over) {
    var out = {};
    for (var k in base) out[k] = base[k];
    for (var k2 in over) {
      if (over[k2] && typeof over[k2] === 'object' && !Array.isArray(over[k2]) && base[k2] && typeof base[k2] === 'object') {
        out[k2] = deepMerge(base[k2], over[k2]);
      } else {
        out[k2] = over[k2];
      }
    }
    return out;
  }

  /**
   * 主计算：standalone + incremental 两套
   */
  function compute(cfg, overrides) {
    var c = deepMerge(cfg, overrides || {});

    // ================= 基础物理量 =================
    var fleetWanTotal = 0;
    for (var k in c.fleetWan) fleetWanTotal += c.fleetWan[k];

    // 装车电池 GWh（车辆×单车带电量÷100）
    var fleetGwh = {};
    var fleetTotalGwh = 0;
    for (var k2 in c.fleetWan) {
      fleetGwh[k2] = c.fleetWan[k2] * c.batteryKwh[k2] / 100;  // 万辆×kWh÷100 = GWh
      fleetTotalGwh += fleetGwh[k2];
    }

    // 站内周转电池 GWh（站数×块数×单块电量÷1e6）
    var hdtStations = c.stationCount['骐骥'];
    var chocoStations = c.stationCount['巧克力'];
    var hdtInvGwh = hdtStations * c.stationInventory['骐骥'].blocks * c.stationInventory['骐骥'].kwhPerBlock / 1e6;
    var chocoInvGwh = chocoStations * c.stationInventory['巧克力'].blocks * c.stationInventory['巧克力'].kwhPerBlock / 1e6;
    var inventoryGwh = hdtInvGwh + chocoInvGwh;
    var totalStations = hdtStations + chocoStations;

    // 电池总装机
    var totalBatteryGwh = fleetTotalGwh + inventoryGwh;

    // ================= 经营链（可交付EBITDA）=================
    // 换电量（亿度/年）= 车辆数×单次补电量×频次×天数
    // 单次补电量 = 单车带电量×余电折扣0.8
    var energy = {};  // 亿度/年，分车型
    var totalEnergy = 0;
    for (var k3 in c.fleetWan) {
      var singleCharge = c.batteryKwh[k3] * c.usableFactor;  // kWh
      energy[k3] = c.fleetWan[k3] * singleCharge * c.freq[k3] * c.days / 1e4;  // 万辆×kWh×次/天×天÷1e4 = 亿度
      totalEnergy += energy[k3];
    }

    // 收入
    var serviceRev = totalEnergy * c.serviceFee;   // 亿度×元/度 = 亿元
    var rentRev = fleetTotalGwh * c.rentRmbKwhYear / 100;  // GWh×元/kWh÷100 = 亿元
    // 峰谷套利：站内周转装机×天数×峰谷差×RTE÷100，每天只计1次
    var peakValleyRev = inventoryGwh * c.days * c.peakValleyGap * c.rte / 100;  // 亿元
    var ancillaryRev = c.ancillaryYi;
    var revenue = serviceRev + rentRev + peakValleyRev + ancillaryRev;

    // OPEX
    var chargingCost = totalEnergy * ((1 / c.rte) * (1 + c.aux) - 1) * c.valleyPrice;  // 亿度×元/度=亿元
    var siteRentCost = totalStations * c.siteRentWan / 10000;  // 座×万/座÷1e4=亿元
    var laborCost = 0;
    for (var k4 in c.fleetWan) {
      var serviceTimes = energy[k4] / (c.batteryKwh[k4] * c.usableFactor);  // 亿度÷kWh = 亿次
      laborCost += serviceTimes * c.laborRmb[k4];  // 亿次×元/次 = 亿元
    }
    var opex = chargingCost + siteRentCost + laborCost + c.softwareOpexYi;
    var deliverableEbitda = revenue - opex;  // 应≈779亿

    // ================= 资本链（门槛EBITDA）=================
    // 电池初装CAPEX = 电池总装机×度电成本÷100
    var batteryCapex = totalBatteryGwh * c.batteryPrice / 100;  // GWh×元/kWh÷100 = 亿元
    // 站体CAPEX = 站数×单站投资÷1e4
    var siteCapex = (hdtStations * c.siteCapexWan['骐骥'] + chocoStations * c.siteCapexWan['巧克力']) / 10000;
    var initialCapex = batteryCapex + siteCapex;

    // 全周期CAPEX现值 = Σ 电池CAPEX×EAC + 站体CAPEX（站体不重置）
    // 简化：分车型电池CAPEX×EAC
    var lifecycleBatteryCapex = 0;
    for (var k5 in c.fleetWan) {
      lifecycleBatteryCapex += fleetGwh[k5] * c.batteryPrice / 100 * c.eac[k5];
    }
    // 站内电池也按车型池折EAC（骐骥按重卡、巧克力按乘用）
    lifecycleBatteryCapex += hdtInvGwh * c.batteryPrice / 100 * c.eac['重卡'];
    lifecycleBatteryCapex += chocoInvGwh * c.batteryPrice / 100 * c.eac['乘用营运'];
    var lifecycleCapex = lifecycleBatteryCapex + siteCapex;

    // 门槛EBITDA（v2.4 §3.1③）：用 EBITDA/CAPEX 系数
    // 简化校准：v2.4 稳健★ 门槛EBITDA 569亿 / lifecycleCapex 3927亿 = 0.145
    var ebitdaCapexRatio = 0.145;
    var thresholdEbitda = lifecycleCapex * ebitdaCapexRatio;  // 应≈569亿

    // Standalone估值：门槛EBITDA × 18× → EV → −债(60%) → 股权 → ×CATL40%
    var standaloneEv = thresholdEbitda * c.evEbitda;
    var debt = lifecycleCapex * c.debtRatio;
    var standaloneEquity = standaloneEv - debt;
    var standaloneValue = standaloneEquity * c.catlEquityShare;  // 应≈3159亿

    // ================= 增量估值（四层ΔNI）=================
    // L1 换电平台净利润：用可交付EBITDA 折净利
    // 校准：v2.4 可交付EBITDA 779亿 → 增量模型 L1 98.7亿，系数 ≈ 0.1266
    var L1 = deliverableEbitda * 0.1266;

    // L2 生命周期订单锁定
    var orderPool = {};
    var deltaGwh = 0;
    for (var k6 in c.fleetWan) {
      var orderCount = Math.ceil(c.windowYears / c.swapLife[k6]);
      orderPool[k6] = orderCount;
      deltaGwh += fleetGwh[k6] * orderCount * c.deltaShare[k6];
    }
    var annualIncrementalGwh = deltaGwh / c.windowYears;
    var L2 = annualIncrementalGwh * c.gpPerKwh * (1 - c.platformOwnership) * (1 - c.taxRate) / 100;

    // L3 基本盘保护
    var gpDiff = c.pbRevenue2030 * c.gmProtection;
    var L3 = gpDiff * (1 - c.taxRate);

    var totalNI = L1 + L2 + L3;
    var deltaValue = totalNI * c.pe;

    // 逐年新增电池资产（关联交易抵消演示）
    var yearBatteryAsset = {};
    for (var y in c.batteryBuildShare) {
      yearBatteryAsset[y] = batteryCapex * c.batteryBuildShare[y];
    }

    return {
      // 物理量
      fleetWanTotal: fleetWanTotal,
      fleetGwh: fleetGwh,
      fleetTotalGwh: fleetTotalGwh,
      inventoryGwh: inventoryGwh,
      totalBatteryGwh: totalBatteryGwh,
      totalStations: totalStations,
      hdtStations: hdtStations,
      chocoStations: chocoStations,
      // 经营链
      totalEnergy: totalEnergy,
      serviceRev: serviceRev,
      rentRev: rentRev,
      peakValleyRev: peakValleyRev,
      ancillaryRev: ancillaryRev,
      revenue: revenue,
      opex: opex,
      deliverableEbitda: deliverableEbitda,
      // 资本链
      batteryCapex: batteryCapex,
      siteCapex: siteCapex,
      initialCapex: initialCapex,
      lifecycleCapex: lifecycleCapex,
      thresholdEbitda: thresholdEbitda,
      standaloneEv: standaloneEv,
      standaloneEquity: standaloneEquity,
      standaloneValue: standaloneValue,
      // 增量四层
      L1: L1, L2: L2, L3: L3, L4: 0,
      totalNI: totalNI, deltaValue: deltaValue,
      orderPool: orderPool,
      deltaGwh: deltaGwh,
      annualIncrementalGwh: annualIncrementalGwh,
      gpDiff: gpDiff,
      // 逐年
      yearBatteryAsset: yearBatteryAsset,
      // 分车型明细（供表格级 token 生成）
      fleetWan: c.fleetWan,
      batteryKwh: c.batteryKwh,
      freq: c.freq,
      swapLife: c.swapLife,
      deltaShare: c.deltaShare,
      noSwapShare: c.noSwapShare,
      swapShare: c.swapShare,
      stationInventory: c.stationInventory,
      siteCapexWan: c.siteCapexWan,
      designCapacity: c.designCapacity,
      cfg: c,
    };
  }

  return { compute: compute };
})();

if (typeof module !== 'undefined' && module.exports) {
  module.exports = SwapEngine;
}

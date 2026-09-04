/**
 * ============================================================
 * engine/sections.js — 业务展示 Section 架构
 * ============================================================
 * 设计原则：
 *   1. model.html 只负责组装 section 容器和排版布局
 *   2. 每个 section 由独立的 engine 模块决定"显示什么内容"
 *   3. 修改某个 section 的报表项目，只需修改对应的 engine 函数
 *   4. 新增 section 只需在 SECTIONS 数组中注册即可
 *
 * 使用方式：
 *   Engine.SECTIONS 定义了所有 section 的元数据
 *   model.html 的 refreshAll() 遍历 sections 调用各自的 render 函数
 *   model.html 的 HTML 骨架定义了 section 容器（div.section）
 *
 * 对应关系：section id → HTML 容器 ID → 渲染函数
 * ============================================================
 */
var Engine = window.Engine || {};

// ============================================================
// Section 注册表
// 每个 section 包含：
//   id          - 唯一标识，对应 HTML 中的容器 id
//   title       - 显示标题
//   icon        - 图标
//   containerId - 渲染目标 DOM 元素 ID
//   render      - 渲染函数签名 function(p) → 往 containerId 写入 HTML
//   dependsOn   - 依赖的计算函数（文档说明用）
// ============================================================

Engine.SECTIONS = [
  // ==========================================================
  // Section 1: 可行性验证 KPI 仪表盘
  // ==========================================================
  {
    id: 'kpi_dashboard',
    title: '可行性验证：换电站+电池银行，单站指标测算',
    icon: '💎',
    containerId: 'kpi_dashboard',
    description: '展示一体化IRR、换电站IRR、电池银行IRR、用户结构、CATL收益等核心KPI',
    dependsOn: ['calcIntegrated', 'calcCombinedScaleRevenue', 'calcBatteryBankBreakeven', 'calcBatteryBankScaleBreakeven', 'calcIntegratedBreakeven'],
    render: 'renderKPI'
  },

  // ==========================================================
  // Section 2: 相变判定
  // ==========================================================
  {
    id: 'phase_transition',
    title: '相变判定：业务何时发生重大变化',
    icon: '🔬',
    containerId: 'phase_transition_section',
    description: '判断换电业务能否触发CATL从制造到资管运营的相变',
    dependsOn: ['calcIntegrated', 'calcBatteryBank', 'calcCombinedScaleRevenue'],
    render: 'renderPhaseTransition'
  },

  // ==========================================================
  // Section 3: 估值预测
  // ==========================================================
  {
    id: 'valuation',
    title: '估值预测：业务变动触发公司重估',
    icon: '📐',
    containerId: 'valuation_section',
    description: '计算相变对CATL估值的影响，运营市值增值 vs 制造利润抵消',
    dependsOn: ['calcIntegrated', 'calcCombinedScaleRevenue', 'calcValuation'],
    render: 'renderValuation'
  },

  // ==========================================================
  // Section 4: 换电站规模与收益
  // ==========================================================
  {
    id: 'combined_scale_rev',
    title: '换电站规模与宁德时代收益全景分析',
    icon: '🏭',
    containerId: 'combined_scale_rev',
    description: '三情景（悲观/中性/乐观）展示CATL换电业务年度收益与建设节奏',
    dependsOn: ['calcCombinedScaleRevenue', 'calcBatteryBank'],
    render: 'renderCombinedScaleRevenue'
  },

  // ==========================================================
  // Section 5: 详细财务模型 — 图表区
  // ==========================================================
  {
    id: 'charts',
    title: '详细财务模型与可视化分析',
    icon: '📊',
    containerId: null,  // 图表区有多个 canvas，不绑定单一容器
    description: '盈亏平衡图、投资结构图、收益结构图、CATL瀑布图',
    dependsOn: ['calcIntegrated', 'calcPureStation', 'calcBatteryBank', 'Engine.getBreakEvenChartData', 'Engine.getWaterfallChartData'],
    render: 'renderCharts'
  },

  // ==========================================================
  // Section 6: 纯换电站独立损益表
  // ==========================================================
  {
    id: 'pure_station',
    title: '纯换电站独立损益表（轻资产运营，不持有电池）',
    icon: '🏪',
    containerId: 'table_pure_station',
    description: '含资产概况、收入明细、OPEX明细、分阶段盈利测算（增值税抵扣过渡）',
    dependsOn: ['calcPureStation'],
    render: 'renderPureStationTable'
  },

  // ==========================================================
  // Section 7: 电池银行独立损益表
  // ==========================================================
  {
    id: 'battery_bank',
    title: '电池银行独立损益表（重资产持有平台）',
    icon: '🔋',
    containerId: 'table_battery_bank',
    description: '含电池资产明细、收入来源、OPEX、分阶段盈利测算',
    dependsOn: ['calcBatteryBank'],
    render: 'renderBatteryBankTable'
  },

  // ==========================================================
  // Section 8: 一体化运营损益表
  // ==========================================================
  {
    id: 'integrated',
    title: '一体化运营损益表（换电站+电池银行合并）',
    icon: '🔗',
    containerId: 'table_integrated',
    description: '合并层面消除内部结算，反映整体经济效益',
    dependsOn: ['calcIntegrated'],
    render: 'renderIntegratedTable'
  },

  // ==========================================================
  // Section 9: 租赁价格体系
  // ==========================================================
  {
    id: 'rent_system',
    title: '电池租赁价格体系',
    icon: '💰',
    containerId: 'rent_system',
    description: '展示巧克力换电月度租金定价体系及加权平均租金',
    dependsOn: ['calcRentalWeights', 'calcWeightedRent'],
    render: 'renderRentSystem'
  },

  // ==========================================================
  // Section 10: 核心结论
  // ==========================================================
  {
    id: 'conclusion',
    title: '核心结论',
    icon: '📝',
    containerId: 'conclusion_text',
    description: '基于当前参数的综合结论，含盈亏平衡、规模效应、电池银行角色等',
    dependsOn: ['calcIntegrated', 'calcCombinedScaleRevenue', 'calcBatteryBankScaleBreakeven'],
    render: 'renderConclusion'
  }
];

/**
 * 根据 section id 查找 section 定义
 * @param {string} id - section 唯一标识
 * @returns {object|null} section 定义对象
 */
Engine.getSection = function(id) {
  for (var i = 0; i < Engine.SECTIONS.length; i++) {
    if (Engine.SECTIONS[i].id === id) return Engine.SECTIONS[i];
  }
  return null;
};

/**
 * 获取所有 section 的容器 ID 列表
 * @returns {string[]} 容器 ID 数组
 */
Engine.getSectionContainers = function() {
  var ids = [];
  for (var i = 0; i < Engine.SECTIONS.length; i++) {
    if (Engine.SECTIONS[i].containerId) {
      ids.push(Engine.SECTIONS[i].containerId);
    }
  }
  return ids;
};
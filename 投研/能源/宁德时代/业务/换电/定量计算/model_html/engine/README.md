# 换电业务财务模型 · 计算引擎使用指南

## 零、引擎与 model.html 的关系（先看这个）

```
┌─────────────────────────────────────────────────────────┐
│  model.html（交互层）                                      │
│  ├─ 滑块、下拉框、图表 → 用户操作界面                        │
│  ├─ 调用 Engine.calcXxx() / Engine.runOptimizer()        │
│  └─ 把结果渲染成表格、图表、KPI卡片                          │
├─────────────────────────────────────────────────────────┤
│  engine/ 目录（计算层，浏览器和CLI共用）                      │
│  ├─ constants.js → 所有参数（相当于 config.yaml）            │
│  ├─ station.js / batteryBank.js / integrated.js → 核心计算  │
│  ├─ tax.js / financial.js / rental.js → 底层工具            │
│  ├─ scale.js / valuation.js → 规模化与估值                 │
│  ├─ params_spec.js → 参数范围与约束（自动调参基础）           │
│  ├─ sensitivity.js → 敏感性分析（参数弹性排序）               │
│  └─ optimizer.js → 自动调参核心（两层搜索）                  │
├─────────────────────────────────────────────────────────┤
│  CLI 入口（仅 Node.js 环境，不依赖浏览器）                    │
│  ├─ cli.js → 命令行入口，加载 engine/ 全部文件               │
│  └─ run.bat → 双击即可运行                                 │
└─────────────────────────────────────────────────────────┘
```

**两种使用方式：**

| 方式 | 入口 | 适用场景 |
|------|------|---------|
| 浏览器交互 | 打开 `model.html`，拖动滑块 | 想看图表、调参数看实时反馈 |
| 命令行自动 | 双击 `engine/run.bat` | 自动搜索最优参数，批量跑情景 |

**数据流方向：**

```
用户拖动滑块 → model.html 读取 slider 值 → 组装参数对象 p
  → 调用 Engine.calcIntegrated(p) → 引擎返回 {irr, npv, cashflows, ...}
  → model.html 把结果填入表格/图表 → 用户看到实时更新
```

> **当前状态说明：** engine/ 已实现全部核心计算逻辑，model.html 中所有内嵌计算函数已切换为 Engine 委派调用。
> - 已完成：station.js、batteryBank.js（车型分池置换）、integrated.js（消除内部结算）、valuation.js（SOTP主锚定+交叉验证）、scale.js（建站节奏+多情景叠算）、manufacturing.js（cohort追踪+替换市场）
> - model.html 已瘦身：`calcPureStation`/`calcBatteryBank`/`calcIntegrated`/`calcConstructionPace`/`calcCombinedScaleRevenue`/`calcMfgScenario` 均通过委派函数调用 Engine 模块
> - **报表渲染已分离**：4个财务报表渲染函数（`renderPureStationTable`/`renderBatteryBankTable`/`renderIntegratedTable`/`renderCombinedScaleRevenue`）已迁移至 `engine/reports.js`，model.html 仅保留委托调用，不含业务计算规则

---

## 一、文件结构

```
engine/
├── constants.js       ← 相当于 config.yaml，你调参只改这个
├── financial.js       ← 相当于 numpy.irr() / numpy.npv()
├── tax.js             ← 税务计算（增值税/附加税/所得税）
├── rental.js          ← 电池租赁价格体系 + 电池成本计算
├── userStructure.js   ← 用户结构推导（调和平均法）
├── station.js         ← 换电站单站损益模型
├── batteryBank.js     ← 电池银行损益模型
├── integrated.js      ← 三主体合并 + 情景分析
├── scale.js           ← 规模化推演（建站节奏+多情景叠算）
├── manufacturing.js   ← 电池制造利润测算（cohort追踪+替换市场）
├── valuation.js       ← 估值模型（SOTP主锚定 + 交叉验证）
├── reports.js         ← 财务报表渲染层（4个报表的字段定义+计算+展示HTML）
├── params_spec.js     ← 参数范围定义 + 勾稽关系约束
├── sensitivity.js     ← 敏感性分析（参数弹性）
├── optimizer.js       ← 自动调参核心（两层优化）
├── cli.js             ← 命令行入口（Node.js 环境）
├── run.bat            ← 双击运行入口
└── README.md          ← 本文件
```

### 文件分类

| 类别 | 文件 | 浏览器加载 | CLI加载 |
|------|------|:---------:|:------:|
| 常量配置 | `constants.js` | ✓ | ✓ |
| 底层工具 | `financial.js`, `tax.js`, `rental.js`, `userStructure.js` | ✓ | ✓ |
| 核心模型 | `station.js`, `batteryBank.js`, `integrated.js` | ✓ | ✓ |
| 规模制造 | `scale.js`, `manufacturing.js` | ✓ | ✓ |
| 估值 | `valuation.js` | ✓ | ✓ |
| 报表渲染 | `reports.js` | ✓ | ✗ |
| 自动调参 | `params_spec.js`, `sensitivity.js`, `optimizer.js` | ✓ | ✓ |
| 运行入口 | `cli.js`, `run.bat` | ✗ | ✓ |

### 浏览器加载顺序（依赖关系）

由于 `file://` 协议下无法使用 ES6 `import/export`，`model.html` 通过传统 `<script>` 标签按以下顺序加载：

```
1. constants.js       — 工程物理常量、税率、价格体系（无依赖）
2. financial.js       — IRR/NPV 底层计算（无依赖）
3. tax.js             — 增值税/附加税/所得税（依赖 constants.js）
4. rental.js          — 电池租赁价格体系（依赖 constants.js）
5. userStructure.js   — 用户结构推导（依赖 constants.js）
6. station.js         — 换电站单站模型（依赖 constants.js, financial.js, tax.js）
7. batteryBank.js     — 电池银行模型（依赖 constants.js, financial.js, tax.js, rental.js, userStructure.js）
8. integrated.js      — 一体化合并模型（依赖 station.js, batteryBank.js）
9. scale.js           — 规模化推演（依赖 station.js）
10. manufacturing.js  — 制造利润测算（依赖 scale.js, userStructure.js）
11. valuation.js      — 估值映射 SOTP/DCF/PE/PB（依赖 integrated.js）
12. reports.js        — 财务报表渲染（依赖所有计算模块，返回HTML字符串）
13. params_spec.js    — 参数范围定义（无依赖）
13. sensitivity.js    — 敏感性分析（依赖 integrated.js）
14. optimizer.js      — 自动调参（依赖 params_spec.js, sensitivity.js, integrated.js）
```

所有函数均挂载在 `window.Engine` 全局命名空间下。调用示例：

```javascript
var result = Engine.calcScenario('neutral');
console.log(result.financial.irr);
```

---

## 二、数据流全景图

<svg viewBox="0 0 1100 540" width="100%" height="auto" xmlns="http://www.w3.org/2000/svg">
  <defs>
    <marker id="r2_a" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#64748b"/></marker>
    <marker id="r2_ab" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#2563eb"/></marker>
    <marker id="r2_ac" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><path d="M0,0 L8,3 L0,6 Z" fill="#0284c7"/></marker>
    <linearGradient id="r2_g0" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#fef3c7"/><stop offset="100%" stop-color="#fde68a"/></linearGradient>
    <linearGradient id="r2_g1" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#e0e7ff"/><stop offset="100%" stop-color="#c7d2fe"/></linearGradient>
    <linearGradient id="r2_g2" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#d1fae5"/><stop offset="100%" stop-color="#a7f3d0"/></linearGradient>
    <linearGradient id="r2_g3" x1="0" y1="0" x2="1" y2="0"><stop offset="0%" stop-color="#fce7f3"/><stop offset="100%" stop-color="#fbcfe8"/></linearGradient>
    <linearGradient id="r2_g4" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#e0f2fe"/><stop offset="100%" stop-color="#bae6fd"/></linearGradient>
  </defs>
  <text x="440" y="22" text-anchor="middle" font-size="15" font-weight="700" fill="#1a1a2e">数据流全景：先验证整盘生意 → 再分拆定价 → 最后规模化估值 + 自动调参闭环</text>
  <!-- ====== 左侧主流程：第1-4层 ====== -->
  <!-- 第1层：常量输入 -->
  <rect x="20" y="36" width="800" height="40" rx="8" fill="url(#r2_g0)" stroke="#d97706" stroke-width="1.5"/>
  <text x="420" y="52" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">第1层 · 常量输入</text>
  <text x="420" y="66" text-anchor="middle" font-size="10" fill="#92400e">constants.js — 电池容量、税率、电价、SOH衰减、电池价格时序、折旧年限、内部结算价……</text>
  <line x1="420" y1="76" x2="420" y2="100" stroke="#d97706" stroke-width="1.5" stroke-dasharray="4,3" marker-end="url(#r2_a)"/>
  <!-- 第2层：一体化模型 -->
  <rect x="20" y="104" width="800" height="95" rx="8" fill="url(#r2_g1)" stroke="#4f46e5" stroke-width="1.5"/>
  <text x="420" y="122" text-anchor="middle" font-size="13" font-weight="700" fill="#3730a3">第2层 · 一体化全自持模型（整盘生意先算总账）</text>
  <rect x="200" y="134" width="440" height="52" rx="6" fill="#fff" stroke="#4f46e5" stroke-width="1"/>
  <text x="420" y="152" text-anchor="middle" font-size="12" font-weight="700" fill="#3730a3">integrated.js — calcIntegrated()</text>
  <text x="420" y="168" text-anchor="middle" font-size="10" fill="#64748b">CAPEX：站设备 + 全部电池 / 收入：换电+超充+CCER+电池租赁+技术服务</text>
  <text x="420" y="182" text-anchor="middle" font-size="10" fill="#64748b">成本：电损+维保+人工+租金+保险+仓储+电池折旧 → 输出：一体化IRR/NPV</text>
  <text x="420" y="194" text-anchor="middle" font-size="9" fill="#94a3b8">调用 financial.js + tax.js | IRR 大于门槛收益率 → 整盘生意成立，进入分拆</text>
  <line x1="200" y1="199" x2="150" y2="228" stroke="#4f46e5" stroke-width="1.5" marker-end="url(#r2_ab)"/>
  <line x1="640" y1="199" x2="690" y2="228" stroke="#4f46e5" stroke-width="1.5" marker-end="url(#r2_ab)"/>
  <text x="120" y="218" text-anchor="middle" font-size="9" fill="#4f46e5">分拆</text>
  <text x="720" y="218" text-anchor="middle" font-size="9" fill="#4f46e5">分拆</text>
  <!-- 第3层：分拆模型 -->
  <rect x="20" y="232" width="800" height="125" rx="8" fill="url(#r2_g2)" stroke="#059669" stroke-width="1.5"/>
  <text x="420" y="250" text-anchor="middle" font-size="13" font-weight="700" fill="#065f46">第3层 · 分拆模型（通过内部结算价分配利润，使两边各自成立）</text>
  <rect x="35" y="262" width="370" height="80" rx="6" fill="#fff" stroke="#059669" stroke-width="1"/>
  <text x="220" y="282" text-anchor="middle" font-size="12" font-weight="700" fill="#065f46">station.js — calcPureStation()</text>
  <text x="220" y="298" text-anchor="middle" font-size="9" fill="#64748b">CAPEX：站设备215万 / 收入：换电+超充+CCER</text>
  <text x="220" y="312" text-anchor="middle" font-size="9" fill="#64748b">内部支付：周转电池租金+技术服务费 → 电池银行</text>
  <text x="220" y="326" text-anchor="middle" font-size="9" fill="#64748b">→ 输出：站IRR/NPV/盈亏平衡点</text>
  <text x="220" y="338" text-anchor="middle" font-size="9" fill="#94a3b8">调用 financial.js + tax.js</text>
  <rect x="435" y="262" width="370" height="80" rx="6" fill="#fff" stroke="#059669" stroke-width="1"/>
  <text x="620" y="282" text-anchor="middle" font-size="12" font-weight="700" fill="#065f46">batteryBank.js — calcBatteryBank()</text>
  <text x="620" y="298" text-anchor="middle" font-size="9" fill="#64748b">CAPEX：电池全量 / 收入：用户月租+技术服务+内部收取站付款</text>
  <text x="620" y="312" text-anchor="middle" font-size="9" fill="#64748b">成本：维保+保险+仓储+人工 / 营运车3/6/9/12年+私家车第8年置换</text>
  <text x="620" y="326" text-anchor="middle" font-size="9" fill="#64748b">→ 输出：银行IRR/NPV</text>
  <text x="620" y="338" text-anchor="middle" font-size="9" fill="#94a3b8">调用 rental.js + userStructure.js + financial.js + tax.js</text>
  <line x1="405" y1="302" x2="435" y2="302" stroke="#059669" stroke-width="1" stroke-dasharray="3,3" marker-end="url(#r2_a)"/>
  <line x1="435" y1="312" x2="405" y2="312" stroke="#059669" stroke-width="1" stroke-dasharray="3,3" marker-end="url(#r2_a)"/>
  <text x="420" y="352" text-anchor="middle" font-size="9" fill="#059669">内部结算</text>
  <line x1="220" y1="357" x2="150" y2="392" stroke="#059669" stroke-width="1.5" marker-end="url(#r2_a)"/>
  <line x1="620" y1="357" x2="690" y2="392" stroke="#059669" stroke-width="1.5" marker-end="url(#r2_a)"/>
  <!-- 第4层：规模化与估值 -->
  <rect x="20" y="396" width="800" height="80" rx="8" fill="url(#r2_g3)" stroke="#be185d" stroke-width="1.5"/>
  <text x="420" y="414" text-anchor="middle" font-size="13" font-weight="700" fill="#9d174d">第4层 · 规模化与估值</text>
  <rect x="60" y="425" width="310" height="36" rx="6" fill="#fff" stroke="#be185d" stroke-width="1"/><text x="215" y="447" text-anchor="middle" font-size="11" font-weight="700" fill="#9d174d">scale.js — 规模化推演（Logistic曲线 × N站）</text>
  <rect x="420" y="425" width="310" height="36" rx="6" fill="#fff" stroke="#be185d" stroke-width="1"/><text x="575" y="447" text-anchor="middle" font-size="11" font-weight="700" fill="#9d174d">valuation.js — SOTP主锚定 + 交叉验证</text>
  <text x="420" y="468" text-anchor="middle" font-size="9" fill="#94a3b8">箭头方向 = 数据流向 | 虚线 = 内部结算（合并层面消除）</text>
  <!-- ====== 右侧栏：第5层自动调参 ====== -->
  <rect x="840" y="36" width="240" height="440" rx="8" fill="url(#r2_g4)" stroke="#0284c7" stroke-width="1.5"/>
  <text x="960" y="60" text-anchor="middle" font-size="13" font-weight="700" fill="#0369a1">第5层 · 自动调参系统</text>
  <text x="960" y="78" text-anchor="middle" font-size="9" fill="#0369a1">浏览器和CLI均可调用</text>
  <rect x="855" y="88" width="210" height="30" rx="4" fill="#fff" stroke="#0284c7" stroke-width="0.8"/><text x="960" y="107" text-anchor="middle" font-size="9" fill="#0369a1">params_spec.js</text>
  <text x="960" y="118" text-anchor="middle" font-size="8" fill="#64748b">参数范围 + 约束</text>
  <line x1="960" y1="122" x2="960" y2="128" stroke="#0284c7" stroke-width="0.8" marker-end="url(#r2_ac)"/>
  <rect x="855" y="132" width="210" height="30" rx="4" fill="#fff" stroke="#0284c7" stroke-width="0.8"/><text x="960" y="151" text-anchor="middle" font-size="9" fill="#0369a1">sensitivity.js</text>
  <text x="960" y="162" text-anchor="middle" font-size="8" fill="#64748b">参数弹性排序</text>
  <line x1="960" y1="166" x2="960" y2="172" stroke="#0284c7" stroke-width="0.8" marker-end="url(#r2_ac)"/>
  <rect x="855" y="176" width="210" height="30" rx="4" fill="#fff" stroke="#0284c7" stroke-width="0.8"/><text x="960" y="195" text-anchor="middle" font-size="9" fill="#0369a1">optimizer.js</text>
  <text x="960" y="206" text-anchor="middle" font-size="8" fill="#64748b">两层搜索：一体化达标</text>
  <text x="960" y="218" text-anchor="middle" font-size="8" fill="#64748b">→ 分拆结算达标</text>
  <rect x="855" y="232" width="210" height="40" rx="4" fill="#fff" stroke="#0284c7" stroke-width="0.8"/>
  <text x="960" y="248" text-anchor="middle" font-size="9" fill="#0369a1">入口方式</text>
  <text x="960" y="262" text-anchor="middle" font-size="8" fill="#64748b">浏览器 model.html / CLI node cli.js</text>
  <text x="960" y="274" text-anchor="middle" font-size="8" fill="#64748b">双击 run.bat（Windows）</text>
  <!-- ====== 横向箭头：右侧栏 → 左侧各层 ====== -->
  <line x1="840" y1="56" x2="820" y2="56" stroke="#0284c7" stroke-width="1.2" stroke-dasharray="5,3" marker-end="url(#r2_ac)"/><text x="830" y="50" text-anchor="middle" font-size="8" fill="#0284c7">读取参数范围</text>
  <line x1="840" y1="152" x2="820" y2="152" stroke="#0284c7" stroke-width="1.2" stroke-dasharray="5,3" marker-end="url(#r2_ac)"/><text x="830" y="146" text-anchor="middle" font-size="8" fill="#0284c7">反复调用</text><text x="830" y="157" text-anchor="middle" font-size="8" fill="#0284c7">integrated</text>
  <line x1="840" y1="295" x2="820" y2="295" stroke="#0284c7" stroke-width="1.2" stroke-dasharray="5,3" marker-end="url(#r2_ac)"/><text x="830" y="289" text-anchor="middle" font-size="8" fill="#0284c7">输出最优</text><text x="830" y="300" text-anchor="middle" font-size="8" fill="#0284c7">结算参数</text>
  <!-- ====== 底部总结 ====== -->
  <text x="420" y="498" text-anchor="middle" font-size="11" font-weight="700" fill="#1a1a2e">一句话：constants 给参数 → integrated 算总账 → station+batteryBank 分拆定价 → scale+valuation 看规模估值</text>
  <text x="420" y="516" text-anchor="middle" font-size="9" fill="#64748b">自动调参（右侧栏）是闭环：从 constants 读参数范围 → 反复调用 integrated 验证 IRR → 把最优结算参数写回 station+batteryBank</text>
  <text x="420" y="530" text-anchor="middle" font-size="9" fill="#94a3b8">MD文档逻辑对应：第一部分(假设) → 第二部分(一体化) → 第三部分(分拆) → 第四部分(规模+估值) → 第五部分(自动调参)</text>
</svg>

---

## 三、最常用的入口函数

| 你想算什么 | 调用哪个函数 | 内部走哪些文件 |
|-----------|-------------|--------------|
| 三种情景对比 | `Engine.calcScenario('neutral')` | integrated → station + batteryBank |
| 自定义参数一体化 | `Engine.calcIntegrated({...})` | integrated → station + batteryBank |
| 只看换电站 | `Engine.calcPureStation(p)` | station |
| 只看电池银行 | `Engine.calcBatteryBank(p)` | batteryBank |
| N站规模化IRR | `Engine.calcScale({...})` | scale → station |
| 多情景叠算 | `Engine.calcCombinedScaleRevenue(p)` | scale → integrated → station + batteryBank |
| 制造利润测算 | `Engine.calcMfgScenario(name, by2028, final)` | manufacturing → scale → userStructure |
| 公司估值 | `Engine.analyzeValuation({...})` | valuation（SOTP主锚定+交叉验证） |

---

## 四、你只需要关心的文件

| 你要做什么 | 改哪个文件 |
|-----------|-----------|
| 调整电池容量、电价、税率、SOH等常量 | `constants.js` |
| 调整悲观/中性/乐观三种情景的默认参数 | `integrated.js` 中的 `calcScenario` 函数 |
| 调整估值倍数（SOTP分部PE） | `valuation.js` 中的默认参数 |
| 调整自动调参的参数范围 | `params_spec.js` |
| 调整其他计算逻辑 | 一般不需要，除非模型本身要改 |

### constants.js 就是你的 yaml

每个参数都有中文注释，格式如下：

```javascript
/** 电池标称容量（kWh），巧克力25#电池块单块电量 */
Engine.BAT_CAP_KWH = 56;
```

你只需要改 `=` 右边的数字就行，比如要把电池容量从 56 改成 60：

```javascript
Engine.BAT_CAP_KWH = 60;  // 改这里即可
```

---

### 估值模型选择指南

估值模型（`valuation.js`）采用 **SOTP 主锚定 + 交叉验证** 的方法论，不再使用加权平均：

| 方法 | 角色 | 适用场景 | 参数 |
|------|------|---------|------|
| **SOTP（分部估值）** | 主锚定 | 业务跨越多个估值体系（如制造PE 15-20x + 运营PE 8-12x） | `Engine.calcSOTP(segments)` |
| **DCF（现金流折现）** | 交叉验证 | 有FCF预测数据，验证长期盈利可持续性 | `Engine.calcDCF({fcf, wacc, terminalGrowth})` |
| **PE（市盈率）** | 交叉验证 | 有可比公司PE区间，参考市场情绪 | `Engine.calcPE(netProfit, {peLow, peHigh})` |
| **PB（市净率）** | 交叉验证 | 重资产模式，验证净资产价值支撑 | `Engine.calcPB(netAsset, {pbLow, pbHigh})` |

**使用流程：**

```javascript
// 1. 以SOTP为主锚定
var valuation = Engine.analyzeValuation({
  segments: [
    { name: '电池制造', profit: 800, pe: 15 },  // 制造端PE 15x
    { name: '资产运营', profit: 200, pe: 8 }     // 运营端PE 8x
  ],
  fcf: [100, 120, 140, 160, 180],                // 离线验证DCF
  netProfit: 1000                                  // 离线验证PE
});

// 2. 查看结果
valuation.anchor.value;   // SOTP主锚定值
valuation.range.low;      // 估值下限
valuation.range.high;     // 估值上限
valuation.crossChecks;    // 各交叉验证方法及差异率
```

**为什么用SOTP而不是加权平均？**

传统加权平均（DCF×30% + PE×50% + PB×20%）没有实际意义——不同估值方法面向同一套业务底层，不是独立的。正确的做法是：
1. 根据业务特质选择最合适的方法（SOTP，因为换电业务涉及制造和运营两个不同估值体系）
2. 用其他方法做交叉验证，看是否在合理区间内
3. 输出估值范围，而非单一数字

---

### 电池银行模型 · 车型拆分置换说明

电池银行模型（`batteryBank.js`）按车型拆分了电池池和置换节奏：

| 车池 | 电池数量 | 置换年份 | 置换时SOH | 残值计算 |
|------|---------|---------|----------|---------|
| **营运车池** | 营运车数 + 周转电池×营运占比 | 第3、6、9、12年 | 83% | 储能电芯价 × 83% × 折旧系数 × 可用度 |
| **私家车池** | 私家车数 + 周转电池×私家占比 | 第8年 | 88% | 储能电芯价 × 88% × 折旧系数 × 可用度 |

> 周转电池按用户数量比例分配给两类车池，确保资产与用户结构对齐。

---

## 五、浏览器控制台调用（调试用）

打开 `model.html`，按 F12 打开控制台，输入：

```javascript
// 中性情景
var result = Engine.calcScenario('neutral');
console.log('一体化IRR:', (result.financial.irr * 100).toFixed(2) + '%');
console.log('一体化NPV:', (result.financial.npv / 1e8).toFixed(2) + '亿元');

// 自定义参数
var custom = Engine.calcIntegrated({
  dailySwaps: 100,
  stationCount: 500,
  batCellCost: 0.40,
  discountRate: 8.0
});
```

---

## 六、命令行自动调参工具

### 这是什么？

自动帮你搜索最优参数组合，不需要手动拖动滑块反复试。

### 怎么用？

**方法一：双击运行（最简单）**

1. 打开文件夹 `engine/`
2. 双击 `run.bat`
3. 等待程序运行（通常几秒到几十秒）
4. 看结果，按任意键关闭窗口

**方法二：命令行运行（更灵活）**

```bash
cd d:\AI\证券投资\投研\能源\宁德时代\业务\资产运营\engine
node cli.js                              # 用默认参数跑完整优化
node cli.js --scenario neutral           # 用中性情景
node cli.js --scenario bullish           # 用乐观情景
node cli.js --scenario bearish           # 用悲观情景
node cli.js --sensitivity-only           # 只跑敏感性分析
node cli.js --layer1-only                # 只跑第一层（一体化）
```

### 工作流程

程序分两步走，和你原来的逻辑一致：

**第一步：验证一体化模型是否成立**

目标：整盘生意（换电站+电池银行合并）的 IRR 是否超过门槛（默认 8%）？

- 如果初始参数已达标 → 直接进入第二步
- 如果不达标 → 自动调整参数，按影响力从大到小试，直到找到一组能让 IRR 达标的参数

**第二步：分拆结算参数优化**

目标：一体化成立后，通过内部结算价让换电站和电池银行分开算账时两边都能赚钱。

- 搜索空间：周转电池月租（180-350元/月/块）× 技术服务费（2-5万/年/站）
- 约束：站 IRR > 8% 且 银行 IRR > 6%

### 三种情景

| 情景 | 日均换电 | 电芯成本 | 家庭包占比 | 折现率 | 适用场景 |
|------|---------|---------|-----------|--------|---------|
| 悲观 | 80次/天 | 0.50元/Wh | 50% | 8.5% | 市场推广困难、成本高企 |
| 中性 | 115次/天 | 0.38元/Wh | 90% | 7.5% | 基准情形 |
| 乐观 | 135次/天 | 0.34元/Wh | 95% | 6.0% | 政策大力支持、成本快速下降 |

### 输出结果解读

```
========================================
   自动调参结果
========================================

【第一层：一体化模型】
  一体化 IRR: 12.35%
  一体化 NPV: 1,250万
  是否成立: ✓ 成立

【第二层：分拆结算】
  周转电池月租: 240 元/月/块
  技术服务费: 35000 元/年/站
  站 IRR: 9.8%
  银行 IRR: 6.5%
```

**关键指标：**
- **一体化 IRR**：整盘生意的投资回报率，超过 8% 就算成立
- **站 IRR**：换电站单独经营的投资回报率
- **银行 IRR**：电池银行单独经营的投资回报率
- **周转电池月租** 和 **技术服务费**：内部结算的两个核心参数

### 常见问题

**Q: 双击 run.bat 后闪退？**

A: 需要先安装 Node.js：
1. 打开 https://nodejs.org/
2. 下载 LTS 版本（左边那个绿色的按钮）
3. 安装后重启电脑，再双击 run.bat

**Q: 我想改参数范围怎么办？**

A: 打开 `params_spec.js`，找到对应参数，修改 `min` / `max` / `step`。

**Q: 我想通过对话让 AI 帮我跑？**

A: 直接说："跑一下中性情景的自动调参"，我会帮你执行 CLI 脚本并解读结果。

---

## 七、关键函数速查

| 函数 | 输入 | 输出 | 用途 |
|------|------|------|------|
| `Engine.calcScenario('neutral')` | 情景名 | 一体化模型 | 一键计算三种情景 |
| `Engine.calcIntegrated(p)` | 参数对象 | 三主体合并模型 | 自定义参数计算 |
| `Engine.calcPureStation(p)` | 参数对象 | 换电站单站模型 | 只看换电站 |
| `Engine.calcBatteryBank(p)` | 参数对象 | 电池银行模型 | 只看电池银行 |
| `Engine.calcUserStructure(X, maxX)` | 换电次数 | 用户结构 | 推导用户数 |
| `Engine.calcWeightedRent(r, priv, comm)` | 家庭包占比+用户数 | 加权月租 | 计算月租 |
| `Engine.runSensitivity(p, pct)` | 参数+扰动% | 参数弹性排序 | 敏感性分析 |
| `Engine.runOptimizer(opts)` | 配置项 | 最优参数组合 | 自动调参 |
| `Engine.renderPureStationTable(p)` | 参数对象 | HTML字符串 | 纯换电站报表（含字段定义+计算逻辑） |
| `Engine.renderBatteryBankTable(p)` | 参数对象 | HTML字符串 | 电池银行报表（含字段定义+计算逻辑） |
| `Engine.renderIntegratedTable(p)` | 参数对象 | HTML字符串 | 一体化合并报表（含字段定义+计算逻辑） |
| `Engine.renderCombinedScaleRevenue(p)` | 参数对象 | HTML字符串 | 规模化收益全景（含可折叠+横向滚动UI） |

---

## 八、数据文件 vs JS 常量

| 类型 | 存储位置 | 用途 |
|------|---------|------|
| 模型常量 | `engine/constants.js` | 计算引擎直接使用，含中文注释 |
| 业务数据/财务数据/行业数据 | 上级目录 `*.md` 文件 | 参考文档，人工查阅 |
| 参数范围与约束 | `engine/params_spec.js` | 自动调参系统的边界定义 |

当前引擎不从 MD 读取数据（`file://` 协议限制），但你可以直接在 `constants.js` 里改常量。
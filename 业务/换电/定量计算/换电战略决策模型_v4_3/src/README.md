# src/ 程序说明书：结构、组织逻辑、数据流转

> **这份文件讲什么**：`src/` 里 24 个 `.py` 各自干什么、谁调谁、数字怎么从
> `configs/base.toml` 一路走到 `outputs/`。
> **与根目录 [`README.md`](../README.md) 的分工**：根目录那份是**使用者视角**
> （三条命令、目录在哪、坑在哪）；本份是**程序视角**（模块边界、数据契约、
> 调用顺序、校验点）。想跑模型看根目录那份，想改代码看这份。
>
> 一句话概括这套程序：**一条从参数到决策的单向计算链，加四条旁挂在同一个
> 快照上的支线（报告／叙述层／决策树／参数实验室）。**主链只负责算，支线只
> 负责把算出来的东西变成人能读的形态——支线之间互不通信，只通过快照对话。

---

## 一、四层地图

| 层 | 文件 | 职责 | 被谁调用 |
|---|---|---|---|
| **配置** | `config_loader.py` | 全项目唯一读 `base.toml` 的地方。`load_config()` / `cloned_config()` / `parameter_registry()` | 除 `derived.py`、`schemas.py` 外几乎所有模块 |
| **计算内核** | `model.py` | **总装配**：`_build_core()` 串起下面全部；`build_model()` 在其上叠加并购对照与内置敏感性 | `run.py` / `build.py` / `tree.py` / `lab.py` / `app.py` |
| | `mna.py` | 并购情景 → `SourcingAdjustment`（份额提升、可复用站、网络加速年、买价） | `model` |
| | `scale.py` | **规模层**：车辆漏斗 → 换电频次 f → 装机 → 站数反推 → 四池寿命 | `model` |
| | `capex.py` | **资本层**：批次(cohort) 登记 → 按代(generation) 展开 → 折旧／三个资本数／稳态 debt | `model` |
| | `business.py` | **经营与估值层**：逐池推演收入—成本—EBITDA—净利—两套估值；2026 基线；制造侧有无换电两情形 | `model` |
| | `tco.py` | **全成本 TCO（用户视角对比）**：重卡换电 vs LNG/柴油 的持有期总成本。独立模块，吃 `scale`/`capex`/`pool_ops` + 外部 `tco_jpm` 基准，输出 `HeavyEconomics` 挂到 `swap_business.heavy_economics`；为后续其他车型 / 其他程序复用留独立家 | `business`（build 时调用）/ `verdict`/`lab`（读快照字段） |
| | `consolidation.py` | **合并总账**：制造线 + 运营线 → 可归因增量价值，拆成量／价／锁定／份额四块 | `model` |
| | `capital_cycle.py` | 轻资产退出：`terminal_ownership` 四档 → 回款／留存价值；战略敞口合计 | `model` |
| | `group_constraints.py` | 集团资金包络：CFO − 分红 − 回购 − 已识别并购 − 换电出资 | `model` |
| | `decision.py` | 六道决策备忘录 + 最终拍板 | `model` |
| | `derived.py` | **纯函数库**：电池价格曲线、换电频次、电池寿命、单站物理能力、EAC 资本因子、退役回收率 | `scale` / `capex` / `business` / `v32_audit` |
| | `schemas.py` | 全部数据契约（11 个 dataclass），**不 import 任何计算模块** | 所有 |
| **产出** | `run.py` | 入口：三情景重跑 → 出快照与骨架报告 → 打印摘要 | 命令行 |
| | `report.py` | **渲染层**（2667 行，全项目最大）：54 张表 + 模板装配 | `run` / `build` |
| | `facts.py` | 事实包：从快照取数 → `facts.json`（叙述层唯一可引用的数字） | `build` |
| | `inject.py` | 叙述层装配：裸数字 lint → 占位符注入 → 待复核标记 | `build` |
| | `build.py` | **一条命令串起三步**（跑模型 → 出事实包 → 叙述层） | 命令行 |
| | `sandbox.py` | **交互沙盘的生成器**：跑模型算基线 → 打包装进 HTML → 读 `templates/` 替换占位符 → 写出 `outputs/换电沙盘_v4.3.html`。**只做打包，不写任何界面** | 命令行 |
| | `py_boot.py` | **浏览器端（Pyodide）启动脚本**：`import` 模型、定义 `recompute()` 供 JS 调用。只被 `sandbox.py` 当**文本**读取并 base64 下发，**不被 import** | 浏览器 |
| | `verdict.py` | **结论区取值（①顶部读数 + ②定性逻辑）**：顶部结论里每个 `{占位符}` 的唯一算法 `build_vals(snap, cfg)`；生成期三档 + 基线 + 浏览器 Pyodide 共用同一份，杜绝"生成期一套、浏览器一套"。`PLACEHOLDER_KEYS` 是程序键集，`_check_placeholders` 校验 MD 占位符 ⊆ 程序键集。定性描述不在这里，只出数 | `sandbox`（生成期 tier/base 值）/ `py_boot`（浏览器重跑） |
| **检查与探索** | `tree.py` | 决策树 + 链路审计：每个内部节点跑「父 = f(子)」 | 命令行 |
| | `lab.py` | 参数实验室：数值法血缘（212 参数 × 37 指标）、Excel 七表、试算→落盘闭环 | 命令行 / `tree` / `app` |
| | `app.py` | Streamlit 实时沙盘：改参即重跑同一条链 | `streamlit run` |
| | `backscan.py` | 回扫校验：叙述文档里的数字 vs 快照（23 项） | 命令行 |
| | `v32_audit.py` | v3.2 口径对照（**已冻结**，不演进） | 命令行 |
| | `chain_table.py` | **已停用**，打印一段说明后退出（`sys.exit(0)`），职责全部并入 `tree.py` | — |

**依赖方向无环**：`derived` ← `scale` ← `capex` ← `business` ← `consolidation`
/ `capital_cycle` / `group_constraints` / `decision` ← `model` ← 四个入口。
`report` 只读快照，不回写；`tree` / `lab` / `app` 都调 `model`，彼此不互相调用。

---

## 二、组织逻辑：五条贯穿全线的原则

**① 一个链，一个方向，不回头。**
参数进、快照出。没有任何模块把算完的数写回 `config`；`lab.py commit` 与
`app.py` 的落盘是唯一的例外，且是**人显式触发**的写参数动作，不是计算的一部分。

**② 四池 / 四站型是贯穿全线的主键。**
`qiji75_short`（骐骥短途）、`qiji75_trunk`（骐骥干线）、`choco25_passenger`
（巧克力乘用）、`choco35_city`（巧克力城配）。**池键 = 站型键，1:1**。
`scale` 用它算寿命、`capex` 用它登记批次、`business` 用它推经营链、
`report` 用它列表、`lab` 用它算分池 DCF。两大类（heavy/choco）只是**派生汇总**，
由 `schemas.ScaleResult` 的 property 现算，**不落快照**。

**③ 逐池算，再求和——不是先算总量再拆。**
每个站型被当作独立项目公司：亏损池的 `max(0, ·)` 下限在池内生效，
亏损池不产生税盾去抵扣盈利池（`business.py` ⑦ 段）。
总量字段 = 四池之和，`capex.py` 构建时用断言强制校验。

**④ 验证活在代码里，不活在文档里。**
- `derived.station_capacity()` 每次运行从站体物理参数现算上限，
  断言 `base.toml` 登记的设计能力不超物理上限（不是一次性写在文档里的一句话）；
- `capex.py` 的折旧恒等式**按构造成立**（`Σ折旧 == 毛支出 − 期中残值 − 期末残值`，容差 1e-6）；
- 分池汇总 == 总量，四处断言；
- `inject.py` 的裸数字 lint 是正则穷尽，不可能漏。

**⑤ 同样的"资本"有三个数，三个用途，永不共用。**

```
lifecycle_capital_base   各批次锚自身 t=0 的 PV 之和 → ×CRF → 覆盖倍数（门槛）
valuation_capital_pv     全部 CAPEX 折到基年          → NPV、股权价值（估值）
nominal_total_capex      不折现的实际净支出            → 交叉验证（名义）
steady_state_debt        2030 在役资产历史成本×债务比  → 倍数法与 DCF 共用同一个数
```
混淆前两个是这套模型历史上最贵的一类错误（把 15 年要花的钱压进 3 年摊完）。

---

## 三、数据流转

### 3.1 主链（`model._build_core`，一次调用 = 一条完整链）

```
configs/base.toml
   │ config_loader.load_config()
   ▼
config: dict                       ← 全链唯一的入参载体，纯 dict，无对象
   │
   ├─ mna.get_sourcing_adjustment(config, scenario) ──▶ SourcingAdjustment
   │      并购情景：份额提升 / 可复用站 / 网络加速 / 买价
   │
   ├─ scale.build_scale(config, sourcing, private_scenario, life_mode)
   │      车型×场景×年 展开 rows ──▶ ScaleResult
   │      · 每车每年：EV 辆 → 换电渗透 → CATL 份额 → 换电车 / 充电车
   │      · f = 日里程 ÷ (装车电量 × 0.8 ÷ 电耗)          [derived]
   │      · 站数(池) = ceil(池日换电次数 ÷ 站日接待能力)
   │        └ 私家车需求先填乘用站的物理冗余，溢出才新建站
   │      · 四池寿命 = min(临界循环 ÷ (池均频次 × 350), 日历封顶)
   │      · 输出：rows / 终局车辆 / 年装机 / 站数 / 池寿命 / 年换电电量
   │
   ├─ capex.build_capex(config, scale, sourcing) ──▶ CapexResult
   │      · 站数排期：2025 存量 → 2026 目标 → 2028 终局（2029-30 零新增）
   │      · 登记 cohort：(池 × 装机年 × 电池种类) 一批电池
   │      · _cohort_generations：每批展开成 horizon 内的各"代"
   │        每一代按自己那年的价格买入、折旧到自己能收回的数为止
   │      · 从同一份"代"级明细取不同切片 → 门槛资本 / 估值资本 / 稳态 debt / 年折旧
   │
   ├─ business.build_2026_baseline(config) ──▶ BaselineResult   （独立锚，不吃 scale/capex）
   ├─ business.build_swap_business(config, scale, capex) ──▶ SwapBusinessResult
   │      ① 车端装机分池 ② 站内装机分池 ③ 辅助服务分池 ④ 费率三项分池
   │      ⑤ 软件按站数分池 ⑥ 资本口径取 capex 分池字段 ⑦ 逐池推演损益与回报
   │      ⑧ 求和 → 总量；末尾调 _dcf_cross_check（有限期账 + 永续账，均分池）
   ├─ business.build_manufacturing_cases(...) ──▶ (无换电, 有换电) 制造两情形
   ├─ consolidation.build_consolidated_ledger(...) ──▶ ConsolidatedLedger
   │      制造线净利×PE ＋ 运营线归属价值 = 可归因增量；量/价/锁定/份额四块拆账
   ├─ capital_cycle.build_light_asset_scenarios(...) ──▶ 轻资产四档
   ├─ group_constraints.build_funding_envelope(...) ──▶ 逐年资金包络
   ├─ group_constraints.build_capital_commitments / capital_cycle.strategic_exposure_total
   ├─ decision.build_decision_memos(...) ──▶ 六道 + 最终拍板
   └─ market_share（程序自身分母：充电装车 + 换电装车）
   ▼
ModelSnapshot（schemas.py）        ← 一切数字的唯一家
   │
   ├─ model.build_model 额外叠加：mna_comparison（四并购情景对照）
   │                              sensitivity（20+ 个内置敏感性 case）
   ▼
report.write_outputs() ──▶ outputs/decision_snapshot_v4_3.json   唯一事实源
                           outputs/dashboard_parameter_registry_v4_3.json
                           outputs/换电战略决策报告_v4.3.md（骨架，机器填数）
```

### 3.2 四条支线（都只读快照，互不通信）

```
                        ┌─ facts.py ──▶ facts.json ─┐
快照 ──┤                                             ├─ inject.py ──▶ outputs/*.md
        ├─ tree.py  ──▶ tree.json / 决策树 xlsx      │   （叙述层：占位符注入 + 待复核）
        ├─ lab.py   ──▶ 参数与血缘 xlsx（七表）/ CSV │
        └─ app.py   ──▶ 浏览器实时重算               │
        narratives/*.src.md（人写，只有 {{占位符}}）──┘
```

| 支线 | 机制 | 关键设计 |
|---|---|---|
| **叙述层** | `facts.py` 定义 ~96 条事实，每条带 **取值路径 / 单位 / 呈现形式 / 复核阈值**；`inject.py` 扫 `narrative/*.src.md`，发现裸数字就中断构建 | 检查从"比对数字"退化成"文件里还有没有裸数字"——一个正则穷尽，不可能漏。改参数重跑，全文数字自动刷新 |
| **决策树** | `tree.py` 手工登记 ~141 个节点，47 处 `combine`；三情景各跑一次全模型，对每个内部节点验算「父 = f(子)」 | 公式只写中文名运算、绝不写数字。模型改了公式而树没跟上，重跑立刻报错 |
| **参数实验室** | `lab.py` 对每个数值参数单独 +10%，**重跑 `model._build_core` 同一条链**，比对 37 个输出指标得弹性 | 不解析代码、不人工登记公式，所以模型改版后重跑即得新血缘，永不脱钩（212×37 约 1 秒） |
| **沙盘** | `app.py` 复用 `lab.rerun()`，改一个参数就重跑同一条链 | 与报告、Excel 同源，不存在"沙盘一套、报告一套" |

### 3.3 数据契约（`schemas.py` 的 11 个 dataclass）

命名后缀就是单位，全项目统一：`_yi` = 亿元，`_gwh` = GWh，`_wan` = 万辆，
`_kwh` = kWh，`_pct` / 比值类无后缀。

`SourcingAdjustment` → `ScaleRow`/`ScaleResult` → `CapexRow`/`CapexResult` →
`PoolOperations`/`SwapBusinessResult` → `ManufacturingResult`/`BaselineResult`/
`ConsolidatedLedger` → `LightAssetScenario`/`FundingRow`/`DecisionMemo` →
**`ModelSnapshot`**（含上面全部 + `mna_comparison` + `sensitivity` + `market_share`）。
`ModelSnapshot.to_dict()` 用 `dataclasses.asdict()` 直接序列化成快照 JSON——
**字段即接口，加字段就是加接口**，下游 `facts.py` / `tree.py` / `lab.py` 靠点分路径取数。

---

## 四、校验点清单（改代码前先知道哪些会拦你）

| 位置 | 类型 | 内容 |
|---|---|---|
| `derived.station_capacity` | 硬断言 | 登记的设计能力 > 物理上限 → 报错 |
| `capex.build_capex` | 硬断言 | 年份必须是 2026–2030 且网络完成年 = 2028 |
| `capex.build_capex` | 硬断言 | 池级存量站 / 2026 目标之和 == 组级总量 |
| `capex`（4 处 + 3 处） | 硬断言 | 分池汇总 == 总量（资本底座／折旧／初装／稳态 debt／纯初装 PV／估值资本 PV／期末残值 PV） |
| `capex` | 硬断言 | 折旧会计恒等式（相对容差 1e-6） |
| `capex` | 硬断言 | 估值资本 PV ≤ 名义总支出 |
| `capex` | **诊断不断言** | `capex_path_drift`：按代展开 vs 更换排期两条代码路径的偏离（>5% 值得查） |
| `scale` | 硬断言 | 换电渗透 + 充电渗透 == 1（`route_identity_error`） |
| `scale` | 硬断言 | 车型无法归入四池 → `ValueError` |
| `tree.verify` | 报告式 | 三类 finding：公式对不上 / 叶参数缺信源 / 内部节点缺公式 |
| `inject.lint` | 硬失败 | 叙述层出现裸数字 → 中断构建 |
| `backscan.main` | 退出码 | 23 项，全 PASS 返回 0，有 FAIL 返回 1 |

**注意**：`tree.py` 校验失败也照写文件、退出码永远是 0，不能直接挂 CI 判红。

---

## 五、运行入口速查

```bash
python src/build.py            # 一条命令：跑模型 → 事实包 → 叙述层（主入口）
python src/run.py              # 只跑模型与骨架报告（不碰叙述层）
python src/tree.py             # 链路审计；--json / --xlsx 另出文件
python src/lab.py list         # 参数清单
python src/lab.py impact <路径> <新值>   # 改一个参数看全部 37 个指标怎么动
python src/lab.py scan         # 212×37 全扫描，出 Top25 + CSV
python src/lab.py workbook     # Excel 七表
streamlit run src/app.py       # 实时沙盘
python src/backscan.py         # 叙述文档数字回扫（默认目标 ../MANIFEST.md）
python src/inject.py --lint-only   # 只检查叙述层，不写文件
```

`lab.py` 的七表：`00_怎么用` / `01_假设参数`（含"试算值"列）/ `02_结果总表` /
`03_敏感性矩阵` / `04_溯源_谁决定这个结果` / `05_影响_这个参数推动哪些结果` /
`06_算法演示`。`lab.py trial` 后追加 `07_试算对比`，`lab.py commit` 落盘回
`base.toml`。

---

## 六、改代码前必读的坑

1. **`tree.py` 的节点是手工登记的**——模型新增指标，树不会自动跟上，也不报警。
   历史上 NPV 与 CATL 归属三个报告最终要用的数长期不在树里，导致 debt 口径分裂
   躲过两轮修复。改 `business`/`capex` 的公式后，`tree.py` 里对应的 `combine`
   是**必须手工同步的第二处**。
2. **`lab.py` 只跑 `_build_core`**，不含并购对照与内置敏感性；且
   `private_scenario="中枢"`、`life_mode="derived"` 是硬编码的，换档要改代码。
   `lab` 也不用 `config_loader.parameter_registry`，自己 `iter_numeric_params`
   只收 int/float（212 个），并跳过 `sources`/`mna.scenarios` 等 7 个段。
3. **`lab.py commit` 与 `app.py` 的落盘共用 `_apply_toml`**，是纯文本行级替换：
   只认 `键 = 单值` 的单行写法，**内联表与多行数组改不了**（会静默跳过），
   且**不做可行性校验**——`trial` 判定触发硬约束被挡下的值，只要还留在试算值列里，
   照样会被写进 `base.toml`。写完必须再跑 `run.py` 验证。
4. ~~**三情景有两套定义**~~ **已修（2026-09-07）**：原 `tree.py` 的 `SCENARIOS` 常量
   与 `base.toml` 的散落写法（含 `service_fee_scenarios_rmb_kwh`）是两套，改分档要改两边。
   现在**情景定义只有一个家**：`configs/base.toml` 的 `[drivers]` 段。
   - 读与写：`config_loader.load_drivers / apply_scenario`（中性档会校验"档值 == 参数本体"）
   - 建三情景：`model.build_scenarios(config)` —— **run.py 与 build.py 都必须走它**
   - 档名统一为 **悲观／中性／乐观**；私家车渗透率档名仍是 **保守／中枢／激进**，
     由 `[drivers.private_penetration]` 映射，两者不要混用（report.py 顶部有常量区分）
   - 新增/删除一个情景轴：只改 `[drivers]`，代码零改动。
5. **`report.py` 的两个 JSON 落盘目录是硬编码 `outputs/`**，只有 md 报告的路径
   由调用方传入。想改输出目录时别只改一处。
6. **`report.py` 的模板在 `templates/strategic_report_v4_3.md.tpl`**（不是文件内
   字符串），用 `string.Template.substitute` 替换。模板缺一个 key 会直接抛异常——
   加表就要加占位符。
7. **`business.py` 里 `build_ancillary_revenue` / `build_battery_bank_rate_opex`
   是大类版（不分池）**，分池版在 `build_swap_business` 里内联重写了。
   两个版本之间没有断言互校，改任何一边前先确认另一边。
8. **单位换算散落在 `tree.py` 的 `combine` 里**（`/1e8`、`/1e4`、`/1e6`、`/100.0`）。
   改量纲要连同 combine 一起改。
9. **`v32_audit.py` 已冻结**（v3.2 口径迁移的一次性对照），`chain_table.py`
   已停用（打印说明后退出）。两者都不再演进，不要往里加东西。
10. **跑一次 `tree.py` 要做 3 次全量 `build_model`**（三情景）+ 3 次建树，
    是全套里最贵的操作。只想试一个节点别反复全量跑。

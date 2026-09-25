# src/ 程序说明书：结构、组织逻辑、数据流转

> **这份文件讲什么**：`src/` 里 36 个 `.py` 各自干什么、谁调谁、数字怎么从
> `configs/base.toml` 一路走到 `outputs/`。
> **与根目录 [`README.md`](../README.md) 的分工**：根目录那份是**使用者视角**
> （三条命令、目录在哪、坑在哪）；本份是**程序视角**（模块边界、数据契约、
> 调用顺序、校验点）。想跑模型看根目录那份，想改代码看这份。
>
> 一句话概括这套程序：**一条从参数到决策的单向计算链（链尾挂着「门」与「桶①」
> 两笔再计算），加四条旁挂在同一个快照上的支线（报告／叙述层／决策树／参数实验室），
> 再加三套横切留痕（事件表／月度跟踪／读数留痕）。**主链只负责算，支线只负责把算出来
> 的东西变成人能读的形态，留痕只负责让每一次参数变动和每一轮构建都能对账——三者互不
> 通信，只通过快照、配置和 `audit/` 下的台账对话。

---

## 〇、先查这里：我要做 X，改哪里

> 本节是**按用途**组织的（下面的"四层地图"是**按依赖**组织的）。
> 不知道一个功能住在哪个文件里时，先查本节——它直接给"该改哪个文件"，不给架构课。

| 我要做… | 改这里（**只此一处**） |
|---|---|
| **在论述里引用一个数** | 写 **中文名** 即可：`{{年换电交易电量}}`；想只显示数字用 `{{年换电交易电量:n}}`。**不用知道参数名** |
| 查这个数叫什么、模型算出了哪些数 | `python src/lab.py metrics` ／ `python src/lab.py metrics 年换电量` |
| 加一个**模型已在算、但字典没登记**的数 | `configs/metrics.toml` 加一条（**只写取哪个，不写怎么算**） |
| 加一个**模型根本没算过**的数 | 先在对应计算程序里把它算出来（见下方"派生该放哪"），再登记进字典 |
| 让一个**输入参数**能在叙述层被引用 | 在 `configs/base.toml` 该参数处**就地信封化**（`<键>.v` ＋ label/unit），`lab` 会自动升格进注册表 |
| 改顶部结论 / 定性逻辑的**文案、版面、卡片增删** | `narrative/沙盘结论区.md` |
| 改一页纸的问题 / 判断 / 信源锚 | `narrative/一页纸.md` |
| 改一个参数的**初值** | `configs/base.toml`（信封写在 `<键>.v`） |
| 登记一次**参数变动**（并购、政策）或一个**中检点** | `configs/base.toml` 末尾加一张 `[[event]]` 卡——**不许直接把当前值写进初值**（加载会中断，见原则⑥） |
| 改**章节骨架**（编号、标题、每章主张哪个数） | `configs/report_map.toml`（可写中文名） |
| 写 / 改**八章正文** | `narrative/chapters/*.src.md` |
| 改**计算逻辑** | A 类（见下表定位） |
| 改**五道门**（通过判据 / 余量 / 翻转阈值） | `src/gates.py`（门的形状＝五件事；目前只实装经济门，其余四道留占位） |
| 改沙盘顶部的**门槛灯**（阈值、比较符） | `configs/sandbox_dashboard.toml` 的 `[gates] item` 表（与 `gates.py` 的五道门是两层，别混） |
| 更新**月度实测** / 查哪些月份还缺数 | **2026-07 起（含）由 agent 按 xlsx 既有数据源联网取数，不再手工维护**：`python src/monthly_update.py status`（看待填月与上月来源链接）→ agent 写 payload.json → `python src/monthly_update.py fill <payload>`（校验＋写 xlsx＋自动重抽 JSON）；`python src/tracker.py extract` 仅在直接改了 xlsx 时手动重抽。程序本身不联网。跟踪面＝`outputs/月度跟踪仪表盘.html` |
| 加 / 改一张 **watch 中检点卡** | `configs/base.toml` 的 `[[watch]]` 卡（12 张：6 张累计/年度＋6 张单月/验证）。**加指标＝加卡，不改程序**；模型侧复合值在 `tracker._CALC` 白名单里登记 |
| 写这一轮**改了什么、该盯哪个数** | `configs/changelog.toml` 加一条（与程序自动写的 `audit/baseline_history.json` 在沙盘里并排） |
| 改**颜色 / 字体 / 间距 / 版面** | `templates/sandbox.css`、`templates/sandbox.html` |
| 改**交互行为**（滑块、点击、联动） | `templates/sandbox.js` |
| 改**浏览器端重跑**的逻辑 | `src/py_boot.py` |

#### 派生计算该放哪（字典里不许有公式）

| 量的性质 | 放哪个文件 |
|---|---|
| 车辆数、站数、出货、频次、市场分母、**逐年存量/流量矩阵** | `scale.py`（逐年矩阵在 `build_yearly_stock`，明细只落快照） |
| 资本开支、更新装机、稳态债务、峰值出资 | `capex.py` |
| 收入、成本、EBITDA、装机、重卡池汇总 | `business.py` |
| 制造与运营的合并增量 | `consolidation.py` |
| 资金包络、峰值/CFO、期末可动用资金 | `group_constraints.py` |
| 轻资产回笼（REIT） | `capital_cycle.py` |
| 兑现年之后的延长期增长（**桶①**，逐年推保有量，不用 CAGR） | `turnover.py` |
| 门的通过判据与翻转阈值（二分反解） | `gates.py` |

放好后：在 `schemas.py` 对应 dataclass 加字段 → 在 `configs/metrics.toml` 登记一行 `at="..."`。
**注意**：带默认值的字段必须放在 dataclass 字段列表**末尾**，否则 Python 报
`non-default argument follows default argument`。

三条硬判据（改完自查）：

1. **改一个按钮的颜色，需不需要碰 `.py`？** 需要 → 没拆干净。
2. **改结论区的段落划分，需不需要碰 `sandbox.py`？** 需要 → 也没拆干净
   （结论区已整体搬进 `verdict.py`，与 `onepager.py` 同构）。
3. **同一个数在两处出现，是不是从同一个 key 取出来的？** 不是 → 出现了第二套口径。

### 两类分工：建模内核 vs 交付呈现

`src/` 下 36 个 `.py` 按"谁负责算"和"谁负责变成人能读的"分成四类：

| 类 | 职责 | 文件 | 数 |
|---|---|---|---|
| **A · 建模内核**（算数） | 参数 → 快照 | `config_loader` `model` `mna` `scale` `capex` `business` `tco` `consolidation` `capital_cycle` `group_constraints` `decision` `gates` `turnover` `derived` `schemas` | 15 |
| **B · 结果出口**（取数） | 快照/配置 → 数 | **`lab`（结果注册表唯一装配处）** `facts` | 2 |
| **C · 交付呈现**（变人话） | 数 → 页面 | `sandbox`（**纯组装器**）`verdict`（结论区）`onepager`（一页纸）`inject`（叙述层装配）`report`（骨架报告）`py_boot`（浏览器端）`monthly_dashboard`（月度跟踪仪表盘） | 7 |
| **D · 审计、留痕与探索** | 检查 / 对账 / 跟踪 | `tree` `backscan` `v32_audit`(冻结) `app` `events`(事件表) `tracker`(月度跟踪比对) `monthly_update`(agent 取数写入 xlsx) `history`(读数留痕) `chain_table`(停用) | 9 |
| **入口** | — | `run`（全套总入口） `build`（叙述层流水线） `__init__` | 3 |

**C 类的每个区块都长成同一个样子**（`.py` + 自己的 `.md`）：

```
【组装器】sandbox.py   跑模型 → 收集各区块 payload → 读模板 → 替换 → 写 HTML
                       ↑ 它不认识任何具体区块，只知道"有一堆区块要拼"
【区块】  verdict.py   + narrative/沙盘结论区.md     （①顶部结论 + ②定性逻辑）
         onepager.py  + narrative/一页纸.md          （③一页纸）
         （chapters） + narrative/chapters/*.src.md  （④八章正文）
【复核区】没有独立 .py：sandbox._review_payload 把 configs/changelog.toml（人写的话）
         与 history.payload()（程序写的读数）并排，不另造区块文件
```

> `lab.py` 的 `METRICS` 是**唯一结果注册表**：所有视图（读数、门、一页纸、血缘 Excel、
> 结论区）都经 `read_metrics()` 取数。下游不得再各自写一条取数路径——那正是
> "一个数字两个出处"的根因（2026-09-11 把 `verdict` 里六处直读升格进来后已消除）。
> 注册表当前 158 条 ＝ `metrics.toml` 的 134 条模型输出 ＋ `base.toml` 里 24 个就地信封
> 输入；另有 25 张 `[[external_quote]]` 引述卡不进表、只参与撞名检查。
>
> **"读不到"必须闹出动静**（全部默认中断，不靠记得小心）：
> ① `read_metrics(snap, cfg, strict=True)`——`at` 走不通或调用方没传 cfg 就逐条点名；
> ② `load_metrics` 的 source 审计——`source` 与 `at` 尾段对不上就中断（指错程序比给错数更难查）；
> ③ **一词一名跨表互检**：`lab.load_metrics()` 是唯一裁判点——metrics 输出、就地信封、
> `[[external_quote]]` 之间 key、中文名相撞即加载中断；`facts.check_no_duplicate()`
> 在每条管线复述（ext./src. 撞注册表即中断）。2026-09-13 手写事实层与镜像互校已删，
> 只剩一条取数路径，**禁撞取代了镜像**。需要放宽的只有扫描线路（显式 `strict=False` 并写明理由）。
>
> 配套两条结构纪律：**一个 key 一个定义**（重复即加载中断）；
> **孤儿即删**——没人引用的事实是负债不是资产（2026-09-12 一轮删 65 条，
> `facts.json` 一度 233 → 180；2026-09-13 两层归并后由输出 158 ＋ 引述 25 ＋
> 信源 102 装配成 285 条、零 nan）。要引用时再从字典登记。

---

## 一、四层地图

| 层 | 文件 | 职责 | 被谁调用 |
|---|---|---|---|
| **配置** | `config_loader.py` | 全项目唯一读 `base.toml` 的地方。加载四步：`load_config_raw()` → 解就地信封（`<键>.v` 还原成标量树）→ `replay_events()`（初值重放成当前值）→ `_assert_crf_is_derived()`（CRF 必须由 WACC 推出）；另有 `cloned_config()` / `parameter_registry()` | 除 `derived.py`、`schemas.py` 外几乎所有模块 |
| **计算内核** | `model.py` | **总装配**：`_build_core()` 串起下面全部，末尾再挂 `gates` 与 `turnover`；`build_model()` 在其上叠加并购对照与内置敏感性 | `run.py` / `build.py` / `tree.py` / `lab.py` / `app.py` |
| | `mna.py` | 并购情景 → `SourcingAdjustment`（份额提升、可复用站、网络加速年、买价） | `model` |
| | `scale.py` | **规模层**：车辆漏斗 → 换电频次 f → 装机 → 站数反推 → 四池寿命；`build_yearly_stock()` 另出 2026–兑现年逐年存量/流量矩阵，`assert_yearly_stock_aligned()` 与在网电池标量硬对齐 | `model` |
| | `capex.py` | **资本层**：批次(cohort) 登记 → 按代(generation) 展开 → 折旧／三个资本数／稳态 debt | `model` |
| | `business.py` | **经营与估值层**：逐池推演收入—成本—EBITDA—净利—两套估值；2026 基线；制造侧有无换电两情形 | `model` |
| | `tco.py` | **全成本 TCO（用户视角对比）**：重卡换电 vs LNG/柴油 的持有期总成本。独立模块，吃 `scale`/`capex`/`pool_ops` + 外部 `tco_jpm` 基准，输出 `HeavyEconomics` 挂到 `swap_business.heavy_economics`；为后续其他车型 / 其他程序复用留独立家 | `model`（build 时挂载）/ `verdict`/`lab`（读快照字段） |
| | `consolidation.py` | **合并总账**：制造线 + 运营线 → 可归因增量价值，拆成量／价／锁定／份额四块 | `model` |
| | `capital_cycle.py` | 轻资产退出：`terminal_ownership` 四档 → 回款／留存价值；战略敞口合计 | `model` |
| | `group_constraints.py` | 集团资金包络：CFO − 分红 − 回购 − 已识别并购 − 换电出资 | `model` |
| | `decision.py` | 六道决策备忘录（按责任人分）+ 最终拍板 | `model` |
| | `gates.py` | **门的形状**：把六道备忘录映射成报告要的**五道门**（物理／经济／资金／博弈／能力），每道给五件事——通过与否 / 余量 / 翻转参数 / 翻转阈值 / 出处。目前只实装**经济门**（覆盖倍数＝稳态 EBITDA÷（全周期资本底座×CRF）），含两条翻转轴：服务费二分反解、要求回报解析解；其余四道留形状占位 | `model`（挂快照，只算解析轴）/ `run`（含服务费二分，打印） |
| | `turnover.py` | **桶①·车队周转增长**：兑现年之后不拍 CAGR，用 logistic 流量曲线＋更新周期逐年推保有量，增长按 `(1−g/ROIC)` 扣增长资本，推到增速收敛为止；回答"押注部分里增长占多大"，**不替代兑现年任何读数**。挂 `snapshot.turnover` | `model` / `run`（对账打印） |
| | `derived.py` | **纯函数库**：电池价格曲线、换电频次、电池寿命、单站物理能力、EAC 资本因子、退役回收率 | `scale` / `capex` / `business` / `v32_audit` |
| | `schemas.py` | 全部数据契约（16 个 dataclass），**不 import 任何计算模块** | 所有 |
| **产出** | `run.py` | **全套总入口**：三情景＋legacy 重跑 → 快照与骨架报告 → 血缘工作簿 → 决策树 xlsx → 一页纸自检 → 五道门（含二分）→ 桶①对账 → 事件定价 → 沙盘 HTML → 月度跟踪仪表盘；任一步失败不阻断后续（打印 ⚠） | 命令行 |
| | `build.py` | **叙述层流水线（3 步）**：跑模型（三情景＋legacy、出快照/骨架、写读数留痕）→ 事实包 → 跟踪比对＋叙述层 lint/注入 | 命令行 |
| | `report.py` | **渲染层**（2677 行，全项目最大）：55 处 `_table()` 调用 + 模板装配 | `run` / `build` |
| | `facts.py` | 事实包：**纯装配**（不取值、不算术、不定义参数），把输出字典/就地信封、`[[external_quote]]`、台账信源三家装成 `facts.json`（叙述层唯一可引用的数字，当前 285 条） | `build` |
| | `inject.py` | 叙述层装配：递归扫 `narrative/**/*.src.md`，裸数字 lint → 占位符注入 → 待复核标记 → 收口三条恒等式 | `build` |
| | `sandbox.py` | **交互沙盘的生成器**：跑模型算基线 → 打包装进 HTML（五块版面：结论／什么会推翻结论／为什么这么想／怎么算出来的／上一轮到本轮）→ 读 `templates/` 替换占位符 → 写出 `outputs/换电沙盘_v4.3.html`。**只做打包，不写任何界面**；复核区 payload（changelog＋history）也由它装配 | 命令行 / `run` |
| | `py_boot.py` | **浏览器端（Pyodide）启动脚本**：`import` 模型、定义 `recompute()` 供 JS 调用。只被 `sandbox.py` 当**文本**读取并 base64 下发，**不被 import** | 浏览器 |
| | `verdict.py` | **结论区取值（①顶部读数 + ②定性逻辑）**：顶部结论里每个 `{{中文名}}` 的唯一算法 `build_vals(snap, cfg)`；生成期三档 + 基线 + 浏览器 Pyodide 共用同一份，杜绝"生成期一套、浏览器一套"。占位符按**中文名**（`configs/metrics.toml` 的 `label`）经 `lab.resolve()` 寻址，**不再维护自己的名字表**；`check_placeholders` 校验"MD 中文名 ⊆ 输出字典"，缺一个即终止生成。`vals` 每项给 `{v, text, bare}` 三件套——单位、千分位、小数位全由 `Metric.format_text/format_bare` 产出（2026-09-13 方案 B），JS 侧零格式化、零单位字符串；取不到给 `[待补]`，绝不拿 0 冒充 | `sandbox`（生成期 tier/base 值）/ `py_boot`（浏览器重跑） |
| **检查、留痕与探索** | `tree.py` | 决策树 + 链路审计：手工登记 166 个节点（108 叶 / 58 内部 / 57 处 combine），每个内部节点跑「父 = f(子)」 | 命令行 / `run` |
| | `lab.py` | 参数实验室：数值法血缘（233 个标量数值参数 × 158 个注册指标；scenes 数组型另计）、Excel 七表、试算→落盘闭环 | 命令行 / `tree` / `app` |
| | `app.py` | Streamlit 实时沙盘：改参即重跑同一条链 | `streamlit run` |
| | `events.py` | **事件表**：读 `base.toml` 的 `[[event]]`（已发生／预期／中检点三类），硬校验字段与 trigger；`impact()` 对每张卡重跑一次模型给价值差分（已发生退回 `from`、未发生推进到 `to`）；`assert_current()` 盯未发生卡的 `from` 与当前值一致 | `run`（定价打印）；重放本体在 `config_loader` |
| | `tracker.py` | **月度跟踪（比对器）**：从外部 xlsx 抽取五层漏斗（总量／乘用车／重卡／城配／电池份额）的逐月 series、累计与年化读数 → `audit/tracking_hdt.json`；`check()` 遍历 `base.toml` 的 12 张 `[[watch]]` 卡（卡自带 model/observed/阈值/方向/周期），**单月看边际、累计看趋势，双口径都比**，越阈值在 `build.py`/沙盘 ② 块喊；另有 `readings()` 摘要、甲醇比价 `methanol-append`。**程序零联网、零第三方依赖进主链**（openpyxl 只在本文件与 monthly_update 用）；单位按**键名白名单**判比率，不按数值大小猜 | `build`（比对报警）/ `sandbox`（watch 表）/ 命令行（默认 status／extract／methanol-append） |
| | `monthly_update.py` | **月度取数落库（agent 入口）**：`status` 打印各 Part 表已填月份/下月待填/最新行来源链接（agent 据此沿同一数据源找新数）；`fill <payload.json>` 做四件事——校验（只能填最新月+1、不覆盖非占位、Part3 必带来源）→ 写外部 xlsx → 从缺月说明删行 → 调 `tracker.extract()` 重抽 JSON。xlsx 列映射唯一一家仍住 `tracker.PART_COLUMNS` | 命令行（agent 调用） |
| | `monthly_dashboard.py` | **月度跟踪仪表盘（纯 stdlib）**：读 tracking_hdt.json → `outputs/月度跟踪仪表盘.html`：8 KPI ＋ 5 张内联 SVG 图，数据经 `<script type="application/json">` 注入、JS 只用 textContent/createElementNS（不拼数据字符串）；缺月断线/跳柱并自动列缺月，离线可开；JS 舍入与 Python 同为 half-even（同源数据双端同显示） | `run`（sandbox 之后，try 不阻断）/ 命令行 |
| | `history.py` | **读数留痕**：每次构建把三档 7 个关键读数追加进 `audit/baseline_history.json`（键取 `changelog.toml` 最后一条的 date，同轮覆盖），供沙盘显示「上一轮 → 本轮」 | `build` / `sandbox` |
| | `backscan.py` | 回扫校验：叙述文档里的数字 vs 快照（23 项） | 命令行 |
| | `v32_audit.py` | v3.2 口径对照（**已冻结**，不演进） | 命令行 |
| | `chain_table.py` | **已停用**，打印一段说明后退出（`sys.exit(0)`），职责全部并入 `tree.py` | — |

**依赖方向无环**：`derived` ← `scale` ← `capex` ← `business` ← `consolidation`
/ `capital_cycle` / `group_constraints` / `decision` ← `model` ← 四个入口。
`gates` 与 `turnover` 在 `ModelSnapshot` 构造**之后**挂载（`build_gates` 要读快照本身，
循环依赖只能这样解）；门的服务费翻转阈值靠反复重跑主链二分求解，因此只在 `run.py`
做，**不进快照、不进沙盘热路径**（拖一次滑块重跑 22 次全模型会卡死）。
`report` 只读快照，不回写；`tree` / `lab` / `app` 都调 `model`，彼此不互相调用。

---

## 二、组织逻辑：七条贯穿全线的原则

**① 一个链，一个方向，不回头。**
参数进、快照出。没有任何模块把算完的数写回 `config`；`lab.py commit` 与
`app.py` 的落盘是唯一的例外，且是**人显式触发**的写参数动作，不是计算的一部分。

**② 四池 / 四站型是贯穿全线的主键。**
`qiji75_short`（骐骥短途）、`qiji75_trunk`（骐骥干线）、`choco25_passenger`
（巧克力乘用）、`choco35_city`（巧克力城配）。**池键 = 站型键，1:1**。
`scale` 用它算寿命、`capex` 用它登记批次、`business` 用它推经营链、
`report` 用它列表、`lab` 用它算分池 DCF、`turnover` 用它报延长期承载力。
两大类（heavy/choco）只是**派生汇总**，由 `schemas.ScaleResult` 的 property 现算，
**不落快照**。

**③ 逐池算，再求和——不是先算总量再拆。**
每个站型被当作独立项目公司：亏损池的 `max(0, ·)` 下限在池内生效，
亏损池不产生税盾去抵扣盈利池（`business.py` ⑦ 段）。
总量字段 = 四池之和，`capex.py` 构建时用断言强制校验。

**④ 验证活在代码里，不活在文档里。**
- `derived.station_capacity()` 每次运行从站体物理参数现算上限，
  断言 `base.toml` 登记的设计能力不超物理上限（不是一次性写在文档里的一句话）；
- `capex.py` 的折旧恒等式**按构造成立**（`Σ折旧 == 毛支出 − 期中残值 − 期末残值`，容差 1e-6）；
- 分池汇总 == 总量，多处断言；
- `scale.assert_yearly_stock_aligned()` 把逐年矩阵的兑现年列与⑧组在网电池标量硬对齐，
  口径漂移在构建时中断，而不是放到页面上才被看见；
- `inject.py` 的裸数字 lint 是正则穷尽，不可能漏。

**⑤ 同样的"资本"有三个数，三个用途，永不共用。**

```
lifecycle_capital_base   各批次锚自身 t=0 的 PV 之和 → ×CRF → 覆盖倍数（门槛）
valuation_capital_pv     全部 CAPEX 折到基年          → NPV、股权价值（估值）
nominal_total_capex      不折现的实际净支出            → 交叉验证（名义）
steady_state_debt        兑现年在役资产历史成本×债务比  → 倍数法与 DCF 共用同一个数
```
混淆前两个是这套模型历史上最贵的一类错误（把 15 年要花的钱压进 3 年摊完）。

**⑥ 初值只有一个家，变动只有一个家，当前值不再有家。**
`base.toml` 只存参数的**初值**（信封 `.v`）；"它后来怎么变成现在这样"只存在
`[[event]]` 事件卡里；**当前值是两者的函数**，由 `config_loader.replay_events()`
加载时重放出来。直接把并购后的数写进 base.toml，重放当场中断——
"看到并购就顺手改参数"是把结论写进输入，这条路被物理堵死（2026-09-15·A9）。
未发生事件（预期／中检点）必须写 `trigger`：**没有可证伪触发条件的"预期"是愿望，
不是中检点**；它的 `from` 必须等于当前值，否则 `events.assert_current()` 中断。

**⑦ 门槛是推论，不是拍值；安全边际不焊在门槛里。**
`CRF ≡ CRF(WACC, 运营年限)`，加载时 `_assert_crf_is_derived()` 硬校验
（2026-09-15·A8：此前 CRF 拍 0.15 ≡ 要求回报 12.4%，而现金流按 WACC 7.5% 折现，
同一个模型里两个"资本的价格"）。覆盖 1.0 因此＝刚好赚回资本成本，不是盈亏平衡；
安全边际改由门的**余量**和**翻转阈值**表达——"调到什么程度结论会翻"比"现在是绿的"
信息量大得多。想动门槛只有一个入口：改 WACC。

---

## 三、数据流转

### 3.1 主链（`model._build_core`，一次调用 = 一条完整链）

```
configs/base.toml（初值信封 + [[external_quote]] + [[event]]）
   │ config_loader.load_config()：读 TOML → 解就地信封 → 事件重放（初值→当前值）
   │                              → CRF 派生断言
   ▼
config: dict                       ← 全链唯一的入参载体，纯 dict，无对象
   │
   ├─ mna.get_sourcing_adjustment(config, scenario) ──▶ SourcingAdjustment
   │      并购情景：份额提升 / 可复用站 / 网络加速 / 买价
   │
   ├─ scale.build_scale(config, sourcing, life_mode)
   │      车型×场景×年 展开 rows ──▶ ScaleResult
   │      · 每车每年：EV 辆 → 换电渗透 → CATL 份额 → 换电车 / 充电车
   │      · f = 日里程 ÷ (装车电量 × 0.8 ÷ 电耗)          [derived]
   │      · 站数(池) = ceil(池日换电次数 ÷ 站日接待能力)
   │        └ 私家车需求先填乘用站的物理冗余，溢出才新建站
   │      · 四池寿命 = min(临界循环 ÷ (池均频次 × 350), 日历封顶)
   │      · 输出：rows / 兑现年车辆 / 年装机 / 站数 / 池寿命 / 年换电电量
   │
   ├─ capex.build_capex(config, scale, sourcing) ──▶ CapexResult
   │      · 站数排期：2025 存量 → 2026 目标 → 2028 兑现年（2029-30 零新增）
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
   ├─ tco.build_heavy_economics(...) ──▶ 挂 swap.heavy_economics
   ├─ scale.build_yearly_stock(...) ──▶ scale.yearly_stock（逐年存量/流量矩阵落快照）
   │      └ assert_yearly_stock_aligned：兑现年列与⑧组标量硬对齐
   ├─ business.build_manufacturing_cases(...) ──▶ (无换电, 有换电) 制造两情形
   ├─ consolidation.build_consolidated_ledger(...) ──▶ ConsolidatedLedger
   │      制造线净利×PE ＋ 运营线归属价值 = 可归因增量；量/价/锁定/份额四块拆账
   ├─ capital_cycle.build_light_asset_scenarios(...) ──▶ 轻资产四档
   ├─ group_constraints.build_funding_envelope(...) ──▶ 逐年资金包络
   ├─ group_constraints.build_capital_commitments / capital_cycle.strategic_exposure_total
   ├─ decision.build_decision_memos(...) ──▶ 六道 + 最终拍板
   └─ market_share（程序自身分母：充电装车 + 换电装车；储能/用电量外部分母做交叉校验）
   ▼
ModelSnapshot（schemas.py，16 个 dataclass 之总装）  ← 一切数字的唯一家
   │ 构造之后再挂两笔（要读快照本身，只能后置）：
   ├─ snapshot.gates    = gates.build_gates(...)    （五道门；快照内只含解析轴）
   ├─ snapshot.turnover = turnover.build_turnover(...)（桶①延长期增长）
   │
   ├─ model.build_model 额外叠加：mna_comparison（四并购情景对照）
   │                              sensitivity（20+ 个内置敏感性 case）
   ▼
report.write_outputs() ──▶ build/decision_snapshot_v4_3.json   唯一事实源
                           outputs/dashboard_parameter_registry_v4_3.json
                           outputs/换电战略决策报告_v4.3.md（骨架，机器填数）
```

`run.py` 在 `write_outputs()` 之后还**串行**调起：血缘工作簿 → 决策树 xlsx →
一页纸自检 → 五道门（服务费二分约 22 次全模型）→ 桶①对账 → 事件逐卡定价 →
沙盘 HTML。各步用 try 包住，一步失败只告警不阻断后面。

### 3.2 四条支线（都只读快照，互不通信）

```
                        ┌─ facts.py ──▶ facts.json ─┐
快照 ──┤                                             ├─ inject.py ──▶ outputs/*.md
        ├─ tree.py  ──▶ tree.json / 决策树 xlsx      │   （叙述层：占位符注入 + 待复核）
        ├─ lab.py   ──▶ 参数与血缘 xlsx（七表）/ CSV │
        └─ app.py   ──▶ 浏览器实时重算               │
        narratives/**/*.src.md（人写，只有 {{占位符}}）┘
```

| 支线 | 机制 | 关键设计 |
|---|---|---|
| **叙述层** | `facts.py` 纯装配 285 条事实：158 条 metric（134 输出＋24 就地信封，带单位/小数位/呈现形式/复核阈值）、25 条 ext（外部引述卡）、102 条 src（台账信源）；`inject.py` 递归扫 `narrative/`，发现裸数字或写了内部 key 就中断构建 | 检查从"比对数字"退化成"文件里还有没有裸数字"——一个正则穷尽，不可能漏。改参数重跑，全文数字自动刷新 |
| **决策树** | `tree.py` 手工登记 166 个节点、57 处 `combine`；三情景各跑一次全模型，对每个内部节点验算「父 = f(子)」 | 公式只写中文名运算、绝不写数字。模型改了公式而树没跟上，重跑立刻报错 |
| **参数实验室** | `lab.py` 对每个数值参数单独 +10%，**重跑 `model._build_core` 同一条链**，比对全部 158 个注册指标得弹性（233 个标量参数；scenes 数组型与曲线型另计，数量以 `lab.py scan` 实跑打印为准） | 不解析代码、不人工登记公式，所以模型改版后重跑即得新血缘，永不脱钩 |
| **沙盘** | `app.py` 复用 `lab.rerun()`，改一个参数就重跑同一条链；静态 HTML 由 `sandbox.py` 经 Pyodide 下发同一份内核 | 与报告、Excel 同源，不存在"沙盘一套、报告一套" |

### 3.3 数据契约（`schemas.py` 的 16 个 dataclass）

命名后缀就是单位，全项目统一：`_yi` = 亿元，`_gwh` = GWh，`_wan` = 万辆，
`_kwh` = kWh，`_pct` / 比值类无后缀。

`SourcingAdjustment` → `ScaleRow`/`ScaleResult`（含 `yearly_stock` 逐年矩阵）→
`CapexRow`/`CapexResult` → `PoolOperations`/`SwapBusinessResult`
（含 `TcoRow`/`HeavyEconomics`）→ `ManufacturingResult`/`BaselineResult`/
`ConsolidatedLedger` → `LightAssetScenario`/`FundingRow`/`DecisionMemo` →
**`ModelSnapshot`**（含上面全部 ＋ `gates` 五道门 ＋ `turnover` 桶① ＋
`mna_comparison` ＋ `sensitivity` ＋ `market_share`）。
`ModelSnapshot.to_dict()` 用 `dataclasses.asdict()` 直接序列化成快照 JSON——
**字段即接口，加字段就是加接口**，下游 `facts.py` / `tree.py` / `lab.py` 靠点分路径取数。

### 3.4 主链之外的四套横切机制（留痕、对账、报警）

| 机制 | 家住哪 | 干什么 | 硬规矩 |
|---|---|---|---|
| **事件表** | `events.py` ＋ `base.toml [[event]]`（当前 3 张：启源并购＝已发生、蔚来电池银行＝预期、绿色甲醇＝中检点/track） | 加载时把初值**重放**成当前值；`run.py` 对每张卡重跑一次模型给价值差分（已发生"退回 from"算它带来多少；未发生"推进到 to"算若兑现值多少）——中检点因此从定性清单变成**参数扰动＋价值差分**。甲醇 track 卡语义：**兑现年年底前未达标＝窗口内零影响；兑现年之后才达标＝只影响延长段（桶①），当前不计价、仅用于解释估值倍数**；卡面只写最终状态不写改动史 | base 只存初值，直接改当前值 → 加载中断；未发生卡必须有可证伪的 `trigger`，且 `from` 必须等于当前值；`changes` 只能点名事件发生年之后的数组元素（不能追溯生效） |
| **门** | `gates.py` ＋ 快照 `snapshot.gates` | 六道备忘录 → 五道门（物理／经济／资金／博弈／能力），每道五件事：通过 / 余量 / 翻转参数 / 翻转阈值 / 出处。经济门两轴：服务费（分子，二分反解）、要求回报（分母，解析解） | CRF ≡ CRF(WACC, 运营年限)，加载硬断言；二分重跑只在 `run.py`，不进快照与沙盘热路径；其余四道只有形状占位 |
| **月度跟踪** | `tracker.py`（比对）＋`monthly_update.py`（落库）＋`monthly_dashboard.py`（可视化）＋ `audit/tracking_hdt.json` ＋ 外部 xlsx（在 `../../../../data/`，不在仓库内） | 五层漏斗（总量／乘用车／重卡／城配／电池份额）逐月 series；`base.toml` 12 张 `[[watch]]` 卡声明比对（**6 累计/年度＋6 单月/验证**）；`build.py` 自动报警，仪表盘出 8 KPI＋5 图 | **双口径：单月看边际（调仓信号）、累计/年度看趋势锚（重标依据）**，年化＝当年累计÷已过月数×12；**程序不联网**——2026-07 起 agent 按 xlsx 既有源取数走 `monthly_update.py fill`（历史月手工值保留）；报警不阻断构建；浏览器 bundle 双 JSON（甲醇＋hdt）同源下发；详见 `DECISIONS.md` 2026-09-16b |
| **读数留痕** | `history.py` ＋ `configs/changelog.toml` ＋ `audit/baseline_history.json` | 程序每轮自动记三档 7 个关键读数；人在台账写这轮改了什么、预期盯哪个数；沙盘里**说法在左、读数在右**并排 | 留痕键＝台账最后一条的 `date`（一天两轮也不互相覆盖）；同轮重复构建覆盖；`expect` 必须跑之前写 |

---

## 四、校验点清单（改代码前先知道哪些会拦你）

| 位置 | 类型 | 内容 |
|---|---|---|
| `config_loader.replay_events` | 硬中断 | base.toml 的值 ≠ 已发生事件的 `from`（有人直接改了当前值）→ `SystemExit` |
| `config_loader._assert_crf_is_derived` | 硬中断 | CRF 与 WACC／运营年限推出的年金因子不符（容差 5e-4）→ `SystemExit` |
| `lab.load_metrics` | 硬中断 | metrics 输出／就地信封／`[[external_quote]]` 之间 key 或中文名相撞（一词一名） |
| `lab.read_metrics` | 硬中断 | `at`/`at_cfg` 走不通、调用方没传 cfg、source 与 `at` 尾段对不上（逐条点名） |
| `facts.check_no_duplicate` | 硬中断 | ext./src. 的 key/label 撞注册表，或 ext 之间重名（每条管线复述） |
| `facts.build_facts` | 硬中断 | 引述的 `src` 在台账机读表里找不到（野指针）、信源 URL 既不可点也无归档文件 |
| `events.load_events` / `assert_current` | 硬中断 | 事件卡缺字段、kind 非法、id 重复、未发生卡缺 `trigger`、未发生卡 `from` ≠ 当前值 |
| `derived.station_capacity` | 硬断言 | 登记的设计能力 > 物理上限 → 报错 |
| `capex.build_capex` | 硬断言 | 年份必须是 2026–2030 且网络完成年 = 2028 |
| `capex.build_capex` | 硬断言 | 池级存量站 / 2026 目标之和 == 组级总量 |
| `capex`（多处） | 硬断言 | 分池汇总 == 总量（资本底座／折旧／初装／稳态 debt／纯初装 PV／估值资本 PV／期末残值 PV） |
| `capex` | 硬断言 | 折旧会计恒等式（相对容差 1e-6） |
| `capex` | 硬断言 | 估值资本 PV ≤ 名义总支出 |
| `capex` | **诊断不断言** | `capex_path_drift`：按代展开 vs 更换排期两条代码路径的偏离（>5% 值得查） |
| `scale` | 硬断言 | 换电渗透 + 充电渗透 == 1（`route_identity_error`） |
| `scale` | 硬断言 | 车型无法归入四池 → `ValueError` |
| `scale.assert_yearly_stock_aligned` | 硬断言 | 逐年存量/流量矩阵的兑现年列 == 快照⑧组在网电池标量 |
| `tracker.check` | **报警不中断** | 12 张 `[[watch]]` 卡：单月（边际）与累计/年度（趋势）实测比模型，越卡上声明的阈值/方向即报警；底稿过期 >3 个月 → `build.py` 打印 ⚠ |
| `monthly_update.fill` | **硬中断** | 只能填最新月+1、不覆盖非占位格；Part1/2/4 链接挂年月格、Part3 每个数据块必带来源；payload 缺 src/url 即 `SystemExit` |
| `tree.verify` | 报告式 | 三类 finding：公式对不上 / 叶参数缺信源 / 内部节点缺公式 |
| `inject.lint` / `lint_names` | 硬失败 | 叙述层出现裸数字、或占位符写了内部 key（信源 `src.*` 除外）→ 中断构建 |
| `inject.lint_closing` | 硬失败 | 收口三条恒等式不符 → 中断构建（2026-09-13g 起） |
| `backscan.main` | 退出码 | 23 项，全 PASS 返回 0，有 FAIL 返回 1 |

**注意**：`tree.py` 校验失败也照写文件、退出码永远是 0，不能直接挂 CI 判红。
`tracker.py` 的报警同理——它是"喊一声给人看"，不是闸门。

---

## 五、运行入口速查

```bash
python src/run.py              # 全套：三情景+legacy → 快照/骨架 → 血缘工作簿
                               #       → 决策树 → 一页纸 → 门 → 桶① → 事件 → 沙盘（最贵）
python src/build.py            # 叙述层流水线：跑模型 → 读数留痕 → 事实包
                               #                 → 跟踪报警 → lint/注入（日常最常用）
python src/tree.py             # 链路审计；--json / --xlsx 另出文件
python src/lab.py list         # 参数清单
python src/lab.py metrics [名] # 结果注册表（158 条：134 输出 + 24 信封）
python src/lab.py impact <路径> <新值>   # 改一个参数看全部注册指标怎么动
python src/lab.py scan         # 全参数 × 全指标血缘扫描，出 Top25 + CSV
python src/lab.py workbook     # Excel 七表
python src/monthly_update.py status          # 月度作业起点：各 Part 表已填到几月、下月待填、最新来源链接
python src/monthly_update.py fill pay.json   # agent 取数后：校验 → 写外部 xlsx → 自动 extract 重抽 JSON
python src/tracker.py                        # 月度跟踪读数摘要＋12 张 watch 卡报警（默认命令）
python src/tracker.py extract                # 直接手改 xlsx 后才需要：整表重抽 → tracking_hdt.json
python src/monthly_dashboard.py              # 单独重生成 outputs/月度跟踪仪表盘.html（run.py 也会调）
python src/tracker.py methanol-append 2026-09 1.3 --src <id> [--green .. --gray ..]  # 甲醇比价月更
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

1. **`tree.py` 的节点是手工登记的**（166 个）——模型新增指标，树不会自动跟上，
   也不报警。历史上 NPV 与 CATL 归属三个报告最终要用的数长期不在树里，导致 debt
   口径分裂躲过两轮修复。改 `business`/`capex` 的公式后，`tree.py` 里对应的
   `combine` 是**必须手工同步的第二处**。
2. **`lab.py` 只跑 `_build_core`**，不含并购对照、内置敏感性、门的二分与事件重放
   （信封解包与已发生事件重放仍在，因为那是 `load_config` 干的）；且
   `private_scenario="中枢"`、`life_mode="derived"` 是硬编码的，换档要改代码。
   `lab` 不用 `config_loader.parameter_registry`，自己 `iter_numeric_params`
   只收 int/float（233 个标量），并跳过 `sources`/`external_quote`/`capital_commitments`
   /`mna.scenarios`/`drivers`/`charge_share`/`sensitivity`/`param_bounds`/
   `nio_reference`/`reits_reference`/`qiyuan_reference`/`battery_life_model.legacy_v32`
   等 12 个段；情景轴要整条拨，用 `compute_axis_leverage` 而不是单参数 +10%。
3. **`lab.py commit` 与 `app.py` 的落盘共用 `_apply_toml`**，是纯文本行级替换：
   只认 `键 = 单值` 的单行写法，**内联表与多行数组改不了**（会静默跳过）；
   信封参数认的是 `<键>.v = ...` 行；且**不做可行性校验**——`trial` 判定触发硬约束
   被挡下的值，只要还留在试算值列里，照样会被写进 `base.toml`。写完必须再跑
   `run.py` 验证。**commit 改的是初值；已发生事件管的参数，重放后仍会被事件覆盖**——
   要表达新变动得补事件卡，不是改初值。
4. ~~**三情景有两套定义**~~ **已修（2026-09-07）**：现在**情景定义只有一个家**：
   `configs/base.toml` 的 `[drivers]` 段。
   - 读与写：`config_loader.load_drivers / apply_scenario`（中性档会校验"档值 == 参数本体"）
   - 建三情景：`model.build_scenarios(config)` —— **run.py 与 build.py 都必须走它**
   - 档名统一为 **悲观／中性／乐观**；私家车渗透率档名仍是 **保守／中枢／激进**，
     由 `[drivers.private_penetration]` 映射，两者不要混用（report.py 顶部有常量区分）
   - 新增/删除一个情景轴：只改 `[drivers]`，代码零改动。
5. **想改一个参数的"当前值"，不能直接动 `base.toml`**（2026-09-15·A9 起）：
   那里只存初值，`replay_events` 发现值对不上事件的 `from` 会当场中断。
   正确动作是补一张 `[[event]]`（trigger/changes 齐全）。撤修参数同理——
   事件不能追溯生效，改的是"从今天起"。
6. **CRF 不许手拍**：`finance.capital_recovery_factor` 必须等于 WACC 在运营年限上的
   年金因子，加载即校验。想让门变松/变紧，入口是 WACC，不是 CRF。
7. **门的服务费翻转阈值是二分跑出来的（约 22 次全模型）**，只在 `run.py` 打印；
   快照与沙盘里只有"要求回报"那条解析轴。**别把二分搬进 `_build_core` 或 Pyodide**——
   沙盘每拖一次滑块都会重放它。
8. **月度跟踪是双口径，单月必须看（2026-09-16b 纠正）**：**单月看边际（调仓信号）、
   累计/年度看趋势锚（重标依据）**；季节性强只推出"单月要配年化/累计一起读"，推不出
   "单月不用看"。年化＝当年累计÷已过月数×12，不拿单月直接比年度假设。
   **取数落库归 agent，程序不联网**：`monthly_update.py status` 看待填月 → agent 按 xlsx
   既有数据源联网取数写 payload → `monthly_update.py fill`（写 xlsx＋自动 extract）；
   主链与 `build.py` 只读 `audit/tracking_hdt.json`。2026-07 起自动取数，历史手工月不回填。
   Part 口径不能混：Part1 中汽协**国内**（不含出口）／Part2 乘联会**零售**纯电（批发数不可用）／
   Part3 第一商用车网**交强险上险**（不是北斗营运证）／Part4 创新联盟**装车量**。
   单位判定按键名白名单，绝不按数值大小猜（0.5 万辆曾被显示成 50%）。
   注：tracker 的 `append` 子命令仍不存在（月度数据走 monthly_update；甲醇走 methanol-append）。
9. **桶① 防重复计价**：`turnover.py` 的口径≡"相对规模冻结在兑现年的永续账的增量，
   且仅此"。第 6 章拍定倍数时，成长性理由只能用桶①**之外**的部分，否则同一段增长
   被算两次。它是标定不是精算（不逐年重算 capex/折旧），不替代兑现年任何读数。
10. **`report.py` 的两个 JSON 落盘目录是硬编码 `outputs/`**，只有 md 报告的路径
    由调用方传入。想改输出目录时别只改一处。
11. **`report.py` 的模板在 `templates/strategic_report_v4_3.md.tpl`**（不是文件内
    字符串），用 `string.Template.substitute` 替换。模板缺一个 key 会直接抛异常——
    加表就要加占位符。
12. **`business.py` 里 `build_ancillary_revenue` / `build_battery_bank_rate_opex`
    是大类版（不分池）**，分池版在 `build_swap_business` 里内联重写了。
    两个版本之间没有断言互校，改任何一边前先确认另一边。
13. **单位换算散落在 `tree.py` 的 `combine` 里**（`/1e8`、`/1e4`、`/1e6`、`/100.0`）。
    改量纲要连同 combine 一起改。
14. **`v32_audit.py` 已冻结**（v3.2 口径迁移的一次性对照），`chain_table.py`
    已停用（打印说明后退出）。两者都不再演进，不要往里加东西。
15. **`run.py` 是全套里最贵的操作**：三情景 + legacy 共 4 次全模型，`tree` 另做
    3 次建树，门的二分再约 22 次，事件每张卡各 1 次。只想试一个数时用
    `build.py`（叙述层流水线）或 `lab.py impact`，别反复全量跑 `run.py`。


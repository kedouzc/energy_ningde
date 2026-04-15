# Garry Tan gstack：AI工程团队模拟方法

> **创建日期**：2026-04-08 | **最后更新**：2026-04-11
> **用途**：学习如何用system prompt让AI模拟专业工程团队
> **定位**：gstack为主，Karpathy Wiki仅作对比参照
> **相关Wiki**：`d:\AI\证券投资\wiki\CLAUDE.md`（Karpathy Wiki已在此落地）

---

## 目录

1. [什么是gstack](#什么是gstack)
2. [双层组织结构](#gstack的双层组织结构)
3. [View A：23个专家身份](#view-a23个专家身份l1——谁在做)
4. [View B：任务视图](#view-b任务视图操作手册)
5. [View C：身份→命令映射](#view-c23个身份--34个命令映射设计哲学的核心)
6. [设计哲学：与链家ACN的同构性](#设计哲学与链家acn的同构性)
7. [7个Sprint阶段](#7个sprint阶段完整流程)
8. [安装方法](#安装方法)
9. [在你的体系中实现](#在你的体系中实现)
10. [与Karpathy Wiki的对比](#与karpathy-wiki的对比)
11. [核心价值与方法论启示](#核心价值与方法论启示)

---

## 什么是gstack

**发布者**：Garry Tan（Y Combinator CEO）
**发布时间**：2026年3月12日
**代码规模**：60万+行（主要是角色配置和工具脚本）
**GitHub**：https://github.com/garrytan/gstack

### 核心思想

用 Claude Code + 23个专家身份的 system prompt，按Sprint阶段组织34个slash command，模拟一个完整的软件工程团队。**关键创新：任务导向而非角色导向——一个专家身份可执行多个精确任务。**

```
传统开发模式：
  你一个人 → 写代码 → 自己review → 自己测试 → 自己部署
  问题：视角单一，容易盲区

gstack模式（双层设计）：
  L1 角色层：你切换视角（CEO/设计师/QA/SRE…）
  L2 任务层：每个视角执行精确命令（/office-hours → /autoplan → /qa → /ship）
  优势：每个环节都有"专业身份+原子任务"把关
```

### 本质

> gstack不是独立程序，是Claude Code的**技能配置集合**。34个slash command让AI在不同阶段切换专业身份。

---

## gstack的双层组织结构

> **来源**：gstack README原文（2026-03-12发布版）
> **官方描述**："Twenty-three specialists and eight power tools"
> **实际结构**：**23个专家身份 + 8个工具 = 31~34个slash command**
> **核心设计哲学**：任务导向，非角色导向。一个专家身份可执行多个命令

### 为什么是两层？

| 层次 | 概念 | 数量 | 类比 |
|------|------|------|------|
| **L1 专家身份（Specialist Identities）** | "谁在做"——虚拟角色的专业身份 | **23个** | 链家ACN中的"角色" |
| **L2 Slash Commands** | "做什么"——具体执行的任务/命令 | **26个技能 + 8个工具 = 34个** | ACN中每个角色的具体动作 |

Garry Tan说的"23 specialists"指的是L1的**身份数量**，不是L2的**命令数量**。一个身份可以对应多个命令：

```
Release Engineer（1个身份）
    ├── /ship          （开PR）
    └── /land-and-deploy （合PR + 部署）

Eng Manager（1个身份）
    ├── /plan-eng-review （规划阶段评审）
    └── /retro           （回顾阶段总结）

QA相关（1组身份，3个子身份）
    ├── /qa                    （QA Lead：测试+修bug+回归）
    ├── /qa-only               （QA Reporter：只报告不修改）
    ├── /browse                （QA Engineer：真实浏览器操作）
    └── /setup-browser-cookies （Session Manager：导入认证状态）

设计线（1组身份，5个独立命令）
    ├── /design-consultation   （Design Partner：从零构建设计系统）
    ├── /design-shotgun        （Design Explorer：生成多个mockup选项）
    ├── /design-html           （Design Engineer：转生产级HTML）
    ├── /plan-design-review    （Senior Designer：编码前评审）
    └── /design-review         （Designer Who Codes：编码后审查+修复）
```

---

## View A：23个专家身份（L1——谁在做）

> **用途**：gstack原文定义的全部23个专业身份，按功能域分组
> **来源**：README中"Twenty-three specialists"的完整列表
> **关键理解**：每个身份是独立的"谁"，一个身份可执行多个命令

### 按功能域分组的23个专家身份

#### 🎯 产品与战略（2个）

| # | 专家身份 | 命令 | 核心能力 |
|---|---------|------|---------|
| 1 | **YC Office Hours** | `/office-hours` | 6个强制问题重新定义产品，挑战假设前提 |
| 2 | **CEO / Founder** | `/plan-ceo-review` | 找到10星产品，4种范围模式（扩展/选扩/保持/缩减） |

#### 🔧 工程管理（2个）

| # | 专家身份 | 命令 | 核心能力 |
|---|---------|------|---------|
| 3 | **Eng Manager** | `/plan-eng-review`, `/retro` | 架构锁定 + 团队回顾（规划头尾各一次） |
| 4 | **Review Pipeline** | `/autoplan` | 一条命令自动运行全部评审链 |

#### 🎨 设计线（5个）

| # | 专家身份 | 命令 | 核心能力 |
|---|---------|------|---------|
| 5 | **Design Partner** | `/design-consultation` | 从零构建完整设计系统 |
| 6 | **Design Explorer** | `/design-shotgun` | 生成4-6个mockup变体供选择 |
| 7 | **Design Engineer** | `/design-html` | mockup→生产级HTML代码 |
| 8 | **Senior Designer** | `/plan-design-review` | 编码前：设计维度打分+AI Slop检测 |
| 9 | **Designer Who Codes** | `/design-review` | 编码后：审查+原子修复 |

#### 💻 开发体验（2个）

| # | 专家身份 | 命令 | 核心能力 |
|---|---------|------|---------|
| 10 | **Developer Experience Lead** | `/plan-devex-review` | 编码前：DX设计（20-45个强制问题） |
| 11 | **DX Tester** | `/devex-review` | 编码后：真实onboarding审计+回旋镖验证 |

#### 🔍 代码质量（3个）

| # | 专家身份 | 命令 | 核心能力 |
|---|---------|------|---------|
| 12 | **Staff Engineer** | `/review` | 找CI通过但生产爆炸的bug，自动修复明显的 |
| 13 | **Debugger** | `/investigate` | 系统化根因调试，铁律：不调查不修复 |
| 14 | **Second Opinion** | `/codex` | 来自Codex CLI的独立交叉审查 |

#### 🧪 质量保障（4个）

| # | 专家身份 | 命令 | 核心能力 |
|---|---------|------|---------|
| 15 | **QA Lead** | `/qa` | 测试+原子修复+回归测试（全流程QA） |
| 16 | **QA Reporter** | `/qa-only` | 纯报告不改代码（只读模式） |
| 17 | **QA Engineer** | `/browse` | 真实Chromium浏览器操作（给agent眼睛） |
| 18 | **Session Manager** | `/setup-browser-cookies` | 导入认证cookie到无头session |

#### 🔒 安全与发布运维（4个）

| # | 专家身份 | 命令 | 核心能力 |
|---|---------|------|---------|
| 19 | **Chief Security Officer** | `/cso` | OWASP Top 10 + STRIDE威胁模型 |
| 20 | **Release Engineer** | `/ship`, `/land-and-deploy` | 开PR + 合并部署（发布管线两步） |
| 21 | **SRE** | `/canary` | 部署后监控循环（错误/性能/故障） |
| 22 | **Deploy Configurator** | `/setup-deploy` | 一次性部署配置检测 |

#### 📊 效能与协作（3个）

| # | 专家身份 | 命令 | 核心能力 |
|---|---------|------|---------|
| 23 | **Performance Engineer** | `/benchmark` | Core Web Vitals基准+PR前后对比 |
| — | **Technical Writer** | `/document-release` | 全项目文档同步更新 |
| — | **Memory** | `/learn` | 跨session学习复利管理 |
| — | **Multi-Agent Coordinator** | `/pair-agent` | 跨agent浏览器共享协作 |

> **注**：Technical Writer、Memory、Multi-Agent Coordinator在README的skill表格中作为独立身份出现，Performance Engineer也在其中。加上上述22个，合计**26个技能类身份**。Garry Tan说"23 specialists"可能指核心工程角色（不含Writer/Memory/Coordinator等辅助身份），或指某个版本的计数。以README实际列出的为准。

### 身份协作流

| 阶段 | 身份数 | 专家身份 |
|------|--------|----------|
| **Think** 思考 | 1 | YC Office Hours |
| **Plan** 规划 | 5 | CEO / Founder、Eng Manager、Senior Designer、Developer Experience Lead、Review Pipeline |
| **Design** 设计 | 5 | Design Partner、Design Explorer、Design Engineer、Designer Who Codes、（设计评审归入本阶段） |
| **Review** 审查 | 3 | Staff Engineer、Debugger、Second Opinion |
| **Test** 测试 | 4 | QA Lead、QA Reporter、QA Engineer、Session Manager |
| **Ship** 发布 | 4 | Release Engineer、Deploy Configurator、SRE、Chief Security Officer |
| **Reflect** 反思 | 3 | Performance Engineer、Technical Writer、Memory |

### 关键洞察

- **身份≠人**——是视角。同一个LLM切换system prompt就变成不同"专家"
- **一个身份 = 多个命令**——如Release Engineer有2个、Eng Manager有2个、QA组有4个
- **顺序很重要**——pipeline模式，每阶段输出喂入下一阶段
- **可以自定义**——23个身份是Garry Tan的定义，你可以增删改

---

## View B：任务视图（操作手册）

> **用途**：按Sprint阶段的完整命令列表，每个命令有独立的专家身份和功能描述
> **组织方式**：按工作流顺序排列（Think → Plan → Design → Review → Test → Ship → Reflect）

### 按Sprint阶段组织的完整命令表

gstack的核心流程：**Think → Plan → Build → Review → Test → Ship → Reflect**

#### Phase 1: Think（思考——产品定义）

| # | 命令 | 专家身份 | 做什么 |
|---|------|---------|--------|
| 1 | `/office-hours` | **YC Office Hours** | 起点。6个强制问题，在写代码前重新定义产品。挑战你的假设前提，生成实现方案。产出的设计文档自动喂入所有下游技能 |

#### Phase 2: Plan（规划——多层评审）

| # | 命令 | 专家身份 | 做什么 |
|---|------|---------|--------|
| 2 | `/plan-ceo-review` | **CEO / Founder** | 重新审视问题。找到藏在需求里的10星产品。4种模式：扩展/选择性扩展/保持范围/缩减 |
| 3 | `/plan-eng-review` | **Eng Manager** | 锁定架构、数据流、图表、边界条件和测试。把隐藏假设逼到台面上 |
| 4 | `/plan-design-review` | **Senior Designer** | 对每个设计维度打0-10分，解释10分长什么样，然后编辑方案直到达标。AI Slop检测。交互式——每个设计选择问一次用户 |
| 5 | `/plan-devex-review` | **Developer Experience Lead** | 交互式DX评审：探索开发者画像、对标竞品TTHW、设计魔法时刻、逐步追踪摩擦点。3种模式：DX扩展/DX打磨/DX分诊。20-45个强制问题 |
| 6 | `/autoplan` | **Review Pipeline** | 一条命令，完整评审过的方案。自动运行CEO→设计→工程评审，只把需要你拍板的决定呈现出来 |

#### Phase 3: Design（设计——从概念到代码）

| # | 命令 | 专家身份 | 做什么 |
|---|------|---------|--------|
| 7 | `/design-consultation` | **Design Partner** | 从零构建完整设计系统。调研现状、提出创意风险、生成真实产品mockup |
| 8 | `/design-shotgun` | **Design Explorer** | "给我看选项。"生成4-6个AI mockup变体，在浏览器打开对比板，收集反馈并迭代。品味记忆会学习你的偏好 |
| 9 | `/design-html` | **Design Engineer** | 把mockup变成真正能用的生产级HTML。Pretext计算布局：文本重排、高度自适应、布局动态。30KB，零依赖。检测React/Svelte/Vue |

#### Phase 4: Review（审查——代码质量）

| # | 命令 | 专家身份 | 做什么 |
|---|------|---------|--------|
| 10 | `/review` | **Staff Engineer** | 找到通过CI但在生产环境爆炸的bug。自动修复明显的。标记完整性缺口 |
| 11 | `/investigate` | **Debugger** | 系统化根因调试。铁律：不调查就不修复。追踪数据流、测试假设、3次修复失败后停止 |
| 12 | `/design-review` | **Designer Who Codes** | 和`/plan-design-review`同样的审计，但会直接修复发现的问题。原子提交，前后截图对比 |
| 13 | `/devex-review` | **DX Tester** | 实时开发者体验审计。真的测试你的onboarding：浏览文档、尝试getting started流程、计时TTHW、截屏错误。和`/plan-devex-review`打分对比——回旋镖验证计划是否匹配现实 |
| 14 | `/codex` | **Second Opinion** | 来自OpenAI Codex CLI的独立代码审查。3种模式：review（通过/失败门禁）、对抗性挑战、开放咨询。当`/review`和`/codex`都运行后进行跨模型分析 |

#### Phase 5: Test（测试——真实浏览器）

| # | 命令 | 专家身份 | 做什么 |
|---|------|---------|--------|
| 15 | `/qa` | **QA Lead** | 测试应用、找bug、原子提交修复、重新验证。为每次修复自动生成回归测试 |
| 16 | `/qa-only` | **QA Reporter** | 和`/qa`相同方法论，但只出报告。纯bug报告，不含代码修改 |
| 17 | `/browse` | **QA Engineer** | 给agent眼睛。真实Chromium浏览器、真实点击、真实截图。~100ms每条命令 |
| 18 | `/setup-browser-cookies` | **Session Manager** | 从真实浏览器导入cookie到无头session。测试需要认证的页面 |

#### Phase 6: Ship & Deploy（发布与部署）

| # | 命令 | 专家身份 | 做什么 |
|---|------|---------|--------|
| 19 | `/ship` | **Release Engineer** | 同步main、运行测试、审计覆盖率、推送、开PR。如果你的项目没有测试框架会自动创建 |
| 20 | `/land-and-deploy` | **Release Engineer** | 合并PR、等CI、部署、验证生产健康状态。一条命令从"已批准"到"生产已验证" |
| 21 | `/canary` | **SRE** | 部署后监控循环。监控控制台错误、性能退化、页面故障 |
| 22 | `/setup-deploy` | **Deploy Configurator** | `/land-and-deploy`的一次性配置。检测平台、生产URL和部署命令 |

#### Phase 7: Reflect & Monitor（反思与监控）

| # | 命令 | 专家身份 | 做什么 |
|---|------|---------|--------|
| 23 | `/benchmark` | **Performance Engineer** | 基准页面加载时间、Core Web Vitals、资源大小。每个PR前后对比 |
| 24 | `/document-release` | **Technical Writer** | 更新所有项目文档以匹配刚发布的内容。自动捕获过时的README |
| 25 | `/retro` | **Eng Manager** | 团队感知的每周回顾。每人分解、发货连续性、测试健康趋势、成长机会。`/retro global`跨所有项目和AI工具运行 |
| 26 | `/learn` | **Memory** | 管理gstack跨session学到的内容。回顾、搜索、修剪、导出项目特定的模式/陷阱/偏好。学习复利让gstack在你的代码库上越来越聪明 |

#### 跨阶段工具（Power Tools）

| # | 命令 | 功能 | 类型 |
|---|------|------|------|
| 27 | `/pair-agent` | **Multi-Agent Coordinator** — 与任何AI agent共享浏览器。支持OpenClaw/Hermes/Codex/Cursor等 | 协作工具 |
| 28 | `/cso` | **Chief Security Officer** — OWASP Top 10 + STRIDE威胁模型。零噪音、置信度门禁 | 安全工具 |
| 29 | `/careful` | **Safety Guardrails** — 在破坏性命令前警告（rm -rf、DROP TABLE）。说"be careful"激活 | 安全护栏 |
| 30 | `/freeze` | **Edit Lock** — 限制文件编辑到一个目录内，防止误改范围外文件 | 安全护栏 |
| 31 | `/guard` | **Full Safety** — `/careful` + `/freeze` 合一。生产工作的最大安全模式 | 安全护栏 |
| 32 | `/unfreeze` | **Unlock** — 移除`/freeze`边界 | 安全护栏 |
| 33 | `/open-gstack-browser` | **GStack Browser** — 启动带侧边栏、反爬虫隐身、自动模型路由的专用浏览器 | 浏览器工具 |
| 34 | `/gstack-upgrade` | **Self-Updater** — 升级gstack到最新版，检测全局vs vendored安装 | 维护工具 |

---

## View C：23个身份 → 34个命令映射（设计哲学的核心）

### 一个身份为什么拆成多个命令？

```
传统思维（角色导向）：            gstack思维（任务导向）：
┌──────────────┐                ┌─────────────────────────┐
│  QA Engineer  │                │  QA Lead (/qa)          │
│  职责：测试    │                │    → 测试+修bug+回归     │
│  输出：测试报告 │                │                         │
└──────────────┘                │  QA Reporter (/qa-only)  │
                                │    → 只报告，不改代码     │
                                │                         │
                                │  QA Engineer (/browse)   │
                                │    → 真实浏览器操作       │
                                │                         │
                                │  Session Manager (...cookies) │
                                │    → 导入认证状态         │
                                └─────────────────────────┘

角色导向：一个人=一个职责范围      任务导向：一个身份=一组原子任务
问题：职责边界模糊               优势：每个任务精确可控
```

### 完整映射表：26个技能身份 + 8个工具 = 34个命令

| 功能域 | 专家身份 | 命令数 | 具体命令 |
|--------|---------|--------|---------|
| **🎯 产品与战略** | YC Office Hours | 1 | `/office-hours` |
| | CEO / Founder | 1 | `/plan-ceo-review` |
| **🔧 工程管理** | Eng Manager | 2 | `/plan-eng-review`, `/retro` |
| | Review Pipeline | 1 | `/autoplan` |
| **🎨 设计线（5个身份→5个命令）** | Design Partner | 1 | `/design-consultation` |
| | Design Explorer | 1 | `/design-shotgun` |
| | Design Engineer | 1 | `/design-html` |
| | Senior Designer | 1 | `/plan-design-review` |
| | Designer Who Codes | 1 | `/design-review` |
| **💻 开发体验** | DX Lead | 2 | `/plan-devex-review`, `/devex-review` |
| **🔍 代码质量（3个身份→3个命令）** | Staff Engineer | 1 | `/review` |
| | Debugger | 1 | `/investigate` |
| | Second Opinion | 1 | `/codex` |
| **🧪 质量保障（4个身份→4个命令）** | QA Lead | 1 | `/qa` |
| | QA Reporter | 1 | `/qa-only` |
| | QA Engineer | 1 | `/browse` |
| | Session Manager | 1 | `/setup-browser-cookies` |
| **🔒 安全与发布运维** | CSO | 1 | `/cso` |
| | Release Engineer | 2 | `/ship`, `/land-and-deploy` |
| | SRE | 1 | `/canary` |
| | Deploy Configurator | 1 | `/setup-deploy` |
| **📊 效能与协作** | Performance Engineer | 1 | `/benchmark` |
| | Technical Writer | 1 | `/document-release` |
| | Memory | 1 | `/learn` |
| | Multi-Agent Coordinator | 1 | `/pair-agent` |
| **🛡️ 安全护栏（无对应专家身份，纯工具）** | Safety Guardrails | 4 | `/careful`, `/freeze`, `/guard`, `/unfreeze` |
| **🌐 基础设施（无对应专家身份，纯工具）** | GStack Browser | 1 | `/open-gstack-browser` |
| | Self-Updater | 1 | `/gstack-upgrade` |

---

## 设计哲学：与链家ACN的同构性

> **核心洞察**：gstack的组织设计和左晖链家ACN（Agent Cooperate Network）遵循完全相同的底层逻辑——**任务导向而非角色导向**

### 左晖的ACN是什么？

2018年，左晖在链家内部推出**ACN经纪人合作网络**，解决了一个行业根本矛盾：

```
传统中介模式的问题：
  一单交易 = 只有成交经纪人拿佣金
  结果：经纪人之间恶性竞争、信息孤岛、客户体验差

ACN的解法：
  一单交易 = 拆成多个【角色】，按贡献分佣金
  ┌─────────────────────────────────────────┐
  │ 房源录入人(5%)  房源维护人(10%)          │
  │ 客源方(35%)     带看人(20%)             │
  │ 重点推荐人(5%)  最终成交人(25%)          │
  └─────────────────────────────────────────┘
  
  关键创新：
  ① 一个经纪人可以在不同交易中扮演不同角色
  ② 角色之间必须协作才能完成一单交易
  ③ 按【任务】分配利益，不是按【人头】分配
```

**左晖原话**（来自招股说明书）：
> "ACN操作系统，ACN操作系统的核心是对经纪人好。"  
> "互联网的本质是一张信息网络。把一张单子切分成多个协作角色，基于交易角色的不同进行业绩分配。"

### gstack × ACN：同构对照

| 维度 | 链家ACN | gstack |
|------|---------|--------|
| **基本单元** | 经纪人（人） | LLM实例（AI） |
| **拆分逻辑** | 一单交易 → 多个协作角色 | 一个sprint → 多个专家身份 |
| **角色数量** | ~7-10个标准角色 | ~23个专家身份 |
| **任务粒度** | 录入/维护/带看/签约… | office-hours/review/qa/ship… |
| **组织原则** | 任务导向，非角色导向 | 任务导向，非角色导向 |
| **一人多角** | 一个经纪人可同时担任多个角色 | 一个LLM切换prompt扮演多个身份 |
| **流程串联** | 按交易流程串起各角色 | 按Sprint阶段串起各命令 |
| **产出物** | 成交合同 + 分佣记录 | 生产代码 + PR + 部署 |
| **核心价值** | 打破信息孤岛，让协作产生网络效应 | 打破能力孤岛，让pipeline产生质量门禁 |

### 为什么任务导向优于角色导向？

```
角色导向的问题：
  "你是QA，你负责测试"
  → 职责边界模糊：测到什么程度？修不修bug？写不写回归？
  → 角色之间容易互相推诿或重叠

任务导向的优势：
  "/qa：测试+原子修复+回归测试"
  "/qa-only：只报告不修改"
  "/browse：给agent眼睛"
  → 每个任务的输入/输出明确定义
  → 可组合、可替换、可并行
  → 就像乐高积木而不是一整块雕塑
```

### 对投研工作的启示

```
如果用gstack/ACN的思路重组投研工作流：

角色导向（当前常见做法）：          任务导向（gstack/ACN启发）：
┌────────────┐                   ┌──────────────────────────┐
│ 研究员      │                   │ /deep-dive  深度基本面研究  │
│ 职责：研究   │                   │ /quick-scan 快速筛选扫描   │
├────────────┤                   │ /risk-audit  风险专项审计  │
│ 分析师      │                   │ /compare     标的横向对比   │
│ 职责：分析   │                   │ /valuation   估值建模       │
├────────────┤                   │ /thesis-check 投资论点验证  │
│ 风控官      │                   │ /red-flags   红旗信号扫描   │
│ 职责：风控   │                   └──────────────────────────┘
└────────────┘
模糊的职责边界                     精确的任务定义 + pipeline串联
```

---

## 7个Sprint阶段（完整流程）

```
Think ──→ Plan ──→ Design ──→ Review ──→ Test ──→ Ship&Deploy ──→ Reflect
  │         │          │           │          │         │             │
  │     CEO评审    设计系统    Staff审查   真实浏览器   PR+部署      回顾+监控
  │     Eng评审    Mockup探索  调试        QA测试     Canary       Benchmark
  │     Design评审 → HTML代码  DX审计      Bug报告    SRE          文档更新
  │     DX评审                Codex第二意见 Cookie管理              Memory学习
  │     Autoplan全自动
  ↓
每个阶段的输出自动喂入下一阶段（pipeline模式）
```

### 各阶段的核心价值

| 阶段 | 解决什么问题 | 核心命令 |
|------|------------|---------|
| **Think** | "我们到底在做什么？" | `/office-hours` — 6个强制问题逼出真实需求 |
| **Plan** | "怎么做才不会返工？" | `/autoplan` — CEO→设计→工程全自动评审链 |
| **Design** | "长什么样才能交付？" | `design-shotgun` → `design-html` — 从选项到生产代码 |
| **Review** | "有什么隐患没发现？" | `/review` + `/codex` — 双模型交叉审查 |
| **Test** | "真的能用吗？" | `/qa` — 真实浏览器、原子修复、回归测试 |
| **Ship** | "怎么安全上线？" | `/ship` → `/land-and-deploy` → `/canary` — 完整发布管线 |
| **Reflect** | "下次怎么做得更好？" | `/retro` + `/learn` — 经验复利积累 |

### 智能路由：该用哪个review？

| 你在构建什么... | 编码前用（Plan阶段） | 上线后用（Review阶段） |
|----------------|---------------------|---------------------|
| 面向终端用户（UI/Web/移动端） | `/plan-design-review` | `/design-review` |
| 面向开发者（API/CLI/SDK/文档） | `/plan-devex-review` | `/devex-review` |
| 架构层面（数据流/性能/测试） | `/plan-eng-review` | `/review` |
| **全部都要** | `/autoplan`（自动检测并运行所有适用评审） | — |

---

## 安装方法

### 前置条件

| 条件 | 说明 |
|------|------|
| Claude Code | 命令行工具（gstack的宿主） |
| Node.js | 运行setup脚本需要 |
| WSL 或 Git Bash | setup脚本用bash编写 |

### 方法1：WSL安装（推荐）

```bash
git clone https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
cd ~/.claude/skills/gstack
./setup
```

### 方法2：手动安装（不用WSL）

```
1. 下载仓库 → https://github.com/garrytan/gstack → Download ZIP
2. 解压到 Claude Code skills 目录
   Windows: C:\Users\<用户名>\.claude\skills\
3. 手动执行 setup 文件中的命令（逐条复制到PowerShell执行）
4. 在项目根目录创建 CLAUDE.md，添加gstack角色指引
```

### 方法3：零安装（纯概念学习）

不装任何东西，只学习方法论：
- 学习gstack的命令组织思路（按sprint阶段、按技能粒度）
- 在Trae中手动切换角色提示词
- 实现类似的多视角工作流

---

## 在你的体系中实现

### 方案A：Trae + 手动角色切换（立即可用）

```
不需要安装任何东西：

操作方式：
  在Trae聊天窗口中直接切换角色提示词

示例流程：
  Step 1: "你是产品经理，请帮我定义XXX项目的需求"
  Step 2: "你是架构师，基于刚才的需求，请设计技术方案"
  Step 3: "你是技术负责人，请审查这个方案的可行性"

优势：
  ✅ 零成本，立即开始
  ✅ 灵活，可随时调整角色定义
  ❌ 需要手动管理上下文切换
  ❌ 没有自动化的工具链
```

### 方案B：安装gstack + Claude Code（完整体验）

```
条件：
  1. 安装 Claude Code（命令行工具）
  2. 用WSL或手动方式安装gstack
  3. 在Claude Code中使用 /gstack 命令

优势：
  ✅ 自动角色切换
  ✅ 更好的上下文管理
  ✅ 内置工具链（Browser/Security Scan等）
  ❌ 需要Claude Code API费用
  ❌ 依赖WSL或bash环境
```

### 方案C：混合方案（推荐中期路径）

```
先用方案A跑通流程（本周）
  ↓
验证哪些角色对你的工作最有价值（本月）
  ↓
针对高频角色创建专用prompt模板（持续）
  ↓
如果团队协作需求增长 → 升级到方案B
```

### 与现有体系的结合点

| 你的体系 | gstack可增强的部分 |
|---------|-------------------|
| `financial_model_project` | Architect角色辅助系统设计 |
| `平行宇宙智能仓位决策引擎` | Tech Lead + Code Reviewer辅助代码质量 |
| 投研框架演化 | Researcher角色辅助技术调研 |
| Wiki维护 | Writer角色辅助文档生成 |

---

## 与Karpathy Wiki的对比

> Karpathy LLM Wiki的方法论已在 `d:\AI\证券投资\wiki\CLAUDE.md` 中完整落地。此处仅作简短对比。

| 维度 | Karpathy LLM Wiki | Garry Tan gstack |
|------|-------------------|------------------|
| **形态** | 知识库构建方法（Markdown组织） | AI角色扮演配置（System Prompt集合） |
| **解决什么问题** | "知识怎么沉淀和复用" | "复杂任务怎么分工协作" |
| **核心产出** | 结构化的知识页面（sources/entities/concepts） | 多视角的专业输出（代码/文档/决策） |
| **技术栈** | 纯文本，任何编辑器 | Claude Code + Node.js |
| **需要WSL？** | ❌ 不需要 | ⚠️ setup脚本需要bash |
| **学习曲线** | 低（立即可用） | 中（需配置环境） |
| **互补关系** | 管"知识"——知道什么 | 管"执行"——怎么做 |

### 一句话定位

```
Karpathy Wiki = 你的"第二大脑"（知识库）
gstack          = 你的"虚拟团队"（执行力）

两者不冲突：
  Wiki告诉你"储能技术的关键参数是什么"
  gstack帮你"设计一个储能优化模型的架构"
```

---

## 核心价值与方法论启示

### Garry Tan的原话

> "我开源了我构建软件的方式。你可以fork它，让它成为你自己的。"

### 可迁移的方法论（不限软件开发）

| 启示 | 说明 | 非软件应用举例 |
|------|------|---------------|
| **角色=视角** | 不是真的要23个"人"，而是23种专业身份（映射到34个命令） | 投研时切换"研究员/分析师/风险官"视角 |
| **双层设计** | L1身份（谁在做）+ L2任务（做什么），任务导向非角色导向 | 投研时：先定义视角，再定义每个视角的原子动作 |
| **阶段门禁** | 每个阶段有明确的输入输出，不能跳步 | 框架演化：定义问题→深挖→验证→统一 |
| **工具赋能技能** | 每个命令有专属能力，不是空谈 | 投研工具（引擎/Wiki/辩论）对应不同阶段 |
| **可定制** | 23个身份是起点不是终点 | 你可以定义自己的"投研命令组" |

### 对投研工作的启发

```
gstack的角色制 → 映射到投研场景：

Product Manager  → 投资主题定义（为什么研究这个？）
Architect        → 分析框架设计（用什么框架切入？）
Researcher       → 行业/公司深度调研
Tech Lead        → 投资逻辑审查（论证是否严密？）
QA Engineer      → 反向压力测试（什么情况下这个判断会错？）
Security         → 风险识别（下行风险是什么？）
Writer           → 研究结论输出
```

---

## 下一步行动计划

### 短期（本周）

- [ ] 在Trae中练习手动角色切换（方案A）
- [ ] 创建3-5个常用角色的prompt模板
- [ ] 用角色切换法完成一个小任务（如代码审查）

### 中期（本月）

- [ ] 评估哪些角色对当前工作价值最高
- [ ] 设计"投研版命令组"（从gstack的23个身份改编）
- [ ] 决定是否需要升级到方案B（Claude Code + gstack）

### 长期（按需）

- [ ] 如果工程协作需求增长 → 安装完整gstack
- [ ] 将角色方法论泛化到非工程领域（投研/人生决策）
- [ ] 探索与其他AI工作流的组合使用

---

## 参考资源

| 资源 | 链接 |
|------|------|
| GitHub仓库 | https://github.com/garrytan/gstack |
| README（最新安装说明） | 同上 |
| 中文介绍 | CSDN "GStack: 将Claude Code转变为按需召唤的专业团队" |
| Karpathy Wiki（已落地版本） | `d:\AI\证券投资\wiki\CLAUDE.md` |

---

## 附录：常见问题

### Q1: gstack必须配合Claude Code吗？

```
答：完整功能需要Claude Code作为宿主。
但核心方法论（角色切换）可以在任何LLM对话中手动实现。
```

### Q2: 不装WSL能用吗？

```
答：可以用。
方法2提供了手动安装步骤，在PowerShell中逐条执行即可。
只是稍微麻烦一点。
```

### Q3: 34个命令都要用吗？

```
答：不需要。
gstack按sprint阶段组织，根据项目规模选择子集：
- 最小集（日常）：/office-hours → /autoplan → /review → /ship（4个命令）
- 标准集：加上 /qa + /cso + /retro（7个命令）
- 完整集：全部34个命令
你也可以自定义命令，gstack是参考不是标准。
```

### Q4: 和我的Wiki体系怎么配合？

```
答：互补关系。
  Wiki管知识沉淀（你知道什么）
  gstack管任务执行（你怎么做事）

具体配合：
  用Wiki存储研究结果（Ingest）
  用gstack角色法驱动研究过程（多视角分析）
  两者的产出都回到Wiki存档
```

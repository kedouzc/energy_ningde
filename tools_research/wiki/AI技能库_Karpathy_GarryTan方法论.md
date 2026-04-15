# AI 技能库：Karpathy LLM Wiki + Garry Tan gstack 方法论

> **创建日期**：2026-04-08
> **用途**：超级个体 AI 工作流技能学习
> **路径**：`d:\AI\tools\research\AI技能库_Karpathy_GarryTan方法论.md`

---

## 目录

1. [核心发现总结](#核心发现总结)
2. [Andrej Karpathy - LLM Wiki 方法论](#andrej-karpathy---llm-wiki-方法论)
3. [Garry Tan - gstack 工程团队模拟](#garry-tan---gstack-工程团队模拟)
4. [在你的体系中如何实现](#在你的体系中如何实现)
5. [下一步行动计划](#下一步行动计划)

---

## 核心发现总结

### 两个工具的本质区别

| 维度 | Karpathy LLM Wiki | Garry Tan gstack |
|------|-------------------|------------------|
| **形态** | 方法论 + Markdown 组织方式 | Claude Code 技能配置 |
| **技术栈** | 纯文本，任何编辑器 | 需要 Claude Code + Node.js |
| **需要 WSL？** | ❌ 完全不需要 | ⚠️ setup 脚本需要 bash |
| **学习曲线** | 低（立即可用） | 中（需配置环境） |
| **核心价值** | 知识库构建方法 | AI 团队协作流程 |

### 关键洞察

```
Karpathy 的 LLM Wiki：
  → 不是软件，是"用 Markdown 管理知识的方法"
  → 任何 IDE（包括 Trae）都能实现
  → 和你的 research 文件夹体系天然契合

gstack：
  → 不是独立程序，是 Claude Code 的"角色扮演配置"
  → 15 个 system prompt 让 AI 模拟工程团队
  → 需要 Claude Code 命令行工具作为宿主
```

---

## Andrej Karpathy - LLM Wiki 方法论

根据 Karpathy 在 [GitHub Gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) 和 [VentureBeat 专访](https://venturebeat.com/data/karpathy-shares-llm-knowledge-base-architecture-that-bypasses-rag-with-an) ：

### 什么是 LLM Wiki？

#### **核心思想**：从“检索”转向“编译”
用 LLM 构建一个**进化式的 Markdown 知识库**，，替代传统的 RAG（检索增强生成）。不是简单的“整理”，而是**“编译（Compilation）”**。
  - 将 `raw/` 视为**源代码**，将 `wiki/` 视为**编译后的二进制/库**。
  - RAG 是在运行时解释，而 Wiki 是在预处理阶段编译。

#### **与传统 RAG 的区别**：

```
传统 RAG：
  上传文件 → 向量化存储 → 查询时检索相关片段 → LLM 生成答案
  问题：每次都要重新检索，没有积累

Karpathy 的 LLM Wiki：
  上传文件 → LLM 阅读理解 → 整合进 Wiki 结构 → 更新关联页面
  优势：知识沉淀，复利增长
```

#### 🚀 为什么这是“RAG 杀手”？

* **消除检索噪音**：向量检索经常会搜到语义相近但逻辑无关的“废话”。Wiki 页面是经过 LLM 深度理解后重写的，密度极高。
* **状态持久化**：对话不再是“阅后即焚”。所有的洞察都通过 **“回填（Backfilling）”** 机制永远留在了你的 Markdown 文件里。
* **人类可读性**：即使没有 AI，这套 [Obsidian](https://obsidian.md/) 文件夹也是你个人最宝贵的、结构清晰的第二大脑。


### 核心机制

#### 1. 架构设计 (The 3-Layer Vault)

```
三层架构：
├── raw/                  ← 你放入原始资料（只读）
├── wiki/                 ← LLM生成和维护（LLM读写）
│   ├── sources/          ← 源摘要（每篇raw一篇）
│   ├── entities/         ← 实体页（人物、公司）
│   ├── concepts/         ← 概念页（理论、方法）
│   ├── logs/             ← 日志页（记录每次修改）
│   └── synthesis/        ← 综合页（主题综述）
├── CLAUDE.md             ← Schema（告诉LLM如何维护）
└── index.md              ← 目录（LLM维护）
```

| 文件夹/文件 | 角色 | 权限 | 内容描述 |
| :--- | :--- | :--- | :--- |
| **`01_raw/`** | **源码层** | 人类只读 | 原始 PDF、网页快照、会议录音转文字。**永不修改**。 |
| **`02_wiki/`** | **知识层** | LLM 主写 | **核心产物**：包含 `entities/`（实体）、`concepts/`（概念）、`logs/`（记录）。 |
| **`CLAUDE.md`** | **指令层** | 人类维护 | **Wiki 宪法**：定义 Markdown 格式规范、命名约定、自动链接触发条件，定义了 LLM 作为“维基编辑”的身份准则、文风和冲突解决逻辑，不只是 Schema（模式），它更像是项目的 **“System Prompt 落地版”** 或 **“规则书”** |
| **`INDEX.md`** | **路由层** | 共同维护 | 动态更新的目录。LLM 导航的“地图”，防止在大规模 Wiki 中迷路。 |

#### 2. 四大核心动作 (The Pipeline)

```
四个流程：
├── Ingest    ← 你放入资料，LLM生成摘要 `sources/` 、更新关联 `entities/`
├── Synthesize ← LLM自动发现关联、建立链接 `synthesis/`
├── Query     ← 你提问，LLM基于wiki回答, 基于 INDEX.md 导航
└── Lint      ← LLM定期检查矛盾、过时LLM Wiki 结构
```

1.  **Ingest (摄入)**：
    * LLM 阅读 `raw/` 资料。
    * **关键动作**：不是生成片段，而是生成一个 `sources/` 摘要，并**主动修改**已有的 `entities/` 页面。例如：新资料提到了“奥本海默”，LLM 会直接去编辑 `wiki/entities/Oppenheimer.md` 增加新细节。
2.  **Synthesize (合成)**：
    * 定期运行。LLM 扫描 `wiki/` 目录，发现两个看似无关的概念（例如“量子计算”与“生物折叠”）之间的联系，并新建一个 `synthesis/` 页面进行深度对比。
3.  **Lint (巡检)**：
    * **一致性检查**：发现新旧资料冲突时，标注 `[CONFLICT]` 标签请人类裁决。
    * **反思性增强**：LLM 会扫描 Wiki 中孤立的页面（孤儿节点），强行寻找它们与已有知识的潜在联系。
    * **链接固化**：将 `[[双括号]]` 链接补齐，确保知识图谱没有断点。
4.  **Query (查询)**：
    * 用户提问时，LLM **优先读取 INDEX.md**，定位到相关的 Wiki 页面，而不是去海量向量库里捞碎片。

#### 3. 关键洞察

> "好的答案应该回填进 Wiki 作为新页面。你要求的对比、你做的分析、你发现的关联——这些不应该消失在聊天历史里。"

- wiki/目录是LLM的领地 ，人类只读不写（或少量编辑）
- 你的工作是 ：放入raw资料、提问、审核LLM的整理
- LLM的工作是 ：维护wiki、建立关联、回答查询

**复利效应**：
- 每次对话产生的洞察 → 沉淀为 Wiki 页面
- 新资料自动关联已有知识 → 知识网络越来越密
- 后续查询基于积累的知识 → 回答质量越来越高

### 在你的体系中实现

Karpathy 推荐使用 Claude Code(https://www.mindstudio.ai/blog/andrej-karpathy-llm-wiki-knowledge-base-claude-code) 或 OpenCode 这种具备文件读写能力的 Agent 挂载到你的本地文件夹。

#### 方案：用 Trae + Markdown 构建 LLM Wiki

```
你的 research 文件夹结构：
d:\AI\tools\research\
├── AI技能库_Karpathy_GarryTan方法论.md  ← 本文件
├── wiki/                                  ← 新增：LLM Wiki 根目录
│   ├── _sources/                          ← 原始资料
│   │   ├── 论文/
│   │   ├── 网页/
│   │   └── 书籍/
│   ├── 能源科技/                          ← 按主题组织
│   │   ├── 储能技术.md
│   │   ├── 光伏产业.md
│   │   └── 电网调度.md
│   ├── 投资研究/
│   │   ├── 周期理论.md
│   │   └── 估值方法.md
│   └── _index.md                          ← 知识库索引
└── ...其他研究文件
```

#### 工作流程（在 Trae 中实现）

**Step 1：添加新资料**
```
你：
  "请阅读这个文件 d:\AI\tools\research\wiki\_sources\论文\新型储能技术.pdf
   提取关键信息，更新到 Wiki 中"

AI：
  1. 阅读 PDF
  2. 提取要点
  3. 创建/更新 wiki/能源科技/储能技术.md
  4. 更新 wiki/_index.md 索引
```

**Step 2：提问查询**
```
你：
  "储能技术和光伏产业的协同发展趋势是什么？"

AI：
  1. 阅读 wiki/能源科技/ 下的相关页面
  2. 综合已有知识
  3. 生成回答
  4. （可选）将新洞察保存为新页面
```

**Step 3：定期整理**
```
你：
  "请检查 Wiki 中的知识空白和矛盾点"

AI：
  1. 扫描所有页面
  2. 发现：储能技术.md 提到"锂电池"但缺少"钠电池"
  3. 发现：光伏产业.md 和 储能技术.md 对"度电成本"的定义不一致
  4. 建议补充和统一
```

### 关键技巧

#### 1. 页面模板

```markdown
---
title: 储能技术
created: 2026-04-08
updated: 2026-04-08
tags: [能源, 储能, 锂电池]
---

# 储能技术

## 核心概念
...

## 技术路线对比
...

## 产业现状
...

## 相关页面
- [[光伏产业]] - 协同应用场景
- [[电网调度]] - 技术需求方

## 待补充
- [ ] 钠电池技术进展
- [ ] 固态电池商业化时间线
```

#### 2. 双向链接语法

```markdown
使用 [[页面名]] 创建链接：
- [[储能技术]]
- [[光伏产业|光伏]]（显示别名）
```

#### 3. 与 AI 的交互提示词模板

```
【添加资料】
请阅读附件 [文件路径]，提取关键信息：
1. 核心观点（3-5条）
2. 重要数据
3. 与我现有知识的关联
4. 建议保存到哪个 Wiki 页面

【查询知识】
基于我的 Wiki 知识库，回答：[问题]
请引用相关的 Wiki 页面。

【整理检查】
请检查我的 Wiki 知识库：
1. 找出知识空白（什么重要主题缺失）
2. 找出矛盾点（不同页面的冲突）
3. 建议改进方向
```

---

## Garry Tan - gstack 工程团队模拟

### 什么是 gstack？

**核心思想**：用 Claude Code + 15 个专业角色的 system prompt，模拟一个完整的工程团队。

**发布时间**：2026 年 3 月 12 日  
**代码规模**：60 万+ 行（主要是角色配置和工具脚本）

### 15 个专业角色

| 角色 | 职责 | 使用场景 |
|------|------|---------|
| **Product Manager** | 产品定义、需求分析 | 项目启动时 |
| **Architect** | 架构设计 | 技术方案阶段 |
| **Tech Lead** | 技术决策、代码审查 | 开发全程 |
| **Frontend Dev** | 前端开发 | UI 实现 |
| **Backend Dev** | 后端开发 | API 实现 |
| **DevOps** | 部署、CI/CD | 发布阶段 |
| **Security** | 安全审计 | 代码审查时 |
| **QA Engineer** | 测试、质量保证 | 测试阶段 |
| **Data Engineer** | 数据架构、ETL | 数据相关 |
| **Designer** | UI/UX 设计 | 设计阶段 |
| **Researcher** | 技术调研 | 技术选型 |
| **Writer** | 文档撰写 | 全程 |
| **Code Reviewer** | 代码审查 | PR 时 |
| **Performance** | 性能优化 | 优化阶段 |

### 6 个工具

| 工具 | 功能 |
|------|------|
| **Browser** | 真实浏览器测试 |
| **Security Scan** | 安全扫描 |
| **Code Search** | 代码搜索 |
| **API Test** | API 测试 |
| **Performance** | 性能基准 |
| **Documentation** | 文档生成 |

### 6 个阶段

```
项目流程：
1. Product → 定义产品
2. Architect → 架构设计
3. Develop → 开发实现
4. Test → 测试验证
5. Deploy → 部署上线
6. Monitor → 监控维护
```

### 安装方法

#### 方法 1：使用 WSL（推荐）

```bash
# 在 WSL 终端中执行
git clone https://github.com/garrytan/gstack.git ~/.claude/skills/gstack
cd ~/.claude/skills/gstack
./setup
```

#### 方法 2：手动安装（不用 WSL）

```
步骤：
1. 下载 gstack 仓库
   → 访问 https://github.com/garrytan/gstack
   → 点击 Code → Download ZIP
   
2. 解压到 Claude Code skills 目录
   → Windows: C:\Users\<用户名>\.claude\skills\
   → 或 ~/AppData/Local/Claude/

3. 手动执行 setup 的内容
   → 打开 setup 文件
   → 复制命令逐行执行

4. 配置 CLAUDE.md
   → 在项目根目录创建 CLAUDE.md
   → 添加 gstack 角色指引
```

#### 方法 3：只用核心概念（完全不用 WSL）

```
如果不安装 gstack，可以：
1. 学习 gstack 的 15 个角色划分方法
2. 在 Trae 中手动切换角色提示词
3. 实现类似的工作流程

操作方式：
→ 在 Trae 的聊天窗口
→ 输入 "你是产品经理，请帮我定义 XXX 项目的需求"
→ 完成后，换 "你是架构师，请帮我设计 XXX 的架构"
```

### 在你的体系中实现

#### 方案 A：直接用 Trae + 手动角色切换

```
不需要安装任何东西，立即可用：

1. 创建角色提示词库
   d:\AI\tools\research\prompts\
   ├── product_manager.md
   ├── architect.md
   ├── tech_lead.md
   └── ...

2. 使用时复制对应角色提示词到 Trae

3. 示例流程：
   Step 1: "你是储能项目的产品经理，请帮我定义这个项目的需求"
   Step 2: "你是架构师，基于刚才的需求，请设计技术方案"
   Step 3: "你是技术负责人，请审查这个方案的可行性"
```

#### 方案 B：安装 gstack + Claude Code（进阶）

```
如果你想完整使用 gstack：

1. 确保有 Claude Code（命令行工具）
2. 用 WSL 或手动安装 gstack
3. 在 Claude Code 中使用 /gstack 命令

优势：
→ 自动切换角色
→ 更好的上下文管理
→ 团队协作模式
```

### gstack 的核心价值

```
Gary Tan 说：
"我开源了我构建软件的方式。你可以 fork 它，让它成为你自己的。"

对你的启发：
→ 不是要复制 gstack，而是学习它的方法论
→ 15 个角色 = 15 种专业视角
→ AI 可以扮演任何角色
→ 你可以定义自己的"团队成员"
```

---

## 在你的体系中如何实现

### 技能优先级排序

| 优先级 | 技能 | 难度 | 价值 | 建议 |
|--------|------|------|------|------|
| ⭐⭐⭐⭐⭐ | Karpathy LLM Wiki | 低 | 极高 | **立即开始**，和你的 research 文件夹天然契合 |
| ⭐⭐⭐⭐ | gstack 角色方法论 | 中 | 高 | 先用手动角色切换，不急着装 Claude Code |
| ⭐⭐⭐ | gstack 完整安装 | 高 | 中 | 等 WSL 场景明确后再做 |

### 立即可用的方案

```
你的能源科技研究 + Karpathy LLM Wiki：

Step 1: 创建 Wiki 目录结构
d:\AI\tools\research\wiki\

Step 2: 用 Trae 打开这个文件夹

Step 3: 让 AI 帮你整理现有研究资料
"请阅读 d:\AI\tools\research\ 下的所有 .md 文件，
 帮我整理成 Wiki 结构，每个主题一页"

Step 4: 建立知识关联
"请找出能源科技和投资研究之间的关联"

Step 5: 持续沉淀
每次研究产生的新洞察 → 保存到 Wiki
```

### WSL 的真正价值（重新定义）

```
WSL 不是"必须品"，而是"备选项"：

需要 WSL 的场景：
→ 安装 gstack（bash setup）
→ 使用只有 Linux 版本的工具
→ 复制粘贴 Linux 教程命令

不需要 WSL 的场景：
→ Karpathy LLM Wiki（完全不需要）
→ gstack 手动安装（可以不做）
→ 日常投研工作（PowerShell 够用）

结论：
→ WSL 保持安装状态，以备不时之需
→ 平时用 PowerShell + Trae
→ 遇到 Linux 专属工具时再切 WSL
```

---

## 下一步行动计划

### 短期（本周）

- [ ] 在 Trae 中打开 `d:\AI\tools\research\wiki\` 文件夹
- [ ] 让 AI 整理现有的研究资料到 Wiki 结构
- [ ] 学习用 Markdown 创建双向链接

### 中期（本月）

- [ ] 建立能源科技的 Wiki 页面体系
- [ ] 测试"添加资料 → 查询 → 整理"的完整流程
- [ ] 评估 gstack 角色方法论的实用性

### 长期（持续）

- [ ] 积累 Wiki 知识，形成个人知识复利
- [ ] 根据需要决定是否安装完整 gstack
- [ ] 探索更多 AI 工作流技能

---

## 参考资源

### Karpathy LLM Wiki

- **GitHub Gist**: https://gist.github.com/karpathy
- **核心文章**: "LLM Knowledge Base: Bypassing RAG with an evolving markdown library"
- **中文解读**: 各技术博客

### Garry Tan gstack

- **GitHub**: https://github.com/garrytan/gstack
- **README**: 查看最新安装说明
- **中文介绍**: CSDN "GStack: 将 Claude Code 转变为按需召唤的专业团队"

---

## 附录：常见问题

### Q1: Karpathy LLM Wiki 需要什么工具？

```
答：完全不需要特殊工具。
- 任何文本编辑器都能打开 Markdown 文件
- 推荐用 Trae（你已经在用）
- 可以用 Obsidian（更适合 Wiki 管理，但非必须）
```

### Q2: gstack 需要付费吗？

```
答：gstack 本身免费。
- 但需要 Claude Code 作为宿主
- Claude Code 需要 API Key（按量付费）
- 或者用 Cursor（$20/月，内置 Claude Code）
```

### Q3: WSL 到底要不要装？

```
答：根据你的需求：
- 纯投研 + Karpathy Wiki → 不需要
- 想用完整 gstack → 需要
- 想学 Linux 命令行 → 可以装
- 想和 Mac 用户用一样命令 → 可以装

建议：保持安装状态，平时不用，需要时再切
```

### Q4: 这些技能和你的大纲有什么关系？

```
答：这是"第一层：用 AI"的延伸技能。

大纲 Q1.1（选工具）：
→ IDE 比网页版更适合深度工作

大纲 Q1.2（选模型）：
→ 根据需求选择国产/Claude/Gemini

新增技能：
→ Karpathy Wiki = 更高阶的"用 AI 做研究"方法
→ gstack = 更高阶的"用 AI 协作开发"方法

这些是大纲中没有覆盖的"进阶用法"，值得学习。
```

---

## 附录B：多知识库协同架构

### 你的完整知识库版图

```
d:\AI\
├── tools\research\                    ← 【本文件位置】AI技能库
│   ├── AI技能库_Karpathy_GarryTan方法论.md  ← 本文件
│   └── Karpathy_Wiki_快速上手指南.md        ← 投研wiki建立指南
│
├── financial_model_project\           ← 工程训练场（能力层）
│   └── mind\                          ← 工程化思维训练
│       ├── decisions/                 ← ADR决策记录
│       ├── lessons/                   ← 问题总结
│       └── design/                    ← 系统设计
│
└── 证券投资\                          ← 投研主战场（应用层）
    ├── wiki\                          ← 投资知识库（目标）
    │   ├── CLAUDE.md                  ← 知识库Schema
    │   ├── _sources/                  ← 原始资料层
    │   ├── 00_框架实验室/             ← 框架演化
    │   ├── 01_概念层/                 ← 概念定义
    │   ├── 02_案例层/                 ← 案例研究
    │   ├── 03_洞察层/                 ← 高层洞察
    │   ├── 04_工具层/                 ← 投资工具
    │   └── 05_外部链接/               ← 逻辑链接
    │       ├── mind知识库链接.md
    │       └── AI技能库链接.md
    │
    ├── 投研\                          ← 原始研究资料
    └── 平行宇宙智能仓位决策引擎\      ← 投资工具
```

### 三层能力转化模型

```
┌─────────────────────────────────────────────────────────────┐
│  第一层：能力训练（financial_model_project/mind）            │
│  ├── 工程化思维（ADR、设计文档、问题总结）                    │
│  └── 产出：系统思考能力                                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ 转化
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  第二层：工具技能（tools/research）                          │
│  ├── AI工具使用（Karpathy Wiki、gstack）                     │
│  └── 产出：AI协作效率                                        │
└──────────────────────────┬──────────────────────────────────┘
                           │ 转化
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  第三层：领域实践（证券投资/wiki）                           │
│  ├── 投研知识沉淀（框架、概念、案例）                        │
│  └── 产出：投资决策质量                                      │
└──────────────────────────┬──────────────────────────────────┘
                           │ 验证
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  工具层：实践验证（平行宇宙引擎）                            │
│  └── 产出：可执行的投资策略                                  │
└─────────────────────────────────────────────────────────────┘
```

### 为什么分散是合理的？

| 目录 | 核心定位 | 为什么不整合 |
|------|---------|-------------|
| `mind` | 工程思维训练场 | 培养通用能力，不限于投研 |
| `research` | AI技能库 | 方法论可跨领域复用 |
| `证券投资/wiki` | 投研知识沉淀 | 聚焦领域，避免噪音 |
| `引擎` | 工具实现 | 代码与知识分离 |

**核心原则**：
- **物理分散**：各目录保持独立，便于独立演化
- **逻辑链接**：通过 `05_外部链接/` 建立关联
- **能力流动**：从通用能力 → 工具技能 → 领域实践

### 跨知识库工作流

**场景1：从工程思维到投研框架**
```
1. 在 mind/ 中学习 ADR 决策记录法
2. 应用到 wiki/00_框架实验室/ 的框架决策
3. 创建 wiki/00_框架实验室/_框架演化决策记录.md
```

**场景2：从AI技能到投研效率**
```
1. 在 research/ 中学习 Karpathy Wiki 方法
2. 应用到 wiki/ 的架构设计
3. 创建 wiki/CLAUDE.md 定义Schema
```

**场景3：从投研洞察到工具实现**
```
1. 在 wiki/02_案例层/ 中发现规律
2. 沉淀到 wiki/03_洞察层/
3. 在 引擎/ 中实现为可执行策略
```

### 给Claude的跨库查询提示词

```markdown
【跨知识库查询】

请基于以下知识库回答问题：

知识库1（AI技能）：d:\AI\tools\research\
- Karpathy_Wiki_快速上手指南.md
- AI技能库_Karpathy_GarryTan方法论.md

知识库2（工程思维）：d:\AI\financial_model_project\mind\
- decisions/ - 决策记录
- lessons/ - 问题总结
- design/ - 设计文档

知识库3（投研实践）：d:\AI\证券投资\wiki\
- 00_框架实验室/ - 投资框架
- 01_概念层/ - 核心概念
- 02_案例层/ - 案例分析

问题：[你的问题]

要求：
1. 优先从投研知识库(wiki/)获取领域知识
2. 参考工程思维库(mind/)的方法论
3. 使用AI技能库(research/)的工具方法
4. 建立跨库关联，发现深层洞察
```

---

> **最后更新**: 2026-04-08
> **下次回顾**: 安装 gstack 前重新评估需求
> **状态**: 学习资料已整理，等待实践
> **新增**: 多知识库协同架构已明确，无需物理整合
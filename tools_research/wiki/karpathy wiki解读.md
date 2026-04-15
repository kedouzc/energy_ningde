# LLM Wiki：让大模型替你打理知识库的完整指南
# 作者：lizhongxuan，2026-04-07
# 链接：https://juejin.cn/post/7625563529491726378, 阅读21分钟

2026 年 4 月，Andrej Karpathy 在 X 上分享了一条帖子，浏览量超过 1700 万。他说自己不再把大模型主要用于写代码，而是将绝大多数 Token 消耗转向了构建个人知识库。随后他在 GitHub Gist 上发布了一份名为 "LLM Wiki" 的 idea file，详细描述了这套模式的架构、操作流程和工具链。

这篇文章是对 Karpathy 原文、社区讨论和多方评论的一次完整梳理。我们会讲清楚 LLM Wiki 是什么、解决了什么问题、怎么落地，以及它的局限性在哪里。

# 一、从一个问题说起：你的知识去哪了？
研究显示，人类在获取新知识后的短时间内就会遗忘其中的大部分内容。现代知识工作者每天平均花费近两个小时，去查找那些"自己曾经读过"的信息。

不论是 Notion、Roam Research、Obsidian，还是各种收藏夹和"稍后阅读"，长期使用后往往都会演变为一个信息堆积却难以调用的"知识墓地"。人类放弃维护个人 Wiki 或团队知识库，从来不是因为缺乏记录的意愿，而是因为维护成本呈指数级上升——更新交叉引用、排查矛盾点、同步旧数据，这些纯粹的"体力活"让人望而却步。

过去几年，AI 行业尝试通过 RAG（检索增强生成）解决这一问题：把文档切成 Chunk，转成向量，存进数据库，提问时做相似性搜索，再喂给大模型生成答案。这套机制能跑通，但有一个致命缺陷——它没有沉淀。

你问一个需要综合五篇文档的复杂问题，LLM 每次都要从头检索、重新拼凑。明天问同样的问题，它再做一遍同样的工作。知识并没有随着你的提问而"生长"。ChatGPT 的文件上传、NotebookLM 以及大多数 RAG 系统都是这种"阅后即焚"的体验。

Karpathy 的思路截然不同：不要优化"检索"，而是从源头出发，"写出更好的文档"。

# 二、LLM Wiki 是什么？
LLM Wiki 的核心理念用一句话概括：让大模型在后台持续构建、维护一个结构化、相互链接的本地 Markdown 知识库，而不是在每次提问时临时去海量原始数据里翻找。

当你添加一个新的信息源时，LLM 不只是把它"索引"起来等着以后检索。它会阅读这份材料，提取关键信息，然后整合进已有的知识体系——更新实体页面、修订主题摘要、标注新数据与旧结论的矛盾之处、强化或挑战正在演化中的综合判断。知识被"编译"一次，然后持续保持更新，而不是每次查询时重新推导。

Karpathy 用了一个精准的类比来描述他的日常工作流：Obsidian 是你的 IDE，大模型是你的程序员，而这个 Markdown 知识库就是你们共同维护的代码库（Codebase）。

你几乎不需要亲手写 Wiki——LLM 负责所有的撰写和维护工作。你负责的是：寻找优质信息源、把握研究方向、提出好的问题。LLM 负责一切脏活累活——摘要、交叉引用、归档、记账。

Wiki vs RAG：关键差异
维度	传统 RAG	LLM Wiki
知识处理时机	查询时（每次提问都重新处理）	摄入时（每个来源只处理一次）
交叉引用	每次查询临时发现	预先构建并持续维护
矛盾检测	可能完全不会被注意到	摄入时主动标记
知识积累	无——每次从零开始	复利式增长，每个来源和每次提问都让系统更丰富
输出格式	聊天回复（转瞬即逝）	持久化的 Markdown 文件（可复用、可传播）
维护者	系统黑箱	LLM（透明、可编辑、可追溯）
人类角色	上传文件 + 提问	策展信息源、探索方向、提出关键问题
这里最关键的区别是：Wiki 是一个持久的、复利式增长的知识资产。 交叉引用已经建好了，矛盾已经被标记了，综合判断已经反映了你读过的所有内容。每添加一个来源、每提出一个问题，Wiki 都会变得更丰富。

# 三、三层架构：极简但够用
整个系统没有复杂的向量数据库，没有中间件，只有三个纯文本层：

## 第一层：Raw Sources（原始数据层）
你的"真理之源"。文章、论文、图片、数据文件、代码仓库、会议记录——统统丢进来。这一层是不可变的（Immutable），LLM 只读不写。

这个设计至关重要：你永远保有原始来源用于验证。如果 LLM 在 Wiki 中犯了错，你可以追溯到原始数据进行纠正。

``` bash
raw/
  articles/
    2026-03-attention-is-all-you-need-revisited.md
    2026-04-scaling-laws-update.md
  papers/
    transformer-architecture-v2.pdf
  data/
    benchmark-results.csv
  assets/
    transformer-diagram.png
```
## 第二层：The Wiki（编译输出层）
一个纯粹由大模型生成和维护的 Markdown 文件夹。摘要、实体页面、概念页面、对比分析、全局概览、综合判断——LLM 拥有这层的绝对控制权。当新数据进来时，它负责创建新页面、更新旧页面、维护双向链接，并保持全局一致性。你读它；LLM 写它。

``` bash
wiki/
  index.md          # 全局目录
  log.md            # 时间线日志
  overview.md       # 全局综合判断
  concepts/         # 概念页面
  entities/         # 实体页面
  sources/          # 来源摘要
  comparisons/      # 对比分析
```

## 第三层：The Schema（控制协议层）
一份告诉 LLM "这个 Wiki 该怎么维护"的配置文档（比如 Claude Code 用 CLAUDE.md，Codex 用 AGENTS.md）。它定义了目录结构、标签规范、页面格式、以及摄入/查询/检查的标准流程。

这是让一个普通聊天 Bot 变成严格的"知识库图书管理员"的开关。 没有它，每次新会话 LLM 都从零开始，不知道你的规范、格式和流程。有了它，LLM 就能跨会话保持一致性。

你和 LLM 会随着使用不断共同演化这份 Schema——发现什么页面结构好用、什么 frontmatter 字段有价值、什么流程需要调整，就更新它。

Schema 示例（以 Claude Code 为例）：

``` markdown
# LLM Wiki Schema

## 项目结构
- `raw/` — 不可变的原始数据。绝对不要修改。
- `wiki/` — LLM 生成的 Wiki。你拥有完全控制权。
- `wiki/index.md` — 全局目录。每次摄入后更新。
- `wiki/log.md` — 只追加的活动日志。

## 页面规范
每个 Wiki 页面必须包含 YAML frontmatter：
---
title: 页面标题
type: concept | entity | source-summary | comparison
sources: [引用的 raw/ 文件列表]
related: [链接的 wiki 页面列表]
created: YYYY-MM-DD
updated: YYYY-MM-DD
confidence: high | medium | low
---

## 摄入流程
当我说"摄入 [文件名]"时：
1. 读取 raw/ 中的源文件
2. 与我讨论关键要点
3. 在 wiki/sources/ 创建或更新摘要页
4. 更新 wiki/index.md
5. 更新所有相关的概念和实体页面
6. 在 wiki/log.md 追加一条记录

## 查询流程
当我提问时：
1. 先读 wiki/index.md 找到相关页面
2. 读取这些页面
3. 综合生成带 [[wiki-link]] 引用的答案
4. 如果答案有价值，主动提议归档为新的 Wiki 页面

## 健康检查流程
当我说"lint"时：
1. 检查页面间的矛盾
2. 找出没有入链的孤岛页面
3. 列出被多次提及但没有独立页面的概念
4. 检查被新来源取代的过时结论
5. 建议下一步值得调查的问题
```

# 四、三大核心操作：让知识库"活"起来
有了三层结构，日常的知识管理就变成了类似软件工程的 SOP：

## 1. Ingest（摄入与编译）
你把一份新材料丢进 raw/ 文件夹，然后告诉 LLM 去处理它。

LLM 不仅会提取核心要点写一份摘要，更关键的是，它会自动去翻阅你之前的相关页面，在新旧内容之间建立双向链接。一个数据源的摄入，可能会触发十几篇相关文档的联动更新。 过去那种碎片化的知识点，被大模型自动缝合在了一起。

Karpathy 个人偏好一次摄入一个来源，全程参与——阅读摘要、检查更新、引导 LLM 该强调什么。但你也可以批量摄入，减少人工介入。关键是找到适合自己的节奏，并把它记录在 Schema 里。

## 2. Query（查询与沉淀）
你向 Wiki 提问，LLM 搜索相关页面、阅读它们、综合生成带引用的答案。答案可以是 Markdown 文档、对比表格、Marp 幻灯片、甚至 Matplotlib 图表。

重点来了：好的答案不要让它留在聊天记录里。 告诉 LLM 把它整理成一篇新的分析文档，归档进 Wiki。

这就形成了一个复利循环：来源被摄入 Wiki → 你的提问产生新洞察 → 最好的洞察被归档为新页面 → Wiki 不仅从外部来源增长，也从你自己的探索中增长。你的每一次深度思考和提问，都变成了知识库里的新资产。

## 3. Lint（自动化健康检查）
定期让 LLM 对整个 Wiki 进行"代码审查"：

- 检测内容自相矛盾的地方（比如旧策略与新引入的规则冲突）
- 找出没有被任何页面引用的"孤岛页面"
- 列出被多次提及但还没有独立页面的重要概念
- 标记被新来源取代的过时结论
- 建议值得调查的新问题和值得寻找的新来源
LLM 就像一个不会疲倦的运维，保持知识库的长期健康。正如社区成员 Charly Wargnier 所说："它就像一个活的 AI 知识库，能够自我修复。"

# 五、两个极简的核心索引文件
不需要向量化，在中小规模（约 100 个来源、数百个页面）下，依靠两个纯文本文件就足够 LLM 掌控全局：

- index.md（空间维度） —— 知识库的全局目录。每个实体、概念都附带一行简短说明和链接，按类别组织。LLM 回答问题前先扫一眼这个文件，就能精准定位该去读哪些详情页。Karpathy 说这在中等规模下"效果出奇地好"，完全不需要向量数据库和嵌入管线。

- log.md（时间维度） —— 纯粹的 Append-only 日志。记录每一次 Ingest、Query 和 Lint 发生的时间和内容。加上统一的格式前缀（如 ## [2026-04-02] ingest | 文章标题），你甚至可以用简单的 grep 命令分析自己的学习轨迹。新会话开始时，LLM 读一下最近几条日志就能理解当前状态。

# 六、工具链：朴素但实用
Karpathy 的方法不依赖复杂基础设施，甚至可以说极其"朴素"。以下是他提到的工具和它们在系统中的角色：

工具	角色	是否必需
Obsidian	浏览 Wiki 的"前端 IDE"	推荐（任何 Markdown 编辑器都行）
Obsidian Web Clipper	一键将网页文章转为 Markdown	推荐（用于快速采集来源）
LLM Agent（Claude Code / Codex 等）	Wiki 的维护者和查询接口	必需
qmd	本地 Markdown 搜索引擎（BM25 + 向量 + LLM 重排序）	可选（小规模用 index.md 就够）
Marp	从 Wiki 内容生成幻灯片	可选
Dataview	查询页面 frontmatter 生成动态表格	可选
Git	版本控制	推荐

## 几个实用技巧：

- Obsidian Web Clipper 是浏览器扩展，支持 Chrome、Firefox、Safari 等，一键把网页转成干净的 Markdown 并保存到你的 raw/ 目录。
- 本地化图片：在 Obsidian 设置中把附件路径指向 raw/assets/，绑定一个快捷键（如 Ctrl+Shift+D）下载当前文件的所有图片到本地。这样 LLM 可以直接查看图片，不依赖可能失效的 URL。
- Graph View 是观察 Wiki 形态的最佳方式——哪些页面是枢纽、哪些是孤岛，一目了然。
- Git 版本控制：Wiki 就是一个 Markdown 文件的 Git 仓库。你免费获得版本历史、分支、协作能力。git diff 看每次摄入改了什么，git revert 回滚一次糟糕的编译，git blame 追溯某个结论是什么时候加入的。
- 当知识库规模进一步扩大时，qmd（由 Shopify CEO Tobi Lutke 开发）是一个值得关注的工具。它是本地 Markdown 搜索引擎，结合 BM25 全文搜索、向量语义搜索和 LLM 重排序，全部在本地运行，不需要云 API。它同时提供 CLI 和 MCP Server 接口，LLM 可以直接调用。

# 七、"Idea File"：一种新的分享范式
Karpathy 发布的不是代码，不是应用，而是一份"idea file"——一个故意保持抽象的概念文档，设计目的是让你复制粘贴给自己的 LLM Agent，由 Agent 根据你的具体需求去实例化。

他自己的话是："在 LLM Agent 的时代，分享具体的代码或应用已经不那么必要了。你只需要分享想法，然后对方的 Agent 会根据具体需求去定制和构建。"

这是一个微妙但深刻的转变。传统上，开发者分享有用的东西时，分享的是实现：一个 GitHub 仓库、一个 npm 包、一个 Docker 镜像。接收者克隆、配置、运行。但在每个人都有 LLM Agent 的世界里，分享想法可能比分享代码更有用——因为想法是可移植的，而代码是特定的。

Karpathy 用 Obsidian + macOS + Claude Code。你可能用 VS Code + Linux + Codex。一个共享的 GitHub 仓库需要 fork、适配、调试。一份 idea file 复制粘贴给你的 Agent，Agent 就能构建一个适配你环境的版本。

这是开源的一种新形态：不是 open code，而是 open ideas。

# 八、与 NotebookLM 的对比：图书馆阅览室 vs 你的花园
Google NotebookLM 看起来做了很多类似的事情：上传来源、提问、获得综合答案，还能生成播客音频、视频概览、思维导图、闪卡。但架构差异决定了本质不同。

NotebookLM 是一个装备精良的图书馆阅览室。 你带着一摞书进去，高效地工作，离开时房间为下一位访客重置。它的来源默认是静态的——文档变了你得手动删旧传新。没有自主机制会在夜间审计你的笔记本、发现缺口、或在未被要求时跨语料库建议新连接。

Karpathy 的系统是一座你年复一年打理的花园。 新来源进入 raw 文件夹，LLM 增量更新 Wiki，问题的答案被归档为新文章，健康检查发现缺口，整个结构随着每个周期变得更加精密。它是一个活的系统，记住一切，自我构建。

还有一个关键区别：数据主权。Karpathy 的系统以纯文本文件的形式存在于你的电脑上，你完全拥有它们。你可以移动、备份、用本地模型处理、三年后交给一个更好的 AI 工具。Markdown 格式在未来几十年都会被人类和机器可读。而 NotebookLM 存在于 Google 的云端，按 Google 的条款运行。对于一个想要构建长期知识基础设施的人来说，谁控制"文件柜"这个问题并不琐碎。

两者都有价值，但只有一个能产生复利。

# 九、最有深度的批评：Zettelkasten 与"认知摩擦"
Extended Brain 的一篇长文对 LLM Wiki 提出了最有深度的批评，通过与德国社会学家 Niklas Luhmann 的 Zettelkasten（卡片盒笔记法）对比，揭示了一个根本性的张力。

Luhmann 是 20 世纪最高产的社会理论家之一，一生写了 70 多本书和 400 多篇论文。他的秘密武器是一个包含约 9 万张卡片的 Zettelkasten。当他读到有趣的东西时，他会用自己的话重新表述这个想法，并手动将它与已有的卡片建立链接。

表面上，两个系统有很多相似之处：都将原始来源与加工后的知识分离，都认为想法之间的链接比想法本身更有价值，都设计为复利式增长。但差异是根本性的：

对 Luhmann 来说，写卡片的行为不是构建知识库过程中的一个步骤——它就是思考本身。 当你不得不用自己的话表述别人的想法时，那种"翻译不太对劲"的摩擦感，那种暴露出你理解缺口的阻力——这不是需要消除的低效，而是真正的认知整合正在发生的信号。

Extended Brain 引入了一个生物学概念来解释这一点：Hormesis（毒物兴奋效应）。少量的压力——运动、热量、轻微的毒素——会让有机体变得更强壮，而完全消除压力则会让它变弱。肌肉因为被迫挣扎而生长。

一个作家在试图用自己的话表达一个困难想法时遇到的摩擦是 hormetic 的。它不是思考过程中的 bug——它是思考的机制。当你的句子写到一半崩溃了，因为你意识到自己其实并不真正理解你试图解释的概念——那个崩溃就是整个写作过程中最有价值的时刻。

Karpathy 的系统通过设计消除了这种摩擦。LLM 写出流畅、组织良好的综合文章。没有崩溃，没有语言暴露理解缺口的时刻。读这些文章的人可能觉得自己理解了这个主题，拥有了一张出色的地图。但他们没有做过在自己的概念架构中构建理解的 hormetic 工作。

Extended Brain 用了一个犀利的类比：想象你想健身。一种方法是雇一个私人教练替你做体育锻炼，然后向你汇报感受如何。你获得了一张关于健身的详细地图——肌肉群、进阶方式、原理——但你的身体没有做任何工作。Luhmann 的 Zettelkasten 是锻炼本身。Karpathy 的 Wiki 是教练的报告。

## 最佳实践：混合方案
这并不意味着 LLM Wiki 没有价值。最有用的方法是一个混合方案：

- 用 LLM 做地图层：让它构建互联图谱、发现缺口、维护索引、识别跨来源的意外连接。这是领域脚手架，LLM 做得比任何人都好。
- 把综合层留给自己：当 LLM 告诉你两个想法在结构上有关联时，不要读它的综合文章——自己写。用你自己的话去挣扎。这个连接到底意味着什么？它成立吗？哪里会崩溃？如果它是对的，意味着什么？你的声音和你的论点就在这里。
- 重新定位健康检查：不要让 LLM 去解决文章间的不一致——那会产生整洁但过早的闭合。让它发现不一致然后停下来。"这里有三个东西似乎存在张力。" 张力本身就是礼物。

在这个配置下，Wiki 不是你思考的输出，而是你思考的、组织良好的输入。是脚手架，不是建筑。是你即将徒步进入的领地的地图——但地图不等于走过那片土地。

# 十、Memex：一个 80 年前的预言
Karpathy 在原文末尾提到了 Vannevar Bush 1945 年在《大西洋月刊》发表的文章 "As We May Think"。Bush 描述了一个叫 Memex 的假想设备：一个桌面大小的机器，个人可以在上面存储所有的书籍、记录和通信，快速搜索，并创建"关联路径"——文档之间带有个人注释的链接序列。

Bush 的核心洞察是：人类的思维通过关联运作，而不是按字母顺序。他的 Memex 直接启发了 Douglas Engelbart（发明了鼠标和个人计算的概念）、Ted Nelson（1965 年创造了"超文本"一词）、以及 Tim Berners-Lee（1989 年的万维网）。

但正如 Karpathy 观察到的，万维网变成了公开的、混乱的，而不是 Bush 设想的私人的、精心策展的。LLM Wiki 更接近 Bush 的原始愿景：私有的、主动策展的、文档之间的连接与文档本身一样有价值。

Bush 在 1945 年无法解决的那个缺失拼图是：谁来做维护？ 创建关联路径、更新连接、保持一切一致——这是乏味的手工劳动。人类放弃知识系统是因为维护负担的增长速度超过了价值。LLM 不会无聊，不会忘记更新一个交叉引用，一次操作就能触及 15 个文件。Wiki 能持续被维护，因为维护成本接近于零。

# 十一、社区反响与产品化尝试
Karpathy 的帖子在技术社区和企业级市场引发了广泛关注。

- 企业视角：企业家 Vamshi Reddy 评论说："每个企业都有一个 raw 目录。从来没有人把它整理过。这就是产品。" Karpathy 对此表示赞同。目前大多数公司都"淹没"在非结构化数据中——Slack 日志、内部 Wiki、PDF 报告，没有人有时间去综合分析。一个"Karpathy 式"的企业层不仅会搜索这些文档，还会主动编写实时更新的"公司知识圣经"。

- 产品化尝试：一位 X 用户将 Karpathy 的方案成功产品化为 "Claudeopedia"（Claude 百科），在一个周末内完成了：采纳 Karpathy 的 idea file、新增支持截图和下载的 /wiki 技能、构建交互式可视化界面（带日期范围，可对比知识随时间演进的变化）、设置定时任务自动将随笔和客户邮件与 Wiki 内容进行比对复核。

- 社区延伸想法：
    - .brain 文件夹 模式：有开发者分享了一个轻量版方案——在项目根目录放一个 .brain 文件夹，包含 index.md、architecture.md、decisions.md 等，作为 AI 会话间的持久记忆。核心规则："改代码前先读 .brain，改完代码后更新 .brain。"
    - Gist 作为 Agent 间通信通道：有人描述了用 GitHub Gist 在不同 AI Agent 之间传递上下文的做法——开发过程中推送带图表的 Gist，然后在 Claude、Grok 等不同前端之间传递。
    - 规模化挑战：Edra 的 CEO 指出，"从个人研究 Wiki 到企业运营的飞跃才是真正的挑战所在。成千上万的员工，数百万条记录，以及团队间相互矛盾的经验知识。"

# 十二、如何落地：从 0 到 1 的实操路径

## 第一步：搭建目录结构
```bash
mkdir -p my-wiki/raw/articles
mkdir -p my-wiki/raw/papers
mkdir -p my-wiki/raw/assets
mkdir -p my-wiki/wiki/concepts
mkdir -p my-wiki/wiki/entities
mkdir -p my-wiki/wiki/sources
mkdir -p my-wiki/wiki/comparisons
touch my-wiki/wiki/index.md
touch my-wiki/wiki/log.md
touch my-wiki/wiki/overview.md
cd my-wiki && git init
```

## 第二步：创建 Schema 文件
在项目根目录创建 CLAUDE.md（或对应你使用的 Agent 的配置文件），参考第三节的 Schema 示例，根据你的领域定制。

## 第三步：配置 Obsidian
1. 安装 Obsidian，将项目文件夹作为 Vault 打开
2. 安装 Web Clipper 浏览器扩展
3. 设置附件路径为 raw/assets/
4. 绑定下载图片的快捷键
4. 可选安装 Marp、Dataview 插件

## 第四步：摄入第一个来源
1. 用 Web Clipper 剪藏一篇文章到 raw/articles/
2. 打开 LLM Agent，告诉它："摄入 raw/articles/[文件名].md"
3. 阅读摘要，引导重点，确认 Wiki 更新
4. 在 Obsidian 中浏览新页面，检查 Graph View
5. git add . && git commit -m "ingest: [文章标题]"

## 第五步：10 个来源测试
从一个主题的 10 个来源开始。全部摄入后，问一个需要综合多个来源才能回答的问题。如果结构化的 Wiki 给了你一个单独阅读来源时不会获得的洞察，系统就在起作用了。从这里开始扩展。

## 第六步：持续演化
重复摄入过程。10-20 个来源后开始查询。50+ 个来源后考虑加入 qmd 搜索。每周跑一次 Lint 健康检查。持续更新 Schema。

# 十三、总结
Karpathy 的 LLM Wiki 不是一个具体的产品，而是一种模式（pattern）。它的核心洞察是：

人类放弃维护知识库，不是因为不想记录，而是因为维护成本太高。LLM 最不怕的就是体力活——它没有耐心限制，不会漏掉一个超链接，一次操作就能并行处理几十个文件。当维护成本接近于零时，知识库就能真正实现复利式增长。

在这套体系里，分工异常清晰：人类负责收集弹药、把握方向、提出好问题；LLM 负责一切脏活累活。

但也要记住 Extended Brain 的提醒：地图不等于领地。LLM 编译出的 Wiki 是你思考的优质输入，而不是思考本身。最有价值的时刻，仍然是你用自己的话去挣扎、去表达、去发现自己到底相信什么的时刻。

用机器构建地图，然后坚持自己走过那片土地。

# 参考来源：

[Karpathy 原始 Gist: LLM Wiki](research\wiki\karpathy wiki解读.md)
[Antigravity: The Complete Guide to His Idea File](https://antigravity.codes%2Fblog%2Fkarpathy-llm-wiki-idea-file)
[Extended Brain: The Wiki That Writes Itself](https://extendedbrain.substack.com%2Fp%2Fthe-wiki-that-writes-itself)
[MindStudio: How to Build a Personal Knowledge Base With Claude Code](https://www.mindstudio.ai%2Fblog%2Fandrej-karpathy-llm-wiki-knowledge-base-claude-code)
[Analytics Drift: Karpathy's LLM Knowledge Base Workflow](https://analyticsdrift.com%2Fkarpathy-llm-knowledge-base-vibe-coding-workflow)

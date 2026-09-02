# HTML↔MD 映射工作范式指引

> **版本**: v3.0  
> **适用范围**: `宁德时代_V3.0.html`、`model.html` 及后续所有需要加载 MD 内容的 HTML  
> **核心原则**: HTML 只管交互展示，MD 负责内容生成与维护，AI 负责语义高亮标注  
> **通用模块**: `../common/md-loader.js` — 所有 HTML 共享同一套加载逻辑

---

## 一、架构总览

```
┌─────────────────────────────────────────────────────────┐
│                   common/md-loader.js                    │
│  (通用模块：fetch MD+HL → 缓存 → 解析 → 自动注入+高亮)     │
│  MdLoader.init({files, autoPopulate}).then(...)         │
└──────┬──────────────────────────────┬───────────────────┘
       │                              │
       ▼                              ▼
┌──────────────┐              ┌──────────────────┐
│  model.html  │              │ 宁德时代_V3.0.html │
│ (手动模式)    │              │ (自动模式)         │
│              │              │                  │
│ 自行调用      │              │ autoPopulate:true │
│ MdLoader.get()│              │ 自动扫描 .md-     │
│ extractSection│              │ content 元素注入  │
└──────────────┘              └──────────────────┘

文件关系：
  xxx.md          ← 纯文本内容（人读写，AI 生成）
  xxx.hl.json     ← 高亮标注（AI 生成，浏览器读取）
  → 两个文件同目录同名，md-loader.js 自动配对加载
```

**一句话**：所有展示内容都在 MD 里维护，HTML 不硬编码任何业务文字。修改内容 → 改 MD；改交互/样式 → 改 HTML；高亮重点 → AI 生成 `.hl.json`。

---

## 二、通用模块：md-loader.js

### 2.1 位置

```
宁德时代/
├── common/
│   └── md-loader.js          ← 通用模块（本文档核心）
├── 报告/
│   └── 宁德时代_V3.0.html    ← 引用 ../common/md-loader.js
├── 业务/换电/财务模型/
    └── model.html             ← 引用 ../../common/md-loader.js
└── 业务/换电/分析结论/
    ├── CATL换电业务_重构版.md      ← 内容源（纯文本）
    └── CATL换电业务_重构版.hl.json ← 高亮标注（AI 生成）
```

### 2.2 API

| 方法 | 说明 |
|:---|:---|
| `MdLoader.init(config)` | 初始化，自动加载 MD + 高亮文件，返回 Promise |
| `MdLoader.get(key)` | 同步获取已缓存的 MD 原文 |
| `MdLoader.isFileProtocol()` | 判断当前是否 file:// 协议 |
| `MdLoader.extractSection(mdText, anchor, endAnchor, excludeEnd)` | 按标题锚点提取章节 → `{summary, detail}` |
| `MdLoader.extractMdFields(chunk)` | 从浓缩版 chunk 提取 `{title, summary, content}` |
| `MdLoader.mdToHtml(text, highlights)` | Markdown → HTML（段落 + 粗体 + 高亮） |
| `MdLoader.applyHighlights(html, annotations)` | 对 HTML 文本应用语义高亮标注 |

### 2.3 init() 配置参数

```javascript
MdLoader.init({
  files: [                          // 要加载的 MD 文件列表
    { key: '别名', path: '相对路径.md' }
    // 高亮文件路径自动派生：将 .md 替换为 .hl.json
    // 如 'xxx.md' → 'xxx.hl.json'，无需单独配置
  ],
  autoPopulate: true                // 可选，默认 false
  // true  → 自动扫描 DOM 中 .md-content 元素并注入内容+高亮（模式 A）
  // false → 仅加载到缓存，由调用方自行渲染（模式 B）
}).then(function() {
  yourInitFunction();
});
```

---

## 三、使用模式 A：自动注入（研报 HTML）

### 3.1 HTML 引入

```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script src="../common/md-loader.js"></script>  <!-- 通用模块 -->
```

### 3.2 配置与启动

```javascript
MdLoader.init({
  files: [
    { key: '换电业务', path: '../业务/换电/分析结论/CATL换电业务_重构版.md' }
    // 后续新增 MD 文件在这里追加
  ],
  autoPopulate: true
}).then(function() {
  init();  // MD + 高亮加载完成后才执行页面初始化
});
```

### 3.3 子卡模板

```html
<!-- 子卡 {编号} {描述} · 动态引用 MD -->
<div class="sublayer {颜色类} md-content" id="{html-id}"
     data-md-src-key="{文件别名}"
     data-md-section="{section-id}">
  <div class="subhead" onclick="subtoggle('{html-id}', event)">
    <div class="subidx">{编号}</div>
    <div class="subbody">
      <h4 class="md-title">加载中...</h4>
      <div class="suboneliner md-summary">加载中...</div>
    </div>
    <div class="subarr">▼</div>
  </div>
  <div class="subdetail">
    <div class="md-content-body" style="line-height:1.85">加载中...</div>
    <div class="src md-src-ref"></div>
  </div>
</div>
```

### 3.4 子卡属性说明

| 属性 | 说明 | 示例 |
|:---|:---|:---|
| `class="sublayer {颜色类} md-content"` | `md-content` 触发自动注入，`p1`~`p5` 控制左边框颜色 | `sublayer p2 md-content` |
| `data-md-src-key` | 对应 `MdLoader.init()` 中 `files[].key` | `换电业务` |
| `data-md-section` | 对应 MD 中 `### 浓缩版：{section-id}` | `L2 - 2.0` |
| `class="md-title"` | 注入标题（含高亮） | — |
| `class="md-summary"` | 注入摘要（含高亮） | — |
| `class="md-content-body"` | 注入正文（含高亮） | — |
| `class="md-src-ref"` | 注入来源标注 | — |

### 3.5 子卡左边框颜色类

| 类名 | 颜色 | 语义 |
|:---|:---|:---|
| `p1` | 绿色 | 通过/安全/已确认 |
| `p2` | 蓝色 | 中性/战略/概览 |
| `p3` | 琥珀色 | 关注/观察/风险 |
| `p4` | 紫色 | 核心/关键 |
| `p5` | 红色 | 危险/警告 |

---

## 四、使用模式 B：手动渲染（model.html）

model.html 使用 `autoPopulate: false`（默认），自行调用 `MdLoader.get()` 和 `MdLoader.extractSection()` 渲染内容。

```javascript
MdLoader.init({
  files: [
    { key: 'main', path: '../定性分析/换电业务相变与估值影响.md' }
  ]
  // autoPopulate 默认 false
}).then(function() {
  refreshAll();  // 自行渲染
});

// 渲染时可选择性使用高亮
function renderMdSection(containerId, anchor) {
  var mdText = MdLoader.get('main');
  var extracted = MdLoader.extractSection(mdText, anchor);
  var html = MdLoader.mdToHtml(extracted.detail);  // 无高亮
  // 或：var html = MdLoader.mdToHtml(extracted.detail, hlAnnotations);  // 带高亮
}
```

---

## 五、MD 文件约定

### 5.1 浓缩版模块格式（模式 A 专用）

每个可供 HTML 子卡引用的内容块，必须在 MD 中以如下格式组织：

```markdown
### 浓缩版：{section-id}

#### 标题
这里是标题文字（单行）

#### 摘要
这里是摘要文字（单行，用于子卡 folded 状态展示）

#### 内容
这里是正文内容，可以多段落。

段落之间用空行分隔。支持 **粗体** Markdown 语法。
```

### 5.2 section-id 命名规范

格式：`{层级代码} - {子卡编号}`

| 示例 | 含义 |
|:---|:---|
| `L2 - 2.0` | 第二层逻辑的第 2.0 号子卡 |
| `L3 - 3.1` | 第三层逻辑的第 3.1 号子卡 |

**规则**：
- 层级代码与 HTML 中 `id="l{n}"` 的层级对应
- 一个 MD 文件可包含多个 `### 浓缩版` 模块

### 5.3 浓缩版字段说明

| 字段 | Markdown 标记 | 用途 | 必须 |
|:---|:---|:---|:---|
| 标题 | `#### 标题` | 子卡 folded 状态的主标题 | 是 |
| 摘要 | `#### 摘要` | 子卡 folded 状态的一行描述 | 是 |
| 内容 | `#### 内容` | 子卡展开后的正文 | 是 |

### 5.4 MD 纯文本原则

**MD 文件必须保持纯文本**，不含任何 HTML 标签或颜色标记：
- MD 可独立作为文档阅读，不依赖 HTML
- 高亮由 AI 通过 `.hl.json` 文件实现，不污染 MD 原文
- MD 中可正常使用 `**粗体**` 等 Markdown 标准语法

---

## 六、语义高亮标注系统

### 6.1 设计理念

| 问题 | 解决方案 |
|:---|:---|
| MD 是纯文本，没有颜色信息 | AI 生成 `.hl.json` 高亮标注文件 |
| 浏览器端没有 LLM，无法语义分析 | 标注在 AI 写 MD 时同步生成，浏览器只负责应用 |
| 已审批的内容不应被改动 | JSON 文件持久化标注，更新时只改变动部分 |

### 6.2 文件约定

- 高亮文件与 MD 文件**同目录、同名**，扩展名为 `.hl.json`
- md-loader.js 在 `init()` 时自动 fetch（路径 = MD 路径 `.md` → `.hl.json`）
- 高亮文件**可选**：不存在时内容正常加载，只是没有高亮

```
CATL换电业务_重构版.md          ← 纯文本内容
CATL换电业务_重构版.hl.json     ← AI 生成的高亮标注
```

### 6.3 JSON 格式

```json
{
  "L2 - 2.0": {
    "title": [
      {"text": "未被定价", "color": "amber"},
      {"text": "换电", "color": "accent"}
    ],
    "summary": [
      {"text": "网络密度是关键", "color": "accent"},
      {"text": "观察窗口", "color": "amber"}
    ],
    "content": [
      {"text": "至今未被资本市场充分定价——换电", "color": "red"},
      {"text": "资产属性和业务属性将从"制造业"转变为"资本运营业"", "color": "green"}
    ]
  }
}
```

**结构说明**：
- 顶层 key = section-id（与 MD 中 `### 浓缩版：{section-id}` 对应）
- 每个 section 下分 `title` / `summary` / `content` 三个字段
- 每个字段是数组，元素为 `{text, color}`
- `text` = MD 中实际出现的文本片段（不含 `**` 等 Markdown 标记）
- `color` = 颜色名（见 6.4）

### 6.4 颜色语义约定

| 颜色名 | CSS 变量 | 语义 | 典型场景 |
|:---|:---|:---|:---|
| `red` | `--red` | 风险/负面/阻碍 | 失血、衰退、锁定、尚未、极高(成本) |
| `green` | `--green` | 正面/优势/进展 | 转正、加速、最优、唯一、升维 |
| `amber` | `--amber` | 关注/不确定/博弈 | 不确定、博弈、风险、观察窗口 |
| `accent` | `--accent` | 关键概念/数字 | 换电网络、电池银行、10万座、引号内容 |
| `purple` | `--purple` | 核心论点 | 极少使用，预留 |

### 6.5 标注生成规则（AI 执行）

AI 在生成 `.hl.json` 时遵循以下规则：

1. **语义识别**：基于对内容的语义理解，识别表达关键含义的词句
2. **颜色选择**：按 6.4 的语义约定选择颜色，不凭个人偏好
3. **长短优先**：优先标注短语（2-12 字），避免整句标注
4. **避免过度**：每段标注不超过 5-8 处，保持视觉重点突出
5. **不跨标记**：标注文本不跨越 `**粗体**` 边界，与渲染后文本一致
6. **数字突出**：关键数字+单位（如"10万座"）用 `accent` 标注

### 6.6 渲染机制

md-loader.js 的工作流程：

```
init() 同时 fetch MD + .hl.json
  ↓
_autoPopulate() 扫描 .md-content 元素
  ↓
对每个子卡：
  1. 从 MD 提取浓缩版字段（标题/摘要/内容）
  2. 从 .hl.json 取该 section 的高亮标注
  3. 标题/摘要：直接 applyHighlights(纯文本, 标注) → innerHTML
  4. 内容：mdToHtml(文本, 标注) → 先转 **粗体** → 再应用高亮 → innerHTML
  ↓
applyHighlights() 内部：
  · 按标注文本长度降序排列（长词优先，避免短词覆盖）
  · 用占位符替换文本（防止重复匹配）
  · 仅替换 HTML 标签外的文本（不破坏标签结构）
  · 占位符 → <span style="color:var(--xxx);font-weight:600">
```

---

## 七、操作流程

### 7.1 新增 MD 文件作为内容源

1. **写 MD**：在 MD 文件中按 5.1 格式编写浓缩版模块
2. **生成高亮**：AI 分析 MD 内容，生成同目录 `.hl.json` 文件
3. **配置 HTML**：在 `MdLoader.init({ files: [...] })` 中追加 `{ key: '别名', path: '路径.md' }`
4. **加子卡**：在 HTML 中插入子卡模板，设置 `data-md-src-key` + `data-md-section`

### 7.2 修改已有子卡内容

1. 找到子卡 HTML 中 `data-md-src-key` 和 `data-md-section` 的值
2. 在对应 MD 文件中找到 `### 浓缩版：{section-id}` 模块
3. 修改 `#### 标题` / `#### 摘要` / `#### 内容` 下的文字
4. **同步更新高亮**：AI 只为改动的部分重新生成标注，未改动的标注保持不变
5. 刷新 HTML 即可

### 7.3 新增子卡

1. **MD 侧**：在 MD 文件中添加 `### 浓缩版：{section-id}` 模块
2. **高亮侧**：AI 在 `.hl.json` 中添加该 section 的标注
3. **HTML 侧**：插入子卡模板（见 3.3），填入 `data-md-src-key`、`data-md-section`、`id`、编号

### 7.4 高亮标注的增量更新（核心工作流）

**原则**：已审批的标注不被改动，只更新变动部分。

```
场景：用户要求修改 L2-2.0 的摘要

AI 执行步骤：
  1. 读取 MD，修改摘要文本
  2. 读取现有 .hl.json
  3. 只为 "L2 - 2.0".summary 重新生成标注
  4. 其他字段（title, content）和其他 section 的标注保持不变
  5. 合并写入 .hl.json

用户只需审阅：摘要部分的高亮是否满意
```

---

## 八、注意事项

### 8.1 HTTP 服务要求

`fetch()` 在 `file://` 协议下无法读取本地文件。必须通过 HTTP 服务打开 HTML：

- **VS Code**: 安装 Live Server 插件，右键 → Open with Live Server
- **命令行**: `python -m http.server 8080` 或 `npx serve .`
- **model.html 专用**: 双击 `open-model.bat` 启动内置 HTTP 服务

### 8.2 路径规则

- `MdLoader.init()` 中 `path` 使用相对于 HTML 文件的路径
- 高亮文件路径自动派生（`.md` → `.hl.json`），无需单独配置
- 路径分隔符统一使用 `/`（不要用 `\`）

### 8.3 编码要求

- MD 文件和 .hl.json 文件必须使用 UTF-8 编码
- .hl.json 必须是合法 JSON（注意转义引号）

### 8.4 内容格式

- 正文支持多段落（空行分隔）
- 支持 `**粗体**` Markdown 语法
- 不支持表格、列表、链接等复杂 Markdown（后续版本扩展）

---

## 九、当前映射关系清单

| 子卡 | HTML id | key | MD 文件 | 高亮文件 | section-id |
|:---|:---|:---|:---|:---|:---|
| 2.0 换电未被定价 | `l2-0` | `换电业务` | `../业务/换电/分析结论/CATL换电业务_重构版.md` | `../业务/换电/分析结论/CATL换电业务_重构版.hl.json` | `L2 - 2.0` |
| 2.1 生死战论证 | `l2-1` | *(硬编码，待迁移)* | — | — | — |
| 2.2 战略协同 | `l2-2` | *(硬编码，待迁移)* | — | — | — |

> 后续子卡逐步迁移至 MD 动态引用模式，更新此清单。

---

## 十、后续扩展方向

- [ ] 支持更丰富的 Markdown 语法（表格、列表、链接）
- [ ] 支持 MD 元数据头（YAML front matter）声明 section
- [ ] 热更新：MD 文件变化时自动刷新对应子卡
- [ ] model.html 迁移到 md-loader.js（目前仍使用内联加载器）
- [ ] 沉淀为 Trae Skill 文档，支持 AI 自动执行
---
title: 方法论_Karpathy_LLM_Wiki_原文
type: source-summary
sources: [karpathy gist llm wiki.md]
related: [Memex, LLM Wiki方法论, Zettelkasten]
created: 2026-04-10
updated: 2026-04-10
confidence: high
tags: [Karpathy, LLM Wiki, 知识管理, 方法论]
---

# Karpathy LLM Wiki 原文摘要

> **来源**：[GitHub Gist](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f)  
> **作者**：Andrej Karpathy  
> **类型**：Idea File（概念文档，非具体实现）  
> **Ingest日期**：2026-04-10  

---

## 核心思想

**LLM不应该是RAG式的"阅后即焚"，而应该增量构建并维护一个持久化的Wiki——一个结构化、相互链接的Markdown文件集合，位于你和原始资料之间。**

关键差异：Wiki是持久的、复利式增长的知识资产。交叉引用已建好，矛盾已被标记，综合判断已反映你读过的所有内容。

## 三层架构

| 层 | 名称 | 谁拥有 | 职责 |
|---|------|--------|------|
| Raw Sources | 原始数据层 | 用户（不可变） | 真理之源，LLM只读 |
| The Wiki | 编译输出层 | **LLM完全控制** | 摘要/实体/概念/对比/综合 |
| The Schema | 控制协议层 | **用户+LLM共同演化** | CLAUDE.md等配置文件 |

## 四大操作流程

### Ingest（摄入与编译）
- 新source进入 → LLM阅读 → 与用户讨论要点 → 写入Wiki → 更新实体/概念页 → 追加log
- 单个source可能触发10-15个Wiki页面更新
- Karpathy偏好逐个摄入、全程参与（可批量但需记录到Schema）

### Query（查询与沉淀）
- 先读index定位候选 → 读取确认 → 综合回答带引用
- **好的答案应归档为新Wiki页面**（复利循环）
- 输出形式灵活：markdown/表格/幻灯片(Marp)/图表(matplotlib)/画布

### Lint（健康检查）
- 矛盾检测 / 孤岛页面 / 缺失概念 / 过时结论 / 数据缺口
- LLM擅长建议新问题和新方向
- 动词是"Look for"/"suggesting"，不是"fix"

### 辅助文件
- **index.md**：空间维度，内容目录，~100 sources规模下效果出奇地好
- **log.md**：时间维度，append-only日志，统一前缀格式便于grep解析

## 适用场景

个人目标追踪、深度研究（数周/月）、读书笔记（类Tolkien Gateway）、企业内部Wiki、竞品分析、尽职调查、旅行规划、课程笔记、爱好深挖

## 关键洞察

1. **人类放弃Wiki的原因不是缺乏意愿，而是维护成本指数增长**
2. **LLM不会无聊、不会忘记更新交叉引用、一次能触及15个文件**
3. **与Vannevar Bush的Memex(1945)一脉相承**：Bush解决了"是什么"，LLM解决了"谁维护"
4. **文档故意保持抽象**：具体实现取决于领域/偏好/LLM选择，所有模块可选可组合

## 工具链（可选）

Obsidian + Web Clipper + LLM Agent(Claude Code/Codex) + qmd(本地搜索) + Marp(幻灯片) + Dataview(frontmatter查询) + Git(版本控制)
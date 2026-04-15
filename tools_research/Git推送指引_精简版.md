# Git 操作指南（实战版）

> **更新时间**：2026-04-13
> **基于真实场景**：今天恢复 tools_research 的完整过程

---

## 一、当前仓库状态（必读）

### 你的仓库信息

```
本地位置：d:\AI\证券投资
远程地址：https://github.com/kedouzc/investment.git
分支名称：main
```

### 目录结构

```
d:\AI\证券投资\
├── wiki/                    # Wiki 知识库（LLM 领地）
├── 投研/                    # 投资研究（你的领地）
├── 平行宇宙智能仓位决策引擎/ # 投资工具
├── tools_research/          # AI 工具研究（已恢复 ✅）
│   ├── claude/
│   ├── gstack/
│   ├── wiki/
│   └── *.md 文件
└── 其他文件...
```

### 重要说明

- **统一管理原则**：所有内容都在 `d:\AI\证券投资` 这个仓库里
- **不再使用符号链接/Junction**：tools_research 直接放在当前目录
- **远程仓库**：GitHub 私有仓库 `kedouzc/energy-research`

---

## 二、日常 Git 操作（最常用）

### 📋 场景 1：查看当前状态

```powershell
# 进入仓库目录
cd "d:\AI\证券投资"

# 查看状态（哪些文件被修改了）
git status

# 查看最近的提交记录
git log --oneline -10
```

**输出解读**：
- `Changes not staged for commit` = 你修改了但还没告诉 Git
- `Untracked files` = 新文件，Git 还不知道
- `On branch main` = 当前在 main 分支

---

### 📋 场景 2：保存修改到本地（commit）

```powershell
cd "d:\AI\证券投资"

# 第1步：查看改了什么
git status

# 第2步：添加要保存的文件（3种方式）

# 方式 A：添加所有修改
git add .

# 方式 B：只添加某个文件
git add "tools_research/某个文件.md"

# 方式 C：只添加某个目录
git add tools_research/

# 第3步：写说明并保存
git commit -m "简要说明你做了什么"
```

**示例**：
```powershell
git add tools_research/
git commit -m "更新 AI 工具研究文档"
```

---

### 📋 场景 3：推送到 GitHub（push）

```powershell
cd "d:\AI\证券投资"

# 先确保已经 commit 了
git status
# 应该显示 "nothing to commit, working tree clean" 或只有 Untracked files

# 推送到 GitHub
git push origin main
```

**⚠️ 注意**：
- 需要代理软件运行中（Clash/V2Ray 等）
- 如果提示用户名密码，输入 GitHub 账号或 Personal Access Token

---

### 📋 场景 4：从 GitHub 拉取最新版本（pull）

```powershell
cd "d:\AI\证券投资"

# 拉取远程最新代码（会合并到本地）
git pull origin main
```

**⚠️ 警告**：
- `git pull` 会拉取**所有文件**
- 如果你在本地有未提交的修改，可能会产生冲突
- 如果只想恢复某个文件/目录，用场景 5

---

## 三、高级操作（按需使用）

### 📋 场景 5：只恢复某个文件/目录（不覆盖其他文件）

**适用情况**：
- 某个文件误删了，想从 GitHub 恢复
- 只想更新某个目录，不想影响其他正在编辑的文件

**今天实际使用的命令**：

```powershell
cd "d:\AI\证券投资"

# 第1步：从远程获取最新信息（不改变本地任何文件）
git fetch origin

# 第2步：只恢复指定的文件或目录
# 恢复单个文件
git checkout origin/main -- "tools_research/某个文件.md"

# 恢复整个目录
git checkout origin/main -- tools_research
```

**✅ 优点**：
- 不影响其他未提交的修改
- 只更新你指定的部分
- 安全，不会丢失工作成果

---

### 📋 场景 6：撤销本地修改（回退到上次提交的状态）

```powershell
cd "d:\AI\证券投资"

# 撤销某个文件的修改（未 add 前）
git restore "某个文件.md"

# 撤销某个文件的修改（已 add 但未 commit）
git restore --staged "某个文件.md"
git restore "某个文件.md"

# 撤销所有修改（危险！）
git restore .
```

**⚠️ 警告**：`git restore .` 会丢弃所有未提交的修改，慎用！

---

### 📋 场景 7：查看历史版本

```powershell
cd "d:\AI\证券投资"

# 查看某个文件的修改历史
git log --oneline "tools_research/某个文件.md"

# 查看某次提交改了什么
git show <commit-id>

# 恢复文件到某个历史版本
git checkout <commit-id> -- "tools_research/某个文件.md"
```

---

## 四、常见问题解决（今天踩过的坑）

### ❌ 问题 1：Git 锁文件残留

**错误信息**：
```
fatal: Unable to create '.git/index.lock': File exists.
Another git process seems to be running in this repository
```

**原因**：上次 Git 操作异常中断（崩溃、强制关闭等）

**解决方案**：
```powershell
# 删除锁文件（安全，只是临时文件）
Remove-Item "d:\AI\证券投资\.git\index.lock" -Force
```

**说明**：锁文件是 Git 的临时文件，删除完全安全，不影响任何数据。

---

### ❌ 问题 2：无法连接 GitHub（网络问题）

**错误信息**：
```
fatal: unable to access 'https://github.com/...':
Failed to connect to github.com port 443 via 127.0.0.1
Could not connect to server
```

**原因**：系统配置了代理（127.0.0.1:7897），但代理软件没有运行

**解决方案**：

**方案 A**：启动代理软件（推荐）
- 打开 Clash for Windows / V2RayN / 其他代理工具
- 确认运行正常且监听端口是 7897
- 重新执行 Git 命令

**方案 B**：临时取消代理直连
```powershell
# 取消代理环境变量
$env:HTTP_PROXY=""
$env:HTTPS_PROXY=""

# 执行 Git 命令
git push origin main
```

**检查当前代理设置**：
```powershell
$env:HTTP_PROXY
$env:HTTPS_PROXY
# 如果有输出，说明设置了代理
```

---

### ❌ 问题 3：符号链接/Junction 导致 checkout 失败

**错误信息**：
```
error: unable to create file tools_research/xxx.md: No such file or directory
fatal: cannot create directory at 'tools_research/xxx': No such file or directory
```

**原因**：`tools_research` 是一个 Junction 符号链接，不是真实目录

**诊断方法**：
```powershell
# 检查是否是链接
(Get-Item "d:\AI\证券投资\tools_research").Attributes
# 如果输出包含 "ReparsePoint"，就是链接

# 查看链接指向哪里
(Get-Item "d:\AI\证券投资\tools_research").Target
```

**解决方案**：
```powershell
# 删除链接（不会删除目标文件夹的数据）
Remove-Item "d:\AI\证券投资\tools_research" -Force -Recurse

# 从 GitHub 重新创建真实目录
git checkout origin/main -- tools_research
```

---

### ❌ 问题 4：远程引用无效

**错误信息**：
```
fatal: invalid reference: origin/main
```

**原因**：本地没有远程分支的引用信息

**解决方案**：
```powershell
# 先获取远程信息
git fetch origin

# 再执行操作
git checkout origin/main -- tools_research
```

---

## 五、完整工作流程示例

### 示例 1：日常编辑后推送

```powershell
# 1. 进入目录
cd "d:\AI\证券投资"

# 2. 编辑了一些文件...

# 3. 查看状态
git status

# 4. 添加修改
git add .

# 5. 提交
git commit -m "更新了 xxx 文档"

# 6. 推送（确保代理开启）
git push origin main
```

### 示例 2：误删文件后恢复（今天的情况）

```powershell
# 1. 发现 tools_research 被删除了
ls "d:\AI\证券投资\tools_research"
# 报错：不存在

# 2. 检查是否有 Git 锁
Test-Path "d:\AI\证券投资\.git\index.lock"
# 如果存在，先删除
Remove-Item "d:\AI\证券投资\.git\index.lock" -Force

# 3. 从远程获取信息
git fetch origin

# 4. 只恢复 tools_research（不影响其他文件）
git checkout origin/main -- tools_research

# 5. 验证恢复结果
ls "d:\AI\证券投资\tools_research"
```

### 示例 3：只想同步某个文件

```powershell
cd "d:\AI\证券投资"

# 正在编辑其他文件，但想从 GitHub 更新某个特定文件
git fetch origin
git checkout origin/main -- "wiki/问题原点.md"
```

---

## 六、关键概念解释（新手友好）

### 什么是 Git？

Git 是一个**版本控制系统**，可以：
- 记录文件的每次修改
- 随时回到历史版本
- 多人协作时不冲突
- 备份到云端（GitHub）

### 核心概念对照表

| 概念 | 类比 | 说明 |
|------|------|------|
| **Repository（仓库）** | 项目文件夹 | 存放代码和文件的地方 |
| **Commit（提交）** | 保存存档 | 记录当前的修改 |
| **Push（推送）** | 上传到云盘 | 把本地提交上传到 GitHub |
| **Pull（拉取）** | 从云盘下载 | 把 GitHub 最新内容下载下来 |
| **Fetch（获取）** | 检查更新 | 只下载信息，不改变本地文件 |
| **Checkout（检出）** | 恢复文件 | 从某个版本恢复文件 |
| **Branch（分支）** | 平行宇宙 | 可以同时尝试多个方向 |
| **Origin** | 云端地址 | 远程仓库的别名 |

### 工作流程图

```
工作区（你编辑文件的地方）
    ↓ git add （告诉 Git 要保存哪些文件）
暂存区（准备提交的文件）
    ↓ git commit （正式保存到本地）
本地仓库（本地的版本历史）
    ↓ git push （上传到云端）
GitHub（云端备份）
```

---

## 七、快速参考卡

### 最常用的 5 个命令

```powershell
git status          # 查看状态
git add .           # 添加所有修改
git commit -m "说明" # 提交
git push origin main # 推送到 GitHub
git pull origin main # 从 GitHub 拉取
```

### 只恢复某个文件（不覆盖其他）

```powershell
git fetch origin
git checkout origin/main -- "文件路径"
```

### 出错了怎么办？

1. **先看错误信息**（复制给 AI 或搜索）
2. **检查代理**（Clash 是否运行？）
3. **检查锁文件**（`.git/index.lock` 是否存在？）
4. **不要慌**（Git 几乎不会丢数据）

---

## 八、注意事项

### ⚠️ 绝对不要做的事

1. **不要手动删除 `.git` 文件夹**（会丢失所有版本历史）
2. **不要在 Git 外面移动/重命名已跟踪的文件**（会导致 Git 追踪失败）
3. **不要 force push 除非你知道在做什么**（会覆盖他人的工作）

### ✅ 推荐的做法

1. **经常 commit**（每完成一个小功能就提交一次）
2. **写清楚的 commit message**（方便以后回顾）
3. **push 前先 pull**（避免冲突）
4. **重要操作前先备份**（虽然 Git 本身就是备份）

---

## 九、与旧版指引的区别

### 旧版的问题

❌ 太复杂（涉及 subtree、多仓库合并）  
❌ 基于假设场景（WSL 环境、不存在的路径）  
❌ 操作步骤不清晰  
❌ 没有包含常见问题  

### 新版的改进

✅ 基于真实场景（今天的实际操作）  
✅ 使用 Windows PowerShell 命令  
✅ 包含完整的故障排查  
✅ 提供具体示例  
✅ 新手友好的概念解释  

---

## 十、需要帮助？

如果遇到问题：

1. **查看本文档的"常见问题解决"章节**
2. **复制完整错误信息**给 AI 分析
3. **记住**：Git 几乎不会真正丢失数据，大胆尝试

---

> **最后更新**：2026-04-13
> **基于**：恢复 tools_research 的真实操作过程

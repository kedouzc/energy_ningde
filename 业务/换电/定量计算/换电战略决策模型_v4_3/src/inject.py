"""叙述层装配：占位符检查 → 注入 → 待复核判定。

三件事，都在这里：

1. **裸数字检查（lint）**
   叙述源文件（``narrative/*.src.md``）里不允许出现字面数字。
   数字只能写成 ``{{换电增量价值合计}}``（规范写法，带单位）或
   ``{{换电增量价值合计:n}}``（只要数字，用于表格列已标单位的场合）。
   白名单：年份、章节号、版本号、有序列表序号、行内代码与代码块。

   名字一律**中文名**（``{{可归因换电增量价值}}``），写内部 key（``{{val.swap_increment}}``）
   由 ``lint_names`` 拦下——理由见 README「写 MD 一律写中文名」。

2. **注入（inject）**
   用 facts.json 把占位符换成真值，写出最终 md。
   改一个参数重跑，所有数字自动更新，不需要重写一个字。

3. **占位符不许写程序内部名（`lint_names`）**
   占位符一律写**中文名**：输出字典写 `configs/metrics.toml` 的 `label`，手写事实
   写 `src/facts.py` 的 `label`。写 `{{base.wacc}}` 这种内部 key 一律中断并点名。
   例外只有一类：`src.*` 信源——它的名字是 `audit/信源审计台账.md` 的机读主键。

4. **待复核（review）**
   每个段落记住它引用了哪些事实、当时的值是多少（存 narrative_state.json）。
   重跑后某个事实的相对变动超过它的 watch 阈值，或文字类事实变了，
   引用它的段落被标成「待复核」——数字自动更新，但**判断需要人重看**。

单独运行：
    python src/inject.py                     # 处理 narrative/ 下全部 .src.md
    python src/inject.py --lint-only         # 只做裸数字检查，不写文件
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

ROOT = Path(__file__).resolve().parent.parent
NARRATIVE_DIR = ROOT / "narrative"
OUTPUT_DIR = ROOT / "outputs"
FACTS_PATH = OUTPUT_DIR / "facts.json"
STATE_PATH = OUTPUT_DIR / "narrative_state.json"

# 占位符：既认内部 key（swap.coverage），也认**中文名**（年换电交易电量）。
# 中文名里可能含空格与斜杠（如"站内装机GWh / 最新储能装机"），故用"非 {} 与冒号"的宽匹配。
# 这一条是"语义寻址"的入口：写论述的人不必知道程序里那个数叫什么。
TOKEN_RE = re.compile(r"\{\{\s*([^{}:]+?)\s*(?::\s*([a-z]+)\s*)?\}\}")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
LINK_TARGET_RE = re.compile(r"\]\([^)]*\)")   # 链接目标里的文件名／锚点不算正文数字

# CJK 统一汉字「基本区」码位区间：一＝U+4E00、鿿＝U+9FFF（这不是乱码——
# 鿿 是 U+9FFF 这个汉字的字形，多数字体里不显形，但码位真实有效）。
# 用途（lint_names）：占位符名里只要含一个汉字，就认定它是给人读的中文名并放行；
# 纯 ASCII 的内部 key（如 {{swap.ebitda}}）一律判违规并点名，`src.*` 信源键除外。
# 判据是"含不含汉字"而不是"是不是合法 label"——合法性留给 lab.resolve 在注入时寻址，
# 这里只管把"写程序内部名"的形态在 lint 阶段拦下来。
CJK_RE = re.compile(r"[一-鿿]")

# 允许出现的数字：年份、章节/小节号、版本号、有序列表序号、表格分隔线
WHITELIST = [
    re.compile(r"\d{4}-\d{2}-\d{2}[a-z]?"),                              # DECISIONS 条目号 2026-09-05e
    re.compile(r"(?:19|20)\d{2}(?:\s*[-–—/]\s*(?:19|20)?\d{2})?\s*年?"),  # 2026 / 2026–2030 / 2026年
    re.compile(r"§\s*\d+(?:\.\d+)*"),                                      # §4.2.1
    # 【2026-09-14 修】原为 `\bv?\d+(?:\.\d+)+\b`，`v` 可选 ⇒ **它吃掉了所有小数**：
    # 850.4 / 1.17 / 0.30 / 2.26 / 38.4% 全部静默放行，而这正是本报告绝大多数关键读数的形态。
    # 裸数字 lint 一直是绿的，不是因为它拦住了什么，是因为人一直在自觉写占位符——
    # **一道会放行主要目标的检查，等于没有检查。** 现在版本号必须带 v 前缀。
    re.compile(r"\bv\d+(?:\.\d+)+\b"),                                     # v4.3（必须带 v）
    re.compile(r"\d+(?:\.\d+)+\s*[节章]"),                                   # 1.2 节 / 4.3 章
    re.compile(r"^\s{0,3}\d{1,2}[.)、]\s"),                                # 有序列表 1. 2)
    re.compile(r"^\s*\|?[\s:|-]*$"),                                       # 表格分隔线
    re.compile(r"第\s*[一二三四五六七八九十百零〇\d]+[A-Z]?\s*[章节部分步条项层]"),  # 第三章 / 第 2 步 / 第 3A 章
    # 标题里的章号："# 0 决策卡" / "## 3A 谁是真用户"。编号是导航件不是数据，
    # 不允许的话，八章正文的每一行标题都会误报裸数字（2026-09-11 立八章骨架时踩到）。
    # 2026-09-14：允许 `### 2.1 小节标题` 这类带点的标题编号（收紧版本号白名单后暴露）。
    re.compile(r"^\s{0,3}#{1,6}\s*\d{1,2}(?:\.\d{1,2})*[A-Z]?(?=\s|$)"),
    re.compile(r"\|\s*\*{0,2}\d{1,2}\s*[·.、)]"),                          # 表格单元格里的序号 | **1 · |
    re.compile(r"[（(]\s*[①-⑳\d]+\s*[）)]"),                               # (1) （②）
    re.compile(r"\bQ\d\b"),                                                # Q1 Q2 必答问题编号
]
DIGIT_RE = re.compile(r"\d")


# ─────────────────────────────────────────── 检查
def _strip_protected(line: str) -> str:
    """把不参与检查的部分挖空：占位符、行内代码、白名单片段。"""
    text = TOKEN_RE.sub(" ", line)
    text = LINK_TARGET_RE.sub("] ", text)
    text = INLINE_CODE_RE.sub(" ", text)
    for pattern in WHITELIST:
        text = pattern.sub(" ", text)
    return text


def lint(path: Path) -> list[tuple[int, str]]:
    """返回 [(行号, 原始行)]，全部是含裸数字的行。空列表 = 通过。"""
    problems: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate(path.read_text("utf-8").splitlines(), 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if DIGIT_RE.search(_strip_protected(line)):
            problems.append((lineno, line.strip()))
    return problems


# 占位符名里允许不是中文的**唯一**一类：`src.*` 信源。
# 理由：它的名字是 audit/信源审计台账.md「信源索引（机读）」表的主键——
# 要引的是"台账里那一行"（名称/URL/抓取日期/分级四件套），不是某个数；
# 它的中文名（label）是整句信源名，写进占位符反而不可读。
NAME_WHITELIST_PREFIX = ("src.",)


def lint_names(path: Path, facts: dict | None = None) -> list[tuple[int, str]]:
    """返回 [(行号, 原始行)]：占位符写了**程序内部 key** 的行。空列表 = 通过。

    判据是"这个名字在事实包/输出字典里是 key 而不是 label"：
    能按 key 直接命中 → 它写的是内部名 → 报错。于是 `{{EBITDA}}`、`{{WACC}}`
    这类本身就叫这个名字的 label 不会被误伤，误伤会让人绕开检查。
    """
    keys = set(facts or {})
    if not keys:
        try:
            from lab import METRIC_BY_KEY           # 延迟 import，避免与 lab 形成环
            keys |= set(METRIC_BY_KEY)
        except Exception:                            # noqa: BLE001
            pass
    problems: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate(path.read_text("utf-8").splitlines(), 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        text = INLINE_CODE_RE.sub(" ", line)        # 行内代码里的 `{{key}}` 是示例，不是引用
        for m in TOKEN_RE.finditer(text):
            name = (m.group(1) or "").strip()
            if CJK_RE.search(name) or name.startswith(NAME_WHITELIST_PREFIX):
                continue
            if name in keys or (not keys and re.fullmatch(r"[a-z_][A-Za-z0-9_.]*", name)):
                problems.append((lineno, line.strip()))
                break
    return problems


# ─────────────────────────────────────────── 中文名寻址
def label_index(facts: dict) -> dict[str, list[str]]:
    """中文名（label）→ 事实 key 列表。

    为什么要有这一条：`facts` 的**键**是程序内部名（`base.wacc`），而纪律要求 MD 里
    一律写中文名。此前只有输出字典的指标支持中文名（`lab.resolve`），手写事实
    （`base.*` / `q1.*` / `thr.*` / `ext.*` / `src.*`）只能写内部 key——于是"写中文名"
    这条规矩在一多半事实上根本做不到。现在按 label 反查，两类事实一个写法。
    """
    idx: dict[str, list[str]] = {}
    for k, f in facts.items():
        lb = (f.get("label") or "").strip()
        if lb:
            idx.setdefault(lb, []).append(k)
    return idx


_AMBIGUOUS_SEEN: set[str] = set()


def _pick(name: str, keys: list[str], facts: dict) -> str | None:
    """中文名撞名时挑一条；挑不出来返回 None（由调用方报错，绝不静默取第一个）。

    顺序是**判据而不是偏好**：
      ① 手写事实（`origin` 为 fact / ext / src）优先于字典自动并入的指标——
         手写事实带显式 kind 与口径 note（如"峰值年"按年渲染不加千分位），
         字典合并项只有单位推断；
      ② 剩下的若渲染结果完全相同（互为镜像的两条），取哪条都一样；
      ③ 都不满足 → None：撞名且渲染不同，必须去 facts.py / metrics.toml 改开 label。
    """
    if len(keys) == 1:
        return keys[0]
    hand = [k for k in keys if (facts[k].get("origin") or "fact") != "metric"]
    if len(hand) == 1:
        _warn_ambiguous(facts, name, keys, hand[0])
        return hand[0]
    if len({facts[k].get("text") for k in keys}) == 1:
        _warn_ambiguous(facts, name, keys, keys[0])
        return keys[0]
    return None


def _warn_ambiguous(facts: dict, name: str, keys: list[str], picked: str) -> None:
    """撞名要**看得见**：静默取一条，等于把"一词一名"的破口藏起来。报一次就够。"""
    if name in _AMBIGUOUS_SEEN:
        return
    _AMBIGUOUS_SEEN.add(name)
    print(f"  · 中文名「{name}」在事实包里对应 {'/'.join(keys)}，本次取 {picked}"
          f"（渲染「{facts[picked].get('text')}」）。"
          f"要根治就把 src/facts.py 或 configs/metrics.toml 的 label 改开（一词一名）")


# ─────────────────────────────────────────── 注入
def inject(text: str, facts: dict) -> tuple[str, list[str]]:
    """替换占位符，返回 (结果文本, 未知key列表)。

    查找顺序：**facts 精确 → facts 的中文名 → 输出字典（中文名／key／容错）**。
    精确优先是为了不破坏既有写法（内部 key 仍然认）；中文名是给人写的，
    字典是"模型算得出什么"的唯一真相，找不到就进 unknown（由调用方报错并给出候选）。
    """
    unknown: list[str] = []
    index = label_index(facts)

    def _sub(m: re.Match) -> str:
        key, mode = (m.group(1) or "").strip(), (m.group(2) or "")
        fact = facts.get(key)
        if fact is None and key in index:
            picked = _pick(key, index[key], facts)
            if picked is None:
                unknown.append(f"{key}（中文名撞名且渲染不同：{'/'.join(index[key])}）")
                return m.group(0)
            fact = facts.get(picked)
        if fact is not None:
            return fact["bare"] if mode == "n" else fact["text"]
        # 退一步：去输出字典里按中文名找（语义寻址），拿到它的内部 key 再取值
        try:
            from lab import resolve                    # 延迟 import，避免与 lab 形成环
            metric = resolve(key)
        except Exception:
            unknown.append(key)
            return m.group(0)
        fact = facts.get(metric.key)
        if fact is None:
            unknown.append(key)
            return m.group(0)
        return fact["bare"] if mode == "n" else fact["text"]

    return TOKEN_RE.sub(_sub, text), unknown


def metric_unknown_detail(names: list[str]) -> list[str]:
    """把"找不到的占位符"变成**能照着改**的提示：每个都给最像的 3 个候选。

    为什么不静默：一个 [待补] 和"这个数今天算不出来"长得一模一样，事后极难追回。
    """
    try:
        from lab import suggest
    except Exception:
        return [f"「{n}」找不到（输出字典不可用）" for n in names]
    out = []
    for n in names:
        cands = suggest(n, 3)
        if not cands:
            out.append(f"「{n}」在输出字典里找不到，且没有相似的条目——确实缺这个数的话，"
                       f"去 configs/metrics.toml 登记（并确认对应计算程序已把它算出来）")
        else:
            lines = "；".join(f"{lab}（{key}）" for lab, key in cands)
            out.append(f"「{n}」找不到。最像的是：{lines}。"
                       f"改成其中任一个即可")
    return out


def tokens_in(text: str) -> list[str]:
    return sorted({m.group(1) for m in TOKEN_RE.finditer(text)})


def blocks_of(text: str) -> list[tuple[int, str]]:
    """按空行切段，返回 [(起始行号, 段落原文)]。"""
    out: list[tuple[int, str]] = []
    buf: list[str] = []
    start = 1
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.strip():
            if not buf:
                start = lineno
            buf.append(line)
        elif buf:
            out.append((start, "\n".join(buf)))
            buf = []
    if buf:
        out.append((start, "\n".join(buf)))
    return out


def _bid(block: str) -> str:
    """段落指纹：只看去掉占位符后的文字，这样改数字不会算成改段落。"""
    skeleton = TOKEN_RE.sub("§", block)
    return hashlib.sha1(skeleton.encode("utf-8")).hexdigest()[:12]


# ─────────────────────────────────────────── 待复核
def review(text: str, facts: dict, prior: dict) -> list[dict]:
    """对比上次落盘时的事实值，挑出需要人重看的段落。"""
    flagged: list[dict] = []
    for start, block in blocks_of(text):
        keys = tokens_in(block)
        if not keys:
            continue
        bid = _bid(block)
        before = prior.get(bid, {})
        moved: list[str] = []
        for key in keys:
            fact = facts.get(key)
            if fact is None or key not in before:
                continue
            old, new = before[key], fact["v"]
            if fact["kind"] == "text":
                if old != new:
                    moved.append(f"{key}: 「{old}」→「{new}」")
                continue
            if old in (0, None):
                continue
            delta = (float(new) - float(old)) / abs(float(old))
            if abs(delta) > fact["watch"]:
                moved.append(
                    f"{key}: {float(old):,.4g} → {float(new):,.4g}"
                    f"（{delta:+.1%}，阈值 ±{fact['watch']:.0%}）"
                )
        if moved:
            flagged.append({
                "line": start,
                "head": block.splitlines()[0][:52],
                "moved": moved,
            })
    return flagged


def state_of(text: str, facts: dict) -> dict:
    out: dict[str, dict] = {}
    for _start, block in blocks_of(text):
        keys = tokens_in(block)
        if not keys:
            continue
        out[_bid(block)] = {k: facts[k]["v"] for k in keys if k in facts}
    return out


# ─────────────────────────────────────────── 收口恒等式（2026-09-11 新增）
# 为什么要有这一条：既有的裸数字 lint 是 **≤ 型**——它只检查"文件里没有手打的数"，
# 一份一个数字都不写的文件能满分通过。于是 13 份专题里 10 份与模型毫无连接却全程绿灯。
# 恒等式版本：**每份叙述必须声明自己论证哪一个收口读数**（`- 收口: <metric_key>`），
# 说不出来 → 它是素材不是正文。这是机械可判的，不靠记得检查。
CLOSING_RE = re.compile(r"^[-*]\s*主张\s*[:：]\s*(.+)$")
SUPPORT_RE = re.compile(r"^[-*]\s*支撑\s*[:：]\s*(.+)$")
QUAL_RE = re.compile(r"^[-*]\s*定性收口\s*[:：]\s*(.+)$")


_KEY_SHAPE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _keys_of(line: str) -> list[str]:
    """取逗号分隔的 key；**只认 key 的形状**。

    为什么必须过滤形状：占位文件里会写 `- 主张: （纯定性章，无模型数收口）`
    这类说明文字，不过滤就会把它当成指标名去查注册表，报出一堆
    "主张 （纯定性章 不在 lab.METRICS 里"这种废话（2026-09-11 实际踩到）。
    """
    out = []
    for k in re.split(r"[,，、]", line):
        k = k.strip()
        if _KEY_SHAPE.match(k):
            out.append(k)
    return out


def closing_of(path: Path) -> list[str]:
    """文件头 `- 收口:` 声明的收口读数（逗号分隔）。没有则空列表。"""
    for raw in path.read_text("utf-8").splitlines()[:24]:
        m = CLOSING_RE.match(raw.strip())
        if m:
            return _keys_of(m.group(1))
    return []


def support_of(path: Path) -> list[str]:
    for raw in path.read_text("utf-8").splitlines()[:24]:
        m = SUPPORT_RE.match(raw.strip())
        if m:
            return _keys_of(m.group(1))
    return []


def qual_of(path: Path) -> str:
    """定性收口：纯定性章用它代替模型数（共识锚、操作触发条件等外部可观察的事实）。"""
    for raw in path.read_text("utf-8").splitlines()[:24]:
        m = QUAL_RE.match(raw.strip())
        if m:
            return m.group(1).strip()
    return ""


# ─────────────────────────────────────────── 2026-09-13g：把 ≤ 型补成恒等式
# 09-13 复核发现：收口 lint 只检查"章有没有**声明**一个 metric"，不检查"正文有没有**用**它"。
# 于是九份正文占位符 0 个、「（待写）」34 处，收口 lint 却给了 6 个 ✓。
#
#   **≤ 型断言会随层级上移而复发**：裸数字（数）→ 收口（声明）→ 引用（使用）。
#   每加一道保护，"空壳也能满分通过"就搬到更上面一层。
#   新增任何一道 lint 前先问：**一份空文件能不能通过它？能 → 它还欠一条恒等式配对。**
#
# 恒等式三条（本轮补齐后两条，并全部切硬失败）：
#   ① 声明：每份叙述必须声明收口（原有）
#   ② 使用：`- 主张: k` 的 k，它的**中文名必须在正文里至少出现一次**
#   ③ 独立阅读：正文不许出现仓内工作文件的指针（报告要能脱离仓库读）
#
# **豁免必须显式且可数**：文件头写 `- 状态: 骨架`（章还没写）或 `- 状态: 素材`（专题还没被章点名）
# 即跳过 ②③，但会在覆盖率表里单独计数。没有静默通过这条路——
# 这正是"先报不中断必须带到期日"那条纪律的落地：豁免是有名字的，黄灯是没有的。
STATUS_RE = re.compile(r"^[-*]\s*状态\s*[:：]\s*(骨架|素材|正文)\b")   # 允许行尾跟注释

# 仓内工作文件的指针：出现在正文里就意味着报告读者要去翻仓库才能读懂。
REPO_POINTER_RE = re.compile(
    r"交接\.md|框架提案|DECISIONS\.md|MANIFEST|review-plan|sandbox-ux-draft"
    r"|v3\.2|v3_2|分析结论/|定性分析/|写作素材/|_archive|口径/|audit/|configs/|src/"
)
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.S)


def status_of(path: Path) -> str:
    for raw in path.read_text("utf-8").splitlines()[:24]:
        m = STATUS_RE.match(raw.strip())
        if m:
            return m.group(1)
    return "正文"


def body_of(path: Path) -> str:
    """正文＝第一个二级标题之后的内容，剔除代码块与 HTML 注释。

    文件头（H1 与首个 `##` 之间）是**工作台元数据**，允许放仓内指针；
    正文是**报告内容**，必须能独立阅读。这条分界让"给自己看的"和"给读者看的"各有其位。
    """
    text = path.read_text("utf-8")
    i = text.find("\n## ")
    body = text[i:] if i >= 0 else ""
    body = HTML_COMMENT_RE.sub(" ", body)
    out, fence = [], False
    for line in body.splitlines():
        if FENCE_RE.match(line):
            fence = not fence
            continue
        if not fence:
            out.append(line)
    return "\n".join(out)


def lint_closing(sources: list[Path]) -> tuple[list[str], list[dict]]:
    """收口恒等式检查（三条）＋ 覆盖率表。返回 (问题清单, 覆盖率行)。

    **2026-09-13g 起硬失败。** 此前"先只报不中断"是对的，但没有到期日的黄灯
    就是永远的黄灯——它给人"已经在管了"的错觉，实际什么都没拦住。
    到期日就是现在：豁免改为显式的 `- 状态: 骨架 / 素材`，可数、可查、会在表里点名。
    """
    from lab import METRIC_BY_KEY          # 延迟 import，避免与 lab 形成环
    problems: list[str] = []
    rows: list[dict] = []
    owner: dict[str, str] = {}
    for src in sources:
        keys = closing_of(src)
        sup = support_of(src)
        qual = qual_of(src)
        st = status_of(src)
        rows.append({"file": src.name, "closing": keys, "support": len(sup),
                     "qual": bool(qual), "status": st})
        if st == "正文":
            body = body_of(src)
            # 恒等式②：主张的数，它的中文名必须在正文里真的被引用
            for k in keys:
                lab = METRIC_BY_KEY[k].label if k in METRIC_BY_KEY else None
                if lab and ("{{%s}}" % lab) not in body and ("{{%s:" % lab) not in body:
                    problems.append(
                        f"{src.name}：主张了 {k}（{lab}），但正文里一次都没引用它——"
                        f"声明不等于论证。写 {{{{{lab}}}}}，或把文件头改成 `- 状态: 骨架`")
            # 恒等式③：正文不许出现仓内工作文件的指针
            for n, line in enumerate(body.splitlines(), 1):
                m = REPO_POINTER_RE.search(line)
                if m:
                    problems.append(
                        f"{src.name}：正文出现仓内指针「{m.group(0)}」——"
                        f"报告要能独立阅读。指向正文章节，或把它挪进文件头的元数据区")
                    break
        if st == "正文" and not keys and not qual:
            problems.append(
                f"{src.name}：既没有定量收口也没有定性收口——这章就是散文。"
                "定量章写 `- 主张: <metric_key>`；纯定性章写 `- 定性收口: <文字>`")
        for k in keys:
            if k not in METRIC_BY_KEY:
                problems.append(f"{src.name}：主张 {k} 不在 lab.METRICS 里")
            elif k in owner:
                # 主张唯一性：跨章引用允许（写 - 引用:），但两章都主张同一个数不行
                problems.append(f"{src.name}：{k} 已被 {owner[k]} 主张，本处应改为 `- 引用:`")
            else:
                owner[k] = src.name
        if len(keys) > 2:
            problems.append(f"{src.name}：主张 {len(keys)} 个，超过上限 2 个（多了等于没收口）")
    return problems, rows


def print_coverage(rows: list[dict]) -> None:
    """覆盖率表：一眼看出哪些叙述接上了数、哪些还是孤儿。"""
    print("\n收口覆盖率（每份叙述必须声明自己论证哪个读数）：")
    print(f"  {'文件':<34} {'收口':<4} {'态':<3} {'支撑':<4} 主张的读数（定性章另见「定性收口」）")
    print("  " + "─" * 92)
    for r in rows:
        mark = "✓" if r["closing"] else ("定" if r["qual"] else "—")
        st = {"骨架": "骨", "素材": "材", "正文": "  "}.get(r.get("status", "正文"), "  ")
        keys = "、".join(r["closing"]) if r["closing"] else (
            "（纯定性章）" if r["qual"] else "（未声明）")
        print(f"  {r['file'][:34]:<34} {mark:<4} {st:<3} {r['support']:<4} {keys}")
    n_ok = sum(1 for r in rows if r["closing"] or r["qual"])
    n_sk = sum(1 for r in rows if r.get("status") == "骨架")
    n_mt = sum(1 for r in rows if r.get("status") == "素材")
    print(f"  " + "─" * 92)
    print(f"  合计 {len(rows)} 份，已收口 {n_ok} 份，孤儿 {len(rows) - n_ok} 份"
          f"（✓＝定量主张　定＝纯定性收口　—＝孤儿）")
    print(f"  **待写 {n_sk} 份（骨架）＋ 待点名 {n_mt} 份（素材）**——"
          f"这两类跳过「主张必须在正文出现」与「正文不许有仓内指针」两道检查。"
          f"\n  它们不是通过了，是**显式挂账**：删掉文件头那行 `- 状态:` 的那一刻，两道检查立刻生效。")


# ─────────────────────────────────────────── 主流程
def process(lint_only: bool = False) -> int:
    """返回 0 = 全部通过；1 = 有裸数字或未知占位符（应中断构建）。"""
    if not NARRATIVE_DIR.exists():
        print(f"没有 {NARRATIVE_DIR.name}/ 目录，跳过叙述层")
        return 0
    # 【2026-09-06 清场】narrative/ 下增设 chapters/ 与 topics/ 两个子目录，
    # 原来的 glob 只扫顶层，搬迁后会一个文件都找不到 → 改 rglob 递归扫。
    sources = sorted(NARRATIVE_DIR.rglob("*.src.md"))
    if not sources:
        print(f"{NARRATIVE_DIR.name}/ 下（含子目录）没有 .src.md，跳过叙述层")
        return 0

    facts = json.loads(FACTS_PATH.read_text("utf-8"))
    prior_all = json.loads(STATE_PATH.read_text("utf-8")) if STATE_PATH.exists() else {}
    new_state: dict[str, dict] = {}
    failed = False
    review_total = 0

    for src in sources:
        name = src.name.removesuffix(".src.md")
        problems = lint(src)
        if problems:
            failed = True
            print(f"\n✗ {src.name} 有 {len(problems)} 行裸数字（叙述层只能写占位符）：")
            for lineno, line in problems[:12]:
                print(f"    {lineno:>4}| {line[:96]}")
            if len(problems) > 12:
                print(f"    …… 另有 {len(problems) - 12} 行")
            continue
        key_names = lint_names(src, facts)
        if key_names:
            failed = True
            print(f"\n✗ {src.name} 有 {len(key_names)} 行占位符写了程序内部名"
                  f"（一律写中文名；信源 `src.*` 除外）：")
            for lineno, line in key_names[:12]:
                print(f"    {lineno:>4}| {line[:96]}")
            continue

        text = src.read_text("utf-8")
        rendered, unknown = inject(text, facts)
        if unknown:
            failed = True
            print(f"\n✗ {src.name} 引用了 facts.json 里没有的事实：{', '.join(sorted(set(unknown)))}")
            continue

        flagged = review(text, facts, prior_all.get(src.name, {}))
        new_state[src.name] = state_of(text, facts)
        review_total += len(flagged)

        if not lint_only:
            target = OUTPUT_DIR / f"{name}.md"
            target.write_text(rendered, encoding="utf-8")
            print(f"✓ {src.name} → outputs/{target.name}"
                  f"（{len(tokens_in(text))} 个事实，无裸数字）")
        else:
            print(f"✓ {src.name} 检查通过（{len(tokens_in(text))} 个事实，无裸数字）")

        if flagged:
            print(f"  ⚠ {len(flagged)} 段待复核——数字已自动更新，但判断需要你重看：")
            for item in flagged:
                print(f"    第{item['line']}行 {item['head']}")
                for moved in item["moved"]:
                    print(f"        {moved}")

    # 收口恒等式三条，**2026-09-13g 起硬失败**（到期日已到，见 lint_closing 的 docstring）。
    # 豁免不是消失，是改名叫「骨架／素材」并在覆盖率表里被点名计数。
    closing_problems, closing_rows = lint_closing(sources)
    print_coverage(closing_rows)
    if closing_problems:
        print(f"\n✗ 收口检查 {len(closing_problems)} 处，已中断：")
        for p in closing_problems[:20]:
            print("   " + p)
        if len(closing_problems) > 20:
            print(f"    …… 另有 {len(closing_problems) - 20} 处")
        failed = True

    if not lint_only and not failed:
        STATE_PATH.write_text(
            json.dumps(new_state, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )

    if failed:
        return 1
    if review_total:
        print(f"\n共 {review_total} 段待复核。")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="叙述层装配")
    parser.add_argument("--lint-only", action="store_true", help="只检查，不写文件")
    args = parser.parse_args()
    sys.exit(process(lint_only=args.lint_only))


if __name__ == "__main__":
    main()

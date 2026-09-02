"""叙述层装配：占位符检查 → 注入 → 待复核判定。

三件事，都在这里：

1. **裸数字检查（lint）**
   叙述源文件（``narrative/*.src.md``）里不允许出现字面数字。
   数字只能写成 ``{{q3.increment}}``（规范写法，带单位）或
   ``{{q3.increment:n}}``（只要数字，用于表格列已标单位的场合）。
   白名单：年份、章节号、版本号、有序列表序号、行内代码与代码块。

2. **注入（inject）**
   用 facts.json 把占位符换成真值，写出最终 md。
   改一个参数重跑，所有数字自动更新，不需要重写一个字。

3. **待复核（review）**
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

TOKEN_RE = re.compile(r"\{\{\s*([A-Za-z0-9_.]+)\s*(?::\s*([a-z]+)\s*)?\}\}")
FENCE_RE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
LINK_TARGET_RE = re.compile(r"\]\([^)]*\)")   # 链接目标里的文件名／锚点不算正文数字

# 允许出现的数字：年份、章节/小节号、版本号、有序列表序号、表格分隔线
WHITELIST = [
    re.compile(r"(?:19|20)\d{2}(?:\s*[-–—/]\s*(?:19|20)?\d{2})?\s*年?"),  # 2026 / 2026–2030 / 2026年
    re.compile(r"§\s*\d+(?:\.\d+)*"),                                      # §4.2.1
    re.compile(r"\bv?\d+(?:\.\d+)+\b"),                                    # v4.3 / 4.3
    re.compile(r"^\s{0,3}\d{1,2}[.)、]\s"),                                # 有序列表 1. 2)
    re.compile(r"^\s*\|?[\s:|-]*$"),                                       # 表格分隔线
    re.compile(r"第\s*[一二三四五六七八九十百零〇\d]+\s*[章节部分步条项层]"),   # 第三章 / 第 2 步
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


# ─────────────────────────────────────────── 注入
def inject(text: str, facts: dict) -> tuple[str, list[str]]:
    """替换占位符，返回 (结果文本, 未知key列表)。"""
    unknown: list[str] = []

    def _sub(m: re.Match) -> str:
        key, mode = m.group(1), (m.group(2) or "")
        fact = facts.get(key)
        if fact is None:
            unknown.append(key)
            return m.group(0)
        return fact["bare"] if mode == "n" else fact["text"]

    return TOKEN_RE.sub(_sub, text), unknown


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


# ─────────────────────────────────────────── 主流程
def process(lint_only: bool = False) -> int:
    """返回 0 = 全部通过；1 = 有裸数字或未知占位符（应中断构建）。"""
    if not NARRATIVE_DIR.exists():
        print(f"没有 {NARRATIVE_DIR.name}/ 目录，跳过叙述层")
        return 0
    sources = sorted(NARRATIVE_DIR.glob("*.src.md"))
    if not sources:
        print(f"{NARRATIVE_DIR.name}/ 下没有 .src.md，跳过叙述层")
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

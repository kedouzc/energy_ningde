"""状态文件纪律检查：口径、专题、章是「状态」层——只写现在是什么，不写怎么改过来的。

规矩（研究项目约定 §1 文件三分法）：状态文件覆盖写、不带版本号；"为什么变成这样"只住 DECISIONS.md。
本检查找三类过程痕迹，出现即报：
  1. 修订标记：带字母后缀的日期版本号（如 09-24f、2026-09-25d）；
  2. 改动叙事用语：更正、原先、此前、上一版、原写、改为、作废、已删、第一次决定、旧租金、旧口径 等；
  3. 例外：文件开头的来历块（第一个 --- 之前的引用块）允许一行"来历"，指向 DECISIONS。
用法：python src/state_lint.py            # 列出全部违规
      被 build.py 调用时，有违规即中断构建。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = [ROOT / "口径", ROOT / "narrative" / "chapters", ROOT / "narrative" / "topics"]
REV = re.compile(r"(?<![\d.])(?:20\d\d-)?\d\d-\d\d[a-h](?![a-z])")
WORDS = ["更正", "原先", "上一版", "上一轮", "原写", "第一次决定",
         "旧租金", "旧口径", "改前", "改后", "订正", "本轮", "本次改", "已撤销"]
SKIP_NAMES = {"README.md"}


def _files() -> list[Path]:
    out: list[Path] = []
    for d in TARGETS:
        for p in sorted(d.glob("*.md")):
            if p.name in SKIP_NAMES:
                continue
            # 由 .src.md 生成的 .md 不重复查（查源文件）
            if not p.name.endswith(".src.md") and (d / (p.stem + ".src.md")).exists():
                continue
            out.append(p)
    return out


def check() -> list[str]:
    bad: list[str] = []
    for p in _files():
        lines = p.read_text(encoding="utf-8").split("\n")
        in_head = True
        for i, line in enumerate(lines, 1):
            if in_head and line.strip() == "---":
                in_head = False
            if in_head and line.startswith(">"):
                continue      # 开头来历块豁免
            rev = [] if "DECISIONS" in line else REV.findall(line)   # 指向 DECISIONS 条目的引用不算
            hits = rev + [w for w in WORDS if w in line]
            if hits:
                bad.append(f"{p.relative_to(ROOT)}:{i}: {','.join(dict.fromkeys(hits))} | {line.strip()[:80]}")
    return bad


def check_sources() -> list[str]:
    """引用的信源必须在台账里：base.toml、口径与叙述源文件里出现的 src.xxx，逐个核对 audit/信源审计台账.md。"""
    led = (ROOT / "audit" / "信源审计台账.md").read_text(encoding="utf-8")
    keys = set(re.findall(r"^\|\s*(src\.[A-Za-z0-9_]+)\s*\|", led, re.M))
    files = [ROOT / "configs" / "base.toml"] + sorted((ROOT / "口径").glob("*.src.md")) + sorted((ROOT / "narrative").rglob("*.src.md"))
    bad: list[str] = []
    for f in files:
        for k in sorted(set(re.findall(r"(?<![\w.])src\.[a-z][A-Za-z0-9]*_[A-Za-z0-9_]+", f.read_text(encoding="utf-8")))):
            if k not in keys:
                bad.append(f"{f.relative_to(ROOT)}: {k} 不在信源台账")
    return bad


def main() -> int:
    bad = check() + check_sources()
    for b in bad:
        print("  ✗ " + b)
    print(f"状态文件纪律：{'通过' if not bad else f'{len(bad)} 处过程痕迹'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

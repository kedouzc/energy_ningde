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


INVENTORY = ROOT / "build" / "_inventory.json"
REMOVED = ROOT / "build" / "_inventory_removed.txt"
WATCH = ["configs", "src", "口径", "narrative", "audit", "约定", "templates"]


def check_inventory() -> list[str]:
    """文件不许悄悄消失：上次构建时在的源文件，这次不在了 → 构建失败。

    有意删除的，把相对路径写进 build/_inventory_removed.txt（一行一个，写明理由），再跑一次。
    由来：2026-09-26 configs/changelog.toml 在两轮之间消失，没有任何检查发现。"""
    import json
    now = set()
    for d in WATCH:
        base = ROOT / d
        if base.exists():
            for p in base.rglob("*"):
                if p.is_file() and "__pycache__" not in p.parts:
                    now.add(p.relative_to(ROOT).as_posix())
    for p in ROOT.glob("*.md"):
        now.add(p.name)
    bad: list[str] = []
    if INVENTORY.exists():
        before = set(json.loads(INVENTORY.read_text(encoding="utf-8")))
        allowed = set()
        if REMOVED.exists():
            allowed = {l.split("#")[0].strip() for l in REMOVED.read_text(encoding="utf-8").splitlines() if l.strip()}
        for f in sorted(before - now - allowed):
            bad.append(f"{f} 上次构建时还在、这次不见了（有意删除请登记到 build/_inventory_removed.txt）")
    if not bad:
        INVENTORY.write_text(json.dumps(sorted(now), ensure_ascii=False, indent=0), encoding="utf-8")
    return bad


# 口径里凡有程序现算表（{{表:…}}）的一节，必须同时写出"算式"与"算例"——研究者不读程序，只能从文档复核（2026-09-28j）。
# 下列旧节在写入这条规矩之前就存在，列为待补账（逐轮补齐后从这里删掉）；新写的节不许进这张表。
CALC_DEBT = {
    ("车辆与站数_推算方法.src.md", "## 2. 站点层"),
    ("车辆与站数_推算方法.src.md", "## 3. 供给侧"),
    ("车队总账_换电对充电.src.md", "## 一、电池寿命"),
    ("车队总账_换电对充电.src.md", "## 三、终局时三个价"),
    ("车队总账_换电对充电.src.md", "## 四、车队总账"),
    ("车队总账_换电对充电.src.md", "## 五、份额怎么算"),
    ("运营收入与成本_口径.src.md", "## 4. 分拆"),
}


def check_calc_explained() -> tuple[list[str], list[str]]:
    """返回（违规，待补账提示）。"""
    bad, debt = [], []
    for f in sorted((ROOT / "口径").glob("*.src.md")):
        for sec in re.split(r"\n(?=## )", f.read_text(encoding="utf-8")):
            if "{{表:" not in sec:
                continue
            head = sec.split("\n", 1)[0]
            if all(k in sec for k in ("算式", "算例")):
                continue
            if any(f.name == fn_ and head.startswith(pre) for fn_, pre in CALC_DEBT):
                debt.append(f"{f.name} {head[:30]}")
            else:
                bad.append(f"{f.relative_to(ROOT)} 「{head[:30]}」有程序现算表，但没写「算式」与「算例」（研究者无法复核）")
    return bad, debt


def main() -> int:
    calc_bad, calc_debt = check_calc_explained()
    bad = check() + check_sources() + check_inventory() + calc_bad
    if calc_debt:
        print(f"  ◇ 算式与算例待补（旧节，{len(calc_debt)} 处）：" + "；".join(calc_debt))
    for b in bad:
        print("  ✗ " + b)
    print(f"状态文件纪律／信源台账／文件清点／算式算例：{'通过' if not bad else f'{len(bad)} 处问题'}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

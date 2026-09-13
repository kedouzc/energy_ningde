"""「一页纸」：把投资决策压成「三层次 × 若干行」的一屏，嵌进沙盘 HTML。

为什么只有 HTML 一个出口
------------------------
以前它写 `outputs/换电一页纸_v4.3.xlsx`——IDE 里读不了、参数一改就得重开文件、
更没法边调参边看判断怎么写。**能实时重算的呈现只有 HTML**，所以 xlsx 停产
（旧文件留作存档，README 已标注）。

三件事住在三个地方（不许串门）
----------------------------
* **问题与定性判断** → `narrative/一页纸.md`（人写、程序读，与叙述层同一套
  `inject.lint()` 裸数字检查）。数字一律 `{{fact}}` 占位符，链接一律 `{{src.xxx}}`——
  **信源与 URL 只住 `audit/信源审计台账.md` 的「信源索引（机读）」表**。
* **数值** → `lab.METRICS` 的 `read_metrics()`。三情景列、当前（实时）列、顶部关键读数、
  可行性验证全部从它取数——**同页一个数只有一个出处**（此前一页纸走 tree 节点、
  再按数值模糊匹配指标，是两套数据源，已删）。
* **配置数据** → `configs/base.toml`（外部锚数值、判断阈值），不放任何定性逻辑。

四条机械校验（任一失败即中断，不静默降级）
----------------------------------------
1. md 有裸数字 → `inject.lint()` 报行号；
2. md 的占位符写了程序内部名 → `inject.lint_names()` 报行号（一律写中文名，`src.*` 除外）；
3. md 引用了算不出来的占位符 → 报 key（含浏览器端取不到的 `sens.*` 与不存在的 `src.*`）；
4. 行里的 `metric:` 不在 `METRICS` → 报行。

（2026-09-13 起原第 5 条"facts↔METRICS 镜像同值"取消：手写事实已全部删除，
只剩一条取数路径；一词一名改由 `facts.check_no_duplicate()` 在每条管线拦截。）

运行
----
    python src/onepager.py        # 只做检查与自检（不落任何文件）
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from config_loader import (  # noqa: E402
    SCENARIO_ORDER,
    apply_scenario,
    load_config,
    load_drivers,
)
from lab import INFLUENCE_ANCHOR, METRICS, METRIC_BY_KEY, read_metrics  # noqa: E402
from model import build_model  # noqa: E402
import facts as facts_mod  # noqa: E402
import inject as inject_mod  # noqa: E402

MD_PATH = ROOT / "narrative" / "一页纸.md"

# md 里每行允许的字段名（顺序即写文档时的顺序）
FIELDS = ("metric", "指标", "问题", "量级", "推翻", "锚")
TEXT_FIELDS = ("量级", "推翻", "锚")


# ─────────────────────────────────────────── md 解析
def load_rows(path: Path = MD_PATH) -> list[tuple[str, str, list[dict]]]:
    """解析一页纸 md → [(层标题, 层说明, [行 dict, ...]), ...]。

    格式：`##` 是层（下面紧跟的 `>` 行是层说明），`###` 是行，`- 字段:` 是字段，
    缩进续行自动并入上一个字段。解析不到的字段留空，由 `check()` 报出来。
    """
    if not path.exists():
        raise SystemExit(f"一页纸内容源不存在：{path}")

    groups: list[tuple[str, str, list[dict]]] = []
    title: str | None = None
    desc: list[str] = []
    rows: list[dict] = []
    cur: dict | None = None
    last: str | None = None

    def flush_row() -> None:
        nonlocal cur, last
        if cur is not None:
            rows.append(cur)
        cur, last = None, None

    def flush_group() -> None:
        nonlocal title, desc, rows
        flush_row()
        if title:
            groups.append((title, " ".join(desc).strip(), rows))
        title, desc, rows = None, [], []

    for raw in path.read_text("utf-8").splitlines():
        line = raw.strip()
        if set(line) <= set("-= "):                      # 分隔线
            continue
        if line.startswith("## "):
            flush_group()
            title = line[3:].strip()
            continue
        if line.startswith("### "):
            flush_row()
            cur = {f: "" for f in FIELDS}
            continue
        if title and line.startswith(">"):
            desc.append(line.lstrip("> ").strip())
            continue
        if line.startswith("- "):
            body = line[2:]
            cuts = [i for i in (body.find(":"), body.find("：")) if i >= 0]
            if cuts:
                key, val = body[: min(cuts)].strip(), body[min(cuts) + 1:].strip()
                if key in FIELDS and cur is not None:
                    cur[key] = val
                    last = key
                    continue
            if cur is not None and last:
                cur[last] += "\n" + body
            continue
        if line and cur is not None and last:
            cur[last] += "\n" + line

    flush_group()
    if not groups:
        raise SystemExit(f"{path.name} 里没解析到任何层（要有 `## 层` / `### 行` / `- 字段:`）")
    return groups


def metric_keys(groups=None) -> list[str]:
    """一页纸用到的全部指标 key（供沙盘扩展嵌入指标集，保证三档值同源）。"""
    groups = groups if groups is not None else load_rows()
    return [r["metric"] for _t, _d, rs in groups for r in rs if r["metric"]]


# ─────────────────────────────────────────── 校验
def check(groups, facts: dict, metric_values: dict) -> list[str]:
    """四条机械校验，返回问题清单（空＝通过）。"""
    problems: list[str] = []

    # ① 裸数字：与叙述层同一函数、同一白名单
    for lineno, text in inject_mod.lint(MD_PATH):
        problems.append(f"裸数字 第{lineno}行：{text}")

    # ①b 占位符写了程序内部名（与叙述层同一函数：一律写中文名，`src.*` 信源除外）
    for lineno, text in inject_mod.lint_names(MD_PATH, facts):
        problems.append(f"占位符写了程序内部名 第{lineno}行：{text}")

    # ② 占位符算不出来（含浏览器端取不到的键、不存在的 src.*）
    #    指标 / 问题 也会渲染占位符（如 {{base.horizon_years}}），一并校验。
    for _title, _desc, rows in groups:
        for r in rows:
            for f in ("指标", "问题") + TEXT_FIELDS:
                _out, unknown = inject_mod.inject(r[f], facts)
                if unknown:
                    problems.append(f"占位符算不出来（{r.get('metric') or '无 metric'}·{f}）："
                                    f"{', '.join(sorted(set(unknown)))}")

    # ③ metric 必须存在于结果注册表
    for _title, _desc, rows in groups:
        for r in rows:
            key = r["metric"]
            if not key:
                problems.append(f"缺 metric：「{r['问题'][:24]}」这一行没写 `- metric:`")
            elif key not in METRIC_BY_KEY:
                problems.append(f"metric 不存在：{key}（不在 lab.METRICS 里）")

    # ④ 一词一名已由 facts.build_facts 内的 check_no_duplicate() 在每条管线机械拦截
    #   （base.toml [[external_quote]]/src. 撞 metrics.toml 的 key/label 即中断）；
    #   旧的手写事实↔字典镜像互校随手写事实删除（2026-09-13），这里不再有第二条取数路径。

    return problems


# ─────────────────────────────────────────── 取数与渲染
def build_context(tier: str = "中性"):
    """一次实跑拿齐：配置 / 驱动 / 快照 / 事实包 / 指标值。

    **与浏览器端 PY_BOOT 走同一段代码**：只跑一次 build_model，事实包由
    build_facts 纯装配输出字典（不依赖敏感性表/三情景表），所以这里渲染得出来的
    占位符，浏览器里也一定渲染得出来——校验 ② 的意义就在这里。
    """
    cfg = load_config()
    drivers = load_drivers(cfg)
    snapshot = build_model(cfg, **apply_scenario(cfg, drivers, tier))
    metric_values = read_metrics(snapshot, cfg)
    # facts 只做装配：值全部来自结果注册表（模型输出＋base.toml 就地信封参数）
    # 与 [[external_quote]] 引述，不需要快照（2026-09-13 起）
    facts = facts_mod.build_facts(metric_values)
    return cfg, drivers, snapshot, facts, metric_values


def tier_metric_values(cfg, drivers, keys: list[str]) -> dict[str, dict]:
    """三情景下每个指标的**精确实跑值**（与沙盘 tierValues 同一套 build_model）。"""
    out: dict[str, dict] = {}
    for tier in SCENARIO_ORDER:
        cfg2 = load_config()
        snapshot = build_model(cfg2, **apply_scenario(cfg2, drivers, tier))
        values = read_metrics(snapshot, cfg2)
        out[tier] = {k: values.get(k) for k in keys}
    return out


def render_field(facts: dict, text: str) -> str:
    """用事实包渲染一个字段里的占位符；取不到的占位符原样返回（不静默丢弃）。"""
    if not text:
        return ""
    rendered, unknown = inject_mod.inject(text, facts)
    return rendered if not unknown else text


def render_texts(facts: dict, groups) -> list[list[str]]:
    """把每行的三段判断文本用 facts 渲染一遍，返回 [[量级, 推翻, 锚], ...]（按行序）。"""
    out: list[list[str]] = []
    for _title, _desc, rows in groups:
        for r in rows:
            rendered = []
            for f in TEXT_FIELDS:
                rendered.append(render_field(facts, r[f]))
            out.append(rendered)
    return out


def payload() -> dict:
    """给沙盘 HTML 用的一页纸数据包（三层次 × 三情景精确值 × 渲染后判断文本）。

    生成期与浏览器端各跑一次：生成期产出快照值，浏览器端（Pyodide）用同一段代码
    按用户当前参数重跑，所以**解释列会跟着参数一起变**，不会停在旧数字上。
    """
    cfg, drivers, _snapshot, facts, _metric_values = build_context()
    groups = load_rows()
    keys = metric_keys(groups)
    tiers = tier_metric_values(cfg, drivers, keys)
    texts = render_texts(facts, groups)

    out_groups = []
    idx = 0
    for title, desc, rows in groups:
        out_rows = []
        for r in rows:
            mag, fals, anchor = texts[idx]
            idx += 1
            m = METRIC_BY_KEY.get(r["metric"])
            out_rows.append({
                "metric": r["metric"],
                "label": render_field(facts, r["指标"]),
                "q": render_field(facts, r["问题"]),
                "unit": m.unit if m else "",
                "decimals": m.decimals if m else 2,
                # 渲染形态（"" 普通数字 / "year" 年份无千分位）：与 facts/verdict
                # 同源走 Metric.fmt，JS 只按此标记选择格式，不自己猜哪个是年份。
                "fmt": m.fmt if m else "",
                "vals": [tiers[t].get(r["metric"]) for t in SCENARIO_ORDER],
                "mag": mag,
                "fals": fals,
                "anchor": anchor,
            })
        out_groups.append({"title": title, "desc": desc, "rows": out_rows})
    return {"tiers": list(SCENARIO_ORDER), "groups": out_groups}


# ─────────────────────────────────────────── 档位方向机械校验（保留）
def axis_tier_effect(config: dict, drivers: dict, neutral_kwargs: dict,
                     base_values: dict) -> list[tuple]:
    """每条轴**单独**摆到悲观/乐观档（其余轴保持中性），实测各指标变了多少。

    回答的是："这条轴调到乐观，换电增量价值多多少？收入、EBITDA 各变多少？"
    ——是**真实档位影响**，不是弹性，所以能直接用来挑"最该跟踪的指标"。
    """
    rows: list[tuple] = []
    for name, spec in drivers.items():
        for tier in ("悲观", "乐观"):
            cfg = copy.deepcopy(config)
            kw = dict(neutral_kwargs)
            try:
                kw.update(apply_scenario(cfg, {name: spec}, tier))
                values = read_metrics(build_model(cfg, **kw), cfg)
            except Exception:  # noqa: BLE001
                continue
            d_abs = values.get(INFLUENCE_ANCHOR, 0.0) - base_values.get(INFLUENCE_ANCHOR, 0.0)
            d_pct = {}
            for m in METRICS:
                b, a = base_values.get(m.key), values.get(m.key)
                if b is None or a is None or b != b or a != a or not b:
                    continue
                d_pct[m.key] = (a - b) / b
            rows.append((name, tier, _tier_text(spec, tier), d_abs, d_pct))
    return rows


def check_tier_direction(cfg, drivers, neutral_kwargs, base_values) -> list[str]:
    """机械检查：三档是**投资价值**的三档，故每条 driver 的乐观档必须让锚点上升、悲观档下降。

    违反者即"档位方向填反了"——最典型是成本类参数被当成收益类填
    （如谷电单价：价越高→成本越高→投资价值越低，乐观档必须是低价）。
    返回违规 driver 名列表（不阻断，由调用方决定怎么报）。
    """
    bad = []
    for name, tier, _tt, d_abs, _pct in axis_tier_effect(cfg, drivers, neutral_kwargs, base_values):
        # 资本结构参数（债/股比）不是"经营价值驱动"：杠杆升高使权益价值切片变小是正确代数，
        # 不应触发"档位方向反了"误报；只校验经营类 driver 的方向。
        if drivers.get(name, {}).get("structure"):
            continue
        if tier == "乐观" and d_abs < 0:
            bad.append(name)
        if tier == "悲观" and d_abs > 0:
            bad.append(name)
    return sorted(set(bad))


def _tier_text(spec: dict, tier: str) -> str:
    v = spec.get(tier)
    if spec.get("mode") == "relative":
        return f"×{v}"
    if "pass_as" in spec:
        return f"→ {v}"
    return f"定档 {v}"


# ─────────────────────────────────────────── 主流程
def main() -> None:
    groups = load_rows()
    cfg, drivers, snapshot, facts, metric_values = build_context()

    problems = check(groups, facts, metric_values)
    n_rows = sum(len(rs) for _t, _d, rs in groups)
    print("═" * 60)
    print("一页纸 · 自检（内容源 narrative/一页纸.md）")
    print("═" * 60)
    print(f"层次 {len(groups)}　行 {n_rows}　引用指标 {len(set(metric_keys(groups)))} 个"
          f"　事实包 {len(facts)} 条")
    if problems:
        print(f"\n✗ {len(problems)} 处问题，已中断：")
        for p in problems[:30]:
            print("   " + p)
        raise SystemExit(1)
    print("✓ 四条校验通过：无裸数字、占位符全写中文名、占位符全部可解析、metric 全部在注册表")
    print("  出口：outputs/换电沙盘_v4.3.html（xlsx 已停产，旧文件留作存档）")

    # 档位方向：三档是投资价值的三档，成本类须反向填（资本结构参数标 structure 跳过）
    neutral_kwargs = apply_scenario(load_config(), drivers, "中性")
    bad = check_tier_direction(cfg, drivers, neutral_kwargs, metric_values)
    if bad:
        print("\n⚠ 档位方向与「投资价值判断」不一致（乐观档反而降低价值 / 悲观档反而提升价值）：")
        print("   ", bad)
        print("   三档是投资价值的三档：成本类参数要反向填——乐观＝低成本、悲观＝高成本。"
              "请修正 base.toml 的 [drivers.*] 档位。\n")


if __name__ == "__main__":
    main()

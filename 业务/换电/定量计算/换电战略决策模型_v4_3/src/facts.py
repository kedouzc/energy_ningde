"""事实包：叙述层唯一可以引用的数字来源（**只做逻辑装配，不做任何参数定义**）。

为什么需要它
------------
v4.3 已经有"快照是唯一事实源"的纪律，但叙述文档仍然允许手写数字，
于是同一个「可归因换电增量价值」在三份文档里出现了三个值
（快照 5,698.3 / MANIFEST 6,724.5 / 叙述报告 8,026.4）。
backscan.py 是事后字符串抽检，只在想起来时跑，必然漏。

本模块把关系倒过来：**叙述层不许出现字面数字，只能写 {{key}} 占位符**，
装配时由本文件生成的 facts.json 注入。检查因此从"比对数字"退化成
"文件里还有没有裸数字"——一个正则就能穷尽，不可能漏。

一个数字只准有一个家（2026-09-13 重构后的三类来源）
--------------------------------------------------
1. **输出字典指标**（origin="metric"）：模型**输出**的定义与口径全部在
   `configs/metrics.toml`（用 `at` 取快照）；被叙述引用的**输入**参数（终局年、
   可调 driver、外锚、阈值）在 `configs/base.toml` 功能段**就地信封化**
   （`<键>.v` ＋ label/unit/…，key＝点分路径本身），由 lab 自动发现并升格进
   同一张结果注册表。值由 `lab.read_metrics` 算好后整包传入，本文件不碰快照、
   不写取值 lambda；呈现（千分位、小数位、单位、年份无千分位）统一调用
   `lab.Metric.format_text/format_bare`，Python 与沙盘 JS 同源。
2. **外部引用事实**（origin="ext"）：外部信源原文里的引用数字（可比公司倍数、
   第三方 TCO 测算），不进任何计算。定义全部在 `configs/base.toml` 的
   `[[external_quote]]`（自带 value/text，src 指台账机读表 key），
   本文件只负责从 lab.EXTERNAL_QUOTES 过滤装配与校验。
3. **信源引用**（origin="src"）：URL/名称/抓取日期的唯一家在
   `audit/信源审计台账.md` 的「信源索引（机读）」表，本文件只解析、不复制。

本文件因此**没有一个字面数字、没有一条口径 note、没有取值函数**：
算术归计算程序（scale/capex/business…），输入与输出归 configs/（base 输入、metrics 输出），
信源归台账，facts.py 只把三家装进同一个包并机械校验"一词一名/key 唯一"。

运行：python src/facts.py     （通常由 build.py 调用，不必单独跑）
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
FACTS_PATH = ROOT / "outputs" / "facts.json"


# ─────────────────────────────────────────── 信源引用事实（src.*）
@dataclass(frozen=True)
class RefFact:
    """信源引用事实：URL / 名称 / 抓取日期 / 分级的**唯一家**在
    `audit/信源审计台账.md` 的「信源索引（机读）」表里，本类只负责把它读出来。

    为什么要单开一类（2026-09-09）：信源与链接**也是一种数据**——此前同一条链接在
    base.toml 注释、台账正文、叙述层正文里各贴一遍，改一处忘三处。现在规矩是：
      · URL / 名称 / 抓取日期 / 分级 → 只写台账索引表；
      · 数值 → 只写 `configs/base.toml`（注释里写「信源：src.xxx」，不重复贴 URL）；
      · 下游（一页纸 md、叙述层、HTML）只能写 `{{src.xxx}}` 引用。

    text 渲染为 `[名称](URL)（抓取于 YYYY-MM-DD）`，与 metric/ext 走同一个
    `{{key}}` 占位符体系，故不需要新语法。
    """

    key: str        # 必须以 src. 开头，与 metric / ext 的命名空间隔离
    label: str      # 名称
    url: str        # 外部可点击信源
    as_of: str      # 抓取日期 YYYY-MM-DD
    grade: str = ""  # 一手 / 二手 / 假设
    used_by: str = ""  # 用于哪个 base.toml 参数

    @property
    def text(self) -> str:
        """渲染成可点击的信源链接（带抓取日期与分级）。"""
        grade = f"·{self.grade}" if self.grade else ""
        return f"[{self.label}]({self.url})（抓取于 {self.as_of}{grade}）"


LEDGER_PATH = ROOT / "audit" / "信源审计台账.md"
REF_SECTION = "## 信源索引（机读）"


def load_ref_facts(path: Path = LEDGER_PATH) -> list[RefFact]:
    """解析台账的「信源索引（机读）」表。

    找不到该节或表头列名不符 → 直接抛错中断：信源是被引用的数据，
    解析不出来却静默跳过，等于让下游渲染出空链接（那比报错更糟）。
    """
    if not path.exists():
        raise FileNotFoundError(f"信源台账不存在：{path}")
    text = path.read_text("utf-8")
    if REF_SECTION not in text:
        raise ValueError(
            f"{path.name} 里没有「{REF_SECTION}」节——信源索引是 URL 的唯一家，"
            f"缺了它下游只能手写链接（会重新变成到处有数据）"
        )
    body = text.split(REF_SECTION, 1)[1]
    rows = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("|")]
    header_idx = next((i for i, ln in enumerate(rows) if "key" in ln and "URL" in ln), None)
    if header_idx is None:
        raise ValueError(f"{path.name} 的「{REF_SECTION}」节里找不到表头行（需含 key 与 URL 两列）")
    cols = [c.strip() for c in rows[header_idx].strip("|").split("|")]
    try:
        i_key, i_name, i_url, i_asof = (cols.index(c) for c in ("key", "名称", "URL", "抓取日期"))
        i_grade = cols.index("分级")
        i_used = cols.index("用于")
    except ValueError as exc:
        raise ValueError(f"{path.name}「信源索引」表头列不全（缺 {exc}）") from exc

    out: list[RefFact] = []
    for ln in rows[header_idx + 1:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < len(cols) or set(cells[0]) <= set("-: "):
            continue                                  # 分隔行
        if not cells[i_key].startswith("src."):
            continue                                  # 表尾的说明行等
        out.append(RefFact(key=cells[i_key], label=cells[i_name], url=cells[i_url],
                           as_of=cells[i_asof], grade=cells[i_grade], used_by=cells[i_used]))
    if not out:
        raise ValueError(f"{path.name}「{REF_SECTION}」表里没有解析到任何 src.* 条目")
    return out


# ─────────────────────────────────────────── 外部引用事实（ext.*）
def quotes_from_config() -> list[dict[str, Any]]:
    """从 ``lab.EXTERNAL_QUOTES`` 投影外部引述（唯一家＝base.toml [[external_quote]]）。

    2026-09-13 前它们住在独立的 configs/external_facts.toml，后并入 base.toml；
    同日定稿为独立的 ``[[external_quote]]`` 段（参数侧则改为功能段就地信封，
    不再与引述混在一张登记表）。字段级硬规矩（ext. 前缀、key/label 唯一、
    text/value/src/as_of 必填、src 必须是台账 key、与输出字典不撞名）全部在
    lab.load_external_quotes / load_metrics 里机械执行，本函数只做字段投影，
    不补值、不校验第二遍。
    """
    from lab import EXTERNAL_QUOTES

    return [
        {
            "key": (q["key"] or "").strip(),
            "label": (q["label"] or "").strip(),
            "text": (q.get("text") or "").strip(),
            "v": float(q["value"]),
            "unit": q.get("unit", ""),
            "src": (q.get("src") or "").strip(),
            "as_of": (q.get("as_of") or "").strip(),
            "note": q.get("note", ""),
        }
        for q in EXTERNAL_QUOTES
    ]


def check_no_duplicate(external: list[dict[str, Any]], refs: list[RefFact]) -> None:
    """一词一名的最后一道闸：ext.*/src.* 的 key 与 label 都不得撞输出字典。

    2026-09-13 替代旧的 check_mirrors()：手写事实删除后，不再需要"两条取数路径
    互校同值"（只剩一条路径），但反向风险还在——base.toml 的 quote 引述若与
    metrics.toml 用了同一个 key 或中文名，事实包会静默二选一，inject 的撞名仲裁
    又把它藏起来。撞即中断，逼出一个改开的名字。每条管线（build/onepager/Pyodide）
    都经 build_facts 跑到本检查。（跨表 key/label 撞名在 lab.load_metrics 已拦一道，
    这里是事实包装配前的复述防线。）
    """
    from lab import METRIC_BY_KEY, METRIC_BY_LABEL
    problems: list[str] = []
    seen_label: dict[str, str] = {}
    for item in external:
        if item["key"] in METRIC_BY_KEY:
            problems.append(f"ext 事实 {item['key']} 与输出字典撞 key")
        if item["label"] in METRIC_BY_LABEL:
            problems.append(f"ext 事实「{item['label']}」与输出字典撞 label（一词一名）")
        prev = seen_label.get(item["label"])
        if prev is not None:
            problems.append(f"ext 事实 label 重复：「{item['label']}」（{prev} / {item['key']}）")
        seen_label[item["label"]] = item["key"]
    for r in refs:
        if r.key in METRIC_BY_KEY:
            problems.append(f"信源引用 {r.key} 与输出字典撞 key")
        if r.label in METRIC_BY_LABEL:
            problems.append(f"信源引用「{r.label}」与输出字典撞 label（一词一名）")
    if problems:
        raise ValueError("事实包一词一名校验失败：\n  " + "\n  ".join(problems))


# ─────────────────────────────────────────── 生成
def build_facts(metrics_values: dict[str, float]) -> dict[str, dict]:
    """把三类来源装配成事实包（纯装配：不取值、不算术、不定义参数）。

    参数
    ------
    metrics_values : lab.read_metrics() 的产物——模型输出指标与 config 型输入名片的
        **已算好的值**，本函数不直接碰快照/配置。

    每条目字段（inject/onepager/tree 的消费契约）：
        label/v/text/bare/unit/kind/watch/from/note/origin，
        ext 与 src 另带 as_of。kind 仅 "num"|"year"|"ext"|"src"
        （旧的 pct/x/int 渲染已并入 Metric 的 decimals/unit/fmt，占比一律
        以百分数存储，渲染层不再做 ×100）。
    """
    from lab import METRICS, METRIC_BY_KEY

    out: dict[str, dict] = {}
    bad: list[str] = []

    def _claim(key: str, label: str) -> bool:
        """登记一个 key：撞名即记账（绝不静默覆盖），返回是否可用。"""
        if key in out:
            bad.append(f"{key}（{label}）：与已装入的 {out[key]['label']} 撞 key")
            return False
        return True

    # ① 输出字典指标：呈现规则全部来自 Metric（facts 与沙盘 JS 同源的关键就在这）
    for metric in METRICS:
        v = metrics_values.get(metric.key)
        v = float("nan") if v is None else float(v)
        out[metric.key] = {
            "label": metric.label,
            "v": v,
            "text": metric.format_text(v),
            "bare": metric.format_bare(v),
            "unit": metric.unit,
            "kind": "year" if metric.fmt == "year" else "num",
            # 重跑相对变动超 3% → 引用段落被标"待复核"（外部事实不随重跑变，见下用 1.0）
            "watch": 0.03,
            "from": metric.source,
            "note": metric.note,
            "origin": "metric",
        }

    # ③' 信源引用先装（②的 quote 要用 src key 解析成可点击信源）：
    # URL/名称/抓取日期的唯一家＝台账「信源索引（机读）」。URL 列允许仓库内归档文件
    # 的相对路径（如 ../../media/ 下的机构研报），但文件必须真实存在。
    refs = load_ref_facts()
    ref_by_key: dict[str, RefFact] = {}
    for r in refs:
        if not _claim(r.key, r.label):
            continue
        if r.url.startswith(("http://", "https://")):
            source_url = r.url
        elif (LEDGER_PATH.parent / r.url).exists():
            source_url = r.url            # 仓库内相对路径（相对台账 audit/ 目录）
        else:
            bad.append(f"{r.key}：URL 既不可点击、相对路径文件也不存在（{r.url}）")
            continue
        ref_by_key[r.key] = r
        out[r.key] = {
            "label": r.label,
            "v": r.url,
            "text": r.text,
            "bare": r.text,
            "unit": "",
            "kind": "src",
            "watch": 1.0,
            "from": source_url,
            "as_of": r.as_of,
            "note": f"{r.grade}｜用于 {r.used_by}",
            "origin": "src",
        }

    # ② 外部引用事实（base.toml [[external_quote]]）：
    # 数字旁的信源不存 URL、只存台账 key，此处解析成台账渲染的可点击链接文本。
    external = quotes_from_config()
    for e in external:
        if not _claim(e["key"], e["label"]):
            continue
        ref = ref_by_key.get(e["src"])
        if ref is None:
            bad.append(f"{e['key']}：src={e['src']} 在台账「信源索引（机读）」里找不到——"
                       f"引述信源必须先登记台账，不许挂野指针")
            continue
        out[e["key"]] = {
            "label": e["label"],
            "v": e["v"],
            "text": e["text"],
            "bare": e["text"],
            "unit": e["unit"],
            "kind": "ext",
            # 外部事实不随重跑变化，watch=1.0 使其永不触发"待复核"；
            # 它需要的是定期回源核对，那是另一套机制（见 交接.md 纪律登记表）
            "watch": 1.0,
            "from": ref.text,
            "as_of": e["as_of"],
            "note": e["note"],
            "origin": "ext",
        }

    # 一词一名：ext/src 不得撞输出字典（每条管线都跑）
    check_no_duplicate(external, refs)
    # 引用了 METRIC_BY_KEY 以保持"本包覆盖全部字典 key"这一契约显式可读
    assert len(METRIC_BY_KEY) == len(METRICS)
    if bad:
        raise ValueError("事实包装配不合规：\n  " + "\n  ".join(bad))
    return out


def main() -> None:
    """单独运行入口：自跑中性档模型 → 装配事实包 → 写 outputs/facts.json。

    通常由 build.py 调用（那里还要写报告/快照）；单独跑只为排查。
    """
    from config_loader import load_config
    from model import build_model
    from lab import read_metrics

    config = load_config()
    snapshot = build_model(config)
    facts = build_facts(read_metrics(snapshot, config))
    FACTS_PATH.write_text(
        json.dumps(facts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    n_ext = sum(1 for v in facts.values() if v.get("kind") == "ext")
    print(f"事实包: {FACTS_PATH}（{len(facts)} 条，其中外部引用 {n_ext} 条）")


if __name__ == "__main__":
    main()

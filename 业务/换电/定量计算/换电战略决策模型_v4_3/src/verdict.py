"""结论区（① 顶部结论 + ② 定性逻辑）：与 `onepager.py` 同构的**区块模块**。

为什么单列这一个文件、以及 2026-09-11 为什么要改它
------------------------------------------------
顶部结论里那几句话的每个 `{{中文名}}` 都是一个数。此前这些数由 `sandbox._build_verdict`
在**生成期**用基线算一次就写死进 HTML——拖滑块、点三档时 ③ 定量看板区会动，
①② 区却纹丝不动（数值、滑块位置、档位高亮三者不同源同刻，信任归零）。

修法不是"把同样的算式在 JS 里再写一遍"（那必然漂移），而是：

    build_vals(snap, cfg)  ← 只有这一份算法
        ├─ 生成期：sandbox.py 对悲观/中性/乐观三档各调一次 → D.tierVals
        └─ 运行期：py_boot.recompute() 里 Pyodide 重跑 build_model 后调一次 → vals

JS 侧不写任何公式，只做字符串替换。这既守住「同源单程、绝不外推」，也让
"改一处、两处都变"成为结构上的必然，而不是靠记得同步。

**2026-09-11 升格**：以前本文件只管算数，`narrative/沙盘结论区.md` 的解析住在
`sandbox.py` 的 `_load_sandbox_md()` 里——于是组装器知道了"顶部结论／结论卡片／
定性逻辑／口径与信源"这些**区块专有名词**，违反它自己"只做打包"的声明。
现在本文件与 `onepager.py` 长成同一个样子：

    onepager.py = 读 narrative/一页纸.md     + 取数 + 渲染 + payload()
    verdict.py  = 读 narrative/沙盘结论区.md + 取数 + 渲染 + payload()

> 判据：**改一个按钮的颜色，需不需要碰 `.py`？** 需要 → 就没拆干净。
> 同理：**改结论区的段落划分，需不需要碰 `sandbox.py`？** 需要 → 也没拆干净。

三件事住在三个地方（不许串门）
----------------------------
* **定性文案** → `narrative/沙盘结论区.md`（人写、程序读）。
  **占位符一律写中文名**（`configs/metrics.toml` 的 `label`），写法与叙述层同一形态
  `{{中文名}}`——写程序内部 key（`{{swap.ebitda}}`、`{ebitda}`）一律中断并给出最像的
  3 个候选。**理由**：改文案的人不该被要求记住程序里这个数叫什么（2026-09-12 立）。
* **数值** → `lab.METRICS` 的 `read_metrics(snap, cfg)`。
  **本文件不再出现任何从 `snap` 属性或 `cfg` 直接取数的路径**——那会让结论区
  变成"第三套数值源"（一页纸与章取不到同一个数）。
* **精度** → 由 `Metric.decimals` 决定（连小数位也只有一个家）。

`vals` 的键＝MD 里写的中文名（不是内部 key），这样浏览器端**不需要再读一遍 md**
（`narrative/沙盘结论区.md` 并没有打进 Pyodide 的 bundle），按同名取值即可。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from lab import METRICS, read_metrics, resolve  # noqa: E402
import inject as inject_mod  # noqa: E402

MD_PATH = ROOT / "narrative" / "沙盘结论区.md"

# 占位符形态＝叙述层那一条正则（`inject.TOKEN_RE`），narrative/ 全目录只有一种写法。
# 不在这里另写一条：两条正则早晚漂移（此前 `{key}` 与 `{{key}}` 两套写法就是这么来的），
# 而"结论区是叙述层的一部分"这件事，本来就该由写法本身固定下来。
PH_RE = inject_mod.TOKEN_RE


# ─────────────────────────────────────────── md 解析
def load_md(path: Path = MD_PATH) -> dict:
    """解析 narrative/沙盘结论区.md：

      # 顶部结论   —— 结论写在最前，空行分段
      # 结论卡片   —— 下用 ## 分段：业绩／估值／卡位／ROI／重点
      # 定性逻辑   —— 下用 ## 分段为三支柱
      # 口径与信源 —— 逐条口径说明与外链

    占位符写 `{{中文名}}`（＝`configs/metrics.toml` 的 label），由 `build_vals` 算出的
    vals 填；浏览器端由 JS 用同一套正则替换，vals 的键就是这个中文名。
    """
    if not path.exists():
        raise SystemExit(f"结论区内容源不存在：{path}")
    text = path.read_text("utf-8")
    parts = re.split(r"^#\s+", text, flags=re.M)
    tmpl, cards, narrative, notes = "", [], [], []
    for part in parts[1:]:
        lines = part.split("\n")
        title = lines[0].strip()
        body = "\n".join(lines[1:]).strip()
        if title == "顶部结论":
            tmpl = body
        elif title == "结论卡片":
            for s in re.split(r"^##\s+", body, flags=re.M)[1:]:
                sl = s.split("\n")
                cards.append({"title": sl[0].strip(), "body": "\n".join(sl[1:]).strip()})
        elif title == "定性逻辑":
            for s in re.split(r"^##\s+", body, flags=re.M)[1:]:
                sl = s.split("\n")
                narrative.append({"title": sl[0].strip(), "body": "\n".join(sl[1:]).strip()})
        elif title == "口径与信源":
            notes = [ln.strip() for ln in body.split("\n") if ln.strip()]
    return {"tmpl": tmpl, "cards": cards, "narrative": narrative, "notes": notes}


# ─────────────────────────────────────────── 校验
def check_unique_labels() -> None:
    """`METRICS` 的中文名必须唯一（生成期硬失败）。

    为什么必须硬失败：`vals` 的键就是中文名，两条指标撞名时后者会悄悄覆盖前者，
    页面上却只看到一个数——"MD 里写了 A 的意思，拿到 B 的值"，事后极难追回。
    撞名要去 `configs/metrics.toml` 把 label 改开（"一词一名"）。
    """
    seen: dict[str, str] = {}
    dup: list[str] = []
    for m in METRICS:
        if m.label in seen:
            dup.append(f"{m.label}（{seen[m.label]} 与 {m.key}）")
        seen[m.label] = m.key
    if dup:
        raise SystemExit(
            "✗ 输出字典里有重复的中文名（label）：\n  " + "\n  ".join(dup)
            + "\n  结论区的 vals 以中文名为键，撞名会静默覆盖。"
              "请改 configs/metrics.toml 的 label，做到一词一名。"
        )


def md_tokens(md: dict) -> set[str]:
    """结论区 md 里出现的全部占位符名（四个区块都要扫：标题里也可能写数）。"""
    parts = [md.get("tmpl", "")]
    for card in md.get("cards", []):
        parts += [card.get("title", ""), card.get("body", "")]
    for sec in md.get("narrative", []):
        parts += [sec.get("title", ""), sec.get("body", "")]
    parts += list(md.get("notes", []))
    return {m.group(1).strip() for p in parts for m in PH_RE.finditer(p or "")}


def check_placeholders(md: dict) -> dict[str, object]:
    """把 md 里的占位符**中文名**解析成 `lab.METRICS` 的条目（找不到即中断）。

    为什么必须硬失败：静默 [待补] 等于"报告里出现一个说不清来源的数"，
    而这类数一旦被引用进决策，事后极难追回。宁可生成失败，也不出半成品。

    为什么不再手写一份 `PLACEHOLDER_MAP`：那份映射是"文案侧名字"与"数值侧名字"
    的第二份清单，MD 加一个数就要记得同步一次，忘了就静默 [待补]。
    现在**中文名就是 `configs/metrics.toml` 的 label**，与一页纸、章共用同一套寻址
    （`lab.resolve`），结论区不再有自己专属的名字表。
    """
    bad: list[str] = []
    out: dict[str, object] = {}
    for tok in sorted(md_tokens(md)):
        try:
            out[tok] = resolve(tok)
        except Exception:      # noqa: BLE001 - resolve 找不到即抛，交给下面的候选提示
            bad.append(tok)
    if bad:
        raise SystemExit(
            "✗ narrative/沙盘结论区.md 引用了输出字典里没有的名字：\n  "
            + "\n  ".join(inject_mod.metric_unknown_detail(bad))
            + "\n  占位符一律写 configs/metrics.toml 的 label（中文名），不写程序内部 key。"
        )
    return out


# ─────────────────────────────────────────── 取数
def build_vals(snap, cfg: dict) -> dict:
    """结论区全部占位符的取值（含渲染文本）。生成期与 Pyodide 复用同一函数。

    **全部走 `read_metrics`**——本函数内不允许出现 `snap.xxx` 或 `cfg[...]` 的直读，
    否则结论区就又变回"第三套数值源"（一页纸与章取不到同一个数）。

    **键＝中文名（label），不是内部 key**：浏览器端按 MD 里写的名字直接取值，
    `narrative/沙盘结论区.md` 因此不必打进 Pyodide 的 bundle——少一处"同一份文案
    存两遍"，也就少一处漂移。

    返回结构（2026-09-13 方案B：单位随数走，JS 不再手写单位）：
        {label: {"v": 裸值|None, "text": "123.0亿元", "bare": "123.0"}}
      * `text`＝完整呈现（`{{名}}`），`bare`＝裸数字（`{{名:n}}`），
        两者都由 `Metric.format_text/format_bare` 产出——与 facts 事实包、
        叙述层 inject 同一套渲染（千分位/小数位/单位/年份无千分位），
        JS 侧零格式化、零单位字符串；
      * 取不到（NaN/inf/None）→ v=None、文本 "[待补]"，页面显形绝不拿 0 冒充。
    """
    mv = read_metrics(snap, cfg)
    out: dict[str, dict] = {}
    for m in METRICS:
        raw = mv.get(m.key)
        try:
            v = float(raw)
            if v != v or v in (float("inf"), float("-inf")):
                raise ValueError("NaN/inf")
        except (TypeError, ValueError):
            out[m.label] = {"v": None, "text": "[待补]", "bare": "[待补]"}
            continue
        out[m.label] = {"v": v, "text": m.format_text(v), "bare": m.format_bare(v)}
    return out


# ─────────────────────────────────────────── 组装（与 onepager.payload 同构）
def payload(snap=None, cfg: dict | None = None) -> dict:
    """给沙盘 HTML 用的结论区数据包（模板 + 基线精确值）。

    与 `onepager.payload()` 同构：读自己的 md → 取数 → 返回数据包。
    不传 snap/cfg 时自己跑一次模型（自检用），但沙盘里应当传入已有的基线
    snapshot，避免为同一个数多跑一次 `build_model`。
    """
    md = load_md()
    check_unique_labels()
    check_placeholders(md)
    if snap is None or cfg is None:
        from config_loader import load_config
        from model import build_model
        cfg = load_config()
        snap = build_model(cfg)
    return {**md, "vals": build_vals(snap, cfg)}


# ─────────────────────────────────────────── 自检
def main() -> None:
    md = load_md()
    check_unique_labels()
    names = check_placeholders(md)
    print("═" * 60)
    print("结论区 · 自检（内容源 narrative/沙盘结论区.md）")
    print("═" * 60)
    print(f"结论分段 {len([p for p in md['tmpl'].split(chr(10)+chr(10)) if p.strip()])}　"
          f"卡片 {len(md['cards'])} 张　定性支柱 {len(md['narrative'])} 段　"
          f"口径与信源 {len(md['notes'])} 条")
    print(f"✓ 占位符 {len(names)} 个，全部用中文名命中输出字典"
          f"（`lab.resolve` 按 label 寻址，写内部 key 会在这里被拦下）")
    # 跑一次模型取基线值，验证**每个占位符都真的取到了数**。
    # 为什么要这一行：占位符写错会被拦截，但"名字对了、指标却算不出来"只会安静地
    # 变成页面上的 [待补]——它看起来和"这个数今天算不出来"一模一样，事后极难追。
    vals = payload()["vals"]
    missing = sorted(m.label for m in names.values() if vals.get(m.label, {}).get("v") is None)
    print(f"  取不到值 {len(missing)} 个"
          + (f"：{'、'.join(missing)}" if missing else "　✓ 全部取到，页面不会出 [待补]"))
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

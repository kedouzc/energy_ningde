"""结论区（① 顶部结论 + ② 定性逻辑）：与 `onepager.py` 同构的**区块模块**。

为什么单列这一个文件、以及 2026-09-11 为什么要改它
------------------------------------------------
顶部结论里那几句话的每个 `{占位符}` 都是一个数。此前这些数由 `sandbox._build_verdict`
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
* **定性文案** → `narrative/沙盘结论区.md`（人写、程序读）
* **数值** → `lab.METRICS` 的 `read_metrics(snap, cfg)`。
  **本文件不再出现任何从 `snap` 属性或 `cfg` 直接取数的路径**——那会让结论区
  变成"第三套数值源"（一页纸与章取不到同一个数）。
* **精度** → 由 `Metric.decimals` 决定（连小数位也只有一个家）。
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

from lab import METRIC_BY_KEY, read_metrics  # noqa: E402

MD_PATH = ROOT / "narrative" / "沙盘结论区.md"

# 占位符 → METRICS key。
# 为什么必须是**映射**而不是两个独立集合：占位符名是文案侧的名字（短、人读），
# METRICS key 是数值侧的名字（带命名空间）。以前这两套名字各写一遍，于是
# "结论区一个数"与"一页纸同一个数"在物理上是两个出处——第三套数值源就是这么来的。
# 现在一一映射，取不到即 None（前端渲染 [待补]），绝不用 0 冒充。
PLACEHOLDER_MAP: dict[str, str] = {
    # — 业绩 —
    "target_year": "base.target_year",
    "veh_ops": "ops.veh_ops",
    "veh_mkt": "ops.market_total",
    "share": "ops.share_of_market",
    "repl_gwh": "mfg.repl_gwh",
    "repl_share_pct": "mfg.repl_share_pct",
    # — 必要性（锁量 + 护价，落到钱上是制造侧增量）—
    "mfg_increment": "val.mfg_increment",
    # — 估值 —
    "dist_cash": "swap.dist_cash",
    "ebitda": "swap.ebitda",
    "mult": "base.ev_ebitda_multiple",
    "own_pct": "base.ownership_pct",
    "mktcap": "val.op_value_trillion",
    # — 卡位 —
    "energy": "ops.annual_energy",
    "elec_share": "mk.share_elec_latest",
    "batt_station": "ops.battery_station",
    "storage_share": "mk.share_storage_2025",
    "stations": "scale.stations_total",
    # — ROI —
    "peak_call": "capex.peak_call",
    "reit_mult": "val.reit_multiple",
    # — 重卡 —
    "veh_heavy": "ops.veh_heavy",
    "heavy_stock_wan": "ops.heavy_market_stock",
    "heavy_pen_pct": "ops.heavy_pen_pct",
    "heavy_fleet_gwh": "ops.heavy_vehicle_gwh",
    "heavy_station_gwh": "ops.heavy_station_gwh",
    "heavy_repl_gwh": "mfg.repl_gwh_heavy",
    "heavy_life_yrs": "ops.heavy_battery_life",
    "heavy_repl_cycle": "ops.heavy_repl_cycle",
    "price_swap_kwh": "ops.heavy_user_price",
    "energy_unit_kwh": "ops.energy_unit_price",
}
# 重卡全成本 TCO：六字段 × 两个持有期（N1＝模型电池寿命 / N2＝重卡更新周期），
# 命名完全规则，故用循环登记，避免 12 行手抄出错。
for _f in ("swap_wan", "swap_kwh", "lng_wan", "lng_kwh", "diesel_wan", "diesel_kwh"):
    PLACEHOLDER_MAP[f"tco_{_f}"] = f"tco.{_f}"
    PLACEHOLDER_MAP[f"tco_{_f}_9"] = f"tco.{_f}_9"

# 与 templates/sandbox.js 的渲染正则保持同一形态（小写字母开头 + 数字/下划线）。
# 生成期用它扫 MD，把"模板里用了但程序没给"的键挡在构建阶段，而不是留到页面上 [待补]。
_PH_RE = re.compile(r"\{([a-z_][a-z0-9_]*)\}")

PLACEHOLDER_KEYS = frozenset(PLACEHOLDER_MAP)


def _r(x, d: int = 1):
    """取数并定精度；取不到或非法一律 None（页面显示 [待补]，绝不拿 0 冒充）。"""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    if v != v or v in (float("inf"), float("-inf")):  # NaN / inf
        return None
    return round(v, d)


# ─────────────────────────────────────────── md 解析
def load_md(path: Path = MD_PATH) -> dict:
    """解析 narrative/沙盘结论区.md：

      # 顶部结论   —— 结论写在最前，空行分段
      # 结论卡片   —— 下用 ## 分段：业绩／估值／卡位／ROI／重点
      # 定性逻辑   —— 下用 ## 分段为三支柱
      # 口径与信源 —— 逐条口径说明与外链

    占位符 {key} 由 `build_vals` 算出的 vals 填（浏览器端由 JS 用同一套正则替换）。
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
def check_map() -> None:
    """PLACEHOLDER_MAP 的**值**必须全部存在于 `lab.METRICS`（生成期硬失败）。

    为什么必须硬失败：映射写错一个 key，`read_metrics` 会安静地返回 NaN，
    页面上就是一个 [待补]——而它看起来和"这个数今天算不出来"一模一样。
    **方向反过来也查**：程序算了却没人用的键，说明两侧已经漂移。
    """
    missing = sorted({k for k in PLACEHOLDER_MAP.values() if k not in METRIC_BY_KEY})
    if missing:
        raise SystemExit(
            "✗ PLACEHOLDER_MAP 指向了 lab.METRICS 里不存在的 key："
            + "、".join(missing)
            + "\n  请在 src/lab.py 的 METRICS 里登记该指标，或修正映射。"
        )


def check_placeholders(md: dict) -> None:
    """MD 占位符 ⊆ PLACEHOLDER_KEYS 的机械校验（缺一个就终止生成）。

    为什么必须硬失败：静默 [待补] 等于"报告里出现一个说不清来源的数"，
    而这类数一旦被引用进决策，事后极难追回。宁可生成失败，也不出半成品。
    """
    used: set[str] = set(_PH_RE.findall(md.get("tmpl", "")))
    for card in md.get("cards", []):
        used |= set(_PH_RE.findall(card.get("title", "")))
        used |= set(_PH_RE.findall(card.get("body", "")))
    for sec in md.get("narrative", []):
        used |= set(_PH_RE.findall(sec.get("body", "")))
    for ln in md.get("notes", []):
        used |= set(_PH_RE.findall(ln))
    missing = used - PLACEHOLDER_KEYS
    if missing:
        raise SystemExit(
            "✗ 沙盘结论区模板引用了程序不认识的占位符："
            + "、".join(sorted(missing))
            + "\n  请在 src/verdict.py 的 PLACEHOLDER_MAP 里补上对应的 METRICS key，"
              "或改 narrative/沙盘结论区.md 的写法。"
        )
    # 方向反过来也要查一次：映射了却没人用的键，说明 MD 与程序已经漂移
    # （例如某个数被从文案里删掉了，但数值侧还在算它）。
    unused = PLACEHOLDER_KEYS - used
    if unused:
        print("  · 结论区模板未用到的数据键：" + "、".join(sorted(unused)))


# ─────────────────────────────────────────── 取数
def build_vals(snap, cfg: dict) -> dict:
    """结论区全部占位符的取值。生成期与 Pyodide 复用同一函数。

    **全部走 `read_metrics`**——本函数内不允许出现 `snap.xxx` 或 `cfg[...]` 的直读，
    否则结论区就又变回"第三套数值源"（一页纸与章取不到同一个数）。
    精度取 `Metric.decimals`，所以小数位也只有一个家。
    """
    mv = read_metrics(snap, cfg)
    vals: dict[str, object] = {}
    for ph, mkey in PLACEHOLDER_MAP.items():
        m = METRIC_BY_KEY.get(mkey)
        vals[ph] = _r(mv.get(mkey), m.decimals if m else 1)
    return vals


# ─────────────────────────────────────────── 组装（与 onepager.payload 同构）
def payload(snap=None, cfg: dict | None = None) -> dict:
    """给沙盘 HTML 用的结论区数据包（模板 + 基线精确值）。

    与 `onepager.payload()` 同构：读自己的 md → 取数 → 返回数据包。
    不传 snap/cfg 时自己跑一次模型（自检用），但沙盘里应当传入已有的基线
    snapshot，避免为同一个数多跑一次 `build_model`。
    """
    md = load_md()
    check_map()
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
    check_map()
    check_placeholders(md)
    print("═" * 60)
    print("结论区 · 自检（内容源 narrative/沙盘结论区.md）")
    print("═" * 60)
    print(f"结论分段 {len([p for p in md['tmpl'].split(chr(10)+chr(10)) if p.strip()])}　"
          f"卡片 {len(md['cards'])} 张　定性支柱 {len(md['narrative'])} 段　"
          f"口径与信源 {len(md['notes'])} 条")
    print("✓ 占位符全部在 PLACEHOLDER_MAP 里有对应的 METRICS key")
    # 跑一次模型取基线值，验证**每个占位符都真的取到了数**。
    # 为什么要这一行：占位符写错会被拦截，但"映射对了、指标却算不出来"只会安静地
    # 变成页面上的 [待补]——它看起来和"这个数今天算不出来"一模一样，事后极难追。
    vals = payload()["vals"]
    missing = sorted(k for k, v in vals.items() if v is None)
    print(f"  占位符 {len(vals)} 个，取不到值 {len(missing)} 个"
          + (f"：{'、'.join(missing)}" if missing else "　✓ 全部取到，页面不会出 [待补]"))
    if missing:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

"""交互沙盘 v3：**轴打包调参** ＋ **区间约束** ＋ **可行性验证（目标反推）**。

三个概念必须分清（这是本模块的设计核心）
----------------------------------------
1. **区间（base.toml 里的 `bounds`／`[param_bounds]`，硬约束）**：这个参数在现实中可能取到的范围。
   滑块不许出界；反解也只在区内求解——否则会解出"服务费 0.526 元/kWh"
   这种越界、根本不可能实现的组合。
2. **档位（`[drivers.*]` 的悲观/乐观，判断）**：在**区间之内**挑两个点代表两种情景。
   档位必须落在区间内（load_drivers 校验）。
3. **微扰幅度（step，尺子）**：测量灵敏度用，与上面两者都无关。

界面范式（照 model.html 的「假设参数 + 可行性验证」）
----------------------------------------
· 假设参数面板：**分类折叠**、每参数只有中文名＋当前值＋一句逻辑＋滑块＋三档按钮；
  不展示英文路径 / 影响力 / 区间数值 / 变化率——那是程序的事，不是用户的事。
· **多目标轴打包**：charge_share／CATL换电市占率／商用换电占有率 各自一条轴、
  一个滑块整体平移（步长 5%），不再逐车型拖。
· 可行性验证：用户给目标 → 系统算出「单参数可达」与「需组合」两张表 →
  勾选组合（按补目标缺口从大到小排）→ 实时试算（每组设值即时重算读数）→ 一键应用。

设计约束（照 框架提案.md §3，已升级）
------------------------------------
· **浏览器内精确重跑，不再外推**：顶部读数、一页纸「当前（实时）」列、可行性试算，
  在自定义态一律由 Pyodide 在浏览器内重跑**同一套 Python `build_model`** 得到精确值；
  档位态直接取 Python 预计算的 `tierValues`（同源同算）。任何位置都不出现"弹性外推 / ±30%"，
  因为那会让调参显得不严肃、不可信（同源单程原则）。
· **离线兜底**：若 Pyodide 未能加载（无网络/出错），界面显示**生成快照的精确值**
  （按当前 base.toml 实跑），并明确提示"改参后回跑 `python src/run.py` 刷新"，
  绝不拿估算值冒充精确值。

运行
----
    python src/sandbox.py         # 写出 outputs/换电沙盘_v4.3.html
"""
from __future__ import annotations

import base64
import json
import math
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
from lab import (  # noqa: E402
    INFLUENCE_ANCHOR,
    METRIC_BY_KEY,
    compute_elasticity,
    iter_numeric_params,
    param_bounds_dict,
    param_cn_dict,
    read_metrics,
    rerun,
    scene_label_map,
    sensitivity_step,
)
from model import build_model  # noqa: E402

OUT = ROOT / "outputs" / "换电沙盘_v4.3.html"

# 下拉顺序：用户最关心的四个读数在前
KEY_METRIC_KEYS = [
    "val.swap_increment",      # 换电增量价值
    "swap.operating_value",    # 换电 CATL 权益市值
    "swap.revenue",            # 年收入
    "swap.ebitda",             # EBITDA
    "swap.coverage", "val.incr_over_mktcap",
]
GATES = [
    ("swap.coverage", "≥", 1.0, "EBITDA 覆盖倍数过线（<1 就是赚的不够还资本）"),
    ("val.incr_over_mktcap", "≥", 0.10, "增量价值占集团市值 ≥10%（才配占用战略敞口）"),
    ("val.swap_increment", "≥", 1000.0, "换电增量价值 ≥1,000 亿（千亿才算重注量级）"),
]
TOP_N = 14

# charge_share 是情景轴（_SKIP_SECTIONS 排除在敏感性扫描之外），
# 但沙盘要给它测弹性——用 also 旁路，不影响扫描口径。
ALSO = ("charge_share",)

# 多目标轴：打包成一条轴、一个滑块整体平移（步长 5%），不再逐车型拖。
AXIS_DRIVERS = ("commercial_nev_penetration", "commercial_swap_share",
                "catl_swap_share", "private_penetration", "charge_share")
AXIS_STEP = 0.05          # 相对轴：整体平移步长 ±5%
AXIS_SPAN = 0.30          # 相对轴：平移范围 ±30%
AXIS_ABS_STEP = 0.05      # 轴默认步长：0.05（份额/渗透率＝5 个百分点）
                          # 私家车轴在 base.toml 用 axis_step=0.01 覆盖（1 个百分点）

# 参数面板分组（纯展示层：只管"怎么摆"，不持有任何数值）。
_GROUPS: list[tuple[str, tuple[str, ...]]] = [
    ("① 需求与规模（车辆数）：逐参数", ("vehicles.",)),
    ("② 价格与运营", ("swap_business.",)),
    ("③ 制造与估值", ("finance.",)),
]


def _key_metrics():
    return [m for k in KEY_METRIC_KEYS if (m := METRIC_BY_KEY.get(k)) is not None]


def _one_paper_metric_keys() -> list[str]:
    """一页纸引用的指标 key（若一页纸解析失败就返回空，不阻断沙盘）。"""
    try:
        import onepager
        return [k for k in onepager.metric_keys() if k in METRIC_BY_KEY]
    except Exception:  # noqa: BLE001
        return []


# 顶部只展示 6 个关键读数，但一页纸「当前（实时）」列与顶部读数必须**同一个数**，
# 所以嵌入集合要覆盖一页纸用到的全部指标：三档 tierValues 与 Pyodide 重跑都从这里取。
# （不覆盖的话，一页纸当前列会退回"按数值猜指标"的老路——那是两套数据源的根因。）
EMBED_METRIC_KEYS = KEY_METRIC_KEYS + ["ops.annual_energy"] + [
    k for k in _one_paper_metric_keys()
    if k not in KEY_METRIC_KEYS and k != "ops.annual_energy"
]


def _embed_metrics():
    return [m for k in EMBED_METRIC_KEYS if (m := METRIC_BY_KEY.get(k)) is not None]


def _group_of(path: str) -> str:
    for title, prefixes in _GROUPS:
        if any(path.startswith(p) for p in prefixes):
            return title
    return "其他"


def _notes(config: dict) -> dict[str, str]:
    """参数 → 一句话逻辑（取 driver desc 的第一句；来历与证据不进沙盘）。"""
    out: dict[str, str] = {}
    for spec in config.get("drivers", {}).values():
        first = (spec.get("desc") or "").split("。")[0]
        if not first:
            continue
        for path in spec.get("targets", [spec.get("target")] or []):
            if path:
                out[path] = first
    return out


def build_data(config: dict, base_values: dict, step: float) -> dict:
    elasticity = compute_elasticity(config, base_values, step, also=ALSO)
    values = dict(iter_numeric_params(config, include_arrays=True, also=ALSO))
    bounds = param_bounds_dict(config)      # 区间：drivers.bounds ∪ 向量轴三档 ∪ 结构边界
    cn_map = param_cn_dict(config)
    notes = _notes(config)
    labels = scene_label_map(config)
    vlabels = {
        k: (v.get("label") or k)
        for k, v in (config.get("vehicles") or {}).items() if isinstance(v, dict)
    }
    pbounds = config.get("param_bounds") or {}   # 只剩硬上界
    # 可调参数的 step / display_div / 三档都在 [drivers] 里（已与 param_bounds 合并）
    drv_meta: dict[str, dict] = {}
    for spec in config.get("drivers", {}).values():
        for t in spec.get("targets", [spec.get("target")] or []):
            if t:
                drv_meta[t] = spec

    # 各档位下每个参数的取值（供一键三档 / 逐参数档位按钮）
    # 中性档严格等于模型基线，故直接用基线 config，不必 apply_scenario（也避开
    # apply_scenario 的「中性≠基线」SystemExit——那是给"真正落档"用的守卫，
    # 这里只是只读探测，base.toml 一旦漂移就会误杀整个沙盘构建、留下陈旧乱码页）。
    tier_vals: dict[str, dict] = {}
    for tier in SCENARIO_ORDER:
        cfg2 = load_config()
        if tier != "中性":
            apply_scenario(cfg2, load_drivers(cfg2), tier, check_neutral=False)
        tier_vals[tier] = dict(iter_numeric_params(cfg2, include_arrays=True, also=ALSO))

    # 各档位下每个核心指标的**精确实跑值**——供「一键三档」显示精确值，
    # 与一页纸三情景列**同源同算**；这样点档位按钮给的数字，和下方一页纸该列完全一致。
    tier_metric_vals: dict[str, dict] = {}
    for tier in SCENARIO_ORDER:
        cfg2 = load_config()
        # 中性档＝基线（不 apply）；其余档只读探测，关闭「中性≠基线」守卫避免误杀构建。
        kw = {} if tier == "中性" else apply_scenario(
            cfg2, load_drivers(cfg2), tier, check_neutral=False)
        mv = read_metrics(build_model(cfg2, **kw))
        tier_metric_vals[tier] = {m.key: mv.get(m.key) for m in _embed_metrics()}

    def influence(p: str) -> float:
        return abs(elasticity.get(p, {}).get(INFLUENCE_ANCHOR, 0.0))

    # 驱动轴落点：三档取 apply_scenario 重跑结果；其余参数取 [param_bounds] 自声明的三档。
    # （不区分的话，非轴参数会被"三档都等于基线"的重跑值覆盖掉。）
    driver_targets: set[str] = set()
    for spec in config.get("drivers", {}).values():
        for t in spec.get("targets", [spec.get("target")] or []):
            if t:
                driver_targets.add(t)

    # ── 多目标轴：打包 ──
    drivers = config.get("drivers", {})
    axes: list[dict] = []
    axis_members: set[str] = set()
    axis_cap: dict[str, float | None] = {}
    for name in AXIS_DRIVERS:
        spec = drivers.get(name)
        if not spec:
            continue
        members = [t for t in spec.get("targets", []) if t in values]
        if not members:
            continue

        def _tier_val(p: str, v) -> float | None:
            """数组型（S 曲线）的档位值换算成"缩放比例"，与滑块同一量纲。"""
            if isinstance(v, list) and isinstance(values[p], list) and values[p][0]:
                return v[0] / values[p][0]
            return v if not isinstance(v, list) else None

        def _cur(p: str):
            return list(values[p]) if isinstance(values[p], list) else values[p]

        def _mname(p: str) -> str:
            parts = p.split(".")
            prefix = ".".join(parts[:-1])
            if prefix in labels:
                return labels[prefix]
            if parts[0] == "vehicles" and parts[1] in vlabels:
                return vlabels[parts[1]]
            return vlabels.get(parts[-1], parts[-1])

        raw = {t: {p: tier_vals.get(t, {}).get(p) for p in members}
               for t in SCENARIO_ORDER}
        def _avg(v):
            return sum(v) / len(v) if isinstance(v, list) else (v or 0.0)

        base_vals = {p: _avg(values[p]) for p in members}
        # 全部轴统一「绝对加减」：δ 直接加到每个成员（份额/渗透率＝百分点）。
        # 不再用乘法——同一个乘数对不同基线的成员会产生不同绝对步长，说不清也数不准。
        step = float(spec.get("step") or AXIS_ABS_STEP)
        cap = spec.get("cap")
        cap = 1.0 if cap is None else float(cap)      # 轴都是比率，物理边界默认 [0,1]

        def _qfloor(x: float) -> float:
            return math.floor(x / step) * step

        def _qround(x: float) -> float:
            return round(x / step) * step

        # 滑块范围＝各成员到物理边界 [0, cap] 的最短距离，左右**对称**，量化到步长倍数。
        # 不再由乘数三档决定——三档只是判断参考点，不是边界；已饱和的成员不参与取值。
        ups = [cap - b for b in base_vals.values() if b < cap]
        downs = [b for b in base_vals.values() if b > 0]
        span = max(min(_qfloor(min(ups) if ups else step),
                       _qfloor(min(downs) if downs else step)), step)

        axis = {
            "mode": "abs",
            "step": step, "cap": cap,
            "lo": -span, "hi": span,
            "base": {p: base_vals[p] for p in members},
            # 档位偏移量化到步长倍数——否则按钮落在两格之间，数字出现第三位小数
            "dTier": {t: _qround(sum(_avg(raw[t][p]) - base_vals[p] for p in members)
                                 / len(members))
                      for t in SCENARIO_ORDER},
            # 轴级弹性：elas＝成员相对弹性之和；dElas＝对绝对偏移 δ 的等效弹性 Σ(e_i/base_i)
            "elas": {m.key: round(sum(elasticity.get(p, {}).get(m.key, 0.0)
                                      for p in members), 4) for m in _embed_metrics()},
            "dElas": {m.key: round(sum(elasticity.get(p, {}).get(m.key, 0.0) / base_vals[p]
                                      for p in members if base_vals[p]), 4)
                      for m in _embed_metrics()},
            # 逐成员弹性：成员值由 A[i] 推导后 est 需要它，不能再回查逐参数表
            "mElas": {p: {m.key: round(elasticity.get(p, {}).get(m.key, 0.0), 4)
                          for m in _embed_metrics()} for p in members},
        }
        axis.update({
            "cn": spec.get("cn") or name,
            "note": (spec.get("desc") or "").split("。")[0],
            "members": members,
            "names": {p: _mname(p) for p in members},
            "cur": {p: _cur(p) for p in members},
            "isArray": {p: isinstance(values[p], list) for p in members},
            "cap": cap,
        })
        axes.append(axis)
        axis_members.update(members)
        for p in members:
            axis_cap[p] = spec.get("cap")

    leaf_cn = {"weight": "场景权重", "onboard_battery_kwh": "单车带电量",
               "daily_km": "日均里程", "battery_kwh": "单车带电量",
               "energy_consumption_kwh_km": "单位电耗", "debt_ratio": "项目负债率",
               "valley_power_price_rmb_kwh": "谷电单价"}

    def cn_of(path: str) -> str:
        cn = cn_map.get(path)
        parts = path.split(".")
        prefix = ".".join(parts[:-1])
        if prefix in labels:                       # 场景级 → 「轴·车型·场景」
            suffix = labels[prefix]
            if not cn:
                return f"{leaf_cn.get(parts[-1], parts[-1])}·{suffix}"
            # 「私家车换电接受度·私家车·8至15万元」→ 去掉重复的车型名
            for v in vlabels.values():
                if suffix.startswith(f"{v}·"):
                    suffix = suffix.split("·", 1)[1]
                    break
            return f"{cn}·{suffix}"
        if not cn:                                 # 无名参数：给中文兜底，不露英文路径
            leaf = leaf_cn.get(parts[-1], parts[-1])
            if len(parts) == 2 and parts[0] == "vehicles":
                return f"{vlabels.get(parts[1], parts[1])}·{leaf}"
            if parts[0] == "finance":
                return f"财务·{leaf}"
            if parts[0] == "swap_business":
                return f"换电业务·{leaf}"
            return path
        if parts[0] == "charge_share":             # 逐车型充电份额 → 「轴·车型」
            return f"{cn}·{vlabels.get(parts[-1], parts[-1])}"
        return cn

    def make(path: str) -> dict:
        v = values[path]
        b = bounds.get(path)
        lo, hi = (b[0], b[1]) if b else (v * 0.5, v * 1.8)
        dm = drv_meta.get(path) or {}
        pb = pbounds.get(path) or {}
        div = float(dm.get("display_div") or pb.get("display_div") or 1.0) or 1.0
        pb_tiers = {t: pb.get(t) for t in SCENARIO_ORDER}
        tiers = {t: tier_vals.get(t, {}).get(path) for t in SCENARIO_ORDER}
        if path not in driver_targets and any(x is not None for x in pb_tiers.values()):
            tiers = pb_tiers                                 # 非轴参数用自声明三档
        tv = [x for x in (tiers["悲观"], tiers["中性"], tiers["乐观"]) if x is not None]
        if dm.get("step") is not None:
            stp = float(dm["step"])
        elif pb.get("step") is not None:
            stp = float(pb["step"])
        elif len(tv) == 3 and tv[2] > tv[0] and abs((tv[1] - tv[0]) - (tv[2] - tv[1])) < 1e-9:
            stp = (tv[2] - tv[0]) / 2                       # 三档等距 → 只落三档
        else:
            stp = (hi - lo) / 200 or abs(v) * 0.01 or 0.01
        return {
            "path": path, "cn": cn_of(path),
            "value": v / div, "min": lo / div, "max": hi / div, "step": stp / div,
            "disp": div,
            "bounded": bool(b),
            "elas": {m.key: round(elasticity.get(path, {}).get(m.key, 0.0), 4)
                     for m in _embed_metrics()},
            "tiers": {t: (x / div if x is not None else None) for t, x in tiers.items()},
            "note": notes.get(path, ""),
        }

    # 候选：轴成员已打包（不单独出卡片）+ 影响力达线的自由参数取前 TOP_N
    cands = [p for p, v in values.items()
             if not isinstance(v, list) and p not in axis_members
             and abs(v) > 1e-12 and influence(p) >= 0.05]
    cands.sort(key=influence, reverse=True)
    params = [make(p) for p in cands[:TOP_N]]
    pmap = {p["path"]: p for p in params}

    seen: dict[str, int] = {}
    for p in params:
        seen[p["cn"]] = seen.get(p["cn"], 0) + 1
    for p in params:
        if seen[p["cn"]] > 1:
            p["cn"] = f'{p["cn"]}·{p["path"].split(".")[-1]}'

    groups: dict[str, list] = {}
    for p in params:
        groups.setdefault(_group_of(p["path"]), []).append(p["path"])

    metrics = [{"key": m.key, "label": m.label, "unit": m.unit,
                "value": base_values.get(m.key), "decimals": m.decimals}
               for m in _key_metrics()]
    # 估算用的指标超集（含一页纸「当前列」要复用的 ops.annual_energy），与弹性嵌入一致
    est_metrics = [{"key": m.key, "label": m.label, "unit": m.unit,
                    "value": base_values.get(m.key), "decimals": m.decimals}
                   for m in _embed_metrics()]
    gates = [{"key": k, "op": op, "thr": thr, "why": why,
              "label": METRIC_BY_KEY[k].label}
             for k, op, thr, why in GATES if k in METRIC_BY_KEY]
    # 数组型轴成员（S 曲线）：不进逐参数表，但要在估算里按整体缩放计入
    arrays = [{"path": p, "value": list(values[p]), "cap": axis_cap.get(p),
               "elas": {m.key: round(elasticity.get(p, {}).get(m.key, 0.0), 4)
                        for m in _embed_metrics()}}
              for p in axis_members if isinstance(values.get(p), list)]
    return {"params": pmap, "axes": axes, "arrays": arrays,
            "metrics": metrics, "estMetrics": est_metrics, "gates": gates,
            "groups": [{"title": t, "paths": ps} for t, ps in groups.items()],
            "tiers": list(SCENARIO_ORDER), "step": step,
            "tierValues": tier_metric_vals}


HTML = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>换电战略沙盘 v4.3</title>
<style>
:root{--bd:#e5e7eb;--mu:#6b7280;--ac:#2563eb;--ok:#16a34a;--bad:#dc2626;--bg:#f8fafc}
*{box-sizing:border-box} body{font:14px/1.6 system-ui,"Microsoft YaHei",sans-serif;margin:0;background:var(--bg);color:#111}
.wrap{max-width:1080px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0} h2{font-size:16px;margin:22px 0 8px}
.card{background:#fff;border:1px solid var(--bd);border-radius:10px;padding:14px;margin-bottom:12px}
.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
button{cursor:pointer;border:1px solid var(--bd);background:#fff;border-radius:8px;padding:5px 12px;font-size:13px}
button:hover{border-color:var(--ac);color:var(--ac)}
button.pri{background:var(--ac);color:#fff;border-color:var(--ac)}
.chip{display:inline-block;border:1px solid var(--bd);border-radius:6px;padding:1px 8px;margin:2px 4px 0 0;font-size:12px;color:var(--mu);cursor:pointer}
.chip.on{border-color:var(--ac);color:var(--ac);background:#eff6ff}
.note{color:var(--mu);font-size:12px}
.metric{border:1px solid var(--bd);border-radius:10px;padding:10px 12px;background:#fff}
.metric b{font-size:20px;display:block;margin:2px 0}
.gate{padding:6px 10px;border-radius:8px;margin-top:6px;font-size:13px}
.gate.ok{background:#f0fdf4;color:var(--ok)} .gate.no{background:#fef2f2;color:var(--bad)}
table{width:100%;border-collapse:collapse;font-size:13px;background:#fff}
th,td{border-bottom:1px solid var(--bd);padding:6px 8px;text-align:left}
th{color:var(--mu);font-weight:500}
input[type=range]{width:100%;accent-color:var(--ac)}
input[type=number]{width:110px;padding:4px 6px;border:1px solid var(--bd);border-radius:6px}
details{margin-bottom:12px} summary{cursor:pointer;font-size:16px;font-weight:600;padding:6px 0}
.pcv{color:var(--ac);font-weight:600}
.opv{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.opv.hi{background:#eff6ff;font-weight:700}
th.opth{text-align:right;color:var(--mu)}
th.opth.hi{background:#eff6ff;color:var(--ac)}
.opj{font-size:12px;color:var(--mu);max-width:280px}
/* 一页纸：三层分组 —— 层标题条 + 可折叠 + 归属口径浅底，解决"问题一箩筐看不到层次" */
details.opgroup{margin:0 0 12px;border:1px solid var(--bd);border-radius:10px;background:#fff}
details.opgroup>summary{font-size:15px;font-weight:600;padding:9px 12px;background:#f1f5f9;
  border-radius:10px 10px 0 0;list-style:none;cursor:pointer}
details.opgroup>summary::-webkit-details-marker{display:none}
details.opgroup[open]>summary{border-bottom:1px solid var(--bd)}
.opdesc{font-size:12px;color:var(--mu);padding:8px 12px 0}
tr.attrib td{background:#f8fafc}
.opj b{color:var(--mu);font-weight:600}
</style>
<!-- Pyodide 改为运行时动态多镜像加载（见 initPy）：cdn.jsdelivr 在国内常不可达，
     故依次回退到 npmmirror / unpkg；全部失败则明确提示，不再静默。 -->
</head><body><div class="wrap">
<h1>换电战略沙盘 <span class="note" id="pystat">精确模式：浏览器内重跑同一套 Python 模型；离线则显示生成快照，改参请回跑 python src/run.py</span></h1>

<div class="card row">
  <b>一键三档</b>
  <button id="tb0" onclick="setTier(0)">一键悲观</button>
  <button id="tb1" class="pri" onclick="setTier(1)">一键中性</button>
  <button id="tb2" onclick="setTier(2)">一键乐观</button>
  <button onclick="resetAll()">全部复位</button>
  <span class="note">详细设置：展开下方面板</span>
</div>

<div id="metrics"></div>
<div id="gates"></div>
<div id="onepaper"></div>

<details>
  <summary>⚙ 假设参数（默认收起）</summary>
  <div id="panel"></div>
</details>

<div class="card">
  <h2 style="margin-top:0">◈ 可行性验证：如果关键读数不达标，调哪些参数能达标</h2>
  <div class="row">
    让 <select id="tgtM"></select> 达到 <input id="tgtV" type="number" step="any">
    <button id="bnAna" class="pri" onclick="analyze()">分析</button>
    <span id="anaHead" class="note"></span>
  </div>
  <div id="anaOut"></div>
</div>

<script>
// base64 -> UTF-8 字符串（裸 atob 会按 Latin-1 解释，中文会乱码，故用 TextDecoder 真解码）。
function b64utf8(s){
  const bin = atob(s), bytes = new Uint8Array(bin.length);
  for(let i=0;i<bin.length;i++) bytes[i] = bin.charCodeAt(i);
  return new TextDecoder("utf-8").decode(bytes);
}
// 把注入数据从 base64 解回对象，避免源码/备注里的 <\/script> 等 HTML 标签
// 提前闭合脚本标签、导致后半段 JS 直接泄漏到页面上。
const D = JSON.parse(b64utf8(__DATA_B64__));
const S = {};                       // path -> 当前值（模型单位）
Object.values(D.params).forEach(p=>S[p.path]=p.value*p.disp);
/* 注意：曲线型（数组）成员**绝不**进 S——把它们写成标量 0 会在运行时被 _set_path
   把 config 里的整个数组覆盖成 0，build_model 做 [year_index] 下标时崩。
   数组只由轴 A（δ 逐元素位移）在 recompute 里管理，S 只管标量参数。 */
const A = D.axes.map(()=>0);        // 轴的整体偏移 δ——**轴状态的唯一来源**
const arrBy = {};                   // 曲线型成员按 path 索引
D.arrays.forEach(a=>arrBy[a.path]=a);
/* 轴成员取值一律由 δ 推导（唯一硬边界 [0, cap]），不再另存一份到 S */
function axMem(ax,p,d){ return Math.max(0, Math.min((ax.cap==null?1:ax.cap), ax.base[p]+d)); }

/* 当前是否正好落在某个档上：curTier=档下标（0/1/2），null=用户已自定义偏离。
   停在档上时，顶部读数与一页纸用**精确实跑值**(D.tierValues)，与一页纸同源同算；
   一旦拖动/勾选任一参数即 markCustom() 置 null，改用弹性估算。 */
let curTier=1;
let applyingTier=false;     // setTier 套用期间，put/setAxisDelta 暂不清 curTier
function markCustom(){ if(!applyingTier) curTier=null; }

const fmt=(v,d)=> (v==null||isNaN(v))?"—":Number(v).toLocaleString("zh",{maximumFractionDigits:d});
const disp=(p,v)=> v/(p.disp||1);
const put=(p,v)=>{ markCustom(); S[p.path]=v*(p.disp||1); };
function clamp(v,lo,hi){return Math.min(hi,Math.max(lo,v));}
/* 曲线整体「加减 δ」后逐年钳 [0,cap]，返回等效比例——渗透率饱和后拖滑块不再无限放大 */
function arrEff(a,d){
  const cap=(a.cap==null?1:a.cap); let s=0,t=0;
  for(const x of a.value){ s+=Math.min(cap,Math.max(0,x+d)); t+=x; }
  return t? s/t : 1;
}

/* 精确引擎：浏览器内用 Pyodide 重跑同一套 Python build_model，得到与一页纸同源的精确值。
   档位态直接取 Python 预计算 D.tierValues（精确实跑）；
   自定义态优先用精确引擎实时重跑，未加载时退回"生成快照精确值"（绝不外推、绝不标 ±30%）。 */
let pyodide = null, pyReady = false, _recompBusy = false;
const PY_BOOT = b64utf8(__PY_BOOT_B64__);
const MODEL_BUNDLE = JSON.parse(b64utf8(__MODEL_BUNDLE_B64__));
let currentE = {};                                   // 当前精确读数（供可行性"组合实时试算"复用）
function snapshotMetrics(){ return D.tierValues[D.tiers[1]]; }   // 生成快照：中性档精确实跑值

/* 动态加载单个 <script>，带超时；失败 reject，便于多镜像回退 */
function loadScript(src, timeout=20000){
  return new Promise((res,rej)=>{
    const el=document.createElement("script"); el.src=src; el.async=true;
    const t=setTimeout(()=>rej(new Error("timeout")),timeout);
    el.onload=()=>{clearTimeout(t);res();};
    el.onerror=()=>{clearTimeout(t);rej(new Error("network"));};
    document.head.appendChild(el);
  });
}
/* Pyodide 多镜像：cdn.jsdelivr 国内常被墙，依次回退到 npmmirror（阿里，国内稳）、unpkg。
   每个 base 都是「完整发行目录」，既含 pyodide.js，也含 .wasm / 标准库 / 包，故 indexURL 指向它即可。 */
const PYODIDE_BASES = [
  "https://cdn.jsdelivr.net/pyodide/v0.26.2/full/",
  "https://fastly.jsdelivr.net/pyodide/v0.26.2/full/",
  "https://registry.npmmirror.com/pyodide/0.26.2/files/full/",
  "https://unpkg.com/pyodide@0.26.2/dist/"
];
async function initPy(){
  const s = document.getElementById("pystat");
  for(const base of PYODIDE_BASES){
    try{
      if(s) s.textContent = "精确引擎加载中…（尝试 "+base+"）";
      await loadScript(base+"pyodide.js");
      if(typeof loadPyodide !== "function") throw new Error("loadPyodide 未定义");
      const py = await loadPyodide({indexURL: base});
      py.FS.mkdir("/app"); py.FS.mkdir("/app/src"); py.FS.mkdir("/app/configs");
      for(const [rel, content] of Object.entries(MODEL_BUNDLE.src)) py.FS.writeFile("/app/src/"+rel, content);
      py.FS.writeFile("/app/configs/base.toml", MODEL_BUNDLE.config);
      // 一页纸的问题文本与信源台账：少了它们，浏览器端重跑后解释列与外链渲染不出来
      for(const [rel, content] of Object.entries(MODEL_BUNDLE.files||{})){
        const i = rel.lastIndexOf("/");
        if(i>0){ try{ py.FS.mkdir("/app/"+rel.slice(0,i)); }catch(e){} }
        py.FS.writeFile("/app/"+rel, content);
      }
      py.runPython(PY_BOOT);                            // 定义 recompute()
      pyodide = py; pyReady = true;
      if(s) s.textContent = "精确引擎已加载（"+base+"）：自定义态实时重跑同一套 Python 模型（与一页纸同源）";
      if(curTier == null) render();                     // 自定义态立即用精确值刷新
      return;
    }catch(e){
      if(s) s.textContent = "精确引擎加载中…（"+base+" 失败："+e.message+"，回退下一镜像）";
    }
  }
  // 全部镜像失败：明确告知，绝不再静默
  pyReady = false;
  if(s) s.textContent = "精确引擎未加载（全部镜像不可达）：显示生成快照精确值；改参后请回跑 python src/run.py 重新生成，或在可联网环境打开本页";
  if(!document.getElementById("engNote")){
    const note=document.createElement("div"); note.id="engNote";
    note.style.cssText="position:fixed;top:0;left:0;right:0;z-index:9998;background:#fffbeb;color:#92400e;padding:8px 14px;font:13px/1.5 system-ui;border-bottom:2px solid #f59e0b;text-align:center";
    note.textContent="⚠ 精确引擎（Pyodide）未能加载，参数联动仅更新滑块位置、读数不会重算。请在联网环境打开本页，或改参后回跑 python src/run.py 重新生成。";
    document.body.appendChild(note);
  }
  // 引擎未加载时，组合实时试算/读数应明确提示，而不是拿快照假装算过
  comboRefresh();
}

/* 重算失败显形：把异常打到页面错误条 + 顶部状态，绝不静默（静默＝闭眼改界面） */
function showRecompError(msg){
  const s = document.getElementById("pystat");
  if(s) s.innerHTML = '<span style="color:var(--bad)">⚠ '+msg+
    '（请回跑 python src/run.py 重新生成，或在可联网环境打开本页）</span>';
  let n = document.getElementById("recompErr");
  if(!n){
    n = document.createElement("div"); n.id="recompErr";
    n.style.cssText="position:fixed;bottom:0;left:0;right:0;z-index:9999;background:#fee2e2;"+
      "color:#b91c1c;padding:10px 14px;font:13px/1.6 monospace;border-top:2px solid #b91c1c;white-space:pre-wrap";
    document.body.appendChild(n);
  }
  n.textContent = "⚠ 重算错误：" + msg;
}
/* over：可选 {S:{path:模型单位值}, A:[轴δ...]}，用于可行性"设值试算"；省略=当前 S/A */
async function recomputeExact(over){
  if(!pyReady) return null;
  const S2 = Object.assign({}, S), A2 = (over && over.A) ? over.A.slice() : A.slice();
  if(over && over.S) for(const k in over.S) S2[k] = over.S[k];
  // metrics 用 estMetrics（＝顶部 6 个读数 ∪ 一页纸全部指标）：
  // 一页纸「当前（实时）」列与顶部读数因此读的是**同一份重跑结果**。
  const state = { S: S2, A: A2, axes: D.axes, metrics: D.estMetrics.map(m=>m.key) };
  // 关键：把 state 作为**字符串**经 pyodide.globals 传入，由 recompute 用 json.loads 解析。
  // 否则直接拼成 Python 字面量时，JSON 的 true/false/null 不是 Python 关键字
  // （axes 里的 isArray 就是布尔），会抛 `NameError: name 'true' is not defined`——
  // 这正是"勾选参数数字不重算"的真正根因（此前被 .catch 静默吞掉）。
  pyodide.globals.set("__state_json", JSON.stringify(state));
  const out = await pyodide.runPythonAsync("recompute(__state_json)");
  const r = JSON.parse(out);
  if(r && r.error) showRecompError("recompute：" + r.error);   // build_model 抛错也显形
  return r;
}

function paintReadings(E, tag){
  currentE = E;
  const rt=document.getElementById("readingTag"); if(rt) rt.innerHTML=(tag||"");
  document.getElementById("metrics").innerHTML =
    '<h2>关键读数'+tag+'</h2><div class="grid">'+D.metrics.map(m=>{
      const v=E[m.key], d=m.decimals==null?2:m.decimals, up=v>=m.value;
      return `<div class="metric">${m.label}
        <b style="color:${up?'var(--ok)':'var(--bad)'}">${fmt(v,d)}<span class="note" style="font-size:12px"> ${m.unit||""}</span></b>
        <span class="note">基线 ${fmt(m.value,d)}</span></div>`;
    }).join("")+"</div>";
  document.getElementById("gates").innerHTML = D.gates.map(g=>{
    const v=E[g.key], ok=g.op==="≥"?v>=g.thr:v<=g.thr, d=D.metrics.find(m=>m.key===g.key);
    return `<div class="gate ${ok?'ok':'no'}">${ok?"✓":"✗"} ${g.label}：${fmt(v,d?d.decimals:2)}（门槛 ${fmt(g.thr,d?d.decimals:2)}）· ${g.why}</div>`;
  }).join("");
}

function render(){
  const exact = (curTier!=null && D.tierValues && D.tierValues[D.tiers[curTier]]);
  const E = exact ? D.tierValues[D.tiers[curTier]] : snapshotMetrics();   // 自定义态先显示快照精确值，绝不外推
  // 离线（精确引擎未加载）且自定义态：必须明确标注"未重算/显示快照"，
  // 否则面板（DOM）已联动、读数却停在中性快照，会被误读成"联动了但没重算"的 bug。
  const tag = exact
    ? ` · <b style="color:var(--ok)">${D.tiers[curTier]}档（精确实跑，＝一页纸该列）</b>`
    : (!pyReady
        ? " · 自定义（⚠ 精确引擎未加载，显示生成快照；改参后请回跑 python src/run.py 重新生成）"
        : " · 自定义（生成快照精确值；精确引擎就绪后实时重跑同一套 Python 模型）");
  paintReadings(E, tag);
  renderPanel();
  renderOnePaper(E);
  if(!exact && pyReady && !_recompBusy){
    _recompBusy = true;
    recomputeExact().then(r=>{
      _recompBusy = false;
      if(r && r.metrics){
        paintReadings(r.metrics, " · 自定义（精确重跑，与一页纸同源）");
        renderOnePaperCurrent(r);          // 数值列 + 解释列一起用重跑结果刷新
        comboRefresh();   // 可行性视图用精确值重算（comboLive 未生成前 comboRefresh 自动 no-op）
      }else if(r){        // 重算返回了但无指标（如 build_model 抛错）：显形，不再静默停在旧快照
        showRecompError("重算返回空指标" + (r.error? "："+r.error : ""));
      }
    }).catch(e=>{        // 重算抛错：显形到页面，绝不静默吞掉（否则等于闭眼改界面）
      _recompBusy = false;
      showRecompError("重算异常：" + (e && e.message ? e.message : e));
    });
  }
}

let built=false;
function renderPanel(){
  if(!built){
    let h = '<h2>① 需求与规模（车辆数）：情景轴打包调整</h2><div class="grid">';
    D.axes.forEach((ax,i)=>{h+=axisCard(ax,i);});
    h += "</div>";
    for(const g of D.groups) h += `<h2>${g.title}</h2><div class="grid">${g.paths.map(p=>card(p)).join("")}</div>`;
    document.getElementById("panel").innerHTML=h; built=true;
  }
  for(const p of Object.values(D.params)){
    const el=document.getElementById("rng:"+p.path); if(el){el.value=disp(p,S[p.path]);}
    const lb=document.getElementById("val:"+p.path); if(lb) lb.textContent=fmt(disp(p,S[p.path]),3);
    document.querySelectorAll(`[data-p="${p.path}"]`).forEach(c=>{
      c.classList.toggle("on",Math.abs(disp(p,S[p.path])-parseFloat(c.dataset.v))<1e-9);
    });
  }
  D.axes.forEach((ax,i)=>{
    const lb=document.getElementById("av:"+i); if(!lb) return;
    lb.textContent = (A[i]>=0?"+":"")+A[i].toFixed(2);
    const ar=document.getElementById("axr:"+i); if(ar) ar.value=A[i];   // 回写滑块位置
    document.querySelectorAll(`[data-a="${i}"]`).forEach(c=>
      c.classList.toggle("on",Math.abs(A[i]-parseFloat(c.dataset.d))<1e-9));
    ax.members.forEach(p=>{                       // 各成员当前值一律由 A[i] 现推
      const el=document.getElementById("mv:"+i+":"+p); if(!el) return;
      const d=A[i]||0, cap=(ax.cap==null?1:ax.cap), cur=ax.cur[p];
      if(Array.isArray(cur)){
        el.textContent = cur.map(x=>fmt(Math.max(0,Math.min(cap,x+d)),2)).join(" → ");
      }else{   // 只钳 [0, cap]，不按乘数档位封顶
        el.textContent = fmt(axMem(ax,p,d),2);
      }
    });
  });
}
function axisCard(ax,i){
  const chips=Object.keys(ax.dTier).map(t=>
    `<span class="chip" data-a="${i}" data-d="${ax.dTier[t]}"
      onclick="setAxisTier(${i},'${t}')">${t}</span>`).join("");
  const vals=ax.members.map(p=>
    `<div class="note">${ax.names[p]}：<b id="mv:${i}:${p}"></b></div>`).join("");
  const unit = `整体加减，步长 ${ax.step}（份额/渗透率＝百分点；各成员以自身悲观/乐观档为界）`;
  return `<div class="card"><b>${ax.cn}</b> <span class="pcv" id="av:${i}"></span>
    <div style="margin:4px 0">${vals}</div>
    ${ax.note?`<div class="note">${ax.note}</div>`:""}
    <input type="range" id="axr:${i}" min="${ax.lo}" max="${ax.hi}" step="${ax.step}" value="0"
      oninput="A[${i}]=parseFloat(this.value);setAxisDelta(${i},A[${i}]);render()">
    <div class="note">${unit}</div>
    <div>${chips}</div></div>`;
}
function card(path){
  const p=D.params[path];
  const chips=Object.entries(p.tiers).filter(([t,v])=>v!=null)
    .map(([t,v])=>`<span class="chip" data-p="${path}" data-v="${v}" onclick="put(D.params['${path}'],${v});render()">${t}${fmt(v,3)}</span>`).join("");
  const note=p.note?`<div class="note">${p.note}</div>`:"";
  return `<div class="card"><b>${p.cn}</b> <span class="pcv" id="val:${path}"></span>${note}
    <input type="range" id="rng:${path}" min="${p.min}" max="${p.max}" step="${p.step}"
      value="${p.value}" oninput="put(D.params['${path}'],parseFloat(this.value));render()">
    <div>${chips}</div></div>`;
}
function setAxisDelta(i,d){ markCustom(); A[i]=d; }   // 成员值由 axMem 现推，S 里不再存轴成员
function setAxisTier(i,t){
  A[i]=D.axes[i].dTier[t]||0;
  render();
}
function setTier(i){
  applyingTier=true;                       // 套用期间不让 put/setAxisDelta 清掉 curTier
  const t=D.tiers[i];
  for(const p of Object.values(D.params)) if(p.tiers[t]!=null) put(p,p.tiers[t]);
  D.axes.forEach((ax,k)=>setAxisTier(k,t));
  applyingTier=false; curTier=i;           // 套用完成才落到该档（精确值态）
  [0,1,2].forEach(k=>document.getElementById("tb"+k).classList.toggle("pri",k===i));
  render();   // render 内部会按 curTier 取精确实跑值并 highlightOpTier(curTier)
}
/* ── 结论校验 · 一页纸（三情景精确实跑值 × 当前实时精确值）──
   三情景列是 Python 实跑三情景的**精确值**；「当前（实时）」列也是精确值：
   停在档上＝该档精确实跑值（与档列同源）；自定义态＝精确引擎实时重跑（与一页纸同源）。
   任何列都不外推、不标 ±30%——同源单程，调参才可信。 */
// 注意：\\n 在 Python 源里要写成双反斜杠，否则这个正则会被 Python 先解成真换行 → JS 语法错
const nl2br=s=>String(s==null?"":s).replace(/\\n/g,"<br>");
let OP_INDEX=[];        // 全局行序 → 所属层/行，供自定义态回填（与 texts 数组同序）
/* 一页纸：三层次分组表。列序＝阅读顺序：问题 → 答案（三情景＋当前实时）→ 解释 → 注意事项。
   停档位＝该档精确实跑值（与档列同源）；自定义态＝Pyodide 精确重跑（数值＋解释一起刷）。 */
function renderOnePaper(E){
  const box=document.getElementById("onepaper"); if(!box) return;
  const op=D.onepaper;
  if(!op||!op.groups||!op.groups.length){ box.innerHTML=""; return; }
  OP_INDEX=[]; let idx=0;
  let h=`<div class="card"><h2 style="margin-top:0">◈ 结论校验 · 一页纸（先看值不值 → 再看做到多大 → 最后看要付多少）</h2>
    <div class="note" style="margin-bottom:10px">三情景列是 <b>python src/run.py 实跑</b>的精确值；
    「当前（实时）」列与上方「关键读数」<b>同一份取数</b>（都来自 lab.METRICS）：
    停在档上＝该档精确实跑值；自定义态＝浏览器内重跑同一套 Python 模型（<b>数值与解释列一起刷新</b>）；
    离线时显示生成快照精确值并提示回跑。任何位置都不外推、无 ±30%。点「一键三档」只高亮对应档列。</div>`;
  op.groups.forEach((g,gi)=>{
    h+=`<details class="opgroup" open><summary>${g.title}</summary>`;
    if(g.desc) h+=`<div class="opdesc">${g.desc}</div>`;
    h+=`<div style="overflow-x:auto;padding:0 12px 12px"><table>
      <tr><th>核心问题</th><th>指标（终端数字）</th>`
      + op.tiers.map((t,i)=>`<th class="opth" data-t="${i}">${t}</th>`).join("")
      + `<th class="opth">当前（实时）</th>`
      + `<th>单位</th><th>合理量级（心算校验）</th><th>注意事项与批判性思考</th></tr>`;
    g.rows.forEach((r,ri)=>{
      const i=idx++; OP_INDEX.push([gi,ri]);
      const d=(r.decimals==null?2:r.decimals);
      const cur=(E&&E[r.metric]!=null)?E[r.metric]:null;
      const attrib=/归属|归母/.test(r.label||"")?" class='attrib'":"";
      h+=`<tr${attrib}><td>${nl2br(r.q)}</td><td>${nl2br(r.label)}</td>`
        + (r.vals||[]).map((v,k)=>`<td class="opv" data-t="${k}">${fmt(v,d)}</td>`).join("")
        + `<td class="opv" id="opc${i}"><b>${fmt(cur,d)}</b></td>`
        + `<td>${r.unit||""}</td>`
        + `<td class="opj" id="opm${i}">${nl2br(r.mag)}</td>`
        + `<td class="opj" id="opf${i}"><div style="margin-bottom:4px"><b>什么会推翻它</b>：${nl2br(r.fals)}</div>`
        + `<div><b>外部锚 / 信源</b>：${nl2br(r.anchor)}</div></td></tr>`;
    });
    h+=`</table></div></details>`;
  });
  h+="</div>";
  box.innerHTML=h;
  highlightOpTier(curTier==null?-1:curTier);   // 自定义态不高亮任何档列
}
/* 自定义态精确引擎返回后：数值列与**解释列**一起用重跑结果覆盖（解释不再停在旧数字） */
function renderOnePaperCurrent(cur){
  if(!cur||!D.onepaper) return;
  const metrics=cur.metrics||{}, texts=cur.texts||[];
  OP_INDEX.forEach((pair,i)=>{
    const gi=pair[0], ri=pair[1];
    const g=D.onepaper.groups[gi]; if(!g) return;
    const r=g.rows[ri]; if(!r) return;
    const d=(r.decimals==null?2:r.decimals);
    const el=document.getElementById("opc"+i);
    if(el) el.innerHTML="<b>"+fmt(metrics[r.metric],d)+"</b>";
    const t=texts[i]; if(!t) return;
    const m=document.getElementById("opm"+i); if(m) m.innerHTML=nl2br(t[0]);
    const f=document.getElementById("opf"+i);
    if(f) f.innerHTML='<div style="margin-bottom:4px"><b>什么会推翻它</b>：'+nl2br(t[1])+'</div>'
                     +'<div><b>外部锚 / 信源</b>：'+nl2br(t[2])+'</div>';
  });
}
function highlightOpTier(k){
  document.querySelectorAll("#onepaper [data-t]").forEach(td=>{
    td.classList.toggle("hi", Number(td.dataset.t)===k);
  });
}
function resetAll(){
  for(const p of Object.values(D.params)) S[p.path]=p.value*p.disp;
  D.arrays.forEach(a=>S[a.path]=0);      // 曲线型偏移也要复位，否则滑块回 0 而值没回
  D.axes.forEach((ax,k)=>A[k]=0);
  curTier=1;                                   // 复位＝回到中性档（精确实跑态）
  [0,1,2].forEach(k=>{const el=document.getElementById("tb"+k);
    if(el) el.classList.toggle("pri",k===1);});   // 复位＝回到中性情景
  highlightOpTier(1);                            // 一页纸也回到中性列高亮
  const ae=document.getElementById("bnAna"); if(ae) ae.classList.remove("pri");
  document.getElementById("anaOut").innerHTML="";
  render();                              // 清表后再刷新，面板 / 读数才真正复位
}

/* ── 可行性验证 ──
   信任优先：表格里的「预计读数 / 补目标缺口」必须按用户在「设值」里填的数【实时】重算，
   不再是只显示触边界结果的死数；底部「组合实时试算」也随每次勾选 / 改值即时更新。
   派生值一律现推（rowReading），不另存——单一真相。 */
let comboRows=[];
let anaMk="", anaBase=0, anaTarget=0;
function analyze(){
  const mk=document.getElementById("tgtM").value;
  const target=parseFloat(document.getElementById("tgtV").value);
  const m=D.metrics.find(x=>x.key===mk); if(!m||!target) return;
  const d=m.decimals==null?2:m.decimals, gap=target/m.value-1;
  anaMk=mk; anaBase=m.value; anaTarget=m.value*(1+gap);
  hiBtn("bnAna");
  document.getElementById("anaHead").textContent=
    `当前 ${fmt(m.value,d)}，目标 ${fmt(target,d)}，差距 ${(gap*100).toFixed(1)}%`;
  const rows=[];
  for(const p of Object.values(D.params)){
    const e=p.elas[mk]; if(!e) continue;
    const mul=p.disp||1, b=p.value*mul;
    const need=b*(1+gap/e);                        // 模型单位：单独达标所需的值
    const lo=p.min*mul, hi=p.max*mul;
    const vc=Math.min(hi,Math.max(lo,need));       // 触到自己边界后最多能调到哪
    rows.push({p, v:vc, need, single:(need>=lo-1e-9&&need<=hi+1e-9),
               contrib: b? e*(vc-b)/b : 0});       // 触边界可贡献（读数相对变化）
  }
  for(const ax of D.axes){                         // 轴：δ 一律钳到自己的对称范围
    const e=ax.dElas[mk]; if(!e) continue;
    const need=gap/e;
    const dc=Math.min(ax.hi,Math.max(ax.lo,need));
    rows.push({ax, e, v:dc, need, single:(need>=ax.lo-1e-9&&need<=ax.hi+1e-9),
               contrib: e*dc,
               unit:`整体 ${(dc>=0?"+":"")}${dc.toFixed(2)}`});
  }
  const sensOf=r=> r.ax? r.e : (r.p.elas[mk]||0);
  // 单参数表按敏感度排；组合表按「触边界可贡献」排
  const single=rows.filter(r=>r.single).sort((a,b)=>Math.abs(sensOf(b))-Math.abs(sensOf(a)));
  const combo =rows.filter(r=>!r.single).sort((a,b)=>Math.abs(b.contrib)-Math.abs(a.contrib));
  // 所有行统一进 comboRows：单参数行默认不勾选（用户选择是否加入组合），组合行默认勾能补 ≥1% 缺口的
  const makeC=(r,on)=>({
    r,
    v: r.single ? r.need : r.v,                       // 单参数行默认给「达标所需值」，组合行给「触边界值」
    on,
    ax:!!r.ax,
    e: r.ax? r.e : (r.p.elas[mk]||0),
    b: r.ax? 0 : (r.p.value*(r.p.disp||1)),            // 该参数自身基线（模型单位）
    axIdx: r.ax? D.axes.indexOf(r.ax) : -1,
    boundReading: anaBase*(1+r.contrib),                // 触边界/达标时的读数（参考列）
  });
  // 默认全不勾选：底部「组合实时试算」始终 = 当前模型真实读数；只有用户显式勾选/改值才写入
  comboRows=single.map(r=>makeC(r,false)).concat(combo.map(r=>makeC(r,false)));
  const nm=r=>r.ax?r.ax.cn:r.p.cn;
  const cur=r=>r.ax?"0":fmt(r.p.value,4);
  const sens=r=>{
    const e=sensOf(r);
    if(!e) return "—";
    return `<span title="该参数每 +10% → 读数 ${(e*D.step*100).toFixed(1)}%">${(Math.abs(e)*D.step*100).toFixed(1)}%</span>`;
  };
  // 列：设值（用户填）→ 预计读数 / 补目标缺口（实时按设值算）→ 边界读数*（触边界/单参数达标参考）
  const head2="<tr><th></th><th>参数</th><th>当前值</th><th>可调到（触边界）</th><th>设值</th><th>预计读数</th><th>补目标缺口</th><th>边界读数*</th><th>敏感度</th></tr>";
  const boundGap=c=>(c.boundReading-anaBase)/(anaTarget-anaBase);
  const crow=(r,i)=>{
    const val=r.ax?String(r.v):String(r.v/(r.p.disp||1));   // 输入框用显示单位
    const c=comboRows[i];
    return `<tr><td><input id="cb:${i}" type="checkbox" ${c.on?"checked":""}`
      +` onchange="onComboCheck(${i},this.checked)"></td>`
      +`<td>${nm(r)}</td><td>${cur(r)}</td>`
      +`<td class="pcv">${r.ax?r.unit:val}</td>`
      +`<td><input id="in:${i}" type="number" step="any" value="${val}" style="width:96px" oninput="setCombo(${i},this.value)"></td>`
      +`<td class="pcv" id="rd:${i}">—</td>`
      +`<td id="gf:${i}">—</td>`
      +`<td class="note" id="bd:${i}">${fmt(c.boundReading,0)}（${(boundGap(c)*100).toFixed(1)}%）</td>`
      +`<td>${sens(r)}</td></tr>`;
  };
  let html="", idx=0;
  if(comboRows.length){
    html+=`<div class="row" style="margin:8px 0"><button class="pri" onclick="toggleAll()">全选 / 全不选</button>
      <span class="note">勾选 / 设值即实时写入主面板；取消即复位；改数值会自动勾选该项</span></div>
      <div class="card" id="comboLive" style="margin-bottom:10px"></div>`;
  }
  if(single.length) html+=`<h2>✓ 单参数即可达标（默认不勾选；勾选后加入组合试算）</h2>
    <table>${head2}${single.map((r,i)=>crow(r,idx++)).join("")}</table>`;
  if(combo.length){
    html+=`<h2>× 单独调整无法达标（按「补目标缺口」排序：先调补得多的；默认全不勾选，按需勾选）</h2>
      <span class="note">在「设值」里填你想要的数，左边「预计读数 / 补目标缺口」会按你填的值实时重算；触边界能到多少见「边界读数*」</span>
      <table>${head2}${combo.map((r,i)=>crow(r,idx++)).join("")}</table>`;
  }
  if(comboRows.length){
    html+=`<div class="note" style="margin-top:8px">勾选 / 设值即实时写入主面板与顶部读数（先看到、即联动）；「全选 / 全不选」可一键批量。每行「预计读数」是只动这一项的隔离读数，「组合实时试算」才是所有已勾选项叠加后的当前读数。单参数达标行勾选后也会被纳入组合试算。距目标还差多少见上方组合实时试算。</div>`;
  }
  if(!html) html="<p class='note'>在所有参数的可行范围内都无法达到该目标——请放宽目标，或回跑 python src/run.py 重估。</p>";
  document.getElementById("anaOut").innerHTML=html;
  // 首渲染：把每行的「预计读数 / 补目标缺口」按初值算出来，再算组合实时读数
  comboRows.forEach((_,i)=>rowRefresh(i));
  comboRefresh();
}
/* 按用户当前「设值」(comboRows[i].v) 现推该行的隔离单因读数 + 补缺口占比 */
function rowReading(i){
  const c=comboRows[i];
  const contrib = c.ax ? c.e*c.v : (c.b? c.e*(c.v-c.b)/c.b : 0);
  const reading=anaBase*(1+contrib);
  const gf=(reading-anaBase)/(anaTarget-anaBase);
  return {reading,gf};
}
function rowRefresh(i){
  const el=document.getElementById("rd:"+i); if(!el) return;
  const {reading,gf}=rowReading(i);
  el.textContent=fmt(reading,0);
  const gfEl=document.getElementById("gf:"+i);
  if(gfEl) gfEl.textContent=(gf*100).toFixed(1)+"%";
}
/* 组合实时试算：直接读当前模型状态（= 已联动的勾选/设值），永远与顶部读数一致 */
function comboRefresh(){
  const box=document.getElementById("comboLive"); if(!box) return;
  if(!pyReady){   // 引擎未加载：明确说清楚，不拿快照假装算过
    box.innerHTML='<b>组合实时试算</b>（需精确引擎）'
      +'<span style="color:var(--bad)">：精确引擎（Pyodide）未加载，暂不可实时重算，此处显示生成快照值。</span>'
      +'<span class="note">请联网打开本页，或改参后回跑 python src/run.py 重新生成。</span>';
    return;
  }
  const mk=anaMk; if(!mk) return;
  const m=D.metrics.find(x=>x.key===mk), d=m.decimals==null?2:m.decimals;
  const reading=currentE[mk]!=null?currentE[mk]:snapshotMetrics()[mk];   // 当前模型精确读数（＝顶部读数，不另行叠加）
  const gf=(reading-anaBase)/(anaTarget-anaBase);
  const ok=reading>=anaTarget-1e-9;
  box.innerHTML=`<b>组合实时试算</b>（= 当前模型 · 勾选/设值实时联动）
    　${m.label} ≈ <span style="color:${ok?'var(--ok)':'var(--bad)'};font-size:18px">${fmt(reading,d)}</span>
    　补目标缺口 <b>${(gf*100).toFixed(1)}%</b>
    　${ok?'<span style="color:var(--ok)">✓ 已达目标</span>':'<span style="color:var(--bad)">距目标还差 '+fmt(anaTarget-reading,d)+'</span>'}`;
}
function setCombo(i,val){
  const c=comboRows[i]; if(!c) return;
  markCustom();                     // 用户在可行性表里填值＝自定义态，离开档位精确值
  const num=parseFloat(val);
  if(isNaN(num)) return;                 // 空输入：保持上次值，不刷新（也不丢光标）
  const raw = c.ax ? num : num*(c.r.p.disp||1);
  const lo = c.ax ? D.axes[c.axIdx].lo : c.r.p.min*(c.r.p.disp||1);
  const hi = c.ax ? D.axes[c.axIdx].hi : c.r.p.max*(c.r.p.disp||1);
  const v = clamp(raw, lo, hi);          // 钳制到可行域（Q3：超限要提示）
  const inp = document.getElementById("in:"+i);
  if(inp){
    if(v !== raw){
      const loTxt = c.ax ? fmt(lo,4) : fmt(lo/(c.r.p.disp||1),4);
      const hiTxt = c.ax ? fmt(hi,4) : fmt(hi/(c.r.p.disp||1),4);
      inp.style.borderColor="var(--bad)"; inp.title=`已钳制到可行域 ${loTxt} ~ ${hiTxt}`;
    } else { inp.style.borderColor=""; inp.title=""; }
  }
  c.v = v;
  // 用户主动填值＝启用该项（忠实反映你的调整），回写勾选框
  c.on=true; const cb=document.getElementById("cb:"+i); if(cb) cb.checked=true;
  if(c.axIdx>=0) A[c.axIdx]=v;
  else S[c.r.p.path]=v;                  // 直接写入唯一状态 S，面板 / 读数随之联动
  rowRefresh(i); render(); comboRefresh();
}
function toggleAll(){
  const boxes=document.querySelectorAll('#anaOut input[type=checkbox]');
  const allOn=[...boxes].every(b=>b.checked);
  boxes.forEach((b,i)=>{b.checked=!allOn; comboRows[i].on=!allOn;});
  // 统一把勾选项写进 S/A（取消的复位基线），再刷一次
  comboRows.forEach(c=>{
    if(c.on){ if(c.axIdx>=0) A[c.axIdx]=clamp(c.v,D.axes[c.axIdx].lo,D.axes[c.axIdx].hi);
              else S[c.r.p.path]=c.v; }
    else { if(c.axIdx>=0) A[c.axIdx]=0; else S[c.r.p.path]=c.b; }
  });
  render(); comboRefresh();
}
/* 可行性表即实时驱动同一套模型状态（S/A）：勾选＝写入设值、取消＝复位到基线、
   设值＝改到该数；面板滑块、顶部读数、三道门全部随之联动，不再有"规划态/已应用态"之分。 */
function onComboCheck(i,on){
  const c=comboRows[i]; if(!c) return;
  markCustom();                     // 勾选/取消可行性项＝自定义态，离开档位精确值
  c.on=on;
  if(on){ if(c.axIdx>=0) A[c.axIdx]=clamp(c.v,D.axes[c.axIdx].lo,D.axes[c.axIdx].hi);
          else S[c.r.p.path]=c.v; }
  else { if(c.axIdx>=0) A[c.axIdx]=0; else S[c.r.p.path]=c.b; }   // 取消＝复位该项到基线
  render(); comboRefresh();
}
function hiBtn(id){
  const el=document.getElementById(id); if(el) el.classList.toggle("pri",true);
}

/* 前端异常是静默的：一旦抛错，按钮"点了没反应"且控制台之外毫无痕迹。
   这里强制把脚本错误显示在页面上——否则永远靠用户猜。 */
window.addEventListener("error", e=>{
  const b=document.createElement("div");
  b.style.cssText="position:fixed;bottom:0;left:0;right:0;z-index:9999;background:#fee2e2;"
    +"color:#b91c1c;padding:10px 14px;font:13px/1.6 monospace;border-top:2px solid #b91c1c";
  b.textContent="⚠ 脚本错误："+e.message+(e.lineno?`（第 ${e.lineno} 行）`:"");
  document.body.appendChild(b);
});

document.getElementById("tgtM").innerHTML=
  D.metrics.map(m=>`<option value="${m.key}">${m.label}</option>`).join("");
document.getElementById("tgtV").value=(D.metrics[0].value*1.2).toFixed(0);
renderOnePaper(snapshotMetrics());
render();
initPy();   // 异步加载精确引擎（Pyodide）；失败则界面显示生成快照精确值
</script></div></body></html>
"""


# 浏览器内精确重跑引导脚本：与生成期同一套 build_model，故"当前列/自定义态"也是精确值，不再是外推。
# 仅把用户 S/A 覆盖 _set_path 进克隆 config 再 build_model，再取 onepager 17 行——与一页纸同源。
PY_BOOT = r'''
import json, sys
# Pyodide 虚拟文件系统里模型源码都在 /app/src，必须显式加进 sys.path，
# 否则下面的「from config_loader import ...」会因模块找不到而整体失败、
# 精确重跑永远退回快照（界面不出假数，但自定义态实时重跑失效）。
sys.path.insert(0, "/app/src")
# 只 import 计算指标必须的件；tree/facts/onepager 仅用于"解释列"渲染，
# 放进函数内的 try 块——万一它们在 Pyodide 里缺依赖而导入失败，
# 绝不会让整个 recompute 未定义、每次调用都静默 NameError（那正是"面板动了数字不动"的根因之一）。
from config_loader import load_config, cloned_config, _set_path
from model import build_model
from lab import read_metrics

def recompute(state_json):
    state = json.loads(state_json)
    cfg = cloned_config(load_config())
    S = state.get("S", {})
    for path, val in S.items():
        try:
            _set_path(cfg, path, val)
        except Exception as exc:
            print("set_path skip %s: %r" % (path, exc))
    A = state.get("A", [])
    axes = state.get("axes", [])
    for i, d in enumerate(A):
        if i >= len(axes):
            continue
        ax = axes[i]
        for p in ax.get("members", []):
            # 数组成员用 ax["cur"][p]（build_data 里 _cur 已保留原始 list），
            # 不能用 ax["base"][p]——base 对数组取了均值（标量），会误判成标量分支、
            # 把 nev_rates 这类数组覆盖成标量，build_model 做 [year_index] 下标时崩。
            # 标量成员才用 base（数值）按 [lo,hi] 钳制。
            cur = ax.get("cur", {}).get(p)
            if isinstance(cur, list):
                cap = ax.get("cap")
                new = [min(cap, max(0.0, x + d)) for x in cur] if cap is not None else [x + d for x in cur]
            else:
                # lo/hi 是轴 δ 的允许范围，不是参数值的范围。
                # 旧代码 `max(lo, min(hi, base + d))` 会把结果值错误地钳到 δ 范围里，
                # 导致正向调整反而被压成基线以下（如 charge_share 0.45 -> 0.30）。
                # 正确做法：先钳 δ，再加到 base；最后按物理边界 [0, cap] 兜底。
                base = ax.get("base", {}).get(p)
                lo, hi = ax.get("lo"), ax.get("hi")
                if lo is not None and hi is not None:
                    d = max(lo, min(hi, d))
                cap = ax.get("cap")
                new = base + d
                if cap is not None:
                    new = min(cap, max(0.0, new))
            try:
                _set_path(cfg, p, new)
            except Exception as exc:
                print("set_path(skip) %s: %r" % (p, exc))
    err = None
    try:
        snap = build_model(cfg)
        mv = read_metrics(snap)
    except Exception as exc:
        # build_model 因某覆盖值抛错：返回空指标 + 错误，让前端显形，而不是整段静默失败
        err = "build_model failed: %r" % (exc,)
        print(err)
        return json.dumps({"metrics": {}, "texts": [], "error": err})
    metrics = {k: (None if mv.get(k) is None else mv.get(k)) for k in state.get("metrics", [])}
    # 一页纸的**解释列**也在这里重渲染：同一份 narrative/一页纸.md ＋ 同一个信源索引表
    # （audit/信源审计台账.md）。只刷数值、不刷解释＝调完参数解释还是旧的，用户会不信。
    # 解释列依赖 tree/facts/onepager，逐个 import 包在 try 内：任一失败只丢解释，不丢指标数字。
    texts = []
    try:
        from dataclasses import asdict
        import facts
        import onepager
        groups = onepager.load_rows()
        snap_dict = asdict(snap)
        snap_dict["_extra"] = {"config": cfg}
        texts = onepager.render_texts(facts.build_facts(snap_dict, strict=False), groups)
    except Exception as exc:
        print("onepaper texts skipped: %r" % (exc,))
    return json.dumps({"metrics": metrics, "texts": texts, "error": err})
'''


def model_bundle() -> dict:
    """把 src/*.py、configs/base.toml 与一页纸的**文本与信源**读入内存。

    后两者必须一起打包：浏览器端重跑后要按同一份 md 与同一个信源索引表重新渲染
    解释列——少打一个，Pyodide 里就渲染不出来（会静默退回旧文本，那比报错更糟）。
    """
    src_dir = Path(__file__).resolve().parent
    root = src_dir.parent
    bundle = {"src": {}, "config": (root / "configs" / "base.toml").read_text(encoding="utf-8")}
    for p in src_dir.rglob("*.py"):
        rel = str(p.relative_to(src_dir)).replace("\\", "/")
        bundle["src"][rel] = p.read_text(encoding="utf-8")
    # 一页纸的问题与判断文本 + 信源索引（URL 的唯一家）
    bundle["files"] = {}
    for rel in ("narrative/一页纸.md", "audit/信源审计台账.md"):
        fp = root / rel
        if fp.exists():
            bundle["files"][rel] = fp.read_text(encoding="utf-8")
        else:
            print(f"⚠ 未打包 {rel}——浏览器端将无法重渲染解释列/信源链接")
    return bundle


def main() -> None:
    config = load_config()
    step = sensitivity_step(config)
    base_values = read_metrics(rerun(config))
    data = build_data(config, base_values, step)
    # 一页纸（三情景精确实跑值 + 四列判断）嵌入沙盘，免得在两个文件间跳读。
    # 快照式：本表是 Python 实跑的精确值，与沙盘的弹性插值估算不同源，页面里必须标注清楚。
    try:
        from onepager import payload as onepager_payload
        data["onepaper"] = onepager_payload()
    except Exception as exc:  # 一页纸失败不应阻断沙盘
        data["onepaper"] = None
        print(f"⚠ 一页纸区块跳过：{exc}")
    # 内嵌模型源码 + 配置，供浏览器内 Pyodide 精确重跑（与一页纸同源，不再外推）。
    # 数据先 JSON（ensure_ascii=True，中文转 \uXXXX 纯 ASCII）再 base64，
    # 这样 atob() 才能无损还原（否则 UTF-8 字节被当 Latin-1 解会乱码），
    # 同时也避免源码/备注里的 </script> 提前闭合 <script> 标签。
    bundle = model_bundle()
    html = HTML.replace(
        "__DATA_B64__",
        json.dumps(base64.b64encode(json.dumps(data, ensure_ascii=True).encode()).decode()),
    )
    html = html.replace(
        "__MODEL_BUNDLE_B64__",
        json.dumps(base64.b64encode(json.dumps(bundle, ensure_ascii=True).encode()).decode()),
    )
    html = html.replace(
        "__PY_BOOT_B64__",
        json.dumps(base64.b64encode(PY_BOOT.encode()).decode()),
    )
    # 防呆：替换链断过一次（第二处误写 HTML.replace，把上一处注入的数据包覆盖回占位符，
    # 页面拿到的是 `__DATA_B64__` 这个未定义标识符 → 整页脚本崩）。宁可中断也不交付坏产物。
    left = [t for t in ("__DATA_B64__", "__MODEL_BUNDLE_B64__", "__PY_BOOT_B64__") if t in html]
    if left:
        raise SystemExit(f"沙盘 HTML 里还有未替换的占位符：{left}——替换链断了，产物不可交付")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(html, encoding="utf-8")
    n = len(data["params"])
    nb = sum(1 for p in data["params"].values() if p["bounded"])
    print(f"已写出 {OUT.name}（{len(data['axes'])} 条打包轴 + {n} 个单参数"
          f"（{nb} 个有区间约束）；{len(data['metrics'])} 个读数"
          f" × {len(data['gates'])} 道门）")


if __name__ == "__main__":
    main()

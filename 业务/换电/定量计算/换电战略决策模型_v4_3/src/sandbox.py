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

本模块只做「打包」，不写界面
--------------------------
页面长什么样、怎么交互，全部住在 `templates/`，本文件不写任何 HTML/CSS/JS：

| 件 | 职责 |
|---|---|
| `templates/sandbox.html` | 骨架 ＋ 占位符（**每一个字符都会原样进产物**，别在里面写注释） |
| `templates/sandbox.css`  | 样式：管**长什么样**（颜色／字体／间距／圆角／高亮） |
| `templates/sandbox.js`   | 交互：管**行为**（滑块／DOM／图表／调 Pyodide） |
| `src/py_boot.py`         | 浏览器端 Python 启动脚本：`import` 模型、定义 `recompute()` 供 JS 调用 |

本文件只剩四件事：**跑模型算基线 → 打包 bundle → 读模板替换占位符 → 写 HTML**。
产物仍是**单文件离线 HTML**（CSS/JS 在生成期内联回去，绝不用外链）。

为什么要外置：写在 Python 字符串里的 JS/CSS 被 IDE 当普通文本（无高亮／补全／lint，
语法错要等浏览器才暴露），且会让"把 HTML 删掉重写、报告结论一个字不变"这条完工标准
失效——删 HTML 等于删 Python 的一部分。
**判据：改一个按钮的颜色，需不需要碰 `.py`？需要 → 就没拆干净。**
（见 DECISIONS「2026-09-10b」、review-plan §3.6.1 坑 22、`框架提案.md` §3）

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










def _b64(obj) -> str:
    r"""对象 → JSON（ensure_ascii=True，中文转 \uXXXX 纯 ASCII）→ base64 → JSON 字符串字面量。

    再包一层 json.dumps 是因为页面里 b64utf8("...") 需要一个 JS 字符串字面量；
    中文先转 \uXXXX 再 base64，atob() 才能无损还原
    （否则 UTF-8 字节被当 Latin-1 解会乱码——见 review-plan §3.6.1 坑 20）。
    """
    raw = obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=True)
    return json.dumps(base64.b64encode(raw.encode()).decode())


def render_html(data: dict, bundle: dict) -> str:
    """读 templates/ 下的三个文件，替换占位符，拼成**单文件** HTML。

    为什么模板外置：把 CSS/JS 写在 Python 字符串里，IDE 当普通文本（无高亮／补全／lint），
    且会让"把 HTML 删掉重写、报告结论一个字不变"这条完工标准失效——删 HTML 等于删 Python
    的一部分（见 DECISIONS「2026-09-10b」、review-plan §3.6.1 坑 22）。

    产物仍必须是**单文件离线 HTML**（模型与配置 base64 内嵌、Pyodide 本地重跑），
    所以这里在生成期把 CSS/JS **内联**回去，绝不用外链——外链会破坏离线可用性。

    ⚠ 改 `templates/sandbox.html` 时注意：**这个文件里的每一个字符都会原样进产物**，
    包括注释和空行。占位符前后**不要**加换行——`sandbox.css` / `sandbox.js` 提取时
    本身已含首尾换行，加了就会在产物里多出空行。需要写说明就写进本文档字符串，别写进模板。
    """
    tpl = ROOT / "templates"
    html = (tpl / "sandbox.html").read_text(encoding="utf-8")
    css = (tpl / "sandbox.css").read_text(encoding="utf-8")
    js = (tpl / "sandbox.js").read_text(encoding="utf-8")
    # 防呆：JS 里若出现 </script 字面量，HTML 解析器会在 <script> 内部提前闭合标签，
    # 后半段 JS 全部泄漏到页面上（见 review-plan §3.6.1 坑 20）。
    # 转成 <\/script——在 JS 字符串里两者等价，但 HTML 解析器不再认它。
    js = js.replace("</script", r"<\/script")
    boot = (SRC / "py_boot.py").read_text(encoding="utf-8")

    reps = {
        "__CSS__": css,
        "__JS__": js,
        "__DATA_B64__": _b64(data),
        "__MODEL_BUNDLE_B64__": _b64(bundle),
        "__PY_BOOT_B64__": _b64(boot),
    }
    for token, val in reps.items():
        html = html.replace(token, val)
    # 防呆：替换链断过一次（第二处误写 HTML.replace，把上一处注入的数据包覆盖回占位符，
    # 页面拿到的是 `__DATA_B64__` 这个未定义标识符 → 整页脚本崩）。宁可中断也不交付坏产物。
    left = [t for t in reps if t in html]
    if left:
        raise SystemExit(f"沙盘 HTML 里还有未替换的占位符：{left}——替换链断了，产物不可交付")
    return html


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
        # py_boot.py 是浏览器端的"启动脚本"，它的内容已经单独经 __PY_BOOT_B64__ 下发，
        # 再打进 bundle 就是同一份文本存两遍（还会让产物无谓变大）。
        if rel == "py_boot.py":
            continue
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
    html = render_html(data, bundle)
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

# 浏览器端（Pyodide）启动脚本 —— 由 src/sandbox.py 读取并 base64 注入 HTML。
#
# 来历：原是 src/sandbox.py 里的 `PY_BOOT = r'''...'''` 字符串常量——
#       "Python 字符串里写 Python"，IDE 当普通文本，无高亮、无补全、无 lint。
#       拆成真 .py 文件后（见 DECISIONS「2026-09-10b」、review-plan §3.6.1 坑 22）：
#         · 生成期：src/sandbox.py 读本文件内容 → base64 → 注入 <script>；
#         · 运行期：浏览器里 py.runPython(本文件内容)，定义 recompute() 供 JS 调用。
#
# 改动前必读的两条约束：
# 1. 本文件**只作为文本被读取与下发，不被 import**。它跑在浏览器里，依赖的
#    config_loader / model / lab 由 Pyodide 虚拟文件系统 /app/src 提供，
#    所以下面的 sys.path.insert 与 import 是**给浏览器用的**，不是给本机用的。
# 2. 本文件位于 src/ 下，因此会被 model_bundle() 连同其他 .py 一起打进 HTML——
#    这无害（无模块 import 它，只多占几 KB 文本），但意味着**改动会改变产物大小**。
#
# 不要在本文件里放"只有本机跑才有意义"的代码。



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
# 结论区①+②的数值：与生成期**同一个** build_vals，杜绝"生成期一套、浏览器一套"。
# 放在 try 里：万一它加载失败，只丢结论区刷新，不能让整个 recompute 未定义
# （那正是"面板动了数字不动"的根因之一）。
try:
    from verdict import build_vals as _build_vals
except Exception as _exc:            # noqa: BLE001
    print("verdict import skipped: %r" % (_exc,))
    _build_vals = None

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
        # cfg 必须一起传：有一批指标（外部锚、REIT 倍数等）需要 cfg 才算得出来，
        # 不传则为 NaN——结论区会显示 [待补] 而不是悄悄给个错值。
        mv = read_metrics(snap, cfg)
    except Exception as exc:
        # build_model 因某覆盖值抛错：返回空指标 + 错误，让前端显形，而不是整段静默失败
        err = "build_model failed: %r" % (exc,)
        print(err)
        return json.dumps({"metrics": {}, "texts": [], "error": err})
    metrics = {k: (None if mv.get(k) is None else mv.get(k)) for k in state.get("metrics", [])}
    # 结论区①+②的取值：同一份 snapshot、同一个 build_vals，与生成期三档值同源同算。
    # 少它，顶部结论就会停在生成快照上——拖滑块时 ①② 区不动、③ 区动，读数自相矛盾。
    vals = {}
    if _build_vals is not None:
        try:
            vals = _build_vals(snap, cfg)
        except Exception as exc:      # noqa: BLE001
            print("verdict vals skipped: %r" % (exc,))
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
    return json.dumps({"metrics": metrics, "texts": texts, "vals": vals, "error": err})

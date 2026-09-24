"""价格 → 净优势 → 份额：重卡换电份额 ＝ 换电份额天花板 × 算得过账的车队占比（2026-09-22 · 门② 重写）。

【为什么重写】2026-09-18g 版的份额链"按基准价归一、基准处乘数恒为 1"：配置里的渗透率
（短途 30%／中途 50%／长途 70%，加权 44.8%）在基准价上从来没被检验过——门① 逐群核对发现，
月租 13.3 下长途只有约 3% 的车队算得过账，模型却假设 70%（门① 一页纸第 2 节第四条）。

【现在的链条】
    两段价租金（保底＋超出按度）／服务费／充电价 → 本场景用户账（tco.build_scene_economics）
      → 按车队借钱成本三群（[fleet_capital_mix]），净优势为正的那部分车队占比（＝算得过账的占比）
      → 场景份额 ＝ 换电份额天花板（vehicles.heavy.scenes.*.swap_share_ceiling）× 算得过账的占比
      → 写进 swap_penetration，供规模链使用

【三条口径】
1. **天花板由站网与车型定，不由价格定。**车队全都算得过账时，换电最多能拿到的份额；三档见 [drivers.swap_share_ceiling]。
2. **算得过账的占比只依赖配置**（服务费、两段价、寿命），不依赖规模——所以在装配规模之前一次算定，不用探针、不迭代。
3. **下限 response_floor**：封闭短倒场景的补能方式由场景方定死，不随资金成本逐年重选，占比不低于它。
车队资金成本分布是经验假设（[fleet_capital_mix] 声明段），低置信度。
"""
from __future__ import annotations

from copy import deepcopy

_TIERS = ("low", "mid", "high")
_FIELDS = (("short", "短途"), ("mid", "中途"), ("long", "长途"))


def _break_even_rate(rates: list[float], adv: list[float]) -> float | None:
    """净优势由负转正落在哪个资金成本上。

    净优势对资金成本单调上升（车队的钱越贵，省下的首付越值钱），所以最多穿越一次。
    三档之间线性插值；三档全正返回 -inf（"全都够"）。

    【三档全负不能直接判"一个都不够"】那会让可服务份额在最高一档穿零的瞬间掉掉整整一档的权重，
    造出一个纯属算法的断崖。按最后一段的斜率把穿越点**外推**到三档之外，
    再交给 `_addressable` 的尾巴段线性走到零——两处配套，缺一处断崖就回来。
    """
    if all(a > 0 for a in adv):
        return float("-inf")
    if all(a <= 0 for a in adv):
        if len(adv) >= 2 and rates[-1] != rates[-2]:
            slope = (adv[-1] - adv[-2]) / (rates[-1] - rates[-2])
            if slope > 0:
                return rates[-1] + (-adv[-1]) / slope
        return float("inf")
    for i in range(len(adv) - 1):
        a0, a1 = adv[i], adv[i + 1]
        if a0 <= 0 < a1:
            span = a1 - a0
            return rates[i] + (rates[i + 1] - rates[i]) * (-a0 / span) if span else rates[i]
    return None


def _addressable(mix: list[tuple[float, float]], r_star: float | None) -> float:
    """资金成本高于 r* 的那部分车队占比。

    把三档当作车队分布上的三个点：资金成本 ≥ 低档的是全部（1.0），≥ 中档的是中＋高两档之和，
    ≥ 高档的只剩高档自己。两点之间线性插值。

    【最高一档必须带一条尾巴，否则会凭空造出一个台阶】
    如果"高档以上直接归零"，那么 r* 从略低于高档挪到略高于高档时，可服务份额会**一次性掉掉整个高档的权重**
    （按当前权重是 30 个百分点），下游渗透率随之出现一个纯属插值方式造成的断崖——那是算法的假象，不是车队的行为。
    真实情况是**最高一档本来就不是一个点**：个体司机与中小物流的资金成本是分散的，高档只是它的代表值。
    没有分布数据，就假定这条尾巴的宽度与下一档的间距相当（即延伸到 高档 ＋（高档 − 中档）），
    份额在尾巴上线性走到零。**这是一个声明的平滑约定，不是测算**；它不影响基准
    （基准处 r* 落在低档与中档之间），只影响价格拉得很远时那一段的形状。
    """
    if r_star is None or r_star == float("inf"):
        return 0.0
    if r_star == float("-inf"):
        return 1.0
    rates = [r for r, _ in mix]
    weights = [w for _, w in mix]
    total = sum(weights) or 1.0
    # S(r_i) ＝ 第 i 档及其以上的权重之和
    surv = [sum(weights[i:]) / total for i in range(len(weights))]
    if r_star <= rates[0]:
        return 1.0
    tail_end = rates[-1] + (rates[-1] - rates[-2] if len(rates) >= 2 else 0.0)
    if r_star >= tail_end:
        return 0.0
    if r_star >= rates[-1]:
        span = tail_end - rates[-1]
        if not span:
            return 0.0
        return surv[-1] * (1.0 - (r_star - rates[-1]) / span)
    for i in range(len(rates) - 1):
        if rates[i] <= r_star <= rates[i + 1]:
            span = rates[i + 1] - rates[i]
            if not span:
                return surv[i]
            t = (r_star - rates[i]) / span
            lo = 1.0 if i == 0 else surv[i]
            return lo + (surv[i + 1] - lo) * t
    return 0.0


def compute_response(config: dict, heavy) -> dict | None:
    """给出每个重卡场景的"算得过账的车队占比"与份额。heavy 为 tco.build_scene_economics 的结果。

    返回 None 表示这条链没接上（缺配置），调用方按天花板直接用、并在页面标出，绝不静默拍一个数。
    """
    mix_cfg = config.get("fleet_capital_mix")
    tco = config.get("tco_jpm") or {}
    if heavy is None or not mix_cfg:
        return None
    rates = [float(tco.get(f"fleet_discount_rate_{t}") or 0.0) for t in _TIERS]
    mix = [(rates[i], float(mix_cfg.get(t) or 0.0)) for i, t in enumerate(_TIERS)]
    floor = float((config.get("price_response") or {}).get("response_floor") or 0.0)
    heavy_scenes = {s.get("name"): s for s in
                    (config.get("vehicles", {}).get("heavy", {}).get("scenes", []) or [])}
    scenes: dict = {}
    pen = pen_spot = ceil_w = 0.0
    for field, name in _FIELDS:
        sc = getattr(heavy, field, None)
        cfg_sc = heavy_scenes.get(name)
        if sc is None or cfg_sc is None:
            continue
        adv_now = [getattr(sc, f"adv_mw_{t}", 0.0) for t in _TIERS]
        # 压力档：充电服务费不在均衡价、而是价格战现价撑满整个持有期（tco.py 已给出这组净优势）
        adv_spot = [getattr(sc, f"adv_mw_spot_{t}", 0.0) for t in _TIERS]
        a_now = max(floor, _addressable(mix, _break_even_rate(rates, adv_now)))
        a_spot = max(floor, _addressable(mix, _break_even_rate(rates, adv_spot)))
        # 【2026-09-24】删去 09-23 的 share_price_insensitive（份额恒为 1）：多班倒车的替代品是
        # 自备两套电池场站轮换，由 tco.py 的 charge_regime="depot_rotation" 表达，份额照常算。
        ceiling = float(cfg_sc.get("swap_share_ceiling", cfg_sc.get("swap_penetration")) or 0.0)
        w = float(cfg_sc.get("weight") or 0.0)
        scenes[name] = {
            "ceiling": ceiling,
            "addressable": a_now,
            "penetration": min(1.0, ceiling * a_now),
            "addressable_spot": a_spot,
            # 现价压力档的占比相对基准剩几成（名字沿用旧读数"份额乘数"）
            "multiplier": a_now,
            "multiplier_spot": (a_spot / a_now) if a_now else 0.0,
        }
        pen += w * scenes[name]["penetration"]
        pen_spot += w * min(1.0, ceiling * a_spot)
        ceil_w += w * ceiling
    if not scenes:
        return None
    return {
        "scenes": scenes,
        "weighted_penetration": pen,
        "weighted_penetration_spot": pen_spot,
        "weighted_ceiling": ceil_w,
    }


def applied_config(config: dict, response: dict | None) -> dict:
    """把"天花板 × 算得过账的占比"写进重卡三场景的 swap_penetration（深拷贝，不改入参）。

    链没接上（response 为 None）时，份额直接取天花板——页面上"算得过账的占比"读数会缺，看得见。
    """
    out = deepcopy(config)
    scenes = (response or {}).get("scenes", {})
    for sc in out.get("vehicles", {}).get("heavy", {}).get("scenes", []) or []:
        ceiling = float(sc.get("swap_share_ceiling", sc.get("swap_penetration")) or 0.0)
        info = scenes.get(sc.get("name"))
        sc["swap_penetration"] = info["penetration"] if info else ceiling
    return out


def effective_config(config: dict) -> tuple[dict, dict | None]:
    """装配前的一站式入口：算用户账 → 算占比 → 写份额。model.py 与 tracker.py 共用，口径只有一个家。"""
    from tco import build_scene_economics   # 局部引入，避免 tco ↔ price_response 循环
    response = compute_response(config, build_scene_economics(config))
    return applied_config(config, response), response

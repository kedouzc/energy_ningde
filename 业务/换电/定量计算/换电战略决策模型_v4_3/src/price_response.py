"""价格 → 净优势 → 份额：把补能服务费的定价接回换电渗透率（2026-09-18g 立）。

【为什么必须有这条链】
`vehicles.heavy.scenes.*.swap_penetration` 的声明段里写着，换电占纯电的份额由两件事决定：
① 网络密度（能不能用上），② **服务定价**（用得起就用不起）。
但在此之前，②这一半在程序里是断的——把换电服务费从 0.30 拉到 0.60，
第 3 章的九宫格会全线翻负，而模型的渗透率纹丝不动。**一个自己不响应自己结论的模型，
只能用来解释、不能用来推演。**本模块把②接上。

【链条】
    服务费 / 电池租金 / 充电服务费
      → 第 3 章的「换电净优势」（tco.py 的 adv_mw_*，按车队资金成本三档给出）
      → 净优势为正的那部分车队占比（＝可服务份额 addressable）
      → 相对基准价的可服务份额之比（＝份额乘数）
      → 乘到该场景的 swap_penetration 上

【三条口径，写在这里以防后人拆开各取一项】
1. **乘数按基准价归一，基准处恒为 1.0。**参考价存在 `[price_response]`，与 base.toml 的
   基准价逐项相等；所以不动滑块时乘数逐位是 1，**基线七个读数一格都不会动**。
   ⚠️ 改 base.toml 里的基准价时**必须同步改 `[price_response]` 的参考价**，
   否则基准情景会被自己的反馈推走——`changelog` 的 watch 行就是为了当场抓住这件事。
2. **只按价格差算，不重跑全模型。**换电服务费单价按构造等于配置值；电池租金单价与月租成正比；
   充电服务费是配置值。所以「换参考价之后净优势变多少」是一个解析量（每年每车的现金差额），
   不需要第二次装配。这既省时间，也避免了"渗透率变→规模变→租金单价变→渗透率再变"的循环。
3. **车队资金成本分布是经验假设，不是统计。**见 `[fleet_capital_mix]` 的声明段：
   营运重卡买方的资金成本结构没有任何公开数据，这三个权重是判断，标注为低置信度。
   它不影响基准（基准处乘数恒为 1），但它决定两件事：弹性的**陡峭程度**，
   以及下面第 4 条那个**上界**——所以"这三个数怎么错都不要紧"是错的读法。
4. **这条链对中途与长途只有下行弹性，没有上行弹性。**乘数的解析上界是 `1 / addressable_ref`；
   而基准价下中途与长途的净优势三档全正、可服务份额已经满格（＝1.0），**上界因此就是 1.0**——
   把换电服务费砍到零，这两个场景的渗透率一动不动。**降价换份额只在短途那一档里成立。**
   这不是实现缺陷，是"可服务份额"这个口径的直接后果：已经全员划算了，再便宜也没有新的人可争取。
   要表达"降价还能多拿份额"，需要的是另一条腿（网络密度／场景方接受度），而那条腿没有建模。
5. **对照档取的是兆瓦超充（`adv_mw_*`），不是常规快充。**三个对照里最苛刻的一个
   （同样的差额摊到更少的小时上），是有意的保守选择。
6. **快照上的读数来自探针（反馈前），九宫格来自正式装配（反馈后）。**基准处两者同源、完全一致；
   偏离基准时二者会差零点几个百分点（渗透率变动反过来微调了租金单价）。
   量小且方向无系统性，但页面上"可服务份额"与"净优势九宫格"逐位对账会差一点点，是已知的。
"""
from __future__ import annotations

from copy import deepcopy

_TIERS = ("low", "mid", "high")


def _prices(config: dict) -> dict[str, float]:
    """当前四个价格入参。改这里的任何一个，份额都应该有反应。"""
    tco = config.get("tco_jpm") or {}
    sb = config.get("swap_business") or {}
    return {
        "swap_service": float(sb.get("service_fee_rmb_kwh") or 0.0),
        "swap_rent_month": float(sb.get("battery_rent_rmb_kwh_month") or 0.0),
        "charge_service": float(tco.get("charge_service_fee_rmb_kwh") or 0.0),
    }


def _reference(config: dict) -> dict[str, float] | None:
    ref = config.get("price_response")
    if not ref:
        return None
    return {
        "swap_service": float(ref.get("ref_swap_service_fee_rmb_kwh") or 0.0),
        "swap_rent_month": float(ref.get("ref_battery_rent_rmb_kwh_month") or 0.0),
        "charge_service": float(ref.get("ref_charge_service_fee_rmb_kwh") or 0.0),
    }


def penetration_pinned(config: dict) -> bool:
    """份额是不是已经被人手工定过了。

    见 `[price_response].ref_heavy_penetration` 的声明：情景三档与沙盘的渗透率滑块
    都是对份额的**直接判断**，而且它们的理由（网络密度、场景方接受度）不在 TCO 模型里。
    这时再乘一道只建了 TCO 腿的反馈，是拿局部覆盖全局。故此处让位，只记读数、不作用。
    """
    ref = (config.get("price_response") or {}).get("ref_heavy_penetration")
    if not ref:
        return False
    scenes = config.get("vehicles", {}).get("heavy", {}).get("scenes", []) or []
    cur = [float(s.get("swap_penetration") or 0.0) for s in scenes]
    if len(cur) != len(ref):
        return True
    return any(abs(a - float(b)) > 1e-12 for a, b in zip(cur, ref))


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
    """给出每个重卡场景的份额乘数。heavy 为 tco.build_heavy_economics 的结果。

    返回 None 表示这条链没接上（缺配置），调用方按"不作用"处理，绝不静默拍一个数。
    """
    ref = _reference(config)
    mix_cfg = config.get("fleet_capital_mix")
    tco = config.get("tco_jpm") or {}
    if heavy is None or not ref or not mix_cfg:
        return None
    rates = [float(tco.get(f"fleet_discount_rate_{t}") or 0.0) for t in _TIERS]
    mix = [(rates[i], float(mix_cfg.get(t) or 0.0)) for i, t in enumerate(_TIERS)]
    now, base = _prices(config), ref
    sb = config.get("swap_business") or {}
    month_now = float(sb.get("battery_rent_rmb_kwh_month") or 0.0)
    # 月租为零时租金单价无法等比折回参考月租，这条链的第三项就整段丢失。
    # 与其抹掉它、照常给出一个看着正常的乘数（静默错值比崩溃更难发现），不如直接判定"没接上"。
    if month_now <= 0:
        return None
    floor = float((config.get("price_response") or {}).get("response_floor") or 0.0)
    pinned = penetration_pinned(config)

    consumption = {
        s.get("name"): float(s.get("energy_consumption_kwh_km") or 0.0)
        for s in config.get("vehicles", {}).get("heavy", {}).get("scenes", []) or []
    }
    scenes = {}
    for field, name in (("short", "短途"), ("mid", "中途"), ("long", "长途")):
        sc = getattr(heavy, field, None)
        if sc is None or not sc.annual_km:
            continue
        # 单车年耗电 ＝ 年里程 × 单公里能耗（与 tco.py 同一口径）
        annual_kwh = sc.annual_km * consumption.get(name, 0.0)
        if annual_kwh <= 0:
            continue
        # 租金单价 ＝ 年租金 ÷ 年耗电；它与月租成正比，所以换参考月租只是等比缩放
        rent_p_now = sc.rent_year_wan * 1e4 / annual_kwh  # noqa: E501  租金单价与月租成正比
        rent_p_ref = rent_p_now * (base["swap_rent_month"] / month_now)
        # 换到参考价后，换电每年的净差额少付多少（正数＝参考价下换电更便宜）
        delta_year = annual_kwh * (
            (now["swap_service"] - base["swap_service"])
            + (rent_p_now - rent_p_ref)
            - (now["charge_service"] - base["charge_service"])
        ) / 1e4
        adv_now = [getattr(sc, f"adv_mw_{t}", 0.0) for t in _TIERS]
        adv_ref = [a + delta_year for a in adv_now]
        # 压力档：充电服务费不回到成本地板、而把当前现价撑满整个持有期（tco.py 已给出这组净优势）
        adv_spot = [getattr(sc, f"adv_mw_spot_{t}", 0.0) for t in _TIERS]
        a_now = _addressable(mix, _break_even_rate(rates, adv_now))
        a_ref = _addressable(mix, _break_even_rate(rates, adv_ref))
        a_spot = _addressable(mix, _break_even_rate(rates, adv_spot))
        # 参考价上本场景本身就无人可服务时，"相对参考价的比值"没有意义——
        # 此时静默给 0 会把乘数永久钉在下限上，而页面看不出为什么。判定为"没接上"，整条链让位。
        if a_ref <= 0:
            return None
        raw = a_now / a_ref
        raw_spot = a_spot / a_ref
        scenes[name] = {
            "addressable": a_now,
            "addressable_ref": a_ref,
            "addressable_spot": a_spot,
            # 下限见 [price_response].response_floor 的声明：封闭短倒场景的补能方式由场景方定死，
            # 不随资金成本逐年重选，所以份额不会因为价格翻负而归零。
            "multiplier": max(floor, raw),
            "multiplier_raw": raw,
            "multiplier_spot": max(floor, raw_spot),
        }
    if not scenes:
        return None
    # 加权渗透率：三场景的销量权重 × 各自渗透率。
    # 【必须用**作用后**的渗透率】这个读数的名字是"模型加权"，它就该等于模型真正在用的那个份额。
    # 若取配置里的原值，拉动价格滑块时九宫格翻负、份额乘数掉下去，而这个总量读数纹丝不动——
    # 那正是这条链要修的毛病在读数层原样复现。基准处乘数恒为 1，所以基准读数不变。
    heavy_scenes = config.get("vehicles", {}).get("heavy", {}).get("scenes", []) or []
    pen_now = pen_spot = 0.0
    for s in heavy_scenes:
        nm = s.get("name")
        if nm not in scenes:
            continue
        w = float(s.get("weight") or 0.0)
        p = float(s.get("swap_penetration") or 0.0)
        # 份额已被手工定过时这条链让位，配置里的 p 就是最终值，不再乘
        m = 1.0 if pinned else scenes[nm]["multiplier"]
        pen_now += w * min(1.0, p * m)
        pen_spot += w * min(1.0, p * scenes[nm]["multiplier_spot"])
    return {
        "at_reference": now == base,
        "pinned": pinned,
        "scenes": scenes,
        "prices": now,
        "reference": base,
        "weighted_penetration": pen_now,
        "weighted_penetration_spot": pen_spot,
    }


def applied_config(config: dict, response: dict | None) -> dict:
    """把份额乘数乘到重卡三场景的 swap_penetration 上（上限 1.0）。

    乘数为 1.0 时原样返回同一个对象——基准情景因此连一次 deepcopy 都不做。
    """
    if not response or response.get("at_reference") or response.get("pinned"):
        return config
    scenes = response["scenes"]
    if all(abs(v["multiplier"] - 1.0) < 1e-12 for v in scenes.values()):
        return config
    out = deepcopy(config)
    for sc in out.get("vehicles", {}).get("heavy", {}).get("scenes", []) or []:
        m = scenes.get(sc.get("name"), {}).get("multiplier")
        if m is None:
            continue
        sc["swap_penetration"] = min(1.0, float(sc.get("swap_penetration") or 0.0) * m)
    return out

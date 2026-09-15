# -*- coding: utf-8 -*-
"""桶①·车队周转增长：逐年推保有量，不用 CAGR。

【2026-09-14 重写】为什么不再用 CAGR
──────────────────────────────────────────────────────────────────────
09-13 那版把"保有量追平流量"这段路径压成了一个常数 CAGR，再喂进闭式永续公式。
两处都错：
  ① **路径是凹的**（逐年减速趋近渐近线），常数 CAGR 不是它；
  ② **程序本来就能逐年算**——用闭式近似代替可算的路径，
     违反"让程序算细、报告读粗"（那一版是让程序算粗，再包装成精确）。
更根本的是那一版把**终局年的流量率冻结到永远**，等于隐含声明
"2060 年中国还有一半重卡烧柴油"——**一个没人会为它辩护的终局状态，藏在机制里从没被说出口**。

【现在怎么做】
──────────────────────────────────────────────────────────────────────
1. **流量曲线**：重卡用 logistic 延长（天花板在 base.toml 声明，k/t0 由**预测窗口自己的两个端点**
   拟合——2026-09-14 从"外部锚点＋窗口首年"改过来，原因见 `_flow_curve`）；
   城配/出租/网约终局年已近饱和，延长期持平。
2. **保有渗透**＝过去一个更新周期的流量均值——这是 `nev_rates` 是流量口径的直接推论，
   **不需要新拍任何数**（保有量、更新周期、流量率三个入参都已在 base.toml）。
3. **只让第 1 层走**：换电占电动（第 2 层）与 CATL 份额（第 3 层）在延长期**冻结**。
   第 2 层实测在跌（见 `topics/竞争格局` 与 base.toml 声明段），冻结已是偏乐观的一侧；
   第 3 层已近终局。**冻结是一个声明，写在这里，不藏在代码里。**
4. **增长要付钱**：`fcff/(wacc−g)` 白拿增长。逐年用 `(1 − g_t/ROIC)` 扣增长资本，
   ROIC 由覆盖倍数反推（模型自己的数）。
5. **地平线之后持平**，不做永续增长。

【桶①的边界——防重复计价】
> **桶① ≡ 相对「规模冻结在终局年」的永续账的增量，且仅此。**
> 第 6 章论证拍定倍数时，**成长性理由只能用桶①之外的部分**，
> 否则同一段增长会被算两次（同 `topics/资本闭环` 那条"三层混一层就是重复计价"）。

【口径与保守偏向】
· 窗口前的历史流量用首年值回推（实际历史远低于此）⇒ 终局年保有渗透**偏高**、剩余空间**偏低**。**保守。**
· 这是一次**标定**不是精算（方法论主线③）：精算要逐年重算 capex 与折旧。
  本模块回答"桶①在押注部分里占多大"，不替代终局年的任何一个读数。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, asdict, field
from typing import Any

_TYPE_TO_CATEGORY = {
    "heavy": "heavy", "city": "city",
    "taxi": "passenger_ops", "ridehail": "passenger_ops", "robotaxi": "passenger_ops",
    "private": "private",
}
# 站型 → 它服务的车型（与 scale.py 的四池一一对应）。
# 这张表只为「延长期承载力」那一节按站型报读数而存在；少一个池或多一个池都当场中断，
# **不许静默按 1.0 处理**——指针悬空要在装配时炸，不能在报告里静静地写成"不需要扩容"。
_POOL_VEHICLE_TYPES = {
    "qiji75_short": ("heavy",),
    "qiji75_trunk": ("heavy",),
    "choco25_passenger": ("taxi", "ridehail"),
    "choco35_city": ("city",),
}

# 延长期窗口不是拍的年数，是一个**收敛判据**：推到保有量年增速降到 _GROWTH_FLOOR 以下为止，
# 之后持平。
#
# 为什么 2026-09-14 从"写死 15"改成判据：写死的 15 读起来像借了运营年限的 15，
# 而**运营年限从换电站投产年起算，和终局年后第几年是两件事，只是数字撞了**。
# 借来的理由是理由的赝品——曲线一改，写死的 15 会悄悄变得或长或短，而没有任何东西会报警。
# 判据自己会动。当前参数下判据正好落在终局年 +15 年：**这次改口径，baseline 一个数没动。**
# 判据是两条，缺一不可：
#   ① 当年增速 < _GROWTH_FLOOR —— "此刻看起来平了"；
#   ② 再推到兜底上限也只多长 _RESIDUAL_TOL —— "**截掉的那一段确实小**"。
# 只有 ① 会被一条爬得极慢的曲线骗过去：它每年只长 0.4%，第一年就"平了"，
# 于是地平线塌到 1 年、桶① 静静地变成 0。**"增速小"和"没剩多少"是两回事。**
_GROWTH_FLOOR = 0.005     # 年增速 < 0.5% 视作保有量路径已压平
_RESIDUAL_TOL = 0.02      # 截断处之后最多还能长 2%，否则不算压平
_HORIZON_CAP = 40         # 兜底：判据不收敛就中断，不许静默拉长地平线


@dataclass
class TypePath:
    key: str
    ceiling: float
    cycle_years: float
    stock_share_terminal: float
    stock_share_end: float
    ratio: float
    weight_gwh: float
    flows: dict[int, float] = field(default_factory=dict)


@dataclass
class PoolCapacity:
    """延长期末，某个站型「需要多少倍承载力」与「单站白拿多少倍」的对账。

    口径（这一段是声明，不是计算副产品）：
    · **延长期不假设任何单站扩容。** 需求超出单站既有物理余量的部分，一律当成「新建站」，
      其资本代价已由 `(1 − g/ROIC)` 按**存量平均资本强度**全额计提。
    · 双工位 / 电网增容只是**更便宜的替代路径**，不进模型——它们只能让代价更低。
      所以 `free_share` 是一块**已经付过钱、但其实不用付**的保守量，不是可用的余粮。
    """
    pool: str
    need_ratio: float          # 延长期末该池车队 ÷ 终局年（= 需要的承载力倍数）
    headroom_ratio: float      # 单站物理上限 ÷ 规划能力（= 不新建站能白拿的倍数）
    binding: str               # 单站物理上限卡在哪一侧："手速" | "能量"
    free_share: float          # 该池增量中落在物理余量内的比例（0=全靠新建，1=全靠余量）
    throughput_share: float    # 该池终局年日换电次数占全网比重（加权用）


@dataclass
class TurnoverResult:
    types: list[TypePath] = field(default_factory=list)
    index: dict[int, float] = field(default_factory=dict)   # 逐年换电车队指数（终局年=1）
    roic: float = 0.0
    ev_frozen_yi: float = 0.0
    ev_turnover_yi: float = 0.0
    bucket1_ev_yi: float = 0.0
    bucket1_catl_yi: float = 0.0
    bucket1_share_of_bet: float = 0.0
    implied_multiple: float = 0.0
    end_index: float = 0.0
    horizon_years: int = 0                 # 延长期年数，由收敛判据定，不是拍的
    pools: list[PoolCapacity] = field(default_factory=list)
    free_capacity_share: float = 0.0       # 延长期增量中由既有站物理余量承接的比重（加权）

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["types"] = [asdict(t) for t in self.types]
        d["pools"] = [asdict(x) for x in self.pools]
        return d


def _crf(i: float, n: int = 15) -> float:
    return i / (1.0 - (1.0 + i) ** -n)


def _solve_i(target: float, n: int = 15) -> float:
    lo, hi = 1e-4, 0.60
    for _ in range(120):
        m = (lo + hi) / 2.0
        if _crf(m, n) < target:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2.0


def _flow_curve(spec: dict, y0: int, y_end: int) -> tuple[dict[int, float], float]:
    """逐年流量渗透率曲线。返回 (年→流量, 天花板)。

    重卡：logistic 延长，L 声明、k/t0 由**窗口自己的两个端点** (y0, rates[0]) 与
    (y_last, rates[-1]) 定死；**窗口内一律用声明的 nev_rates，不被曲线覆盖**。
    其余车型：终局年已近饱和，延长期持平；窗口内用配置值。
    窗口之前一律用首年值回推（保守，见模块 docstring）。

    【2026-09-14 改了拟合的两个点，原因】
    ────────────────────────────────────────────────────────────
    原来两点是 (nev_anchor_year, nev_anchor_rate) 与 (y0, rates[0])——一个**外部观测点**
    加窗口首年。中性档看不出问题（那条 nev_rates 本来就是这么生成的），
    但情景轴把整条 nev_rates 上下平移 ±15% 时，**锚点不动**，于是：
      · 悲观档首年被压到几乎贴着锚点 → 斜率 k 塌掉 → 曲线爬 40 年还没压平（这次是它把构建打断的）；
      · 而且曲线会**覆盖窗口内的声明值**：悲观档 turnover 眼里的终局年渗透 ≈0.33，
        scale.py 眼里是声明的 0.50——**同一个数两个家，在情景档里差了一半，没有任何东西报警。**
    改成用窗口自己的两个端点拟合，两件事一起消失：延长期与窗口天然接得上（曲线穿过端点），
    情景轴平移整条 nev_rates 时斜率随之平移，**不再出现"轴动了一半"这种半吊子形变**。
    `nev_anchor_*` 保留在 base.toml：它是**中性档那条 nev_rates 的生成依据**与跟踪对账基准
    （tracker 拿实测比它），不再参与延长期拟合——一个数一个用途。
    """
    rates = list(spec["nev_rates"])
    n = len(rates)
    years = list(range(y0, y0 + n))
    out = {y: r for y, r in zip(years, rates)}
    L = spec.get("nev_ceiling")
    L = (L["v"] if isinstance(L, dict) else L) if L is not None else None

    if L is not None and n >= 2 and max(rates) < L:
        y_last = years[-1]
        lg = lambda p: math.log(p / (L - p))
        k = (lg(rates[-1]) - lg(rates[0])) / (y_last - y0)
        if k <= 0:
            raise ValueError("窗口内渗透率不是单调上升，logistic 延长无从谈起——"
                             f"nev_rates={rates}")
        t0 = y_last - lg(rates[-1]) / k
        for y in range(y_last + 1, y_end + 1):      # 只延长，不覆盖窗口内的声明值
            out[y] = L / (1.0 + math.exp(-k * (y - t0)))
    else:
        L = rates[-1]
        for y in range(years[-1] + 1, y_end + 1):
            out[y] = rates[-1]          # 已近饱和，持平
    for y in range(y0 - 40, y0):
        out[y] = rates[0]               # 窗口前回推（保守）
    return out, L


def _pool_capacity(snapshot, ratio: dict[str, float]) -> tuple[list[PoolCapacity], float]:
    """延长期末，四个站型各自「需要多少倍承载力」与「单站白拿多少倍」的对账。

    它回答的是一句具体的追问：**终局年按 2030 车队规模建成的站网，2030 之后车队还在长，
    承载力从哪来？** 三条路——填满单站既有物理余量（免费）、加工位、电网增容（后两条更便宜），
    以及新建站（最贵）。**模型一律按最贵的那条计价**，所以这里报出来的 `free_share`
    是一块已经付过钱、其实不必付的保守量，不是可以花掉的余粮。

    这里只报读数、不改任何现金流。会中断的只有一种情况：站型与车型的对应关系接不上
    （新增站池忘了登记、或车型被删）——那会让读数静静地变成"不需要扩容"，比报错危险得多。
    """
    diag = getattr(snapshot.scale, "station_capacity_diagnostics", None) or {}
    demand = getattr(snapshot.scale, "target_station_demand", None) or {}
    missing = set(diag) ^ set(_POOL_VEHICLE_TYPES)
    if diag and missing:
        raise ValueError(f"站型与承载力对照表对不上：{sorted(missing)}——"
                         "新增站池必须在 turnover._POOL_VEHICLE_TYPES 登记，不许默认按 1.0 处理")
    rows, incr, free_incr, thr_all = [], [], [], []
    for pool, vts in _POOL_VEHICLE_TYPES.items():
        if pool not in diag:
            continue
        unknown = [v for v in vts if v not in ratio]
        if unknown:
            raise ValueError(f"站型 {pool} 挂的车型 {unknown} 不在延长期路径里——"
                             "要么车型改了名，要么它没有 nev_rates，两种都得先说清楚")
        need = max(ratio[v] for v in vts)
        d = diag[pool]
        plan = float(d["planning_capacity"])
        head = (float(d["physical_limit"]) / plan) if plan else 1.0
        binding = "手速" if d["mechanical_limit"] <= d["energy_limit"] else "能量"
        inc = max(0.0, need - 1.0)                       # 该池需要的增量倍数
        free = 1.0 if inc <= 0 else min(1.0, max(0.0, head - 1.0) / inc)
        thr = float(demand.get(pool, 0.0)) * plan        # 终局年日换电次数（加权底）
        rows.append(PoolCapacity(pool=pool, need_ratio=need, headroom_ratio=head,
                                 binding=binding, free_share=free, throughput_share=thr))
        incr.append(thr * inc)
        free_incr.append(thr * inc * free)
        thr_all.append(thr)
    thr_total = sum(thr_all) or 1.0
    for r in rows:
        r.throughput_share = r.throughput_share / thr_total
    total_inc = sum(incr)
    return rows, (sum(free_incr) / total_inc if total_inc else 0.0)


def build_turnover(config: dict, snapshot) -> TurnoverResult:
    fin = config["finance"]
    wacc = fin["wacc"]; crf0 = fin["capital_recovery_factor"]
    own = fin["construction_ownership"]
    sb = snapshot.swap_business
    ebitda = sb.ebitda_yi
    ev_perp = sb.dcf_ev_perpetual_yi
    debt = sb.dcf_valuation_debt_yi
    # CRF 的 n 是**运营年限**（从换电站投产年起算），和延长期年数没有关系；
    # 此前两处都写死 15，读起来像同一个 15，改口径时必然连坐。现在各自回各自的家。
    life = config["finance"]["model_horizon_years"]
    life = int(life["v"] if isinstance(life, dict) else life)
    # ROIC ＝ 终局年净现金流 ÷ 全周期资本。两边都是同一层的钱（税后、全投资口径），
    # 所以这个比值就是"这门生意每投一块钱，一年赚回几分"，正好是增长资本该按的比率。
    #
    # 【2026-09-15 改·原 R7】原来写的是 `_solve_i(EBITDA覆盖 × CRF)`，反推出 16.69%。
    # 那是**税前**的项目回报，而被它扣减的 netcf 是**税后**现金流——
    # 分子税后、分母税前，扣减因此偏轻，桶① 偏大。改完 1,318.2 → 912.8 亿。
    lifecycle_capital = snapshot.capex.annual_capital_requirement_yi / crf0 if crf0 else 0.0
    netcf0 = ev_perp * wacc
    roic = (netcf0 / lifecycle_capital) if lifecycle_capital else 0.0

    tgt = config["meta"].get("target_year")
    tgt = int(tgt["v"] if isinstance(tgt, dict) else tgt)
    y0 = tgt - len(config["vehicles"]["heavy"]["nev_rates"]) + 1
    y_scan = tgt + _HORIZON_CAP        # 先推到兜底上限，再由判据截断

    ys = getattr(snapshot.scale, "yearly_stock", None) or {}
    try:
        gwh_by_cat = ys["stock"]["onboard_gwh"][str(tgt)]
    except Exception:
        gwh_by_cat = {}

    paths: list[dict] = []
    per_type_index: list[tuple[float, dict[int, float]]] = []
    for key, spec in config.get("vehicles", {}).items():
        if not isinstance(spec, dict) or "nev_rates" not in spec:
            continue
        cyc = spec.get("replacement_cycle_years")
        cyc = float(cyc["v"] if isinstance(cyc, dict) else cyc)
        if not cyc:
            continue
        flows, L = _flow_curve(spec, y0, y_scan)
        n = int(round(cyc))
        stock = {y: sum(flows[y - i] for i in range(n)) / n for y in range(y0, y_scan + 1)}
        base = stock[tgt]
        if base <= 0:
            continue
        idx = {y: stock[y] / base for y in range(tgt, y_scan + 1)}
        cat = _TYPE_TO_CATEGORY.get(key)
        w = float(gwh_by_cat.get(cat, 0.0)) if cat else 0.0
        paths.append({"key": key, "L": L, "cyc": cyc, "base": base,
                      "stock": stock, "flows": flows, "w": w})
        per_type_index.append((w, idx))

    tot_w = sum(w for w, _ in per_type_index) or float(len(per_type_index) or 1)
    index = {}
    for y in range(tgt, y_scan + 1):
        if sum(w for w, _ in per_type_index) > 0:
            index[y] = sum(w * ix[y] for w, ix in per_type_index) / tot_w
        else:
            index[y] = sum(ix[y] for _, ix in per_type_index) / len(per_type_index)

    # ── 收敛判据决定延长期长度（不是拍年数）
    horizon = 0
    prev = 1.0
    for y in range(tgt + 1, y_scan + 1):
        g = index[y] / prev - 1.0
        prev = index[y]
        residual = index[y_scan] / index[y] - 1.0
        if g < _GROWTH_FLOOR and residual < _RESIDUAL_TOL:
            horizon = y - tgt
            break
    if not horizon:
        raise ValueError(
            f"车队指数在终局年后 {_HORIZON_CAP} 年内没有压平"
            f"（判据：年增速 <{_GROWTH_FLOOR:.1%} 且残余 <{_RESIDUAL_TOL:.0%}；"
            f"末年指数 {index[y_scan]:.3f}）：要么天花板或更新周期被改坏了，"
            "要么这条曲线本来就不该用「推到压平」这个判据。"
            "不许把 _HORIZON_CAP 调大了事——先说清楚为什么它不收敛。")
    y_end = tgt + horizon
    index = {y: v for y, v in index.items() if y <= y_end}

    types = [TypePath(key=d["key"], ceiling=d["L"], cycle_years=d["cyc"],
                      stock_share_terminal=d["base"], stock_share_end=d["stock"][y_end],
                      ratio=d["stock"][y_end] / d["base"], weight_gwh=d["w"],
                      flows={y: round(d["flows"][y], 4) for y in range(tgt, y_end + 1)})
             for d in paths]

    # 逐年折现：现金流按车队指数缩放，增量按 ROIC 扣增长资本
    netcf = ev_perp * wacc
    ev_turn, prev = 0.0, 1.0
    for j, y in enumerate(range(tgt + 1, y_end + 1), start=1):
        cur = index[y]
        g = (cur / prev) - 1.0 if prev > 0 else 0.0
        cf = netcf * cur * max(0.0, 1.0 - (g / roic if roic else 0.0))
        ev_turn += cf / (1.0 + wacc) ** j
        prev = cur
    ev_turn += (netcf * index[y_end] / wacc) / (1.0 + wacc) ** horizon

    pools, free_share = _pool_capacity(snapshot, {t.key: t.ratio for t in types})

    catl_perp = max(0.0, ev_perp - debt) * own
    catl_turn = max(0.0, ev_turn - debt) * own
    bet = sb.catl_attributable_value_yi - catl_perp
    return TurnoverResult(
        types=types, index={y: round(v, 4) for y, v in index.items()}, roic=roic,
        ev_frozen_yi=ev_perp, ev_turnover_yi=ev_turn,
        bucket1_ev_yi=ev_turn - ev_perp, bucket1_catl_yi=catl_turn - catl_perp,
        bucket1_share_of_bet=((catl_turn - catl_perp) / bet) if bet else 0.0,
        implied_multiple=(ev_turn / ebitda) if ebitda else 0.0,
        end_index=index[y_end],
        horizon_years=horizon, pools=pools, free_capacity_share=free_share,
    )


def print_turnover(r: TurnoverResult) -> None:
    print("\n" + "═" * 78)
    print("桶① · 车队周转增长（逐年推保有量；流量曲线由 logistic 延长，第 2、3 层冻结）")
    print("═" * 78)
    print("  %-10s %8s %6s %10s %10s %8s %9s" % (
        "车型", "天花板", "周期", "终局保有", "末年保有", "倍数", "装机权重"))
    for t in r.types:
        print("  %-10s %7.0f%% %6.0f %9.1f%% %9.1f%% %8.2f %9.1f" % (
            t.key, t.ceiling * 100, t.cycle_years,
            t.stock_share_terminal * 100, t.stock_share_end * 100, t.ratio, t.weight_gwh))
    print("  换电车队指数（终局年=1）：" + "  ".join(
        "%d:%.2f" % (y, v) for y, v in sorted(r.index.items()) if (y % 5 == 0 or y == max(r.index))))
    print("  隐含项目 ROIC %.2f%%" % (r.roic * 100))
    print("  永续账（规模冻结）EV {:,.1f} 亿 → 计周转增长 {:,.1f} 亿（隐含 {:.2f}×）".format(
        r.ev_frozen_yi, r.ev_turnover_yi, r.implied_multiple))
    print("  **桶①（CATL 归属口径）= {:+,.1f} 亿，占押注部分的 {:.0f}%**".format(
        r.bucket1_catl_yi, r.bucket1_share_of_bet * 100))
    if r.pools:
        print("  ── 延长期承载力对账（终局年站网 = 1.00；不假设任何单站扩容）")
        print("  %-18s %8s %8s %6s %8s %8s" % ("站型", "需要倍数", "单站余量", "卡在", "免费承接", "吞吐权重"))
        for x in r.pools:
            print("  %-18s %7.2f× %7.2f× %6s %7.0f%% %7.0f%%" % (
                x.pool, x.need_ratio, x.headroom_ratio, x.binding,
                x.free_share * 100, x.throughput_share * 100))
        print("  延长期新增需求中 {:.0f}% 落在既有站的物理余量里——**模型仍按新建站全额计提了资本**，"
              "\n  这一块是桶①之外没认领的保守量，不是可以花掉的余粮。".format(r.free_capacity_share * 100))
    print("  余下才是桶②基准外期权 ＋ 桶③风险低于假设 ＋ 桶④纯重估押注。"
          "\n  **桶①可被市场之外的东西证伪（渗透率曲线、车型数、区域盈利都可观察）；桶④不能。**")

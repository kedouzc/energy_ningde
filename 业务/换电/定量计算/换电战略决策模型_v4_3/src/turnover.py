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
1. **流量曲线**：重卡用 logistic（天花板在 base.toml 声明，k/t0 由最近两个年度实测拟合）；
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
HORIZON_AFTER_TERMINAL = 15        # 延长到终局年后 15 年；之后持平


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

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["types"] = [asdict(t) for t in self.types]
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

    重卡：logistic，L 声明、k/t0 由 (nev_anchor_year, nev_anchor_rate) 与 (y0, rates[0]) 两点定死。
    其余车型：终局年已近饱和，延长期持平；窗口内用配置值。
    窗口之前一律用首年值回推（保守，见模块 docstring）。
    """
    rates = list(spec["nev_rates"])
    n = len(rates)
    years = list(range(y0, y0 + n))
    out = {y: r for y, r in zip(years, rates)}
    L = spec.get("nev_ceiling")
    L = (L["v"] if isinstance(L, dict) else L) if L is not None else None

    if L is not None and "nev_anchor_rate" in spec:
        ay = int(spec["nev_anchor_year"]); ar = float(spec["nev_anchor_rate"])
        lg = lambda p: math.log(p / (L - p))
        k = (lg(rates[0]) - lg(ar)) / (y0 - ay)
        t0 = ay - lg(ar) / k
        for y in range(y0, y_end + 1):
            out[y] = L / (1.0 + math.exp(-k * (y - t0)))
    else:
        L = rates[-1]
        for y in range(years[-1] + 1, y_end + 1):
            out[y] = rates[-1]          # 已近饱和，持平
    for y in range(y0 - 40, y0):
        out[y] = rates[0]               # 窗口前回推（保守）
    return out, L


def build_turnover(config: dict, snapshot) -> TurnoverResult:
    fin = config["finance"]
    wacc = fin["wacc"]; crf0 = fin["capital_recovery_factor"]
    own = fin["construction_ownership"]
    sb = snapshot.swap_business
    ebitda = sb.ebitda_yi
    ev_perp = sb.dcf_ev_perpetual_yi
    debt = sb.dcf_valuation_debt_yi
    roic = _solve_i(sb.forward_to_required_ebitda * crf0)

    tgt = config["meta"].get("target_year")
    tgt = int(tgt["v"] if isinstance(tgt, dict) else tgt)
    y0 = tgt - len(config["vehicles"]["heavy"]["nev_rates"]) + 1
    y_end = tgt + HORIZON_AFTER_TERMINAL

    ys = getattr(snapshot.scale, "yearly_stock", None) or {}
    try:
        gwh_by_cat = ys["stock"]["onboard_gwh"][str(tgt)]
    except Exception:
        gwh_by_cat = {}

    types: list[TypePath] = []
    per_type_index: list[tuple[float, dict[int, float]]] = []
    for key, spec in config.get("vehicles", {}).items():
        if not isinstance(spec, dict) or "nev_rates" not in spec:
            continue
        cyc = spec.get("replacement_cycle_years")
        cyc = float(cyc["v"] if isinstance(cyc, dict) else cyc)
        if not cyc:
            continue
        flows, L = _flow_curve(spec, y0, y_end)
        n = int(round(cyc))
        stock = {y: sum(flows[y - i] for i in range(n)) / n for y in range(y0, y_end + 1)}
        base = stock[tgt]
        if base <= 0:
            continue
        idx = {y: stock[y] / base for y in range(tgt, y_end + 1)}
        cat = _TYPE_TO_CATEGORY.get(key)
        w = float(gwh_by_cat.get(cat, 0.0)) if cat else 0.0
        types.append(TypePath(key=key, ceiling=L, cycle_years=cyc,
                              stock_share_terminal=base, stock_share_end=stock[y_end],
                              ratio=stock[y_end] / base, weight_gwh=w,
                              flows={y: round(flows[y], 4) for y in range(tgt, y_end + 1)}))
        per_type_index.append((w, idx))

    tot_w = sum(w for w, _ in per_type_index) or float(len(per_type_index) or 1)
    index = {}
    for y in range(tgt, y_end + 1):
        if sum(w for w, _ in per_type_index) > 0:
            index[y] = sum(w * ix[y] for w, ix in per_type_index) / tot_w
        else:
            index[y] = sum(ix[y] for _, ix in per_type_index) / len(per_type_index)

    # 逐年折现：现金流按车队指数缩放，增量按 ROIC 扣增长资本
    netcf = ev_perp * wacc
    ev_turn, prev = 0.0, 1.0
    for j, y in enumerate(range(tgt + 1, y_end + 1), start=1):
        cur = index[y]
        g = (cur / prev) - 1.0 if prev > 0 else 0.0
        cf = netcf * cur * max(0.0, 1.0 - (g / roic if roic else 0.0))
        ev_turn += cf / (1.0 + wacc) ** j
        prev = cur
    ev_turn += (netcf * index[y_end] / wacc) / (1.0 + wacc) ** HORIZON_AFTER_TERMINAL

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
    print("  余下才是桶②基准外期权 ＋ 桶③风险低于假设 ＋ 桶④纯重估押注。"
          "\n  **桶①可被市场之外的东西证伪（渗透率曲线、车型数、区域盈利都可观察）；桶④不能。**")

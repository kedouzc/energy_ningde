"""结论区（①顶部结论 + ②定性逻辑）的数值：唯一算法，生成期与浏览器共用。

为什么单列这一个文件
--------------------
顶部结论里那几句话的每个 {} 都是一个数。此前这些数由 `sandbox._build_verdict`
在**生成期**用基线算一次就写死进 HTML——拖滑块、点三档时 ③ 定量看板区会动，
①② 区却纹丝不动（数值、滑块位置、档位高亮三者不同源同刻，信任归零）。

修法不是"把同样的算式在 JS 里再写一遍"（那必然漂移），而是：

    build_vals(snap, cfg)  ← 只有这一份算法
        ├─ 生成期：sandbox.py 对悲观/中性/乐观三档各调一次 → D.tierVals
        └─ 运行期：py_boot.recompute() 里 Pyodide 重跑 build_model 后调一次 → vals

JS 侧不写任何公式，只做字符串替换。这既守住「同源单程、绝不外推」，也让
"改一处、两处都变"成为结构上的必然，而不是靠记得同步。

本文件**不写任何定性文案**（那是 narrative/沙盘结论区.md 的事），只负责算数。
"""

from __future__ import annotations

from lab import read_metrics
from scale import operating_market_total

# 占位符清单：与 narrative/沙盘结论区.md 里的 {key} 一一对应。
# 生成期用它与模板实际出现的占位符做集合比对，缺一个就报错终止——
# 不靠"记得填"，靠机器判。
PLACEHOLDER_KEYS = frozenset({
    # — 业绩 —
    "target_year", "veh_ops", "veh_mkt", "share", "repl_gwh", "repl_share_pct",
    # — 估值 —
    "dist_cash", "ebitda", "mult", "own_pct", "mktcap",
    # — 卡位 —
    "energy", "elec_share", "batt_station", "storage_share", "stations",
    # — ROI —
    "peak_call", "reit_mult",
    # — 重卡 —
    "veh_heavy", "heavy_stock_wan", "heavy_pen_pct", "heavy_fleet_gwh",
    "heavy_station_gwh", "heavy_repl_gwh", "heavy_life_yrs", "heavy_repl_cycle",
    "energy_unit_kwh",
    # — 全成本 TCO：N1=模型电池寿命 / N2=更新周期 —
    "tco_swap_wan", "tco_swap_kwh", "tco_lng_wan", "tco_lng_kwh",
    "tco_diesel_wan", "tco_diesel_kwh",
    "tco_swap_wan_9", "tco_swap_kwh_9", "tco_lng_wan_9", "tco_lng_kwh_9",
    "tco_diesel_wan_9", "tco_diesel_kwh_9",
})


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


def _pct(num, den, d: int = 2):
    if not num or not den:
        return None
    try:
        return round(float(num) / float(den) * 100.0, d)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def build_vals(snap, cfg: dict) -> dict:
    """结论区全部占位符的取值。生成期与 Pyodide 复用同一函数。

    取不到的键一律 None——前端渲染成 [待补]，而不是编一个数填上去。
    """
    mv = read_metrics(snap)

    def g(key: str):
        return mv.get(key)

    fin = cfg.get("finance") or {}
    meta = cfg.get("meta") or {}
    veh_heavy_cfg = (cfg.get("vehicles") or {}).get("heavy") or {}

    # —— 业绩 ——
    raw_ops = (g("ops.veh_commercial") or 0) + (g("ops.veh_passenger_ops") or 0)
    veh_ops = _r(raw_ops, 1)
    mkt = operating_market_total(cfg)
    veh_mkt = _r(mkt, 1)
    repl_gwh = g("mfg.repl_gwh")
    # 2026E 出货分母在 [financial_2026e]（不是 [finance]），别写错段名
    shipments = (cfg.get("financial_2026e") or {}).get("power_battery_shipments_gwh")

    # —— 估值：倍数与持股是**可调 driver**，必须从传入的 cfg 现读，不能写死 ——
    op_value = g("swap.operating_value")

    # —— 重卡 ——
    heavy_life = g("ops.heavy_battery_life")
    heavy_stock = veh_heavy_cfg.get("stock_wan")

    he = getattr(snap.swap_business, "heavy_economics", None)
    n1 = getattr(he, "n1", None)
    n2 = getattr(he, "n2", None)

    def _tco(row, prefix: str) -> dict:
        if not row:
            return {k: None for k in (
                f"tco_swap_wan{prefix}", f"tco_swap_kwh{prefix}",
                f"tco_lng_wan{prefix}", f"tco_lng_kwh{prefix}",
                f"tco_diesel_wan{prefix}", f"tco_diesel_kwh{prefix}")}
        return {
            f"tco_swap_wan{prefix}": _r(row.swap_wan, 1),
            f"tco_swap_kwh{prefix}": _r(row.swap_kwh, 3),
            f"tco_lng_wan{prefix}": _r(row.lng_wan, 1),
            f"tco_lng_kwh{prefix}": _r(row.lng_kwh, 3),
            f"tco_diesel_wan{prefix}": _r(row.diesel_wan, 1),
            f"tco_diesel_kwh{prefix}": _r(row.diesel_kwh, 3),
        }

    # REIT 回笼倍数：把已算好的快照喂进去，避免 capital_cycle 内部再建一次模型
    reit_mult = None
    try:
        from capital_cycle import reit_recycle_multiple
        reit_mult = reit_recycle_multiple(
            cfg, snap.scale, snap.capex, snap.swap_business, snap.ledger
        )
    except Exception:  # noqa: BLE001 —— 结论区不能因为一个派生数失败就整块空白
        reit_mult = None

    vals = {
        "target_year": meta.get("target_year"),
        "veh_ops": veh_ops,
        "veh_mkt": veh_mkt,
        "share": _pct(raw_ops, mkt),
        "repl_gwh": _r(repl_gwh, 1),
        "repl_share_pct": _pct(repl_gwh, shipments, 1),
        "dist_cash": _r(g("swap.dist_cash"), 1),
        "ebitda": _r(g("swap.ebitda"), 1),
        "mult": _r(fin.get("swap_ev_ebitda"), 1),
        "own_pct": _pct(fin.get("construction_ownership"), 1.0, 1),
        "mktcap": _r(op_value / 10000, 3) if op_value is not None else None,
        "energy": _r(g("ops.annual_energy"), 1),
        "elec_share": _r(g("mk.share_elec_latest"), 3),
        "batt_station": _r(g("ops.battery_station"), 0),
        "storage_share": _r(g("mk.share_storage_2025"), 3),
        "stations": _r(g("scale.stations_total"), 0),
        "peak_call": _r(g("capex.peak_call"), 1),
        "reit_mult": reit_mult,
        "veh_heavy": _r(g("ops.veh_heavy"), 1),
        "heavy_stock_wan": _r(heavy_stock, 0),
        "heavy_pen_pct": _pct(g("ops.veh_heavy"), heavy_stock),
        "heavy_fleet_gwh": _r(g("ops.heavy_vehicle_gwh"), 1),
        "heavy_station_gwh": _r(g("ops.heavy_station_gwh"), 1),
        "heavy_repl_gwh": _r(g("mfg.repl_gwh_heavy"), 1),
        "heavy_life_yrs": _r(heavy_life, 2),
        "heavy_repl_cycle": _r(veh_heavy_cfg.get("replacement_cycle_years"), 1),
        "price_swap_kwh": _r(g("ops.heavy_user_price"), 3),
        "energy_unit_kwh": _r(
            float((cfg.get("swap_business") or {}).get("valley_power_price_rmb_kwh", 0.0))
            + float((cfg.get("swap_business") or {}).get("grid_spread_rmb_kwh", 0.0)),
            3,
        ),
    }
    vals.update(_tco(n1, ""))       # N1 持有期 = 模型算出的重卡电池寿命
    vals.update(_tco(n2, "_9"))     # N2 持有期 = 重卡更新周期（9 年）
    return vals

# -*- coding: utf-8 -*-
"""月度跟踪：把实测读数变成会自己响的中检点。

【2026-09-14】为什么是这个形态
──────────────────────────────────────────────────────────────────────
`data/电车人新能源重卡月度数据_*.xlsx` 的身份不是**预测输入**，是**跟踪工具**——
商用车是生产资料，销量季节性极强（春节在 1 月或 2 月、年末抢装），
**月度值不构成趋势证据，只用来验证判断**。

所以这里不做任何预测，只做三件事：
  ① **抽取**：从 xlsx 取年度/累计读数，落成 `audit/tracking_hdt.json`（纯 stdlib 可读）；
  ② **比对**：拿最新实测去比模型的对应假设；
  ③ **报警**：差距越过阈值就在 `build.py` 里喊出来。

**为什么抽成 JSON**：主链（`src/` 除本文件外）坚持零第三方依赖（Pyodide 要跑同一套 Python），
xlsx 解析进不去。抽成 JSON 之后，主链只读 JSON，跟踪数据也就进了版本管理、可比可回溯。

【抓取为什么不写在这里】
第一商用车网的月度数据经新浪财经转载后可稳定抓取（实测：2026-06 提取值与本地表逐项一致），
但抓取是**联网取数**动作，属于 agent 的职责，不是模型的职责——
写成脚本里的 requests 既会被网络策略挡，也会在源站改版时静默取错。
**做法：每月由 agent 取数 → `tracker.py append` 校验落表 → `build.py` 自动比对。**
待取月份由 `tracker.py status` 列出，见 `交接.md` §跟踪。
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "audit" / "tracking_hdt.json"
XLSX_CANDIDATES = [
    ROOT / "../../../../data/电车人新能源重卡月度数据_2024-2026_口径更新.xlsx",
    ROOT / "../../../../data/电车人新能源重卡月度数据_2024-2026.xlsx",
]

# 中检点阈值：**只对年度/累计读数生效，不看单月**（季节性）
WATCH = {
    "swap_share_gap": 0.10,   # 实测换电占纯电 与 模型兑现年假设 的差，越过即报警
    "nev_anchor_gap": 0.03,   # 实测年度渗透 与 拟合锚 的差
}


def _find_xlsx() -> pathlib.Path | None:
    for c in XLSX_CANDIDATES:
        if c.exists():
            return c.resolve()
    return None


def extract() -> dict:
    """从 xlsx 抽取年度/累计读数 → JSON。需要 openpyxl（只在本文件用）。"""
    import openpyxl
    src = _find_xlsx()
    if src is None:
        raise SystemExit("找不到月度数据表；候选路径见 XLSX_CANDIDATES")
    wb = openpyxl.load_workbook(src, data_only=True)
    ws = wb["Part3_商用车细分"]
    hdr = [c.value for c in ws[1]]
    def col(name):
        for i, h in enumerate(hdr):
            if h and name in str(h):
                return i
        return None
    ci = {k: col(k) for k in ("NEV重卡累计渗透率%", "换电累计占比%(纯电累计)",
                              "NEV重卡渗透率%", "换电占比%(纯电中)")}
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r[0]:
            continue
        def g(k):
            i = ci[k]
            v = r[i] if (i is not None and i < len(r)) else None
            return None if v in (None, "待补", "-") else float(v) / 100.0
        rows.append({"ym": str(r[0]),
                     "nev_pen_cum": g("NEV重卡累计渗透率%"),
                     "swap_share_cum": g("换电累计占比%(纯电累计)"),
                     "nev_pen_m": g("NEV重卡渗透率%"),
                     "swap_share_m": g("换电占比%(纯电中)")})
    def latest(field):
        for row in reversed(rows):
            if row[field] is not None:
                return row["ym"], row[field]
        return None, None
    ym_p, pen = latest("nev_pen_cum")
    ym_s, shr = latest("swap_share_cum")
    data = {
        "source": "src.dcr_hdt_monthly",
        "caliber": "第一商用车网上险量（不含出口/军车）；**累计口径，不看单月**（季节性）",
        "file": src.name,
        "latest_nev_pen_cum": {"ym": ym_p, "value": pen},
        "latest_swap_share_cum": {"ym": ym_s, "value": shr},
        "series": [r for r in rows if r["nev_pen_cum"] is not None or r["swap_share_cum"] is not None],
        "missing": [r["ym"] for r in rows if all(r[k] is None for k in
                    ("nev_pen_cum", "swap_share_cum", "nev_pen_m", "swap_share_m"))],
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


def load() -> dict | None:
    if not OUT.exists():
        return None
    return json.loads(OUT.read_text(encoding="utf-8"))


def check(config: dict) -> list[str]:
    """拿实测比模型假设。返回报警行（空＝没越阈值）。**主链只调这个，纯 stdlib。**"""
    d = load()
    if not d:
        return []
    warn = []
    hv = config["vehicles"]["heavy"]
    # ① 换电占纯电：模型兑现年加权 vs 最新实测累计
    scenes = hv.get("scenes", [])
    tot_w = sum(s.get("weight", 0.0) for s in scenes) or 1.0
    model_share = sum(s.get("weight", 0.0) * s.get("swap_penetration", 0.0) for s in scenes) / tot_w
    obs = d["latest_swap_share_cum"]["value"]
    if obs is not None and abs(model_share - obs) > WATCH["swap_share_gap"]:
        warn.append(
            f"【换电占纯电】模型兑现年加权 {model_share:.1%}，最新实测（{d['latest_swap_share_cum']['ym']}"
            f" 累计）{obs:.1%}，差 {model_share - obs:+.1%}。"
            f"这不是 bug，是一个**反转预期**——推翻条件写在 base.toml 的声明段，"
            f"机制与三条反驳见 topics/竞争格局「换电占电动为什么在跌」")
    # ② 年度渗透：拟合锚 vs 最新实测累计
    anchor = hv.get("nev_anchor_rate")
    obs_p = d["latest_nev_pen_cum"]["value"]
    if anchor and obs_p is not None and obs_p - anchor > WATCH["nev_anchor_gap"]:
        warn.append(
            f"【重卡电动化】logistic 拟合锚 {anchor:.1%}（{hv.get('nev_anchor_year')} 年度），"
            f"最新实测 {obs_p:.1%}（{d['latest_nev_pen_cum']['ym']} 累计）已高出 "
            f"{obs_p - anchor:+.1%}——**年度数据满一年后应重标曲线**（改锚即可，k/t0 自动重算）")
    return warn


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "extract":
        d = extract()
        print(f"✓ 已抽取 → {OUT.relative_to(ROOT)}")
        print(f"  最新年度渗透 {d['latest_nev_pen_cum']['value']:.1%}"
              f"（{d['latest_nev_pen_cum']['ym']}）")
        print(f"  最新换电占纯电 {d['latest_swap_share_cum']['value']:.1%}"
              f"（{d['latest_swap_share_cum']['ym']}）")
        print(f"  待取月份 {len(d['missing'])} 个：{'、'.join(d['missing'])}")
        return 0
    d = load()
    if not d:
        print("还没抽取过，先跑：python src/tracker.py extract")
        return 1
    print("跟踪读数（%s）" % d["caliber"])
    print(f"  年度渗透 {d['latest_nev_pen_cum']['value']:.1%}（{d['latest_nev_pen_cum']['ym']}）")
    print(f"  换电占纯电 {d['latest_swap_share_cum']['value']:.1%}（{d['latest_swap_share_cum']['ym']}）")
    print(f"  **待取月份**：{'、'.join(d['missing']) or '无'}")
    from config_loader import load_config
    for w in check(load_config()):
        print("  ⚠ " + w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

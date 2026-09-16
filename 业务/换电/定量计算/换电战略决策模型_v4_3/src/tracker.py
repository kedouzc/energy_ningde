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
    "bev_share_gap": 0.10,    # 实测乘用车 BEV 占新能源 与 模型私家车纯电占比 的差
    "stale_months": 3,        # 底稿最新月距今超过这么多个月 → 数据过期报警
}


def _find_xlsx() -> pathlib.Path | None:
    for c in XLSX_CANDIDATES:
        if c.exists():
            return c.resolve()
    return None


def _num(v, pct=False):
    """把单元格变成数；"待补"/"-"/空 → None。pct=True 时按百分数转小数。"""
    if v in (None, "", "待补", "-", "—"):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f / 100.0 if pct else f


def _sheet_rows(wb, sheet: str, want: dict[str, tuple[str, bool]]) -> list[dict]:
    """按列名子串取列。want = {输出键: (列名子串, 是否百分数)}。列名对不上就整列 None——
    **不许猜列**：底稿改了列名，读数变 None 会在新鲜度/缺口报警里显形，比默认取错列安全。"""
    if sheet not in wb.sheetnames:
        return []
    ws = wb[sheet]
    hdr = [c.value for c in ws[1]]
    idx = {}
    for key, (name, _pct) in want.items():
        idx[key] = next((i for i, h in enumerate(hdr) if h and name in str(h)), None)
    out = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        if not r or not r[0]:
            continue
        row = {"ym": str(r[0])}
        for key, (_name, pct) in want.items():
            i = idx[key]
            row[key] = _num(r[i], pct) if (i is not None and i < len(r)) else None
        out.append(row)
    return out


def _latest(rows: list[dict], field: str) -> dict:
    for row in reversed(rows):
        if row.get(field) is not None:
            return {"ym": row["ym"], "value": row[field]}
    return {"ym": None, "value": None}


def extract() -> dict:
    """从 xlsx 抽取整条漏斗的年度/累计读数 → JSON。需要 openpyxl（只在本文件用）。

    【2026-09-15 扩到漏斗上层】原来只抽重卡那一层。
    但模型的车辆规模是**一条漏斗**：总量 → 分车型 → 电动化 → 换电占电动 → CATL 份额，
    **只跟最下面一层，等于只在最后一道关口设岗**——上游任何一层偏了，都要等它传导到重卡换电
    才看得见，而那时已经晚了一整年。底稿（用户维护）里五层都有，这里五层都抽。
    """
    import openpyxl
    src = _find_xlsx()
    if src is None:
        raise SystemExit("找不到月度数据表；候选路径见 XLSX_CANDIDATES")
    wb = openpyxl.load_workbook(src, data_only=True)

    # ① 总量层（中汽协批发口径）
    total = _sheet_rows(wb, "Part1_中汽协总量", {
        "nev_wan": ("新能源总量销量(万辆)", False),
        "pen_m": ("月度渗透率(%)", True),
        "nev_cum_wan": ("1-X月累计(万辆)", False),
    })
    # ② 乘用车层（乘联会）
    pas = _sheet_rows(wb, "Part2_乘联会乘用车", {
        "sales_wan": ("乘用车销量(万辆)", False),
        "bev_wan": ("BEV销量(万)", False),
        "bev_share": ("BEV占比(%)", True),
        "pen": ("渗透率(%)", True),
    })
    # ③ 商用车层（第一商用车网）——重卡三层 ＋ 城配口径的轻卡/物流车
    com = _sheet_rows(wb, "Part3_商用车细分", {
        "nev_pen_cum": ("NEV重卡累计渗透率%", True),
        "swap_share_cum": ("换电累计占比%(纯电累计)", True),
        "charge_share_cum": ("充电累计占比%(纯电累计)", True),
        "nev_pen_m": ("NEV重卡渗透率%", True),
        "swap_share_m": ("换电占比%(纯电中)", True),
        "bev_in_nev_cum": ("纯电累计占比%(新能累计)", True),
        "light_truck_wan": ("轻卡(万)", False),
        "logistics_wan": ("物流车(万)", False),
    })
    # ④ 电池份额层（中国汽车动力电池产业创新联盟）——CATL 份额的外部对照
    bat = _sheet_rows(wb, "Part4_动力电池", {
        "catl_passenger": ("乘用车-宁德时代%", True),
        "catl_commercial": ("商用车-宁德时代%", True),
        "install_gwh": ("装车量(GWh)", False),
    })

    # 乘用车 BEV 年化销量：按最新自然年的已有月份年化。
    # **这是私家车池分母唯一能被外部证伪的读数**——模型的"年净增"再大也不可能超过当年销量。
    bev_by_year: dict[str, list] = {}
    for r in pas:
        if r.get("bev_wan") is None:
            continue
        y = str(r["ym"])[:4]
        bev_by_year.setdefault(y, [0.0, 0])
        bev_by_year[y][0] += r["bev_wan"]
        bev_by_year[y][1] += 1
    bev_annual = None
    if bev_by_year:
        y = max(bev_by_year)
        tot, n = bev_by_year[y]
        bev_annual = {"ym": y, "value": tot / n * 12 if n else None, "months": n}

    layers = {
        "总量": {"sheet": "Part1_中汽协总量", "caliber": "中汽协批发口径",
                 "latest_nev_wan": _latest(total, "nev_wan"),
                 "latest_pen": _latest(total, "pen_m")},
        "乘用车": {"sheet": "Part2_乘联会乘用车", "caliber": "乘联会零售/批发口径",
                   "latest_sales_wan": _latest(pas, "sales_wan"),
                   "latest_bev_share": _latest(pas, "bev_share"),
                   "latest_pen": _latest(pas, "pen"),
                   "bev_annualized_wan": bev_annual},
        "重卡": {"sheet": "Part3_商用车细分", "caliber": "第一商用车网上险量（不含出口/军车）",
                 "latest_nev_pen_cum": _latest(com, "nev_pen_cum"),
                 "latest_swap_share_cum": _latest(com, "swap_share_cum"),
                 "latest_charge_share_cum": _latest(com, "charge_share_cum"),
                 "latest_bev_in_nev_cum": _latest(com, "bev_in_nev_cum")},
        "城配": {"sheet": "Part3_商用车细分", "caliber": "第一商用车网；轻卡与物流车月度量",
                 "latest_light_truck_wan": _latest(com, "light_truck_wan"),
                 "latest_logistics_wan": _latest(com, "logistics_wan")},
        "电池份额": {"sheet": "Part4_动力电池", "caliber": "动力电池创新联盟装车量口径",
                     "latest_catl_passenger": _latest(bat, "catl_passenger"),
                     "latest_catl_commercial": _latest(bat, "catl_commercial")},
    }
    all_ym = sorted({r["ym"] for r in (total + pas + com + bat) if r.get("ym")})
    data = {
        "source": "src.dcr_hdt_monthly",
        "file": src.name,
        "caliber": "**累计口径，不看单月**（商用车是生产资料，季节性极强）；各层口径见 layers[*].caliber",
        "latest_ym": all_ym[-1] if all_ym else None,
        "layers": layers,
        # 兼容旧键：下游只认这两个，保留以免一次改两处
        "latest_nev_pen_cum": layers["重卡"]["latest_nev_pen_cum"],
        "latest_swap_share_cum": layers["重卡"]["latest_swap_share_cum"],
        "series": [r for r in com if r["nev_pen_cum"] is not None or r["swap_share_cum"] is not None],
        "missing": [r["ym"] for r in com if all(r.get(k) is None for k in
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
    """拿实测比模型假设，逐层比。返回报警行（空＝没越阈值）。**主链只调这个，纯 stdlib。**

    【2026-09-15 扩到漏斗上层】车辆规模是一条漏斗：
    总量 → 分车型 → 电动化 → **纯电占新能源** → 换电占纯电 → CATL 份额。
    原来只比最下面两层，等于只在最后一道关口设岗；上游偏了要等它传导下来才看得见。
    """
    d = load()
    if not d:
        return []
    warn: list[str] = []
    L = d.get("layers") or {}

    def val(layer: str, key: str):
        node = (L.get(layer) or {}).get(key) or {}
        return node.get("ym"), node.get("value")

    # ── ① 重卡·电动化：拟合锚 vs 最新实测累计
    hv = config["vehicles"]["heavy"]
    anchor = hv.get("nev_anchor_rate")
    ym_p, obs_p = val("重卡", "latest_nev_pen_cum")
    if anchor and obs_p is not None and obs_p - anchor > WATCH["nev_anchor_gap"]:
        warn.append(
            f"【重卡·电动化】logistic 拟合锚 {anchor:.1%}（{hv.get('nev_anchor_year')} 年度），"
            f"最新实测 {obs_p:.1%}（{ym_p} 累计）已高出 {obs_p - anchor:+.1%}"
            f"——**年度数据满一年后应重标曲线**（改锚即可，k/t0 自动重算）")

    # ── ② 重卡·换电占纯电：模型兑现年加权 vs 最新实测累计
    scenes = hv.get("scenes", [])
    tot_w = sum(sc.get("weight", 0.0) for sc in scenes) or 1.0
    model_share = sum(sc.get("weight", 0.0) * sc.get("swap_penetration", 0.0) for sc in scenes) / tot_w
    ym_s, obs_s = val("重卡", "latest_swap_share_cum")
    if obs_s is not None and abs(model_share - obs_s) > WATCH["swap_share_gap"]:
        warn.append(
            f"【重卡·换电占纯电】模型兑现年加权 {model_share:.1%}，最新实测（{ym_s} 累计）"
            f"{obs_s:.1%}，差 {model_share - obs_s:+.1%}。这不是 bug，是一个**反转预期**"
            f"——推翻条件写在 base.toml 的声明段，机制与三条反驳见 topics/竞争格局"
            f"「换电占电动为什么在跌」")

    # ── ③ 私家车池的分母 vs 实测乘用车 BEV 销量
    #
    # 【2026-09-15 撤回一条误报】上一版拿模型 `pure_electric_share=1.0` 去比
    # 乘联会「BEV 占新能源 64.2%」，报了"模型把私家车池放大 1.56 倍"。**那是误报。**
    # 查用户的素材《素材-电池装机量》§4.B 后确认：私家车池的分母**本来就是纯电口径**——
    # 2025 年基数取公安部**纯电动保有量 3022 万**，原文明确写着"**不取 IEA 含插混的 4400 万**"。
    # 分母已经排除插混，`pure_electric_share=1.0` 因此是对的，**错的是我拿来比的那个数**。
    #
    # 换成一条真正能证伪的：**年净增不可能超过当年销量。**
    pri = config["vehicles"]["private"]
    adds = pri.get("annual_net_additions_wan") or []
    node = (L.get("乘用车") or {}).get("bev_annualized_wan") or {}
    obs_bev, ym_bev, months = node.get("value"), node.get("ym"), node.get("months")
    if adds and obs_bev:
        first = float(adds[0])
        if first > obs_bev * 1.6:
            warn.append(
                f"【私家车池·分母】模型首年净增 {first:,.0f} 万辆，"
                f"而实测乘用车 BEV 年化销量 {obs_bev:,.0f} 万辆"
                f"（{ym_bev} 年前 {months} 个月年化）——**高出 {first/obs_bev:.2f} 倍**。"
                f"净增是存量增量、销量是流量，**净增不可能超过销量**，所以这两个数之间"
                f"必须有一个能说出口的增长路径；末年 {float(adds[-1]):,.0f} 万还要再翻一倍。"
                f"口径本身没错（分母是公安部纯电 3022 万口径，已排除插混），"
                f"要核的是**这条增长路径的依据**")

    # ── ④ 底稿新鲜度：竞争性变量必须带复核周期，过期即响
    latest = d.get("latest_ym")
    if latest:
        try:
            import datetime as _dt
            y, m = (int(x) for x in str(latest).split("-")[:2])
            now = _dt.date.today()
            gap = (now.year - y) * 12 + (now.month - m)
            if gap > WATCH["stale_months"]:
                warn.append(
                    f"【底稿过期】月度数据最新到 {latest}，距今 {gap} 个月"
                    f"（阈值 {WATCH['stale_months']}）——**上面几条比对都是拿旧数在比**。"
                    f"更新 data/ 下的月度底稿后跑 `python src/tracker.py extract`")
        except Exception:
            pass
    return warn


def readings() -> list[str]:
    """漏斗五层的最新读数（不报警，只报数）。给沙盘 ② 块和命令行看。"""
    d = load()
    if not d:
        return []
    out = []
    for layer, items in (d.get("layers") or {}).items():
        parts = []
        for k, v in items.items():
            if not isinstance(v, dict) or v.get("value") is None:
                continue
            name = k.replace("latest_", "")
            x = v["value"]
            parts.append(f"{name} {x:.1%}" if x <= 1.5 else f"{name} {x:,.1f}")
        if parts:
            out.append(f"{layer}（{items.get('caliber','')}）：" + "；".join(parts))
    return out


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
    print(f"  底稿最新月份：{d.get('latest_ym')}")
    for line in readings():
        print("  · " + line)
    print(f"  **待取月份**：{'、'.join(d['missing']) or '无'}")
    from config_loader import load_config
    for w in check(load_config()):
        print("  ⚠ " + w)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

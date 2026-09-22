# -*- coding: utf-8 -*-
"""月度跟踪：把实测读数变成会自己响的中检点。

【为什么单月和累计都要跟（2026-09-16 用户定调）】
──────────────────────────────────────────────────────────────────────
跟踪是为投资调仓服务的，不是为写年报服务的：
  · **单月看边际**——趋势反转、竞争失守、价格收敛都最先出现在单月，
    等年度数据确认再动仓往往已经晚了一个季度；单月报警＝调仓信号；
  · **累计/年度看趋势锚**——商用车是生产资料，季节性极强（春节错位、年末抢装），
    单月不直接用来重标模型曲线；累计口径越线才重标锚点。
两类读数本文件**都抽取、都比对**（watch 卡用 observed 字段名区分：`*_m`＝单月、
`*_cum`／年化＝累计趋势），阈值分别设定：单月放宽以容纳季节波动。

所以这里不做任何预测，只做三件事：
  ① **抽取**：从 xlsx 取五层漏斗（总量/乘用车/重卡/城配/电池份额）的逐月读数，
     落成 `audit/tracking_hdt.json`（纯 stdlib 可读，含 latest＋series）；
  ② **比对**：拿最新实测去比模型的对应假设（`[[watch]]` 卡片驱动）；
  ③ **报警**：差距越过阈值就在 `build.py` 里喊出来。

**为什么抽成 JSON**：主链（`src/` 除本文件外）坚持零第三方依赖（Pyodide 要跑同一套 Python），
xlsx 解析进不去。抽成 JSON 之后，主链只读 JSON，跟踪数据也就进了版本管理、可比可回溯。

【xlsx 谁来维护（2026-09-16 起的新链路）】
2026-07 起（含）不由人工维护：agent 按 xlsx 内既有数据源（Part3 内嵌超链接／各 Part
口径列注明的发布方）联网取数，经 `src/monthly_update.py fill` 校验后写入底稿新行
（只许填空单元格、必须带信源），再跑本文件 `extract` 刷新 JSON。
历史月份（≤2026-06）为人工维护，保持原样。抓取不写在本文件里：联网取数是 agent 的
职责，写成 requests 既会被网络策略挡，也会在源站改版时静默取错。
待取月份由 `python src/monthly_update.py status` 列出，见 `交接.md` §跟踪。
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

# 中检点默认阈值（卡片自带 threshold，这里只留数据新鲜度等程序侧常量）
WATCH = {
    "stale_months": 3,        # 底稿最新月距今超过这么多个月 → 数据过期报警
}

# ── xlsx 四层底稿的列映射（唯一一家）─────────────────────────────────────────
# extract（读）与 monthly_update（写）都引用本表：列名改了只需改这里一处。
# {输出键: (表头子串, 是否百分数)}。**不许猜列**：表头对不上 → 整列 None，
# 会在新鲜度/缺列报警里显形，比默认取错列安全。
# 注意 Part3 有两个同名「NEV重卡(万辆)」列（col1/col4，历史值一致），子串取首个。
PART_COLUMNS: dict[str, dict[str, tuple[str, bool]]] = {
    "Part1_中汽协总量": {
        "nev_wan": ("新能源总量销量(万辆)", False),
        "nev_yoy": ("同比(%)", True),
        "pen_m": ("月度渗透率(%)", True),
        "nev_cum_wan": ("1-X月累计(万辆)", False),
        "nev_cum_yoy": ("累计同比(%)", True),
    },
    "Part2_乘联会乘用车": {
        "sales_wan": ("乘用车销量(万辆)", False),
        "sales_yoy": ("同比(%)", True),
        "pen": ("渗透率(%)", True),
        "sales_cum_wan": ("1-X月累计(万)", False),
        "bev_wan": ("BEV销量(万)", False),
        "bev_share": ("BEV占比(%)", True),
        "phev_wan": ("PHEV销量(万)", False),
        "reev_wan": ("REEV销量(万)", False),
    },
    "Part3_商用车细分": {
        "nev_wan": ("NEV重卡(万辆)", False),
        "nev_yoy": ("NEV重卡同比%", True),
        "nev_pen_m": ("NEV重卡渗透率%", True),
        "nev_cum_wan": ("NEV重卡累计(万)", False),
        "nev_cum_yoy": ("NEV重卡累计同比%", True),
        "nev_pen_cum": ("NEV重卡累计渗透率%", True),
        "gas_wan": ("燃气重卡(万辆)", False),
        "diesel_wan": ("柴油/汽油重卡(万辆)", False),
        "bev_truck_wan": ("纯电重卡(万辆)", False),
        "bev_in_nev_m": ("纯电占比%(新能重卡)", True),
        "swap_wan": ("换电重卡(万辆)", False),
        "swap_share_m": ("换电占比%(纯电中)", True),
        "charge_wan": ("充电重卡(万辆)", False),
        "charge_share_m": ("充电占比%(纯电中)", True),
        "bev_cum_wan": ("纯电累计(万)", False),
        "bev_in_nev_cum": ("纯电累计占比%(新能累计)", True),
        "swap_cum_wan": ("换电累计(万)", False),
        "swap_share_cum": ("换电累计占比%(纯电累计)", True),
        "charge_cum_wan": ("充电累计(万)", False),
        "charge_share_cum": ("充电累计占比%(纯电累计)", True),
        "logistics_wan": ("物流车(万)", False),
        "logistics_yoy": ("物流同比%", True),
        "logistics_cum_wan": ("物流累计(万)", False),
        "logistics_cum_yoy": ("物流累计同比%", True),
        "light_truck_wan": ("轻卡(万)", False),
        "light_truck_yoy": ("轻卡同比%", True),
        "light_truck_cum_wan": ("轻卡累计(万)", False),
    },
    "Part4_动力电池": {
        "install_gwh": ("装车量(GWh)", False),
        "install_yoy": ("同比(%)", True),
        "install_cum_gwh": ("1-X月累计(GWh)", False),
        "install_cum_yoy": ("累计同比%", True),
        "lfp_share": ("磷酸铁锂占比%", True),
        "catl_passenger": ("乘用车-宁德时代%", True),
        "catl_commercial": ("商用车-宁德时代%", True),
        "eve_commercial": ("商用车-亿纬%", True),
    },
}

# Part3 五个「来源·文章」列：填数块 → (列序号0基, 键名)。agent fill 时写文章标题＋超链接。
PART3_SOURCE_COLS = {
    "nev": 3, "gas": 18, "diesel": 19, "swap": 32, "charge": 33,
}
# 各数据块依赖的来源块（填了这些字段就必须给对应文章链接）
PART3_BLOCK_SOURCES = {
    "nev": ("nev_wan", "nev_yoy", "nev_pen_m", "nev_cum_wan", "nev_cum_yoy", "nev_pen_cum",
            "gas_wan", "diesel_wan", "bev_truck_wan", "bev_in_nev_m"),
    "gas": ("gas_wan",),
    "swap": ("swap_wan", "swap_share_m", "swap_cum_wan", "swap_share_cum"),
    "charge": ("charge_wan", "charge_share_m", "charge_cum_wan", "charge_share_cum"),
}
# 无专用来源列的 Part 表：信源超链接挂在「年月」单元格（列0），可见可点、不动既有列语义
MONTH_CELL_SOURCE_SHEETS = ("Part1_中汽协总量", "Part2_乘联会乘用车", "Part4_动力电池")

# ── 外部月度数据「多源注册表」（2026-09-16）──────────────────────────────────
# 一切影响规模与判断的外部月度数据，采集方式可以不同（人工 xlsx 抽取／agent 直更），
# 但**程序消费层只有一种形态**：audit/tracking_<源>.json（layers＋latest＋series）。
# [[watch]] 卡的 observed 与 [[event]] 的 track 都只引用这里登记的源——
# 加一个数据源＝加一个 JSON＋在此登记一行，主链/浏览器端同源只读。
TRACK_SOURCES = {
    "hdt": "tracking_hdt.json",            # 重卡漏斗五层：xlsx 人工底稿 → extract 抽取
    "methanol": "tracking_methanol.json",  # 绿醇/灰醇比价：agent 月更（methanol-append）
}

# track 声明支持的比较算子：达标判定只用月度实测值，不做任何外推
_TRACK_OPS = {
    "<=": lambda a, b: a <= b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    ">": lambda a, b: a > b,
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


def _ytd_annualized_cum(rows: list[dict], field: str) -> dict:
    """按**累计列**年化：最新非空累计值 ÷ 当年已过月数 × 12。
    累计口径自动抹平单月季节波动（春节/抢装），是与年度模型值同口径的流量估计。"""
    latest = _latest(rows, field)
    if latest["value"] is None:
        return {"ym": None, "value": None, "months": None}
    try:
        m = int(str(latest["ym"])[5:7])
    except (ValueError, IndexError):
        return {"ym": None, "value": None, "months": None}
    if m <= 0:
        return {"ym": None, "value": None, "months": None}
    return {"ym": f'{latest["ym"]}（1–{m}月年化）', "value": latest["value"] / m * 12.0,
            "months": m}


def _ytd_annualized_monthly(rows: list[dict], field: str) -> dict:
    """按**月度列**加总年化（无累计列时用）：当年已有月份之和 ÷ 月数 × 12。"""
    by_year: dict[str, list[float]] = {}
    for r in rows:
        if r.get(field) is None:
            continue
        by_year.setdefault(str(r["ym"])[:4], []).append(float(r[field]))
    if not by_year:
        return {"ym": None, "value": None, "months": None}
    y = max(by_year)
    vals = by_year[y]
    return {"ym": f"{y}年（1–{len(vals)}月年化）", "value": sum(vals) / len(vals) * 12.0,
            "months": len(vals)}


def extract() -> dict:
    """从 xlsx 抽取五层漏斗的**逐月＋累计**读数 → JSON。需要 openpyxl（只在本文件用）。

    【漏斗上层】模型的车辆规模是一条链：
    总量 → 分车型 → 电动化 → 换电占电动 → CATL 份额。
    **只跟最下面一层，等于只在最后一道关口设岗**——上游偏了要等传导到重卡换电
    才看得见，那时已晚了一整年。底稿四层都有，这里四层都抽。
    【series】四层行按 ym 合并成统一逐月序列，键加前缀 t_/p_/c_/b_ 防跨层撞名，
    供月度仪表盘与未来的 track 事件消费；layers.* 给 watch 卡的最新值比对。
    """
    import openpyxl
    src = _find_xlsx()
    if src is None:
        raise SystemExit("找不到月度数据表；候选路径见 XLSX_CANDIDATES")
    wb = openpyxl.load_workbook(src, data_only=True)

    # ① 总量层（中汽协国内口径，不含出口）② 乘用车层（乘联会零售口径）
    # ③ 商用车层（第一商用车网＋电车资源）④ 电池份额层（动力电池创新联盟）
    total = _sheet_rows(wb, "Part1_中汽协总量", PART_COLUMNS["Part1_中汽协总量"])
    pas = _sheet_rows(wb, "Part2_乘联会乘用车", PART_COLUMNS["Part2_乘联会乘用车"])
    com = _sheet_rows(wb, "Part3_商用车细分", PART_COLUMNS["Part3_商用车细分"])
    bat = _sheet_rows(wb, "Part4_动力电池", PART_COLUMNS["Part4_动力电池"])

    layers = {
        "总量": {"sheet": "Part1_中汽协总量",
                 "caliber": "中汽协国内口径（NEV 销量/渗透率不含出口，出口在底稿单列；"
                            "2024–2025 行沿用电车人底稿原口径）",
                 "latest_nev_wan": _latest(total, "nev_wan"),
                 "latest_pen": _latest(total, "pen_m"),
                 "latest_nev_cum_wan": _latest(total, "nev_cum_wan"),
                 "nev_annualized_wan": _ytd_annualized_cum(total, "nev_cum_wan")},
        "乘用车": {"sheet": "Part2_乘联会乘用车", "caliber": "乘联会零售口径（BEV 列为零售纯电）",
                   "latest_sales_wan": _latest(pas, "sales_wan"),
                   "latest_bev_wan": _latest(pas, "bev_wan"),
                   "latest_bev_share": _latest(pas, "bev_share"),
                   "latest_pen": _latest(pas, "pen"),
                   "bev_annualized_wan": _ytd_annualized_monthly(pas, "bev_wan")},
        "重卡": {"sheet": "Part3_商用车细分", "caliber": "第一商用车网上险量（不含出口/军车）",
                 "latest_nev_wan": _latest(com, "nev_wan"),
                 "latest_nev_pen_m": _latest(com, "nev_pen_m"),
                 "latest_nev_pen_cum": _latest(com, "nev_pen_cum"),
                 "latest_nev_cum_wan": _latest(com, "nev_cum_wan"),
                 "latest_swap_wan": _latest(com, "swap_wan"),
                 "latest_swap_share_m": _latest(com, "swap_share_m"),
                 "latest_swap_share_cum": _latest(com, "swap_share_cum"),
                 "latest_swap_cum_wan": _latest(com, "swap_cum_wan"),
                 "latest_charge_share_cum": _latest(com, "charge_share_cum"),
                 "latest_bev_in_nev_cum": _latest(com, "bev_in_nev_cum")},
        "城配": {"sheet": "Part3_商用车细分",
                 "caliber": "物流车＝电车资源保险上险（NEV 七类，不含重卡/皮卡/客车，含中卡）；轻卡为其子集口径",
                 "latest_logistics_wan": _latest(com, "logistics_wan"),
                 "latest_logistics_cum_wan": _latest(com, "logistics_cum_wan"),
                 "logistics_annualized_wan": _ytd_annualized_cum(com, "logistics_cum_wan"),
                 "latest_light_truck_wan": _latest(com, "light_truck_wan")},
        "电池份额": {"sheet": "Part4_动力电池", "caliber": "动力电池创新联盟装车量口径",
                     "latest_install_gwh": _latest(bat, "install_gwh"),
                     "latest_install_cum_gwh": _latest(bat, "install_cum_gwh"),
                     "install_annualized_gwh": _ytd_annualized_cum(bat, "install_cum_gwh"),
                     "latest_catl_passenger": _latest(bat, "catl_passenger"),
                     "latest_catl_commercial": _latest(bat, "catl_commercial")},
    }

    # 四层合并成统一逐月序列（前缀防撞名）；只保留至少有一个实测值的月份
    prefix_sheet = (("t", "Part1_中汽协总量"), ("p", "Part2_乘联会乘用车"),
                    ("c", "Part3_商用车细分"), ("b", "Part4_动力电池"))
    merged: dict[str, dict] = {}
    for prefix, rows in (("t", total), ("p", pas), ("c", com), ("b", bat)):
        for r in rows:
            d = merged.setdefault(str(r["ym"]), {"ym": str(r["ym"])})
            for k, v in r.items():
                if k != "ym":
                    d[f"{prefix}_{k}"] = v
    data_keys = [f"{prefix}_{k}" for prefix, sn in prefix_sheet for k in PART_COLUMNS[sn]]
    series = sorted((r for r in merged.values()
                     if any(r.get(k) is not None for k in data_keys)),
                    key=lambda r: r["ym"])

    all_ym = sorted(merged)
    # 缺数月份：重卡层四个核心读数全空（含已占位但未取数的行）
    miss_keys = ("c_nev_pen_cum", "c_swap_share_cum", "c_nev_pen_m", "c_swap_share_m")
    missing = [r["ym"] for r in series
               if all(r.get(k) is None for k in miss_keys)
               and any(r.get(k) is not None for k in
                       ("t_nev_wan", "p_sales_wan", "b_install_gwh", "c_logistics_wan"))]
    data = {
        "source": "src.dcr_hdt_monthly",
        "file": src.name,
        "caliber": "**单月看边际（调仓信号）、累计/年度看趋势锚（重标依据），两者都跟踪**；"
                   "年化＝当年累计÷已过月数×12（抹平季节）。各层口径见 layers[*].caliber",
        "latest_ym": all_ym[-1] if all_ym else None,
        "layers": layers,
        # 兼容旧键：部分下游/命令行直接读这两个
        "latest_nev_pen_cum": layers["重卡"]["latest_nev_pen_cum"],
        "latest_swap_share_cum": layers["重卡"]["latest_swap_share_cum"],
        "series": series,
        "missing": missing,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return data


def load_source(name: str) -> dict | None:
    """读一个已注册跟踪源的 JSON（audit/tracking_<name>.json）。不存在返回 None。"""
    fn = TRACK_SOURCES.get(name)
    if not fn:
        return None
    p = OUT.parent / fn
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def load_all() -> dict[str, dict]:
    """读全部已注册且存在的跟踪源：{源名: 数据包}。主链与报警都从这里取数。"""
    return {name: d for name in TRACK_SOURCES if (d := load_source(name))}


def load() -> dict | None:
    """重卡漏斗源（hdt）。兼容旧调用；新代码请用 load_source/load_all。"""
    return load_source("hdt")


def _split_obs(obs_path: str) -> tuple[str, str]:
    """observed 路径首段是注册源名时走该源，否则默认 hdt（兼容旧卡）。

    例：「methanol.甲醇.latest_ratio」→ ("methanol", "甲醇.latest_ratio")；
       「重卡.latest_nev_pen_cum」     → ("hdt",       "重卡.latest_nev_pen_cum")。
    """
    parts = str(obs_path).split(".")
    if len(parts) > 1 and parts[0] in TRACK_SOURCES:
        return parts[0], ".".join(parts[1:])
    return "hdt", str(obs_path)


def _get_path(obj, path: str):
    """按点分路径取值；下标用数字段。取不到返回 None（**不猜**）。"""
    cur = obj
    for key in str(path).split("."):
        if isinstance(cur, dict):
            if key not in cur:
                return None
            cur = cur[key]
        elif isinstance(cur, (list, tuple)):
            try:
                cur = cur[int(key)]
            except (ValueError, IndexError):
                return None
        else:
            return None
        if isinstance(cur, dict) and "v" in cur and len(cur) > 1:
            cur = cur["v"]          # 就地信封：取值不取呈现要素
    return cur


def _calc_heavy_swap_penetration_weighted(config: dict):
    """重卡「换电占纯电」的模型值＝按场景权重加权。**复合值必须有名字**，
    否则它就只能硬编码在比对逻辑里，卡片化就白做了。"""
    # 【2026-09-22 · 门②】份额＝天花板 × 算得过账的车队占比，取装配时实际使用的那个值
    from price_response import effective_config
    config, _ = effective_config(config)
    scenes = config.get("vehicles", {}).get("heavy", {}).get("scenes", []) or []
    tot = sum(sc.get("weight", 0.0) for sc in scenes)
    if not tot:
        return None
    return sum(sc.get("weight", 0.0) * sc.get("swap_penetration", 0.0) for sc in scenes) / tot


def _current_year_index(config: dict) -> int:
    """跟踪比对发生在「当前自然年」：模型曲线 years[0]..years[-1] 中对应的下标（钳边界）。
    单月/年化实测都是当年流量，只能与当年模型流量比，不能与兑现年值比。"""
    import datetime
    years = (config.get("construction") or {}).get("years") or [2026, 2027, 2028, 2029, 2030]
    yi = datetime.date.today().year - int(years[0])
    return max(0, min(len(years) - 1, yi))


def _operating_stocks_tracker(config: dict) -> dict[str, float]:
    """出租/网约保有量（与 scale._operating_stocks 同公式，此处独立避免导入环）。"""
    d = config["operating_demand"]
    robotaxi_km = d["robotaxi_fleet_wan"] * d["robotaxi_daily_km"] * d["robotaxi_days"] / 1e4
    human_stock = (d["pool_2030_yi_km"] - robotaxi_km) / (
        d["human_daily_km"] * d["human_days"] / 1e4)
    return {"taxi": d["taxi_stock_wan"], "ridehail": human_stock - d["taxi_stock_wan"]}


def _pool_annual_ev_wan(config: dict, vehicle_key: str, yi: int) -> float | None:
    """单个车池当年的电动化年流量（万辆）：
      · 私家车＝年净增数组（保有量口径增量）；
      · 其余池＝保有量 ÷ 更新周期 × 当年电动化率 × 纯电占比。"""
    v = (config.get("vehicles") or {}).get(vehicle_key)
    if not v:
        return None
    pure = v.get("pure_electric_share", 1.0)
    arr = v.get("annual_net_additions_wan")
    if arr is not None:
        return float(arr[min(yi, len(arr) - 1)]) * float(pure)
    if vehicle_key == "taxi":
        stock = _operating_stocks_tracker(config)["taxi"]
    elif vehicle_key == "ridehail":
        stock = _operating_stocks_tracker(config)["ridehail"]
    else:
        stock = _get_path(config, f"vehicles.{vehicle_key}.stock_wan")
    cycle = _get_path(config, f"vehicles.{vehicle_key}.replacement_cycle_years")
    rates = v.get("nev_rates") or []
    if stock is None or cycle is None or not rates:
        return None
    return float(stock) / float(cycle) * float(rates[min(yi, len(rates) - 1)]) * float(pure)


def _calc_city_annual_ev_wan(config: dict):
    """城配池当年电动化更新流量（万辆）＝保有 1500 万 ÷ 8 年 × 当年 NEV 率。
    实测对照：电车资源「物流车」NEV 上险年化（七类口径，比模型分母窄）。"""
    return _pool_annual_ev_wan(config, "city", _current_year_index(config))


def _calc_pool_flows_total_wan(config: dict):
    """模型四池（重卡/城配/出租/网约/私家车）当年电动化流量合计（万辆）。
    用途＝**漏斗天花板校验**：模型覆盖池子的流量之和不可能超过全国 NEV 批发总盘。
    （robotaxi 年增量当前为 0 且量级小，不计入；私家取净增，天然 ≤ 销量，方向保守。）"""
    yi = _current_year_index(config)
    total = 0.0
    for key in ("heavy", "city", "taxi", "ridehail", "private"):
        f = _pool_annual_ev_wan(config, key, yi)
        if f is None:
            return None
        total += f
    return total


def _calc_national_install_gwh_current_year(config: dict):
    """全国动力电池装车量的**模型当年值**（GWh）：2025=769.7 → 兑现年=1350 线性插值。
    实测对照：联盟月度装车 YTD 年化（下半年装机偏强，年初年化系统性偏低）。"""
    import datetime
    nb = config.get("national_battery_market") or {}
    v0 = nb.get("power_battery_install_gwh_2025")
    v1 = nb.get("power_battery_install_gwh_2030")
    years = (config.get("construction") or {}).get("years") or [2026, 2027, 2028, 2029, 2030]
    if v0 is None or v1 is None:
        return None
    y1 = int(years[-1])
    cur = datetime.date.today().year
    if cur <= 2025:
        return float(v0)
    if cur >= y1:
        return float(v1)
    return float(v0) + (float(v1) - float(v0)) * (cur - 2025) / (y1 - 2025)


def _calc_commercial_catl_share_model(config: dict):
    """商用车换电体系内 CATL 标准份额的模型值：重卡三场景＋城配两场景，
    按**当年换电车辆流量**（池 EV 流量×场景权重×场景换电渗透×CATL 份额）加权。
    实测对照是联盟「CATL 占全部商用车装车」份额——口径更宽，只作 plausibility 锚。"""
    from price_response import effective_config   # 【2026-09-22 · 门②】重卡份额取装配时实际使用的值
    config, _ = effective_config(config)
    yi = _current_year_index(config)
    heavy_f = _pool_annual_ev_wan(config, "heavy", yi)
    city_f = _pool_annual_ev_wan(config, "city", yi)
    num = den = 0.0
    if heavy_f:
        for sc in (config.get("vehicles", {}).get("heavy", {}).get("scenes") or []):
            w = float(sc.get("weight", 0.0)) * float(sc.get("swap_penetration", 0.0))
            num += heavy_f * w * float(sc.get("catl_swap_share", 0.0))
            den += heavy_f * w
    if city_f:
        for sc in (config.get("vehicles", {}).get("city", {}).get("scenes") or []):
            w = float(sc.get("weight", 0.0)) * float(sc.get("swap_penetration", 0.0))
            num += city_f * w * float(sc.get("catl_swap_share", 0.0))
            den += city_f * w
    return num / den if den else None


_CALC = {
    "heavy_swap_penetration_weighted": _calc_heavy_swap_penetration_weighted,
    "city_annual_ev_wan": _calc_city_annual_ev_wan,
    "pool_flows_total_wan": _calc_pool_flows_total_wan,
    "national_install_gwh_current_year": _calc_national_install_gwh_current_year,
    "commercial_catl_share_model": _calc_commercial_catl_share_model,
}


def track_status(spec: dict) -> dict:
    """按事件卡的 track 声明扫月度序列，返回最新读数与**首个达标月**。

    这是「数据驱动的中检点」：达标与否完全由 audit/tracking_<source>.json 的
    series 实测决定，程序不预测、不手填——agent 每月追加数据后，首次满足
    field op value 的月份就是触发月（config_loader 重放时据此自动改参数）。
    spec = {source, field, op, value}，例：
      {source="methanol", field="ratio", op="<=", value=1.3}
    """
    src_name = str(spec.get("source") or "").strip()
    field = str(spec.get("field") or "").strip()
    op = str(spec.get("op") or "<=").strip()
    if src_name not in TRACK_SOURCES:
        raise SystemExit(f"track.source={src_name!r} 未在 TRACK_SOURCES 登记——"
                         f"可选：{sorted(TRACK_SOURCES)}")
    if op not in _TRACK_OPS:
        raise SystemExit(f"track.op={op!r} 不支持，可选：{sorted(_TRACK_OPS)}")
    thr = float(spec["value"])
    d = load_source(src_name) or {}
    series = sorted((r for r in (d.get("series") or []) if r.get(field) is not None),
                    key=lambda r: str(r.get("ym")))
    hit = next((str(r["ym"]) for r in series
                if _TRACK_OPS[op](float(r[field]), thr)), None)
    latest = series[-1] if series else {}
    return {
        "source": src_name, "field": field, "op": op, "threshold": thr,
        "latest_ym": latest.get("ym"),
        "latest_value": (None if not latest else float(latest[field])),
        "triggered_ym": hit,   # None＝截至最新月从未达标，事件零影响
    }


def _fmt_card(v: float, card: dict) -> str:
    """按卡片声明的 unit/decimals 格式化报警文案——**不按数值大小猜量级**。"""
    unit = str(card.get("unit") or "")
    dec = card.get("decimals")
    if unit == "%":
        return f"{float(v):.{1 if dec is None else int(dec)}%}"
    d = 1 if dec is None else int(dec)
    return f"{float(v):,.{d}f}"


def _eval_card(card: dict, sources: dict, config: dict) -> str | None:
    """评估一张 `[[watch]]` 卡：越阈值返回**去掉【层名】前缀的报警正文**，否则 None。

    【2026-09-16 卡片化】比对规则全部住卡片（compare/threshold/direction），
    本函数只遍历——**加一层跟踪＝加一张卡，不改程序。**
    【2026-09-16e】返回值不含层名前缀：归组展示时层名（group）由 check_rows 统一戴，
    同组多张卡的正文并列在同一条报警下（累计锚/单月边际各一行）。
    """
    obs_path = str(card.get("observed") or "").strip()
    if not obs_path:
        return None                        # 数据源未接：卡片登记在案，但不报警
    src_name, rel = _split_obs(obs_path)
    layers = (sources.get(src_name) or {}).get("layers") or {}
    node = _get_path(layers, rel)
    obs = node.get("value") if isinstance(node, dict) else node
    if obs in (None, 0):
        return None
    model_ref = str(card.get("model") or "")
    if model_ref.startswith("calc:"):
        mv = (_CALC.get(model_ref[5:]) or (lambda _c: None))(config)
    else:
        mv = _get_path(config, model_ref)
    if mv is None:
        return (f"模型侧取不到 `{model_ref}`——**卡片指向了一个不存在的参数**，改名或删卡")
    mv, obs = float(mv), float(obs)
    mode = card.get("compare", "diff")
    thr = float(card.get("threshold", 0))
    gap = (mv - obs) if mode == "diff" else (mv / obs)
    over = (gap > thr) if mode == "diff" else (gap > thr)
    under = (gap < -thr) if mode == "diff" else (gap < 1.0 / thr if thr else False)
    direction = card.get("direction", "either")
    hit = {"model_high": over, "model_low": under, "either": over or under}[direction]
    # model_low 的含义是"模型偏低"＝实测高于模型，diff 模式下即 obs − mv 越阈值
    if direction == "model_low" and mode == "diff":
        hit = (obs - mv) > thr
    if not hit:
        return None
    ym = node.get("ym") if isinstance(node, dict) else None
    if mode == "diff":
        head = (f"模型 {_fmt_card(mv, card)}，实测 {_fmt_card(obs, card)}（{ym}），"
                f"差 {_fmt_card(mv - obs, card)}")
    else:
        head = (f"模型 {_fmt_card(mv, card)}，实测 {_fmt_card(obs, card)}（{ym}），"
                f"**高出 {gap:.2f} 倍**")
    why = str(card.get("why", "") or "")
    period = str(card.get("period", "—") or "—")
    return f"{head}。{why}（复核周期：{period}）" if why else f"{head}（复核周期：{period}）"


def check_rows(config: dict) -> list[dict]:
    """结构化报警（沙盘 ② 的数据源）：遍历 watch 卡，按 card.group 归组。

    返回三类行（kind 区分）：
      single —— {layer, text}：无 group 的独立报警；
      group  —— {layer=组名, members:[{role, text}]}：同组多张卡合并成一条，
                各卡以 role 分行——**判定逻辑各自独立（双轨），展示合并（一副变量、
                两副眼镜）**，避免「累计 28.9% / 单月 35.0%」被读成模型自相矛盾；
      stale  —— {text}：跟踪底稿过期（正文自带【...】前缀）。
    组内只收集**实际越阈值**的卡；组里仅一张卡报警时仍以组名出现（标明它是哪副眼镜）。
    """
    sources = load_all()
    if not sources:
        return []
    rows: list[dict] = []
    groups: dict[str, dict] = {}

    for card in config.get("watch", []) or []:
        text = _eval_card(card, sources, config)
        if text is None:
            continue
        grp = str(card.get("group") or "").strip()
        if grp:
            role = str(card.get("role") or "").strip()
            if not role:
                raise SystemExit(
                    f"watch 卡 {card.get('id')} 写了 group={grp!r} 就必须写 role"
                    "——归组后各卡靠角色名区分（如累计锚/单月边际）")
            row = groups.get(grp)
            if row is None:
                row = {"kind": "group", "layer": grp, "members": []}
                groups[grp] = row
                rows.append(row)
            row["members"].append({"role": role, "text": text})
        else:
            rows.append({"kind": "single",
                         "layer": str(card.get("layer") or ""), "text": text})

    # ── 底稿新鲜度：每个跟踪源各自检查，过期即响（竞争性变量必须带复核周期）
    import datetime as _dt
    now = _dt.date.today()
    for src_name, d in sources.items():
        latest = d.get("latest_ym")
        if not latest:
            continue
        try:
            y, m = (int(x) for x in str(latest).split("-")[:2])
            gap = (now.year - y) * 12 + (now.month - m)
        except Exception:
            continue
        if gap > WATCH["stale_months"]:
            how = ("agent 联网取数后跑 `python src/monthly_update.py fill <payload.json>`，"
                   "再 `python src/tracker.py extract`（≤2026-06 为人工底稿）"
                   if src_name == "hdt"
                   else "跑 `python src/tracker.py methanol-append` 追加月度读数")
            rows.append({"kind": "stale",
                         "text": (f"【{src_name} 跟踪数据过期】最新到 {latest}，距今 {gap} 个月"
                                  f"（阈值 {WATCH['stale_months']}）——**上面的比对是拿旧数在比**。{how}")})
    return rows


def check(config: dict) -> list[str]:
    """命令行用的扁平报警串：把 check_rows() 结构压成「一行一条」。**纯 stdlib。**

    沙盘前端直接消费 check_rows()（要保留组结构）；命令行 `tracker.py` 调本函数。
    """
    out: list[str] = []
    for r in check_rows(config):
        if r["kind"] == "stale":
            out.append(r["text"])
        elif r["kind"] == "single":
            out.append(f"【{r['layer']}】{r['text']}")
        else:
            body = "；".join(f"［{m['role']}］{m['text']}" for m in r["members"])
            out.append(f"【{r['layer']}】{body}")
    return out


def watch_table(config: dict) -> list[dict]:
    """给沙盘 ② 块的跟踪表：每张卡一行（含未接数据源的）。"""
    sources = load_all()
    rows = []
    for card in config.get("watch", []) or []:
        obs_path = str(card.get("observed") or "").strip()
        if obs_path:
            src_name, rel = _split_obs(obs_path)
            layers = (sources.get(src_name) or {}).get("layers") or {}
            node = _get_path(layers, rel)
        else:
            node = None
        obs = node.get("value") if isinstance(node, dict) else None
        model_ref = str(card.get("model") or "")
        mv = ((_CALC.get(model_ref[5:]) or (lambda _c: None))(config)
              if model_ref.startswith("calc:") else _get_path(config, model_ref))
        rows.append({
            "id": card.get("id"), "layer": card.get("layer"),
            "group": str(card.get("group") or ""),    # 非空＝双轨之一，层名后展示 role
            "role": str(card.get("role") or ""),
            "model": None if mv is None else float(mv),
            "observed": None if obs is None else float(obs),
            "ym": node.get("ym") if isinstance(node, dict) else None,
            "compare": card.get("compare", "diff"),
            "threshold": card.get("threshold"),
            "unit": card.get("unit", ""),                 # 单位住卡片：程序不按数值猜量级
            "decimals": card.get("decimals"),             # 缺省由前端按单位兜底
            "period": card.get("period"),
            "connected": bool(obs_path),
            "why": card.get("why", ""),
        })
    return rows


def readings() -> list[str]:
    """全部跟踪源各层的最新读数（不报警，只报数）。给沙盘 ② 块和命令行看。"""
    out = []
    for src_name, d in load_all().items():
        src_parts = []
        for layer, items in (d.get("layers") or {}).items():
            parts = []
            for k, v in items.items():
                if not isinstance(v, dict) or v.get("value") is None:
                    continue
                name = k.replace("latest_", "")
                x = v["value"]
                # 单位按键名判，不按数值大小猜——0.5451 是万辆不是 54.5%
                # （watch 卡的单位住卡片；此处是无卡片的总览，只能按键名白名单判）。
                is_ratio = ("pen" in k or "share" in k or "bev_in_nev" in k
                            or k.endswith("catl_passenger") or k.endswith("catl_commercial"))
                parts.append(f"{name} {x:.1%}" if is_ratio else f"{name} {x:,.1f}")
            if parts:
                src_parts.append(f"{layer}（{items.get('caliber','')}）：" + "；".join(parts))
        if src_parts:
            out.append(f"[{src_name}] " + "　".join(src_parts))
    return out


def append_methanol(ym: str, ratio: float, *, green: float | None = None,
                    gray: float | None = None, src: str = "", note: str = "") -> dict:
    """追加一条甲醇月度比价记录（**agent 月更的唯一写入口**，带校验）。

    用法：
      python src/tracker.py methanol-append 2026-10 2.8 --src src.xxx \\
          --green 6000 --gray 2140 [--note "..."]
    校验（任一不过即中断，绝不写入脏数据）：
      · ym 必须 YYYY-MM 且**严格晚于**最后一条（不许倒灌、不许覆盖）；
      · ratio>0；若 green/gray 都给了，必须与 ratio 自洽（±1%）；
      · src 必填——信源可回溯是月更数据的准入条件。
    写入后同步刷新 layers 最新值；触发判定（≤1.3）由模型重放时自动完成，本函数不碰参数。
    """
    import re
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", ym):
        raise SystemExit(f"月份格式必须 YYYY-MM：{ym!r}")
    ratio = float(ratio)
    if ratio <= 0:
        raise SystemExit(f"绿醇/灰醇比价必须为正：{ratio}")
    if not src.strip():
        raise SystemExit("--src 必填：月更数据必须带可回溯信源（见 audit/信源审计台账.md）")
    if green is not None and gray is not None:
        green, gray = float(green), float(gray)
        if gray <= 0:
            raise SystemExit(f"灰甲醇价必须为正：{gray}")
        if abs(green / gray - ratio) > 0.01:
            raise SystemExit(f"绿醇/灰醇 不自洽：{green}/{gray}={green/gray:.3f} ≠ ratio {ratio}")

    p = OUT.parent / TRACK_SOURCES["methanol"]
    d = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {
        "source": src,
        "caliber": "绿色甲醇到岸价 ÷ 灰甲醇价（倍）。月度更新；**触发只看比值不看渗透率**"
                   "（价格是因、渗透率是果），各月记录见 series",
        "latest_ym": None,
        "layers": {"甲醇": {"caliber": "绿色甲醇到岸价/灰甲醇价（绿醇 6000–8000 元/吨口径，2026-09）",
                            "latest_ratio": {"ym": None, "value": None}}},
        "series": [],
    }
    series = d.setdefault("series", [])
    if series and ym <= max(str(r.get("ym")) for r in series):
        raise SystemExit(f"{ym} 不晚于已有最后月份——月更只许追加，修正旧数请人工评审后改 JSON")
    row = {"ym": ym, "ratio": ratio,
           "green_price_rmb_t": green, "gray_price_rmb_t": gray,
           "src": src.strip(), "note": note.strip()}
    series.append(row)
    series.sort(key=lambda r: str(r.get("ym")))
    d["latest_ym"] = series[-1]["ym"]
    d.setdefault("layers", {}).setdefault("甲醇", {})["latest_ratio"] = {"ym": ym, "value": ratio}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    hit = track_status({"source": "methanol", "field": "ratio", "op": "<=", "value": 1.3})
    flag = (f"　★★ 已达触发线 ≤1.3（首个达标月 {hit['triggered_ym']}）——"
            f"重跑 run.py 后参数自动生效") if hit["triggered_ym"] else ""
    print(f"✓ 已追加 {ym} 绿醇/灰醇 = {ratio:g}×（{src}）→ {p.relative_to(ROOT)}{flag}")
    return d


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
    if cmd == "methanol-append":
        # 极简参数解析（agent 调用面；保持纯 stdlib）
        args, kw = sys.argv[2:], {}
        pos = []
        i = 0
        while i < len(args):
            if args[i].startswith("--") and i + 1 < len(args):
                kw[args[i][2:]] = args[i + 1]
                i += 2
            else:
                pos.append(args[i])
                i += 1
        if len(pos) < 2:
            raise SystemExit('用法：python src/tracker.py methanol-append '
                             'YYYY-MM 比值 --src 信源id [--green 绿醇价 --gray 灰醇价] [--note 备注]')
        append_methanol(
            pos[0], float(pos[1]),
            green=(float(kw["green"]) if "green" in kw else None),
            gray=(float(kw["gray"]) if "gray" in kw else None),
            src=kw.get("src", ""), note=kw.get("note", ""))
        return 0
    sources = load_all()
    if not sources:
        print("还没有跟踪数据：重卡先跑 python src/tracker.py extract；"
              "甲醇用 python src/tracker.py methanol-append ...")
        return 1
    for line in readings():
        print("  · " + line)
    from config_loader import load_config
    warns = check(load_config())
    for w in warns:
        print("  ⚠ " + w)
    if not warns:
        print("  各源无越阈值报警。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

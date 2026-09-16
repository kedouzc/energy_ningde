# -*- coding: utf-8 -*-
"""agent 月度取数 → xlsx 底稿的**唯一写入口**（带硬校验，绝不写脏数据）。

为什么有这个文件（2026-09-16 起的新月更链路）
──────────────────────────────────────────────────────────────────────
≤2026-06 的月度数据由用户手工维护；2026-07 起（含）改由 agent 按 xlsx 内既有
数据源（Part3 内嵌的第一商用车网文章超链接、各 Part 口径列注明的发布方）联网取数，
但 agent **不直接拿 openpyxl 改表**——所有写入都经过本文件校验：
  ① 只许填「最新月的下一月」新行（Part1–4）或已占位的待取月（月度重卡数据）；
  ② 目标单元格已有真实数据 → 中断（只能填空/占位格，绝不覆盖）；
  ③ 百分数按 xlsx 历史存储习惯填**显示值**（47.24 表示 47.24%，extract 时再 ÷100）；
  ④ 每个动到的数据块必须带来源文章（Part3 写五个「来源」列；Part1/2/4 把链接挂年月格）；
  ⑤ 写入成功后自动跑 tracker.extract() 刷新 audit/tracking_hdt.json。

用法
──────────────────────────────────────────────────────────────────────
  python src/monthly_update.py status
      列出各 sheet 已填到几月、下月该填什么、最新一行的来源链接（agent 据此找数）
  python src/monthly_update.py fill <payload.json>
      按 payload 写一个月。payload 结构：
      {
        "ym": "2026-07",
        "sheets": {
          "Part1_中汽协总量": {"values": {"nev_wan": 156.1, "pen_m": 60.4,
              "nev_cum_wan": 900.7}, "url": "https://...", "src": "src.caam_202607",
              "caliber": "可选：写入该 Part 末列口径说明（只填空格）"},
          "Part3_商用车细分": {"values": {"nev_wan": 2.6503, ...},
              "sources": {"nev": ["文章标题", "https://...cvworld...240714"],
                          "swap": ["换电月报标题", "http://...240853"],
                          "charge": ["充电月报标题", "https://...240750"]}}
        },
        "月度重卡数据": {"sales": 26503, "yoy": 59.3, "pen": 47.24,
                         "title": "7月新能源重卡...", "url": "https://...240714",
                         "note": "可选备注"}
      }
      键名＝tracker.PART_COLUMNS 的输出键（唯一一家，列名变了两边一起换）。
      取数完成后还须把新信源登记进 audit/信源审计台账.md（src 字段给的是台账 id）。
"""
from __future__ import annotations

import datetime as _dt
import json
import pathlib
import re
import sys

import tracker

# 允许覆盖的占位值（真实数字/文字一律不覆盖）
PLACEHOLDERS = {None, "", "待补", "-", "—", "未获取"}

# 「月度重卡数据」简表列映射（0 基）
SIMPLE_SHEET = "月度重卡数据"
SIMPLE_COLS = {"sales": 1, "yoy": 2, "pen": 4, "caliber": 5, "source": 6, "note": 7}
MISSING_SHEET = "缺失月份说明"


def _next_month(ym: str) -> str:
    """YYYY-MM 加一个月。"""
    y, m = int(ym[:4]), int(ym[5:7])
    y += (m // 12)
    m = m % 12 + 1
    return f"{y:04d}-{m:02d}"


def _resolve_columns(ws, want: dict[str, tuple[str, bool]]) -> dict[str, int]:
    """按表头子串解析列号（与 tracker._sheet_rows 同规则；对不上→该键不可写）。"""
    hdr = [c.value for c in ws[1]]
    out = {}
    for key, (name, _pct) in want.items():
        hit = next((i for i, h in enumerate(hdr) if h and name in str(h)), None)
        if hit is None:
            raise SystemExit(f"sheet「{ws.title}」表头找不到列 {name!r}（键 {key}）——"
                             "底稿改了表头？先更新 tracker.PART_COLUMNS")
        out[key] = hit
    return out


def _assert_writable(cell, where: str) -> None:
    """目标格必须为空或占位值；已有真实内容立即中断（**绝不覆盖**）。"""
    if cell.value not in PLACEHOLDERS:
        raise SystemExit(f"{where} 已有真实值 {cell.value!r}——fill 只许填空，"
                         "修正旧数请人工评审后改底稿")


def _link(cell, url: str, title: str | None = None) -> None:
    """给单元格挂超链接（标题文本可选），并设蓝色下划线让链接可见。"""
    import openpyxl.styles as st
    if not re.fullmatch(r"https?://\S+", url):
        raise SystemExit(f"链接必须 http(s) 完整 URL：{url!r}")
    cell.hyperlink = url
    if title is not None:
        cell.value = title
    cell.font = st.Font(color="0000FF", underline="single")


def _fill_part_sheet(wb, sheet: str, ym: str, block: dict) -> None:
    """填 Part1–4 中一张表的新月份行：定位行→逐键写值→挂来源。"""
    import openpyxl.styles as st
    ws = wb[sheet]
    want = tracker.PART_COLUMNS[sheet]
    col = _resolve_columns(ws, want)

    # 行定位：最新月 + 1（不许跳月、不许重填）
    yms = [str(ws.cell(row=r, column=1).value) for r in range(2, ws.max_row + 1)
           if ws.cell(row=r, column=1).value]
    expected = _next_month(yms[-1]) if yms else None
    if ym != expected:
        raise SystemExit(f"「{sheet}」下月应填 {expected}，payload 给的是 {ym}——"
                         "不许跳月/重填（最新已填月：%s）" % (yms[-1] if yms else "无"))
    row = ws.max_row + 1
    ws.cell(row=row, column=1, value=ym)

    values = block.get("values") or {}
    bad = [k for k in values if k not in col]
    if bad:
        raise SystemExit(f"「{sheet}」出现未登记键 {bad}——可写键见 tracker.PART_COLUMNS")

    for key, val in values.items():
        try:
            num = float(val)
        except (TypeError, ValueError):
            raise SystemExit(f"「{sheet}」{key}={val!r} 不是数（百分数填显示值如 47.24）")
        c = ws.cell(row=row, column=col[key] + 1)
        _assert_writable(c, f"「{sheet}」{ym} {key}")
        c.value = num

    # ── 来源：Part3 写文章列；Part1/2/4 链接挂年月格
    if sheet == "Part3_商用车细分":
        sources = block.get("sources") or {}
        need = set()
        for blk, fields in tracker.PART3_BLOCK_SOURCES.items():
            if any(k in values for k in fields):
                need.add(blk)
        miss = need - set(sources)
        if miss:
            raise SystemExit(f"「{sheet}」{ym} 填了 {sorted(need)} 数据块，"
                             f"sources 缺文章：{sorted(miss)}（[标题, URL] 二元组）")
        for blk, pair in sources.items():
            if blk not in tracker.PART3_SOURCE_COLS:
                raise SystemExit(f"Part3 sources 未知块 {blk!r}；"
                                 f"可选 {sorted(tracker.PART3_SOURCE_COLS)}")
            if not (isinstance(pair, list) and len(pair) == 2):
                raise SystemExit(f"Part3 sources.{blk} 必须是 [标题, URL]")
            title, url = pair
            ci = tracker.PART3_SOURCE_COLS[blk]
            _link(ws.cell(row=row, column=ci + 1), url, title)
        if not sources:
            raise SystemExit(f"「{sheet}」{ym} 必须给 sources（文章标题＋链接）")
    else:
        url = block.get("url")
        if not url:
            raise SystemExit(f"「{sheet}」{ym} 必填 url（发布方原文链接，挂年月单元格）")
        _link(ws.cell(row=row, column=1), url)
    if not str(block.get("src") or "").strip():
        raise SystemExit(f"「{sheet}」{ym} 必填 src（信源台账 id，见 audit/信源审计台账.md")

    # 口径说明列（各 Part 末列，表头含「口径」）：可选写入，只填空格，不覆盖旧说明
    caliber = str(block.get("caliber") or "").strip()
    if caliber:
        cal_idx = next((i for i, c in enumerate(ws[1])
                        if c.value and "口径" in str(c.value)), ws.max_column - 1)
        cal_cell = ws.cell(row=row, column=cal_idx + 1)
        _assert_writable(cal_cell, f"「{sheet}」{ym} 口径说明")
        cal_cell.value = caliber


def _fill_simple_sheet(wb, ym: str, block: dict) -> None:
    """填「月度重卡数据」简表：允许写入已占位的待取月，或追加下一月。"""
    ws = wb[SIMPLE_SHEET]
    target = None
    for r in range(2, ws.max_row + 1):
        if str(ws.cell(row=r, column=1).value) == ym:
            target = r
            break
    if target is None:
        yms = [str(ws.cell(row=r, column=1).value) for r in range(2, ws.max_row + 1)
               if ws.cell(row=r, column=1).value]
        expected = _next_month(yms[-1]) if yms else None
        if ym != expected:
            raise SystemExit(f"「{SIMPLE_SHEET}」下月应填 {expected}，payload 给的是 {ym}")
        target = ws.max_row + 1
        ws.cell(row=target, column=1, value=ym)

    for key, val in (("sales", block.get("sales")), ("yoy", block.get("yoy")),
                     ("pen", block.get("pen"))):
        if val is None:
            continue
        c = ws.cell(row=target, column=SIMPLE_COLS[key] + 1)
        _assert_writable(c, f"「{SIMPLE_SHEET}」{ym} {key}")
        c.value = float(val)
    cal = ws.cell(row=target, column=SIMPLE_COLS["caliber"] + 1)
    _assert_writable(cal, f"「{SIMPLE_SHEET}」{ym} 口径")
    cal.value = "新能源重卡"
    src = ws.cell(row=target, column=SIMPLE_COLS["source"] + 1)
    _assert_writable(src, f"「{SIMPLE_SHEET}」{ym} 来源")
    url = block.get("url")
    if not url:
        raise SystemExit(f"「{SIMPLE_SHEET}」{ym} 必填 url（第一商用车网月度原文）")
    _link(src, url, block.get("title") or "第一商用车网")
    note = ws.cell(row=target, column=SIMPLE_COLS["note"] + 1)
    if note.value in PLACEHOLDERS:
        note.value = block.get("note") or f"agent 按既有数据源自动取数（{_dt.date.today()}）"


def fill(payload_path: str) -> None:
    """按 payload 写一个月：校验 → 写 xlsx → 删缺失说明行 → extract 刷新 JSON。"""
    import openpyxl
    p = pathlib.Path(payload_path)
    payload = json.loads(p.read_text(encoding="utf-8"))
    ym = str(payload.get("ym") or "")
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", ym):
        raise SystemExit(f"payload.ym 必须 YYYY-MM：{ym!r}")

    xlsx = tracker._find_xlsx()
    if xlsx is None:
        raise SystemExit("找不到月度数据表；候选见 tracker.XLSX_CANDIDATES")
    wb = openpyxl.load_workbook(xlsx)          # 不用 data_only：要保留公式/超链接写回

    sheets = payload.get("sheets") or {}
    if not sheets and SIMPLE_SHEET not in payload:
        raise SystemExit("payload 没有任何 sheets 数据")
    for sheet, block in sheets.items():
        if sheet not in tracker.PART_COLUMNS:
            raise SystemExit(f"未知 sheet {sheet!r}；可选：{sorted(tracker.PART_COLUMNS)}")
        _fill_part_sheet(wb, sheet, ym, block)
    if SIMPLE_SHEET in payload:
        _fill_simple_sheet(wb, ym, payload[SIMPLE_SHEET])

    # 该月已取数 → 从「缺失月份说明」移除对应行（倒序删防位移）
    if MISSING_SHEET in wb.sheetnames:
        wsm = wb[MISSING_SHEET]
        for r in range(wsm.max_row, 1, -1):
            if str(wsm.cell(row=r, column=1).value) == ym:
                wsm.delete_rows(r, 1)

    wb.save(xlsx)
    print(f"✓ 已写入 {xlsx.name}：{ym}（{', '.join(sheets) or SIMPLE_SHEET}）")
    data = tracker.extract()
    print(f"✓ 已刷新 audit/tracking_hdt.json（最新月 {data['latest_ym']}）")


def status() -> None:
    """打印各表已填到几月、下月待填、最新行的来源链接——agent 据此沿同一数据源找新数。"""
    import openpyxl
    xlsx = tracker._find_xlsx()
    if xlsx is None:
        raise SystemExit("找不到月度数据表")
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    for sheet in tracker.PART_COLUMNS:
        ws = wb[sheet]
        yms = [str(ws.cell(row=r, column=1).value) for r in range(2, ws.max_row + 1)
               if ws.cell(row=r, column=1).value]
        nxt = _next_month(yms[-1])
        print(f"[{sheet}] 已填至 {yms[-1]}，下月待填 {nxt}")
        if sheet == "Part3_商用车细分":
            last = ws.max_row
            for blk, ci in tracker.PART3_SOURCE_COLS.items():
                c = ws.cell(row=last, column=ci + 1)
                if c.value:
                    print(f"    {blk:6s} 最新来源：{c.value[:38]} → {c.hyperlink.target if c.hyperlink else '（无链接）'}")
        elif tracker.MONTH_CELL_SOURCE_SHEETS and sheet in tracker.MONTH_CELL_SOURCE_SHEETS:
            c = ws.cell(row=ws.max_row, column=1)
            print(f"    发布方口径：{ws.cell(row=ws.max_row, column=ws.max_column).value}")
    ws = wb[SIMPLE_SHEET]
    placeholders = [str(ws.cell(row=r, column=1).value) for r in range(2, ws.max_row + 1)
                    if ws.cell(row=r, column=1).value
                    and ws.cell(row=r, column=SIMPLE_COLS["source"] + 1).value in PLACEHOLDERS]
    yms = [str(ws.cell(row=r, column=1).value) for r in range(2, ws.max_row + 1)
           if ws.cell(row=r, column=1).value]
    print(f"[{SIMPLE_SHEET}] 已填至 {yms[-1]}；占位待取：{placeholders or '无'}")
    print("\n取数流程：联网取数 → 写 payload.json → "
          "python src/monthly_update.py fill payload.json → 登记信源台账")


def main() -> int:
    """命令行入口：status（默认）／fill <payload.json>。"""
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        status()
        return 0
    if cmd == "fill":
        if len(sys.argv) < 3:
            raise SystemExit("用法：python src/monthly_update.py fill <payload.json>")
        fill(sys.argv[2])
        return 0
    raise SystemExit(f"未知命令 {cmd!r}（status｜fill）")


if __name__ == "__main__":
    raise SystemExit(main())

# -*- coding: utf-8 -*-
"""读数留痕：每次构建把三档关键读数追加一条，供沙盘显示「上一轮 → 本轮」。

【2026-09-15】为什么要有它
──────────────────────────────────────────────────────────────────────
用户不读程序，只看 `outputs/换电沙盘_v4.3.html`。而此前所有改动都落在
`src/`、`configs/`、`narrative/` —— **改了一整轮，HTML 上看不出任何区别**，
于是"我做完了"这句话无法被复核，只能被相信。

本模块 + `configs/changelog.toml` 一起补这个洞，分工是刻意的：

  · **数字自动记**（本模块）：程序每次构建自己写，写的是实跑读数。**它不会替我说谎。**
  · **话人工写**（changelog.toml）：这一轮改了什么、为什么、该盯哪个数。

两者在沙盘里并排显示：**我的说法在左，程序的读数在右，对不上一眼就能看见。**
一个只有说法的变更记录是公关稿；一个只有数字的变更记录看不懂。要的是两个都在。

【同日覆盖】同一天多次构建只留最后一次——一天之内的反复试错不是"轮次"。
"""
from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "audit" / "baseline_history.json"

# 盯住的读数：少而关键。加一条之前先问"它变了我会不会想知道"——
# 会，就加；不确定，就不加。**这张表长了，等于没有。**
WATCHED: tuple[tuple[str, str, int], ...] = (
    ("val.swap_increment", "换电增量价值合计（亿）", 1),
    ("val.incr_over_mktcap", "增量/集团市值", 3),
    ("swap.coverage", "EBITDA 覆盖倍数", 2),
    ("swap.ebitda", "终局年 EBITDA（亿）", 1),
    ("scale.stations_total", "终局站数合计", 0),
    ("val.implied_multiple_perpetual", "隐含倍数·永续账", 2),
    ("val.turnover_multiple", "隐含倍数·计周转增长", 2),
)


def latest_round_key() -> str:
    """留痕的键 ＝ `configs/changelog.toml` 最后一条的 `date`（如 "2026-09-15b"）。

    用台账的键而不是日历日期，是因为**一天可能做两轮**——用日期当键，
    第二轮会把第一轮的读数悄悄覆盖掉，于是台账里写着两条、读数里只剩一条，
    "说法与读数并排对照"这件事当场失效。台账没有就退回今天的日期。
    """
    try:
        import tomllib
        raw = (ROOT / "configs" / "changelog.toml").read_bytes()
        rounds = tomllib.loads(raw.decode("utf-8")).get("round", [])
        if rounds:
            return str(rounds[-1].get("date") or _dt.date.today().isoformat())
    except Exception:
        pass
    return _dt.date.today().isoformat()


def load() -> list[dict[str, Any]]:
    if not HISTORY_PATH.exists():
        return []
    try:
        return json.loads(HISTORY_PATH.read_text("utf-8"))
    except Exception:
        return []


def record(values_by_tier: dict[str, dict[str, float]], today: str | None = None) -> list[dict]:
    """把今天的三档读数写进留痕（同日覆盖）。`values_by_tier` ＝ {档名: read_metrics 结果}。"""
    day = today or _dt.date.today().isoformat()
    row = {"date": day, "tiers": {}}
    for tier, vals in values_by_tier.items():
        row["tiers"][tier] = {k: (None if vals.get(k) is None else float(vals[k]))
                              for k, _lb, _d in WATCHED if k in vals}
    rows = [r for r in load() if r.get("date") != day]
    rows.append(row)
    rows.sort(key=lambda r: str(r["date"]))
    rows = rows[-40:]                     # 只留最近 40 天，文件不许无限长
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(rows, ensure_ascii=False, indent=1) + "\n",
                            encoding="utf-8")
    return rows


def payload() -> dict[str, Any]:
    """给沙盘的数据包：读数定义 + 最近两次的值（够看"上一轮→本轮"）。"""
    rows = load()
    return {
        "watched": [{"key": k, "label": lb, "decimals": d} for k, lb, d in WATCHED],
        "rows": rows[-8:],
        "prev": rows[-2] if len(rows) >= 2 else None,
        "curr": rows[-1] if rows else None,
    }

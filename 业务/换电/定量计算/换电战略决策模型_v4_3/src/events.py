# -*- coding: utf-8 -*-
"""事件表：参数是怎么变成现在这样的，以及每一次变动值多少钱。

【2026-09-13h】为什么要有它
──────────────────────────────────────────────────────────────────────
并购启源之后，`vehicles.heavy.scenes.*.catl_swap_share` 从 0.30 改成 0.80，
**这一个参数让换电增量价值几乎翻倍**——而这次改动在仓库里只留下一行行尾注释。
改动本身没有账：说不出它值多少钱，也说不出如果它没发生现在会是什么样。

更要紧的是它暴露了一个方法缺口：**"看到并购 → 直接改参数"是把结论写进输入。**
正确的形态是——并购是一个**事件**，事件**扰动**参数，扰动**产生**价值差分。
三者分开，模型才留得下痕。

**这同时解决了中检点的形态问题**：一条中检点＝一个 `kind="预期"` 的事件。
它不改当前值，但程序照样能算出"若兑现，价值 +X"。
中检点因此从一张定性清单变成**参数扰动 ＋ 价值差分**，第 7 章要的正是这个。

【2026-09-15·A9 升级为重放版】
──────────────────────────────────────────────────────────────────────
轻量版是"账本与账实各记一遍，再断言两边相等"——断言只能发现不一致，说不出谁对。
重放版把关系倒过来：

  · **初值**只有一个家：`configs/base.toml`；
  · **"它后来怎么变成现在这样"**只有一个家：本文件读的 `[[event]]` 表；
  · **当前值不再有家，它是两者的函数**（`config_loader.replay_events`）。

于是"想改当前值，只能补一张事件卡"从一条纪律变成一条**物理约束**：
直接去 base.toml 把并购后的数写进去，重放时当场中断。

【trigger 与 changes 分开】
`trigger` 答"凭什么说它发生了"（可观察、可证伪的触发条件），
`changes` 答"它发生之后哪些参数变成多少"。
已发生事件用 `date` 交代前者，未发生事件**必须写 `trigger`**——
没有触发条件的"预期"是愿望，不是中检点。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from config_loader import cloned_config, get_path, _set_path

KINDS = ("已发生", "预期", "中检点")


@dataclass
class Change:
    param: str
    frm: float
    to: float


@dataclass
class Event:
    id: str
    date: str
    kind: str
    title: str
    why: str
    src: str = ""
    trigger: str = ""          # 未发生事件必填：凭什么说它发生了
    changes: list[Change] = field(default_factory=list)


def load_events(config: dict) -> list[Event]:
    """读 [[event]] 并硬校验。缺字段直接中断——事件是判断，不许含糊登记。"""
    out: list[Event] = []
    seen: set[str] = set()
    for i, raw in enumerate(config.get("event", []) or []):
        for k in ("id", "date", "kind", "title", "why", "changes"):
            if k not in raw:
                raise SystemExit(f"[[event]] 第 {i+1} 张卡缺字段 {k!r}")
        if raw["kind"] not in KINDS:
            raise SystemExit(f"[[event]] {raw['id']} 的 kind 必须是 {KINDS} 之一")
        if raw["id"] in seen:
            raise SystemExit(f"[[event]] id 重复：{raw['id']}")
        seen.add(raw["id"])
        if raw["kind"] != "已发生" and not str(raw.get("trigger", "")).strip():
            raise SystemExit(
                f"[[event]] {raw['id']} 是「{raw['kind']}」却没有 trigger——"
                "**没有触发条件的预期是愿望，不是中检点**。写清楚：什么可观察的事发生了，"
                "就算它兑现了（要能被证伪，且最好月度可查）。")
        chs = []
        for c in raw["changes"]:
            for k in ("param", "from", "to"):
                if k not in c:
                    raise SystemExit(f"[[event]] {raw['id']} 的 changes 缺字段 {k!r}")
            chs.append(Change(param=c["param"], frm=float(c["from"]), to=float(c["to"])))
        out.append(Event(id=raw["id"], date=str(raw["date"]), kind=raw["kind"],
                         title=raw["title"], why=raw["why"], src=raw.get("src", ""),
                         trigger=str(raw.get("trigger", "")), changes=chs))
    return out


def assert_current(config: dict, events: list[Event]) -> None:
    """**未发生**事件的 `from` 必须等于参数的当前值（＝重放之后的值）。

    已发生事件不在这里查——`config_loader.replay_events` 在重放时已经把
    "base.toml 的初值 == 事件的 from" 断过一次，重放完当前值必然等于 `to`，
    再断一遍是同义反复。**真正会悄悄漂开的是未发生事件那一侧**：
    别的事件改了同一个参数，某张中检点卡的 `from` 就停在了旧世界，
    于是它算出来的"若兑现值多少"是相对一个已经不存在的现状说的。
    """
    bad = []
    for ev in events:
        if ev.kind == "已发生":
            continue
        for c in ev.changes:
            cur = get_path(config, c.param)
            cur = cur["v"] if isinstance(cur, dict) and "v" in cur else cur
            if abs(float(cur) - c.frm) > 1e-9:
                bad.append(f"  事件 {ev.id}：登记 from={c.frm}，而 {c.param} 当前值={cur}"
                           f"——这张卡的差分是相对一个已经不存在的现状算的")
    if bad:
        raise SystemExit(
            "未发生事件的起点与当前值不一致：\n" + "\n".join(bad)
            + "\n把 from 更新到当前值（差分口径随之改变，请顺便复核 why 还成不成立）。"
        )


def impact(config: dict, events: list[Event], build: Callable, read: Callable) -> list[dict]:
    """每个事件值多少钱。

    · 已发生 → 把参数**退回** `from` 再跑一次，差额＝这个事件带来的价值。
    · 预期／中检点 → 把参数**推进到** `to` 再跑一次，差额＝若兑现值多少。
    """
    base = read(build(cloned_config(config)))
    rows = []
    for ev in events:
        cfg = cloned_config(config)
        for c in ev.changes:
            _set_path(cfg, c.param, c.frm if ev.kind == "已发生" else c.to)
        alt = read(build(cfg))
        rows.append({
            "id": ev.id, "kind": ev.kind, "date": ev.date, "title": ev.title,
            "base": base, "alt": alt,
            "delta": (base - alt) if ev.kind == "已发生" else (alt - base),
            "why": ev.why, "src": ev.src, "trigger": ev.trigger,
            "changes": [(c.param, c.frm, c.to) for c in ev.changes],
        })
    return rows


def print_events(rows: list[dict], unit: str = "亿元") -> None:
    if not rows:
        print("\n（事件表为空）")
        return
    print("\n" + "═" * 76)
    print("事件表 · 参数是怎么变成现在这样的，以及每一次变动值多少钱")
    print("═" * 76)
    for r in rows:
        verb = "已带来" if r["kind"] == "已发生" else "若兑现"
        print(f"  [{r['kind']}] {r['date']}　{r['title']}")
        for p, a, b in r["changes"]:
            print(f"      {p}：{a} → {b}")
        print(f"      **{verb} {r['delta']:+,.1f} {unit}**"
              f"（对照：{r['alt']:,.1f} → {r['base']:,.1f}）")
        if r.get("trigger"):
            print(f"      触发条件：{r['trigger']}")
        print(f"      因为：{r['why']}")
    print("─" * 76)
    happened = sum(r["delta"] for r in rows if r["kind"] == "已发生")
    pending = sum(r["delta"] for r in rows if r["kind"] != "已发生")
    print(f"  已发生事件累计贡献 {happened:+,.1f} {unit}；"
          f"未兑现事件合计 {pending:+,.1f} {unit}（＝中检点的量化形态）")

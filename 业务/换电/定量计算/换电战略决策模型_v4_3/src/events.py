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

from config_loader import (cloned_config, get_path, _set_path,
                           apply_timed_changes, timed_effect_weights, _model_years)

KINDS = ("已发生", "预期", "中检点")


@dataclass
class Change:
    param: str
    frm: float
    to: float


@dataclass
class TimedChange:
    """数据驱动事件的参数扰动：效应大小是固定的，生效节奏由达标月决定。

    · kind="delta"：逐年序列（如 nev_rates），达标年按剩余月份加权、次年起全效；
    · kind="set"  ：标量（如兑现年后延长段的 nev_ceiling），窗口内达标即整体切换。
    """
    param: str
    kind: str
    full_delta: float | None = None
    frm: float | None = None
    to: float | None = None

    def as_raw(self) -> dict[str, Any]:
        """转回 apply_timed_changes 消费的 TOML 原表。"""
        if self.kind == "delta":
            return {"param": self.param, "type": "delta", "full_delta": self.full_delta}
        return {"param": self.param, "type": "set", "from": self.frm, "to": self.to}


@dataclass
class Event:
    id: str
    date: str
    kind: str
    title: str
    why: str
    src: str = ""
    trigger: str = ""          # 未发生事件必填：凭什么说它发生了（人话）
    changes: list[Change] = field(default_factory=list)
    # 数据驱动的中检点：track＝机器可读触发条件（指向 audit/tracking_*.json），
    # timed_changes＝达标后按月加权的参数扰动。与 changes 互斥。
    track: dict[str, Any] | None = None
    timed_changes: list[TimedChange] = field(default_factory=list)


def load_events(config: dict) -> list[Event]:
    """读 [[event]] 并硬校验。缺字段直接中断——事件是判断，不许含糊登记。"""
    out: list[Event] = []
    seen: set[str] = set()
    for i, raw in enumerate(config.get("event", []) or []):
        for k in ("id", "date", "kind", "title", "why"):
            if k not in raw:
                raise SystemExit(f"[[event]] 第 {i+1} 张卡缺字段 {k!r}")
        if raw["kind"] not in KINDS:
            raise SystemExit(f"[[event]] {raw['id']} 的 kind 必须是 {KINDS} 之一")
        if raw["id"] in seen:
            raise SystemExit(f"[[event]] id 重复：{raw['id']}")
        seen.add(raw["id"])

        track = raw.get("track")
        tcs_raw = raw.get("timed_changes")
        if track is not None:
            ev = _load_tracked_event(raw, track, tcs_raw)
            out.append(ev)
            continue

        if "changes" not in raw:
            raise SystemExit(f"[[event]] {raw['id']} 缺字段 'changes'（或改用 track+timed_changes）")
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


def _load_tracked_event(raw: dict, track: dict, tcs_raw: list[dict] | None) -> Event:
    """解析并硬校验一张「数据驱动的中检点」卡。"""
    eid = raw["id"]
    if raw["kind"] == "已发生":
        raise SystemExit(
            f"[[event]] {eid} 带 track 却标成「已发生」——数据驱动事件的发生与否"
            "只能由跟踪数据判定，不许人手标已发生（要表达既成事实，去掉 track 用 changes）")
    if raw.get("changes"):
        raise SystemExit(f"[[event]] {eid} 的 track 与 changes 互斥：时序冲击只能写在 timed_changes")
    for k in ("source", "field", "op", "value"):
        if k not in track:
            raise SystemExit(f"[[event]] {eid} 的 track 缺字段 {k!r}"
                             "（需要 source/field/op/value，例："
                             '{source="methanol", field="ratio", op="<=", value=1.3}）')
    if not tcs_raw:
        raise SystemExit(f"[[event]] {eid} 有 track 却没有 timed_changes——"
                         "达标后改哪些参数、幅度多少，必须登记在案")
    tcs: list[TimedChange] = []
    for c in tcs_raw:
        if "param" not in c or "type" not in c:
            raise SystemExit(f"[[event]] {eid} 的 timed_changes 每项需要 param 与 type")
        if c["type"] == "delta":
            if "full_delta" not in c:
                raise SystemExit(f"[[event]] {eid} 的 delta 型 timed_change 缺 full_delta")
            tcs.append(TimedChange(param=c["param"], kind="delta",
                                   full_delta=float(c["full_delta"])))
        elif c["type"] == "set":
            for k in ("from", "to"):
                if k not in c:
                    raise SystemExit(f"[[event]] {eid} 的 set 型 timed_change 缺 {k!r}")
            tcs.append(TimedChange(param=c["param"], kind="set",
                                   frm=float(c["from"]), to=float(c["to"])))
        else:
            raise SystemExit(f"[[event]] {eid} 的 timed_change type={c['type']!r} 不支持"
                             "（只支持 delta／set）")
    return Event(id=eid, date=str(raw["date"]), kind=raw["kind"],
                 title=raw["title"], why=raw["why"], src=raw.get("src", ""),
                 trigger=str(raw.get("trigger", "")), track=dict(track), timed_changes=tcs)


def assert_current(config: dict, events: list[Event]) -> None:
    """**未发生**事件的 `from` 必须等于参数的当前值（＝重放之后的值）。

    已发生事件不在这里查——`config_loader.replay_events` 在重放时已经把
    "base.toml 的初值 == 事件的 from" 断过一次，重放完当前值必然等于 `to`，
    再断一遍是同义反复。**真正会悄悄漂开的是未发生事件那一侧**：
    别的事件改了同一个参数，某张中检点卡的 `from` 就停在了旧世界，
    于是它算出来的"若兑现值多少"是相对一个已经不存在的现状说的。

    数据驱动事件（track）只对 set 型扰动做对齐：未达标时当前值必须＝from，
    已达标（replay 已自动切换）时必须＝to；delta 型作用于逐年序列，无单一起点可对。
    """
    import tracker
    bad = []
    for ev in events:
        if ev.kind == "已发生":
            continue
        if ev.track is not None:
            st = tracker.track_status(ev.track)
            for tc in ev.timed_changes:
                if tc.kind != "set":
                    continue
                cur = float(get_path(config, tc.param))
                expect = float(tc.to if st["triggered_ym"] else tc.frm)
                if abs(cur - expect) > 1e-9:
                    state = f"已于 {st['triggered_ym']} 触发，应为 to={expect}" if st["triggered_ym"] \
                            else f"未触发，应为 from={expect}"
                    bad.append(f"  事件 {ev.id}：{tc.param} 当前值={cur}（{state}）")
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


def _fmt_arr(arr: list) -> str:
    """逐年序列紧凑成 [.35 .41 .48 .54 .59] 供事件表展示。"""
    return "[" + " ".join(f"{float(x):.2f}" for x in arr) + "]"


def impact(config: dict, events: list[Event], build: Callable, read: Callable) -> list[dict]:
    """每个事件值多少钱。

    · 已发生 → 把参数**退回** `from` 再跑一次，差额＝这个事件带来的价值。
    · 预期／中检点 → 把参数**推进到** `to` 再跑一次，差额＝若兑现值多少。
    · 数据驱动（track）→ 见 _impact_tracked：是否已发生由月度跟踪数据判定，
      效应按达标月加权，两个方向的反事实都从同一规则推导。
    """
    base = read(build(cloned_config(config)))
    rows = []
    for ev in events:
        if ev.track is not None:
            rows.append(_impact_tracked(config, ev, build, read, base))
            continue
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


def _impact_tracked(config: dict, ev: Event, build: Callable,
                    read: Callable, base: float) -> dict:
    """数据驱动事件的价值差分。

    · 已达标（replay 已把效应织入当前 config）：反事实＝按同一触发月**精确撤回**，
      delta＝base-alt＝它迄今已带来的价值；
    · 未达标：反事实＝假设在**最新跟踪月即刻达标**（"若此刻达标值多少"的中检点量化），
      delta＝alt-base；最新月已在兑现年之后则窗口内加权全为 0、delta=0——
      兑现年后达标只影响延长段，当前不计价、仅用于解释估值倍数。
    """
    import tracker
    years = _model_years(config)
    raws = [tc.as_raw() for tc in ev.timed_changes]
    st = tracker.track_status(ev.track)
    triggered = bool(st["triggered_ym"])
    eff_ym = st["triggered_ym"] or st["latest_ym"]

    cfg = cloned_config(config)
    applied = False
    if eff_ym:
        applied = apply_timed_changes(
            cfg, raws, eff_ym, years, sign=(-1.0 if triggered else 1.0))
    alt = read(build(cfg))
    delta = (base - alt) if triggered else (alt - base)

    weights = (timed_effect_weights(eff_ym, years)
               if (eff_ym and applied) else {y: 0.0 for y in years})
    chg = []
    for tc in ev.timed_changes:
        if tc.kind == "delta":
            before = get_path(config, tc.param)
            chg.append((tc.param, _fmt_arr(before),
                        f"全效 {tc.full_delta:+.2f}/年·按达标月加权（见生效节奏）"))
        else:
            chg.append((tc.param, tc.frm, tc.to))
    return {
        "id": ev.id, "kind": ev.kind, "date": ev.date, "title": ev.title,
        "base": base, "alt": alt, "delta": delta,
        "why": ev.why, "src": ev.src, "trigger": ev.trigger,
        "changes": chg,
        "tracked": True,
        "track": {
            "source": st["source"], "field": st["field"], "op": st["op"],
            "threshold": st["threshold"],
            "latest_ym": st["latest_ym"], "latest_value": st["latest_value"],
            "triggered_ym": st["triggered_ym"],
            "effective_ym": eff_ym,                 # 本次反事实采用的生效月
            "in_window": bool(applied),
            "weights": {str(y): round(float(w), 4) for y, w in weights.items()},
        },
    }


def print_events(rows: list[dict], unit: str = "亿元") -> None:
    if not rows:
        print("\n（事件表为空）")
        return
    print("\n" + "═" * 76)
    print("事件表 · 参数是怎么变成现在这样的，以及每一次变动值多少钱")
    print("═" * 76)
    for r in rows:
        if r.get("tracked"):
            t = r["track"]
            if t["triggered_ym"]:
                head = (f"[{r['kind']}·数据跟踪] {r['date']}　{r['title']}\n"
                        f"      ★ 已于 {t['triggered_ym']} 达标自动生效（{t['field']} "
                        f"{t['latest_value']:g}{t['op']}{t['threshold']:g}）")
                verb = "已带来"
            else:
                head = (f"[{r['kind']}·数据跟踪] {r['date']}　{r['title']}\n"
                        f"      ◷ 跟踪中：{t['latest_ym']} 实测 {t['latest_value']:g}×"
                        f"（触发线 {t['op']} {t['threshold']:g}×）——窗口内当前零影响；"
                        f"兑现年后才达标只影响延长段（仅解释倍数，不计价）")
                verb = f"若 {t['latest_ym']} 即刻达标"
            print("  " + head)
            for p, a, b in r["changes"]:
                print(f"      {p}：{a} → {b}")
            sched = "、".join(f"{y}×{w:g}" for y, w in t["weights"].items() if w)
            print(f"      生效节奏：{sched or '窗口内不生效'}"
                  f"（达标当月观察、次月起车队转向，当年只压剩余月份）")
            print(f"      **{verb} {r['delta']:+,.1f} {unit}**"
                  f"（对照：{r['alt']:,.1f} → {r['base']:,.1f}）")
            print(f"      因为：{r['why']}")
            continue
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
    def _is_realized(r: dict) -> bool:
        """已兑现：普通已发生事件，或数据跟踪事件已被月度实测触发。"""
        return r["kind"] == "已发生" or bool(r.get("track", {}).get("triggered_ym"))
    happened = sum(r["delta"] for r in rows if _is_realized(r))
    pending = sum(r["delta"] for r in rows if not _is_realized(r))
    print(f"  已兑现事件累计贡献 {happened:+,.1f} {unit}；"
          f"未兑现事件合计 {pending:+,.1f} {unit}（＝中检点的量化形态）")

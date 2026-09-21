from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any


# v4.3 目录布局：src/ 存计算程序，configs/ 与 MANIFEST.md 在其上一级
ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT.parent / "configs" / "base.toml"


def load_config_raw(path: Path | None = None) -> dict[str, Any]:
    """只读 TOML 原文、**不解信封**：信封的呈现要素（label/unit/note…）只能从这里取。

    普通取参一律用 load_config()（返回值与历史完全同构：叶子全是裸标量）；
    只有 lab.py 注册输入参数名片时需要本函数，沿原文树发现信封并读其元数据。
    """
    config_path = path or DEFAULT_CONFIG
    with config_path.open("rb") as handle:
        return tomllib.load(handle)


def _unwrap_envelopes(node: Any) -> Any:
    """递归把「参数信封」解成裸标量。

    信封＝含 ``v`` 键的子表：``{"v": 0.075, "label": "WACC", ...}`` → ``0.075``。
    判定只认 ``v`` 键（[vehicles.heavy] 本就有业务键 label，靠"其余键是元数据"判会误杀）。
    configs/ 全目录经 grep 确认无任何存量 ``v`` 键，故该判定不会误伤；
    信封的 label 必填闸在 lab.load_envelopes（防止误写 v 键被静默注册）。
    """
    if isinstance(node, dict):
        if "v" in node:
            return node["v"]
        return {k: _unwrap_envelopes(child) for k, child in node.items()}
    if isinstance(node, list):
        return [_unwrap_envelopes(child) for child in node]
    return node


def load_config(path: Path | None = None) -> dict[str, Any]:
    """读配置并解信封：对所有既有消费方，``cfg["finance"]["wacc"]`` 仍是 0.075。

    就地信封化（2026-09-13 再改）后，参数值与呈现要素同住一个虚线子表
    （base.toml 里写 ``wacc.v = 0.075`` / ``wacc.label = "WACC"``），
    本函数在加载时统一还原为标量树——模型、driver 拨档、浏览器 Pyodide 全部零改动同源。
    """
    cfg = _unwrap_envelopes(load_config_raw(path))
    replay_events(cfg)
    _assert_crf_is_derived(cfg)
    _assert_charge_fee_is_derived(cfg)
    return cfg


def _assert_charge_fee_is_derived(cfg: dict[str, Any]) -> None:
    """【2026-09-21 · 门①】充电服务费基准必须等于 [charging_station] 成本曲线推出的均衡价。

    和 CRF 同一个道理：这个数是推论，不是第二个拍值。想改它，改它的来源（利用率、造价、WACC）。
    只在加载基线时校验；情景三档会把利用率与两个服务费一起拨动，那是 [drivers.fee_level] 的事。
    """
    tco = cfg.get("tco_jpm") or {}
    if "charge_service_fee_rmb_kwh" not in tco or not cfg.get("charging_station"):
        return
    from charging import equilibrium_service_fee   # 局部引入：避免装载期循环依赖
    want = equilibrium_service_fee(cfg)["equilibrium_fee"]
    have = float(tco["charge_service_fee_rmb_kwh"])
    if abs(have - want) > 5e-4:
        raise SystemExit(
            f"[tco_jpm] charge_service_fee_rmb_kwh={have} 与 [charging_station] 成本曲线推出的均衡价 "
            f"{want:.4f} 不符。**它是推论不是拍值**——要改就改利用率、造价或 WACC。")


def replay_events(cfg: dict[str, Any]) -> list[str]:
    """把 base.toml 里的**初值**按事件表重放成**当前值**。返回重放过的事件 id。

    【2026-09-15·A9 重放版】此前 base.toml 直接存并购后的 0.80，事件表另存一行
    `from=0.30, to=0.80`，靠一条断言 `to == 当前值` 维持一致。那是**账本与账实各记一遍**：
    断言只能发现它们不一致，不能说明谁对。

    现在倒过来——**base.toml 只存初值，当前值是推出来的**：
      · 参数的"初值"有且只有一个家（base.toml）；
      · "它后来怎么变成现在这样"有且只有一个家（事件表）；
      · **当前值不再有家，它是两者的函数。** 想改当前值，只能补一张事件卡。
    这条路堵死了"看到并购就顺手把参数改了"——那正是把结论写进输入。

    断言也跟着变了向：重放前 base.toml 的值必须等于事件的 `from`。
    有人直接把 base 改成并购后的数，这里当场中断。

    【2026-09-16】再增一类「数据驱动的中检点」：带 track 的事件不预设发生年，
    生效月由 audit/tracking_<source>.json 的月度实测自动判定（首个达标月），
    参数按 timed_changes 逐月加权织入——见 apply_timed_changes。
    """
    events = cfg.get("event") or []
    done: list[str] = []
    for raw in sorted(events, key=lambda e: str(e.get("date", ""))):
        if raw.get("kind") != "已发生":
            continue
        for c in raw.get("changes", []) or []:
            cur = get_path(cfg, c["param"])
            cur = cur["v"] if isinstance(cur, dict) and "v" in cur else cur
            if abs(float(cur) - float(c["from"])) > 1e-9:
                raise SystemExit(
                    f"事件重放失败：{c['param']} 在 base.toml 里是 {cur}，"
                    f"而事件 {raw.get('id')} 登记的初值是 {c['from']}。\n"
                    "**base.toml 只存初值，当前值由事件重放派生**——"
                    "要表达一个新的变动，补一张 [[event]] 卡，不要直接改这个数。")
            _set_path(cfg, c["param"], float(c["to"]))
        done.append(str(raw.get("id")))

    # ── 数据驱动的中检点：track 声明 + 月度跟踪 JSON，达标月自动生效（不预测、不手填）
    for raw in events:
        spec = raw.get("track")
        if not spec:
            continue
        import tracker  # lazy：tracker 模块级不依赖本模块，无循环
        st = tracker.track_status(spec)
        if not st["triggered_ym"]:
            continue                # 截至最新月从未达标：窗口内零影响，参数一个都不动
        if apply_timed_changes(cfg, raw.get("timed_changes", []) or [],
                               st["triggered_ym"], _model_years(cfg)):
            done.append(f"{raw.get('id')}@{st['triggered_ym']}")
    return done


def _model_years(cfg: dict[str, Any]) -> list[int]:
    """模型窗口年序列（优先 construction.years，缺失时按兑现年回推五年）。"""
    years = (cfg.get("construction") or {}).get("years")
    if years:
        return [int(y) for y in years]
    tgt = int(cfg.get("target_year", 2030))
    return list(range(tgt - 4, tgt + 1))


def timed_effect_weights(trigger_ym: str, years: list[int]) -> dict[int, float]:
    """外部价格在 ``trigger_ym``（YYYY-MM）达标时，各日历年的参数生效权重。

    口径＝**只影响达标时点之后**（当月月底才观察到价格，车队采购从次月起转向）：
      · 触发年之前：0（事件不追溯）；
      · 触发当年：(12 - m)/12 —— 6 月达标 → 只压 7–12 月 → 权重 0.5；
      · 次年起：1（全效）。
    例：2030-06 达标 → 2030 权重 0.5；2030-12 达标 → 2030 权重 0、2031 起全效。
    """
    ty, tm = int(trigger_ym[:4]), int(trigger_ym[5:7])
    out: dict[int, float] = {}
    for y in (int(v) for v in years):
        out[y] = 0.0 if y < ty else (max(0.0, (12 - tm) / 12.0) if y == ty else 1.0)
    return out


def apply_timed_changes(cfg: dict[str, Any], changes: list[dict[str, Any]],
                        trigger_ym: str, years: list[int], sign: float = 1.0) -> bool:
    """按生效月在 cfg 上织入（sign=1）或精确撤销（sign=-1）一组时序冲击。

    触发年晚于窗口末年 → 一律不动：**兑现年之后才达标只影响兑现年后的延长段，
    当前窗口内不计价（delta=0），该效应仅用于解释估值倍数**。
    每条 timed_change（TOML 原表）：
      · ``{param, type="delta", full_delta=-0.15}``：逐年序列按年权重加减，钳 [0,1]；
      · ``{param, type="set", from=0.80, to=0.65}``：窗口内触发即整体切换
        （这类参数只作用于兑现年后延长段，窗口内触发后延长段必为全效）。
    """
    years = [int(y) for y in years]
    if int(trigger_ym[:4]) > years[-1]:
        return False
    weights = timed_effect_weights(trigger_ym, years)
    for c in changes:
        p = c["param"]
        if c.get("type", "delta") == "delta":
            arr = get_path(cfg, p)
            d = float(c["full_delta"])
            for i, y in enumerate(years):
                if i < len(arr):
                    arr[i] = min(1.0, max(0.0, float(arr[i]) + sign * d * weights[y]))
        else:
            _set_path(cfg, p, float(c["to"] if sign > 0 else c["from"]))
    return True


def _assert_crf_is_derived(cfg: dict[str, Any]) -> None:
    """CRF 必须等于 WACC 在运营年限上的年金因子——它是推论，不是第二个拍值。

    【2026-09-15·A8】此前 CRF 独立拍 0.15（隐含要求回报 12.4%），而现金流按 WACC 7.5% 折现。
    **同一个模型里出现了两个"资本的价格"**：模型自己算出来的 EV 用的是一个它在门那里
    不认可的折现率。断言把这个口子焊死——想改门槛只有一个入口，就是改 WACC。
    """
    fin = cfg.get("finance") or {}
    wacc = fin.get("wacc"); n = fin.get("model_horizon_years"); crf = fin.get("capital_recovery_factor")
    if wacc is None or n is None or crf is None:
        return
    n = int(n)
    want = wacc / (1.0 - (1.0 + wacc) ** -n)
    if abs(crf - want) > 5e-4:
        raise SystemExit(
            f"[finance] capital_recovery_factor={crf} 与 WACC {wacc:.4f}／运营年限 {n} 年"
            f"推出的 {want:.4f} 不符。**CRF 是推论不是拍值**——要改门槛就改 WACC，"
            "不要直接改这个数（理由见 base.toml 该字段上方注释）。")


def cloned_config(config: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(config)


# ─────────────────────────────────────────── 情景驱动因子
# 情景定义只有一个家：configs/base.toml 的 [drivers] 段。
# 原 tree.py 里的 SCENARIOS 常量是第二个家（硬编码了服务费/份额/私家车/净利率四档），
# 已删除——见 DECISIONS「2026-09-02 · 「三情景」名不副实」。
SCENARIO_ORDER: tuple[str, ...] = ("悲观", "中性", "乐观")


# 不可作"可调参数"扫描的 config 段（情景轴/元数据/事实台账）。
# lab.iter_numeric_params 与 parameter_registry 同口径复用——情景轴走三档切换，
# 不进单参数 +10% 扰动，也不混进"可调参数"清单。
_SKIP_SECTIONS = (
    "sources",
    "external_quote",
    "capital_commitments",
    "mna.scenarios",
    "drivers",
    "charge_share",
    "sensitivity",
    "param_bounds",
    "nio_reference",
    "reits_reference",
    "qiyuan_reference",
    "battery_life_model.legacy_v32",
)


def load_drivers(config: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """取并校验 [drivers] 段。缺段/缺档/缺落点直接报错，不静默降级。"""
    drivers = config.get("drivers")
    if not drivers:
        raise SystemExit(
            "base.toml 缺少 [drivers] 段。情景定义必须有且只有一个家；\n"
            "详见 DECISIONS「2026-09-02 · 「三情景」名不副实」。"
        )
    for name, spec in drivers.items():
        if not isinstance(spec, dict):
            raise SystemExit(f"[drivers.{name}] 必须是一张表")
        for tier in SCENARIO_ORDER:
            if tier not in spec:
                raise SystemExit(f"[drivers.{name}] 缺少「{tier}」档")
        has_target = "target" in spec or "targets" in spec
        if not has_target and "pass_as" not in spec:
            raise SystemExit(
                f"[drivers.{name}] 必须声明 target / targets（config 点分路径）"
                f"或 pass_as（build_model 关键字参数）"
            )
        # 【2026-09-13e】每条轴必须显式声明进不进三情景，缺了直接报错——
        # 新增一条 driver 时被迫做这个判断，而不是默认进轴、悄悄把区间撑宽。
        if "scenario_axis" not in spec:
            raise SystemExit(
                f"[drivers.{name}] 缺少 scenario_axis（true/false）。\n"
                f"判据：三情景轴只装「我不知道会怎样」的经营不确定性；\n"
                f"「我自己能选的」（资本结构）与「市场怎么定价」（倍数）填 false，"
                f"并写 off_axis_reason 说明它归哪一章处理。"
            )
        if not isinstance(spec["scenario_axis"], bool):
            raise SystemExit(f"[drivers.{name}] scenario_axis 必须是 true/false")
        if not spec["scenario_axis"] and not spec.get("off_axis_reason"):
            raise SystemExit(
                f"[drivers.{name}] scenario_axis=false 必须同时写 off_axis_reason——"
                f"把一条轴移出三情景是一个判断，不许静默"
            )
        if spec.get("mode") == "relative" and spec.get("中性") != 1.0:
            raise SystemExit(f"[drivers.{name}] relative 模式中性档必须为 1.0（不动基线）")
        # 档位必须落在 bounds 内：否则沙盘滑块够不到自己的某一档（档位是区间内的两个点）。
        b = spec.get("bounds")
        if isinstance(b, (list, tuple)) and len(b) == 2:
            lo, hi = float(b[0]), float(b[1])
            for tier in SCENARIO_ORDER:
                v = spec.get(tier)
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    continue      # 向量档（dict）／路由档（str）不适用
                if not lo <= v <= hi:
                    raise SystemExit(
                        f"[drivers.{name}] 的「{tier}」档（{v}）落在 bounds（[{lo}, {hi}]）之外。\n"
                        f"档位必须落在区间内——请放宽 bounds 到能容纳三档，或把档位收回区间内。"
                    )
    return drivers


def _walk(node: Any, key: str) -> Any:
    return node[int(key)] if isinstance(node, list) and key.isdigit() else node[key]


def _walk_set(node: Any, key: str, value: Any) -> None:
    if isinstance(node, list) and key.isdigit():
        node[int(key)] = value
    else:
        node[key] = value


def get_path(config: dict[str, Any], path: str) -> Any:
    node: Any = config
    for key in path.split("."):
        node = _walk(node, key)
    return node


def _set_path(config: dict[str, Any], path: str, value: Any) -> None:
    node: Any = config
    keys = path.split(".")
    for key in keys[:-1]:
        node = _walk(node, key)
    _walk_set(node, keys[-1], value)


def _apply_factor(base: Any, factor: float) -> Any:
    """relative 模式：标量直接乘；列表逐元素乘（用于 nev_rates 这类 S 曲线数组）。"""
    if isinstance(base, list):
        return [x * factor for x in base]
    return base * factor


def _apply_cap(value: Any, cap: float | None) -> Any:
    """上限钳制：标量直接钳；列表逐元素钳（份额/渗透率不得 >1）。"""
    if cap is None:
        return value
    if isinstance(value, list):
        return [min(x, cap) for x in value]
    return min(value, cap)


def _scene_name(config: dict[str, Any], target: str) -> str | None:
    """落点是「...scenes.<i>.<字段>」时，返回该场景的 name；否则 None。

    供向量型情景按场景名取分量（私家车三档渗透率的分量键＝价格带）。
    """
    parts = target.split(".")
    for i, part in enumerate(parts[:-1]):
        if part == "scenes" and i + 1 < len(parts) and parts[i + 1].isdigit():
            try:
                node: Any = config
                for p in parts[: i + 2]:
                    node = _walk(node, p)
            except (KeyError, IndexError, TypeError):
                return None
            if isinstance(node, dict) and isinstance(node.get("name"), str):
                return node["name"]
    return None


def apply_scenario(
    config: dict[str, Any],
    drivers: dict[str, dict[str, Any]],
    tier: str,
    check_neutral: bool = True,
) -> dict[str, Any]:
    """把某一档的 driver 取值落进 config（原地修改，调用方需先 cloned_config）。

    返回需要传给 build_model 的关键字参数（pass_as 型 driver 不落 config，
    避免与参数本体形成第二个家）。

    中性档额外做一条报警：driver 的中性值必须等于参数本体的当前值——
    中性档严格等于模型基线，两边不一致说明有人在改一个数而没改另一个。
    """
    if tier not in SCENARIO_ORDER:
        raise SystemExit(f"未知情景档位 {tier!r}，应为 {SCENARIO_ORDER}")
    kwargs: dict[str, Any] = {}
    for name, spec in drivers.items():
        # 【2026-09-13e】非情景轴固定在中性：仍走完整流程（中性档=基线的断言对全部 13 条
        # 都要成立），只是不随档位摆动。它们改由沙盘单参数滑块单独拨。
        tier_eff = tier if spec.get("scenario_axis", True) else "中性"
        value = spec[tier_eff]
        if "pass_as" in spec:
            kwargs[spec["pass_as"]] = value
            continue
        mode = spec.get("mode", "absolute")
        cap = spec.get("cap")
        targets = spec["targets"] if "targets" in spec else [spec["target"]]
        if isinstance(value, dict):
            # 向量型情景：每个 target 取 value 中同名分量。分量键的取法：
            #   · 落点是 [[scenes]].N.field → 用场景自己的 name（如私家车价格带"8至15万元"）；
            #   · 否则用末级键（如 charge_share 的 heavy/city/…）。
            # 前者解决"同一段 targets 末级键全部相同（swap_penetration）"的分量对位。
            for target in targets:
                leaf = target.split(".")[-1]
                comp = value[_scene_name(config, target) or leaf]
                if check_neutral and tier_eff == "中性":
                    current = get_path(config, target)
                    if current != comp:
                        raise SystemExit(
                            f"[drivers.{name}] 的中性档分量（{target}={comp!r}）"
                            f"与当前值（{current!r}）不一致。\n"
                            f"中性档必须严格等于模型基线——请改参数本体的值，不要改 [drivers] 的中性档。"
                        )
                _set_path(config, target, comp)
            continue
        for target in targets:
            if mode == "relative":
                if check_neutral and tier_eff == "中性":
                    continue  # 中性档=1.0，乘 1.0 即不动基线
                base = get_path(config, target)
                new = _apply_factor(base, value)
            else:
                if check_neutral and tier_eff == "中性":
                    current = get_path(config, target)
                    if current != value:
                        raise SystemExit(
                            f"[drivers.{name}] 的中性档（{value!r}）与 {target} 当前值（{current!r}）不一致。\n"
                            f"中性档必须严格等于模型基线——请改参数本体的值，不要改 [drivers] 的中性档。"
                        )
                new = value
            _set_path(config, target, _apply_cap(new, cap))
    return kwargs


def parameter_registry(config: dict[str, Any]) -> list[dict[str, Any]]:
    """为后续Dashboard输出扁平化参数表；列表/场景保持为一个可编辑对象。

    跳过 _SKIP_SECTIONS（sources/资本台账/情景声明charge_share等），
    与 iter_numeric_params 口径一致——情景轴不进"可调参数"清单。
    """
    rows: list[dict[str, Any]] = []

    def _skip(prefix: str) -> bool:
        return any(prefix == s or prefix.startswith(s + ".") for s in _SKIP_SECTIONS)

    def walk(prefix: str, value: Any) -> None:
        if _skip(prefix):
            return
        if isinstance(value, dict):
            for key, child in value.items():
                walk(f"{prefix}.{key}" if prefix else key, child)
        elif isinstance(value, list):
            rows.append({"key": prefix, "value": value, "type": "list"})
        else:
            rows.append({"key": prefix, "value": value, "type": type(value).__name__})

    walk("", config)
    return rows


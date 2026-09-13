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
    return _unwrap_envelopes(load_config_raw(path))


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
        value = spec[tier]
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
                if check_neutral and tier == "中性":
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
                if check_neutral and tier == "中性":
                    continue  # 中性档=1.0，乘 1.0 即不动基线
                base = get_path(config, target)
                new = _apply_factor(base, value)
            else:
                if check_neutral and tier == "中性":
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


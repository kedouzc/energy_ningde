from __future__ import annotations

import copy
import tomllib
from pathlib import Path
from typing import Any


# v4.3 目录布局：src/ 存计算程序，configs/ 与 MANIFEST.md 在其上一级
ROOT = Path(__file__).resolve().parent
DEFAULT_CONFIG = ROOT.parent / "configs" / "base.toml"


def load_config(path: Path | None = None) -> dict[str, Any]:
    config_path = path or DEFAULT_CONFIG
    with config_path.open("rb") as handle:
        return tomllib.load(handle)


def cloned_config(config: dict[str, Any]) -> dict[str, Any]:
    return copy.deepcopy(config)


# ─────────────────────────────────────────── 情景驱动因子
# 情景定义只有一个家：configs/base.toml 的 [drivers] 段。
# 原 tree.py 里的 SCENARIOS 常量是第二个家（硬编码了服务费/份额/私家车/净利率四档），
# 已删除——见 DECISIONS「2026-09-02 · 「三情景」名不副实」。
SCENARIO_ORDER: tuple[str, ...] = ("悲观", "中性", "乐观")


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
    """为后续Dashboard输出扁平化参数表；列表/场景保持为一个可编辑对象。"""
    rows: list[dict[str, Any]] = []

    def walk(prefix: str, value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                walk(f"{prefix}.{key}" if prefix else key, child)
        elif isinstance(value, list):
            rows.append({"key": prefix, "value": value, "type": "list"})
        else:
            rows.append({"key": prefix, "value": value, "type": type(value).__name__})

    walk("", config)
    return rows


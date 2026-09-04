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


"""模型实验室：给"不写代码但要改模型"的人准备的追踪器。

解决的问题
----------
模型拆成 configs/src/outputs 三件套后，参数改一个值，人看不出它影响了谁。
Excel 里这件事由"追踪引用单元格/从属单元格"解决；本模块用**实测**解决：

    改一个参数 → 重跑同一条计算链 → 对比全部指标

血缘关系因此不是人工登记的注释，而是每次跑出来的真值，模型改版不会失效。

命令
----
    python src/lab.py list                      列出全部可调数值参数（值 + 一句话理由 + 锚点）
    python src/lab.py impact <参数路径> <新值>   改这一个参数，看所有指标怎么动
    python src/lab.py impact <参数路径> +10%     同上，按相对幅度调
    python src/lab.py lineage <指标键>           追溯：哪些参数在影响这个指标、影响多大
    python src/lab.py scan                      全参数扫描 → 敏感性矩阵 + 关键参数排序

输出一律 UTF-8；所有列表先打印"怎么用"再打印结果。
"""
from __future__ import annotations

import copy
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import DEFAULT_CONFIG, ROOT, load_config  # noqa: E402
from model import _build_core  # noqa: E402
from schemas import ModelSnapshot  # noqa: E402

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    Workbook = None
else:
    HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
    HEADER_FONT = Font(bold=True, color="FFFFFF")
    EDIT_FILL = PatternFill("solid", fgColor="DDEBF7")
    BLOCK_FILL = PatternFill("solid", fgColor="F2F2F2")
    WRAP = Alignment(vertical="top", wrap_text=True)

    def style_header(ws, row_index: int, ncols: int) -> None:
        for col in range(1, ncols + 1):
            cell = ws.cell(row=row_index, column=col)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.freeze_panes = ws.cell(row=row_index + 1, column=1)

    def set_widths(ws, widths: list[int]) -> None:
        for index, width in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(index)].width = width

# ══════════════════════════════════════════════════════════════════════
# 一、参数路径工具（支持 "vehicles.heavy.battery_kwh" 这类点分路径）
# ══════════════════════════════════════════════════════════════════════

_SKIP_SECTIONS = (
    "sources",              # 全是 URL
    "capital_commitments",  # 交易台账，非可调假设
    "mna.scenarios",        # 情景卡片，整体切换而非逐参数调
    "nio_reference",        # 参照公司事实数据
    "reits_reference",
    "qiyuan_reference",
    "battery_life_model.legacy_v32",  # 遗留对照口径
)


def get_path(config: dict, path: str) -> Any:
    node: Any = config
    for part in path.split("."):
        node = node[part]
    return node


def set_path(config: dict, path: str, value: Any) -> None:
    parts = path.split(".")
    node: Any = config
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def iter_numeric_params(config: dict) -> list[tuple[str, float]]:
    """扁平列出全部可调的数值参数，跳过开关/字符串/URL/事实台账。"""
    out: list[tuple[str, float]] = []

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                walk(f"{prefix}.{key}" if prefix else key, child)
        elif isinstance(node, list):
            pass  # 数组型（渗透率曲线等）整体替换语义不清，暂不自动扫描
        elif isinstance(node, bool):
            pass
        elif isinstance(node, (int, float)):
            if any(prefix == s or prefix.startswith(s + ".") for s in _SKIP_SECTIONS):
                return
            out.append((prefix, float(node)))

    walk("", config)
    return out


# ══════════════════════════════════════════════════════════════════════
# 二、参数档案：从 base.toml 的注释里取"为什么这么假设"
# ══════════════════════════════════════════════════════════════════════

_KEY_RE = re.compile(r'^\s*(?:\[\[?\s*([^\]]+?)\s*\]\]?|"?([^"=]+?)"?\s*=)')


def load_param_docs(path: Path = DEFAULT_CONFIG) -> dict[str, dict[str, str]]:
    """解析 base.toml，把每个键上方紧邻的注释块作为它的'一句话理由'。

    tomllib 丢弃注释，理由只能靠文本解析取回——这是唯一需要读原文的地方。
    """
    docs: dict[str, dict[str, str]] = {}
    stack: list[str] = []       # 当前表路径
    pending: list[str] = []     # 尚未归属的注释行
    array_of_tables: str | None = None

    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            stripped = line.strip()

            if not stripped:
                pending = []
                continue

            if stripped.startswith("#"):
                text = stripped.lstrip("#").strip()
                # 分隔符（──── / ┌─┐ 之类）只作视觉分节，不进理由
                if text and not re.fullmatch(r"[\s\-─=━┌┐└┘│├┤·]+", text):
                    pending.append(text)
                continue

            match = _KEY_RE.match(line)
            if not match:
                continue

            if match.group(1):  # 表头
                header = match.group(1).strip()
                if header.startswith("["):  # [[array of tables]]
                    header = header.strip("[]").strip()
                    array_of_tables = header
                    stack = [header]
                else:
                    first = header.split(".")[0]
                    if array_of_tables and first == array_of_tables and len(header.split(".")) == 1:
                        stack = [array_of_tables]
                    else:
                        array_of_tables = None
                        stack = [p.strip().strip('"') for p in header.split(".")]
                pending = []
                continue

            key = match.group(2).strip().strip('"')
            full = ".".join([*stack, key]) if stack else key
            # 理由取前两行有效注释，避免整段推导搬进来（推导在 MANIFEST）
            reason = " / ".join(pending[:2])
            docs[full] = {"reason": reason, "section": ".".join(stack)}
            pending = []

    return docs


# ══════════════════════════════════════════════════════════════════════
# 三、指标注册表：要盯住哪些结果
# ══════════════════════════════════════════════════════════════════════


class Metric:
    def __init__(self, key: str, label: str, getter: Callable[[ModelSnapshot], float],
                 decimals: int = 1, unit: str = "", group: str = ""):
        self.key = key
        self.label = label
        self.getter = getter
        self.decimals = decimals
        self.unit = unit
        self.group = group


def _daily_swaps_wan(s: ModelSnapshot) -> float:
    return sum(s.scale.mature_daily_swaps.values()) / 1e4


def _peak_cash_to_cfo(s: ModelSnapshot) -> float:
    return max((row.swap_cash_to_cfo for row in s.funding), default=0.0)


def _closing_liquidity(s: ModelSnapshot) -> float:
    return s.funding[-1].closing_liquid_resources_before_uncommitted_strategy_yi if s.funding else 0.0


# ── 存量口径 vs 流量口径（两个最容易混的口径，必须显式区分）──────────────
# 存量 = 终局在役多少（operating_stock_by_vehicle_wan）：报告 Q1 的"CATL换电车辆 351.9 万辆"。
# 流量 = 2030 当年交付多少（scale.rows[year==2030]）：出货量口径，用于制造侧收入。
# 二者相差 3 倍以上，混用会让"覆盖了多少车"和"今年卖了多少电池"互相污染。
_COMMERCIAL = ("heavy", "city")                        # 商用营运车：重卡 + 城配
_PASSENGER_OPS = ("taxi", "ridehail", "robotaxi")      # 乘用营运车：出租 + 网约 + Robotaxi
_PRIVATE = ("private",)                                # 私家车
_ALL_VEHICLES = _COMMERCIAL + _PASSENGER_OPS + _PRIVATE


def _stock_vehicles(keys: tuple[str, ...]) -> Callable[[ModelSnapshot], float]:
    """终局覆盖车辆（存量口径，万辆）。"""
    def get(s: ModelSnapshot) -> float:
        return sum(s.scale.operating_stock_by_vehicle_wan.get(k, 0.0) for k in keys)
    return get


def _flow(field: str, keys: tuple[str, ...] | None = None,
          year: int = 2030) -> Callable[[ModelSnapshot], float]:
    """某年度出货量（流量口径）：车辆万辆 / 装车 GWh，取自 scale.rows。"""
    def get(s: ModelSnapshot) -> float:
        return sum(
            getattr(row, field)
            for row in s.scale.rows
            if row.year == year and (keys is None or row.vehicle_key in keys)
        )
    return get


def _station_battery_gwh(s: ModelSnapshot) -> float:
    return sum(p.station_battery_gwh for p in s.swap_business.pool_operations.values())


def _battery_stock_total(s: ModelSnapshot) -> float:
    return s.swap_business.rent_vehicle_gwh + _station_battery_gwh(s)


METRICS: list[Metric] = [
    # — ① 运营业务规模（存量口径：终局在役多少、网络多大）—
    Metric("ops.veh_commercial", "终局覆盖·商用营运车(重卡+城配)", _stock_vehicles(_COMMERCIAL), 1, "万辆", "①运营规模"),
    Metric("ops.veh_passenger_ops", "终局覆盖·乘用营运车(出租+网约+Robotaxi)", _stock_vehicles(_PASSENGER_OPS), 1, "万辆", "①运营规模"),
    Metric("ops.veh_private", "终局覆盖·私家车", _stock_vehicles(_PRIVATE), 1, "万辆", "①运营规模"),
    Metric("ops.veh_total", "终局覆盖车辆合计", _stock_vehicles(_ALL_VEHICLES), 1, "万辆", "①运营规模"),
    Metric("ops.battery_vehicle", "换电装机保有量·车端", lambda s: s.swap_business.rent_vehicle_gwh, 1, "GWh", "①运营规模"),
    Metric("ops.battery_station", "换电装机保有量·站内周转", _station_battery_gwh, 1, "GWh", "①运营规模"),
    Metric("ops.battery_total", "换电装机保有量合计", _battery_stock_total, 1, "GWh", "①运营规模"),
    Metric("ops.annual_energy", "年换电交易电量", lambda s: s.swap_business.annual_energy_yi_kwh, 1, "亿kWh", "①运营规模"),
    Metric("scale.daily_swaps", "成熟期日换电次数", _daily_swaps_wan, 1, "万次/日", "①运营规模"),
    Metric("scale.heavy_stations", "终局重卡站数", lambda s: s.scale.station_demand_by_category["heavy"], 0, "座", "①运营规模"),
    Metric("scale.choco_stations", "终局巧克力站数", lambda s: s.scale.station_demand_by_category["choco"], 0, "座", "①运营规模"),
    # — ② 制造业务出货（流量口径：2030 当年交付多少，区分换电/充电）—
    Metric("mfg.swap_veh_2030", "2030出货·换电车辆", _flow("catl_swap_vehicles_wan"), 1, "万辆", "②制造出货"),
    Metric("mfg.charge_veh_2030", "2030出货·充电车辆", _flow("catl_charge_vehicles_wan"), 1, "万辆", "②制造出货"),
    Metric("mfg.swap_gwh_2030", "2030出货·换电装车", _flow("catl_swap_gwh"), 1, "GWh", "②制造出货"),
    Metric("mfg.charge_gwh_2030", "2030出货·充电装车", _flow("catl_charge_gwh"), 1, "GWh", "②制造出货"),
    # — ③ 资本层 —
    Metric("capex.initial_capex", "终局初装CAPEX", lambda s: s.capex.total_initial_capex_yi, 1, "亿元", "③资本"),
    Metric("capex.equity_call", "CATL权益出资合计", lambda s: s.capex.catl_total_equity_call_yi, 1, "亿元", "③资本"),
    Metric("capex.peak_call", "峰值年权益出资", lambda s: s.capex.catl_peak_equity_call_yi, 1, "亿元", "③资本"),
    Metric("capex.project_debt", "项目债务", lambda s: s.capex.project_debt_yi, 1, "亿元", "③资本"),
    # — 运营层 —
    Metric("swap.revenue", "运营年收入", lambda s: s.swap_business.revenue_yi, 1, "亿元", "④运营财务"),
    Metric("swap.service_rev", "　服务费收入", lambda s: s.swap_business.service_revenue_yi, 1, "亿元", "④运营财务"),
    Metric("swap.rent_rev", "　电池租金收入", lambda s: s.swap_business.battery_rent_yi, 1, "亿元", "④运营财务"),
    Metric("swap.ancillary", "　辅助服务收入", lambda s: s.swap_business.ancillary_yi, 1, "亿元", "④运营财务"),
    Metric("swap.opex", "运营OPEX", lambda s: s.swap_business.opex_yi, 1, "亿元", "④运营财务"),
    Metric("swap.ebitda", "EBITDA", lambda s: s.swap_business.ebitda_yi, 1, "亿元", "④运营财务"),
    Metric("swap.required_ebitda", "资本回报要求EBITDA", lambda s: s.swap_business.required_ebitda_yi, 1, "亿元", "④运营财务"),
    Metric("swap.coverage", "EBITDA覆盖倍数", lambda s: s.swap_business.forward_to_required_ebitda, 2, "×", "④运营财务"),
    Metric("swap.operating_value", "运营权益价值(CATL归属)", lambda s: s.swap_business.catl_attributable_value_yi, 1, "亿元", "④运营财务"),
    # — 制造与估值层 —
    Metric("mfg.with_swap_np", "有换电制造净利", lambda s: s.ledger.with_swap_manufacturing.net_profit_yi, 1, "亿元", "⑤估值"),
    Metric("mfg.no_swap_np", "无换电制造净利", lambda s: s.ledger.no_swap_manufacturing.net_profit_yi, 1, "亿元", "⑤估值"),
    Metric("val.power_with_swap", "2030动力价值(有换电)", lambda s: s.ledger.power_value_2030_with_swap_yi, 1, "亿元", "⑤估值"),
    Metric("val.power_no_swap", "2030动力价值(无换电)", lambda s: s.ledger.power_value_2030_no_swap_yi, 1, "亿元", "⑤估值"),
    Metric("val.swap_increment", "换电增量价值合计", lambda s: s.ledger.total_swap_increment_value_yi, 1, "亿元", "⑤估值"),
    Metric("val.incr_over_mktcap", "增量价值/集团市值", lambda s: s.ledger.attributable_swap_value_to_current_group_market_cap, 4, "倍", "⑤估值"),
    # — 资金层 —
    Metric("fund.peak_cash_to_cfo", "换电出资峰值/CFO", _peak_cash_to_cfo, 3, "倍", "⑥资金"),
    Metric("fund.closing_liquidity", "2030期末可动用资金", _closing_liquidity, 1, "亿元", "⑥资金"),
    Metric("fund.exposure", "待决战略敞口", lambda s: s.strategic_exposure_yi, 1, "亿元", "⑥资金"),
]

METRIC_BY_KEY = {m.key: m for m in METRICS}


def read_metrics(snapshot: ModelSnapshot) -> dict[str, float]:
    values: dict[str, float] = {}
    for metric in METRICS:
        try:
            values[metric.key] = float(metric.getter(snapshot))
        except Exception:
            values[metric.key] = float("nan")
    return values


# ══════════════════════════════════════════════════════════════════════
# 四、重跑：只跑核心链（不含并购对比与内置敏感性，故快）
# ══════════════════════════════════════════════════════════════════════

_BASE_PRIVATE_SCENARIO = "中枢"


def rerun(config: dict, scenario_name: str | None = None) -> ModelSnapshot:
    return _build_core(config, scenario_name, _BASE_PRIVATE_SCENARIO, "derived")


def perturbed(config: dict, path: str, factor: float | None = None,
              value: float | None = None) -> tuple[dict, float, float]:
    """返回 (新config, 原值, 新值)。factor 与 value 二选一。"""
    new_config = copy.deepcopy(config)
    old = float(get_path(new_config, path))
    if value is not None:
        new = float(value)
    else:
        new = old * factor if old else (abs(factor - 1.0) or 0.01)
    set_path(new_config, path, new)
    return new_config, old, new


# ══════════════════════════════════════════════════════════════════════
# 五、终端输出辅助（中文按 2 宽度对齐）
# ══════════════════════════════════════════════════════════════════════


def _width(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(text))


def _ljust(text: Any, width: int) -> str:
    text = str(text)
    return text + " " * max(0, width - _width(text))


def _rjust(text: Any, width: int) -> str:
    text = str(text)
    return " " * max(0, width - _width(text)) + text


def _fmt(value: float, decimals: int) -> str:
    if value != value:  # NaN
        return "—"
    if abs(value) >= 1e6:
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


# ══════════════════════════════════════════════════════════════════════
# 六、命令实现
# ══════════════════════════════════════════════════════════════════════


def cmd_list(config: dict) -> None:
    docs = load_param_docs()
    params = iter_numeric_params(config)
    print(f"\n可调数值参数共 {len(params)} 个（已排除 URL/交易台账/参照公司事实/开关项）\n")
    print(_ljust("参数路径（改它就用这个完整路径）", 58) + _rjust("当前值", 12) + "   " + "一句话理由（完整推导见 MANIFEST）")
    print("─" * 132)
    last_section = ""
    for path, value in params:
        doc = docs.get(path, {})
        section = doc.get("section", path.rsplit(".", 1)[0])
        if section != last_section:
            print(f"\n■ {section}")
            last_section = section
        reason = doc.get("reason", "")
        if _width(reason) > 60:
            reason = reason[:58] + "…"
        print("  " + _ljust(path, 56) + _rjust(f"{value:g}", 12) + "   " + reason)
    print("\n提示：改参数用 impact 先看影响，再改 configs/base.toml。")


def cmd_impact(config: dict, base_values: dict[str, float], path: str, spec: str) -> None:
    if spec.endswith("%"):
        delta = float(spec[:-1]) / 100.0
        new_config, old, new = perturbed(config, path, factor=1.0 + delta)
        how = f"{old:g} → {new:g}（{spec}）"
    else:
        new_config, old, new = perturbed(config, path, value=float(spec))
        how = f"{old:g} → {new:g}"

    print(f"\n改动：{path}    {how}\n")
    try:
        values = read_metrics(rerun(new_config))
    except AssertionError as exc:
        print(f"✗ 该取值触发模型硬约束，未通过校验：\n  {exc}")
        print("  这不是程序错误——模型在告诉你这个参数不能单独这么调。")
        return
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 重跑失败：{type(exc).__name__}: {exc}")
        return

    print(_ljust("指标", 26) + _rjust("改前", 14) + _rjust("改后", 14) + _rjust("变化", 12) + _rjust("幅度", 10))
    print("─" * 78)
    last_group = ""
    for metric in METRICS:
        if metric.group != last_group:
            print(f"\n{metric.group}")
            last_group = metric.group
        before = base_values[metric.key]
        after = values[metric.key]
        if before != before or after != after:
            continue
        diff = after - before
        pct = (diff / before * 100) if before else float("nan")
        flag = "  ←" if abs(pct if pct == pct else 0) >= 1 else ""
        print(
            "  " + _ljust(metric.label, 24)
            + _rjust(_fmt(before, metric.decimals), 14)
            + _rjust(_fmt(after, metric.decimals), 14)
            + _rjust(_fmt(diff, metric.decimals), 12)
            + _rjust(("—" if pct != pct else f"{pct:+.1f}%"), 10)
            + flag
        )
    print("\n（← 标记 = 变化超过 1%；未列出的指标未受影响）")


def cmd_lineage(config: dict, base_values: dict[str, float], metric_key: str,
                top: int = 15, step: float = 0.10) -> None:
    metric = METRIC_BY_KEY.get(metric_key)
    if metric is None:
        print(f"✗ 未知指标 {metric_key}。可用指标（python src/lab.py scan 也能看到）：")
        for m in METRICS:
            print(f"    {m.key:<28}{m.label}")
        return
    base_value = base_values[metric.key]
    print(f"\n追溯：{metric.label}（当前 {_fmt(base_value, metric.decimals)} {metric.unit}）")
    print(f"做法：逐个参数单独 {step:+.0%}，实测该指标的反应（弹性 = 指标变化% ÷ 参数变化%）\n")

    params = iter_numeric_params(config)
    rows: list[tuple[str, float, float, float]] = []
    t0 = time.time()
    for index, (path, old) in enumerate(params, 1):
        if abs(old) < 1e-12:
            factor = 1.0 + step  # 零值参数改用绝对微扰，避免除零
            new_config, _, _ = perturbed(config, path, value=step)
        else:
            new_config, _, _ = perturbed(config, path, factor=1.0 + step)
            factor = 1.0 + step
        try:
            after = metric.getter(rerun(new_config))
        except Exception:  # noqa: BLE001 - 触发硬约束的参数记 0 影响
            continue
        if after != after:
            continue
        diff = after - base_value
        if base_value:
            pct = diff / base_value
        else:
            pct = 0.0 if abs(diff) < 1e-12 else float("inf") if diff else 0.0
        elasticity = pct / (factor - 1.0) if factor != 1.0 else 0.0
        rows.append((path, old, diff, elasticity))
        if index % 40 == 0:
            print(f"    …已试 {index}/{len(params)} 个参数（{time.time() - t0:.0f}s）", flush=True)

    rows.sort(key=lambda r: abs(r[3]), reverse=True)
    print(_ljust("上游参数", 54) + _rjust("参数值", 12) + _rjust(f"{step:+.0%}后的变化", 16) + _rjust("弹性", 10))
    print("─" * 94)
    for path, old, diff, elasticity in rows[:top]:
        bar = "█" * min(20, int(abs(elasticity) * 20))
        print(
            _ljust(path, 54)
            + _rjust(f"{old:g}", 12)
            + _rjust(_fmt(diff, metric.decimals), 16)
            + _rjust(f"{elasticity:+.2f}", 10)
            + "  " + bar
        )
    print(f"\n共 {len(params)} 个参数参与实测，上表为影响最大的前 {top} 个。")
    print("弹性读法：+1.00 = 参数涨 10%、指标涨 10%；0.00 = 该参数根本没进这条链。")


def compute_elasticity(
    config: dict,
    base_values: dict[str, float],
    step: float = 0.10,
    quiet: bool = True,
) -> dict[str, dict[str, float]]:
    """逐个参数单独微扰、重跑、比对——用实测得出完整的「参数 × 指标」血缘矩阵。

    不解析代码、不登记公式：模型改版后重跑即得新血缘，永远不会和代码脱钩。
    触发模型硬约束（assert）的参数记为 {} ——那不是错误，是模型在说它不能单独这么调。
    """
    params = iter_numeric_params(config)
    elasticity: dict[str, dict[str, float]] = {}
    t0 = time.time()
    for index, (path, old) in enumerate(params, 1):
        new_config = copy.deepcopy(config)
        set_path(new_config, path, step if abs(old) < 1e-12 else old * (1.0 + step))
        try:
            values = read_metrics(rerun(new_config))
        except Exception:  # noqa: BLE001
            elasticity[path] = {}
            continue
        row: dict[str, float] = {}
        for metric in METRICS:
            before, after = base_values[metric.key], values[metric.key]
            if before != before or after != after:
                continue
            row[metric.key] = (((after - before) / before) / step) if before else 0.0
        elasticity[path] = row
        if not quiet and index % 50 == 0:
            print(f"    …{index}/{len(params)}（{time.time() - t0:.0f}s）", flush=True)
    return elasticity


# 总影响力口径（问题1修正）：只算「估值相关终端指标」，排除物理中间量(①运营规模/②制造出货)
# 且在终端层内剔除「合计值 vs 其分项」的恒等式重复：
#   · ④ 运营年收入 已含 服务费/租金/辅助 → 剔除那三个分项
#   · EBITDA = 年收入 − OPEX（可由二者推出）→ 剔除 EBITDA，保留覆盖倍数(比率)
#   · ⑤ 增量价值/集团市值 与 换电增量价值 弹性完全相同(市值=外部常数) → 只留归一化口径
#   · 有/无换电动力价值 是绝对值、增量=有−无 → 只留 增量价值/市值 与 有换电制造净利
# 这样排名不再把「电量→EBITDA→估值」这类链式传染重复加总。
VALUATION_TERMINAL_METRICS = [
    # ③ 资本层（投入与出资）
    "capex.initial_capex", "capex.equity_call", "capex.peak_call", "capex.project_debt",
    # ④ 运营财务层（实际业绩；已剔除分项与可推导项）
    "swap.revenue", "swap.opex", "swap.coverage", "swap.operating_value",
    # ⑤ 估值层（资本市场影响；已剔除绝对值恒等式重复）
    "mfg.with_swap_np", "val.incr_over_mktcap",
    # ⑥ 资金层（资金压力与战略敞口）
    "fund.peak_cash_to_cfo", "fund.closing_liquidity", "fund.exposure",
]
_VALUATION_TERMINAL_SET = set(VALUATION_TERMINAL_METRICS)


def total_influence(row: dict[str, float]) -> float:
    """只对一个参数对「估值相关终端指标」的弹性取绝对值求和，避免链式重复加总。"""
    return sum(abs(v) for k, v in row.items() if k in _VALUATION_TERMINAL_SET)


def _short(path: str) -> str:
    """参数路径的简短显示：保留末两段，避免表格被撑爆。"""
    parts = path.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else path


def cmd_workbook(config: dict, base_values: dict[str, float], step: float = 0.10) -> None:
    """生成 Excel 工作簿：假设表 / 结果表 / 敏感性矩阵 / 双向血缘。

    对应财务建模的三张表习惯，但血缘不是人写的注释，是实测出来的。
    """
    if Workbook is None:
        print("缺少 openpyxl，请先安装：pip install openpyxl")
        return

    print(f"正在实测全参数血缘（每个参数单独 {step:+.0%}）…", flush=True)
    t0 = time.time()
    elasticity = compute_elasticity(config, base_values, step)
    print(f"血缘实测完成（{time.time() - t0:.0f}s）")

    docs = load_param_docs()
    params = dict(iter_numeric_params(config))
    influence = {p: total_influence(row) for p, row in elasticity.items()}

    def new_sheet(wb, title: str, first: bool = False):
        return wb.active if first else wb.create_sheet(title)

    wb = Workbook()

    # ── Sheet 0：怎么用 ────────────────────────────────────────────
    ws = wb.active
    ws.title = "00_怎么用"
    guide = [
        ("换电战略决策模型 v4.3 — 参数与血缘工作簿", True),
        ("", False),
        ("生成方式：python src/lab.py workbook（改模型后重跑本命令即可刷新全部内容）", False),
        ("", False),
        ("【这张表解决什么问题】", True),
        ("模型拆成 configs/src/outputs 之后，改一个参数看不出它影响了谁——Excel 里靠「追踪引用/从属单元格」，", False),
        ("这里靠实测：把每个参数单独 +10%，重跑同一条计算链，比对全部指标。所以下面的血缘不是注释，是测量值。", False),
        ("", False),
        ("【五个页签怎么读】", True),
        ("01_假设参数　　全部可调参数：值 + 为什么这么假设 + 影响力星级。浅蓝底＝可调。", False),
        (f"02_结果总表　　{len(METRICS)} 个输出结果，每个都标出「决定它的三个参数」。", False),
        ("03_敏感性矩阵　参数 × 指标的完整弹性表，红绿配色＝方向和强弱。", False),
        ("04_溯源　　　　选中一个结果，看它由哪些参数决定（＝Excel 追踪引用单元格）。", False),
        ("05_影响　　　　选中一个参数，看它推动哪些结果（＝Excel 追踪从属单元格）。", False),
        ("", False),
        ("【弹性怎么读】", True),
        ("弹性 = 参数 +10% 时，该指标变化百分之几 ÷ 10%。例：+1.00＝参数涨 10%、指标涨 10%（同比例）；", False),
        ("-1.50＝参数涨 10%、指标跌 15%（放大且反向）；0.00＝这个参数根本没进这条链，调它不影响该结果。", False),
        ("", False),
        ("【影响力/弹性是怎么算出来的】", True),
        ("只做一件事：把参数单独 +10%，重跑同一条计算链，比对全部结果。不解析代码、不登记公式，", False),
        ("所以模型改版后重跑即得新血缘，永远不会和代码脱钩。完整逐步演算见 06_算法演示 页签。", False),
        ("「总影响力」＝该参数对「估值相关终端指标」(③资本/④运营财务/⑤估值/⑥资金，共13项)的弹性取绝对值之和。", False),
        ("　　已剔除①运营规模、②制造出货这两个物理中间量，并去掉「合计值与其分项」「增量价值与归一化值」等恒等式重复——", False),
        ("　　否则链式因果(电量→EBITDA→估值)会被重复加总。总影响力只用来给参数排重要度，不作决策数字。", False),
        ("", False),
        ("【改参数的标准动作（不想碰代码，全在 Excel 里完成）】", True),
        ("1. python src/lab.py workbook  → 生成本工作簿，01_假设参数 多出一列「试算值(改这里)」", False),
        ("2. 在 Excel 里把想试的参数那格改成新值（其余别动）", False),
        ("3. python src/lab.py trial  → 看 07_试算对比：基准值 vs 试算值，变化≥±5% 自动标黄", False),
        ("4. 满意了 → python src/lab.py commit  → 改动安全写回 base.toml（保留原注释）", False),
        ("5. python src/run.py 刷新快照与报告，再 python src/backscan.py MANIFEST.md 验收 15/15", False),
        ("", False),
        ("【只想知道单个参数动一下会怎样（不进 Excel）】", True),
        ("命令行：python src/lab.py impact <参数路径> <新值|±%>  只看结果，不动任何文件", False),
        ("", False),
        ("【口径纪律】", True),
        ("· 本工作簿的所有数字都来自 outputs/decision_snapshot，与骨架报告同源，不存在第二套数。", False),
        ("· 一句话理由取自 base.toml 注释（前两行）；完整推导与信源一律见 MANIFEST.md，不在此展开。", False),
        ("· 影响力星级：★★★ 总弹性≥5（动它要慎）｜★★ ≥2｜★ ≥0.5｜空白＝几乎不影响任何结果。", False),
    ]
    for row_index, (text, bold) in enumerate(guide, 1):
        cell = ws.cell(row=row_index, column=1, value=text)
        if bold:
            cell.font = Font(bold=True, size=12 if row_index == 1 else 11)
    set_widths(ws, [118])

    # ── Sheet 1：假设参数表 ────────────────────────────────────────
    ws = wb.create_sheet("01_假设参数")
    headers = ["序号", "所属段", "参数路径", "当前值", "试算值(改这里)", "一句话理由（为什么这么假设）", "总影响力", "关键度"]
    ws.append(headers)
    style_header(ws, 1, len(headers))

    grouped: dict[str, list[str]] = {}
    for path in params:
        section = docs.get(path, {}).get("section", path.rsplit(".", 1)[0])
        grouped.setdefault(section, []).append(path)

    row_index = 1
    serial = 0
    for section in sorted(grouped):
        paths = sorted(grouped[section], key=lambda p: influence.get(p, 0.0), reverse=True)
        for path in paths:
            serial += 1
            row_index += 1
            total = influence.get(path, 0.0)
            stars = "★★★" if total >= 5 else "★★" if total >= 2 else "★" if total >= 0.5 else ""
            ws.append([
                serial,
                section,
                path,
                params[path],
                params[path],   # 试算值：初始=当前值，用户在 Excel 里改这一格
                docs.get(path, {}).get("reason", ""),
                round(total, 3),
                stars,
            ])
            ws.cell(row=row_index, column=4).fill = EDIT_FILL
            ws.cell(row=row_index, column=5).fill = EDIT_FILL
            for col in (1, 4, 5, 7, 8):
                ws.cell(row=row_index, column=col).alignment = Alignment(horizontal="center")
            ws.cell(row=row_index, column=6).alignment = WRAP
    set_widths(ws, [6, 24, 52, 13, 13, 58, 10, 7])

    # ── Sheet 2：结果总表 ─────────────────────────────────────────
    ws = wb.create_sheet("02_结果总表")
    headers = ["分组", "指标", "当前值", "单位", "决定它的三个参数（弹性）"]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    for row_index, metric in enumerate(METRICS, 2):
        column = [(p, elasticity.get(p, {}).get(metric.key, 0.0)) for p in elasticity]
        column = [c for c in column if abs(c[1]) >= 0.005]
        column.sort(key=lambda c: abs(c[1]), reverse=True)
        drivers = "；".join(f"{_short(p)} {v:+.2f}" for p, v in column[:3]) or "（不受单参数显著影响）"
        ws.append([metric.group, metric.label, base_values[metric.key], metric.unit, drivers])
        ws.cell(row=row_index, column=3).number_format = (
            f"#,##0.{'0' * metric.decimals}" if metric.decimals > 0 else "#,##0"
        )
        ws.cell(row=row_index, column=5).alignment = WRAP
    set_widths(ws, [8, 26, 16, 10, 62])

    # ── Sheet 3：敏感性矩阵 ────────────────────────────────────────
    ws = wb.create_sheet("03_敏感性矩阵")
    headers = ["参数路径", "当前值", "总影响力", *[m.label for m in METRICS]]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    ordered = sorted(elasticity, key=lambda p: influence.get(p, 0.0), reverse=True)
    for row_index, path in enumerate(ordered, 2):
        row = elasticity.get(path, {})
        ws.append([
            path,
            params[path],
            round(influence.get(path, 0.0), 2),
            *[round(row.get(m.key, 0.0), 3) for m in METRICS],
        ])
    last_row = len(ordered) + 1
    ws.conditional_formatting.add(
        f"D2:{get_column_letter(3 + len(METRICS))}{last_row}",
        ColorScaleRule(
            start_type="num", start_value=-1.5, start_color="F8696B",
            mid_type="num", mid_value=0, mid_color="FFFFFF",
            end_type="num", end_value=1.5, end_color="63BE7B",
        ),
    )
    set_widths(ws, [56, 12, 10, *[13] * len(METRICS)])

    # ── Sheet 4：溯源（结果 ← 参数）─────────────────────────────────
    ws = wb.create_sheet("04_溯源_谁决定这个结果")
    headers = ["结果指标", "当前值", "单位", "上游参数", "参数值", "弹性", "方向"]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    row_index = 1
    for metric in METRICS:
        row_index += 1
        ws.cell(row=row_index, column=1, value=metric.label).fill = BLOCK_FILL
        ws.cell(row=row_index, column=1).font = Font(bold=True)
        ws.cell(row=row_index, column=2, value=base_values[metric.key]).font = Font(bold=True)
        ws.cell(row=row_index, column=3, value=metric.unit)
        column = [(p, elasticity.get(p, {}).get(metric.key, 0.0)) for p in elasticity]
        column = [c for c in column if abs(c[1]) >= 0.005]
        column.sort(key=lambda c: abs(c[1]), reverse=True)
        if not column:
            ws.cell(row=row_index, column=4, value="（不受任何单参数显著影响）")
            continue
        for path, value in column[:12]:
            row_index += 1
            ws.append([None, None, None, path, params[path], round(value, 3),
                       "↑同向" if value > 0 else "↓反向"])
            ws.cell(row=row_index, column=6).alignment = Alignment(horizontal="center")
    set_widths(ws, [26, 14, 10, 54, 14, 10, 10])

    # ── Sheet 5：影响（参数 → 结果）─────────────────────────────────
    ws = wb.create_sheet("05_影响_这个参数推动哪些结果")
    headers = ["参数路径", "参数值", "受影响的结果", "结果当前值", "弹性"]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    row_index = 1
    for path in ordered[:40]:
        row = {k: v for k, v in elasticity.get(path, {}).items() if abs(v) >= 0.005}
        if not row:
            continue
        row_index += 1
        ws.cell(row=row_index, column=1, value=path).fill = BLOCK_FILL
        ws.cell(row=row_index, column=1).font = Font(bold=True)
        ws.cell(row=row_index, column=2, value=params[path])
        for metric_key, value in sorted(row.items(), key=lambda kv: abs(kv[1]), reverse=True)[:10]:
            metric = METRIC_BY_KEY[metric_key]
            row_index += 1
            ws.append([None, None, metric.label, base_values[metric_key], round(value, 3)])
            ws.cell(row=row_index, column=5).alignment = Alignment(horizontal="center")
    set_widths(ws, [56, 14, 28, 16, 10])

    # ── Sheet 6：算法演示（把弹性的计算过程摊开，不留黑箱）────────────
    demo_param = "swap_business.service_fee_rmb_kwh"
    demo_metric = "val.swap_increment"
    metric = METRIC_BY_KEY[demo_metric]
    demo_old = float(get_path(config, demo_param))
    demo_cfg = copy.deepcopy(config)
    set_path(demo_cfg, demo_param, demo_old * (1.0 + step))
    demo_after = read_metrics(rerun(demo_cfg))[demo_metric]
    demo_before = base_values[demo_metric]
    demo_diff = demo_after - demo_before
    demo_pct = (demo_diff / demo_before) if demo_before else 0.0
    demo_elas = demo_pct / step

    ws = wb.create_sheet("06_算法演示_弹性怎么算出来的")
    ws.append(["弹性的计算过程——拿一个真实例子从头算一遍"])
    ws.cell(row=1, column=1).font = Font(bold=True, size=12)
    ws.append([])
    ws.append(["被调参数", demo_param, "（换电服务费，元/kWh）"])
    ws.append(["被看指标", metric.label, metric.unit])
    ws.append([])
    headers = ["步骤", "这一步在做什么", "算式", "结果"]
    ws.append(headers)
    style_header(ws, 6, len(headers))
    steps = [
        ("① 读基准参数", "从 configs/base.toml 原样读出", "—", f"{demo_old:g} 元/kWh"),
        ("② 扰动参数", f"只把这一个参数 {step:+.0%}，其余一律不动",
         f"{demo_old:g} × {1 + step:g}", f"{demo_old * (1 + step):g} 元/kWh"),
        ("③ 基准重跑", "用原参数跑完整计算链，读该指标", "—", f"{demo_before:,.1f} {metric.unit}"),
        ("④ 扰动重跑", "用②的参数再跑一遍同一条链", "—", f"{demo_after:,.1f} {metric.unit}"),
        ("⑤ 算变化额", "④ − ③", f"{demo_after:,.1f} − {demo_before:,.1f}", f"{demo_diff:+,.1f} {metric.unit}"),
        ("⑥ 算变化率", "⑤ ÷ ③", f"{demo_diff:,.1f} ÷ {demo_before:,.1f}", f"{demo_pct:+.2%}"),
        ("⑦ 算弹性", f"⑥ ÷ {step:.0%}（换算成「每 1%」的力道）",
         f"{demo_pct:+.2%} ÷ {step:.0%}", f"{demo_elas:+.2f}"),
    ]
    for text, what, formula, result in steps:
        ws.append([text, what, formula, result])
        ws.cell(row=ws.max_row, column=4).alignment = Alignment(horizontal="right")
    ws.append([])
    ws.append(["结论", f"服务费每涨 1%，{metric.label}涨 {demo_elas:.2f}%——这就是 03 表里那个 +0.55 的来历", "", ""])
    ws.append([])
    ws.append(["「总影响力」又是什么", "", "", ""])
    ws.append(["", f"把同一个参数对「估值相关终端指标」(③资本/④运营财务/⑤估值/⑥资金，共 {len(VALUATION_TERMINAL_METRICS)} 项)的弹性取绝对值后相加，得到它撬动决策结果的总力度。", "", ""])
    ws.append(["", "已剔除①运营规模、②制造出货这两个物理中间量，并去掉「合计值与其分项」「增量价值与归一化值」等恒等式重复，", "", ""])
    ws.append(["", "否则链式因果(电量→EBITDA→估值)会被重复加总、虚高影响力。它只用来给参数排重要度，不作决策数字——", "", ""])
    ws.append(["", "要看具体哪个结果、变了多少，请回到 03/05 表。", "", ""])
    ws.append([])
    ws.append(["这方法的三条局限（必须知道）", "", "", ""])
    ws.append(["", "1. 一次只动一个参数，不含「两个一起变」的交互效应；真实世界常常是联动的。", "", ""])
    ws.append(["", f"2. 步长固定 {step:+.0%}。若关系是弯曲的（取整、min/max、ceil 都会造成弯折），", "", ""])
    ws.append(["", "　　换个步长算出的弹性会变——所以它叫「局部弹性」。", "", ""])
    ws.append(["", "3. 触发模型硬约束（assert）的参数会被跳过、弹性留空。那不是报错，", "", ""])
    ws.append(["", "　　是模型在告诉你：这个参数不能单独这么调（例如规划能力不能超过物理上限）。", "", ""])
    set_widths(ws, [22, 62, 30, 24])

    out_dir = ROOT.parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = out_dir / "换电模型_参数与血缘_v4.3.xlsx"
    try:
        wb.save(xlsx_path)
    except PermissionError:
        fallback = out_dir / "换电模型_参数与血缘_v4.3_新.xlsx"
        wb.save(fallback)
        print(f"\n⚠ 目标文件被占用（多半是 Excel 正打开它），已改写到：\n  {fallback}")
        print("  关闭 Excel 里的旧文件后重新运行本命令，即可覆盖回原文件名。")
        return
    print(f"\n已生成：{xlsx_path}")
    print("  00_怎么用 / 01_假设参数 / 02_结果总表 / 03_敏感性矩阵 / 04_溯源 / 05_影响")


# ══════════════════════════════════════════════════════════════════════
# 五、试算闭环：在 Excel 里改「试算值」→ trial 看结果 → commit 落盘
# ══════════════════════════════════════════════════════════════════════

def _locate_workbook() -> Path:
    """优先用规范文件名；被 Excel 占用时回退到 _新 副本。"""
    out_dir = ROOT.parent / "outputs"
    canonical = out_dir / "换电模型_参数与血缘_v4.3.xlsx"
    fallback = out_dir / "换电模型_参数与血缘_v4.3_新.xlsx"
    if canonical.exists():
        return canonical
    if fallback.exists():
        return fallback
    raise SystemExit("找不到工作簿，请先跑：python src/lab.py workbook")


def _read_trials(xlsx_path: Path) -> dict[str, tuple[float, float]]:
    """从 01_假设参数 的「试算值」列读出 (当前值, 试算值)，只保留改过的。"""
    wb = load_workbook(xlsx_path, data_only=True)
    ws = wb["01_假设参数"]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    i_path = header.index("参数路径")
    i_cur = header.index("当前值")
    i_trial = header.index("试算值(改这里)")
    trials: dict[str, tuple[float, float]] = {}
    for r in rows[1:]:
        if not r or r[i_path] is None:
            continue
        try:
            cur = float(r[i_cur])
            trial = float(r[i_trial])
        except (TypeError, ValueError):
            continue
        if trial != cur:
            trials[str(r[i_path])] = (cur, trial)
    return trials


def _fmt_toml_value(v: float) -> str:
    fv = float(v)
    return str(int(fv)) if fv.is_integer() else repr(fv)


def _section_matches(current: str | None, target: str) -> bool:
    return current is not None and current.strip() == target.strip()


def _apply_toml(toml_path: Path, trials: dict[str, tuple[float, float]]) -> list[str]:
    """把试算值安全写回 base.toml：只在对应 [section] 下替换 leaf 的值，保留注释与缩进。"""
    lines = toml_path.read_text(encoding="utf-8").splitlines()
    targets = {p: (p.rsplit(".", 1)[0], p.rsplit(".", 1)[1]) for p in trials}
    remaining = set(targets)
    current_section = None
    out: list[str] = []
    changed: list[str] = []
    for line in lines:
        m_sec = re.match(r"^\s*\[([^\]]+)\]\s*", line)
        if m_sec:
            current_section = m_sec.group(1)
            out.append(line)
            continue
        hit = None
        for path in list(remaining):
            section, leaf = targets[path]
            if _section_matches(current_section, section):
                m = re.match(rf"^(\s*{re.escape(leaf)}\s*=\s*)([^\s#]+)(\s*(#.*)?)$", line)
                if m:
                    hit = path
                    break
        if hit:
            _cur, trial = trials[hit]
            m = re.match(rf"^(\s*{re.escape(targets[hit][1])}\s*=\s*)([^\s#]+)(\s*(#.*)?)$", line)
            prefix, _old, comment = m.group(1), m.group(2), m.group(3) or ""
            out.append(f"{prefix}{_fmt_toml_value(trial)}{comment}")
            changed.append(hit)
            remaining.discard(hit)
        else:
            out.append(line)
    if remaining:
        print(f"  ⚠ 以下参数在 base.toml 未找到对应行，已跳过：{sorted(remaining)}")
    toml_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def cmd_trial(config: dict, base_values: dict[str, float]) -> None:
    ALERT_FILL = PatternFill("solid", fgColor="FFF2CC")
    xlsx_path = _locate_workbook()
    trials = _read_trials(xlsx_path)
    if not trials:
        print("01_假设参数 的「试算值」与当前值完全一致，没有要试算的改动。")
        print("先在 Excel 里把想试的参数那格改成新值，再跑本命令。")
        return

    # 逐个测可行性：触发硬约束的参数不参与合并试算，避免整组崩掉
    feasible: dict[str, tuple[float, float]] = {}
    blocked: list[str] = []
    for path, (cur, trial) in trials.items():
        c = copy.deepcopy(config)
        set_path(c, path, trial)
        try:
            rerun(c)
            feasible[path] = (cur, trial)
        except Exception:  # noqa: BLE001
            blocked.append(path)

    if blocked:
        print(f"⚠ 以下 {len(blocked)} 个试算值触发模型硬约束，已排除在合并试算之外：")
        for p in blocked:
            print(f"   · {p}（试算值 {trials[p][1]:g}）")

    trial_config = copy.deepcopy(config)
    for path, (cur, trial) in feasible.items():
        set_path(trial_config, path, trial)
    trial_values = read_metrics(rerun(trial_config))

    wb = load_workbook(xlsx_path)
    if "07_试算对比" in wb.sheetnames:
        del wb["07_试算对比"]
    ws = wb.create_sheet("07_试算对比")
    ws.append(["试算对比：基准值 vs 你在 Excel 里填的试算值"])
    ws.cell(row=1, column=1).font = Font(bold=True, size=12)
    ws.append([])
    ws.append(["改动参数", "当前值", "试算值"])
    style_header(ws, 3, 3)
    for path, (cur, trial) in feasible.items():
        ws.append([path, cur, trial])
    ws.append([])
    headers = ["分组", "指标", "基准值", "试算值", "变化额", "变化率", "单位"]
    ws.append(headers)
    style_header(ws, ws.max_row, len(headers))
    for metric in METRICS:
        b = base_values[metric.key]
        t = trial_values[metric.key]
        if b != b or t != t:
            continue
        delta = t - b
        pct = (delta / b) if b else 0.0
        ws.append([metric.group, metric.label,
                   round(b, metric.decimals), round(t, metric.decimals),
                   round(delta, metric.decimals), pct, metric.unit])
        if abs(pct) >= 0.05:
            for col in range(1, 8):
                ws.cell(row=ws.max_row, column=col).fill = ALERT_FILL
    ws.append([])
    ws.append(["提示：变化率≥±5% 的行已标黄。确认满意后跑 python src/lab.py commit 把试算值落盘。"])
    set_widths(ws, [22, 30, 14, 14, 14, 10, 10])

    try:
        wb.save(xlsx_path)
    except PermissionError:
        wb.save(str(xlsx_path).replace(".xlsx", "_新.xlsx"))
    print(f"\n已写入 07_试算对比 页签（{len(feasible)} 个参数生效，{len(blocked)} 个被硬约束挡下）。")
    print("打开 Excel 看 07_试算对比，确认后再跑 commit。")


def cmd_commit(config: dict, base_values: dict[str, float]) -> None:
    xlsx_path = _locate_workbook()
    trials = _read_trials(xlsx_path)
    if not trials:
        print("没有可提交的改动（试算值都与当前值一致）。")
        return
    toml_path = ROOT.parent / "configs" / "base.toml"
    changed = _apply_toml(toml_path, trials)
    print(f"已落盘 {len(changed)} 个参数到 base.toml：")
    for p in changed:
        print(f"   · {p}：{trials[p][0]:g} → {trials[p][1]:g}")
    print("\n下一步：python src/run.py 刷新快照与报告，再 python src/backscan.py MANIFEST.md 验收。")


def commit_edits(edited_config: dict) -> list[str]:
    """把与默认配置不同的数值参数安全写回 base.toml（保留注释与缩进）。

    供实时沙盘（app.py）在用户点「落盘」时调用；逻辑复用 _apply_toml，单一真相源。
    """
    base = load_config()
    trials: dict[str, tuple[float, float]] = {}
    for path, old in iter_numeric_params(base):
        try:
            new = get_path(edited_config, path)
        except Exception:
            continue
        if float(new) != float(old):
            trials[path] = (float(old), float(new))
    if not trials:
        return []
    toml_path = ROOT.parent / "configs" / "base.toml"
    return _apply_toml(toml_path, trials)


def cmd_scan(config: dict, base_values: dict[str, float], step: float = 0.10,
             top_per_metric: int = 8) -> None:
    params = iter_numeric_params(config)
    print(f"\n全参数扫描：{len(params)} 个参数 × {len(METRICS)} 个指标，每个参数单独 {step:+.0%}")
    print("（这是数值法实测的血缘矩阵，不是人工登记的注释）\n")

    t0 = time.time()
    elasticity = compute_elasticity(config, base_values, step)
    print(f"\n扫描完成，用时 {time.time() - t0:.0f}s\n")

    # ── 表 1：参数影响力排序（仅对估值相关终端指标）──
    print("【表 1】谁最能撬动决策结果（按对估值相关终端指标的总绝对弹性排序）")
    print(_ljust("参数", 54) + _rjust("总影响力", 12) + "   受影响最大的指标")
    print("─" * 110)
    ranked = sorted(
        elasticity.items(),
        key=lambda kv: total_influence(kv[1]),
        reverse=True,
    )
    for path, row in ranked[:25]:
        total = total_influence(row)
        if total < 0.005:
            continue
        terminal_items = [(k, v) for k, v in row.items() if k in _VALUATION_TERMINAL_SET]
        top_metric = max(terminal_items, key=lambda kv: abs(kv[1])) if terminal_items else ("", 0)
        label = METRIC_BY_KEY[top_metric[0]].label if top_metric[0] in METRIC_BY_KEY else "—"
        print(
            _ljust(path, 54)
            + _rjust(f"{total:.2f}", 12)
            + f"   {label}（弹性 {top_metric[1]:+.2f}）"
        )

    # ── 表 2：每个关键指标的 Top 上游（龙卷风数据）──
    print("\n【表 2】每个结果由谁决定（各指标影响最大的上游参数）")
    for metric in METRICS:
        col = [(p, row.get(metric.key, 0.0)) for p, row in elasticity.items()]
        col = [c for c in col if abs(c[1]) >= 0.005]
        if not col:
            continue
        col.sort(key=lambda c: abs(c[1]), reverse=True)
        print(f"\n  ▸ {metric.label}  = {_fmt(base_values[metric.key], metric.decimals)} {metric.unit}")
        for path, value in col[:top_per_metric]:
            print("      " + _ljust(path, 52) + _rjust(f"{value:+.2f}", 8) + "  " + "█" * min(24, int(abs(value) * 12)))

    # ── 落盘：完整矩阵 ──
    out_dir = ROOT.parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = out_dir / "敏感性矩阵_v4.3.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        handle.write("参数路径,当前值," + ",".join(m.key for m in METRICS) + "\n")
        param_values = dict(params)
        for path, row in elasticity.items():
            handle.write(f"{path},{param_values[path]:g}," + ",".join(f"{row.get(m.key, 0.0):.4f}" for m in METRICS) + "\n")
    print(f"\n完整矩阵已写入：{csv_path}")
    print("（CSV 里每个数字 = 弹性：参数 +10% 时该指标变化百分之几）")


# ══════════════════════════════════════════════════════════════════════


USAGE = """用法：
  python src/lab.py list                          列出全部可调参数（值 + 理由）
  python src/lab.py impact <参数路径> <新值|±%>    改一个参数，看所有结果怎么动
  python src/lab.py lineage <指标键>               追溯：哪些参数在影响这个结果
  python src/lab.py scan                          全参数扫描 → 敏感性矩阵（终端）
  python src/lab.py workbook                      生成 Excel 工作簿（假设表/结果表/敏感性/双向血缘）
  python src/lab.py trial                         读回 01 表「试算值」→ 重跑 → 写 07_试算对比
  python src/lab.py commit                        把 01 表「试算值」安全落盘到 base.toml（保留注释）

闭环用法（不碰代码也能改模型）：
  1. python src/lab.py workbook       生成 Excel，01_假设参数 里多出一列「试算值(改这里)」
  2. 在 Excel 里把想试的参数那格改成新值（其余别动）
  3. python src/lab.py trial          看 07_试算对比：基准值 vs 试算值，变化≥±5% 自动标黄
  4. 满意了 → python src/lab.py commit   改动写回 base.toml
  5. python src/run.py                 刷新快照与报告

例子：
  python src/lab.py impact swap_business.service_fee_rmb_kwh 0.35
  python src/lab.py impact finance.wacc +20%
  python src/lab.py lineage val.swap_increment
  python src/lab.py workbook
  python src/lab.py trial
  python src/lab.py commit
"""


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(USAGE)
        return 0

    command = argv[1]
    config = load_config()

    if command == "list":
        cmd_list(config)
        return 0

    print("正在跑基准情景…", flush=True)
    t0 = time.time()
    base_values = read_metrics(rerun(config))
    print(f"基准完成（{time.time() - t0:.1f}s）")

    if command == "impact":
        if len(argv) < 4:
            print(USAGE)
            return 1
        cmd_impact(config, base_values, argv[2], argv[3])
    elif command == "lineage":
        if len(argv) < 3:
            print(USAGE)
            return 1
        cmd_lineage(config, base_values, argv[2])
    elif command == "scan":
        cmd_scan(config, base_values)
    elif command == "workbook":
        cmd_workbook(config, base_values)
    elif command == "trial":
        cmd_trial(config, base_values)
    elif command == "commit":
        cmd_commit(config, base_values)
    else:
        print(USAGE)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

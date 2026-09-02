"""模型装配层：把各子模块（scale/capex/business/ledger/...）组装成 ModelSnapshot，
并提供 _build_sensitivity 单变量敏感性（只改一个自变量、重跑同一核心链）。

变更历史
--------
v4.2.3（2026-08-29）
- 【敏感性】"充电段份额差(实现率0/50%/100%)"参数组改为"充电段市占率(悲观/中性/乐观)"，
  与 base.toml [charge_share] 三档对齐，并入7.1敏感性表。
"""
from __future__ import annotations

from copy import deepcopy
from typing import Callable

from business import build_2026_baseline, build_manufacturing_cases, build_swap_business
from capex import build_capex
from capital_cycle import build_light_asset_scenarios, strategic_exposure_total
from consolidation import build_consolidated_ledger
from decision import build_decision_memos
from group_constraints import build_capital_commitments, build_funding_envelope
from mna import get_sourcing_adjustment
from scale import build_scale
from schemas import ModelSnapshot


def _build_core(
    config: dict,
    scenario_name: str | None = None,
    private_scenario: str = "中枢",
    life_mode: str = "derived",
) -> ModelSnapshot:
    sourcing = get_sourcing_adjustment(config, scenario_name)
    scale = build_scale(config, sourcing, private_scenario, life_mode)
    capex = build_capex(config, scale, sourcing)
    baseline = build_2026_baseline(config)
    swap = build_swap_business(config, scale, capex)
    no_swap, with_swap = build_manufacturing_cases(config, scale, capex)
    ledger = build_consolidated_ledger(config, baseline, no_swap, with_swap, swap)
    light = build_light_asset_scenarios(config, scale, capex, swap, ledger)
    funding = build_funding_envelope(config, capex, sourcing)
    commitments = build_capital_commitments(config)
    exposure = strategic_exposure_total(config)
    memos = build_decision_memos(config, scale, capex, swap, ledger, light, funding, exposure)
    return ModelSnapshot(
        meta={
            **config["meta"],
            "wacc": config["finance"]["wacc"],
            "wacc_basis": "蔚来换电ABS融资基准，毛估估直接采用，不作CAPM推导",
            "generated_numbers_only": True,
            "private_scenario": private_scenario,
            "life_mode": life_mode,
        },
        sourcing=sourcing,
        scale=scale,
        capex=capex,
        swap_business=swap,
        ledger=ledger,
        light_asset=light,
        funding=funding,
        capital_commitments=commitments,
        strategic_exposure_yi=exposure,
        memos=memos,
        sources=config["sources"].copy(),
    )


def build_model(
    config: dict,
    scenario_name: str | None = None,
    private_scenario: str = "中枢",
    life_mode: str = "derived",
) -> ModelSnapshot:
    """private_scenario：私家车分档换电渗透率情景（保守/中枢/激进），
    与并购情景 scenario_name 正交——前者是需求侧分情景，后者是供给侧并购假设。

    life_mode：电池寿命口径，"derived"（基准）或 "legacy_v32"（附录对照重跑）。
    """
    snapshot = _build_core(config, scenario_name, private_scenario, life_mode)
    reference = _build_core(
        config, config["mna"]["comparison_scenario_name"], private_scenario, life_mode
    )
    reference_power_value = reference.ledger.power_value_2030_with_swap_yi
    reference_swap_value = reference.ledger.total_swap_increment_value_yi
    reference_operating_value = reference.swap_business.catl_attributable_value_yi
    reference_manufacturing_value = (
        reference.ledger.manufacturing_swap_margin_effect_value_yi
    )
    reference_selfbuild_call = reference.capex.catl_total_equity_call_yi
    comparison: list[dict] = []
    for scenario in config["mna"]["scenarios"]:
        candidate = (
            snapshot
            if scenario["name"] == snapshot.sourcing.name
            else _build_core(config, scenario["name"], private_scenario, life_mode)
        )
        transaction_cash = candidate.sourcing.cash_consideration_yi
        acquired_asset_value = candidate.sourcing.purchase_price_yi
        incremental_power_value = (
            candidate.ledger.power_value_2030_with_swap_yi - reference_power_value
        )
        incremental_swap_value = (
            candidate.ledger.total_swap_increment_value_yi - reference_swap_value
        )
        remaining_selfbuild = candidate.capex.catl_total_equity_call_yi
        selfbuild_saving = reference_selfbuild_call - remaining_selfbuild
        total_catl_cash_required = transaction_cash + remaining_selfbuild
        comparison.append({
            "name": candidate.sourcing.name,
            "label": candidate.sourcing.label,
            "price_status": candidate.sourcing.price_status,
            "price_basis": candidate.sourcing.price_basis,
            "cash_consideration_yi": transaction_cash,
            "inherited_project_debt_yi": candidate.sourcing.assumed_debt_yi,
            "network_acceleration_years": candidate.sourcing.acceleration_years,
            "acquired_network_stations": candidate.sourcing.acquired_network_stations,
            "acquired_battery_bank_gwh": candidate.sourcing.acquired_battery_bank_gwh,
            "pure_selfbuild_catl_equity_call_yi": reference_selfbuild_call,
            "remaining_selfbuild_catl_equity_call_yi": remaining_selfbuild,
            "selfbuild_cash_saved_yi": selfbuild_saving,
            "total_catl_cash_requirement_yi": total_catl_cash_required,
            "incremental_catl_cash_vs_pure_selfbuild_yi": (
                total_catl_cash_required - reference_selfbuild_call
            ),
            "transaction_cash_to_pure_selfbuild_call": (
                transaction_cash / reference_selfbuild_call
                if reference_selfbuild_call else None
            ),
            "organic_project_debt_yi": candidate.capex.project_debt_yi,
            "total_project_debt_yi": (
                candidate.capex.project_debt_yi
                + candidate.sourcing.assumed_debt_yi
            ),
            "swap_operating_value_yi": candidate.swap_business.catl_attributable_value_yi,
            "attributable_swap_value_yi": candidate.ledger.total_swap_increment_value_yi,
            "power_value_2030_yi": candidate.ledger.power_value_2030_with_swap_yi,
            "incremental_swap_operating_value_vs_base_yi": (
                candidate.swap_business.catl_attributable_value_yi - reference_operating_value
            ),
            "incremental_manufacturing_value_vs_base_yi": (
                candidate.ledger.manufacturing_swap_margin_effect_value_yi
                - reference_manufacturing_value
            ),
            "incremental_attributable_swap_value_vs_base_yi": incremental_swap_value,
            "incremental_power_value_vs_base_yi": incremental_power_value,
            "acquired_asset_value_reference_yi": acquired_asset_value,
            "gross_power_value_addition_yi": (
                acquired_asset_value + incremental_power_value
            ),
            "power_value_including_acquired_assets_yi": (
                candidate.ledger.power_value_2030_with_swap_yi + acquired_asset_value
            ),
            "net_shareholder_value_creation_after_cash_yi": (
                acquired_asset_value + incremental_power_value - transaction_cash
            ),
            "incremental_cash_vs_pure_selfbuild_yi": transaction_cash,
            "physical_station_reuse_assumed": (
                candidate.sourcing.reusable_heavy_stations
                + candidate.sourcing.reusable_choco_stations
            ),
        })
    snapshot.mna_comparison = comparison
    snapshot.sensitivity = _build_sensitivity(config, snapshot)
    return snapshot


def _build_sensitivity(config: dict, base: ModelSnapshot) -> list[dict]:
    """只改一个关键自变量，重跑同一核心链；并购另在Part 7比较。"""
    cases: list[tuple[str, str, Callable[[dict], None]]] = []

    for multiple in (14.0, 18.0, 22.0, 25.0):
        cases.append((
            "运营EV/EBITDA",
            f"{multiple:g}×",
            lambda cfg, value=multiple: cfg["finance"].__setitem__(
                "swap_ev_ebitda", value
            ),
        ))
    for multiple in (18.0, 20.0, 22.0):
        cases.append((
            "制造PE",
            f"{multiple:g}×",
            lambda cfg, value=multiple: cfg["finance"].__setitem__(
                "manufacturing_pe", value
            ),
        ))
    for factor in (0.8, 1.0, 1.2):
        def set_prices(cfg: dict, value: float = factor) -> None:
            cfg["swap_business"]["service_fee_rmb_kwh"] = (
                config["swap_business"]["service_fee_rmb_kwh"] * value
            )
            cfg["swap_business"]["battery_rent_rmb_kwh_year"] = (
                config["swap_business"]["battery_rent_rmb_kwh_year"] * value
            )

        cases.append(("服务费+租金", f"基准×{factor:.1f}", set_prices))
    for crf in (0.10, 0.125, 0.15):
        cases.append((
            "资本回报要求CRF",
            f"{crf:.1%}",
            lambda cfg, value=crf: cfg["finance"].__setitem__(
                "capital_recovery_factor", value
            ),
        ))
    for capacity in (250.0, 300.0, 350.0):
        cases.append((
            "巧克力单站规划能力",
            f"{capacity:g}次/日",
            lambda cfg, value=capacity: cfg["stations"]["choco"].__setitem__(
                "planning_daily_capacity", value
            ),
        ))
    for factor in (0.9, 1.0, 1.1):
        cases.append((
            "电池价格",
            f"基准×{factor:.1f}",
            lambda cfg, value=factor: cfg["construction"][
                "battery_price_curve"
            ].__setitem__(
                "base_price_rmb_kwh",
                config["construction"]["battery_price_curve"][
                    "base_price_rmb_kwh"
                ] * value,
            ),
        ))
    # 充电段市占率：悲观/中性/乐观三档（v4.2.2 取消"份额提升实现率"这一中间层，
    # 改为直接给份额；中性档由程序取两档均值派生，不再手工拍值）。
    # 该链条（换电数据反哺充电市占率）证据最弱，只进敏感性，不进可归因价值。
    def set_charge_scenario(cfg: dict, value: str) -> None:
        # 用setdefault：配置段缺失时（如base.toml被外部回滚）仍能构造情景。
        cfg.setdefault("charge_share", {})["scenario"] = value

    for scenario in ("悲观", "中性", "乐观"):
        cases.append((
            "充电段市占率",
            scenario,
            lambda cfg, value=scenario: set_charge_scenario(cfg, value),
        ))
    # 制造净利率差：有换电15%为锚，净利率差0/1.5/3pct对应12%/13.5%/15%。
    for margin_gap in (0.00, 0.015, 0.03):
        cases.append((
            "制造净利率差",
            f"{margin_gap:.1%}",
            lambda cfg, value=margin_gap: cfg["swap_business"].__setitem__(
                "with_swap_manufacturing_net_margin",
                config["swap_business"]["no_swap_manufacturing_net_margin"] + value,
            ),
        ))

    rows: list[dict] = []
    base_value = base.ledger.power_value_2030_with_swap_yi
    for group, label, mutate in cases:
        scenario_config = deepcopy(config)
        mutate(scenario_config)
        candidate = _build_core(scenario_config, base.sourcing.name)
        rows.append({
            "parameter_group": group,
            "scenario": label,
            "heavy_stations": candidate.scale.target_station_demand["heavy"],
            "choco_stations": candidate.scale.target_station_demand["choco"],
            "catl_construction_cash_call_yi": candidate.capex.catl_total_equity_call_yi,
            "required_ebitda_yi": candidate.swap_business.required_ebitda_yi,
            "deliverable_ebitda_yi": candidate.swap_business.ebitda_yi,
            "ebitda_coverage": (
                candidate.swap_business.ebitda_yi
                / candidate.swap_business.required_ebitda_yi
            ),
            "manufacturing_net_profit_yi": (
                candidate.ledger.with_swap_manufacturing.net_profit_yi
            ),
            "attributable_swap_value_yi": (
                candidate.ledger.total_swap_increment_value_yi
            ),
            "power_value_2030_yi": candidate.ledger.power_value_2030_with_swap_yi,
            "power_value_delta_yi": (
                candidate.ledger.power_value_2030_with_swap_yi - base_value
            ),
        })
    return rows

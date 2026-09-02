from __future__ import annotations

from business import build_2026_baseline, build_manufacturing_cases, build_swap_business
from capex import build_capex
from capital_cycle import build_light_asset_scenarios, strategic_exposure_total
from consolidation import build_consolidated_ledger
from decision import build_decision_memos
from group_constraints import build_capital_commitments, build_funding_envelope
from mna import get_sourcing_adjustment
from scale import build_scale
from schemas import ModelSnapshot


def _build_core(config: dict, scenario_name: str | None = None) -> ModelSnapshot:
    sourcing = get_sourcing_adjustment(config, scenario_name)
    scale = build_scale(config, sourcing)
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


def build_model(config: dict, scenario_name: str | None = None) -> ModelSnapshot:
    snapshot = _build_core(config, scenario_name)
    base_power_value = snapshot.ledger.power_value_2030_with_swap_yi
    base_swap_value = snapshot.ledger.total_swap_increment_value_yi
    base_operating_value = snapshot.swap_business.catl_attributable_value_yi
    base_manufacturing_value = snapshot.ledger.manufacturing_swap_margin_effect_value_yi
    base_cash = snapshot.sourcing.cash_consideration_yi
    base_burden = snapshot.sourcing.total_transaction_burden_yi
    comparison: list[dict] = []
    for scenario in config["mna"]["scenarios"]:
        candidate = snapshot if scenario["name"] == snapshot.sourcing.name else _build_core(config, scenario["name"])
        extra_cash = candidate.sourcing.cash_consideration_yi - base_cash
        extra_burden = candidate.sourcing.total_transaction_burden_yi - base_burden
        acquired_asset_value = max(
            0.0, candidate.sourcing.purchase_price_yi - snapshot.sourcing.purchase_price_yi
        )
        incremental_power_value = (
            candidate.ledger.power_value_2030_with_swap_yi - base_power_value
        )
        incremental_swap_value = (
            candidate.ledger.total_swap_increment_value_yi - base_swap_value
        )
        comparison.append({
            "name": candidate.sourcing.name,
            "label": candidate.sourcing.label,
            "price_status": candidate.sourcing.price_status,
            "price_basis": candidate.sourcing.price_basis,
            "cash_consideration_yi": candidate.sourcing.cash_consideration_yi,
            "assumed_debt_yi": candidate.sourcing.assumed_debt_yi,
            "total_transaction_burden_yi": candidate.sourcing.total_transaction_burden_yi,
            "network_acceleration_years": candidate.sourcing.acceleration_years,
            "acquired_network_stations": candidate.sourcing.acquired_network_stations,
            "acquired_battery_bank_gwh": candidate.sourcing.acquired_battery_bank_gwh,
            "remaining_selfbuild_catl_equity_call_yi": candidate.capex.catl_total_equity_call_yi,
            "swap_operating_value_yi": candidate.swap_business.catl_attributable_value_yi,
            "attributable_swap_value_yi": candidate.ledger.total_swap_increment_value_yi,
            "power_value_2030_yi": candidate.ledger.power_value_2030_with_swap_yi,
            "incremental_swap_operating_value_vs_base_yi": (
                candidate.swap_business.catl_attributable_value_yi - base_operating_value
            ),
            "incremental_manufacturing_value_vs_base_yi": (
                candidate.ledger.manufacturing_swap_margin_effect_value_yi
                - base_manufacturing_value
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
                acquired_asset_value + incremental_power_value - extra_cash
            ),
            "incremental_cash_vs_base_yi": extra_cash,
            "incremental_burden_vs_base_yi": extra_burden,
            "incremental_power_value_to_burden": (
                incremental_power_value / extra_burden if extra_burden > 0 else None
            ),
            "physical_station_reuse_assumed": (
                candidate.sourcing.reusable_heavy_stations
                + candidate.sourcing.reusable_choco_stations
            ),
        })
    snapshot.mna_comparison = comparison
    return snapshot

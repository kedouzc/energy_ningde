from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourcingAdjustment:
    name: str
    label: str
    purchase_price_yi: float
    assumed_debt_yi: float
    integration_cost_yi: float
    heavy_share_uplift: float
    passenger_share_uplift: float
    reusable_heavy_stations: int
    reusable_choco_stations: int
    acceleration_years: float
    acquired_network_stations: int
    acquired_battery_bank_gwh: float
    price_basis: str
    price_status: str

    @property
    def cash_consideration_yi(self) -> float:
        return self.purchase_price_yi + self.integration_cost_yi

    @property
    def total_transaction_burden_yi(self) -> float:
        return self.cash_consideration_yi + self.assumed_debt_yi


@dataclass
class ScaleRow:
    year: int
    vehicle_key: str
    vehicle_label: str
    scene: str
    station_group: str
    ev_vehicles_wan: float
    market_swap_vehicles_wan: float
    market_charge_vehicles_wan: float
    catl_swap_vehicles_wan: float
    catl_charge_vehicles_wan: float
    catl_no_swap_vehicles_wan: float
    catl_swap_gwh: float
    catl_charge_gwh: float
    catl_no_swap_gwh: float
    battery_kwh: float
    swap_frequency_per_day: float
    daily_km: float
    usable_range_km: float
    battery_life_years: float


@dataclass
class ScaleResult:
    years: list[int]
    rows: list[ScaleRow]
    operating_stock_by_vehicle_wan: dict[str, float]
    terminal_frequency_by_vehicle: dict[str, float]
    annual_catl_swap_gwh: dict[int, float]
    annual_catl_charge_gwh: dict[int, float]
    annual_catl_no_swap_gwh: dict[int, float]
    target_station_demand: dict[str, int]
    mature_daily_swaps: dict[str, float]
    mature_annual_energy_yi_kwh: dict[str, float]
    station_capacity_diagnostics: dict[str, dict[str, float]]
    route_identity_error: float


@dataclass
class CapexRow:
    year: int
    new_heavy_stations: int
    new_choco_stations: int
    cumulative_heavy_stations: int
    cumulative_choco_stations: int
    vehicle_battery_capex_yi: float
    station_battery_capex_yi: float
    station_body_capex_yi: float
    replacement_gwh: float
    vehicle_replacement_gwh: float
    station_replacement_gwh: float
    replacement_gross_capex_yi: float
    residual_recovery_yi: float
    replacement_net_capex_yi: float
    total_project_capex_yi: float
    catl_equity_call_yi: float


@dataclass
class CapexResult:
    annual: list[CapexRow]
    total_initial_capex_yi: float
    first_replacement_net_capex_yi: float
    lifecycle_capital_base_yi: float
    lifecycle_crf: float
    annual_capital_requirement_yi: float
    mature_annual_depreciation_yi: float
    project_debt_yi: float
    catl_lifecycle_equity_commitment_yi: float
    catl_total_equity_call_yi: float
    catl_peak_equity_call_yi: float
    peak_year: int
    lifecycle_replacement_schedule_yi: dict[int, float]
    station_targets: dict[str, int]
    opening_station_stock: dict[str, int]
    preperiod_station_initial_capex_yi: float
    catl_preperiod_station_equity_investment_yi: float
    battery_price_path_rmb_kwh: dict[int, float]
    lifecycle_factor_by_life: dict[str, float]
    terminal_residual_by_life: dict[str, float]
    retirement_recovery_ratio: float


@dataclass
class SwapBusinessResult:
    annual_energy_yi_kwh: float
    rent_vehicle_gwh: float
    rent_station_external_gwh: float
    rent_eligible_gwh: float
    revenue_yi: float
    service_revenue_yi: float
    battery_rent_yi: float
    arbitrage_yi: float
    ancillary_yi: float
    opex_yi: float
    energy_cost_yi: float
    station_rent_yi: float
    labor_yi: float
    software_opex_yi: float
    ebitda_yi: float
    depreciation_yi: float
    ebit_yi: float
    project_net_profit_yi: float
    catl_attributable_net_profit_yi: float
    enterprise_value_yi: float
    project_equity_value_yi: float
    catl_attributable_value_yi: float
    required_ebitda_yi: float
    forward_to_required_ebitda: float
    project_interest_yi: float
    required_fcff_yi: float
    forward_fcff_yi: float
    minimum_distributable_cash_yi: float
    catl_minimum_distributable_cash_yi: float
    forward_distributable_cash_yi: float
    catl_forward_distributable_cash_yi: float
    catl_initial_equity_investment_yi: float
    catl_cash_yield_on_initial_equity: float
    catl_initial_payback_years: float
    catl_lifecycle_payback_years: float


@dataclass
class ManufacturingResult:
    label: str
    shipments_gwh: float
    revenue_yi: float
    net_margin: float
    net_profit_yi: float
    equity_value_yi: float
    swap_addressable_revenue_yi: float = 0.0


@dataclass
class BaselineResult:
    power_gross_profit_share: float
    power_revenue_2026e_yi: float
    power_net_profit_2026e_yi: float
    power_market_value_2026e_yi: float
    modeled_power_net_profit_2026e_yi: float
    modeled_power_market_value_2026e_yi: float
    non_power_net_profit_2026e_yi: float
    non_power_market_value_2026e_yi: float
    group_net_profit_2026e_yi: float
    group_market_value_2026e_yi: float
    implied_group_pe: float


@dataclass
class ConsolidatedLedger:
    baseline: BaselineResult
    no_swap_manufacturing: ManufacturingResult
    with_swap_manufacturing: ManufacturingResult
    swap_business: SwapBusinessResult
    power_net_profit_2030_no_swap_yi: float
    power_net_profit_2030_with_swap_yi: float
    power_value_2030_no_swap_yi: float
    power_value_2030_with_swap_yi: float
    manufacturing_volume_share_effect_net_profit_yi: float
    manufacturing_volume_share_effect_value_yi: float
    manufacturing_swap_margin_effect_net_profit_yi: float
    manufacturing_swap_margin_effect_value_yi: float
    manufacturing_other_margin_effect_net_profit_yi: float
    manufacturing_other_margin_effect_value_yi: float
    full_manufacturing_scenario_gap_net_profit_yi: float
    full_manufacturing_scenario_gap_value_yi: float
    direct_swap_increment_net_profit_yi: float
    direct_swap_increment_value_yi: float
    total_swap_increment_net_profit_yi: float
    total_swap_increment_value_yi: float
    full_with_vs_pure_manufacturing_gap_net_profit_yi: float
    full_with_vs_pure_manufacturing_gap_value_yi: float
    power_value_growth_vs_2026_modeled_yi: float
    power_value_multiple_vs_2026_modeled: float
    power_value_growth_vs_2026_allocated_yi: float
    power_value_multiple_vs_2026_allocated: float
    attributable_swap_value_to_2026_modeled_power_value: float
    attributable_swap_value_to_2026_allocated_power_value: float
    attributable_swap_value_to_current_group_market_cap: float
    full_gap_to_current_group_market_cap: float
    power_value_cagr_2026_to_2030: float
    value_bridge_error_yi: float


@dataclass
class LightAssetScenario:
    terminal_ownership: float
    sale_proceeds_gross_yi: float
    sale_proceeds_net_yi: float
    managed_aum_yi: float
    manager_fee_revenue_yi: float
    manager_net_profit_yi: float
    manager_value_yi: float
    retained_operating_value_yi: float
    post_exit_recurring_profit_yi: float
    recurring_profit_retention: float
    post_exit_power_value_ex_cash_yi: float
    post_exit_power_value_including_cash_yi: float
    sustainable_value_retention: float
    persistent_power_value_delta_yi: float
    including_cash_power_value_delta_yi: float
    cash_per_persistent_value_lost: float | None
    future_catl_capital_released_yi: float
    data_control_ok: bool
    decision_role: str


@dataclass
class FundingRow:
    year: int
    opening_liquid_resources_yi: float
    projected_net_profit_yi: float
    period_cfo_yi: float
    dividend_payout_ratio: float
    dividend_reserve_yi: float
    buyback_reserve_yi: float
    known_direct_mna_cash_yi: float
    swap_equity_call_yi: float
    annual_investable_funds_generated_yi: float
    closing_liquid_resources_before_uncommitted_strategy_yi: float
    minimum_liquidity_reserve_yi: float
    funds_reserved_for_other_strategy_yi: float
    swap_cash_to_cfo: float


@dataclass
class DecisionMemo:
    owner: str
    status: str
    conclusion: str
    evidence: dict[str, float | str | bool] = field(default_factory=dict)
    key_risk: str = ""


@dataclass
class ModelSnapshot:
    meta: dict[str, Any]
    sourcing: SourcingAdjustment
    scale: ScaleResult
    capex: CapexResult
    swap_business: SwapBusinessResult
    ledger: ConsolidatedLedger
    light_asset: list[LightAssetScenario]
    funding: list[FundingRow]
    capital_commitments: list[dict[str, Any]]
    strategic_exposure_yi: float
    memos: list[DecisionMemo]
    mna_comparison: list[dict[str, Any]] = field(default_factory=list)
    sensitivity: list[dict[str, Any]] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

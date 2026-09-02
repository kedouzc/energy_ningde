from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# 四池/四站型 → 两大类汇总键（重卡=短途+中长途，巧克力=乘用+城配）。
# 与 scale.POOL_STATION_GROUP 同构；schemas 不 import scale（避免环）。
_POOL_CATEGORY = {
    "qiji75_short": "heavy",
    "qiji75_trunk": "heavy",
    "choco25_passenger": "choco",
    "choco35_city": "choco",
}


def _pool_category(pool_key: str) -> str:
    """池键 → 两大类汇总键（heavy/choco）；未知键直接归 heavy 会在汇总中丢数，故显式报错。"""
    if pool_key not in _POOL_CATEGORY:
        raise ValueError(f"未知电池池键 {pool_key}，可用：{list(_POOL_CATEGORY)}")
    return _POOL_CATEGORY[pool_key]


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
    battery_pool: str  # 四池归属（qiji75_short/qiji75_trunk/choco25_passenger/choco35_city）
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
    onboard_battery_kwh: float  # 场景实际装车电量（换电车装机与频次分母同源：重卡342/513、乘用56、城配81）
    swap_frequency_per_day: float
    daily_km: float
    usable_range_km: float
    battery_life_years: float


@dataclass
class ScaleResult:
    """规模测算结果。

    四池（=四站型）独立口径：target_station_demand/mature_daily_swaps/
    mature_annual_energy_yi_kwh/station_capacity_diagnostics 的键均为池键
    （qiji75_short/qiji75_trunk/choco25_passenger/choco35_city）。
    两大类汇总（重卡=短途+中长途、巧克力=乘用+城配）通过 property 派生，
    仅供 v3.2 对照与总表展示（asdict 不序列化 property，快照只含四池键）。
    """

    years: list[int]
    rows: list[ScaleRow]
    operating_stock_by_vehicle_wan: dict[str, float]
    terminal_frequency_by_vehicle: dict[str, float]
    annual_catl_swap_gwh: dict[int, float]
    annual_catl_charge_gwh: dict[int, float]
    annual_catl_no_swap_gwh: dict[int, float]
    target_station_demand: dict[str, int]  # 键=四池/四站型
    mature_daily_swaps: dict[str, float]  # 键=四池/四站型
    mature_annual_energy_yi_kwh: dict[str, float]  # 键=四池/四站型
    station_capacity_diagnostics: dict[str, dict[str, float]]  # 键=四池/四站型
    route_identity_error: float
    battery_pool_life_years: dict[str, float]  # 四池寿命（按池EFC强度推算，非硬编码；键=qiji75_short等）
    city_stock_layer: dict = field(default_factory=dict)  # 城配存量层（高不确定·单列·不并入headline）

    # ---- 两大类汇总（重卡=短途+中长途、巧克力=乘用+城配）：仅派生展示，不落快照 ----

    @property
    def station_demand_by_category(self) -> dict[str, int]:
        """终局站数按两大类汇总（v3.2 对照与总表口径）。"""
        return {
            category: sum(
                count for pool, count in self.target_station_demand.items()
                if _pool_category(pool) == category
            )
            for category in ("heavy", "choco")
        }

    @property
    def daily_swaps_by_category(self) -> dict[str, float]:
        """成熟期日换电次数按两大类汇总。"""
        return {
            category: sum(
                swaps for pool, swaps in self.mature_daily_swaps.items()
                if _pool_category(pool) == category
            )
            for category in ("heavy", "choco")
        }

    @property
    def annual_energy_by_category(self) -> dict[str, float]:
        """成熟期年换电电量（亿kWh）按两大类汇总。"""
        return {
            category: sum(
                energy for pool, energy in self.mature_annual_energy_yi_kwh.items()
                if _pool_category(pool) == category
            )
            for category in ("heavy", "choco")
        }


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
    # 【2026-09-02】三个资本数，三个用途，永不共用：
    #   lifecycle_capital_base_yi —— 门槛口径。各批次锚在自身 t=0 的 PV 之和，×CRF 得年资本要求。
    #     这是「单站 EAC 往上聚合」的结果，比值无量纲，跨年份加总不影响它。
    #   valuation_capital_pv_yi  —— 估值口径。全部 CAPEX 统一折到基年。NPV 只能用这一条。
    #   nominal_total_capex_yi   —— 名义口径。不折现的实际花钱总额，只用于不变量断言。
    valuation_capital_pv_yi: float
    nominal_total_capex_yi: float
    # 折旧口径的会计恒等式三项：累计折旧 == 毛支出 − 期中残值 − 期末残值（容差5%）
    gross_total_capex_yi: float
    interim_residual_yi: float
    terminal_residual_yi: float
    capital_consumed_yi: float
    cumulative_depreciation_yi: float
    capex_path_drift: float
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
    # 4站型独立明细（键=池键）：各池年度新增站排期、期初存量拆分、2026累计目标拆分。
    # CapexRow 的 new_heavy/new_choco_stations 为两大类汇总（重卡=短途+中长途、
    # 巧克力=乘用+城配），4池明细在此查。
    station_schedules_by_pool: dict[str, list[int]]
    opening_station_stock_by_pool: dict[str, int]
    station_2026_targets_by_pool: dict[str, int]
    preperiod_station_initial_capex_yi: float
    catl_preperiod_station_equity_investment_yi: float
    battery_price_path_rmb_kwh: dict[int, float]
    lifecycle_factor_by_life: dict[str, float]
    terminal_residual_by_life: dict[str, float]
    retirement_recovery_ratio: float
    # 【新增｜分池资本】四站型各自的资本口径（键=池键=站型键）：
    # 全周期资本底座、成熟期年折旧、终局初装 CAPEX。四池之和与对应总量字段恒等
    # （capex.py 构建时断言校验），供 report 分站型列示与 business 分池推演使用。
    unit_vintage: list[dict] = field(default_factory=list)
    lifecycle_capital_base_by_pool: dict[str, float] = field(default_factory=dict)
    mature_annual_depreciation_by_pool: dict[str, float] = field(default_factory=dict)
    total_initial_capex_by_pool: dict[str, float] = field(default_factory=dict)


@dataclass
class PoolOperations:
    """四站型（池）各自独立的经营链与现金回报指标（v4.4 分站型列示的数据源）。

    口径：每个站型视作独立项目公司——收入、现金OPEX 线性分池；折旧/利息/债务按
    该池资本底座派生；净利润、可分派现金的 max(0,·) 下限在池内生效（亏损池不
    产生税盾抵扣）。SwapBusinessResult 的总量字段=四池之和（business.py 保证）。
    """
    # 经营链（报表 ①—⑯ 节点）
    annual_swaps_yi: float
    annual_energy_yi_kwh: float
    service_revenue_yi: float
    rent_vehicle_gwh: float
    station_battery_gwh: float
    station_external_rent_gwh: float
    rent_eligible_gwh: float
    battery_rent_yi: float
    arbitrage_yi: float
    ancillary_yi: float
    revenue_yi: float
    charged_energy_yi_kwh: float
    energy_cost_yi: float
    station_rent_yi: float
    labor_yi: float
    software_opex_yi: float
    insurance_yi: float
    pooling_maintenance_yi: float
    warehouse_logistics_yi: float
    opex_yi: float
    ebitda_yi: float
    # 资本与回报（依赖 capex 分池资本口径）
    depreciation_yi: float
    interest_yi: float
    pre_tax_profit_yi: float
    project_net_profit_yi: float
    catl_net_profit_yi: float
    enterprise_value_yi: float
    project_equity_value_yi: float
    catl_value_yi: float
    required_fcff_yi: float
    minimum_distributable_yi: float
    catl_minimum_distributable_yi: float
    forward_fcff_yi: float
    forward_distributable_yi: float
    catl_forward_distributable_yi: float
    catl_initial_equity_yi: float
    catl_lifecycle_equity_yi: float


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
    pre_tax_profit_yi: float
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
    # v4.3 新增：辅助服务分列。三项性质不同，**不可相加**：
    #   · 容量补偿：站建成即可申报，"存在就有收益"，无条件计入；
    #   · 需求响应 / 调频：须实际提供服务才有收益，且二者争夺同一份可调容量，
    #     同一块电池同一时段只能干一件事 → 全局孰高，只有胜出方计入。
    # 故 ancillary_yi = 容量补偿 + max(需求响应, 调频)。两个候选项以 _candidate_
    # 命名并配 ancillary_counted_item 标明本情景实际计入了哪一项，防止误加。
    capacity_compensation_yi: float = 0.0
    demand_response_candidate_yi: float = 0.0
    frequency_regulation_candidate_yi: float = 0.0
    ancillary_counted_item: str = ""
    # v4.4 新增：DCF 交叉验证（回答"18× 凭什么"这个报告里最容易被打穿的地方）。
    # 做法：把项目自己的 FCFF 按两条折现口径资本化，反算它支持多少倍 EV/EBITDA，
    # 与 base.toml 里拍的 swap_ev_ebitda 并排放。差额不是误差，是**押注**——
    # 押市场最终把这类资产放进基建—平台倍数阶梯的哪一档，这一段判断该写进正文而不是藏在乘数里。
    # 口径A（与门槛同源）：EV = FCFF ÷ CRF。CRF 是设门槛用的期望收益率年金因子（10–15% 中值），
    #   所以这条与 required_ebitda / 覆盖倍数完全同源，是模型内部最自洽的一条。
    # 口径B（成本线）：EV = FCFF × 年金因子(WACC, 分析期)。WACC 是成本下限，故本口径给出上界。
    # 注意：两条都用**成熟期**FCFF 资本化，未扣建设期爬坡，因此都偏乐观；
    #   带爬坡的逐年 DCF 需等年度化做完，届时隐含倍数只会更低。
    dcf_valuation_capital_pv_yi: float = 0.0
    dcf_valuation_debt_yi: float = 0.0
    dcf_legacy_debt_yi: float = 0.0
    dcf_ev_at_crf_yi: float = 0.0
    dcf_ev_at_wacc_yi: float = 0.0
    dcf_implied_multiple_at_crf: float = 0.0
    dcf_implied_multiple_at_wacc: float = 0.0
    dcf_multiple_premium: float = 0.0          # 拍的倍数 ÷ 口径A隐含倍数
    dcf_npv_at_crf_yi: float = 0.0             # 口径A EV − 全周期资本底座
    dcf_catl_value_at_crf_yi: float = 0.0      # 口径A 下 CATL 归属权益价值
    dcf_catl_value_gap_yi: float = 0.0         # 倍数法归属 − 口径A归属 ＝ 押注的那部分
    # v4.3 新增：电池银行侧费率三项（蔚能四项成本对照框架补齐）
    battery_asset_yi: float = 0.0
    equipment_asset_yi: float = 0.0
    insurance_yi: float = 0.0
    pooling_maintenance_yi: float = 0.0
    warehouse_logistics_yi: float = 0.0
    # v4.3 新增：四站型分池经营明细（键=池键）。总量字段=四池之和，
    # report 的 operating_table/cash_return_table 分站型列直接读这里。
    pool_operations: dict[str, PoolOperations] = field(default_factory=dict)


@dataclass
class ManufacturingResult:
    label: str
    shipments_gwh: float
    revenue_yi: float
    net_margin: float
    net_profit_yi: float
    equity_value_yi: float
    swap_addressable_revenue_yi: float = 0.0
    # 换电段+更换循环×外部权益口径的锁定订单装机；40%内部权益部分价值已在运营线确认。
    swap_locked_gwh: float = 0.0


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
    manufacturing_swap_locked_volume_effect_net_profit_yi: float
    manufacturing_swap_locked_volume_effect_value_yi: float
    manufacturing_charge_share_effect_net_profit_yi: float
    manufacturing_charge_share_effect_value_yi: float
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
    market_share: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

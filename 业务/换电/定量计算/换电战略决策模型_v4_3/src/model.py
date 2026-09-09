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
    life_mode: str = "derived",
) -> ModelSnapshot:
    sourcing = get_sourcing_adjustment(config, scenario_name)
    scale = build_scale(config, sourcing, life_mode)
    capex = build_capex(config, scale, sourcing)
    baseline = build_2026_baseline(config)
    swap = build_swap_business(config, scale, capex)
    no_swap, with_swap = build_manufacturing_cases(config, scale, capex)
    ledger = build_consolidated_ledger(config, baseline, no_swap, with_swap, swap)
    light = build_light_asset_scenarios(config, scale, capex, swap, ledger)
    funding = build_funding_envelope(config, capex, sourcing)
    commitments = build_capital_commitments(config)
    exposure = strategic_exposure_total(config)
    # 市占率（程序自身口径）：分母=电车动力电池装机=充电装车+换电装车（scale 年算）。
    # 换电主业服务车主，相关"电车动力电池装机"即本程序每年算的充电+换电装车数；
    # 外部全国数仅作交叉校验，不充当分母（见 base.toml [national_battery_market]）。
    nbm = config.get("national_battery_market", {})
    market_share: dict = {}
    for yr in scale.annual_catl_charge_gwh:
        ch = scale.annual_catl_charge_gwh.get(yr, 0.0)
        sw = scale.annual_catl_swap_gwh.get(yr, 0.0)
        tot = ch + sw
        market_share[str(yr)] = {
            "catl_charge_gwh": round(ch, 2),
            "catl_swap_gwh": round(sw, 2),
            "catl_ev_battery_total_gwh": round(tot, 2),
            "swap_share_of_catl_ev_battery": round(sw / tot, 4) if tot else None,
        }
    if nbm:
        np25 = nbm.get("power_battery_install_gwh_2025")
        np30 = nbm.get("power_battery_install_gwh_2030")
        st25 = nbm.get("storage_install_gwh_2025")
        st30 = nbm.get("storage_install_gwh_2030")
        years = list(scale.annual_catl_charge_gwh.keys())
        y0, y1 = min(years), max(years)
        t0 = scale.annual_catl_charge_gwh.get(y0, 0.0) + scale.annual_catl_swap_gwh.get(y0, 0.0)
        t1 = scale.annual_catl_charge_gwh.get(y1, 0.0) + scale.annual_catl_swap_gwh.get(y1, 0.0)
        bank = swap.rent_vehicle_gwh
        station_bank = sum(p.station_battery_gwh for p in swap.pool_operations.values())
        market_share["cross_check_vs_national"] = {
            "national_power_install_gwh_2025": np25,
            "national_power_install_gwh_2030": np30,
            f"catl_ev_battery_modeled_{y0}_gwh": round(t0, 2),
            f"catl_ev_battery_modeled_{y1}_gwh": round(t1, 2),
            "catl_modeled_share_of_national_2025": round(t0 / np25, 4) if np25 else None,
            "catl_modeled_share_of_national_2030": round(t1 / np30, 4) if np30 else None,
            "national_storage_install_gwh_2025": st25,
            "national_storage_install_gwh_2030": st30,
            # 车端装机：参与电网调度的能力有限（电池在车上、不常驻站），只作注释。
            "swap_battery_bank_gwh": round(bank, 2),
            # 站内周转装机：常驻站、可参与电网调度/储能，才是"分布式储能电网"的有效底数。
            "swap_station_battery_gwh": round(station_bank, 2),
            # 装机相当于多少储能：分子改用站内周转装机（车端装机的影响已在年换电量÷全社会用电量体现）。
            "swap_station_battery_share_of_national_storage_2025": round(station_bank / st25, 4) if st25 else None,
            "swap_station_battery_share_of_national_storage_2030": round(station_bank / st30, 4) if st30 else None,
        }
    # 全社会用电量：换电交易量（年换电量）的市场分母。换电网络的本质是分布式储能电网，
    # 所以交易量除了对储能装机，还要对全社会用电量做量级对照——两者单位统一为亿kWh。
    # 分母同取自 config（外部信源只登记在 audit/信源审计台账.md「信源索引（机读）」）。
    npm = config.get("national_power_market", {})
    if npm:
        el_now = npm.get("society_electricity_yi_kwh_latest")
        el_30 = npm.get("society_electricity_yi_kwh_2030")
        energy = swap.annual_energy_yi_kwh
        market_share["cross_check_vs_society_electricity"] = {
            "national_society_electricity_yi_kwh_latest": el_now,
            "national_society_electricity_yi_kwh_2030": el_30,
            "swap_annual_energy_yi_kwh": round(energy, 2),
            "swap_energy_share_of_society_electricity_latest": round(energy / el_now, 6) if el_now else None,
            "swap_energy_share_of_society_electricity_2030": round(energy / el_30, 6) if el_30 else None,
        }
    memos = build_decision_memos(config, scale, capex, swap, ledger, light, funding, exposure)
    return ModelSnapshot(
        meta={
            **config["meta"],
            "wacc": config["finance"]["wacc"],
            "wacc_basis": "蔚来换电ABS融资基准，毛估估直接采用，不作CAPM推导",
            "generated_numbers_only": True,
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
        market_share=market_share,
    )


def build_scenarios(config: dict) -> dict[str, "ModelSnapshot"]:
    """按 base.toml [drivers] 声明的驱动因子组合，整体重跑三个情景。

    情景的**定义**与**施加**只有一个家：configs/base.toml 的 [drivers] 段
    （读取与写入走 config_loader.apply_scenario）。
    run.py 与 build.py 都必须走这里，不许各自另建一套——此前两边各跑一遍
    private_scenario，是「一件事两个家」的又一例（DECISIONS 2026-09-02）。

    纪律：要么全打包按情景跑，要么全跑中性，不许散装。
    中性档严格等于模型基线（apply_scenario 会校验）。
    """
    from config_loader import (
        SCENARIO_ORDER,
        apply_scenario,
        cloned_config,
        load_drivers,
    )

    drivers = load_drivers(config)
    out: dict[str, ModelSnapshot] = {}
    for tier in SCENARIO_ORDER:
        scenario_config = cloned_config(config)
        kwargs = apply_scenario(scenario_config, drivers, tier)
        out[tier] = build_model(scenario_config, **kwargs)
    return out


def build_model(
    config: dict,
    scenario_name: str | None = None,
    life_mode: str = "derived",
) -> ModelSnapshot:
    """life_mode：电池寿命口径，"derived"（基准）或 "legacy_v32"（附录对照重跑）。

    私家车分档渗透率已由 [drivers.private_penetration] 按情景档写入场景活值，
    随 config 走，不再是独立关键字参数。
    """
    snapshot = _build_core(config, scenario_name, life_mode)
    reference = _build_core(
        config, config["mna"]["comparison_scenario_name"], life_mode
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
            else _build_core(config, scenario["name"], life_mode)
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
            cfg["swap_business"]["battery_rent_rmb_kwh_month"] = (
                config["swap_business"]["battery_rent_rmb_kwh_month"] * value
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
        # 【4站型适配】"巧克力单站规划能力"敏感性同时作用于乘用站与城配站
        # （两类站体参数同源复用，敏感性应联动，避免只动一类导致池间口径漂移）。
        def set_choco_capacity(cfg: dict, value: float = capacity) -> None:
            for station_key in ("choco25_passenger", "choco35_city"):
                cfg["stations"][station_key]["planning_daily_capacity"] = value

        cases.append((
            "巧克力单站规划能力",
            f"{capacity:g}次/日",
            set_choco_capacity,
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
    # 逐车型三档份额统一声明在 base.toml 的 [drivers.charge_share]（一个家）；
    # 本处按档把各车型活值写入 config["charge_share"]，供 _charge_share() 直接读。
    # 该链条（换电数据反哺充电市占率）证据最弱，只进敏感性，不进可归因价值。
    def set_charge_scenario(cfg: dict, value: str) -> None:
        # 按档把逐车型份额写入 config["charge_share"]（活值），与 apply_scenario 同口径；
        # 配置段缺失（如被外部回滚）时静默跳过，保证可构造情景。
        spread = cfg.get("drivers", {}).get("charge_share", {}).get(value)
        if not isinstance(spread, dict):
            return
        cs = cfg.setdefault("charge_share", {})
        for vtype, share in spread.items():
            cs[vtype] = share

    for scenario in ("悲观", "中性", "乐观"):
        cases.append((
            "充电段市占率",
            scenario,
            lambda cfg, value=scenario: set_charge_scenario(cfg, value),
        ))
    # 制造净利率差：有换电净利率 = 无换电12.5% + 上浮；三档 0/1.0/2.5pct 对应 12.5%/13.5%/15%（悲观无保护/中性+1pct/乐观基准）。
    for margin_gap in (0.00, 0.01, 0.025):
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
            "heavy_stations": candidate.scale.station_demand_by_category["heavy"],
            "choco_stations": candidate.scale.station_demand_by_category["choco"],
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

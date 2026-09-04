from __future__ import annotations

import math
from collections import defaultdict

from derived import (
    annual_battery_price_path,
    battery_price_rmb_kwh,
    lifecycle_factors,
    retirement_recovery_ratio,
)
from schemas import CapexResult, CapexRow, ScaleResult, SourcingAdjustment


def _capex_yi(gwh: float, price_rmb_kwh: float) -> float:
    return gwh * price_rmb_kwh / 100.0


def _station_schedule(
    opening_2025: int,
    cumulative_target_2026: int,
    cumulative_target_2028: int,
) -> list[int]:
    """直算2026—2028新增站数；2029—2030不再建站。"""
    if not 0 <= opening_2025 <= cumulative_target_2026 <= cumulative_target_2028:
        raise ValueError(
            "站数应满足：2025年末存量 <= 2026累计目标 <= 2028终局目标"
        )

    new_2026 = cumulative_target_2026 - opening_2025
    new_2027_to_2028 = cumulative_target_2028 - cumulative_target_2026
    new_2027 = round(new_2027_to_2028 / 2)
    new_2028 = new_2027_to_2028 - new_2027
    return [new_2026, new_2027, new_2028, 0, 0]


def _event_year_weights(event_year: float) -> list[tuple[int, float]]:
    """把均匀投放形成的非整数寿命事件分配到相邻两个年度。"""
    early = math.floor(event_year + 1e-9)
    late = math.ceil(event_year - 1e-9)
    if early == late:
        return [(early, 1.0)]
    late_weight = event_year - early
    return [(early, 1.0 - late_weight), (late, late_weight)]


def build_capex(
    config: dict,
    scale: ScaleResult,
    sourcing: SourcingAdjustment,
) -> CapexResult:
    del sourcing  # 物理复用已在scale的站数需求中反映。
    years = config["construction"]["years"]
    completion_year = config["construction"]["station_network_completion_year"]
    if years != [2026, 2027, 2028, 2029, 2030] or completion_year != 2028:
        raise ValueError("v4.1建站排期固定为2026—2028建设、2029—2030零新增")
    first_year_targets = config["construction"]["station_2026_cumulative_targets"]
    opening_stations = config["construction"]["opening_2025_stations"]
    station_schedules = {
        group: _station_schedule(
            opening_stations[group],
            first_year_targets[group],
            scale.target_station_demand[group],
        )
        for group in ("heavy", "choco")
    }
    rows_by_year = {year: [row for row in scale.rows if row.year == year] for year in years}

    # 2025年末存量站属于终局总资产，但不属于2026—2030新增现金支出。
    # 为避免仅因时点校准而改变总项目CAPEX，按2026等效价格纳入资产底座与生命周期。
    battery_cohorts: list[dict[str, float | int | str]] = []
    preperiod_station_battery_gwh = 0.0
    preperiod_station_body_capex = 0.0
    opening_price = battery_price_rmb_kwh(config, years[0])
    for group in ("heavy", "choco"):
        station = config["stations"][group]
        count = opening_stations[group]
        gwh = count * station["inventory_blocks"] * station["block_kwh"] / 1e6
        preperiod_station_battery_gwh += gwh
        preperiod_station_body_capex += (
            count * station["station_body_capex_wan"] / 1e4
        )
        if gwh:
            battery_cohorts.append({
                "kind": "station",
                "install_year": years[0],
                "gwh": gwh,
                "life": station["battery_life_years"],
                "initial_capex": _capex_yi(gwh, opening_price),
            })
    preperiod_station_initial_capex = (
        preperiod_station_body_capex
        + _capex_yi(preperiod_station_battery_gwh, opening_price)
    )

    # 每个批次保存自己的寿命与初装价格；全周期资本、折旧和年度更新共用同一批次。
    initial_components: dict[int, dict[str, float]] = {}
    for index, year in enumerate(years):
        price = battery_price_rmb_kwh(config, year)
        vehicle_gwh = sum(row.catl_swap_gwh for row in rows_by_year[year])
        for row in rows_by_year[year]:
            if row.catl_swap_gwh:
                battery_cohorts.append({
                    "kind": "vehicle",
                    "install_year": year,
                    "gwh": row.catl_swap_gwh,
                    "life": row.battery_life_years,
                    "initial_capex": _capex_yi(row.catl_swap_gwh, price),
                })
        station_battery_gwh = 0.0
        station_body_capex = 0.0
        for group in ("heavy", "choco"):
            station = config["stations"][group]
            count = station_schedules[group][index]
            gwh = count * station["inventory_blocks"] * station["block_kwh"] / 1e6
            station_battery_gwh += gwh
            station_body_capex += count * station["station_body_capex_wan"] / 1e4
            if gwh:
                battery_cohorts.append({
                    "kind": "station",
                    "install_year": year,
                    "gwh": gwh,
                    "life": station["battery_life_years"],
                    "initial_capex": _capex_yi(gwh, price),
                })
        initial_components[year] = {
            "vehicle": _capex_yi(vehicle_gwh, price),
            "station_battery": _capex_yi(station_battery_gwh, price),
            "station_body": station_body_capex,
        }

    horizon = config["finance"]["model_horizon_years"]
    final_schedule_year = years[-1] + horizon
    recovery_ratio = retirement_recovery_ratio(config)
    replacement_gwh: dict[int, float] = defaultdict(float)
    vehicle_replacement_gwh: dict[int, float] = defaultdict(float)
    station_replacement_gwh: dict[int, float] = defaultdict(float)
    replacement_net: dict[int, float] = defaultdict(float)
    replacement_gross: dict[int, float] = defaultdict(float)
    replacement_residual: dict[int, float] = defaultdict(float)
    for cohort in battery_cohorts:
        cycle = 1
        while cycle * float(cohort["life"]) < horizon - 1e-9:
            event_year = int(cohort["install_year"]) + cycle * float(cohort["life"])
            for replacement_year, weight in _event_year_weights(event_year):
                if replacement_year > final_schedule_year:
                    continue
                gwh = float(cohort["gwh"]) * weight
                gross = _capex_yi(gwh, battery_price_rmb_kwh(config, replacement_year))
                recovery = gross * recovery_ratio
                replacement_gwh[replacement_year] += gwh
                if cohort["kind"] == "vehicle":
                    vehicle_replacement_gwh[replacement_year] += gwh
                else:
                    station_replacement_gwh[replacement_year] += gwh
                replacement_gross[replacement_year] += gross
                replacement_residual[replacement_year] += recovery
                replacement_net[replacement_year] += gross - recovery
            cycle += 1

    finance = config["finance"]
    equity_factor = (1.0 - finance["debt_ratio"]) * finance["construction_ownership"]
    annual: list[CapexRow] = []
    cumulative_heavy = opening_stations["heavy"]
    cumulative_choco = opening_stations["choco"]
    for index, year in enumerate(years):
        components = initial_components[year]
        total = sum(components.values()) + replacement_net[year]
        cumulative_heavy += station_schedules["heavy"][index]
        cumulative_choco += station_schedules["choco"][index]
        annual.append(CapexRow(
            year=year,
            new_heavy_stations=station_schedules["heavy"][index],
            new_choco_stations=station_schedules["choco"][index],
            cumulative_heavy_stations=cumulative_heavy,
            cumulative_choco_stations=cumulative_choco,
            vehicle_battery_capex_yi=components["vehicle"],
            station_battery_capex_yi=components["station_battery"],
            station_body_capex_yi=components["station_body"],
            replacement_gwh=replacement_gwh[year],
            vehicle_replacement_gwh=vehicle_replacement_gwh[year],
            station_replacement_gwh=station_replacement_gwh[year],
            replacement_gross_capex_yi=replacement_gross[year],
            residual_recovery_yi=replacement_residual[year],
            replacement_net_capex_yi=replacement_net[year],
            total_project_capex_yi=total,
            catl_equity_call_yi=total * equity_factor,
        ))

    lifecycle_capital = 0.0
    battery_depreciation = 0.0
    factor_samples: dict[str, float] = {}
    residual_samples: dict[str, float] = {}
    for cohort in battery_cohorts:
        factors = lifecycle_factors(
            config, float(cohort["install_year"]), float(cohort["life"])
        )
        initial_capex = float(cohort["initial_capex"])
        lifecycle_capital += initial_capex * factors.capital_multiplier
        battery_depreciation += (
            initial_capex
            * (factors.capital_multiplier - factors.terminal_residual_ratio)
            / float(cohort["life"])
        )
        label = f"{float(cohort['life']):g}年"
        if int(cohort["install_year"]) == years[0]:
            factor_samples[label] = factors.capital_multiplier
            residual_samples[label] = factors.terminal_residual_ratio

    station_body_total = (
        preperiod_station_body_capex
        + sum(item["station_body"] for item in initial_components.values())
    )
    lifecycle_capital += station_body_total
    mature_depreciation = battery_depreciation + station_body_total / horizon
    crf = finance["capital_recovery_factor"]
    total_initial = (
        preperiod_station_initial_capex
        + sum(sum(item.values()) for item in initial_components.values())
    )
    peak = max(annual, key=lambda row: row.catl_equity_call_yi)
    return CapexResult(
        annual=annual,
        total_initial_capex_yi=total_initial,
        first_replacement_net_capex_yi=sum(replacement_net[year] for year in years),
        lifecycle_capital_base_yi=lifecycle_capital,
        lifecycle_crf=crf,
        annual_capital_requirement_yi=lifecycle_capital * crf,
        mature_annual_depreciation_yi=mature_depreciation,
        project_debt_yi=lifecycle_capital * finance["debt_ratio"],
        catl_lifecycle_equity_commitment_yi=(
            lifecycle_capital
            * (1.0 - finance["debt_ratio"])
            * finance["construction_ownership"]
        ),
        catl_total_equity_call_yi=sum(row.catl_equity_call_yi for row in annual),
        catl_peak_equity_call_yi=peak.catl_equity_call_yi,
        peak_year=peak.year,
        lifecycle_replacement_schedule_yi={
            year: replacement_net[year]
            for year in sorted(replacement_net)
            if replacement_net[year]
        },
        station_targets=scale.target_station_demand.copy(),
        opening_station_stock=opening_stations.copy(),
        preperiod_station_initial_capex_yi=preperiod_station_initial_capex,
        catl_preperiod_station_equity_investment_yi=(
            preperiod_station_initial_capex * equity_factor
        ),
        battery_price_path_rmb_kwh=annual_battery_price_path(config),
        lifecycle_factor_by_life=factor_samples,
        terminal_residual_by_life=residual_samples,
        retirement_recovery_ratio=recovery_ratio,
    )

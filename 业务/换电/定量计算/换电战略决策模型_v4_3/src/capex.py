from __future__ import annotations

import math
from collections import defaultdict

from derived import (
    annual_battery_price_path,
    battery_price_rmb_kwh,
    lifecycle_factors,
    retirement_recovery_ratio,
)
from scale import BATTERY_POOLS, POOL_STATION_GROUP, split_group_station_count
from schemas import CapexResult, CapexRow, ScaleResult, SourcingAdjustment


def _capex_yi(gwh: float, price_rmb_kwh: float) -> float:
    return gwh * price_rmb_kwh / 100.0


def _append_station_pool_cohorts(
    battery_cohorts: list[dict[str, float | int | str]],
    config: dict,
    scale: ScaleResult,
    pool_key: str,
    count: int,
    install_year: int,
    price: float,
) -> float:
    """【重构｜4站型】把一个（池×年份×站数）的站内电池批次直接登记为该池 cohort。

    4站型独立架构下站内电池天然按池归属（池键=站型键），不再需要从大类按
    需求份额拆分；站内电池寿命=所属池寿命（池内EFC分母已含站内库存，
    装车与站内电池同池同寿命）。返回该批次总GWh（用于站内电池CAPEX汇总）。
    """
    if count <= 0:
        return 0.0
    station = config["stations"][pool_key]
    total_gwh = count * station["inventory_blocks"] * station["block_kwh"] / 1e6
    battery_cohorts.append({
        "kind": "station",
        "install_year": install_year,
        "gwh": total_gwh,
        "life": scale.battery_pool_life_years[pool_key],
        "initial_capex": _capex_yi(total_gwh, price),
        "battery_pool": pool_key,
    })
    return total_gwh


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
    # 【重构｜池级显式】2025存量站/2026累计目标的池级拆分：
    # - 骐骥（heavy）：组级总量按短途/中长途池换电需求份额程序拆分（最大余数法），
    #   拆分规则与 scale 站数反推一致；
    # - 巧克力（choco）：池级显式配置（乘用/城配分列），组级值仅作总量校验——
    #   城配35#专门站2025存量为0、2026累计目标140（大湾区建设计划，catl.com/news/9884），
    #   乘用2025存量1020、2026累计目标=3000−140=2860（倒挤）。
    choco_opening_by_pool = config["construction"]["opening_2025_choco_by_pool"]
    choco_target2026_by_pool = config["construction"]["station_2026_choco_targets_by_pool"]
    if sum(choco_opening_by_pool.values()) != opening_stations["choco"]:
        raise ValueError(
            "opening_2025_choco_by_pool 之和应等于 opening_2025_stations.choco"
        )
    if sum(choco_target2026_by_pool.values()) != first_year_targets["choco"]:
        raise ValueError(
            "station_2026_choco_targets_by_pool 之和应等于 station_2026_cumulative_targets.choco"
        )
    pool_demand = scale.mature_daily_swaps
    opening_by_pool: dict[str, int] = dict(choco_opening_by_pool)
    target2026_by_pool: dict[str, int] = dict(choco_target2026_by_pool)
    opening_by_pool.update(
        split_group_station_count(opening_stations["heavy"], "heavy", pool_demand)
    )
    target2026_by_pool.update(
        split_group_station_count(first_year_targets["heavy"], "heavy", pool_demand)
    )
    station_schedules = {
        pool_key: _station_schedule(
            opening_by_pool[pool_key],
            target2026_by_pool[pool_key],
            scale.target_station_demand[pool_key],
        )
        for pool_key in BATTERY_POOLS
    }
    rows_by_year = {year: [row for row in scale.rows if row.year == year] for year in years}

    # 2025年末存量站属于终局总资产，但不属于2026—2030新增现金支出。
    # 为避免仅因时点校准而改变总项目CAPEX，按2026等效价格纳入资产底座与生命周期。
    battery_cohorts: list[dict[str, float | int | str]] = []
    preperiod_station_battery_gwh = 0.0
    preperiod_station_body_capex = 0.0
    # 【新增｜分池资本】存量站体/站内电池按池累计（四池之和=上方总量，构建后断言校验）。
    preperiod_body_by_pool = {pk: 0.0 for pk in BATTERY_POOLS}
    preperiod_battery_gwh_by_pool = {pk: 0.0 for pk in BATTERY_POOLS}
    opening_price = battery_price_rmb_kwh(config, years[0])
    for pool_key in BATTERY_POOLS:
        count = opening_by_pool[pool_key]
        pool_body_capex = count * config["stations"][pool_key]["station_body_capex_wan"] / 1e4
        preperiod_station_body_capex += pool_body_capex
        preperiod_body_by_pool[pool_key] += pool_body_capex
        # 【重构｜4站型】存量站内电池直接按池登记cohort，用所属池寿命。
        pool_battery_gwh = _append_station_pool_cohorts(
            battery_cohorts, config, scale, pool_key, count, years[0], opening_price
        )
        preperiod_station_battery_gwh += pool_battery_gwh
        preperiod_battery_gwh_by_pool[pool_key] += pool_battery_gwh
    preperiod_station_initial_capex = (
        preperiod_station_body_capex
        + _capex_yi(preperiod_station_battery_gwh, opening_price)
    )
    preperiod_initial_by_pool = {
        pk: preperiod_body_by_pool[pk]
        + _capex_yi(preperiod_battery_gwh_by_pool[pk], opening_price)
        for pk in BATTERY_POOLS
    }

    # 每个批次保存自己的寿命与初装价格；全周期资本、折旧和年度更新共用同一批次。
    initial_components: dict[int, dict[str, float]] = {}
    # 【新增｜分池资本】年度初装CAPEX按池拆分（车辆电池按 row.battery_pool 归属）。
    initial_components_by_pool: dict[int, dict[str, dict[str, float]]] = {}
    for index, year in enumerate(years):
        price = battery_price_rmb_kwh(config, year)
        vehicle_gwh = sum(row.catl_swap_gwh for row in rows_by_year[year])
        vehicle_gwh_by_pool = {pk: 0.0 for pk in BATTERY_POOLS}
        for row in rows_by_year[year]:
            if row.catl_swap_gwh:
                battery_cohorts.append({
                    "kind": "vehicle",
                    "install_year": year,
                    "gwh": row.catl_swap_gwh,
                    # derived 模式下 row 已继承所属池寿命（scale 回填）。
                    "life": row.battery_life_years,
                    "initial_capex": _capex_yi(row.catl_swap_gwh, price),
                    "battery_pool": row.battery_pool,
                })
                vehicle_gwh_by_pool[row.battery_pool] += row.catl_swap_gwh
        station_battery_gwh = 0.0
        station_body_capex = 0.0
        station_battery_gwh_by_pool = {pk: 0.0 for pk in BATTERY_POOLS}
        station_body_by_pool = {pk: 0.0 for pk in BATTERY_POOLS}
        for pool_key in BATTERY_POOLS:
            count = station_schedules[pool_key][index]
            pool_body_capex = (
                count * config["stations"][pool_key]["station_body_capex_wan"] / 1e4
            )
            station_body_capex += pool_body_capex
            station_body_by_pool[pool_key] += pool_body_capex
            # 【重构｜4站型】站内电池直接按池登记cohort，用所属池寿命。
            pool_battery_gwh = _append_station_pool_cohorts(
                battery_cohorts, config, scale, pool_key, count, year, price
            )
            station_battery_gwh += pool_battery_gwh
            station_battery_gwh_by_pool[pool_key] += pool_battery_gwh
        initial_components[year] = {
            "vehicle": _capex_yi(vehicle_gwh, price),
            "station_battery": _capex_yi(station_battery_gwh, price),
            "station_body": station_body_capex,
        }
        initial_components_by_pool[year] = {
            pk: {
                "vehicle": _capex_yi(vehicle_gwh_by_pool[pk], price),
                "station_battery": _capex_yi(station_battery_gwh_by_pool[pk], price),
                "station_body": station_body_by_pool[pk],
            }
            for pk in BATTERY_POOLS
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
    # 【重构｜4站型】两大类累计站数由四池汇总派生（重卡=短途+中长途、巧克力=乘用+城配）。
    cumulative_by_pool = dict(opening_by_pool)
    for index, year in enumerate(years):
        components = initial_components[year]
        total = sum(components.values()) + replacement_net[year]
        for pool_key in BATTERY_POOLS:
            cumulative_by_pool[pool_key] += station_schedules[pool_key][index]
        heavy_pools = [pk for pk in BATTERY_POOLS if POOL_STATION_GROUP[pk] == "heavy"]
        choco_pools = [pk for pk in BATTERY_POOLS if POOL_STATION_GROUP[pk] == "choco"]
        annual.append(CapexRow(
            year=year,
            new_heavy_stations=sum(station_schedules[pk][index] for pk in heavy_pools),
            new_choco_stations=sum(station_schedules[pk][index] for pk in choco_pools),
            cumulative_heavy_stations=sum(cumulative_by_pool[pk] for pk in heavy_pools),
            cumulative_choco_stations=sum(cumulative_by_pool[pk] for pk in choco_pools),
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
    # 【新增｜分池资本】全周期资本底座/电池折旧按池累计（cohort 已带 battery_pool 归属）。
    lifecycle_capital_by_pool = {pk: 0.0 for pk in BATTERY_POOLS}
    battery_depreciation_by_pool = {pk: 0.0 for pk in BATTERY_POOLS}
    factor_samples: dict[str, float] = {}
    residual_samples: dict[str, float] = {}
    # 【新增｜单站 vintage 表】按 (池 × 装机年) 留存单位经济性，供报告下钻与「窗口成本」章。
    unit_vintage: list[dict[str, float | str]] = []
    for cohort in battery_cohorts:
        factors = lifecycle_factors(
            config, float(cohort["install_year"]), float(cohort["life"])
        )
        initial_capex = float(cohort["initial_capex"])
        life = float(cohort["life"])
        lifecycle_capital += initial_capex * factors.capital_multiplier
        # 【修正 2026-09-02｜折旧分子】原式用 (capital_multiplier − terminal_residual)/life：
        # capital_multiplier 是「15 年全周期要花多少钱」的 PV 倍数——那是 EAC 的分子；
        # 折旧要回答的是「现在装着的这一代电池每年掉多少价」，只与本代有关。
        # 两者共用分子 ⇒ 把 15 年要买的 N 代电池压进一代寿命里摊完，累计折旧达名义支出的 2.28 倍。
        # 正确式：本代初装 × (1 − 退役回收率) / 本代寿命。EAC 与折旧从此不共用分子。
        # 见 DECISIONS.md「2026-09-02 · 成熟期折旧用错了分子」。
        battery_depreciation += initial_capex * (1.0 - recovery_ratio) / life
        pool_key = str(cohort["battery_pool"])
        lifecycle_capital_by_pool[pool_key] += (
            initial_capex * factors.capital_multiplier
        )
        battery_depreciation_by_pool[pool_key] += (
            initial_capex * (1.0 - recovery_ratio) / life
        )
        unit_vintage.append({
            "battery_pool": pool_key,
            "kind": str(cohort.get("kind", "")),
            "install_year": int(cohort["install_year"]),
            "life_years": life,
            "initial_capex_yi": initial_capex,
            "capital_multiplier": factors.capital_multiplier,
            # 单位全周期资本 PV：锚在该批次自身 t=0——这正是「单站模型」要的口径，
            # 所以它可以直接 × CRF 得单位 EAC，比值往上聚合不受年份影响。
            "lifecycle_pv_yi": initial_capex * factors.capital_multiplier,
            "annual_capital_requirement_yi": (
                initial_capex * factors.capital_multiplier
                * finance["capital_recovery_factor"]
            ),
            "annual_depreciation_yi": initial_capex * (1.0 - recovery_ratio) / life,
        })
        label = f"{float(cohort['life']):g}年"
        if int(cohort["install_year"]) == years[0]:
            factor_samples[label] = factors.capital_multiplier
            residual_samples[label] = factors.terminal_residual_ratio

    station_body_total = (
        preperiod_station_body_capex
        + sum(item["station_body"] for item in initial_components.values())
    )
    # 【新增｜分池资本】站体总初装按池累计，并入各池资本底座与折旧。
    station_body_total_by_pool = {
        pk: preperiod_body_by_pool[pk]
        + sum(
            initial_components_by_pool[year][pk]["station_body"] for year in years
        )
        for pk in BATTERY_POOLS
    }
    lifecycle_capital += station_body_total
    lifecycle_capital_by_pool = {
        pk: lifecycle_capital_by_pool[pk] + station_body_total_by_pool[pk]
        for pk in BATTERY_POOLS
    }
    mature_depreciation = battery_depreciation + station_body_total / horizon
    mature_depreciation_by_pool = {
        pk: battery_depreciation_by_pool[pk] + station_body_total_by_pool[pk] / horizon
        for pk in BATTERY_POOLS
    }
    crf = finance["capital_recovery_factor"]
    total_initial = (
        preperiod_station_initial_capex
        + sum(sum(item.values()) for item in initial_components.values())
    )
    total_initial_by_pool = {
        pk: preperiod_initial_by_pool[pk]
        + sum(
            sum(initial_components_by_pool[year][pk].values()) for year in years
        )
        for pk in BATTERY_POOLS
    }
    # 分池汇总与总量一致性校验（防拆分口径漂移）。
    for label, by_pool, total in (
        ("全周期资本底座", lifecycle_capital_by_pool, lifecycle_capital),
        ("成熟期折旧", mature_depreciation_by_pool, mature_depreciation),
        ("终局初装CAPEX", total_initial_by_pool, total_initial),
    ):
        if abs(sum(by_pool.values()) - total) > 1e-6:
            raise ValueError(f"分池{label}之和({sum(by_pool.values())})≠总量({total})")

    # 【新增 2026-09-02｜估值资本，统一折到基年】
    # lifecycle_capital 是「各批次锚在自身 t=0 的 PV 之和」——那是**门槛口径**（单位 EAC 聚合，
    # 比值无量纲，跨年份加总不影响它），不是估值口径。估值要的是同一时点的钱，
    # 所以这里单独算一条：全部 CAPEX 折到 base_year。NPV 只能用这一条。
    # 见 DECISIONS.md「2026-09-02 · EAC 的资本底座混了年份」。
    base_year = years[0]
    wacc = finance["wacc"]
    valuation_capital_pv = preperiod_station_initial_capex + sum(
        sum(initial_components[year].values()) / (1.0 + wacc) ** (year - base_year)
        for year in years
    ) + sum(
        amount / (1.0 + wacc) ** (year - base_year)
        for year, amount in replacement_net.items()
        if amount
    )

    # 【新增 2026-09-02｜不变量断言】这类错误用一个恒等式就能挡住，不必靠人眼审。
    nominal_total_capex = total_initial + sum(
        amount for amount in replacement_net.values() if amount
    )
    # 【强化 2026-09-02b】原来只断言「累计折旧 ≤ 名义净支出」——那是个很弱的不等式，
    # 而且两个数不同源：nominal_total_capex 已扣期中残值、且用逐年下降的实际价格。
    # 真正的恒等式是会计意义上的资本消耗：
    #     累计折旧 == 毛资本支出 − 期中残值回收 − 期末在役资产残值
    # 三项都在本函数内可得，故直接断言，容差 5%（残余偏差来自折旧按初装价计
    # 而更换按逐年下降价发生，方向已知、量级 3% 左右）。
    replacement_gross_all = sum(
        amount / (1.0 - recovery_ratio) for amount in replacement_net.values() if amount
    ) if recovery_ratio < 1.0 else 0.0
    interim_residual = replacement_gross_all - sum(
        amount for amount in replacement_net.values() if amount
    )
    terminal_residual = sum(
        float(cohort["initial_capex"])
        * lifecycle_factors(
            config, float(cohort["install_year"]), float(cohort["life"])
        ).terminal_residual_ratio
        for cohort in battery_cohorts
    )
    capital_consumed = (
        total_initial + replacement_gross_all - interim_residual - terminal_residual
    )
    cumulative_depreciation = mature_depreciation * horizon
    if capital_consumed > 0:
        drift = cumulative_depreciation / capital_consumed - 1.0
        if abs(drift) > 0.05:
            raise ValueError(
                f"累计折旧({cumulative_depreciation:.1f})与真实资本消耗"
                f"({capital_consumed:.1f})偏离{drift:+.1%}，超过5%容差——折旧口径错误。"
                f"（毛支出{total_initial + replacement_gross_all:.1f}"
                f" 期中残值{interim_residual:.1f} 期末残值{terminal_residual:.1f}）"
            )
    if valuation_capital_pv > nominal_total_capex + 1e-6:
        raise ValueError(
            f"估值资本PV({valuation_capital_pv:.1f})>名义总支出({nominal_total_capex:.1f})"
        )
    peak = max(annual, key=lambda row: row.catl_equity_call_yi)
    return CapexResult(
        annual=annual,
        total_initial_capex_yi=total_initial,
        first_replacement_net_capex_yi=sum(replacement_net[year] for year in years),
        lifecycle_capital_base_yi=lifecycle_capital,
        valuation_capital_pv_yi=valuation_capital_pv,
        nominal_total_capex_yi=nominal_total_capex,
        gross_total_capex_yi=total_initial + replacement_gross_all,
        interim_residual_yi=interim_residual,
        terminal_residual_yi=terminal_residual,
        capital_consumed_yi=capital_consumed,
        unit_vintage=unit_vintage,
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
        station_schedules_by_pool={
            pool_key: list(station_schedules[pool_key]) for pool_key in BATTERY_POOLS
        },
        opening_station_stock_by_pool=dict(opening_by_pool),
        station_2026_targets_by_pool=dict(target2026_by_pool),
        preperiod_station_initial_capex_yi=preperiod_station_initial_capex,
        catl_preperiod_station_equity_investment_yi=(
            preperiod_station_initial_capex * equity_factor
        ),
        battery_price_path_rmb_kwh=annual_battery_price_path(config),
        lifecycle_factor_by_life=factor_samples,
        terminal_residual_by_life=residual_samples,
        retirement_recovery_ratio=recovery_ratio,
        lifecycle_capital_base_by_pool=dict(lifecycle_capital_by_pool),
        mature_annual_depreciation_by_pool=dict(mature_depreciation_by_pool),
        total_initial_capex_by_pool=dict(total_initial_by_pool),
    )

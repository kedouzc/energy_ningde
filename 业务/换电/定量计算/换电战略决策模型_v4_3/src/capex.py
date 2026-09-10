"""资本支出层：建站/电池的初装、更换、折旧、残值、稳态debt——全部从「批次」算起。

【核心概念：cohort（批次）与 generation（代）】
一个 cohort 是"同一年、同一池、同一种电池"的一批电池（站内电池或车载电池）；
它在 horizon（15年）内会被更换若干次，每一次更换都开启新的一"代"（generation）。
`_cohort_generations` 把一个 cohort 展开成它在 horizon 内的所有代，每一代都
**按自己那一年的价格买入**（电池逐年降价，后代更便宜）、折旧到自己实际能收回
的残值为止——这是本文件几乎所有下游计算（折旧、稳态debt、更换排期）共用的
唯一"代"级明细来源，不要在别处重新拆分 cohort。

【数据流：build_capex 是唯一入口，其余函数都是它的子步骤】
    build_capex(config, scale, sourcing)
      ├─ 站数排期：_station_schedule 把"2025存量→2026目标→2028终局"三个
      │   拍定的里程碑，直算成每年新增站数（2029-2030不再新建）。
      ├─ 登记 cohort：_append_station_pool_cohorts 把每个（池×年份×站数）
      │   的站内电池批次登记进 battery_cohorts 列表；车辆电池批次在
      │   build_capex 主循环里直接从 scale.rows 登记（不走这个函数，
      │   因为车辆电池的 gwh 是 scale 已经算好的，不需要再乘 station 参数）。
      ├─ 按代展开：对 battery_cohorts 里每一个 cohort 调 _cohort_generations，
      │   拿到这个 cohort 在 horizon 内的完整"代"级明细（成本/折旧/残值）。
      │   同时用 _event_year_weights 把非整数寿命的更换事件分摊到相邻两年，
      │   算出 replacement_gwh/replacement_net（年度更换现金流排期）。
      └─ 从"代"级明细聚合出 CapexResult 的各个字段——**关键的是，多个不同
          用途的量都从同一份"代"级明细里取不同的切片，口径互相不通用**：
            · lifecycle_capital_base_yi：各批次锚在**自己**t=0的PV之和
              （门槛/EAC口径，不对应任何单一时点，不能当"投入"跟"值多少"相除）
            · valuation_capital_pv_yi：全部CAPEX统一折到**base_year**
              （估值/DCF口径，NPV只能用这个）
            · steady_state_debt_yi：**target_year(2030)在役那一代**的历史
              成本×债务比（资产负债表快照口径，倍数法与DCF法共用同一个数，
              见 capex_debt_估值公式链.md 第3-4节）
            · mature_annual_depreciation_yi：**target_year在役那一代**的
              年折旧额（稳态永续口径，DCF真实主口径拿它当可持续资本性支出
              的代理，见 business.py::_dcf_cross_check）
          三个"债务/折旧/估值"字段看起来都从同一个cohort循环里的 in_service
          变量算出，但分别回答"欠多少""每年掉价多少""折现值多少"三个不同
          问题，改动其中一个前先确认清楚要改的是哪一个。

【参数怎么传递】
入参 config（base.toml解析出的dict）、scale（ScaleResult，车辆/站数/寿命
已经算好）、sourcing（当前未使用，装机需求已经在scale里体现，保留参数位是
为了跟其他 build_* 函数签名一致，方便 model.py 统一调用）。出参 CapexResult
（schemas.py定义），是 business.py / capital_cycle.py / consolidation.py /
tree.py 的公共上游——本文件不知道、也不需要知道下游怎么用这些数。
"""
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
    """直算2026—2028新增站数；2029—2030不再建站。

    站数是存量、不可为负、不可低于已有存量：需求下修（如 NEV 渗透率悲观情景）
    时不再拆站，故对累计目标做单调钳制（新增站数不为负）。这让向下情景轴不会因
    "规划站数跌破 2025 存量" 而让模型抛错；基线/乐观档本就满足单调，钳制为恒等。"""
    cumulative_target_2026 = max(opening_2025, cumulative_target_2026)
    cumulative_target_2028 = max(cumulative_target_2026, cumulative_target_2028)
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


def _cohort_generations(
    config: dict,
    install_year: float,
    life: float,
    horizon: float,
    recovery_ratio: float,
    initial_capex: float,
    terminal_residual_ratio: float,
) -> list[dict[str, float]]:
    """【新增 2026-09-02c】把一个 cohort 在 horizon 内展开成「各代电池」。

    每一代都是一笔独立的资产：**按自己那一年的价格买入**、用 life 年、
    退役时收回一笔钱。它的可折旧额 = 买入价 − 实际收回额。

        depreciable_k = cost_k − recovery_k
        recovery_k    = 回收率 × 下一代成本（模型口径：残值按更换时的新电池价计）
        末代 recovery = 初装 × terminal_residual_ratio（期末在役批的残值：DCF终值假设，
                         按实际SOH折算、打二手交易折价，但不降级储能——
                         见 derived.terminal_residual_details）

    这样定义之后，会计恒等式**按构造成立、无需容差**：
        Σ depreciable == Σ cost − Σ 期中回收 − 期末残值

    修正的是 2026-09-02 版的两处遗留误差（合计约 −3%，激进情景下超 5%）：
      ① 原式对每一代都用**第 0 代的价格**，而电池逐年降价，后代更便宜；
      ② 期末在役批按 `terminal_residual_ratio` 计，但折旧那一侧仍按第 0 代成本摊，
         两侧口径不一致。
    见 DECISIONS.md「2026-09-02c · 折旧恒等式改为按构造成立」与
    「2026-09-03 · 末代残值不再降级储能」（terminal_residual_ratio 本身的口径修正）。
    """
    base_price = battery_price_rmb_kwh(config, install_year)
    generations: list[dict[str, float]] = []
    index = 0
    while index * life < horizon - 1e-9:
        start = index * life
        price = battery_price_rmb_kwh(config, install_year + start)
        generations.append({
            "index": float(index),
            "start": start,
            "cost": initial_capex * price / base_price,
        })
        index += 1
    for position, generation in enumerate(generations):
        is_last = position + 1 == len(generations)
        if is_last:
            generation["recovery"] = initial_capex * terminal_residual_ratio
            generation["service_years"] = horizon - generation["start"]
            generation["has_successor"] = 0.0
        else:
            generation["recovery"] = recovery_ratio * generations[position + 1]["cost"]
            generation["service_years"] = life
            generation["has_successor"] = 1.0
        generation["depreciable"] = generation["cost"] - generation["recovery"]
        generation["annual_depreciation"] = generation["depreciable"] / life
    return generations


def build_capex(
    config: dict,
    scale: ScaleResult,
    sourcing: SourcingAdjustment,
) -> CapexResult:
    """本文件唯一入口，五个阶段依次执行（各阶段用到的子函数见文件头）：

    1. 站数排期（_station_schedule）：拆出每年新增站数，按池分摊。
    2. 登记 battery_cohorts：存量站(2025年末)、每年新增车辆电池/站内电池，
       各自记录 install_year/life/initial_capex/battery_pool。
    3. 年度更换排期：对每个 cohort 展开出 horizon 内的更换事件年份与
       weight（_event_year_weights），聚合成 replacement_gwh/replacement_net
       等逐年字典，供 CapexRow.annual 与 lifecycle_replacement_schedule_yi。
    4. 按代展开（_cohort_generations）主循环：对每个 cohort 算出它在
       horizon 内的完整代际明细，从中取出 target_year 在役的那一代
       （in_service），分别喂给折旧、稳态debt、终值PV三个不同用途的累加器；
       同时做折旧会计恒等式（按构造成立）与分池汇总一致性两类断言。
    5. 聚合成 CapexResult：从上面几步的累加器和字典组装最终返回值。
    """
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
    # 【新增 2026-09-05｜第四轮永续账】更新净支出按池分列（cohort 已带 battery_pool
    # 归属）——供 valuation_capital_pv_by_pool（有限期账投资侧分池）使用。
    replacement_net_by_pool: dict[str, dict[int, float]] = {
        pk: defaultdict(float) for pk in BATTERY_POOLS
    }
    for cohort in battery_cohorts:
        pool_key = str(cohort["battery_pool"])
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
                replacement_net_by_pool[pool_key][replacement_year] += gross - recovery
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
    # 【新增 2026-09-04｜稳态debt】target_year(2030)在役批次的历史成本，供倍数法与
    # DCF法统一使用同一个债务口径——不是 lifecycle_capital_base（各批次锚在自身t0，
    # 跨年份加总不对应任何单一时点），也不是 valuation_capital_pv（含2030年以后才
    # 发生的未来更新，混进了还没借的钱）。这是资产负债表快照口径："2030这一刻账上
    # 实际欠多少"。见 capex_debt_估值公式链.md 第3-4节，debt_by_pool 的 in_service
    # 变量本来就在给折旧用，这里只是多读一次同一个数。站体不重置、全部在建设期
    # (2026-2030)建成，2030年全额在役，在循环外单独加总（下方 station_body_total）。
    steady_state_debt_base = 0.0
    steady_state_debt_base_by_pool = {pk: 0.0 for pk in BATTERY_POOLS}
    factor_samples: dict[str, float] = {}
    residual_samples: dict[str, float] = {}
    # 【新增｜单站 vintage 表】按 (池 × 装机年) 留存单位经济性，供报告下钻与「窗口成本」章。
    unit_vintage: list[dict[str, float | str]] = []
    # 【新增 2026-09-02c】折旧恒等式的四项，按代展开时逐 cohort 累加。
    target_year = config["meta"]["target_year"]
    gross_battery_capex = 0.0
    interim_recovery = 0.0
    terminal_recovery = 0.0
    cumulative_battery_depreciation = 0.0
    # 【新增 2026-09-03，经用户复核后补】期末残值的估值(DCF)口径：每个 cohort 的终值发生在
    # 「自己的装机年 + horizon」这一年——不同 cohort 装机年不同，终值发生的绝对年份也不同，
    # 不能像 terminal_recovery（记账口径，不折现）那样直接相加。这里把每个 cohort 的终值
    # 折回统一的 base_year，才能作为 DCF 的期末现金流入项使用。同类问题与修法见
    # DECISIONS.md「2026-09-02 · EAC 的资本底座混了年份」。
    #
    # 【税｜2026-09-03 第二次修正，经用户指出后补】这笔钱在 DCF 里是一笔期末处置收益，
    # 依常规财务处理该按 tax_rate 缴税，不能税前直接计入 NPV。
    # 简化（已知比精确处理保守，即多计税）：按残值全额视为应税处置收益计税
    # ATSV = 残值 ×(1 − tax_rate)，而不是更精确的"残值 − 账面净值"差额计税
    # ——本模型的折旧排布是"按构造成立"以恒等式为目的反推的（depreciable = cost − recovery），
    # 并非独立追踪的税务账面净值，若用它做净值口径，处置当期几乎恒等于零损益，
    # 会把税额算成 0，明显与"处置价高于账面残值、理应产生应税收益"的常识不符。
    # 全额计税是保守方向（多计税、压低 NPV），留作后续精化项（接入独立的税务账面净值追踪）。
    base_year = years[0]
    wacc = finance["wacc"]
    tax_rate = finance["tax_rate"]
    terminal_recovery_pv = 0.0
    # 【新增 2026-09-05｜第四轮】期末残值PV分池 + 成熟期机队总GWh分池——后者是
    # 永续账"稳态净更新支出"的第一性原理anchor（Σ_池 机队GWh/池寿命），与具体
    # 日历年份无关（更新理论：稳态更新速率=存量÷寿命），见
    # capex_debt_估值公式链.md 第四轮 §4.3。
    terminal_recovery_pv_by_pool: dict[str, float] = {pk: 0.0 for pk in BATTERY_POOLS}
    mature_fleet_gwh_by_pool: dict[str, float] = {pk: 0.0 for pk in BATTERY_POOLS}
    for cohort in battery_cohorts:
        factors = lifecycle_factors(
            config, float(cohort["install_year"]), float(cohort["life"])
        )
        initial_capex = float(cohort["initial_capex"])
        life = float(cohort["life"])
        install_year_f = float(cohort["install_year"])
        lifecycle_capital += initial_capex * factors.capital_multiplier
        # 【修正 2026-09-02｜折旧分子】原式用 (capital_multiplier − terminal_residual)/life：
        # capital_multiplier 是「15 年全周期要花多少钱」的 PV 倍数——那是 EAC 的分子；
        # 折旧要回答的是「现在装着的这一代电池每年掉多少价」，只与本代有关。
        # 两者共用分子 ⇒ 把 15 年要买的 N 代电池压进一代寿命里摊完，累计折旧达名义支出的 2.28 倍。
        # 【再修正 2026-09-02c】按代展开：每一代按**自己那年的价格**买入、
        # 折旧到**自己实际能收回的那个数**为止。恒等式因此按构造成立，不需要容差。
        # 见 DECISIONS.md「2026-09-02 · 成熟期折旧用错了分子」与「2026-09-02c」。
        generations = _cohort_generations(
            config, install_year_f, life, float(horizon),
            recovery_ratio, initial_capex, factors.terminal_residual_ratio,
        )
        # 成熟期折旧：取**目标年在役的那一代**（不是第 0 代），按其可折旧额／寿命计。
        elapsed_to_target = max(0.0, float(target_year) - install_year_f)
        in_service = generations[
            min(int(elapsed_to_target // life), len(generations) - 1)
        ]
        cohort_mature_dep = in_service["annual_depreciation"]
        battery_depreciation += cohort_mature_dep
        # 全周期口径（供恒等式断言）：各代可折旧额之和 == 毛支出 − 期中回收 − 期末残值。
        gross_battery_capex += sum(g["cost"] for g in generations)
        interim_recovery += sum(
            g["recovery"] for g in generations if g["has_successor"]
        )
        terminal_recovery += sum(
            g["recovery"] for g in generations if not g["has_successor"]
        )
        cumulative_battery_depreciation += sum(g["depreciable"] for g in generations)
        # 【2026-09-03】本 cohort 的终值发生在 install_year_f + horizon 这一年，
        # 先按 tax_rate 计税（全额视为应税处置收益，保守简化见上方说明），
        # 税后现金流再折回 base_year。
        terminal_recovery_pv += sum(
            g["recovery"] * (1.0 - tax_rate)
            / (1.0 + wacc) ** (install_year_f + horizon - base_year)
            for g in generations if not g["has_successor"]
        )
        pool_key = str(cohort["battery_pool"])
        terminal_recovery_pv_by_pool[pool_key] += sum(
            g["recovery"] * (1.0 - tax_rate)
            / (1.0 + wacc) ** (install_year_f + horizon - base_year)
            for g in generations if not g["has_successor"]
        )
        mature_fleet_gwh_by_pool[pool_key] += float(cohort["gwh"])
        lifecycle_capital_by_pool[pool_key] += (
            initial_capex * factors.capital_multiplier
        )
        battery_depreciation_by_pool[pool_key] += cohort_mature_dep
        # 【新增 2026-09-04】in_service 是"target_year(2030)在役的那一代"，其 cost
        # 就是那一代按自己vintage价格买入的历史成本——这正是稳态debt要的"在役成本"，
        # 复用折旧已经算好的这个数，不新写遍历逻辑。
        steady_state_debt_base += in_service["cost"]
        steady_state_debt_base_by_pool[pool_key] += in_service["cost"]
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
            "annual_depreciation_yi": cohort_mature_dep,
            "generations": len(generations),
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
    # 【新增 2026-09-04】站体无重置、全部在2026-2030建成，2030年全额在役——
    # 按原值（非净值）计入稳态debt基数，与电池"在役代按其vintage价格"的口径一致
    # （debt跟踪的是"当前在服役资产的原始融资额"，不是账面折旧后的净值）。
    steady_state_debt_base += station_body_total
    steady_state_debt_base_by_pool = {
        pk: steady_state_debt_base_by_pool[pk] + station_body_total_by_pool[pk]
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
        ("稳态debt基数", steady_state_debt_base_by_pool, steady_state_debt_base),
    ):
        if abs(sum(by_pool.values()) - total) > 1e-6:
            raise ValueError(f"分池{label}之和({sum(by_pool.values())})≠总量({total})")

    # 【新增 2026-09-02｜估值资本，统一折到基年】
    # lifecycle_capital 是「各批次锚在自身 t=0 的 PV 之和」——那是**门槛口径**（单位 EAC 聚合，
    # 比值无量纲，跨年份加总不影响它），不是估值口径。估值要的是同一时点的钱，
    # 所以这里单独算一条：全部 CAPEX 折到 base_year。NPV 只能用这一条。
    # 见 DECISIONS.md「2026-09-02 · EAC 的资本底座混了年份」。
    # （base_year/wacc 已在上方 cohort 循环前定义，供 terminal_recovery_pv 复用。）
    valuation_capital_pv = preperiod_station_initial_capex + sum(
        sum(initial_components[year].values()) / (1.0 + wacc) ** (year - base_year)
        for year in years
    ) + sum(
        amount / (1.0 + wacc) ** (year - base_year)
        for year, amount in replacement_net.items()
        if amount
    )

    # 【新增 2026-09-05｜第四轮，capex_debt_估值公式链.md §4.1-4.7】
    # ① 纯初装现值(pure_initial_capex_pv)：valuation_capital_pv 剔除更换支出后剩下的
    #   部分——永续账唯一还需要的、真正一次性的"初始投资"（有限期账继续用
    #   valuation_capital_pv，含更换支出，两条线各自服务各自的NPV公式，互不混用）。
    pure_initial_capex_pv = preperiod_station_initial_capex + sum(
        sum(initial_components[year].values()) / (1.0 + wacc) ** (year - base_year)
        for year in years
    )
    pure_initial_capex_pv_by_pool = {
        pk: preperiod_initial_by_pool[pk] + sum(
            sum(initial_components_by_pool[year][pk].values())
            / (1.0 + wacc) ** (year - base_year)
            for year in years
        )
        for pk in BATTERY_POOLS
    }
    # ② valuation_capital_pv 分池版——供有限期账（基础账）分池NPV用。
    valuation_capital_pv_by_pool = {
        pk: pure_initial_capex_pv_by_pool[pk] + sum(
            amount / (1.0 + wacc) ** (year - base_year)
            for year, amount in replacement_net_by_pool[pk].items()
            if amount
        )
        for pk in BATTERY_POOLS
    }
    # ③ 稳态净更新支出(steady_state_net_replacement)：永续账的可持续资本性支出
    #   anchor，不用折旧代理（历史成本口径，混了不同cohort装机年价格，已验证
    #   比真实排期偏高45.4%），改用更新理论(renewal reward theorem)第一性原理——
    #   稳态更新速率=Σ_池(机队总GWh÷池寿命)，量与具体日历年份无关；价用
    #   target_year当年新电池净单价(扣回收后)。见第四轮§4.3。
    target_price = battery_price_rmb_kwh(config, target_year)
    net_unit_cost_target = target_price * (1.0 - recovery_ratio) / 100.0
    steady_state_net_replacement_by_pool = {
        pk: (mature_fleet_gwh_by_pool[pk] / scale.battery_pool_life_years[pk]) * net_unit_cost_target
        for pk in BATTERY_POOLS
    }
    steady_state_net_replacement = sum(steady_state_net_replacement_by_pool.values())
    # ③b 【2026-09-10】稳态年更新装机的**物理量**（GWh/年）：同一条更新理论，只是
    #   不乘净单价。结论区"锁定之后每年平均 X GWh 订单"就取这个——建设期结束之后
    #   新增装车归零、只剩更新，而更新必须**分池**算（倒短 8.37 年 vs 干线 2.94 年，
    #   若用单一寿命会把干线池的更换频率抹平，稳态量直接算错一半以上）。
    steady_state_replacement_gwh_by_pool = {
        pk: (mature_fleet_gwh_by_pool[pk] / scale.battery_pool_life_years[pk])
        if scale.battery_pool_life_years.get(pk) else 0.0
        for pk in BATTERY_POOLS
    }
    steady_state_replacement_gwh = sum(steady_state_replacement_gwh_by_pool.values())
    # ④ 站体设备（第四轮§4.6，2026-09-05d修正）：15年一次性整体更新，与折旧年限
    #   (model_horizon_years)同步，不设独立参数。永续账按"每horizon年一笔"的
    #   递归永续现值处理（标准年金公式：PV=L÷[(1+r)^N−1]，付**全额**，不扣任何
    #   回收——这本身就隐含"设备到期视为耗尽"）。
    #   【不设期末残值】有限期账不给这台设备补期末残值：既然永续账已经把它当"到期
    #   全额换新、不扣回收"处理，有限期账若再给一份残值，等于对同一资产的寿命
    #   终点持两套矛盾的假设（一边说耗尽要全款换、一边说没耗尽还值钱）；且换电
    #   行业没有设备二手市场的真实数据支撑残值折价比例（不像电池有完整可查的
    #   回收价格链）。维持"折旧到零=残值为零"这个更朴素、内部自洽的假设。
    station_equipment_perpetual_pv = station_body_total / ((1.0 + wacc) ** horizon - 1.0)
    station_equipment_perpetual_pv_by_pool = {
        pk: station_body_total_by_pool[pk] / ((1.0 + wacc) ** horizon - 1.0)
        for pk in BATTERY_POOLS
    }
    # 分池一致性校验（第四轮新增字段，同样不靠人眼审）。
    for label, by_pool, total in (
        ("纯初装现值", pure_initial_capex_pv_by_pool, pure_initial_capex_pv),
        ("估值资本PV", valuation_capital_pv_by_pool, valuation_capital_pv),
        ("期末残值PV", terminal_recovery_pv_by_pool, terminal_recovery_pv),
    ):
        if abs(sum(by_pool.values()) - total) > 1e-6 * max(1.0, abs(total)):
            raise ValueError(f"分池{label}之和({sum(by_pool.values())})≠总量({total})")

    # 【新增 2026-09-02｜不变量断言】这类错误用一个恒等式就能挡住，不必靠人眼审。
    nominal_total_capex = total_initial + sum(
        amount for amount in replacement_net.values() if amount
    )
    # 【强化 2026-09-02c｜折旧的会计恒等式，按构造成立、无容差】
    #     累计折旧 == 毛资本支出 − 期中残值回收 − 期末在役残值
    # 站体：无更换、期末账面为 0，故毛支出=折旧、两侧残值均为 0，自然满足。
    # 电池：由 _cohort_generations 按代展开，depreciable_k = cost_k − recovery_k，
    # 求和后恒等式左右两边是同一组数的两种排列，只可能因浮点误差而不等。
    # 断言用 1e-6 相对容差——它现在检的是「有没有写错代码」，不是「口径差多少」。
    gross_total_capex = gross_battery_capex + station_body_total
    cumulative_depreciation = cumulative_battery_depreciation + station_body_total
    capital_consumed = gross_total_capex - interim_recovery - terminal_recovery
    if abs(cumulative_depreciation - capital_consumed) > 1e-6 * max(1.0, gross_total_capex):
        raise ValueError(
            f"折旧恒等式不成立：累计折旧({cumulative_depreciation:.4f}) != "
            f"毛支出({gross_total_capex:.4f}) − 期中残值({interim_recovery:.4f}) "
            f"− 期末残值({terminal_recovery:.4f}) = {capital_consumed:.4f}"
        )
    if valuation_capital_pv > nominal_total_capex + 1e-6:
        raise ValueError(
            f"估值资本PV({valuation_capital_pv:.1f})>名义总支出({nominal_total_capex:.1f})"
        )
    # 诊断（不断言）：按代展开 与 模型自己的更换排期，是两条独立代码路径，
    # 两者的净支出应当接近；持续偏离 >5% 说明其中一条有口径漂移，值得查。
    generation_path_net_capex = gross_total_capex - interim_recovery
    schedule_path_net_capex = nominal_total_capex
    capex_path_drift = (
        generation_path_net_capex / schedule_path_net_capex - 1.0
        if schedule_path_net_capex else 0.0
    )

    peak = max(annual, key=lambda row: row.catl_equity_call_yi)
    steady_state_debt = steady_state_debt_base * finance["debt_ratio"]
    steady_state_debt_by_pool = {
        pk: steady_state_debt_base_by_pool[pk] * finance["debt_ratio"] for pk in BATTERY_POOLS
    }
    return CapexResult(
        annual=annual,
        total_initial_capex_yi=total_initial,
        first_replacement_net_capex_yi=sum(replacement_net[year] for year in years),
        lifecycle_capital_base_yi=lifecycle_capital,
        valuation_capital_pv_yi=valuation_capital_pv,
        nominal_total_capex_yi=nominal_total_capex,
        gross_total_capex_yi=gross_total_capex,
        interim_residual_yi=interim_recovery,
        terminal_residual_yi=terminal_recovery,
        terminal_residual_pv_yi=terminal_recovery_pv,
        capital_consumed_yi=capital_consumed,
        cumulative_depreciation_yi=cumulative_depreciation,
        capex_path_drift=capex_path_drift,
        unit_vintage=unit_vintage,
        lifecycle_crf=crf,
        annual_capital_requirement_yi=lifecycle_capital * crf,
        mature_annual_depreciation_yi=mature_depreciation,
        project_debt_yi=lifecycle_capital * finance["debt_ratio"],
        external_equity_yi=(
            lifecycle_capital
            * (1.0 - finance["debt_ratio"])
            * (1.0 - finance["construction_ownership"])
        ),
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
        steady_state_debt_yi=steady_state_debt,
        steady_state_debt_by_pool_yi=steady_state_debt_by_pool,
        # 【新增 2026-09-05｜第四轮：两本账】见 capex_debt_估值公式链.md 第四轮。
        station_body_total_yi=station_body_total,
        station_body_total_by_pool_yi=dict(station_body_total_by_pool),
        pure_initial_capex_pv_yi=pure_initial_capex_pv,
        pure_initial_capex_pv_by_pool_yi=dict(pure_initial_capex_pv_by_pool),
        valuation_capital_pv_by_pool_yi=dict(valuation_capital_pv_by_pool),
        terminal_residual_pv_by_pool_yi=dict(terminal_recovery_pv_by_pool),
        steady_state_net_replacement_yi=steady_state_net_replacement,
        steady_state_net_replacement_by_pool_yi=dict(steady_state_net_replacement_by_pool),
        station_equipment_perpetual_pv_yi=station_equipment_perpetual_pv,
        station_equipment_perpetual_pv_by_pool_yi=dict(station_equipment_perpetual_pv_by_pool),
        # 【2026-09-10】稳态年更新 GWh（分池 + 合计），结论区"每年平均订单"取这里。
        mature_fleet_gwh_by_pool=dict(mature_fleet_gwh_by_pool),
        steady_state_replacement_gwh_by_pool=dict(steady_state_replacement_gwh_by_pool),
        steady_state_replacement_gwh=steady_state_replacement_gwh,
    )

from __future__ import annotations

from derived import battery_price_rmb_kwh
from scale import BATTERY_POOLS
from schemas import (
    BaselineResult,
    CapexResult,
    ManufacturingResult,
    PoolOperations,
    ScaleResult,
    SwapBusinessResult,
)


def build_2026_baseline(config: dict) -> BaselineResult:
    h1 = config["financial_2026h1"]
    estimate = config["financial_2026e"]
    power_gross_profit = h1["power_battery_revenue_yi"] * h1["power_battery_gross_margin"]
    group_gross_profit = h1["group_revenue_yi"] * h1["group_gross_margin"]
    power_share = power_gross_profit / group_gross_profit
    group_np = estimate["group_net_profit_consensus_yi"]
    group_value = estimate["group_market_cap_ah_yi"]
    power_np = group_np * power_share
    power_value = group_value * power_share
    modeled_revenue = (
        estimate["power_battery_shipments_gwh"]
        * battery_price_rmb_kwh(config, config["meta"]["reference_year"])
        / 100.0
    )
    modeled_np = modeled_revenue * config["swap_business"]["with_swap_manufacturing_net_margin"]
    modeled_value = modeled_np * config["finance"]["manufacturing_pe"]
    power_revenue = config["financial_2025a"]["power_battery_revenue_yi"] * (
        1.0 + h1["power_battery_revenue_yoy"]
    )
    return BaselineResult(
        power_gross_profit_share=power_share,
        power_revenue_2026e_yi=power_revenue,
        power_net_profit_2026e_yi=power_np,
        power_market_value_2026e_yi=power_value,
        modeled_power_net_profit_2026e_yi=modeled_np,
        modeled_power_market_value_2026e_yi=modeled_value,
        non_power_net_profit_2026e_yi=group_np - power_np,
        non_power_market_value_2026e_yi=group_value - power_value,
        group_net_profit_2026e_yi=group_np,
        group_market_value_2026e_yi=group_value,
        implied_group_pe=group_value / group_np,
    )


def build_ancillary_revenue(config: dict, capex: CapexResult) -> tuple[float, float, float, float]:
    """电网辅助服务收入计算项（v4.3 结构性修正：原 5.15 亿固定值废除）。

    推算链（MANIFEST §4.1.1，源自 v3.2 L613-629）：
      辅助服务收入 = 容量补偿 + max(需求响应, 调频)   —— 后两项互斥取孰高
    （同一块电池同一时段只能干一件事：顶峰放电或跟踪调频指令）。
      容量补偿 = Σ(站数×申报容量)×容量补偿单价
      需求响应 = Σ(站数×申报容量)×年小时×单价
      调频     = Σ(站数×调频容量)×年小时×单价
    按终局站数计算，与站数直接挂钩、随站网规模动态变化。
    """
    anc = config["ancillary_services"]
    # 【重构｜4站型】站数键=四池/四站型；辅助服务参数仍按两大类（骐骥两站型同源重卡参数、
    # 巧克力两站型同源乘用参数），故先汇总为两大类站数再计价。
    heavy_stations = sum(
        count for pool, count in capex.station_targets.items()
        if pool.startswith("qiji75")
    )
    choco_stations = sum(
        count for pool, count in capex.station_targets.items()
        if pool.startswith("choco")
    )
    # 申报容量合计（kW）：重卡站 152kW/座 + 巧克力站 25kW/座
    declared_kw = (
        heavy_stations * anc["heavy_station_declared_kw"]
        + choco_stations * anc["choco_station_declared_kw"]
    )
    # ① 容量补偿：存在即挣的固定收益（广东容量补偿下限 45 元/kW·年）
    capacity_compensation = (
        declared_kw * anc["capacity_compensation_price_rmb_kw_year"] / 1e8
    )
    # ② 需求响应：按申报容量×年等效小时×单价（浙发改 131 号约定型口径）
    demand_response = (
        declared_kw
        * anc["demand_response_hours_year"]
        * anc["demand_response_price_rmb_kwh"]
        / 1e8
    )
    # ③ 调频：按调频容量×年利用小时×单价（蔚来苏州 68 站 VPP 实测锚）
    frequency_regulation = (
        heavy_stations * anc["heavy_frequency_regulation_kw"]
        + choco_stations * anc["choco_frequency_regulation_kw"]
    ) * anc["frequency_regulation_hours_year"] * anc["frequency_regulation_price_rmb_kwh"] / 1e8
    total = capacity_compensation + max(demand_response, frequency_regulation)
    return total, capacity_compensation, demand_response, frequency_regulation


def build_battery_bank_rate_opex(
    config: dict,
    capex: CapexResult,
    vehicle_gwh: float,
    station_gwh: float,
) -> dict[str, float]:
    """电池银行侧费率三项：保险+池化维护+仓储物流（v4.3 补齐，蔚能四项成本对照框架）。

    资产基数口径：电池资产 = 车端运营装机 + 站内周转装机（全托管口径，保守——
    40% 自持归属差异在估值层处理，不在此折减）；设备资产 = 站体初装 CAPEX。
    价格基准取 reference_year 现价（590 元/kWh，价格曲线上界=保守方向）。
    """
    business = config["swap_business"]
    price_now = battery_price_rmb_kwh(config, config["meta"]["reference_year"])
    battery_asset_yi = (vehicle_gwh + station_gwh) * 1e6 * price_now / 1e8
    equipment_asset_yi = sum(
        station_count * config["stations"][pool_key]["station_body_capex_wan"]
        for pool_key, station_count in capex.station_targets.items()
    ) / 1e4
    # 保险：电池 0.20%（蔚能实证费率）+ 设备 0.15%（老模型储能对标）
    insurance = (
        battery_asset_yi * business["battery_insurance_rate"]
        + equipment_asset_yi * business["equipment_insurance_rate"]
    )
    # 池化维护 0.20%：老模型对标储能运维 0.4–0.5% 的 50%（池化管理强度较低）
    pooling_maintenance = battery_asset_yi * business["pooling_maintenance_rate"]
    # 仓储物流 0.05%：不建专门区域仓储网络，第三方物流+按需调拨包干（MANIFEST §8.2）
    warehouse_logistics = battery_asset_yi * business["warehouse_logistics_rate"]
    return {
        "battery_asset_yi": battery_asset_yi,
        "equipment_asset_yi": equipment_asset_yi,
        "insurance_yi": insurance,
        "pooling_maintenance_yi": pooling_maintenance,
        "warehouse_logistics_yi": warehouse_logistics,
    }


def build_pool_ancillary_revenue(
    config: dict, capex: CapexResult
) -> dict[str, tuple[float, float, float, float]]:
    """【新增｜分池】辅助服务收入按池（=站型）分列，总额与大类汇总口径严格一致。

    总额口径（build_ancillary_revenue）：容量补偿＋max(需求响应,调频)——后两项
    全局孰高（同一块电池同一时段只能干一件事）。
    分池拆分：容量补偿按池申报容量直算；孰高项在池层面分别算出需求响应/调频
    后，取全局获胜项的池值相加。四池之和恒等于大类汇总总额。
    返回 {pool_key: (合计, 容量补偿, 需求响应, 调频)}。
    """
    anc = config["ancillary_services"]
    capacity_by_pool: dict[str, float] = {}
    demand_by_pool: dict[str, float] = {}
    freq_by_pool: dict[str, float] = {}
    for pool_key, station_count in capex.station_targets.items():
        is_heavy = pool_key.startswith("qiji75")
        declared_kw = station_count * (
            anc["heavy_station_declared_kw"] if is_heavy else anc["choco_station_declared_kw"]
        )
        freq_kw = station_count * (
            anc["heavy_frequency_regulation_kw"] if is_heavy else anc["choco_frequency_regulation_kw"]
        )
        capacity_by_pool[pool_key] = (
            declared_kw * anc["capacity_compensation_price_rmb_kw_year"] / 1e8
        )
        demand_by_pool[pool_key] = (
            declared_kw
            * anc["demand_response_hours_year"]
            * anc["demand_response_price_rmb_kwh"]
            / 1e8
        )
        freq_by_pool[pool_key] = (
            freq_kw
            * anc["frequency_regulation_hours_year"]
            * anc["frequency_regulation_price_rmb_kwh"]
            / 1e8
        )
    winner = (
        demand_by_pool
        if sum(demand_by_pool.values()) >= sum(freq_by_pool.values())
        else freq_by_pool
    )
    return {
        pool_key: (
            capacity_by_pool[pool_key] + winner[pool_key],
            capacity_by_pool[pool_key],
            demand_by_pool[pool_key],
            freq_by_pool[pool_key],
        )
        for pool_key in capex.station_targets
    }


def _dcf_cross_check(
    config: dict, capex: CapexResult, ebitda: float, forward_fcff: float, ownership: float
) -> dict[str, float]:
    """DCF 交叉验证：项目自己的现金流支持多少倍 EV/EBITDA？

    不改变任何主链结论，只多产出一组对照数——用来回答报告第 5 章那个绕不开的问题：
    「你用 EBITDA 的 18 倍估值，那这门生意的现金流本身支持几倍？」

    两条口径（都用成熟期 FCFF，未扣建设期爬坡，故均偏乐观）：
      A 与门槛同源：EV = FCFF ÷ CRF。CRF 即设 required_ebitda 用的期望收益率年金因子，
        所以本口径与覆盖倍数完全同源，是模型内部最自洽的一条。
      B 成本线上界：EV = FCFF × 年金因子(WACC, 分析期)。WACC 只是成本下限，故给出上界。
    """
    finance = config["finance"]
    crf = finance["capital_recovery_factor"]
    wacc = finance["wacc"]
    horizon = finance["model_horizon_years"]
    debt_ratio = finance["debt_ratio"]
    multiple = finance["swap_ev_ebitda"]

    annuity_wacc = (1 - (1 + wacc) ** -horizon) / wacc
    ev_crf = forward_fcff / crf if crf else 0.0
    ev_wacc = forward_fcff * annuity_wacc
    debt = capex.lifecycle_capital_base_yi * debt_ratio
    catl_value_crf = max(0.0, ev_crf - debt) * ownership
    catl_value_multiple = max(0.0, ebitda * multiple - debt) * ownership
    implied_crf = ev_crf / ebitda if ebitda else 0.0
    return {
        "dcf_ev_at_crf_yi": ev_crf,
        "dcf_ev_at_wacc_yi": ev_wacc,
        "dcf_implied_multiple_at_crf": implied_crf,
        "dcf_implied_multiple_at_wacc": ev_wacc / ebitda if ebitda else 0.0,
        "dcf_multiple_premium": multiple / implied_crf if implied_crf else 0.0,
        "dcf_npv_at_crf_yi": ev_crf - capex.lifecycle_capital_base_yi,
        "dcf_catl_value_at_crf_yi": catl_value_crf,
        "dcf_catl_value_gap_yi": catl_value_multiple - catl_value_crf,
    }


def build_swap_business(config: dict, scale: ScaleResult, capex: CapexResult) -> SwapBusinessResult:
    """换电业务测算：先分池（四站型独立项目公司）计算，再汇总为总量。

    【重构｜4站型列示】v4.4 起经营链逐节点按池计算，SwapBusinessResult 的总量
    字段=四池之和：收入/OPEX 类线性分池；折旧、利息、债务按各池资本底座派生
    （capex.lifecycle_capital_base_by_pool 等）；净利润与可分派现金的 max(0,·)
    下限在池内生效——亏损站型不产生税盾抵扣盈利站型（每站型独立项目公司口径）。
    """
    business = config["swap_business"]
    finance = config["finance"]
    days = business["operating_days"]
    ownership = finance["construction_ownership"]
    tax_rate = finance["tax_rate"]
    crf = finance["capital_recovery_factor"]

    # ---- ① 车端运营装机按池（车型级终局存量取整口径不变，按池内原始车辆份额拆分，
    # 池内用池内加权装车电量——四池之和=原车型口径总装机，只补池维度不换总量）。
    vehicle_gwh_by_pool = {pk: 0.0 for pk in BATTERY_POOLS}
    for key in config["vehicles"]:
        relevant = [row for row in scale.rows if row.vehicle_key == key]
        total_veh = sum(row.catl_swap_vehicles_wan for row in relevant)
        if total_veh <= 0:
            continue
        stock = scale.operating_stock_by_vehicle_wan[key]
        for pool_key in sorted({row.battery_pool for row in relevant}):
            pool_rows = [row for row in relevant if row.battery_pool == pool_key]
            pool_veh = sum(row.catl_swap_vehicles_wan for row in pool_rows)
            pool_avg_onboard = (
                sum(row.catl_swap_vehicles_wan * row.onboard_battery_kwh for row in pool_rows)
                / pool_veh
            )
            vehicle_gwh_by_pool[pool_key] += (
                stock * (pool_veh / total_veh) * pool_avg_onboard / 100.0
            )

    # ---- ② 站内周转电池按池（池键=站型键，各用各站参数）。
    station_gwh_by_pool = {
        pk: capex.station_targets[pk]
        * config["stations"][pk]["inventory_blocks"]
        * config["stations"][pk]["block_kwh"]
        / 1e6
        for pk in BATTERY_POOLS
    }

    # ---- ③ 分池辅助服务（总额与大类汇总口径一致，见 build_pool_ancillary_revenue）。
    ancillary_by_pool = build_pool_ancillary_revenue(config, capex)

    # ---- ④ 电池银行侧费率三项按池（价格基准取 reference_year 现价，与总量口径一致）。
    price_now = battery_price_rmb_kwh(config, config["meta"]["reference_year"])
    bank_by_pool: dict[str, dict[str, float]] = {}
    for pk in BATTERY_POOLS:
        battery_asset_yi = (
            (vehicle_gwh_by_pool[pk] + station_gwh_by_pool[pk]) * 1e6 * price_now / 1e8
        )
        equipment_asset_yi = (
            capex.station_targets[pk]
            * config["stations"][pk]["station_body_capex_wan"]
            / 1e4
        )
        bank_by_pool[pk] = {
            "battery_asset_yi": battery_asset_yi,
            "equipment_asset_yi": equipment_asset_yi,
            "insurance_yi": (
                battery_asset_yi * business["battery_insurance_rate"]
                + equipment_asset_yi * business["equipment_insurance_rate"]
            ),
            "pooling_maintenance_yi": battery_asset_yi * business["pooling_maintenance_rate"],
            "warehouse_logistics_yi": battery_asset_yi * business["warehouse_logistics_rate"],
        }

    # ---- ⑤ 软件调度按站数份额分池（固定投入，跟随站网规模）。
    total_stations = sum(capex.station_targets.values())
    software_by_pool = {
        pk: business["software_opex_yi_year"]
        * (capex.station_targets[pk] / total_stations if total_stations else 0.0)
        for pk in BATTERY_POOLS
    }

    # ---- ⑥ 资本口径按池（capex 分池构建，四池之和=总量）。
    lifecycle_by_pool = capex.lifecycle_capital_base_by_pool
    dep_by_pool = capex.mature_annual_depreciation_by_pool
    initial_by_pool = capex.total_initial_capex_by_pool
    debt_by_pool = {pk: lifecycle_by_pool[pk] * finance["debt_ratio"] for pk in BATTERY_POOLS}
    capreq_by_pool = {pk: lifecycle_by_pool[pk] * crf for pk in BATTERY_POOLS}

    # ---- ⑦ 逐池推演经营链与现金回报。
    pool_ops: dict[str, PoolOperations] = {}
    for pk in BATTERY_POOLS:
        energy = scale.mature_annual_energy_yi_kwh[pk]
        service = energy * business["service_fee_rmb_kwh"]
        station_external_gwh = station_gwh_by_pool[pk] * (1.0 - ownership)
        rent_gwh = vehicle_gwh_by_pool[pk] + station_external_gwh
        battery_rent = rent_gwh * business["battery_rent_rmb_kwh_year"] / 100.0
        arbitrage = (
            station_gwh_by_pool[pk] * days * business["grid_spread_rmb_kwh"]
            * business["rte"] / 100.0
        )
        ancillary = ancillary_by_pool[pk][0]
        revenue = service + battery_rent + arbitrage + ancillary
        charged_energy = energy / business["rte"] * (1 + business["auxiliary_power_rate"])
        energy_cost = (charged_energy - energy) * business["valley_power_price_rmb_kwh"]
        station_rent = capex.station_targets[pk] * business["site_rent_wan_year"] / 1e4
        labor = (
            capex.station_targets[pk]
            * (
                business["heavy_station_labor_wan_year"]
                if pk.startswith("qiji75")
                else business["passenger_station_labor_wan_year"]
            )
            / 1e4
        )
        bank = bank_by_pool[pk]
        bank_total = (
            bank["insurance_yi"] + bank["pooling_maintenance_yi"] + bank["warehouse_logistics_yi"]
        )
        opex = energy_cost + station_rent + labor + software_by_pool[pk] + bank_total
        ebitda = revenue - opex
        depreciation = dep_by_pool[pk]
        interest = debt_by_pool[pk] * finance["debt_interest_rate"]
        # 税前利润为负时不交所得税，净利润=税前利润（亏损如实计入、不得归零）；
        # 仅对税前为正部分计税，亏损池不抵扣其他盈利池税盾（按站型独立计税）。
        pre_tax = ebitda - depreciation - interest
        project_np = pre_tax - max(0.0, pre_tax) * tax_rate
        catl_np = project_np * ownership
        ev = ebitda * finance["swap_ev_ebitda"]
        equity_value = max(0.0, ev - debt_by_pool[pk])
        catl_value = equity_value * ownership
        forward_fcff = ebitda * (1 - tax_rate) + depreciation * tax_rate
        minimum_distributable = max(0.0, capreq_by_pool[pk] - interest)
        forward_distributable = max(0.0, forward_fcff - interest)
        pool_ops[pk] = PoolOperations(
            annual_swaps_yi=scale.mature_daily_swaps[pk] * days / 1e8,
            annual_energy_yi_kwh=energy,
            service_revenue_yi=service,
            rent_vehicle_gwh=vehicle_gwh_by_pool[pk],
            station_battery_gwh=station_gwh_by_pool[pk],
            station_external_rent_gwh=station_external_gwh,
            rent_eligible_gwh=rent_gwh,
            battery_rent_yi=battery_rent,
            arbitrage_yi=arbitrage,
            ancillary_yi=ancillary,
            revenue_yi=revenue,
            charged_energy_yi_kwh=charged_energy,
            energy_cost_yi=energy_cost,
            station_rent_yi=station_rent,
            labor_yi=labor,
            software_opex_yi=software_by_pool[pk],
            insurance_yi=bank["insurance_yi"],
            pooling_maintenance_yi=bank["pooling_maintenance_yi"],
            warehouse_logistics_yi=bank["warehouse_logistics_yi"],
            opex_yi=opex,
            ebitda_yi=ebitda,
            depreciation_yi=depreciation,
            interest_yi=interest,
            pre_tax_profit_yi=pre_tax,
            project_net_profit_yi=project_np,
            catl_net_profit_yi=catl_np,
            enterprise_value_yi=ev,
            project_equity_value_yi=equity_value,
            catl_value_yi=catl_value,
            required_fcff_yi=capreq_by_pool[pk],
            minimum_distributable_yi=minimum_distributable,
            catl_minimum_distributable_yi=minimum_distributable * ownership,
            forward_fcff_yi=forward_fcff,
            forward_distributable_yi=forward_distributable,
            catl_forward_distributable_yi=forward_distributable * ownership,
            catl_initial_equity_yi=(
                initial_by_pool[pk] * (1 - finance["debt_ratio"]) * ownership
            ),
            catl_lifecycle_equity_yi=(
                lifecycle_by_pool[pk] * (1 - finance["debt_ratio"]) * ownership
            ),
        )

    # ---- ⑧ 汇总：总量=四池之和（线性项与原总量口径恒等；非线性下限项按池生效后求和）。
    def _sum(attr: str) -> float:
        return sum(getattr(pool_ops[pk], attr) for pk in BATTERY_POOLS)

    annual_energy = _sum("annual_energy_yi_kwh")
    service = _sum("service_revenue_yi")
    battery_rent = _sum("battery_rent_yi")
    arbitrage = _sum("arbitrage_yi")
    ancillary = _sum("ancillary_yi")
    revenue = _sum("revenue_yi")
    cumulative_vehicle_gwh = _sum("rent_vehicle_gwh")
    station_battery_gwh = _sum("station_battery_gwh")
    station_external_rent_gwh = _sum("station_external_rent_gwh")
    rent_gwh = _sum("rent_eligible_gwh")
    energy_cost = _sum("energy_cost_yi")
    station_rent = _sum("station_rent_yi")
    labor = _sum("labor_yi")
    software = _sum("software_opex_yi")
    opex = _sum("opex_yi")
    ebitda = _sum("ebitda_yi")
    depreciation = _sum("depreciation_yi")
    ebit = ebitda - depreciation
    interest = _sum("interest_yi")
    project_np = _sum("project_net_profit_yi")
    pre_tax_profit = _sum("pre_tax_profit_yi")
    catl_np = _sum("catl_net_profit_yi")
    ev = _sum("enterprise_value_yi")
    equity_value = _sum("project_equity_value_yi")
    catl_value = _sum("catl_value_yi")
    forward_fcff = _sum("forward_fcff_yi")
    minimum_distributable = _sum("minimum_distributable_yi")
    forward_distributable = _sum("forward_distributable_yi")
    catl_minimum_distributable = _sum("catl_minimum_distributable_yi")
    catl_forward_distributable = _sum("catl_forward_distributable_yi")
    catl_initial_equity = _sum("catl_initial_equity_yi")

    # 汇总级派生量：门槛EBITDA与覆盖倍数仍按项目整体口径（资本要求/折旧为全项目量）。
    required_ebitda = max(
        0.0,
        (capex.annual_capital_requirement_yi - depreciation * tax_rate)
        / (1 - tax_rate),
    )
    # 辅助服务三项分列（总额口径，与大类汇总一致）。
    _, capacity_comp, demand_resp, freq_reg = build_ancillary_revenue(config, capex)
    bank_totals = {
        attr: sum(bank_by_pool[pk][attr] for pk in BATTERY_POOLS)
        for attr in (
            "battery_asset_yi", "equipment_asset_yi", "insurance_yi",
            "pooling_maintenance_yi", "warehouse_logistics_yi",
        )
    }
    return SwapBusinessResult(
        annual_energy_yi_kwh=annual_energy,
        rent_vehicle_gwh=cumulative_vehicle_gwh,
        rent_station_external_gwh=station_external_rent_gwh,
        rent_eligible_gwh=rent_gwh,
        revenue_yi=revenue,
        service_revenue_yi=service,
        battery_rent_yi=battery_rent,
        arbitrage_yi=arbitrage,
        ancillary_yi=ancillary,
        opex_yi=opex,
        energy_cost_yi=energy_cost,
        station_rent_yi=station_rent,
        labor_yi=labor,
        software_opex_yi=software,
        ebitda_yi=ebitda,
        depreciation_yi=depreciation,
        ebit_yi=ebit,
        pre_tax_profit_yi=pre_tax_profit,
        project_net_profit_yi=project_np,
        catl_attributable_net_profit_yi=catl_np,
        enterprise_value_yi=ev,
        project_equity_value_yi=equity_value,
        catl_attributable_value_yi=catl_value,
        required_ebitda_yi=required_ebitda,
        forward_to_required_ebitda=ebitda / required_ebitda if required_ebitda else float("inf"),
        project_interest_yi=interest,
        required_fcff_yi=capex.annual_capital_requirement_yi,
        forward_fcff_yi=forward_fcff,
        **_dcf_cross_check(config, capex, ebitda, forward_fcff, ownership),
        minimum_distributable_cash_yi=minimum_distributable,
        catl_minimum_distributable_cash_yi=catl_minimum_distributable,
        forward_distributable_cash_yi=forward_distributable,
        catl_forward_distributable_cash_yi=catl_forward_distributable,
        catl_initial_equity_investment_yi=catl_initial_equity,
        catl_cash_yield_on_initial_equity=(
            catl_minimum_distributable / catl_initial_equity
            if catl_initial_equity else float("inf")
        ),
        catl_initial_payback_years=(
            catl_initial_equity / catl_minimum_distributable
            if catl_minimum_distributable else float("inf")
        ),
        catl_lifecycle_payback_years=(
            capex.catl_lifecycle_equity_commitment_yi / catl_minimum_distributable
            if catl_minimum_distributable else float("inf")
        ),
        # v4.3 新增：辅助服务分列（容量补偿无条件计入；后两项争夺同一份可调容量，
        # 须实际提供服务才有收益，故全局孰高、只有胜出方进 ancillary_yi）
        capacity_compensation_yi=capacity_comp,
        demand_response_candidate_yi=demand_resp,
        frequency_regulation_candidate_yi=freq_reg,
        ancillary_counted_item=("需求响应" if demand_resp >= freq_reg else "调频"),
        # v4.3 新增：电池银行侧费率三项及资产基数（=四池之和）
        battery_asset_yi=bank_totals["battery_asset_yi"],
        equipment_asset_yi=bank_totals["equipment_asset_yi"],
        insurance_yi=bank_totals["insurance_yi"],
        pooling_maintenance_yi=bank_totals["pooling_maintenance_yi"],
        warehouse_logistics_yi=bank_totals["warehouse_logistics_yi"],
        # v4.4 新增：四站型分池经营明细
        pool_operations=pool_ops,
    )


def build_manufacturing_cases(
    config: dict,
    scale: ScaleResult,
    capex: CapexResult,
    terminal_ownership: float | None = None,
) -> tuple[ManufacturingResult, ManufacturingResult]:
    years = scale.years
    target = years[-1]
    business = config["swap_business"]
    no_swap_gwh = scale.annual_catl_no_swap_gwh[target]
    # 外部权益比例：派生量（=1-自持比例），v4.2 独立键 swap_battery_external_sales_share 已废弃
    external_share = (
        1.0 - config["finance"]["construction_ownership"]
        if terminal_ownership is None else 1.0 - terminal_ownership
    )
    replacement_gwh = next(
        row.vehicle_replacement_gwh for row in capex.annual if row.year == target
    )
    with_swap_gwh = (
        scale.annual_catl_charge_gwh[target]
        + (scale.annual_catl_swap_gwh[target] + replacement_gwh) * external_share
    )
    price = battery_price_rmb_kwh(config, target)
    pe = config["finance"]["manufacturing_pe"]

    def make(
        label: str,
        gwh: float,
        margin: float,
        addressable_revenue: float = 0.0,
        locked_gwh: float = 0.0,
    ) -> ManufacturingResult:
        revenue = gwh * price / 100.0
        net_profit = revenue * margin
        return ManufacturingResult(
            label=label,
            shipments_gwh=gwh,
            revenue_yi=revenue,
            net_margin=margin,
            net_profit_yi=net_profit,
            equity_value_yi=net_profit * pe,
            swap_addressable_revenue_yi=addressable_revenue,
            swap_locked_gwh=locked_gwh,
        )

    # 本报告只建模电动车场景；有换电制造收入全部属于该场景的定价权保护范围。
    addressable_revenue = with_swap_gwh * price / 100.0
    # 换电段+更换循环×外部权益=被换电体系锁定、且确认为制造收入的订单装机。
    swap_locked_gwh = (scale.annual_catl_swap_gwh[target] + replacement_gwh) * external_share
    return (
        make("2030E无换电纯制造", no_swap_gwh, business["no_swap_manufacturing_net_margin"]),
        make(
            "2030E重资产换电",
            with_swap_gwh,
            business["with_swap_manufacturing_net_margin"],
            addressable_revenue,
            swap_locked_gwh,
        ),
    )

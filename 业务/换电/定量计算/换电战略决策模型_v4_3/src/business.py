"""经营与估值层：把 capex.py 算好的资本/折旧/debt，接上收入/成本，算出损益、
现金流、两套独立估值（倍数法／DCF），逐池（四站型）算完再汇总成总量。

【主入口只有一个：build_swap_business，其余函数分两类】
    build_swap_business(config, scale, capex) -> SwapBusinessResult
      是本文件唯一的"总装"函数，八个阶段（函数体内 ①…⑧ 注释对应）：
      车端装机分池→站内装机分池→辅助服务分池→电池银行费率分池→软件OPEX
      分池→资本口径分池（debt/折旧/门槛EAC，全部来自capex.py的分池字段）
      →逐池推演损益与两套估值→按池求和汇总成总量。**逐池算、逐池套
      max(0,·)下限、再求和，不是先总量算完再拆分**——这是"每站型独立
      项目公司"这个建模假设本身要求的：亏损站型不能用税盾/负debt去
      抵扣盈利站型，顺序颠倒会把独立项目公司的下限保护漏掉。
    子函数分两类：
      · build_pool_ancillary_revenue：build_swap_business ③会直接调用，
        是分池经营链的必需上游。
      · build_ancillary_revenue／build_battery_bank_rate_opex：**大类
        口径（不分池）的独立实现**，分别在总量层重算一遍"辅助服务三项
        分列"（供 SwapBusinessResult 的诊断字段）和"电池银行费率三项"
        （build_swap_business ④ 内联重写了分池版，这个大类版函数目前
        没有调用方，是历史遗留——数值口径应与分池版汇总一致，但没有
        断言强制校验，改任何一边前先确认另一边要不要同步改）。
      · build_2026_baseline：完全独立的口径，不吃 capex/scale，只算
        "2026年动力电池业务在集团里的净利/市值占比"这一个比较锚，
        供报告第1章"共识锚"用，跟换电经营链没有数据依赖。
      · _dcf_cross_check：build_swap_business ⑧汇总完总量后，作为最后
        一步被调用，是本文件里独立成篇、公式最复杂的一块，见其自身
        docstring（三条主线：debt统一、时点rebase、真实DCF）。

【参数怎么传递】
入参 config（base.toml）、scale（ScaleResult，车辆装机已算好）、capex
（CapexResult，资本/折旧/debt已按池算好——本文件不重新计算这些，只消费）。
出参 SwapBusinessResult（含 pool_operations 逐池明细 + 总量字段），是
consolidation.py／capital_cycle.py／tree.py 的上游。
"""
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
    config: dict,
    capex: CapexResult,
    pool_ops: dict[str, PoolOperations],
    ebitda: float,
    forward_fcff: float,
    ownership: float,
    catl_attributable_value: float,
) -> dict[str, float]:
    """DCF 交叉验证：项目自己的现金流支持多少倍 EV/EBITDA？

    不改变任何主链结论，只多产出一组对照数——用来回答报告第 5 章那个绕不开的问题：
    「你用 EBITDA 的 18 倍估值，那这门生意的现金流本身支持几倍？」

    两条捷径口径（都用成熟期 FCFF，未扣建设期爬坡，且未扣任何资本性支出，保留作对照，
    不再是主口径）：
      A 与门槛同源：EV = FCFF ÷ CRF。CRF 即设 required_ebitda 用的期望收益率年金因子，
        所以本口径与覆盖倍数完全同源，是模型内部最自洽的一条捷径。
      B 成本线上界：EV = FCFF × 年金因子(WACC, 分析期)。WACC 只是成本下限，故给出上界。

    【2026-09-05，第四轮，见 capex_debt_估值公式链.md 第四轮 + DECISIONS
    「2026-09-04c」「2026-09-05」，本条在09-04/09-04b的基础上再修两处、并改成分池】

    ① 有限期账（基础账，dcf_*_true_yi 三个既有字段）：去掉重复扣减——此前
       `ev_true = (forward_fcff − sustaining_capex) × 15年WACC年金因子`，而
       `npv_true = ev_true + 残值 − valuation_capital_target`里的
       valuation_capital_target 已经通过真实排期把2031-2045这段更新支出精确
       扣过一次，sustaining_capex是同一笔钱的近似值——被扣了两次。改为
       `ev_base = forward_fcff × 年金因子`（毛现金流，不再净sustaining_capex），
       capex侧的真实排期已经在valuation_capital_target里扣过，不用再扣一次。
       同时补一条对称的站体设备期末残值（现状"无更换、期末账面为0"）。
       验证（wacc=7.5%）：NPV从−1,371.9亿翻正到+1,650.9亿，隐含IRR从2.06%
       升到12.65%（详见公式链文档第四轮§4.1）。

    ② 新增永续账（开放上限，dcf_*_perpetual_yi）：`capex诊断.md`§8.4已经论证过
       "只算到2030满产、不建模2030后增长"是保守口径——两本账都不建模2030后
       的规模增长，差异只在于"停在2030规模不动"这件事延续多久（15年有限期，
       还是永续）。查证换电站没有类似光伏/风电/垃圾发电REITs那样"政府授予、
       有法定上限"的特许经营权框架（换电站走发改委备案，不是招投标授予的
       特许经营）；用地是商业/工业用地(40-50年，非约束)；宁德时代与中石化
       合作直接把换电站建在现有加油站场址上——"分布式储能构成的虚拟电网，
       类比国网/南网"这个定位站得住，该按永续经营建模。
       可持续资本性支出不再用折旧代理（历史成本口径，混了不同cohort装机年
       价格，已验证比真实排期平台期均值系统性偏高45.4%），改用
       `capex.steady_state_net_replacement_by_pool_yi`——按更新理论
       (renewal reward theorem)第一性原理算：稳态更新速率=Σ_池(机队GWh÷池
       寿命)，与具体日历年份无关。净更新支出本身逐年递减（电池降价，回收
       残值是同一条价格曲线的固定比例）——用递减永续年金（除数WACC+g，
       g=价格曲线长期降幅slow_annual_decline_rate）资本化，不是常数永续。
       站体设备（机械臂等自动化设备，15年周期，与折旧年限model_horizon_years
       同步，毛估估）按"每15年一笔"的递归永续现值处理
       （capex.station_equipment_perpetual_pv_by_pool_yi）。永续假设下不设
       终点，没有期末残值项。

    ③ 两本账都分池计算（capex分池字段：steady_state_debt_by_pool_yi、
       valuation_capital_pv_by_pool_yi、terminal_residual_pv_by_pool_yi、
       pure_initial_capex_pv_by_pool_yi、steady_state_net_replacement_by_pool_yi、
       station_equipment_*_by_pool_yi 均已按池算好），供报告展示四个池子各自
       的投入/回报，不只是总量口径。

    ④ debt 统一为 capex.steady_state_debt_yi（2030年在役批次历史成本×债务比），
       倍数法与本函数共用同一个数（T3 已解决）。

    ⑤ T5交叉验证（框架L/U）：仍用有限期账（ev_base）与sustaining_capex（折旧
       代理）——这条只是诊断对照，不受①②修正影响，理由见 capex_debt_
       估值公式链.md §3b（M-M定理U=L恒等要求debt逐期摊销，本模型debt是固定
       快照，两种"恒定杠杆"定义在有限期截断下本就不代数等价）。
    """
    finance = config["finance"]
    crf = finance["capital_recovery_factor"]
    wacc = finance["wacc"]
    tax_rate = finance["tax_rate"]
    debt_ratio = finance["debt_ratio"]
    horizon = finance["model_horizon_years"]
    multiple = finance["swap_ev_ebitda"]
    target_year = config["meta"]["target_year"]
    years = config["construction"]["years"]
    base_year = years[0]
    slow_decline = config["construction"]["battery_price_curve"]["slow_annual_decline_rate"]

    # 两条捷径EV，聚合口径，保留作对照（不再是主口径）。
    annuity_wacc = (1 - (1 + wacc) ** -horizon) / wacc
    ev_crf = forward_fcff / crf if crf else 0.0
    ev_wacc = forward_fcff * annuity_wacc

    debt = capex.steady_state_debt_yi
    debt_legacy = capex.lifecycle_capital_base_yi * finance["debt_ratio"]
    rebase_to_target = (1.0 + wacc) ** (target_year - base_year)

    # —— 分池：有限期账（基础账，去掉重复扣减）与永续账（开放上限）——
    ev_base_by_pool: dict[str, float] = {}
    npv_base_by_pool: dict[str, float] = {}
    catl_value_base_by_pool: dict[str, float] = {}
    ev_perp_by_pool: dict[str, float] = {}
    npv_perp_by_pool: dict[str, float] = {}
    catl_value_perp_by_pool: dict[str, float] = {}
    for pk in BATTERY_POOLS:
        fcff_pool = pool_ops[pk].forward_fcff_yi
        debt_pool = capex.steady_state_debt_by_pool_yi[pk]

        # 【2026-09-05d，见 DECISIONS 同日条】站体设备不设期末残值——15年周期在
        # 永续账里已经按"到期全额换新、不扣回收"处理（station_equipment_perpetual_pv），
        # 这隐含"设备到期即视为耗尽"；有限期账若再给同一台设备一份期末残值，
        # 等于两本账对同一资产的寿命终点持相互矛盾的假设。且换电行业没有设备二手
        # 市场的真实数据支撑这个折价比例（不像电池有完整可查的回收价格链），
        # 与其编一个数，不如维持"折旧到零=残值为零"这个更朴素、内部自洽的假设。
        terminal_target_pool = capex.terminal_residual_pv_by_pool_yi[pk] * rebase_to_target
        valuation_target_pool = capex.valuation_capital_pv_by_pool_yi[pk] * rebase_to_target

        ev_base_pool = fcff_pool * annuity_wacc  # 毛现金流资本化，不重复扣减
        ev_base_by_pool[pk] = ev_base_pool
        npv_base_by_pool[pk] = ev_base_pool + terminal_target_pool - valuation_target_pool
        catl_value_base_by_pool[pk] = (
            max(0.0, ev_base_pool + terminal_target_pool - debt_pool) * ownership
        )

        anchor_pool = capex.steady_state_net_replacement_by_pool_yi[pk]
        equip_perp_pool = capex.station_equipment_perpetual_pv_by_pool_yi[pk]
        ev_perp_pool = fcff_pool / wacc - anchor_pool / (wacc + slow_decline) - equip_perp_pool
        ev_perp_by_pool[pk] = ev_perp_pool
        npv_perp_by_pool[pk] = (
            ev_perp_pool - capex.pure_initial_capex_pv_by_pool_yi[pk] * rebase_to_target
        )
        catl_value_perp_by_pool[pk] = max(0.0, ev_perp_pool - debt_pool) * ownership

    ev_base = sum(ev_base_by_pool.values())
    npv_base = sum(npv_base_by_pool.values())
    catl_value_base = sum(catl_value_base_by_pool.values())
    ev_perp = sum(ev_perp_by_pool.values())
    npv_perp = sum(npv_perp_by_pool.values())
    catl_value_perp = sum(catl_value_perp_by_pool.values())

    implied_crf = ev_crf / ebitda if ebitda else 0.0
    implied_base = ev_base / ebitda if ebitda else 0.0
    implied_perp = ev_perp / ebitda if ebitda else 0.0

    terminal_residual_pv_target = capex.terminal_residual_pv_yi * rebase_to_target
    valuation_capital_target = capex.valuation_capital_pv_yi * rebase_to_target

    # CRF捷径EV，但debt与时点已修正（仍标"_at_crf"，如实反映EV仍是CRF年金捷径算出的）。
    npv_at_crf = ev_crf + terminal_residual_pv_target - valuation_capital_target
    catl_value_at_crf = max(0.0, ev_crf + terminal_residual_pv_target - debt) * ownership

    # ⑤【T5】框架L交叉验证：仍用有限期账（ev_base）与折旧代理sustaining_capex，
    # 不受①②修正影响（见docstring）。
    sustaining_capex = capex.mature_annual_depreciation_yi
    ke_true = (wacc - debt_ratio * finance["debt_interest_rate"] * (1 - tax_rate)) / (1 - debt_ratio)
    after_tax_interest = debt * finance["debt_interest_rate"] * (1 - tax_rate)
    fcfe_true = (forward_fcff - sustaining_capex) - after_tax_interest
    annuity_ke = (1 - (1 + ke_true) ** -horizon) / ke_true if ke_true else 0.0
    framework_l_equity = fcfe_true * annuity_ke
    framework_u_equity = ev_base - debt
    framework_ul_gap_pct = (
        (framework_l_equity - framework_u_equity) / framework_u_equity if framework_u_equity else 0.0
    )

    return {
        "dcf_ev_at_crf_yi": ev_crf,
        "dcf_ev_at_wacc_yi": ev_wacc,
        "dcf_ev_true_yi": ev_base,
        "dcf_implied_multiple_at_crf": implied_crf,
        "dcf_implied_multiple_at_wacc": ev_wacc / ebitda if ebitda else 0.0,
        "dcf_implied_multiple_true": implied_base,
        "dcf_multiple_premium": multiple / implied_crf if implied_crf else 0.0,
        "dcf_multiple_premium_true": multiple / implied_base if implied_base else 0.0,
        "dcf_npv_at_crf_yi": npv_at_crf,
        "dcf_npv_true_yi": npv_base,
        "dcf_catl_value_at_crf_yi": catl_value_at_crf,
        "dcf_catl_value_true_yi": catl_value_base,
        # 【2026-09-04】此前这里用内部现算的"倍数法归属"（第三个、从未暴露的debt版本，
        # 见 DECISIONS「2026-09-03b」）——debt统一后，直接用真正的倍数法headline数字
        # catl_attributable_value 相减，三份"倍数法归属"合并为一份（T3已解决）。
        "dcf_catl_value_gap_yi": catl_attributable_value - catl_value_base,
        "dcf_valuation_capital_pv_yi": capex.valuation_capital_pv_yi,
        "dcf_valuation_capital_pv_at_target_yi": valuation_capital_target,
        "dcf_valuation_debt_yi": debt,
        "dcf_terminal_residual_pv_yi": capex.terminal_residual_pv_yi,
        "dcf_terminal_residual_pv_at_target_yi": terminal_residual_pv_target,
        "dcf_legacy_debt_yi": debt_legacy,
        "dcf_ke_derived": ke_true,
        "dcf_framework_l_equity_yi": framework_l_equity,
        "dcf_framework_u_equity_yi": framework_u_equity,
        "dcf_framework_ul_gap_pct": framework_ul_gap_pct,
        # 【2026-09-05，第四轮】永续账（开放上限）。
        "dcf_ev_perpetual_yi": ev_perp,
        "dcf_npv_perpetual_yi": npv_perp,
        "dcf_catl_value_perpetual_yi": catl_value_perp,
        "dcf_implied_multiple_perpetual": implied_perp,
        "dcf_multiple_premium_perpetual": multiple / implied_perp if implied_perp else 0.0,
        "dcf_ev_base_by_pool_yi": ev_base_by_pool,
        "dcf_npv_base_by_pool_yi": npv_base_by_pool,
        "dcf_catl_value_base_by_pool_yi": catl_value_base_by_pool,
        "dcf_ev_perpetual_by_pool_yi": ev_perp_by_pool,
        "dcf_npv_perpetual_by_pool_yi": npv_perp_by_pool,
        "dcf_catl_value_perpetual_by_pool_yi": catl_value_perp_by_pool,
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
    # 【修正 2026-09-04｜debt统一为稳态口径】此前用 lifecycle_by_pool×债务比——
    # lifecycle_by_pool 是"各批次锚在自身t0的PV之和"，跨年份加总，不对应2030这一个
    # 时点的负债余额（本职是给下面 capreq_by_pool 这个门槛口径用的）。改用
    # capex.steady_state_debt_by_pool_yi（2030年在役批次的历史成本×债务比），
    # 与DCF线（_dcf_cross_check）共用同一个debt，两条线口径统一（T3已解决）。
    # 见 capex_debt_估值公式链.md 第3-4节。
    debt_by_pool = capex.steady_state_debt_by_pool_yi
    capreq_by_pool = {pk: lifecycle_by_pool[pk] * crf for pk in BATTERY_POOLS}

    # ---- ⑦ 逐池推演经营链与现金回报。
    pool_ops: dict[str, PoolOperations] = {}
    for pk in BATTERY_POOLS:
        energy = scale.mature_annual_energy_yi_kwh[pk]
        service = energy * business["service_fee_rmb_kwh"]
        station_external_gwh = station_gwh_by_pool[pk] * (1.0 - ownership)
        rent_gwh = vehicle_gwh_by_pool[pk] + station_external_gwh
        # 配置值是月租（元/kWh·月），年租 = 月租 × 12
        battery_rent = rent_gwh * business["battery_rent_rmb_kwh_month"] * 12.0 / 100.0
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
        **_dcf_cross_check(config, capex, pool_ops, ebitda, forward_fcff, ownership, catl_value),
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

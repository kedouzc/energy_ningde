from __future__ import annotations

from schemas import ModelSnapshot


def _pct(value: float, digits: int = 1) -> str:
    return f"{value:.{digits}%}"


def _num(value: float, digits: int = 1) -> str:
    return f"{value:,.{digits}f}"


def _seq(values: list[float], percent: bool = False) -> str:
    if percent:
        return "/".join(_pct(value, 0) for value in values)
    return "/".join(f"{value:g}" for value in values)


def _vehicle_summary(snapshot: ModelSnapshot) -> dict[str, dict[str, float]]:
    """返回进入终局决策链的规范化节点，而不是重新使用未取整明细。"""
    return {
        key: {
            "vehicles_wan": vehicles,
            "frequency": snapshot.scale.terminal_frequency_by_vehicle[key],
            "daily_swaps": vehicles
            * 1e4
            * snapshot.scale.terminal_frequency_by_vehicle[key],
        }
        for key, vehicles in snapshot.scale.operating_stock_by_vehicle_wan.items()
    }


def _vehicle_battery_life(snapshot: ModelSnapshot) -> dict[str, float]:
    """各车型按CATL换电装机GWh加权的**推算**寿命。

    寿命已不再硬编码于配置，改为按《超换一体.md》§2.1 的2000次循环临界点÷年循环次数、
    与日历寿命封顶取 min 推算；同车型不同场景频次不同→寿命不同，故按装机GWh加权取代表值。
    """
    result: dict[str, float] = {}
    for key in snapshot.scale.operating_stock_by_vehicle_wan:
        key_rows = [row for row in snapshot.scale.rows if row.vehicle_key == key]
        gwh = sum(row.catl_swap_gwh for row in key_rows)
        result[key] = (
            sum(row.catl_swap_gwh * row.battery_life_years for row in key_rows) / gwh
            if gwh else 0.0
        )
    return result


def station_reconciliation_rows(
    config: dict, snapshot: ModelSnapshot
) -> list[tuple[str, ...]]:
    """对齐v3.2主文展示值与当前版本规范化节点；只用于审计，不参与模型。"""
    current = _vehicle_summary(snapshot)
    lives = _vehicle_battery_life(snapshot)
    passenger_keys = ("taxi", "ridehail", "robotaxi")
    passenger_vehicles = sum(current[key]["vehicles_wan"] for key in passenger_keys)
    passenger_daily = sum(current[key]["daily_swaps"] for key in passenger_keys)
    passenger_frequency = passenger_daily / (passenger_vehicles * 1e4)
    choco_vehicles = (
        current["city"]["vehicles_wan"]
        + passenger_vehicles
        + current["private"]["vehicles_wan"]
    )
    choco_daily = snapshot.scale.daily_swaps_by_category["choco"]
    rows = [
        (
            "重卡",
            "38.0",
            _num(current["heavy"]["vehicles_wan"], 1),
            "1.80（展示值）",
            _num(current["heavy"]["frequency"], 1),
            "68.4",
            _num(current["heavy"]["daily_swaps"] / 1e4, 1),
            "车辆不变；在车型终局节点把加权频次保留1位",
        ),
        (
            "城配物流",
            "87.0",
            _num(current["city"]["vehicles_wan"], 1),
            "1.30（展示值）",
            _num(current["city"]["frequency"], 1),
            "113.1",
            _num(current["city"]["daily_swaps"] / 1e4, 1),
            "v3把年度56.25万先取整为57万，逐层放大到87万；1.266是频次，不是存量",
        ),
        (
            "乘用营运（出租+网约+Robotaxi）",
            "88.0",
            _num(passenger_vehicles, 1),
            "1.42（合并展示值）",
            _num(passenger_frequency, 1),
            "125.0",
            _num(passenger_daily / 1e4, 1),
            "逐车型在终局节点各保留1位，再汇总交易量",
        ),
        (
            "私家车",
            "145.0",
            _num(current["private"]["vehicles_wan"], 1),
            "0.20（展示值）",
            _num(current["private"]["frequency"], 1),
            "29.0",
            _num(current["private"]["daily_swaps"] / 1e4, 1),
            "终局车辆和频次均保留1位",
        ),
        (
            "巧克力合计",
            "320.0",
            _num(choco_vehicles, 1),
            "按三段加总",
            _num(choco_daily / (choco_vehicles * 1e4), 1),
            "267.1",
            _num(choco_daily / 1e4, 1),
            "规划能力仍为300次/日；差异来自车辆节点和频次节点口径",
        ),
    ]
    return rows


def parameter_audit_rows(config: dict, snapshot: ModelSnapshot) -> list[tuple[str, ...]]:
    """完整核对会进入主链的数值参数；文本标签与来源URL不列入数值审计。"""
    scale = snapshot.scale
    capex = snapshot.capex
    business = config["swap_business"]
    finance = config["finance"]
    current = _vehicle_summary(snapshot)
    lives = _vehicle_battery_life(snapshot)
    heavy = config["vehicles"]["heavy"]
    city = config["vehicles"]["city"]
    taxi = config["vehicles"]["taxi"]
    ridehail = config["vehicles"]["ridehail"]
    robotaxi = config["vehicles"]["robotaxi"]
    private = config["vehicles"]["private"]
    heavy_scenes = heavy["scenes"]
    private_scenes = private["scenes"]
    rows: list[tuple[str, ...]] = []

    def add(
        category: str,
        parameter: str,
        old: str,
        new: str,
        status: str,
        reason: str,
        impact: str,
    ) -> None:
        rows.append((category, parameter, old, new, status, reason, impact))

    add("模型边界", "建设/目标年份", "2026—2030", f"{config['construction']['years'][0]}—{config['construction']['years'][-1]}", "一致", "共同规模窗口", "车辆、装机、建设期CAPEX")
    add("模型边界", "全周期观察期", "15年", f"{finance['model_horizon_years']}年", "一致", "用于重置与期末残值", "全周期资本、折旧")
    add("资本", "WACC", "7.5%", _pct(finance["wacc"]), "一致", "横向照抄蔚来ABS，只作折现", "重置现值、残值现值")
    add("资本", "回报要求/CRF", "10%—15%；主链CRF=15%", f"{_pct(finance['required_return_range'][0],0)}—{_pct(finance['required_return_range'][1],0)}；CRF={_pct(finance['capital_recovery_factor'],0)}", "一致", "CRF不由WACC推导", "门槛FCFF、门槛EBITDA")
    add("资本", "税率/债务比例/债息", "25% / 60% / 2.5%", f"{_pct(finance['tax_rate'],0)} / {_pct(finance['debt_ratio'],0)} / {_pct(finance['debt_interest_rate'])}", "一致", "资本结构未改", "净利润、债务、运营价值")
    add("资本", "建设期CATL经济权益", "40%", _pct(finance["construction_ownership"],0), "一致", "2030前不分档", "资本调用、归母利润与价值")
    add("估值", "制造PE/运营EV-EBITDA", "20× / 18×", f"{finance['manufacturing_pe']:g}× / {finance['swap_ev_ebitda']:g}×", "一致", "沿用v3主估值口径", "制造价值、换电运营价值")
    add("估值", "资管平台参数", "v3正文未形成独立可调三参数", f"费率{_pct(finance['manager_fee_rate'])} / 净利率{_pct(finance['manager_net_margin'],0)} / PE{finance['manager_pe']:g}×", "已移除", "Part6改为两层估值后不再计算资管平台价值；参数仅存档，待真实滚动发行AUM出现才可能启用", "不再影响任何估值结果")
    add("估值", "交易成本率", "未单列", _pct(finance["transaction_cost_rate"]), "新增项", "从毛回款扣除", "轻资产净回款")

    add("需求", "重卡存量/更新周期", "900万 / 9年", f"{heavy['stock_wan']:g}万 / {heavy['replacement_cycle_years']:g}年", "一致", "存量更新法", "重卡EV基数")
    add("需求", "重卡NEV渗透率", "35%/43%/46%/48%/50%", _seq(heavy["nev_rates"], True), "一致", "逐年S曲线", "重卡EV基数")
    add("需求", "重卡场景权重", "38%/50%/12%", _seq([row["weight"] for row in heavy_scenes], True), "一致", "短/中/长途", "重卡车辆与频次加权")
    add("需求", "重卡换电渗透率", "30%/50%/70%", _seq([row["swap_penetration"] for row in heavy_scenes], True), "一致", "逐场景相乘", "重卡CATL换电车辆")
    add("需求", "重卡CATL换电市占率", "30%/30%/70%", _seq([row["catl_swap_share"] for row in heavy_scenes], True), "一致", "基准不确认启源协同", "重卡CATL换电车辆")
    add("需求", "2025既有CATL换电重卡", "0.7万", f"{heavy['existing_catl_swap_stock_wan']:g}万", "已恢复", "作为2026累计底座，不是启源协同", "重卡车辆、装机、站数、CAPEX")
    add("需求", "重卡单车电量/寿命", "500kWh / 5.7年（旧硬编码）", f"{heavy['battery_kwh']:g}kWh / {lives['heavy']:g}年", "改为推算", "寿命=min(2000次÷年循环, 10年)，不再硬编码", "制造收入、电池CAPEX")
    add("需求", "重卡里程/背电/电耗", "130/400/650km；342/513/513kWh；1.5/1.7/1.7", "/".join(f"{row['daily_km']:g}" for row in heavy_scenes)+"km；"+"/".join(f"{row['onboard_battery_kwh']:g}" for row in heavy_scenes)+"kWh；"+"/".join(f"{row['energy_consumption_kwh_km']:g}" for row in heavy_scenes), "一致", "频次改为逐场景未取整推导", "重卡日需求、站数、交易量")

    add("需求", "城配存量/周期/NEV", "1,500万 / 8年 / 50%—95%", f"{city['stock_wan']:g}万 / {city['replacement_cycle_years']:g}年 / {_seq(city['nev_rates'], True)}", "一致", "高频场景权重另列", "城配EV基数")
    add("需求", "城配场景", "高频30%，换电50%，CATL 80%；低频不换电", f"高频{_pct(city['scenes'][0]['weight'],0)}，换电{_pct(city['scenes'][0]['swap_penetration'],0)}，CATL{_pct(city['scenes'][0]['catl_swap_share'],0)}；低频不换电", "一致", "不先合成平均比例", "城配换电车辆")
    add("需求", "城配电量/里程/电耗/寿命", "80kWh / 300km / 0.27 / 3.8年（旧硬编码）", f"{city['battery_kwh']:g}kWh / {city['daily_km']:g}km / {city['energy_consumption_kwh_km']:g} / {lives['city']:g}年", "改为推算", "频次精确推导；寿命=min(2000次÷年循环, 10年)", "城配交易量、CAPEX")
    add("需求", "出租/网约里程池参数", "3,500亿km；Robotaxi 50万×350km×330天；有人350km×330天；出租139万", f"{config['operating_demand']['pool_2030_yi_km']:g}亿km；{config['operating_demand']['robotaxi_fleet_wan']:g}万×{config['operating_demand']['robotaxi_daily_km']:g}×{config['operating_demand']['robotaxi_days']:g}；有人{config['operating_demand']['human_daily_km']:g}×{config['operating_demand']['human_days']:g}；出租{config['operating_demand']['taxi_stock_wan']:g}万", "一致", "需求侧反推活跃车", "出租/网约存量")
    add("需求", "出租/网约NEV渗透率", "92%/94%/96%/98%/100%", _seq(taxi["nev_rates"], True), "已恢复", "旧代码曾误写96%平值；现按主文逐年值", "出租/网约车辆")
    add("需求", "出租与网约日里程", "450 / 342km", f"{taxi['daily_km']:g} / {ridehail['daily_km']:g}km", "一致", "分别计算频次", "巧克力日需求")
    add("需求", "出租/网约共用参数", "56kWh；8年；换电50%；CATL 50%；寿命3.8年（旧硬编码）", f"{taxi['battery_kwh']:g}kWh；{taxi['replacement_cycle_years']:g}年；换电{_pct(taxi['scenes'][0]['swap_penetration'],0)}；CATL{_pct(taxi['scenes'][0]['catl_swap_share'],0)}；寿命{lives['taxi']:g}/{lives['ridehail']:g}年", "改为推算", "寿命=min(2000次÷年循环, 10年)，出租频次高故短于网约", "车辆、装机、交易量")
    add("需求", "Robotaxi逐年净增", "0/0/5/15/30万", _seq(robotaxi["annual_net_additions_wan"])+"万", "一致", "累计50万", "车辆、装机、交易量")
    add("需求", "Robotaxi运营参数", "56kWh；450km；换电/CATL 100%；寿命3.8年（旧硬编码）", f"{robotaxi['battery_kwh']:g}kWh；{robotaxi['daily_km']:g}km；换电/CATL 100%；寿命{lives['robotaxi']:g}年", "改为推算", "站数频次沿用主文450km；寿命=min(2000次÷年循环, 10年)", "巧克力日需求、CAPEX")
    add("需求", "私家车逐年净增", "1,200/1,300/1,600/2,000/2,300万", _seq(private["annual_net_additions_wan"])+"万", "一致", "累计8,400万", "私家车底座")
    add("需求", "私家价格带权重", "12.3%/40.4%/47.3%", _seq([row["weight"] for row in private_scenes], True), "一致", "分档计算", "私家换电车辆")
    add("需求", "私家换电渗透/CATL市占", "0%/5%/3%；CATL 50%", _seq([row["swap_penetration"] for row in private_scenes], True)+f"；CATL {_pct(private_scenes[0]['catl_swap_share'],0)}", "一致", "中性情景", "私家换电车辆")
    add("需求", "私家电量/里程/电耗/寿命", "56kWh / 60km / 0.15 / 10年", f"{private['battery_kwh']:g}kWh / {private['daily_km']:g}km / {private['energy_consumption_kwh_km']:g} / {lives['private']:g}年", "按主文", "旧配置66.7km/90%与主文60km/80%冲突；现跟主文；寿命改为推算后低频使循环寿命>10年、由日历封顶兜住10年", "频次、站数、CAPEX")
    add("需求", "无换电CATL份额(=charge_share中性档)", "营运35%；私家33%", f"重卡/城配/出租/网约/Robotaxi {_pct(config['drivers']['charge_share']['中性']['heavy'],0)}；私家{_pct(config['drivers']['charge_share']['中性']['private'],0)}", "一致", "无换电基准改由 charge_share 中性档派生（不再单列 no_swap_catl_share）", "无换电制造装机")

    add("频次", "可用电量比例", "80%", _pct(business["usable_energy_factor"],0), "一致", "剩余20%换电", "全部车型频次与交易电量")
    add("频次", "重卡加权频次", "1.80次/日（展示值）", f"{current['heavy']['frequency']:.1f}次/日", "一致", "分场景原值加权，在车型终局节点保留1位", "重卡站数维持3,563")
    add("频次", "城配频次", "1.30次/日（展示值）", f"{current['city']['frequency']:.1f}次/日", "一致", "300÷(81×80%÷0.27)=1.25，在车型终局节点保留1位", "与85.5万辆共同反推日需求")
    add("频次", "出租/网约/Robotaxi/私家", "1.5/1.1/1.5/0.2", f"{current['taxi']['frequency']:.1f}/{current['ridehail']['frequency']:.1f}/{current['robotaxi']['frequency']:.1f}/{current['private']['frequency']:.1f}", "一致", "由里程、背电与电耗推导后在车型终局节点保留1位", "巧克力日需求与站数")

    # 【4站型】v3.2 对照仍按两大类展示；站参数取代表站型（骐骥两站型/巧克力两站型同源参数）。
    for group, old_label in (
        ("heavy", "重卡"),
        ("choco", "巧克力"),
    ):
        representative = (
            "qiji75_short" if group == "heavy" else "choco25_passenger"
        )
        station = config["stations"][representative]
        old_station = "500万/24块×171kWh/5.7年（旧硬编码）" if group == "heavy" else "200万/14块×56kWh/3.8年（旧硬编码）"
        # 四池口径：站内电池寿命按组内两池并列展示（池间寿命可能分化，不再取单一组值）。
        pool_lives = snapshot.scale.battery_pool_life_years
        group_pool_lives = "/".join(
            f"{pool_lives[pk]:g}" for pk in ("qiji75_short", "qiji75_trunk")
            if pk in pool_lives
        ) if group == "heavy" else "/".join(
            f"{pool_lives[pk]:g}" for pk in ("choco25_passenger", "choco35_city")
            if pk in pool_lives
        )
        new_station = f"{station['station_body_capex_wan']:g}万/{station['inventory_blocks']:g}块×{station['block_kwh']:g}kWh/{group_pool_lives}年"
        add("站网", f"{old_label}站体/库存/寿命", old_station, new_station, "改为推算", "站体不含电池；站内电池寿命按四池口径推算（组内两池并列）", "站体与站内电池CAPEX")
        old_physical = "4,500kW/16h/300秒" if group == "heavy" else "1,120kW/24h/100秒"
        new_physical = f"{station['charging_power_kw']:,.0f}kW/{station['operating_hours_day']:g}h/{station['swap_duration_seconds']:g}秒"
        add("站网", f"{old_label}物理校验", old_physical, new_physical, "一致", "只校验规划能力不越过物理上限", "诊断项，不直接进入CAPEX")
    add("站网", "重卡规划能力", "192次/日", f"{config['stations']['qiji75_short']['planning_daily_capacity']:g}次/日", "一致", "官方16h×5分钟口径（骐骥两站型同源）", "重卡站数分母")
    add("站网", "巧克力规划能力", "300次/日（毛估估）", f"{config['stations']['choco25_passenger']['planning_daily_capacity']:g}次/日（外生）", "口径澄清", "不再用1.84倍冗余倒算；物理上限只作校验（巧克力两站型同源）", "巧克力站数分母")
    add("站网", "巧克力工位物理上限", "822次/日（含衔接裕量）", f"{scale.station_capacity_diagnostics['choco25_passenger']['mechanical_limit']:.0f}次/日（100秒理论值）", "诊断差异", "两者均高于能量上限且不参与300规划值", "无主模型数值影响")
    add("站网", "终局站数", "重卡3,563；巧克力8,902", f"重卡{scale.station_demand_by_category['heavy']:,}；巧克力{scale.station_demand_by_category['choco']:,}", "重卡一致/巧克力变化", "车辆和频次在终局节点各保留1位；基准启源协同为0", "站体/站内电池CAPEX、场租、站内电池租金与套利")
    add("站网", "2025年末存量站", "正文未从2026新增任务中扣除", f"重卡{config['construction']['opening_2025_stations']['heavy']:,}；巧克力{config['construction']['opening_2025_stations']['choco']:,}", "已纠错", "存量属于终局总资产，但不是2026新增现金", "下调2026新增站体/站内电池CAPEX；不改终局CAPEX")
    add("站网", "2026累计/2028完工", "v3排期按总量均摊至2028（1,247/3,116起）", f"2026累计={config['construction']['station_2026_cumulative_targets']['heavy']:,}/{config['construction']['station_2026_cumulative_targets']['choco']:,}；{config['construction']['station_network_completion_year']}完工", "规划校准", "2026新增=累计目标－2025存量，剩余在2028前完成", "年度CAPEX峰值；不改终局需求")

    curve = config["construction"]["battery_price_curve"]
    add("电池价格", "2026—2030价格路径", "590/590/590/566.4/543.7元/kWh", "/".join(f"{value:.1f}" for value in capex.battery_price_path_rmb_kwh.values())+"元/kWh", "一致", "平台至2028，2029起年降4%", "初装、更新、制造收入")
    add("电池价格", "平台/快降/慢降", "2028止；2033止；-4%/-2.5%~3%", f"{curve['platform_end_year']}止；{curve['rapid_decline_end_year']}止；-{_pct(curve['rapid_annual_decline_rate'],1)}/-{_pct(curve['slow_annual_decline_rate'],2)}", "一致", "将旧表年份数组改为曲线生成", "所有未来电池价格")
    add("残值", "储能/动力价格比×退役SOH×二手折价", "0.917×80%×60%（旧表每次再乘届时价格折）", f"{curve['storage_to_power_price_ratio']:.3f}×{_pct(curve['retirement_soh'],0)}×{_pct(curve['secondary_market_discount'],0)}={_pct(capex.retirement_recovery_ratio,2)}（相对同年新电池）", "公式澄清", "44.016%不是相对初装的固定残值率", "每次更新净CAPEX")
    # v4.3 格式修正（2026-08-29）：残值率/资本倍数原为"/"连接长串（不分寿命档、不可读），
    # 改为按寿命档逐行展开；v3.2 只有 5.7/3.8/10 年三档硬编码，其余档旧值记"—"。
    _v32_residual = {5.7: "约32.9%", 3.8: "约32.9%", 10.0: "约31.7%"}
    _v32_factor = {5.7: "1.46×", 3.8: "1.78×", 10.0: "1.21×"}

    def _v32_match(life: float) -> float | None:
        return next((old for old in _v32_residual if abs(life - old) < 0.05), None)

    residual_items = sorted(
        capex.terminal_residual_by_life.items(),
        key=lambda kv: float(kv[0].replace("年", "")),
    )
    factor_map = capex.lifecycle_factor_by_life
    for label, residual in residual_items:
        life = float(label.replace("年", ""))
        old_key = _v32_match(life)
        factor = factor_map.get(label, 0.0)
        add(
            "残值",
            f"寿命{life:.1f}年档：残值率/资本倍数",
            f"{_v32_residual.get(old_key, '—')} / {_v32_factor.get(old_key, '—')}",
            f"{_pct(residual, 1)} / {factor:.2f}×",
            "派生精度" if old_key is None else "重推",
            "按届时价格、批次年龄、SOH和WACC路径逐批次推导（v4.3 从硬编码寿命改为循环推算，寿命档随之变化）",
            "折旧基数；全周期资本、门槛EBITDA、债务",
        )
    add("更新", "3.8年首轮更新年度拆分", "第3年20%＋第4年80%", "事件年3.8按相邻年度20%/80%", "一致", "非整数寿命批次分配", "2029—2030更新CAPEX")

    add("经营", "运营天数/服务费/电池月租金", "350天 / 0.4元/kWh / 10元/kWh月", f"{business['operating_days']:g}天 / {business['service_fee_rmb_kwh']:g}元/kWh / {business['battery_rent_rmb_kwh_month']:g}元/kWh月", "一致", "核心经营单价", "服务收入、租金收入")
    add("经营", "租金资产范围", "主文：仅装车；修订记录：装车+站内×60%（内部冲突）", "装车电池+站内电池×外部权益60%", "按v3.2最终修订口径", "只对外部股东对应电池确认租金，不确认CATL内部权益租金", "站数通过站内外部权益电池租金影响EBITDA")
    add("经营", "峰谷/RTE/自耗/谷价", "0.4 / 92% / 2% / 0.3元", f"{business['grid_spread_rmb_kwh']:g} / {_pct(business['rte'],0)} / {_pct(business['auxiliary_power_rate'],0)} / {business['valley_power_price_rmb_kwh']:g}元", "一致", "净额法", "套利与损耗电费")
    add("经营", "场租/人工/软件", "30万站年；重卡30元/次、乘用13元/次；20亿/年", f"{business['site_rent_wan_year']:g}万站年；重卡{business['heavy_station_labor_wan_year']:g}万/站年、巧克力{business['passenger_station_labor_wan_year']:g}万/站年；{business['software_opex_yi_year']:g}亿/年", "口径变更", "场租统一15万；人工改按站计价（重卡2人双班；巧克力0.2人/站保守档=5站共用1名巡检员，官方3公里服务半径口径下1人覆盖约25–40km行程圈）；软件三路径核验后取2亿", "EBITDA")
    add("经营", "辅助服务", "约5.15亿元/年", f"{snapshot.swap_business.ancillary_yi:.1f}亿元/年（容量补偿+max(需求响应,调频)计算值）", "口径变更", "固定值废除，改随站数动态计算", "EBITDA")
    add("制造", "换电资产外部权益/制造确认", "60%", _pct(1.0 - config["finance"]["construction_ownership"],0), "一致", "40%内部经济权益简化抵销；外部权益改为派生量（=1-自持比例）", "换电电池制造出货")
    add("制造", "有/无换电净利率", "15% / 12.5%", f"{_pct(business['with_swap_manufacturing_net_margin'],1)} / {_pct(business['no_swap_manufacturing_net_margin'],1)}", "一致", "沿用v3.2加权反推锚：15%/12.5%，净利率差2.5pct（换电锁量锁价的定价权保护）", "制造净利润与价值")
    add("制造", "制造范围", "只算已建模电动车", "只算已建模电动车；未建模装机不并入", "已纠错", "取消来历不明的其余动力装机CAGR", "制造价值回到约v3口径")
    add("资本结果", "项目债务口径", "全周期资本底座×60%", f"{_num(capex.lifecycle_capital_base_yi,1)}×60%={_num(capex.project_debt_yi,1)}亿元", "已纠错", "不是初装CAPEX×60%", "利息、运营权益价值")

    funding = config["group_funding"]
    add("集团资金", "期初现金类资产", "3,335亿元（旧时点）", f"{_num(funding['initial_cash_and_trading_assets_yi'],2)}亿元", "时点更新", "2026H1现金+交易性金融资产", "集团资金余量")
    add("集团资金", "净利润/CFO预测", "净利未单列；CFO 1,200/1,275/1,350/1,500/1,800", f"净利{_seq(funding['projected_group_net_profit_yi'])}；CFO{_seq(funding['projected_group_cfo_yi'])}", "新增/更新", "净利润只推分红；原始CFO独立输入，再扣资本/筹资支出形成可投资金盘", "年度资金表")
    add("集团资金", "分红率/回购", "分红绝对额约1/3净利口径；回购400亿", f"分红{_pct(funding['dividend_payout_ratio'],0)}；回购{funding['buyback_yi'][0]:g}亿", "时点更新", "按近年习惯作压力情景", "年度资金余量")
    add("集团资金", "最低流动性", "3,000亿元储备线", f"{funding['minimum_liquidity_yi']:g}亿元", "一致", "战略安全垫", "轻资产触发判断")
    base_mna_price = next(
        item["purchase_price_yi"]
        for item in config["mna"]["scenarios"]
        if item["name"] == config["mna"]["base_scenario_name"]
    )
    mna_2026_total = funding["known_catl_direct_mna_cash_yi"][0] + base_mna_price
    add("集团资金", "已识别直接并购现金", "未纳入", f"2026年三项合计{_num(mna_2026_total,2)}亿元（中恒29.03＋世纪互联64.00＋启源{_num(base_mna_price,2)}）", "合并三项", "世纪互联按审慎口径补入；启源经并购基准情景进入资金表", "年度资金余量")

    add("轻资产", "终局权益档", "10%/20%/30%/40%", _seq(config["light_asset"]["terminal_ownership_options"], True), "一致", "仅成熟后比较", "回款、持续利润与价值")
    add("轻资产", "数据/标准/技术场景控制", "所有档位必须保留", "三项均为硬约束", "一致", "经济权益与业务控制分开", "方案可行性门槛")
    first_mna = next(
        item for item in config["mna"]["scenarios"]
        if item["name"] == config["mna"]["base_scenario_name"]
    )
    add("并购", "启源基准现金/市占协同/物理复用", "v3未建模", f"{first_mna['purchase_price_yi']:.2f}亿元 / +{_pct(first_mna['heavy_catl_swap_share_uplift'],0)} / {first_mna['physically_reusable_heavy_stations']}站", "新增且隔离", "已摘牌但未整合；基准不提前确认协同", "现金支出；不改变基准车辆、站数、CAPEX或EBITDA")
    add("并购", "蔚来两种收购方案", "v3未建模", "全网络+电池银行 / 仅电池银行", "情景项", "相对纯自建比较交易现金、自建节省和协同", "CATL现金增量、项目债务与动力线价值")

    return rows


def outcome_audit_rows(snapshot: ModelSnapshot) -> list[tuple[str, ...]]:
    """把参数/口径变化最终收束到可供拍板的核心结果。"""
    capex = snapshot.capex
    swap = snapshot.swap_business
    ledger = snapshot.ledger
    baseline = ledger.baseline
    return [
        (
            "2026E电动车制造基准价值（装机量法，仅作交叉校验）",
            "11,399",
            _num(baseline.modeled_power_market_value_2026e_yi, 1),
            "基本一致",
            "同为644GWh×590元×15%×PE20；v4.3拍板：此法仅校验下行分摊法结果，两法差异<5%口径内",
        ),
        (
            "2026E动力分部市值分摊基准（主口径）",
            "未作为主分母",
            _num(baseline.power_market_value_2026e_yi, 1),
            "口径拍板",
            "2026-08拍板：只用分摊法（2026H1动力毛利润占集团毛利润×当前A+H市值），装机量法降为校验",
        ),
        (
            "重卡/巧克力终局站数",
            "3,563 / 8,902",
            f"{snapshot.scale.station_demand_by_category['heavy']:,} / {snapshot.scale.station_demand_by_category['choco']:,}",
            f"{snapshot.scale.station_demand_by_category['heavy'] - 3563:+,} / {snapshot.scale.station_demand_by_category['choco'] - 8902:+,}",
            "车辆与频次在车型终局节点各保留1位；启源基准协同为0",
        ),
        (
            "初装项目CAPEX",
            "2,782.0",
            _num(capex.total_initial_capex_yi, 1),
            _num(capex.total_initial_capex_yi - 2782.0, 1),
            "取消结果锚校准；由逐年车辆、站内电池和站体直接求和",
        ),
        (
            "2029—2030首轮更新净CAPEX",
            "58.1",
            _num(capex.first_replacement_net_capex_yi, 1),
            _num(capex.first_replacement_net_capex_yi - 58.1, 1),
            (
                "寿命模型从硬编码改为循环推算（2000次临界÷年循环次数，四池口径）："
                f"重卡站电池5.7→倒短{_num(snapshot.scale.battery_pool_life_years['qiji75_short'], 2)}/"
                f"干线{_num(snapshot.scale.battery_pool_life_years['qiji75_trunk'], 2)}年"
                f"（干线更新提前进2029-30窗，倒短拉长）；"
                f"巧克力站3.8→乘用{_num(snapshot.scale.battery_pool_life_years['choco25_passenger'], 2)}/"
                f"城配{_num(snapshot.scale.battery_pool_life_years['choco35_city'], 2)}年，"
                f"乘用池推迟出窗仅部分抵销；"
                f"车端各寿命档（{_num(min(r.battery_life_years for r in snapshot.scale.rows), 1)}–"
                f"{_num(max(r.battery_life_years for r in snapshot.scale.rows), 1)}年）逐批次到期"
            ),
        ),
        (
            "等效全周期资本底座",
            "4,015.0",
            _num(capex.lifecycle_capital_base_yi, 1),
            _num(capex.lifecycle_capital_base_yi - 4015.0, 1),
            (
                "EAC法沿用（初装×(1＋净重置比例)）：旧版倍数按寿命档取整展示（1.44×）；"
                "v4.3逐批次按价格路径与WACC推EAC，倍数上升主因寿命重推（重卡站电池四池口径"
                f"倒短{_num(snapshot.scale.battery_pool_life_years['qiji75_short'], 2)}/"
                f"干线{_num(snapshot.scale.battery_pool_life_years['qiji75_trunk'], 2)}年）致净重置更密"
            ),
        ),
        (
            "EAC全周期资本倍数",
            "1.44×",
            f"{capex.lifecycle_capital_base_yi / capex.total_initial_capex_yi:.2f}×",
            f"{capex.lifecycle_capital_base_yi / capex.total_initial_capex_yi - 1.44:+.2f}×",
            (
                "EAC＝全周期资本底座÷初装＝1＋净重置比例；关键中间参数——资本底座、年资本要求FCFF"
                "（×CRF）、门槛EBITDA均由它派生（正文2.3节capex推导表）"
            ),
        ),
        (
            "稳态项目债务",
            "2,409.0",
            _num(capex.project_debt_yi, 1),
            _num(capex.project_debt_yi - 2409.0, 1),
            "两版均为全周期资本×60%；差异随资本底座",
        ),
        (
            "CRF门槛EBITDA",
            "583.0",
            _num(swap.required_ebitda_yi, 1),
            _num(swap.required_ebitda_yi - 583.0, 1),
            "全周期资本与按批次折旧税盾同时变化",
        ),
        (
            "正算换电EBITDA",
            "805.0",
            _num(swap.ebitda_yi, 1),
            _num(swap.ebitda_yi - 805.0, 1),
            "按装车电池+站内外部权益电池计租，并采用终局节点1位精度",
        ),
        (
            "CATL换电运营价值",
            "4,829.0",
            _num(swap.catl_attributable_value_yi, 1),
            _num(swap.catl_attributable_value_yi - 4829.0, 1),
            "EBITDA×18－全周期债务后乘40%",
        ),
        (
            "2030E有换电制造价值",
            "11,779.0",
            _num(ledger.with_swap_manufacturing.equity_value_yi, 1),
            _num(ledger.with_swap_manufacturing.equity_value_yi - 11779.0, 1),
            "已删除未建模动力装机，回到电动车制造口径",
        ),
        (
            "可归因换电价值",
            "6,792.0",
            _num(ledger.total_swap_increment_value_yi, 1),
            _num(ledger.total_swap_increment_value_yi - 6792.0, 1),
            (
                f"较v3.2增加：运营直接4,829→{_num(ledger.direct_swap_increment_value_yi, 1)}"
                "（+223.9，随EBITDA 805→853.4）；制造增量1,963→"
                f"{_num(ledger.total_swap_increment_value_yi - ledger.direct_swap_increment_value_yi, 1)}"
                f"（+1,010.5）——v3.2制造增量为纯护价（有/无换电同出货量、只差利润率）；"
                "v4.3首次将换电锁定订单（换电段＋更换循环×外部权益）计入主值"
                f"{_num(ledger.manufacturing_swap_locked_volume_effect_value_yi, 1)}亿，"
                f"护价{_num(ledger.manufacturing_swap_margin_effect_value_yi, 1)}亿与旧版相当"
            ),
        ),
        (
            "2030E有换电动力电池价值",
            "16,608.0",
            _num(ledger.power_value_2030_with_swap_yi, 1),
            _num(ledger.power_value_2030_with_swap_yi - 16608.0, 1),
            "制造价值＋CATL换电运营价值",
        ),
        (
            "CATL建设期累计资本调用",
            "454.4",
            _num(capex.catl_total_equity_call_yi, 1),
            _num(capex.catl_total_equity_call_yi - 454.4, 1),
            "实际初装与首轮更新×40%权益资本×40%CATL权益",
        ),
        (
            "CATL单年资本调用峰值",
            "99.9",
            _num(capex.catl_peak_equity_call_yi, 1),
            _num(capex.catl_peak_equity_call_yi - 99.9, 1),
            f"峰值时点由旧版2030年前移至{capex.peak_year}年，因站网按规划前置；峰值规模仍约100亿",
        ),
    ]

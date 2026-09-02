from __future__ import annotations

from schemas import (
    CapexResult,
    ConsolidatedLedger,
    DecisionMemo,
    FundingRow,
    LightAssetScenario,
    ScaleResult,
    SwapBusinessResult,
)


def _status(ok: bool, conditional: bool = False) -> str:
    if ok:
        return "支持"
    return "有条件支持" if conditional else "不支持"


def _select_light_asset(
    light: list[LightAssetScenario],
    funding_gap_yi: float,
) -> LightAssetScenario:
    current = max(light, key=lambda row: row.terminal_ownership)
    if funding_gap_yi <= 0:
        return current
    candidates = sorted(
        (
            row for row in light
            if row.data_control_ok and row.sale_proceeds_net_yi >= funding_gap_yi
        ),
        key=lambda row: row.terminal_ownership,
        reverse=True,
    )
    return candidates[0] if candidates else min(light, key=lambda row: row.terminal_ownership)


def build_decision_memos(
    config: dict,
    scale: ScaleResult,
    capex: CapexResult,
    swap: SwapBusinessResult,
    ledger: ConsolidatedLedger,
    light: list[LightAssetScenario],
    funding: list[FundingRow],
    strategic_exposure_yi: float,
) -> list[DecisionMemo]:
    threshold = config["decision_thresholds"]
    peak_funding = max(funding, key=lambda row: row.swap_cash_to_cfo)
    value_multiple = (
        ledger.total_swap_increment_value_yi
        / capex.catl_lifecycle_equity_commitment_yi
    )
    min_headroom = min(row.funds_reserved_for_other_strategy_yi for row in funding)
    funding_gap = max(0.0, -min_headroom)
    selected = _select_light_asset(light, funding_gap)
    light_by_ownership = {row.terminal_ownership: row for row in light}
    mineral_amount = next(
        item["headline_amount_yi"]
        for item in config["capital_commitments"]
        if "矿产资源" in item["label"]
    )

    memos = [
        DecisionMemo(
            owner="规模与网络",
            status=_status(scale.route_identity_error < 1e-12),
            conclusion="共同车辆底座闭合；需求反推终局站数，建设节奏按2026里程碑、2028完成网络处理。",
            evidence={
                "重卡站": scale.target_station_demand["heavy"],
                "巧克力站": scale.target_station_demand["choco"],
                "2028后新增站": sum(
                    row.new_heavy_stations + row.new_choco_stations
                    for row in capex.annual if row.year > 2028
                ),
            },
            key_risk="站网先行与车辆后放量造成早期利用率爬坡风险。",
        ),
        DecisionMemo(
            owner="资本开支",
            status=_status(
                peak_funding.swap_cash_to_cfo <= threshold["max_peak_swap_cash_to_cfo"],
                conditional=True,
            ),
            conclusion="建设期累计与单年峰值均从年度站体、车辆电池、站内电池和首轮更新逐项推导。",
            evidence={
                "CATL累计资本调用": capex.catl_total_equity_call_yi,
                "CATL单年峰值": capex.catl_peak_equity_call_yi,
                "峰值换电资本/当年原始CFO": peak_funding.swap_cash_to_cfo,
            },
            key_risk="项目融资比例和车辆放量速度会改变CATL实际现金调用时点。",
        ),
        DecisionMemo(
            owner="换电经营",
            status=_status(
                swap.forward_to_required_ebitda
                >= threshold["min_forward_to_required_ebitda"],
                conditional=True,
            ),
            conclusion=(
                f"正向经营链覆盖{config['finance']['capital_recovery_factor']:.0%} CRF资本门槛；"
                f"{config['finance']['wacc']:.1%}只用于折扣链中历次净更新的现值折算。"
            ),
            evidence={
                "正向EBITDA": swap.ebitda_yi,
                "门槛EBITDA": swap.required_ebitda_yi,
                "覆盖倍数": swap.forward_to_required_ebitda,
            },
            key_risk="电池租金、服务费、换电频次和站均利用率是主要敏感项。",
        ),
        DecisionMemo(
            owner="动力电池总账",
            status=_status(
                value_multiple >= threshold["min_swap_value_creation_multiple"],
                conditional=True,
            ),
            conclusion="制造线与运营线已经合并；制造只覆盖已建模电动车，换电护价与完整情景差额分开。",
            evidence={
                "2030动力电池价值": ledger.power_value_2030_with_swap_yi,
                "可归因换电价值": ledger.total_swap_increment_value_yi,
                "占当前集团市值": ledger.attributable_swap_value_to_current_group_market_cap,
                "占2026道路口径制造锚": ledger.attributable_swap_value_to_2026_modeled_power_value,
                "换电价值/CATL全周期权益承诺": value_multiple,
            },
            key_risk="市占率与制造净利率差是情景变量，不能把全部动力业务成长归因给换电。",
        ),
        DecisionMemo(
            owner="成熟期资本循环",
            status="支持设置决策前沿",
            conclusion=(
                f"当前资金模型无缺口，基准保留{selected.terminal_ownership:.0%}；"
                "成熟后不推荐固定权益档：资金需求大就多卖，需求小或市场承接弱就少卖。"
            ),
            evidence={
                "当前选择权益": selected.terminal_ownership,
                "保留30%净回款": light_by_ownership[0.30].sale_proceeds_net_yi,
                "保留20%净回款": light_by_ownership[0.20].sale_proceeds_net_yi,
                "保留10%净回款": light_by_ownership[0.10].sale_proceeds_net_yi,
            },
            key_risk="控制权、数据权、标准权和技术验证场景必须由交易协议保障。",
        ),
        DecisionMemo(
            owner="集团资金",
            status=_status(min_headroom >= 0, conditional=True),
            conclusion="以2026H1现金类资产为起点，扣除分红储备、回购上限、三项已识别并购现金（中恒＋世纪互联＋启源）和换电资本后检验余量。",
            evidence={
                "最低流动性余量": min_headroom,
                "未决战略资金敞口情景": strategic_exposure_yi,
                "2026H1现金类资产": config["group_funding"]["initial_cash_and_trading_assets_yi"],
                "2026三项并购合并现金": next(
                    row.known_direct_mna_cash_yi
                    for row in funding
                    if row.year == 2026
                ),
            },
            key_risk=(
                f"矿产{mineral_amount:.0f}亿元为注册资本上限，不能机械计入年度现金支出；"
                "世纪互联v4.2起按审慎口径与中恒、启源一并计入2026年现金。"
            ),
        ),
    ]
    required = [memo.status != "不支持" for memo in memos]
    final_status = "支持重注" if all(required) else "暂不支持重注"
    memos.append(DecisionMemo(
        owner="最终拍板",
        status=final_status,
        conclusion=(
            f"按中性假设，建设期维持{config['finance']['construction_ownership']:.0%}并完成网络与电池银行；"
            "成熟后按实际资金缺口和市场承接能力决定出售10/20/30个百分点，不指定固定最优档。"
            "换电的业务属性有二：既以约"
            f"{swap.catl_cash_yield_on_initial_equity:.0%}的稳态初装现金收益率稳住动力电池基本盘"
            "（远高于400亿元回购按20×PE约5%的隐含回报率），又以成熟后出表回款构成面向类固收市场的"
            "金融类权益投资生意——蔚能REITs已经跑通这一退出路径，CATL收购启源后可加速复制。"
            if all(required) else
            "至少一个资金或经营硬门槛未通过，应先调整规模、价格或资本结构。"
        ),
        evidence={
            "2026E动力电池市值基准": ledger.baseline.power_market_value_2026e_yi,
            "2026E同口径制造价值": ledger.baseline.modeled_power_market_value_2026e_yi,
            "2030E动力电池价值": ledger.power_value_2030_with_swap_yi,
            "可归因换电价值": ledger.total_swap_increment_value_yi,
            "相当于当前宁德时代": ledger.attributable_swap_value_to_current_group_market_cap,
            "稳态初装现金收益率": swap.catl_cash_yield_on_initial_equity,
            "最保守出表30%净回款": light_by_ownership[0.30].sale_proceeds_net_yi,
        },
        key_risk="结论依赖中性参数，需由后续Dashboard做敏感性复核；报告本身保留完整推导链。",
    ))
    return memos

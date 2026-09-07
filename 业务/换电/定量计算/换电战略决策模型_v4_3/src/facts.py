"""事实包：叙述层唯一可以引用的数字来源。

为什么需要它
------------
v4.3 已经有"快照是唯一事实源"的纪律，但叙述文档仍然允许手写数字，
于是同一个「可归因换电增量价值」在三份文档里出现了三个值
（快照 5,698.3 / MANIFEST 6,724.5 / 叙述报告 8,026.4）。
backscan.py 是事后字符串抽检，只在想起来时跑，必然漏。

本模块把关系倒过来：**叙述层不许出现字面数字，只能写 {{key}} 占位符**，
装配时由本文件生成的 facts.json 注入。检查因此从"比对数字"退化成
"文件里还有没有裸数字"——一个正则就能穷尽，不可能漏。

每条事实自带：
    from   快照取值路径（数字永远不是手打的）
    unit   单位（单位漂移也一并治掉）
    kind   呈现形式：num 数值 / pct 百分比 / x 倍数 / text 文字
    watch  复核阈值：重跑后相对变动超过它，引用它的段落被标"待复核"

运行：python src/facts.py     （通常由 build.py 调用，不必单独跑）
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
SNAPSHOT_PATH = ROOT / "outputs" / "decision_snapshot_v4_3.json"
FACTS_PATH = ROOT / "outputs" / "facts.json"


# ─────────────────────────────────────────── 取值助手
def dig(path: str) -> Callable[[dict], Any]:
    """按 'ledger.total_swap_increment_value_yi' 形式的路径取数。"""

    def _get(snap: dict) -> Any:
        node: Any = snap
        for key in path.split("."):
            node = node[key]
        return node

    _get.__doc__ = path
    return _get


def _stations(prefix: str) -> Callable[[dict], float]:
    def _get(snap: dict) -> float:
        return float(sum(
            n for pool, n in snap["scale"]["target_station_demand"].items()
            if pool.startswith(prefix)
        ))
    return _get


def _veh(*keys: str) -> Callable[[dict], float]:
    def _get(snap: dict) -> float:
        stock = snap["scale"]["operating_stock_by_vehicle_wan"]
        return float(sum(stock[k] for k in keys))
    return _get


def _veh_all(snap: dict) -> float:
    return float(sum(snap["scale"]["operating_stock_by_vehicle_wan"].values()))


def _swap_gwh_total(snap: dict) -> float:
    return float(sum(row["catl_swap_gwh"] for row in snap["scale"]["rows"]))


def _peak_row(snap: dict) -> dict:
    return max(snap["funding"], key=lambda r: r["swap_equity_call_yi"])


def _eac_factor(snap: dict) -> float:
    c = snap["capex"]
    return c["lifecycle_capital_base_yi"] / c["total_initial_capex_yi"]


def _final_verdict(snap: dict) -> str:
    return str(snap["memos"][-1]["status"])


def _private_scen(field: str, scen: str) -> Callable[[dict], float]:
    """私家车三情景：快照本身只存中枢档，三档由 build.py 重跑后塞进 _extra。"""

    def _get(snap: dict) -> float:
        return float(snap["_extra"]["private_scenarios"][scen][field])

    return _get


def _sens(group: str, scenario: str, field: str) -> Callable[[dict], float]:
    """从敏感性表里取一格（口径讨论要引用的对照值都从这里来）。"""

    def _get(snap: dict) -> float:
        for row in snap["sensitivity"]:
            if row["parameter_group"] == group and row["scenario"] == scenario:
                return float(row[field])
        raise KeyError(f"敏感性表里没有 {group} / {scenario}")

    return _get


# ─────────────────────────────────────────── 事实定义
@dataclass(frozen=True)
class Fact:
    key: str
    label: str
    get: Callable[[dict], Any]
    unit: str = ""
    kind: str = "num"        # num | pct | x | int | text
    decimals: int = 1
    watch: float = 0.03      # 相对变动超过它 → 引用它的段落待复核
    note: str = ""           # 口径说明，写进 facts.json 供人查


@dataclass(frozen=True)
class ExtFact:
    """外部引用事实：不是模型算出来的，是从外部信源引来的。

    为什么要单开一类（2026-09-06）：
      `facts.json` 原本只装模型输出，但**叙述层的裸数字纪律同样管着外部引用事实**——
      可比公司倍数、第三方 TCO 测算、电池价格，它们同样不许在正文里裸写。
      而 `facts.py` 的 `Fact` 要求能从快照里取值，外部事实取不到，所以另立一类。

    两条硬规矩：
      1. `source` 必须是**外部可达的信源**（URL，或 `media/` 下的外部报告原文），
         **不能填本仓库某个老版本文档**——老版本会被归档，指针会断。
      2. `as_of` 必须填**抓取日期**。理由见 DECISIONS「2026-09-05i」：
         引用一个时点数，必须写清它是哪个时点的。
      两条缺一，`build_facts` 直接报错。
    """

    key: str
    label: str
    text: str                # 正文里显示的形式，可以是区间（如 "40–50%"）
    v: float                 # 变更侦测用的代表值；区间取中点
    source: str              # 外部 URL 或 media/ 下的原文路径
    as_of: str               # 抓取日期 YYYY-MM-DD
    bare: str = ""           # 表格里的裸写法，默认同 text
    unit: str = ""
    note: str = ""


# ── 外部引用事实（`ext.*`）───────────────────────────────
# 排序按主题，不按字母。每条必须带 source ＋ as_of。
_MV = "https://multiples.vc/public-comps"
_JPM = "业务/换电/media/JPM_重卡电动化_英中对照.md"

E: list[ExtFact] = [
    # ── 估值倍数：三族定位的外部锚（口径均为 LTM）──────────
    ExtFact("ext.mult_infra_low", "重资产基建运营族·区间下沿", "6.7×", 6.7,
            f"{_MV}/brookfield-infrastructure-valuation-multiples", "2026-08-26", unit="×",
            note="Brookfield Infrastructure；族内还包括公用事业 8–14×、储能平台 10–14×"),
    ExtFact("ext.mult_infra_high", "重资产基建运营族·区间上沿", "14×", 14.0,
            f"{_MV}/brookfield-infrastructure-valuation-multiples", "2026-08-26", unit="×",
            note="公用事业与储能平台档的上沿"),
    ExtFact("ext.mult_gp_low", "轻资产资管平台族·区间下沿", "18×", 18.0,
            "https://valueinvesting.io/BX/valuation/ev_ebitda-multiples", "2026-08-26", unit="×",
            note="该族中位数；换电不是真 GP，只能取这一档"),
    ExtFact("ext.mult_gp_high", "轻资产资管平台族·区间上沿", "22×", 22.0,
            "https://valueinvesting.io/BX/valuation/ev_ebitda-multiples", "2026-08-26", unit="×",
            note="Blackstone 21.8× 附近"),
    ExtFact("ext.mult_tsla", "车＋能源网络复合族参照", "89.7×", 89.7,
            f"{_MV}/tesla-valuation-multiples", "2026-08-26", unit="×",
            note="只作叙事参照，不作倍数锚——叙事半径不同，见 topics/赔率与跟踪"),
    ExtFact("ext.mult_catl_self", "CATL 自身 EV/EBITDA", "13.0×", 13.0,
            f"{_MV}/catl-valuation-multiples", "2026-08-26", unit="×",
            note="制造业估值口径下的当前读数，是共识锚的旁证"),
    ExtFact("ext.mult_byd", "比亚迪 EV/EBITDA", "6.5×", 6.5,
            f"{_MV}/catl-valuation-multiples", "2026-08-26", unit="×"),

    # ── 重卡 TCO：整套引用 JPM，不各取一项 ──────────────────
    ExtFact("ext.batt_share_of_truck", "电池包占整车成本比例", "40–50%", 0.45,
            _JPM, "2026-08", note="JPM §8.3；承重方论证的量级依据"),
    ExtFact("ext.pack_400kwh_price", "大电量电池包价格", "30–40 万元", 35.0,
            _JPM, "2026-08", unit="万元", note="JPM §8.3，400kWh 档"),
    ExtFact("ext.revenue_uplift_per_truck", "单车年增收（换电 vs 充电）", "约 4 万元/年", 4.0,
            _JPM, "2026-08", unit="万元/年",
            note="JPM §8.3；原文标注可直接用作换电服务付费意愿的上限"),
    ExtFact("ext.baas_capex_cut", "BaaS 购车成本降幅", "40–50%", 0.45,
            _JPM, "2026-08", note="JPM §8.3；痛点强度的资金占用分量"),
    ExtFact("ext.payload_loss_ev", "电动重卡年载重损失", "7 万元/年", 7.0,
            _JPM, "2026-08", unit="万元/年",
            note="JPM Table 3；电动重卡最大的隐性成本项，漏掉它的 TCO 结论都不可信"),
    ExtFact("ext.tco_ev_vs_lng_3y", "三年持有期 TCO：电动 vs LNG", "−4%", -0.04,
            _JPM, "2026-08", note="JPM Table 3"),
    ExtFact("ext.tco_ev_vs_lng_5y", "五年持有期 TCO：电动 vs LNG", "−11%", -0.11,
            _JPM, "2026-08", note="JPM Table 3；真正的边际对手是 LNG，不是柴油"),
    ExtFact("ext.tco_ev_vs_diesel_5y", "五年持有期 TCO：电动 vs 柴油", "−25%", -0.25,
            _JPM, "2026-08", note="JPM Table 3；安全但没信息量的那条对比"),
    ExtFact("ext.lng_price_rise", "LNG 价格年度涨幅", "+48%", 0.48,
            _JPM, "2026-08",
            note="JPM 正文；意味着换电当前的痛点强度里有一部分是 LNG 涨价送的，不是自己挣的"),
]


F: list[Fact] = [
    # ── 集团基本盘 ────────────────────────────────
    Fact("base.rev_2025a", "集团营收（上一完整年度实绩）",
         dig("_extra.config.financial_2025a.group_revenue_yi"), "亿元", decimals=0),
    Fact("base.np_2025a", "集团净利（上一完整年度实绩）",
         dig("_extra.config.financial_2025a.group_net_profit_yi"), "亿元", decimals=0),
    Fact("base.cash_2025a", "货币资金＋交易性金融资产",
         dig("_extra.config.financial_2025a.cash_and_trading_assets_yi"), "亿元", decimals=0),
    Fact("base.group_np", "集团净利（模型期初）", dig("ledger.baseline.group_net_profit_2026e_yi"), "亿元"),
    Fact("base.group_mktcap", "集团市值基准（A+H）", dig("ledger.baseline.group_market_value_2026e_yi"), "亿元", decimals=0),
    Fact("base.group_pe", "集团隐含PE", dig("ledger.baseline.implied_group_pe"), "倍", kind="x", decimals=1),
    Fact("base.power_value_2026", "动力电池线现值（分摊口径）", dig("ledger.baseline.power_market_value_2026e_yi"), "亿元"),
    Fact("base.wacc", "折现率", dig("meta.wacc"), "", kind="pct", decimals=1,
         note="蔚来换电ABS融资基准，直接采用，不作CAPM推导"),
    Fact("base.target_year", "终局年", dig("meta.target_year"), "", kind="int", watch=1.0),
    Fact("base.horizon_years", "模型分析期", dig("_extra.config.finance.model_horizon_years"), "年", kind="int", watch=1.0),
    Fact("base.debt_ratio", "项目公司债务比例", dig("_extra.config.finance.debt_ratio"), "", kind="pct", decimals=0),
    Fact("base.equity_share", "CATL建站持股比例", dig("_extra.config.finance.construction_ownership"), "", kind="pct", decimals=0),
    Fact("base.ev_ebitda", "运营侧EV/EBITDA基准倍数", dig("_extra.config.finance.swap_ev_ebitda"), "×", kind="x", decimals=0),
    # 2026-09-06：换电资产里 CATL 真正自己出的钱占多少。
    # 曾一度打算做成 ext.catl_equity_share_blended，但它是**派生量**不是外部事实——
    # =(1−项目公司债务比例)×CATL建站持股比例。做成派生，债务比例一改它自动跟着变。
    Fact("base.catl_blended_share", "CATL 综合自有出资比例",
         lambda s: (1.0 - float(dig("_extra.config.finance.debt_ratio")(s)))
                   * float(dig("_extra.config.finance.construction_ownership")(s)),
         "", kind="pct", decimals=0,
         note="=(1−债务比例)×建站持股比例。三族定位里'不是真 GP'那条判断的量化依据"),
    Fact("base.mfg_pe", "制造侧PE", dig("_extra.config.finance.manufacturing_pe"), "×", kind="x", decimals=0),
    Fact("base.cfo_gate", "换电现金占CFO体检线",
         dig("_extra.config.decision_thresholds.max_peak_swap_cash_to_cfo"), "", kind="pct", decimals=0),

    # ── Q1 做透的规模 ────────────────────────────
    Fact("q1.st_heavy", "骐骥重卡站（终局合计）", _stations("qiji75"), "座", kind="int"),
    Fact("q1.st_heavy_short", "骐骥短途站", dig("scale.target_station_demand.qiji75_short"), "座", kind="int"),
    Fact("q1.st_heavy_trunk", "骐骥干线站", dig("scale.target_station_demand.qiji75_trunk"), "座", kind="int"),
    Fact("q1.st_choco", "巧克力站（终局合计）", _stations("choco"), "座", kind="int"),
    Fact("q1.st_choco_pass", "巧克力乘用站", dig("scale.target_station_demand.choco25_passenger"), "座", kind="int"),
    Fact("q1.st_choco_city", "巧克力城配站", dig("scale.target_station_demand.choco35_city"), "座", kind="int"),
    Fact("q1.veh_total", "CATL换电车辆（终局）", _veh_all, "万辆"),
    Fact("q1.veh_heavy", "换电重卡", _veh("heavy"), "万辆"),
    Fact("q1.veh_city", "换电城配物流车", _veh("city"), "万辆"),
    Fact("q1.veh_taxi", "换电出租车", _veh("taxi"), "万辆"),
    Fact("q1.veh_ridehail", "换电网约车", _veh("ridehail"), "万辆"),
    Fact("q1.veh_robotaxi", "换电Robotaxi", _veh("robotaxi"), "万辆"),
    Fact("q1.veh_private", "换电私家车", _veh("private"), "万辆"),
    Fact("q1.veh_ops", "换电营运车合计", _veh("heavy", "city", "taxi", "ridehail", "robotaxi"), "万辆"),
    Fact("q1.gwh_total", "换电电池总装机", _swap_gwh_total, "GWh",
         note="车端＋站内周转，按各年新增装机汇总"),
    Fact("q1.gwh_vehicle", "换电装机·车端", dig("swap_business.rent_vehicle_gwh"), "GWh"),
    Fact("q1.energy", "年换电交易电量（成熟期）", dig("swap_business.annual_energy_yi_kwh"), "亿kWh"),

    # ── Q2 做透的代价 ────────────────────────────
    Fact("q2.capex_initial", "初装CAPEX合计", dig("capex.total_initial_capex_yi"), "亿元"),
    Fact("q2.lifecycle_base", "全周期资本底座（15年现值）", dig("capex.lifecycle_capital_base_yi"), "亿元"),
    Fact("q2.eac_factor", "全周期／初装倍数", _eac_factor, "倍", kind="x", decimals=2,
         note="电池更新推高的资本倍数，等价年金法的核心中间量"),
    Fact("q2.equity_call", "CATL建设期累计资本调用", dig("capex.catl_total_equity_call_yi"), "亿元"),
    Fact("q2.peak_call", "单年峰值资本调用", dig("capex.catl_peak_equity_call_yi"), "亿元"),
    Fact("q2.peak_year", "峰值年", dig("capex.peak_year"), "", kind="int", watch=1.0),
    Fact("q2.commitment", "CATL全周期权益承诺", dig("capex.catl_lifecycle_equity_commitment_yi"), "亿元"),
    Fact("q2.project_debt", "项目债务", dig("capex.project_debt_yi"), "亿元"),

    # ── Q3 换回的价值 ────────────────────────────
    Fact("q3.revenue", "换电业务年收入（成熟期）", dig("swap_business.revenue_yi"), "亿元"),
    Fact("q3.rev_service", "　服务费收入", dig("swap_business.service_revenue_yi"), "亿元"),
    Fact("q3.rev_rent", "　电池租金收入", dig("swap_business.battery_rent_yi"), "亿元"),
    Fact("q3.rev_arb", "　峰谷套利收入", dig("swap_business.arbitrage_yi"), "亿元"),
    Fact("q3.rev_anc", "　电网辅助服务收入", dig("swap_business.ancillary_yi"), "亿元"),
    Fact("q3.opex", "运营OPEX", dig("swap_business.opex_yi"), "亿元"),
    Fact("q3.ebitda", "EBITDA", dig("swap_business.ebitda_yi"), "亿元"),
    Fact("q3.dep", "年折旧", dig("swap_business.depreciation_yi"), "亿元"),
    Fact("q3.ebit", "EBIT", dig("swap_business.ebit_yi"), "亿元", decimals=2, watch=1.0,
         note="接近零：折旧几乎吃掉全部EBITDA，估值口径讨论的起点"),
    Fact("q3.required_ebitda", "资本回报要求EBITDA", dig("swap_business.required_ebitda_yi"), "亿元"),
    Fact("q3.coverage", "EBITDA覆盖倍数", dig("swap_business.forward_to_required_ebitda"), "倍", kind="x", decimals=2),
    Fact("q3.op_value", "运营侧直接增量（CATL归属）", dig("ledger.direct_swap_increment_value_yi"), "亿元",
         note="EV/EBITDA×倍数－债，再乘40%权益"),
    Fact("q3.mfg_gap_value", "制造侧锁量锁价增量", dig("ledger.full_manufacturing_scenario_gap_value_yi"), "亿元",
         note="有换电制造净利 − 纯制造净利，再×制造PE；已综合锁单、虹吸与利润率保护"),
    Fact("q3.increment", "可归因换电增量价值", dig("ledger.total_swap_increment_value_yi"), "亿元"),
    Fact("q3.increment_pct", "增量价值／集团市值", dig("ledger.attributable_swap_value_to_current_group_market_cap"), "", kind="pct"),
    Fact("q3.power_value_with", "2030E动力电池线价值（有换电）", dig("ledger.power_value_2030_with_swap_yi"), "亿元"),
    Fact("q3.power_value_no", "2030E动力电池线价值（无换电对照）", dig("ledger.power_value_2030_no_swap_yi"), "亿元"),
    Fact("q3.mfg_np_with", "2030E制造净利（有换电）", dig("ledger.with_swap_manufacturing.net_profit_yi"), "亿元"),
    Fact("q3.mfg_np_no", "2030E制造净利（无换电）", dig("ledger.no_swap_manufacturing.net_profit_yi"), "亿元"),
    Fact("q3.mfg_margin_no", "无换电制造净利率", dig("ledger.no_swap_manufacturing.net_margin"), "", kind="pct"),
    Fact("q3.mfg_margin_with", "有换电制造净利率", dig("ledger.with_swap_manufacturing.net_margin"), "", kind="pct"),
    Fact("q3.dist_cash", "CATL年可分派现金（成熟期）", dig("swap_business.catl_forward_distributable_cash_yi"), "亿元"),
    Fact("q3.payback", "全周期回收期", dig("swap_business.catl_lifecycle_payback_years"), "年", decimals=1),

    # ── 估值口径对照：算出来的 vs 押注的（第 5 章的骨）──
    Fact("dcf.fcff", "成熟期项目自由现金流 FCFF", dig("swap_business.forward_fcff_yi"), "亿元",
         note="EBITDA×(1−税率)＋折旧×税率；全周期重置已由 CRF 年金化内含"),
    Fact("dcf.ev_crf", "DCF企业价值·与门槛同源口径", dig("swap_business.dcf_ev_at_crf_yi"), "亿元",
         note="FCFF ÷ CRF。CRF 即设门槛 EBITDA 用的期望收益率年金因子，故与覆盖倍数完全同源"),
    Fact("dcf.ev_wacc", "DCF企业价值·成本线口径（上界）", dig("swap_business.dcf_ev_at_wacc_yi"), "亿元",
         note="FCFF × 年金因子(WACC 7.5%, 15年)。WACC 是成本下限，故本口径给出上界"),
    Fact("dcf.mult_crf", "现金流支持的倍数·与门槛同源", dig("swap_business.dcf_implied_multiple_at_crf"), "×",
         kind="x", decimals=2,
         note="几乎正好落在 v3.2 §4.1 引用的 Brookfield 6.7×（重资产基建运营族底部）"),
    Fact("dcf.mult_wacc", "现金流支持的倍数·成本线上界", dig("swap_business.dcf_implied_multiple_at_wacc"), "×",
         kind="x", decimals=2),
    Fact("dcf.premium", "拍的倍数 ÷ 现金流支持的倍数", dig("swap_business.dcf_multiple_premium"), "倍",
         kind="x", decimals=2, note="这个倍数就是战略溢价的大小，是判断不是计算"),
    Fact("dcf.npv", "项目NPV·与门槛同源口径", dig("swap_business.dcf_npv_at_crf_yi"), "亿元",
         note="DCF企业价值 − 全周期资本底座。为正即已跑赢自设门槛"),
    Fact("dcf.catl_value", "CATL归属价值·现金流口径", dig("swap_business.dcf_catl_value_at_crf_yi"), "亿元"),
    Fact("dcf.bet", "押注的那部分", dig("swap_business.dcf_catl_value_gap_yi"), "亿元",
         note="倍数法归属 − 现金流口径归属；报告第 5 章必须正面论证的就是这一块"),

    # ── Q4 资金从容度 ────────────────────────────
    Fact("q4.peak_to_cfo", "峰值年换电现金／CFO", lambda s: _peak_row(s)["swap_cash_to_cfo"], "", kind="pct"),
    Fact("q4.closing_liquidity", "峰值年末可投资金结余",
         lambda s: _peak_row(s)["closing_liquid_resources_before_uncommitted_strategy_yi"], "亿元"),
    Fact("q4.min_reserve", "集团最低流动性储备线",
         lambda s: _peak_row(s)["minimum_liquidity_reserve_yi"], "亿元", decimals=0),
    Fact("q4.exposure", "待决战略敞口合计", dig("strategic_exposure_yi"), "亿元"),
    Fact("q4.verdict", "决策备忘录末端判断", _final_verdict, "", kind="text", watch=1.0),

    # ── 情景（私家车三档，需求侧最大不确定项）──────
    Fact("sens.private_low", "私家车换电车辆·保守", _private_scen("私家车换电车辆(万)", "保守"), "万辆"),
    Fact("sens.private_mid", "私家车换电车辆·中枢", _private_scen("私家车换电车辆(万)", "中枢"), "万辆"),
    Fact("sens.private_high", "私家车换电车辆·激进", _private_scen("私家车换电车辆(万)", "激进"), "万辆"),
    Fact("sens.increment_low", "可归因增量·保守", _private_scen("可归因换电增量(亿)", "保守"), "亿元"),
    Fact("sens.increment_high", "可归因增量·激进", _private_scen("可归因换电增量(亿)", "激进"), "亿元"),
    Fact("sens.coverage_low", "EBITDA覆盖倍数·保守", _private_scen("EBITDA覆盖倍数", "保守"), "倍", kind="x", decimals=2),
    Fact("sens.coverage_high", "EBITDA覆盖倍数·激进", _private_scen("EBITDA覆盖倍数", "激进"), "倍", kind="x", decimals=2),

    # ── 口径对照：估值倍数怎么撬动结论（第 5 章要用）──
    Fact("sens.ev14", "增量价值 @运营14×", _sens("运营EV/EBITDA", "14×", "attributable_swap_value_yi"), "亿元"),
    Fact("sens.ev18", "增量价值 @运营18×（基准）", _sens("运营EV/EBITDA", "18×", "attributable_swap_value_yi"), "亿元"),
    Fact("sens.ev22", "增量价值 @运营22×", _sens("运营EV/EBITDA", "22×", "attributable_swap_value_yi"), "亿元"),
    Fact("sens.ev25", "增量价值 @运营25×", _sens("运营EV/EBITDA", "25×", "attributable_swap_value_yi"), "亿元"),
    Fact("sens.fee_low", "增量价值 @服务费租金×0.8",
         _sens("服务费+租金", "基准×0.8", "attributable_swap_value_yi"), "亿元"),
    Fact("sens.fee_low_cov", "EBITDA覆盖倍数 @服务费租金×0.8",
         _sens("服务费+租金", "基准×0.8", "ebitda_coverage"), "倍", kind="x", decimals=2),
    Fact("sens.batt_high", "增量价值 @电池价格×1.1",
         _sens("电池价格", "基准×1.1", "attributable_swap_value_yi"), "亿元"),
    Fact("sens.margin_zero", "增量价值 @制造净利率差取零",
         _sens("制造净利率差", "0.0%", "attributable_swap_value_yi"), "亿元"),
    # 倍数档位的标签本身也来自敏感性表，避免表头数字变成手写
    Fact("sens.ev14_x", "档位标签", lambda s: "14×", kind="text", watch=1.0),
    Fact("sens.ev18_x", "档位标签", lambda s: "18×", kind="text", watch=1.0),
    Fact("sens.ev22_x", "档位标签", lambda s: "22×", kind="text", watch=1.0),
    Fact("sens.ev25_x", "档位标签", lambda s: "25×", kind="text", watch=1.0),
]

FACT_BY_KEY = {f.key: f for f in F}


# ─────────────────────────────────────────── 呈现
def render(fact: Fact, value: Any) -> str:
    """事实的规范写法。{{key}} 注入的就是这个字符串。"""
    if fact.kind == "text":
        return str(value)
    if fact.kind == "int":
        return f"{int(round(float(value))):,}{fact.unit}"
    if fact.kind == "pct":
        return f"{float(value) * 100:,.{fact.decimals}f}%"
    if fact.kind == "x":
        return f"{float(value):,.{fact.decimals}f}{fact.unit}"
    return f"{float(value):,.{fact.decimals}f}{fact.unit}"


def render_bare(fact: Fact, value: Any) -> str:
    """{{key:n}} 注入的写法：只有数字，不带单位（用于表格列已标单位的场合）。"""
    if fact.kind == "text":
        return str(value)
    if fact.kind == "int":
        return f"{int(round(float(value))):,}"
    if fact.kind == "pct":
        return f"{float(value) * 100:,.{fact.decimals}f}"
    return f"{float(value):,.{fact.decimals}f}"


# ─────────────────────────────────────────── 生成
def build_facts(snapshot: dict | None = None) -> dict:
    snap = snapshot if snapshot is not None else json.loads(SNAPSHOT_PATH.read_text("utf-8"))
    out: dict[str, dict] = {}
    missing: list[str] = []
    for fact in F:
        try:
            raw = fact.get(snap)
        except (KeyError, IndexError, TypeError) as exc:
            missing.append(f"{fact.key} ← {exc!r}")
            continue
        value = raw if fact.kind == "text" else float(raw)
        out[fact.key] = {
            "label": fact.label,
            "v": value,
            "text": render(fact, value),
            "bare": render_bare(fact, value),
            "unit": fact.unit,
            "kind": fact.kind,
            "watch": fact.watch,
            "from": getattr(fact.get, "__doc__", "") or "派生",
            "note": fact.note,
        }
    if missing:
        raise KeyError("以下事实在快照里取不到（快照结构变了？）：\n  " + "\n  ".join(missing))

    # ── 合并外部引用事实 ────────────────────────────────
    bad: list[str] = []
    for e in E:
        if e.key in out:
            bad.append(f"{e.key}：与模型事实重名")
            continue
        if not e.source:
            bad.append(f"{e.key}：缺 source（外部事实必须带可达信源）")
        if not e.as_of:
            bad.append(f"{e.key}：缺 as_of（引用时点数必须写清是哪个时点的）")
        out[e.key] = {
            "label": e.label,
            "v": e.v,
            "text": e.text,
            "bare": e.bare or e.text,
            "unit": e.unit,
            "kind": "ext",
            # 外部事实不随重跑变化，watch 设为 1.0 使其永不触发"待复核"；
            # 它需要的是**定期回源核对**，那是另一套机制（见 交接.md 纪律登记表）
            "watch": 1.0,
            "from": e.source,
            "as_of": e.as_of,
            "note": e.note,
        }
    if bad:
        raise ValueError("外部事实（ext.*）不合规：\n  " + "\n  ".join(bad))

    return out


def main() -> None:
    facts = build_facts()
    FACTS_PATH.write_text(
        json.dumps(facts, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    n_ext = sum(1 for v in facts.values() if v.get("kind") == "ext")
    print(f"事实包: {FACTS_PATH}（{len(facts)} 条，其中外部引用 {n_ext} 条）")


if __name__ == "__main__":
    main()

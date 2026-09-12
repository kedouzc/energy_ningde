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
from collections import Counter
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


def _veh(*keys: str) -> Callable[[dict], float]:
    def _get(snap: dict) -> float:
        stock = snap["scale"]["operating_stock_by_vehicle_wan"]
        return float(sum(stock[k] for k in keys))
    return _get


def _veh_all(snap: dict) -> float:
    return float(sum(snap["scale"]["operating_stock_by_vehicle_wan"].values()))


# （2026-09-12 删除 `_stations`／`_swap_gwh_total`／`_peak_row`／`_eac_factor`／
#   `_final_verdict`／`_scen`／`_sens` 七个取值助手：它们的调用方——65 条"定义了没人引用"
#  的孤儿事实——已删，其中 `_swap_gwh_total` 的算式已由 business.py 算成快照字段。
#  留着就是"一个算式两个出处"：改了那边，这边的死代码还挂着旧口径。）

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
    mirror: str = ""         # 对应的 lab.METRICS key：两条取数路径必须给出同一个数，
                             # 由 onepager.check_mirrors() 每次实跑断言（不一致即中断）


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


@dataclass(frozen=True)
class RefFact:
    """信源引用事实：URL / 名称 / 抓取日期 / 分级的**唯一家**在
    `audit/信源审计台账.md` 的「信源索引（机读）」表里，本类只负责把它读出来。

    为什么要单开一类（2026-09-09）：信源与链接**也是一种数据**——此前同一条链接在
    base.toml 注释、台账正文、叙述层正文里各贴一遍，改一处忘三处。现在规矩是：
      · URL / 名称 / 抓取日期 / 分级 → 只写台账索引表；
      · 数值 → 只写 `configs/base.toml`（注释里写「信源：src.xxx」，不重复贴 URL）；
      · 下游（一页纸 md、叙述层、HTML）只能写 `{{src.xxx}}` 引用。

    text 渲染为 `[名称](URL)（抓取于 YYYY-MM-DD）`，与 Fact/ExtFact 走同一个
    `{{key}}` 占位符体系，故不需要新语法。
    """

    key: str        # 必须以 src. 开头，与 Fact / ExtFact 的命名空间隔离
    label: str      # 名称
    url: str        # 外部可点击信源
    as_of: str      # 抓取日期 YYYY-MM-DD
    grade: str = ""  # 一手 / 二手 / 假设
    used_by: str = ""  # 用于哪个 base.toml 参数

    @property
    def text(self) -> str:
        grade = f"·{self.grade}" if self.grade else ""
        return f"[{self.label}]({self.url})（抓取于 {self.as_of}{grade}）"


LEDGER_PATH = ROOT / "audit" / "信源审计台账.md"
REF_SECTION = "## 信源索引（机读）"


def load_ref_facts(path: Path = LEDGER_PATH) -> list[RefFact]:
    """解析台账的「信源索引（机读）」表。

    找不到该节或表头列名不符 → 直接抛错中断：信源是被引用的数据，
    解析不出来却静默跳过，等于让下游渲染出空链接（那比报错更糟）。
    """
    if not path.exists():
        raise FileNotFoundError(f"信源台账不存在：{path}")
    text = path.read_text("utf-8")
    if REF_SECTION not in text:
        raise ValueError(
            f"{path.name} 里没有「{REF_SECTION}」节——信源索引是 URL 的唯一家，"
            f"缺了它下游只能手写链接（会重新变成到处有数据）"
        )
    body = text.split(REF_SECTION, 1)[1]
    rows = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("|")]
    header_idx = next((i for i, ln in enumerate(rows) if "key" in ln and "URL" in ln), None)
    if header_idx is None:
        raise ValueError(f"{path.name} 的「{REF_SECTION}」节里找不到表头行（需含 key 与 URL 两列）")
    cols = [c.strip() for c in rows[header_idx].strip("|").split("|")]
    try:
        i_key, i_name, i_url, i_asof = (cols.index(c) for c in ("key", "名称", "URL", "抓取日期"))
        i_grade = cols.index("分级")
        i_used = cols.index("用于")
    except ValueError as exc:
        raise ValueError(f"{path.name}「信源索引」表头列不全（缺 {exc}）") from exc

    out: list[RefFact] = []
    for ln in rows[header_idx + 1:]:
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < len(cols) or set(cells[0]) <= set("-: "):
            continue                                  # 分隔行
        if not cells[i_key].startswith("src."):
            continue                                  # 表尾的说明行等
        out.append(RefFact(key=cells[i_key], label=cells[i_name], url=cells[i_url],
                           as_of=cells[i_asof], grade=cells[i_grade], used_by=cells[i_used]))
    if not out:
        raise ValueError(f"{path.name}「{REF_SECTION}」表里没有解析到任何 src.* 条目")
    return out


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
    Fact("base.group_mktcap", "集团市值基准（A+H）", dig("ledger.baseline.group_market_value_2026e_yi"), "亿元", decimals=0,
         mirror="val.group_market_cap"),
    # 占比类一律以百分数存储（v=7.5 表示 7.5%），与输出字典的 `%` 条目同值——
    # 原先存比值 0.075、靠 kind="pct" 渲染时才 ×100，与字典差 100 倍却没人发现。
    Fact("base.wacc", "折现率", lambda s: float(dig("meta.wacc")(s)) * 100.0, "%", kind="num", decimals=1,
         mirror="base.wacc_pct", note="蔚来换电ABS融资基准，直接采用，不作CAPM推导"),
    Fact("base.target_year", "终局年", dig("meta.target_year"), "", kind="int", watch=1.0),
    Fact("base.horizon_years", "模型分析期", dig("_extra.config.finance.model_horizon_years"), "年", kind="int", watch=1.0,
         mirror="base.horizon_years"),
    Fact("base.debt_ratio", "项目公司债务比例",
         lambda s: float(dig("_extra.config.finance.debt_ratio")(s)) * 100.0,
         "%", kind="num", decimals=0, mirror="base.debt_ratio_pct"),
    # 占比一律**以百分数存储**（v=40 表示 40%），与输出字典的 `%` 条目同值——
    # 原先这里存比值 0.4、靠 kind="pct" 渲染时才 ×100，于是与字典的 `base.ownership_pct`
    # 差整整 100 倍，两条路径互相校不上（2026-09-12 由新增的同名/镜像断言查出来）。
    Fact("base.equity_share", "CATL建站持股比例",
         lambda s: float(dig("_extra.config.finance.construction_ownership")(s)) * 100.0,
         "%", kind="num", decimals=0, mirror="base.ownership_pct"),
    Fact("base.ev_ebitda", "运营侧EV/EBITDA基准倍数", dig("_extra.config.finance.swap_ev_ebitda"), "×", kind="x", decimals=0,
         mirror="base.ev_ebitda_multiple"),
    # 2026-09-06：换电资产里 CATL 真正自己出的钱占多少。
    # 曾一度打算做成 ext.catl_equity_share_blended，但它是**派生量**不是外部事实——
    # =(1−项目公司债务比例)×CATL建站持股比例。做成派生，债务比例一改它自动跟着变。
    Fact("base.catl_blended_share", "CATL 综合自有出资比例",
         lambda s: (1.0 - float(dig("_extra.config.finance.debt_ratio")(s)))
                   * float(dig("_extra.config.finance.construction_ownership")(s)),
         "", kind="pct", decimals=0,
         note="=(1−债务比例)×建站持股比例。三族定位里'不是真 GP'那条判断的量化依据"),
    Fact("base.mfg_pe", "制造侧PE", dig("_extra.config.finance.manufacturing_pe"), "×", kind="x", decimals=0,
         mirror="base.mfg_pe"),
    Fact("base.cfo_gate", "换电现金占CFO体检线",
         lambda s: float(dig("_extra.config.decision_thresholds.max_peak_swap_cash_to_cfo")(s)) * 100.0,
         "%", kind="num", decimals=0, mirror="base.cfo_gate_pct"),

    Fact("q1.veh_total", "CATL换电车辆（终局）", _veh_all, "万辆", mirror="ops.veh_total"),
    Fact("q1.veh_ops", "换电营运车合计", _veh("heavy", "city", "taxi", "ridehail", "robotaxi"), "万辆",
         mirror="ops.veh_ops"),
    # 口径更正（2026-09-12）：本条**不含**站内周转——它是各年新增装机逐年累加（流量口径），
    # 574.0 GWh；含站内的存量口径是「换电装机保有量合计」608.8 GWh（字典 ops.battery_total）。
    # 原 note 写"车端＋站内周转"是把两个口径混说了，而它与"车端"只差 0.03%，
    # 混着读几乎看不出来——正是最该咬文嚼字的地方。算式已由 business.py 算成快照字段，
    # 不再由本文件另起一份（一个数字只准有一个算式）。
    Fact("q1.gwh_total", "换电电池总装机（各年新增累计）",
         dig("swap_business.swap_gwh_cumulative_flow"), "GWh", mirror="ops.gwh_cum_flow",
         note="各年新增装机逐年累加（流量口径，574.0）；不含站内周转，"
              "也不等于存量口径的 '换电装机保有量合计'（608.8）"),
    Fact("q1.gwh_vehicle", "换电装机·车端", dig("swap_business.rent_vehicle_gwh"), "GWh",
         mirror="ops.battery_vehicle"),
    Fact("q1.gwh_station", "换电装机·站内周转",
         lambda s: sum(p["station_battery_gwh"] for p in s["swap_business"]["pool_operations"].values()),
         "GWh", mirror="ops.battery_station"),
    Fact("q1.energy", "年换电交易电量（成熟期）", dig("swap_business.annual_energy_yi_kwh"), "亿kWh",
         mirror="ops.annual_energy"),

    # ── Q2 做透的代价 ────────────────────────────
    Fact("q2.capex_initial", "初装CAPEX合计", dig("capex.total_initial_capex_yi"), "亿元",
         mirror="capex.initial_capex"),
    Fact("q2.lifecycle_base", "全周期资本底座（15年现值）", dig("capex.lifecycle_capital_base_yi"), "亿元",
         mirror="capex.lifecycle_base"),
    Fact("q2.project_debt", "项目债务", dig("capex.project_debt_yi"), "亿元",
         mirror="capex.project_debt"),

    # ── 估值口径对照：算出来的 vs 押注的（第 5 章的骨）──
    Fact("dcf.fcff", "成熟期项目自由现金流 FCFF", dig("swap_business.forward_fcff_yi"), "亿元",
         mirror="swap.forward_fcff",
         note="EBITDA×(1−税率)＋折旧×税率；全周期重置已由 CRF 年金化内含"),
    Fact("dcf.mult_crf", "现金流支持的倍数·与门槛同源", dig("swap_business.dcf_implied_multiple_at_crf"), "×",
         kind="x", decimals=2, mirror="swap.dcf_implied_multiple",
         note="几乎正好落在 v3.2 §4.1 引用的 Brookfield 6.7×（重资产基建运营族底部）"),
    Fact("dcf.bet", "押注的那部分", dig("swap_business.dcf_catl_value_gap_yi"), "亿元",
         mirror="val.dcf_bet",
         note="倍数法归属 − 现金流口径归属；报告第 5 章必须正面论证的就是这一块"),

    # ── 外部市场锚（一页纸市占率的分母）────────────────────
    # 数值只在 base.toml；**信源（名称/URL/抓取日期/分级）只在 audit/信源审计台账.md 的
    # 「信源索引（机读）」表**，故这里 note 只指 key、不复制链接——链接复制第二份就会开始漂移。
    Fact("ext.storage_gwh_2025", "最新全国新型储能累计装机",
         dig("_extra.config.national_battery_market.storage_install_gwh_2025"), "GWh", kind="int",
         watch=1.0, note="外部一手（国家能源局）；信源见台账 src.nea_storage_2026"),
    Fact("ext.storage_gwh_2030", "2030 全国新型储能装机预测",
         dig("_extra.config.national_battery_market.storage_install_gwh_2030"), "GWh", kind="int",
         watch=1.0, note="国务院文件推算（等效 2.6h 折算属经验假设）；信源见台账 src.gov_storage_2030"),
    Fact("ext.elec_latest", "最新年度全社会用电量",
         dig("_extra.config.national_power_market.society_electricity_yi_kwh_latest"), "亿kWh", kind="int",
         watch=1.0, note="外部一手（国家能源局）；信源见台账 src.nea_elec_2025"),
    Fact("ext.elec_2030", "2030 全社会用电量预测",
         dig("_extra.config.national_power_market.society_electricity_yi_kwh_2030"), "亿kWh", kind="int",
         watch=1.0, note="国网能源院口径（二手转引）；另有中电联 13 万亿口径差约 4%；信源见台账 src.society_elec_2030"),

    # ── 判断阈值（唯一家＝base.toml [decision_thresholds]；下游只引用，不许再写一遍数字）──
    Fact("thr.min_increment_yi", "重注门槛·增量价值下限",
         dig("_extra.config.decision_thresholds.min_swap_increment_yi"), "亿元", kind="int", watch=1.0),
    Fact("thr.min_incr_pct", "战略敞口门槛·增量占集团市值下限",
         dig("_extra.config.decision_thresholds.min_increment_over_mktcap"), "", kind="pct", watch=1.0),
    Fact("thr.target_incr_pct", "值得重注·增量占集团市值目标",
         dig("_extra.config.decision_thresholds.target_increment_over_mktcap"), "", kind="pct", watch=1.0),
    Fact("thr.bet_high", "押注占比·结论靠倍数而非现金流的线",
         dig("_extra.config.decision_thresholds.max_bet_share_high"), "", kind="pct", watch=1.0),
    Fact("thr.min_coverage", "EBITDA 覆盖倍数体检线",
         dig("_extra.config.decision_thresholds.min_forward_to_required_ebitda"), "倍", kind="x",
         decimals=2, watch=1.0),

    # ── 与 lab.METRICS 镜像的结果事实 ────────────────────────
    # 一页纸的数值列走 METRICS（与沙盘读数同一出口），解释列走 facts 占位符；
    # 两条取数路径必须给出同一个数，由本文件的 check_mirrors() **每条管线**实跑断言。
    Fact("op.net_profit", "运营净利润（项目100%口径）",
         dig("swap_business.project_net_profit_yi"), "亿元", mirror="swap.net_profit",
         note="分池计税、亏损池不跨池抵扣，故合计可能为负"),
    Fact("op.ev_multiple", "运营企业价值 EV（倍数法，100%口径）",
         dig("swap_business.enterprise_value_yi"), "亿元", mirror="val.op_ev_multiple",
         note="未扣债、未乘持股比例；归属口径见 运营侧直接增量（CATL归属）"),
    Fact("op.equity_gross", "运营项目权益价值（100%口径）",
         dig("swap_business.project_equity_value_yi"), "亿元", mirror="val.op_equity_gross"),
    Fact("dcf.catl_true", "CATL归属·DCF有限期",
         dig("swap_business.dcf_catl_value_true_yi"), "亿元", mirror="val.catl_dcf_true"),
    Fact("q2.peak_year", "峰值年", dig("capex.peak_year"), "年", kind="year", watch=1.0,
         mirror="capex.peak_year", note="CATL 单年权益出资最大的年份——年份不加千分位"),
]

# **一个 key 只能定义一次**：重复时后者悄悄覆盖前者，前者写的 unit/kind/note 全白写，
# 而且查错的时候不报错——这正是"同一个数两个出处"最容易复发的形态，故加载即中断。
_dupes = [k for k, n in Counter(f.key for f in F).items() if n > 1]
if _dupes:
    _detail = "\n  ".join(
        f"{k}：{[f.label for f in F if f.key == k]}" for k in _dupes)
    raise SystemExit(
        f"✗ facts.py 里有 {len(_dupes)} 个 key 定义了两次（后者覆盖前者）：\n  {_detail}\n"
        "  怎么办：保留口径最新、带 mirror 的那条（另一个 numbers 已在输出字典里有家），删掉另一个。")

FACT_BY_KEY = {f.key: f for f in F}


def check_mirrors(facts: dict, metric_values: dict) -> list[str]:
    """手写事实 ↔ 输出字典：两条取数路径必须给出同一个数。

    2026-09-12 下沉到本文件（原先只住在 `onepager.check()` 里）：
    * 只在 onepager 跑 ⇒ `build.py` 那条管线（facts.json 落盘）完全没校到；
    * 原来 `mirror` 指向字典里没有的 key 时会**静默 continue**——写着"互校"，
      实际什么也没校。这就是"key 在 source 里找不到还能读到数吗"的答案：
      读不到，而且没人告诉你。
    """
    problems: list[str] = []
    for fact in F:
        if not fact.mirror:
            continue
        item = facts.get(fact.key)
        if item is None:
            continue                      # 本次没取到（strict=False 的场合）
        if fact.mirror not in metric_values:
            problems.append(
                f"facts.{fact.key} 的 mirror={fact.mirror} 不在输出字典里——"
                f"两条路径根本校不上（写着互校，等于没校）。"
                f"把它改成 configs/metrics.toml 里真实存在的 key，或删掉这条手写事实")
            continue
        a, b = item["v"], metric_values[fact.mirror]
        if b != b and a == a:
            # 事实有值、字典那头却是空的：等于"写着互校，实际只有一条路有数"。
            # 典型原因就是 at_cfg 路径写错（finance.wacc 写成了 meta.wacc），
            # 而 read_metrics 对 NaN 只报不中断——这里必须补上这一刀。
            problems.append(
                f"镜像那头是空的：facts.{fact.key}={a:,.6g} 有值，"
                f"METRICS.{fact.mirror} 却是 NaN——去 configs/metrics.toml 查 "
                f"{fact.mirror} 的 `at`/`at_cfg` 路径写对没有")
            continue
        if a != a or b != b:
            continue                      # 两头都空：read_metrics 已 ⚠ 报过，不重复刷屏
        if abs(a - b) > 1e-9 * max(1.0, abs(b)):
            where = getattr(fact.get, "__doc__", "") or "派生"
            if abs(a * 100.0 - b) < 1e-9 * max(1.0, abs(b)) or abs(a - b * 100.0) < 1e-9 * max(1.0, abs(a)):
                problems.append(
                    f"百倍差（比值 vs 百分数）：facts.{fact.key}={a:,.6g}"
                    f" vs METRICS.{fact.mirror}={b:,.6g}——两边差的正好是 100 倍。"
                    f"本仓库的规矩是**占比一律以百分数存储**（v=40 表示 40%），"
                    f"请把 facts.{fact.key} 改成存百分数（unit='%'、kind='num'）")
                continue
            problems.append(
                f"镜像不一致：facts.{fact.key}={a:,.6g}（{where}）"
                f" vs METRICS.{fact.mirror}={b:,.6g}——同一个数两条路径算出两个值，"
                f"先确认两者是不是同一个口径（现值/名义、%/比值、存量/流量）")

    # **同名即为镜像**：手写事实与字典撞了同一个 key 时，`build_facts` 会保留手写事实、
    # 静默丢掉字典那条——两条互不照面，正是最隐蔽的"一个数两个家"。
    # 同名不像别名那样眼可见，故此处一并断言：撞 key 就必须同值。
    for fact in F:
        if fact.key in facts and fact.key in metric_values and not fact.mirror:
            a, b = facts[fact.key]["v"], metric_values[fact.key]
            if a != a or b != b:
                continue
            if abs(a - b) > 1e-9 * max(1.0, abs(b)):
                problems.append(
                    f"同名不同值：facts.{fact.key}={a:,.6g} vs METRICS.{fact.key}={b:,.6g}"
                    f"——撞了同一个 key 却算出两个数（事实包会悄悄用前者）。"
                    f"改其中一个的名字，或补 `mirror=` 声明它们本就是一个数")
    return problems


# ─────────────────────────────────────────── 呈现
def render(fact: Fact, value: Any) -> str:
    """事实的规范写法。{{key}} 注入的就是这个字符串。"""
    if fact.kind == "text":
        return str(value)
    if fact.kind == "year":
        return f"{int(round(float(value)))}{fact.unit}"     # 年份不加千分位（2030 ≠ 2,030）
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
    if fact.kind == "year":
        return f"{int(round(float(value)))}"
    if fact.kind == "int":
        return f"{int(round(float(value))):,}"
    if fact.kind == "pct":
        return f"{float(value) * 100:,.{fact.decimals}f}"
    return f"{float(value):,.{fact.decimals}f}"


# ─────────────────────────────────────────── 生成
def build_facts(snapshot: dict | None = None, strict: bool = True,
                metrics_values: dict | None = None) -> dict:
    """装配事实包。

    strict=True（默认，build.py 走这条路）：任何一条事实取不到就中断——
    宁可中断也不能给出一份缺数的事实包。

    strict=False：给**只跑了一次 build_model 的场景**用（一页纸、浏览器内 Pyodide 重跑）。
    这些场景没有 `snap["sensitivity"]`（敏感性表）与 `_extra.scenarios`（三情景表），
    依赖它们的事实（sens.*）自然取不到——跳过即可，不该让整包失败。
    """
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
            "mirror": fact.mirror,
        }
    if missing and strict:
        raise KeyError("以下事实在快照里取不到（快照结构变了？）：\n  " + "\n  ".join(missing))
    if missing:
        print(f"　（strict=False：{len(missing)} 条事实取不到已跳过，"
              f"多为依赖敏感性表/三情景表的 sens.*）")

    # 两条取数路径必须对得上：手写事实 vs 输出字典。
    # 放在这里而不是某一张页面里，是因为 **每条管线都要校**（build.py / run.py / 浏览器重跑）。
    if metrics_values:
        _mirror_bad = check_mirrors(out, metrics_values)
        if _mirror_bad:
            raise ValueError("事实包与输出字典互相校不上：\n  " + "\n  ".join(_mirror_bad))

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
    # ── 合并信源引用事实（src.*，来自台账「信源索引（机读）」）──────
    # 链接是被引用的数据：这里只从唯一的家读出来渲染，下游一律写 {{src.xxx}}。
    for r in load_ref_facts():
        if r.key in out:
            bad.append(f"{r.key}：与已有事实重名")
            continue
        if not r.url.startswith(("http://", "https://")):
            bad.append(f"{r.key}：URL 不可点击（{r.url}）——信源必须是外部可达的链接")
            continue
        out[r.key] = {
            "label": r.label,
            "v": r.url,
            "text": r.text,
            "bare": r.text,
            "unit": "",
            "kind": "src",
            "watch": 1.0,
            "from": r.url,
            "as_of": r.as_of,
            "note": f"{r.grade}｜用于 {r.used_by}",
            "mirror": "",
        }

    # ── 合并输出字典指标（2026-09-12：字典条目自动进事实包，键＝指标内部名）────
    # MD 里写 {{中文名}} 时，inject 经 resolve() 把中文名→指标 key→这里取值。
    # 已有手写 Fact（如 val.* 镜像项）的 key 优先，不覆盖；其余字典指标并入事实包。
    if metrics_values:
        try:
            from lab import METRIC_BY_KEY
        except Exception:
            METRIC_BY_KEY = {}
        for _k, _v in metrics_values.items():
            if _k in out or _k not in METRIC_BY_KEY:
                continue
            _m = METRIC_BY_KEY[_k]
            # Metric 无 kind 字段：按单位推断（%→pct，其余→num；×/倍 用 num 也正确）
            _kind = "pct" if (_m.unit or "").strip() == "%" else "num"
            _f = Fact(_m.key, _m.label, lambda s: None,
                      _m.unit or "", _kind, _m.decimals or 1,
                      watch=0.03, note=_m.note or "")
            out[_k] = {
                "label": _m.label,
                "v": float(_v),
                "text": render(_f, _v),
                "bare": render_bare(_f, _v),
                "unit": _m.unit,
                "kind": _kind,
                "watch": 0.03,
                "from": _m.source,
                "note": _m.note,
                "mirror": "",
            }

    if bad:
        raise ValueError("外部事实（ext.* / src.*）不合规：\n  " + "\n  ".join(bad))

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

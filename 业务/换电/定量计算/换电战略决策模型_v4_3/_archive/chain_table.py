"""「从假设到决策」全链条表生成器。

设计原则
--------
1. **数值一律来自 config + 模型实跑**，不手抄。config 参数按路径读取，派生量从
   ModelSnapshot（scale/capex/swap/ledger）读取；模型改版后重跑即得新表，不会脱钩。
2. **公式是手写的**（给人看的计算链），但每条都有对应的 `check` 自校验：
   用公式重算一遍与模型值比对，超差即报错。模型改公式而表没改，重跑会当场失败。
3. 列布局：6 组（重卡/城配/乘用营运/营运合计/私家/总计）× 3 情景（悲观/中性/乐观）。
   中性档 == 模型基线（service_fee 0.30、charge_share 中性、私家中枢、制造净利率 13.5%）。

运行：python src/chain_table.py
"""
from __future__ import annotations

import math
import re
import sys
from copy import deepcopy
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

import config_loader  # noqa: E402
import model as model_mod  # noqa: E402

# ---------------------------------------------------------------- 情景定义
# 三情景 = 把 config 里本来就有三档的参数同时拨档；
# 中性档严格等于模型基线（不改动任何参数即基线）。
SCENARIOS = [
    ("悲观", dict(service_fee=0.20, charge_share="悲观", private="保守", margin=0.125)),
    ("中性", dict(service_fee=0.30, charge_share="中性", private="中枢", margin=0.135)),
    ("乐观", dict(service_fee=0.40, charge_share="乐观", private="激进", margin=0.150)),
]

# 模型车型键 → 展示分组
GROUPS = [
    ("重卡", ["heavy"]),
    ("城配", ["city"]),
    ("乘用营运", ["taxi", "ridehail", "robotaxi"]),
    ("营运合计", ["heavy", "city", "taxi", "ridehail", "robotaxi"]),
    ("私家", ["private"]),
    ("总计", ["heavy", "city", "taxi", "ridehail", "robotaxi", "private"]),
]
ALL_VEHICLES = ["heavy", "city", "taxi", "ridehail", "robotaxi", "private"]
OPERATING = ["heavy", "city", "taxi", "ridehail", "robotaxi"]

# 电池池 → 所属展示分组（choco25_passenger 由乘用营运与私家共享，按换电量分摊）
POOL_OWNER = {
    "qiji75_short": "heavy",
    "qiji75_trunk": "heavy",
    "choco35_city": "city",
    "choco25_passenger": "shared_passenger",
}
SHARED_POOL = "choco25_passenger"
SHARED_MEMBERS = ["taxi", "ridehail", "robotaxi", "private"]


# ---------------------------------------------------------------- 信源（最终可用版本）
# 直接给出每个指标最终采用的信源与可点链接，不含历史更新过程与审计判定。
# 第二元素：http(s) 外链；或相对 ROOT 的本地路径（解析为 file://）；None = 无外链，
# 此时第一元素若为「经验假设」类说明即作为最终可用版本。
FINAL_SRC: dict[str, tuple[str, str | None]] = {
    # —— A. 车辆层 ——
    "换电车辆（万辆）": ("自下而上 5 层漏斗（保有→更新→电动化→换电渗透→CATL份额→进宁德），分项信源见下行",
                    "https://www.gov.cn/zhengce/zhengceku/202606/content_7072002.htm"),
    "车辆基数（万辆）": ("重卡/城配/出租/网约＝2030 保有量；私家/Robotaxi＝2026–2030 各年净增之和",
                    None),
    "当年电动新增（万辆/年）": ("＝总保有÷更新周期×NEV渗透率(末年)；净增口径＝末年净增×纯电占比",
                          None),
    "更新周期（年）": ("货车强制报废标准（15 年）→ 电动重卡取 9 年更新；城配 8 年；出租 8 年",
                  "https://www.gov.cn/zhengce/zhengceku/202606/content_7072002.htm"),
    "NEV渗透率（逐年）": ("重卡 S 曲线 2026=35%→2030=50%（国泰海通/JPM）；城配 32.4%→95%；出租/网约流量口径→100%；逐年全 5 年值见明细 sheet 表B2",
                      "https://www.gov.cn/zhengce/zhengceku/202606/content_7072002.htm"),
    "纯电占比": ("新能源中纯电占比（剔除插混）：重卡 96%、乘用营运 100%、私家 100%",
               None),
    "换电渗透率（分场景）": ("重卡分场景 30/50/70%（JPM 续航分布 + 极兔 5000 台订单实证）；城配高频 50%；出租/网约 50%；Robotaxi 100%；私家分档",
                       "https://m.10jqka.com.cn/20260702/c677904714.shtml"),
    "CATL换电份额（分场景）": ("重卡短途 30%/长途 70%（极兔订单、奥动原话）；城配 80%；出租/网约 50%；Robotaxi 100%；私家 50%",
                          "https://chejiahao.autohome.com.cn/info/25909400"),
    "场景权重（分场景）": ("重卡短途38%/中途50%/长途12%（JPM 续航分布）；城配高频30%/低频70%；私家价格带 8万下12.3%/8–15万40.4%/15万+47.3%（中汽协）",
                         "https://auto.cri.cn/20260211/89cb7bc0-d691-49c4-926b-fed73a9366fc.html"),
    "存量CATL换电结转（万辆）": ("2025 已入 CATL 换电体系存量：重卡 0.7 万（盐田港案例）、城配单列不并入 headline",
                            None),
    "里程池（亿车·km）": ("2030 里程池 3500 亿 = 2025 客运量 344.82 亿人次×9km×年增 3%（交通运输部公报）",
                      "https://www.thepaper.cn/newsDetail_forward_32501028"),
    "Robotaxi 保有（万）": ("50 万 = 高盛/东吴/巴克莱 30–50 万共识取上沿",
                       "https://www.toutiao.com/article/7535654361658130959/"),
    "出租保有（万）": ("巡游出租 132.31 万（交通运输部 2025 公报原文）",
                   "https://www.gov.cn/lianbo/202606/content_7072829.htm"),
    "私家车累计净增（万）": ("2030 私家车 EV 保有 11400 万(IEA) − 2025 纯电 3022 万(公安部) = 8400 万累计净增",
                        "https://www.iea.org/data-and-statistics/data-tools/global-ev-data-explorer"),
    "价格带占比": ("中汽协 2025 实测占比：8万下 12.3% / 8–15万 40.4% / 15万+ 47.3%",
                "https://auto.cri.cn/20260211/89cb7bc0-d691-49c4-926b-fed73a9366fc.html"),
    "私家车分档换电渗透": ("中枢：8万下0 / 8–15万5% / 15万+3%（受 CTC/CTB 架构与蔚来竞争约束，分档假设）",
                       None),
    # —— B. 运营层 ——
    "年换电量（亿度）": ("＝换电车辆×1e4×频次×单次补电量×运营天数÷1e8", None),
    "换电频次（次/天）": ("＝日均里程÷可用续航；可用续航＝背电量×可用系数÷电耗（derived.py）", None),
    "单次补电量（kWh）": ("＝背电量×可用能量系数(补能比例)；重卡 342/513、乘用 56、城配 81", None),
    "日均里程（km）": ("分场景日均里程：重卡 130/400/650、城配 300、出租 450、网约 342、Robotaxi 450、私家 60", None),
    "背电量（kWh）": ("实际装车电量：重卡短途 342/中长途 513（盐田港 171kWh 块）、乘用 56（25#块）、城配 81（35#块）",
                  "https://www.catl.com/news/9884.html"),
    "电耗（kWh/km）": ("单公里电耗：重卡 1.5/1.7、乘用 0.15、城配 0.27", None),
    "可用能量系数（补能比例）": ("可用 SOC 窗口占装车电量比例（换电非 0→100%），经验假设", None),
    "可用续航（km）": ("＝背电量×可用系数÷电耗（频次的分母）", None),
    "年运营天数": ("年运营天数，保守取 350（留检修与极端天气），经验假设", None),
    # —— C. 站数层 ——
    "换电站数（座）": ("＝⌈(日换电需求−私家溢出)÷单站规划能力⌉，私家先填单站物理冗余、溢出才新建（四站型独立反推）", None),
    "日换电次数（万次）": ("＝换电车辆×换电频次", None),
    "单站规划能力": ("外生假设的规划日接待能力（非物理上限）", None),
    "单站物理上限": ("＝min(营业时长×3600÷单次换电秒数, 充电功率×时长×RTE÷(块电量×可用系数))", None),
    "单站投资（万元）": ("站体（不含电池）单站建设投资，外生假设", None),
    "单站库存块数": ("单站配备周转电池块数，外生假设", None),
    "单块带电量（kWh）": ("标准电池块容量（25#56 / 35#81 / 75#171 kWh）", "https://www.catl.com/news/9884.html"),
    # —— D. 电池与 CAPEX ——
    "初装CAPEX合计（亿）": ("＝电池初装CAPEX ＋ 站体CAPEX", None),
    "电池初装CAPEX（亿）": ("＝(装车电池 ＋ 站内周转电池)×电池价格÷100", None),
    "站体CAPEX（亿）": ("＝站数×单站投资÷1e4", None),
    "装车电池装机（GWh）": ("＝Σ年 Σ场景 CATL换电车辆×背电量÷100", None),
    "站内周转电池（GWh）": ("＝站数×单站库存块数×单块带电量÷1e6", None),
    "电池价格（元/kWh）": ("三阶段价格曲线基年价格（平台期→快速降→慢速降），行业假设", None),
    "电池寿命（年）": ("＝min(临界循环次数÷(池均频次×年运营天数), 日历寿命封顶)；按四物理电池池核算", None),
    "全周期资本基数（亿）": ("＝初装CAPEX×(1＋重置现值比)（EAC 式全周期资本）", None),
    "年折旧（亿）": ("＝电池折旧基数÷电池寿命 ＋ 站体CAPEX÷站体折旧年限（会计寿命）", None),
    "年资本要求 FCFF（亿）": ("＝全周期资本基数×CRF（满足 15% 回报的年度自由现金流）", None),
    "CRF（资本回收系数）": ("资本回收系数＝要求回报×(1+要求回报)^n÷((1+要求回报)^n−1)，与 required_return 上沿一致", None),
    "WACC": ("能源基建行业收益率 6–8% 中性中枢，经验假设", None),
    "债务比例": ("类固收项目可做到 1:1.5 杠杆，经验假设", None),
    # —— E. 收入/成本/EBITDA ——
    "营收合计（亿）": ("＝服务费收入 ＋ 电池租金 ＋ 峰谷套利 ＋ 辅助服务（净额法）", None),
    "换电服务费（亿）": ("＝年换电量×度电服务费（净额法）", None),
    "度电服务费（元/kWh）": ("三情景：悲观 0.20 / 中性 0.30 / 乐观 0.40 元/kWh（CATL 公开月租/服务费）", None),
    "电池租金（亿）": ("＝收租装机×度电租金÷100（收租装机＝装车 ＋ 站内×外部股东占比）", None),
    "度电租金（元/kWh·年）": ("综合约 10 元/月折算的年度租金单价，经验假设", None),
    "收租装机（GWh）": ("＝装车电池 ＋ 站内外股东电池（可出租电池资产）", None),
    "峰谷套利（亿）": ("＝站内周转装机×天数×峰谷价差×RTE÷100（每日夜间谷充峰放一次）", None),
    "辅助服务（亿）": ("＝容量补偿 ＋ max(需求响应, 调频VPP)（变动收益取孰高）", None),
    "OPEX 合计（亿）": ("＝充电成本 ＋ 场租 ＋ 人工 ＋ 软件 ＋ 保险 ＋ 池维护 ＋ 仓储物流", None),
    "充电成本（亿）": ("＝净电量×谷电价（净电量＝总充电−换电量，仅 RTE 损失与厂用电）", None),
    "场租（亿）": ("＝站数×单站年租÷1e4", None),
    "人工（亿）": ("＝站数×单站人工成本（重卡/乘用站分别取）", None),
    "软件调度（亿）": ("全网站点调度系统年度运维，已由 20 亿核减为 2 亿", None),
    "保险＋池维护＋仓储（亿）": ("＝电池资产×保险费率 ＋ 装机×维护费率 ＋ 仓储（蔚能实证费率）", None),
    "可交付 EBITDA（亿）": ("＝营收合计 − OPEX 合计", None),
    "EBITDA 率": ("＝可交付EBITDA÷营收合计", None),
    "门槛 EBITDA（亿）": ("＝全周期资本基数×EBITDA/CAPEX（满足要求回报最低要求，全网口径）", None),
    "安全边际（可交付÷门槛）": ("＝可交付EBITDA÷门槛EBITDA；>1 即达标（全网口径）", None),
    # —— F. 估值与决策 ——
    "换电增量价值合计（亿）": ("＝运营线归属价值 ＋ 制造线换电锁定毛利贡献", None),
    "运营线：企业价值 EV（亿）": ("＝可交付EBITDA×EV/EBITDA 倍数", None),
    "运营线：宁德归属价值（亿）": ("＝项目股权价值×建站持股比例（config stations.*.catl_equity_share）", None),
    "EV/EBITDA 倍数": ("估值倍数中枢，行业参照", None),
    "制造线：换电锁定毛利贡献（亿）": ("＝有换电 vs 无换电制造端净利差 × 制造PE", None),
    "制造线：净利率差效应（亿）": ("＝有换电−无换电净利率，三档 0/1.0/2.5pct", None),
    "集团市值（亿）": ("A+H 总市值（估值分母）", None),
    "增量价值 / 集团市值": ("＝换电增量价值÷集团市值（决策核心读数）", None),
    "宁德初始权益出资（亿）": ("＝初装CAPEX×股权比例×CATL 权益比例", None),
    "回收期（年）": ("＝宁德初始出资÷宁德年可分现金", None),
    "决策阈值：安全边际下限": ("安全边际下限，低于即判定不达标", None),
}


def src_for(plain_name: str) -> tuple[str, str | None]:
    """返回 (最终可用信源文本, 链接)。链接为 http(s) 或 ROOT 下的本地 file://。"""
    rec = FINAL_SRC.get(plain_name)
    if not rec:
        return ("模型派生（由下行参数计算，见计算链）"
                if plain_name in ("换电车辆（万辆）", "年换电量（亿度）", "换电站数（座）",
                                   "初装CAPEX合计（亿）", "营收合计（亿）", "OPEX 合计（亿）",
                                   "可交付 EBITDA（亿）", "换电增量价值合计（亿）") else "模型派生",
                None)
    text, url = rec
    if url and not url.startswith("http"):
        p = (ROOT / url).resolve()
        url = p.as_uri() if p.exists() else None
    return (text, url)


# ---------------------------------------------------------------- 情景上下文
class Ctx:
    """一个情景下的全部中间量。"""

    def __init__(self, cfg: dict, snap):
        self.cfg = cfg
        self.snap = snap
        self.sb = cfg["swap_business"]
        self.usable = self.sb["usable_energy_factor"]
        self.days = self.sb["operating_days"]
        self.stock = dict(snap.scale.operating_stock_by_vehicle_wan)
        self.freq = dict(snap.scale.terminal_frequency_by_vehicle)
        # 车型级逐年累计换电车辆（= 终局车辆数，全部年份累加）
        self.energy = self._per_vehicle_energy()
        self.onboard_wavg = self._wavg("onboard_battery_kwh")
        self.pool_share = self._pool_share()

    def rows_for(self, vkey):
        return [r for r in self.snap.scale.rows if r.vehicle_key == vkey]

    def _per_vehicle_energy(self) -> dict[str, float]:
        """按车型推算年换电量（亿度）：车辆×1e4×频次×单次补电量×天数÷1e8。"""
        out = {k: 0.0 for k in ALL_VEHICLES}
        for r in self.snap.scale.rows:
            per = r.catl_swap_vehicles_wan * 1e4 * r.swap_frequency_per_day
            per = per * r.onboard_battery_kwh * self.usable * self.days / 1e8
            out[r.vehicle_key] += per
        return out

    def _wavg(self, field: str) -> dict[str, float]:
        """按换电车辆数加权的场景级参数（重卡短途342/中长途513等）。"""
        out = {}
        for v in ALL_VEHICLES:
            rs = self.rows_for(v)
            tot = sum(r.catl_swap_vehicles_wan for r in rs)
            out[v] = (
                sum(getattr(r, field) * r.catl_swap_vehicles_wan for r in rs) / tot
                if tot else 0.0
            )
        return out

    def _pool_share(self) -> dict[tuple[str, str], float]:
        """池 → 车型 分摊权重（共享池按换电量份额）。"""
        share: dict[tuple[str, str], float] = {}
        for pool, owner in POOL_OWNER.items():
            if owner != "shared_passenger":
                share[(pool, owner)] = 1.0
                continue
            tot = sum(self.energy[m] for m in SHARED_MEMBERS)
            for m in SHARED_MEMBERS:
                share[(pool, m)] = (self.energy[m] / tot) if tot else 0.0
        return share

    def alloc_pool(self, pool_value: dict, field: str) -> dict[str, float]:
        """把池级指标（PoolOperations 字段）分摊到车型。"""
        out = {k: 0.0 for k in ALL_VEHICLES}
        for pool, ops in pool_value.items():
            val = getattr(ops, field, 0.0)
            for (p, v), w in self.pool_share.items():
                if p == pool:
                    out[v] += val * w
        return out

    def alloc_stations(self) -> dict[str, float]:
        out = {k: 0.0 for k in ALL_VEHICLES}
        for pool, n in self.snap.scale.target_station_demand.items():
            for (p, v), w in self.pool_share.items():
                if p == pool:
                    out[v] += n * w
        return out


def build_ctx(scen: dict) -> Ctx:
    cfg = config_loader.load_config()
    cfg["swap_business"]["service_fee_rmb_kwh"] = scen["service_fee"]
    cfg["charge_share"]["scenario"] = scen["charge_share"]
    cfg["swap_business"]["with_swap_manufacturing_net_margin"] = scen["margin"]
    snap = model_mod._build_core(
        cfg, cfg["mna"]["base_scenario_name"], scen["private"], "derived"
    )
    ctx = Ctx(cfg, snap)
    ctx.private_key = scen["private"]   # 供下钻行按情景取私家车换电渗透
    return ctx


# ---------------------------------------------------------------- 取值助手
def cfg_param(path_tpl: str):
    """按模板从 config 读参数，返回 {车型: 值}。"""
    def f(c: Ctx) -> dict:
        out = {}
        for v in ALL_VEHICLES:
            node = c.cfg
            ok = True
            for part in path_tpl.replace("{v}", v).split("."):
                if isinstance(node, dict) and part in node:
                    node = node[part]
                else:
                    ok = False
                    break
            out[v] = node if ok else None
        return out
    return f


def scenes_wavg(field: str, year_idx: int | None = None):
    """场景级参数按 CATL 换电车辆加权平均（渗透率/份额/里程等强度量）。"""
    def f(c: Ctx) -> dict:
        out = {}
        for v in ALL_VEHICLES:
            scenes = c.cfg["vehicles"][v].get("scenes", [])
            if not scenes:
                out[v] = None
                continue
            # 权重：该场景当年累计的 CATL 换电车辆
            rs = c.rows_for(v)
            w = {}
            for r in rs:
                w[r.scene] = w.get(r.scene, 0.0) + r.catl_swap_vehicles_wan
            tot = sum(w.values())
            if tot <= 0:
                out[v] = None
                continue
            vehicle_level = c.cfg["vehicles"][v].get(field)
            val = 0.0
            for s in scenes:
                # 场景层没有该参数时回退到车型层（如 city/private 的 daily_km 在车型层）
                raw = s.get(field, vehicle_level)
                if raw is None:
                    continue
                if isinstance(raw, list):
                    raw = raw[year_idx if year_idx is not None else -1]
                val += raw * w.get(s["name"], 0.0)
            out[v] = val / tot
        return out
    return f


def global_val(path: str):
    """全局参数：所有列同值。"""
    def f(c: Ctx) -> dict:
        node = c.cfg
        for part in path.split("."):
            node = node[part]
        return {v: node for v in ALL_VEHICLES}
    return f


def derived(fn):
    """自定义按车型派生。"""
    return fn


# ---------------------------------------------------------------- 行定义
# kind: sec | main | param
# agg : sum(广延量) | wavg(强度量，按换电车辆加权) | global(同值) | none(仅总计)
Row = dict
ROWS: list[Row] = []


def R(kind, name, eng, formula, unit, fetch, agg="sum", src=None, check=None):
    ROWS.append(dict(kind=kind, name=name, eng=eng, formula=formula, unit=unit,
                     fetch=fetch, agg=agg, src=src, check=check))


def sec(title):
    ROWS.append(dict(kind="sec", name=title))


# ---------------------------------------------------------------- 计算链（真实公式）辅助
# 这些函数从 config 实跑生成推导式文本，保证「节点→子参数」可串、且永不与代码脱钩。
def _cfg_op_stocks(cfg: dict) -> dict[str, float]:
    """营运车保有量由里程池反推（复刻 scale._operating_stocks）。"""
    d = cfg["operating_demand"]
    robotaxi_km = d["robotaxi_fleet_wan"] * d["robotaxi_daily_km"] * d["robotaxi_days"] / 1e4
    human_stock = (d["pool_2030_yi_km"] - robotaxi_km) / (
        d["human_daily_km"] * d["human_days"] / 1e4
    )
    return {"taxi": d["taxi_stock_wan"], "ridehail": human_stock - d["taxi_stock_wan"]}


def _cfg_year_base(cfg: dict, v: str, yidx: int = -1) -> float:
    """某车型末年（或指定年）进入电动漏斗的基础增量（万辆/年）。"""
    veh = cfg["vehicles"][v]
    pure = veh.get("pure_electric_share", 1.0)
    if "annual_net_additions_wan" in veh:
        return veh["annual_net_additions_wan"][yidx] * pure
    st = _cfg_op_stocks(cfg).get(veh.get("stock_source"), veh.get("stock_wan"))
    return st / veh["replacement_cycle_years"] * veh["nev_rates"][yidx] * pure


def _fmt_scenes(cfg: dict, v: str, field: str, pct: bool = True) -> str:
    """把某车型的各场景取值拼成『场景名:值』串（重卡/城配/私家分场景可见）。"""
    out = []
    for s in cfg["vehicles"][v]["scenes"]:
        val = s.get(field)
        if pct and isinstance(val, (int, float)):
            out.append(f"{s['name']}{val * 100:.0f}%")
        else:
            out.append(f"{s['name']}{val}")
    return "·".join(out)


def _funnel_main(cfg: dict) -> str:
    """换电车辆主项的计算链：展示各车型基础年增量如何由保有量/净增推得。"""
    lines = []
    for v in ["heavy", "city", "taxi", "ridehail", "robotaxi", "private"]:
        veh = cfg["vehicles"][v]
        if "annual_net_additions_wan" in veh:
            val = veh["annual_net_additions_wan"][-1] * veh.get("pure_electric_share", 1.0)
            base = f"各年净增(末{val:.0f})×纯电{veh.get('pure_electric_share', 1.0) * 100:.0f}%"
        else:
            st = _cfg_op_stocks(cfg).get(veh.get("stock_source"), veh.get("stock_wan"))
            base = f"{st:.1f}÷{veh['replacement_cycle_years']:.0f}×NEV{veh['nev_rates'][-1] * 100:.0f}%"
        lines.append(f"  {veh['label']}: {base}")
    return (
        "终局换电车辆 = Σ年(2026–2030) Σ场景[\n"
        "    基础年增量_y × NEV渗透率_y × 场景占比_s × 换电渗透率_s × CATL换电份额_s\n"
        "  ] ＋ 首年存量结转(仅 year0 按场景构成分摊)\n"
        "基础年增量_y（进入电动漏斗的当年新增）：\n" + "\n".join(lines) + "\n"
        "网约总保有 = (里程池 − Robotaxi里程) ÷ (日均里程×天数) − 出租保有"
    )


def _funnel_scenes(cfg: dict, field: str, intro: str) -> str:
    """换电渗透率/CATL份额/场景权重：逐车型列出分场景数值。"""
    lines = []
    for v in ["heavy", "city", "taxi", "ridehail", "robotaxi", "private"]:
        lines.append(f"  {cfg['vehicles'][v]['label']}: {_fmt_scenes(cfg, v, field)}")
    return intro + "：\n" + "\n".join(lines)


def _lambda_scenes(field: str, intro: str):
    """返回一个 callable(cfg)→str，供公式列展示分场景真实数值。"""
    return lambda cfg: _funnel_scenes(cfg, field, intro)


# ---------------------------------------------------------------- 换电车辆漏斗：参数名公式 + 逐年明细
# 全部由 config 现算（复刻 scale.py 的漏斗），与模型同源、不手抄；模型改版重跑即得新表。
FUNNEL_FORMULA = """换电车辆(v) = Σ_{y=2026..2030} Σ_{s∈场景} 进宁德(v,s,y)  ＋ 首年存量结转(v, 仅 y=2026)
进宁德(v,s,y) = 当年电动新增(v,y) × 场景权重(v,s) × 换电渗透率(v,s) × min(1, CATL份额(v,s)+份额上修(v))
              ＋ (y==2026 ? 存量结转(v,s) : 0)
当年电动新增(v,y) =
  · 保有口径(重卡/城配/出租/网约): vehicles.{v}.stock_wan ÷ replacement_cycle_years × vehicles.{v}.nev_rates[y] × pure_electric_share
      其中 出租/网约 stock_wan 由 [operating_demand] 里程池反推 = (pool_2030_yi_km − robotaxi里程) ÷ (human_daily_km×human_days) − taxi_stock_wan
  · 净增口径(私家/Robotaxi): vehicles.{v}.annual_net_additions_wan[y] × pure_electric_share
换电渗透率(v,s) = 私家车 ? scenario_swap_penetration.{保守/中枢/激进}[价格带] : vehicles.{v}.scenes[s].swap_penetration
份额上修(v) = mna.启源入股_不收蔚来.{heavy/passenger}_catl_swap_share_uplift
说明: 模型内 换电渗透率/CATL份额 分场景恒定(不随年变); 仅 NEV渗透率 逐年 S 曲线、私家车三情景不同。逐年限值见「换电车辆漏斗逐年明细」sheet"""


def _operating_stocks_cfg(cfg: dict) -> dict:
    """复刻 scale._operating_stocks：出租/网约保有量由营运里程池反推。"""
    d = cfg["operating_demand"]
    robotaxi_km = d["robotaxi_fleet_wan"] * d["robotaxi_daily_km"] * d["robotaxi_days"] / 1e4
    human_stock = (d["pool_2030_yi_km"] - robotaxi_km) / (
        d["human_daily_km"] * d["human_days"] / 1e4
    )
    return {"taxi": d["taxi_stock_wan"], "ridehail": human_stock - d["taxi_stock_wan"]}


def _annual_ev_cfg(veh: dict, yidx: int, stocks: dict) -> float:
    """复刻 scale._annual_ev_wan：当年进入电动漏斗的基础增量（万辆/年）。"""
    pure = veh.get("pure_electric_share", 1.0)
    if "annual_net_additions_wan" in veh:
        return veh["annual_net_additions_wan"][yidx] * pure
    stock = stocks[veh["stock_source"]] if "stock_source" in veh else veh["stock_wan"]
    return stock / veh["replacement_cycle_years"] * veh["nev_rates"][yidx] * pure


def _mna_uplift(cfg: dict, station_group: str) -> float:
    """CATL 换电份额上修（来自 mna 基准情景）。"""
    base = next(s for s in cfg["mna"]["scenarios"]
                if s["name"] == cfg["mna"]["base_scenario_name"])
    return (base["heavy_catl_swap_share_uplift"] if station_group == "heavy"
            else base["passenger_catl_swap_share_uplift"])


def _funnel_detail(cfg: dict, private_scenario: str) -> list[dict]:
    """复刻 scale.build_scale 的逐 车×场景×年 进宁德换电车辆漏斗（万辆）。

    返回每行: year/vkey/label/scene/base_add/nev/weight/swap_pen/catl_share/catl_swap。
    """
    years = cfg["construction"]["years"]
    stocks = _operating_stocks_cfg(cfg)
    table = cfg["vehicles"].get("private", {}).get("scenario_swap_penetration", {})
    private_pen = table.get(private_scenario, {}) if private_scenario != "中枢" else {}
    out = []
    for vkey, veh in cfg["vehicles"].items():
        uplift = _mna_uplift(cfg, veh["station_group"])
        existing = veh.get("existing_catl_swap_stock_wan", 0.0)
        exist_w = [s["weight"] * s["swap_penetration"] * s["catl_swap_share"]
                   for s in veh["scenes"]]
        ew_sum = sum(exist_w)
        for yidx, year in enumerate(years):
            annual_ev = _annual_ev_cfg(veh, yidx, stocks)
            nev = veh.get("nev_rates", [None] * len(years))[yidx] if "nev_rates" in veh else None
            for sidx, s in enumerate(veh["scenes"]):
                weight = s["weight"]
                swap_pen = (private_pen.get(s["name"], s["swap_penetration"])
                            if private_pen else s["swap_penetration"])
                catl_share = min(1.0, s["catl_swap_share"] + uplift)
                catl_swap = annual_ev * weight * swap_pen * catl_share
                if yidx == 0 and existing and ew_sum:
                    catl_swap += existing * exist_w[sidx] / ew_sum
                out.append(dict(year=year, vkey=vkey, label=veh["label"], scene=s["name"],
                                base_add=annual_ev, nev=nev, weight=weight,
                                swap_pen=swap_pen, catl_share=catl_share,
                                catl_swap=catl_swap))
    return out


# ===== A. 车辆层（树状下钻：主项 → 中间量 → 基础假设，全并入主表） =====
# 主表即「层层深挖的计算链条（总分结构）」：换电车辆 → 当年电动新增 / 场景权重 /
# 换电渗透率 / CATL换电份额 / 首年存量；每项再下钻到最基础假设。
# 纪律：① 计算链(公式)列只写中文名运算、绝不写具体数值（数值随参数变会乱套）；
#       ② 公式写在「正确的节点层」，最基础假设（叶状）节点计算链留白、改由信源列写取值依据+链接；
#       ③ 逐年变化的量（NEV渗透率、当年电动新增、净增）按 2026–2030 年展开行；
#          场景结构逐年恒定者只保留分场景行，不重复 3×5 行。
BASE_CFG = config_loader.load_config()   # 仅用于场景命名（情景无关），数值仍由模型实跑
_YEARS = BASE_CFG["construction"]["years"]
_PRIV_TABLE = BASE_CFG["vehicles"]["private"]["scenario_swap_penetration"]
_S = lambda k: FINAL_SRC.get(k, ("模型派生", None))   # 取「信源文本, 链接」二元组
_NET_SRC = (
    "私家＝累计净增口径（2026–2030 逐年 1200/1300/1600/2000/2300 万，由 IEA 2030 私家车 EV 保有 − 公安部 2025 纯电推算）；"
    "Robotaxi＝保有 50 万共识（高盛/东吴/巴克莱 30–50 万取上沿）+ 渗透爬坡（逐年 0/0/5/15/30 万）",
    FINAL_SRC["私家车累计净增（万）"][1],
)
_STOCK_SRC = (
    "重卡/城配＝2030 保有假设（900/1500 万）；出租＝交通运输部公报 132.31 万；"
    "网约＝营运里程池反推；私家/Robotaxi 为净增口径、无保有量",
    FINAL_SRC["出租保有（万）"][1],
)

sec("A. 车辆层：保有量 / 更新 / 渗透 / 份额 → 进宁德换电车辆 → 换电车辆（终局·三情景×三口径）")

R("main", "换电车辆（万辆）", "scale.operating_stock_by_vehicle_wan",
  "＝ Σ_{车×场景×年}[ 当年电动新增 × 场景权重 × 换电渗透率 × min(1, CATL换电份额＋份额上修) ]"
  "＋ 首年存量CATL换电结转（仅 y=2026）\n"
  "场景结构逐年恒定、不逐年展开；仅 NEV渗透率 / 当年电动新增 逐年变化，见下钻",
  "万辆",
  derived(lambda c: dict(c.stock)), "sum",
  check=lambda c: abs(sum(c.stock[k] for k in OPERATING) + c.stock["private"]
                      - sum(c.stock.values())) < 1e-9)

# —— 当年电动新增（漏斗「流量」入口；公式在本节点，组件为下钻子项）——
R("param", "↳ 当年电动新增（万辆/年）", "= 营运车: 保有量÷更新周期×NEV渗透率×纯电占比 | 私家/Robotaxi: 净增×纯电占比",
  "＝ 营运车：保有量 ÷ 更新周期 × NEV渗透率 × 纯电占比；私家/Robotaxi：净增 × 纯电占比（逐年值见下钻）",
  "万辆", derived(lambda c: _annual_flow(c)), "sum")

R("param", "↳↳ 保有量（万辆）", "vehicles.{v}.stock_wan | operating_demand 里程池反推",
  "", "万辆", derived(lambda c: {v: _stock_of(c, v) for v in ALL_VEHICLES}), "sum",
  src=_STOCK_SRC)

R("param", "↳↳ 更新周期（年）", "vehicles.{v}.replacement_cycle_years",
  "", "年", cfg_param("vehicles.{v}.replacement_cycle_years"), "wavg",
  src=_S("更新周期（年）"))

R("param", "↳↳ NEV渗透率（逐年）", "vehicles.{v}.nev_rates[y]（y=2026..2030）",
  "＝ ( 保有量÷更新周期×NEV渗透率×纯电占比 ) 中的 NEV 项；逐年 S 曲线，见下钻 5 年",
  "%", None, "wavg", src=_S("NEV渗透率（逐年）"))
for _yi, _yr in enumerate(_YEARS):
    R("param", f"↳↳↳ NEV渗透率 {_yr}", f"vehicles.{{v}}.nev_rates[{_yi}]",
      "", "%", derived(lambda c, _yi=_yi: {v: (c.cfg["vehicles"][v]["nev_rates"][_yi]
                              if "nev_rates" in c.cfg["vehicles"][v] else None)
                          for v in ALL_VEHICLES}), "wavg", src=_S("NEV渗透率（逐年）"))

R("param", "↳↳ 纯电占比", "vehicles.{v}.pure_electric_share",
  "", "%", cfg_param("vehicles.{v}.pure_electric_share"), "wavg",
  src=_S("纯电占比"))

# 净增：仅私家/Robotaxi 的基础假设口径（乘用营运中 Robotaxi 直接取、出租/网约车靠保有量÷更新周期推算）
R("param", "↳↳ 净增（万辆/年）", "vehicles.{v}.annual_net_additions_wan[y]（私家/Robotaxi）",
  "＝ 私家车/Robotaxi 累计净增口径（基础假设）；Robotaxi 直接取，私家车×纯电占比；营运车为保有口径、无净增",
  "万辆", None, "sum", src=_NET_SRC)
for _yi, _yr in enumerate(_YEARS):
    R("param", f"↳↳↳ 净增 {_yr}", f"vehicles.{{v}}.annual_net_additions_wan[{_yi}]",
      "", "万辆", derived(lambda c, _yi=_yi: {v: (c.cfg["vehicles"][v]["annual_net_additions_wan"][_yi]
                              if "annual_net_additions_wan" in c.cfg["vehicles"][v] else None)
                          for v in ALL_VEHICLES}), "sum", src=_NET_SRC)

# 当年电动新增：逐年、全车型（解决「重卡/城配缺失」）
for _yi, _yr in enumerate(_YEARS):
    R("param", f"↳↳ 当年电动新增 {_yr}", f"= 上层公式按年代入（y={_yr}）",
      "", "万辆", derived(lambda c, _yi=_yi: _annual_ev_dict(c, _yi)), "sum",
      src=("＝ 上层「当年电动新增」公式按年代入：营运车 保有量÷更新周期×NEV_%s×纯电占比；"
           "私家/Robotaxi 净增_%s×纯电占比" % (_yr, _yr), None))

# —— 场景权重：分场景（逐年恒定，不逐年展开）——
R("param", "↳ 场景权重（分场景）", "vehicles.{v}.scenes[s].weight",
  "＝ 分场景结构权重（见下钻逐场景）；× 当年电动新增 → 场景级电动新增",
  "%", None, "solo", src=_S("场景权重（分场景）"))
for _vkey in ["heavy", "city", "taxi", "ridehail", "robotaxi", "private"]:
    _veh = BASE_CFG["vehicles"][_vkey]
    for _s in _veh["scenes"]:
        R("param", f"↳↳ {_veh['label']}·{_s['name']} 场景权重", "scenes[].weight",
          "", "%", derived(lambda c, _vkey=_vkey, _w=_s["weight"]: {_vkey: _w}), "solo",
          src=_S("场景权重（分场景）"))

# —— 换电渗透率：分场景（逐年恒定；私家车分价格带三情景不同）——
R("param", "↳ 换电渗透率（分场景）", "vehicles.{v}.scenes[s].swap_penetration｜ private: scenario_swap_penetration.{保守/中枢/激进}[价格带]",
  "＝ 分场景换电渗透（见下钻逐场景）；× 场景电动新增 → 市场换电车辆（再×CATL份额→进宁德）",
  "%", None, "solo", src=_S("换电渗透率（分场景）"))
for _vkey in ["heavy", "city", "taxi", "ridehail", "robotaxi"]:
    _veh = BASE_CFG["vehicles"][_vkey]
    for _s in _veh["scenes"]:
        R("param", f"↳↳ {_veh['label']}·{_s['name']} 换电渗透率", "scenes[].swap_penetration",
          "", "%", derived(lambda c, _vkey=_vkey, _p=_s["swap_penetration"]: {_vkey: _p}), "solo",
          src=_S("换电渗透率（分场景）"))
for _s in BASE_CFG["vehicles"]["private"]["scenes"]:
    _band = _s["name"]
    R("param", f"↳↳ 私家车·{_band} 换电渗透率", "scenario_swap_penetration.{保守/中枢/激进}[{_band}]",
      "", "%", derived(lambda c, _band=_band: {"private": c.cfg["vehicles"]["private"]["scenario_swap_penetration"][c.private_key][_band]}), "solo",
      src=_S("私家车分档换电渗透"))

# —— CATL换电份额：分场景 + 份额上修 ——
R("param", "↳ CATL换电份额（分场景）", "min(1, vehicles.{v}.scenes[s].catl_swap_share ＋ mna.份额上修)",
  "＝ 分场景CATL换电份额（见下钻逐场景）；× 市场换电车辆 → 进宁德换电车辆",
  "%", None, "solo", src=_S("CATL换电份额（分场景）"))
for _vkey in ["heavy", "city", "taxi", "ridehail", "robotaxi", "private"]:
    _veh = BASE_CFG["vehicles"][_vkey]
    for _s in _veh["scenes"]:
        R("param", f"↳↳ {_veh['label']}·{_s['name']} CATL换电份额", "scenes[].catl_swap_share",
          "", "%", derived(lambda c, _vkey=_vkey, _p=_s["catl_swap_share"]: {_vkey: _p}), "solo",
          src=_S("CATL换电份额（分场景）"))
R("param", "↳↳ 份额上修（重卡/乘用）", "mna.{heavy/passenger}_catl_swap_share_uplift",
  "", "%", derived(lambda c: {_v: _mna_uplift(c.cfg, _v) for _v in ["heavy", "private"]}), "solo",
  src=("mna 基准情景 启源入股_不收蔚来 ⇒ 上修=0（重卡/乘用均 0）；并购情景才 重卡+1%/乘用+2~3%", None))

# —— 首年存量结转 ——
R("param", "↳ 首年存量CATL换电结转（万辆）", "vehicles.{v}.existing_catl_swap_stock_wan",
  "", "万辆", cfg_param("vehicles.{v}.existing_catl_swap_stock_wan"), "sum",
  src=_S("存量CATL换电结转（万辆）"))

# ===== B. 运营层 =====
sec("B. 运营层：里程 / 背电量 / 电耗 → 频次与单次补电量 → 换电量")
R("main", "年换电量（亿度）", "swap.annual_energy_yi_kwh",
  "= 换电车辆 × 1e4 × 换电频次 × 单次补电量 × 年运营天数 ÷ 1e8",
  "亿度",
  derived(lambda c: dict(c.energy)), "sum",
  check=lambda c: abs(sum(c.energy.values()) - c.snap.swap_business.annual_energy_yi_kwh)
  / max(1e-9, c.snap.swap_business.annual_energy_yi_kwh) < 0.02)
R("param", "↳ 换电频次（次/天）", "scale.terminal_frequency_by_vehicle",
  "= 日均里程 ÷ 可用续航；可用续航 = 背电量 × 可用能量系数 ÷ 电耗",
  "次/天", derived(lambda c: dict(c.freq)), "wavg")
R("param", "↳ 单次补电量（kWh）", "onboard_battery_kwh × usable_energy_factor",
  "= 场景背电量 × 可用能量系数（补能比例）",
  "kWh",
  derived(lambda c: {v: c.onboard_wavg[v] * c.usable for v in ALL_VEHICLES}), "wavg")
R("param", "↳ 日均里程（km）", "vehicles.{v}.scenes[].daily_km",
  "分场景日均行驶里程",
  "km", scenes_wavg("daily_km"), "wavg")
R("param", "↳ 背电量（kWh）", "vehicles.{v}.scenes[].onboard_battery_kwh",
  "实际装车电量（重卡短途342 / 中长途513，与频次分母同源）",
  "kWh", derived(lambda c: dict(c.onboard_wavg)), "wavg")
R("param", "↳ 电耗（kWh/km）", "vehicles.{v}.scenes[].energy_consumption_kwh_km",
  "百公里电耗折算的单公里电耗",
  "kWh/km", scenes_wavg("energy_consumption_kwh_km"), "wavg")
R("param", "↳ 可用能量系数（补能比例）", "swap_business.usable_energy_factor",
  "可用 SOC 窗口占装车电量比例（换电不是从0充到100%）",
  "%", global_val("swap_business.usable_energy_factor"), "global")
R("param", "↳ 可用续航（km）", "onboard_kwh × usable_energy_factor ÷ 电耗",
  "= 背电量 × 可用能量系数 ÷ 电耗（频次的分母）",
  "km",
  derived(lambda c: {v: (c.onboard_wavg[v] * c.usable / w)
                     if (w := _wavg_cons(c, v)) else None
                     for v in ALL_VEHICLES}), "wavg")
R("param", "↳ 年运营天数", "swap_business.operating_days",
  "年运营天数（保守取 350，留检修与极端天气）",
  "天", global_val("swap_business.operating_days"), "global")

# ===== C. 站数层 =====
sec("C. 站数层：日换电需求 ÷ 单站能力 → 站数（冗余优先）")
R("main", "换电站数（座）", "scale.target_station_demand",
  "= ⌈(日换电需求 − 私家溢出) ÷ 单站规划能力⌉，私家先填单站物理冗余，溢出才新建",
  "座", derived(lambda c: c.alloc_stations()), "sum")
R("param", "↳ 日换电次数（万次）", "vehicles × 频次",
  "= 换电车辆 × 换电频次",
  "万次/日",
  derived(lambda c: {v: c.stock[v] * c.freq[v] for v in ALL_VEHICLES}), "sum")
R("param", "↳ 单站规划能力", "stations.{pool}.planning_daily_capacity",
  "外生假设的规划日接待能力（非物理上限）",
  "次/日", derived(lambda c: _station_param("planning_daily_capacity")(c)), "wavg")
R("param", "↳ 单站物理上限", "min(机械能力, 充电能力)",
  "= min[营业时长×3600÷单次换电秒数, 充电功率×时长×RTE÷(块电量×可用系数)]",
  "次/日",
  derived(lambda c: _phys(c)), "wavg")
R("param", "↳ 单站投资（万元）", "stations.{pool}.station_body_capex_wan",
  "站体（不含电池）单站建设投资",
  "万元/座", derived(lambda c: _station_param("station_body_capex_wan")(c)), "wavg")
R("param", "↳ 单站库存块数", "stations.{pool}.inventory_blocks",
  "单站配备的周转电池块数",
  "块", derived(lambda c: _station_param("inventory_blocks")(c)), "wavg")
R("param", "↳ 单块带电量（kWh）", "stations.{pool}.block_kwh",
  "标准电池块容量",
  "kWh", derived(lambda c: _station_param("block_kwh")(c)), "wavg")

# ===== D. 电池与 CAPEX =====
sec("D. 电池与 CAPEX：装机 → 初装投资 → 全周期资本")
R("main", "初装CAPEX合计（亿）", "capex.total_initial_capex_yi",
  "= 电池初装CAPEX ＋ 站体CAPEX",
  "亿元",
  derived(lambda c: _capex_by_pool_alloc(c, "total_initial_capex_by_pool")), "sum")
R("param", "↳ 电池初装CAPEX（亿）", "= 电池总装机(GWh) × 电池价格 ÷ 100",
  "= (装车电池 ＋ 站内周转电池) × 电池价格(元/kWh) ÷ 100",
  "亿元", derived(lambda c: _battery_capex(c)), "sum")
R("param", "↳ 站体CAPEX（亿）", "= 站数 × 单站投资 ÷ 1e4",
  "站体不含电池；单站投资按万元折算为亿元",
  "亿元", derived(lambda c: _station_capex(c)), "sum")
R("param", "↳ 装车电池装机（GWh）", "scale.annual_catl_swap_gwh（累计）",
  "= Σ年 Σ场景 CATL换电车辆 × 背电量 ÷ 100",
  "GWh",
  derived(lambda c: {v: sum(r.catl_swap_gwh for r in c.rows_for(v))
                     for v in ALL_VEHICLES}), "sum")
R("param", "↳ 站内周转电池（GWh）", "stations × inventory_blocks × block_kwh ÷ 1e6",
  "= 站数 × 单站库存块数 × 单块带电量 ÷ 1e6",
  "GWh",
  derived(lambda c: {v: _station_gwh(c, v) for v in ALL_VEHICLES}), "sum")
R("param", "↳ 电池价格（元/kWh）", "construction.battery_price_curve.base_price_rmb_kwh",
  "三阶段价格曲线基年价格（平台期→快速降→慢速降）",
  "元/kWh", global_val("construction.battery_price_curve.base_price_rmb_kwh"), "global")
R("param", "↳ 电池寿命（年）", "scale.battery_pool_life_years",
  "= min(临界循环次数 ÷ (池均频次 × 年运营天数), 日历寿命封顶)",
  "年", derived(lambda c: _pool_life_alloc(c)), "wavg")
R("main", "全周期资本基数（亿）", "capex.lifecycle_capital_base_yi",
  "= 初装CAPEX × (1 ＋ 重置现值比)（EAC 式全周期资本）",
  "亿元",
  derived(lambda c: _capex_total_alloc(c, "lifecycle_capital_base_by_pool")), "sum")
R("param", "↳ 年折旧（亿）", "capex.mature_annual_depreciation_yi",
  "＝ 电池折旧基数 ÷ 电池寿命 ＋ 站体CAPEX ÷ 站体折旧年限",
  "亿元",
  derived(lambda c: _capex_total_alloc(c, "mature_annual_depreciation_by_pool")), "sum")
R("param", "↳ 年资本要求 FCFF（亿）", "= 全周期资本基数 × CRF",
  "资本端要求锚：满足期望回报所需的年度自由现金流",
  "亿元",
  derived(lambda c: _capex_alloc(c, "required_fcff_yi")), "sum")
R("param", "↳ CRF（资本回收系数）", "finance.capital_recovery_factor",
  "项目要求回报（非 WACC），与 required_return_range 上沿一致",
  "%", global_val("finance.capital_recovery_factor"), "global")
R("param", "↳ WACC", "finance.wacc",
  "能源基建行业收益率 6–8% 的中性中枢（显式假设）",
  "%", global_val("finance.wacc"), "global")
R("param", "↳ 债务比例", "finance.debt_ratio",
  "类固收项目可做到 1:1.5 杠杆",
  "%", global_val("finance.debt_ratio"), "global")

# ===== E. 收入 / 成本 / EBITDA =====
sec("E. 经营链：收入 → 成本 → 可交付 EBITDA")
R("main", "营收合计（亿）", "swap.revenue_yi",
  "= 服务费收入 ＋ 电池租金 ＋ 峰谷套利 ＋ 辅助服务",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "revenue_yi")), "sum")
R("param", "↳ 换电服务费（亿）", "= 年换电量(亿度) × 度电服务费",
  "净额法口径的服务费收入",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "service_revenue_yi")), "sum")
R("param", "↳ 度电服务费（元/kWh）", "swap_business.service_fee_rmb_kwh",
  "三情景档：悲观0.20 / 中性0.30 / 乐观0.40",
  "元/kWh", global_val("swap_business.service_fee_rmb_kwh"), "global")
R("param", "↳ 电池租金（亿）", "= 收租装机(GWh) × 度电租金 ÷ 100",
  "收租装机 = 装车电池 ＋ 站内电池×外部股东占比",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "battery_rent_yi")), "sum")
R("param", "↳ 度电租金（元/kWh·年）", "swap_business.battery_rent_rmb_kwh_year",
  "综合约 10 元/月 折算的年度租金单价",
  "元/kWh·年", global_val("swap_business.battery_rent_rmb_kwh_year"), "global")
R("param", "↳ 收租装机（GWh）", "rent_eligible_gwh",
  "= 装车电池 ＋ 站内外股东电池（可出租的电池资产）",
  "GWh", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                        "rent_eligible_gwh")), "sum")
R("param", "↳ 峰谷套利（亿）", "= 站内周转装机 × 天数 × 峰谷价差 × RTE ÷ 100",
  "每天只计夜间那一次谷充峰放",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "arbitrage_yi")), "sum")
R("param", "↳ 辅助服务（亿）", "= 容量补偿 ＋ max(需求响应, 调频VPP)",
  "同一调节行为不重复获利，变动收益取孰高",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "ancillary_yi")), "sum")
R("main", "OPEX 合计（亿）", "swap.opex_yi",
  "= 充电成本 ＋ 场租 ＋ 人工 ＋ 软件 ＋ 保险 ＋ 池维护 ＋ 仓储物流",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "opex_yi")), "sum")
R("param", "↳ 充电成本（亿）", "= 净电量 × 谷电价",
  "净额法：净电量 = 总充电量 − 换电量（仅 RTE 损失与厂用电）",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "energy_cost_yi")), "sum")
R("param", "↳ 场租（亿）", "= 站数 × 单站年租 ÷ 1e4",
  "站点场地租金",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "station_rent_yi")), "sum")
R("param", "↳ 人工（亿）", "= 站数 × 单站人工成本",
  "重卡/乘用站分别取单站年人工",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "labor_yi")), "sum")
R("param", "↳ 软件调度（亿）", "swap_business.software_opex_yi_year",
  "全网站点调度系统年度运维（已由 20 亿核减为 2 亿）",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "software_opex_yi")), "sum")
R("param", "↳ 保险＋池维护＋仓储（亿）", "= 电池资产×保险费率 ＋ 装机×维护费率 ＋ …",
  "蔚能实证费率校验的三项持有成本",
  "亿元", derived(lambda c: _three_costs(c)), "sum")
R("main", "可交付 EBITDA（亿）", "swap.ebitda_yi",
  "= 营收合计 − OPEX 合计",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "ebitda_yi")), "sum")
R("param", "↳ EBITDA 率", "= 可交付EBITDA ÷ 营收合计",
  "经营能力链的盈利质量",
  "%", derived(lambda c: _ratio(c, "ebitda_yi", "revenue_yi")), "wavg")
R("main", "门槛 EBITDA（亿）", "swap.required_ebitda_yi",
  "＝ 全周期资本基数 × EBITDA/CAPEX（满足要求回报的最低 EBITDA；全网口径，模型不按车型拆）",
  "亿元", derived(lambda c: _swap_total(c, "required_ebitda_yi")), "none")
R("main", "安全边际（可交付÷门槛）", "swap.forward_to_required_ebitda",
  "= 可交付EBITDA ÷ 门槛EBITDA；>1 即达标（全网口径）",
  "倍", derived(lambda c: _swap_total(c, "forward_to_required_ebitda")), "none")

# ===== F. 估值与决策 =====
sec("F. 估值与决策：运营价值 → 制造增量 → 决策结论")
R("main", "换电增量价值合计（亿）", "ledger.total_swap_increment_value_yi",
  "= 运营线归属价值 ＋ 制造线换电锁定毛利贡献",
  "亿元", derived(lambda c: _total_only(c, "total_swap_increment_value_yi")), "none")
R("param", "↳ 运营线：企业价值 EV（亿）", "swap.enterprise_value_yi",
  "= 可交付EBITDA × EV/EBITDA 倍数",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "enterprise_value_yi")), "sum")
R("param", "↳ 运营线：宁德归属价值（亿）", "swap.catl_attributable_value_yi",
  "＝ 项目股权价值 × 建站持股比例",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "catl_value_yi")), "sum")
R("param", "↳ EV/EBITDA 倍数", "finance.swap_ev_ebitda",
  "估值倍数中枢",
  "倍", global_val("finance.swap_ev_ebitda"), "global")
R("param", "↳ 制造线：换电锁定毛利贡献（亿）",
  "ledger.manufacturing_swap_locked_volume_effect_value_yi",
  "有换电 vs 无换电的制造端净利差 × 制造PE",
  "亿元", derived(lambda c: _total_only(c, "manufacturing_swap_locked_volume_effect_value_yi")), "none")
R("param", "↳ 制造线：净利率差效应（亿）",
  "ledger.manufacturing_swap_margin_effect_value_yi",
  "有换电净利率 − 无换电净利率，三档 0/1.0/2.5pct",
  "亿元", derived(lambda c: _total_only(c, "manufacturing_swap_margin_effect_value_yi")), "none")
R("param", "↳ 集团市值（亿）", "financial_2026e.group_market_cap_ah_yi",
  "A+H 总市值（估值的分母）",
  "亿元", global_val("financial_2026e.group_market_cap_ah_yi"), "global")
R("main", "增量价值 / 集团市值", "ledger.attributable_swap_value_to_current_group_market_cap",
  "= 换电增量价值 ÷ 集团市值（决策的核心读数）",
  "%", derived(lambda c: _total_only(
      c, "attributable_swap_value_to_current_group_market_cap")), "none")
R("param", "↳ 宁德初始权益出资（亿）", "swap.catl_initial_equity_investment_yi",
  "= 初装CAPEX × 股权比例 × CATL 权益比例",
  "亿元", derived(lambda c: c.alloc_pool(c.snap.swap_business.pool_operations,
                                         "catl_initial_equity_yi")), "sum")
R("param", "↳ 回收期（年）", "swap.catl_initial_payback_years",
  "= 宁德初始出资 ÷ 宁德年可分现金",
  "年", derived(lambda c: _payback(c)), "wavg")
R("param", "↳ 决策阈值：安全边际下限", "decision_thresholds.min_forward_to_required_ebitda",
  "低于此值即判定不达标",
  "倍", global_val("decision_thresholds.min_forward_to_required_ebitda"), "global")


# ---------------------------------------------------------------- 叶状基础假设节点：计算链留白
# 这些行已是「最基础假设」，取值依据统一由「信源」列给出（FINAL_SRC 含依据+链接），
# 故计算链(公式)列留白，避免写死具体数值、随参数调整而失同步。
_LEAF_BLANK = {
    "日均里程（km）", "背电量（kWh）", "电耗（kWh/km）", "可用能量系数（补能比例）",
    "年运营天数", "单站规划能力", "单站投资（万元）", "单站库存块数", "单块带电量（kWh）",
    "电池价格（元/kWh）", "CRF（资本回收系数）", "WACC", "债务比例",
    "度电服务费（元/kWh）", "度电租金（元/kWh·年）", "软件调度（亿）",
    "保险＋池维护＋仓储（亿）", "EV/EBITDA 倍数", "集团市值（亿）",
    "决策阈值：安全边际下限", "制造线：净利率差效应（亿）",
}
for _r in ROWS:
    if _r["name"].lstrip("↳ ").strip() in _LEAF_BLANK:
        _r["formula"] = ""


# ---------------------------------------------------------------- 辅助函数
def _operating_stocks(c: Ctx) -> dict[str, float]:
    """复刻 scale._operating_stocks：taxi/ridehail 保有量由营运总里程池反解。"""
    d = c.cfg["operating_demand"]
    robotaxi_km = d["robotaxi_fleet_wan"] * d["robotaxi_daily_km"] * d["robotaxi_days"] / 1e4
    human_stock = (d["pool_2030_yi_km"] - robotaxi_km) / (
        d["human_daily_km"] * d["human_days"] / 1e4
    )
    return {"taxi": d["taxi_stock_wan"], "ridehail": human_stock - d["taxi_stock_wan"]}


def _stock_of(c: Ctx, v: str) -> float | None:
    veh = c.cfg["vehicles"][v]
    if "stock_source" in veh:
        return _operating_stocks(c).get(veh["stock_source"])
    return veh.get("stock_wan")


def _vehicle_base(c: Ctx) -> dict:
    """车辆基数：保有量口径取保有量；净增口径取 2026–2030 逐年净增之和。"""
    out = {}
    for v in ALL_VEHICLES:
        veh = c.cfg["vehicles"][v]
        if "annual_net_additions_wan" in veh:
            out[v] = sum(veh["annual_net_additions_wan"])
        else:
            out[v] = _stock_of(c, v)
    return out


def _annual_flow(c: Ctx) -> dict:
    """年新增电动车辆（万辆/年）：进入换电漏斗前的流量（末年值）。"""
    return _annual_ev_dict(c, -1)


def _annual_ev_dict(c: Ctx, yidx: int) -> dict:
    """某年各车型进入电动漏斗的基础增量（万辆/年），与模型 _annual_ev_cfg 一致。

    - 营运车：保有量 ÷ 更新周期 × NEV渗透率[y] × 纯电占比
    - 私家/Robotaxi：净增[y] × 纯电占比（净增口径）
    """
    cfg = c.cfg
    years = cfg["construction"]["years"]
    yi = yidx if yidx >= 0 else len(years) - 1
    stocks = _operating_stocks_cfg(cfg)
    out = {}
    for v in ALL_VEHICLES:
        veh = cfg["vehicles"][v]
        pure = veh.get("pure_electric_share", 1.0)
        if "annual_net_additions_wan" in veh:
            out[v] = veh["annual_net_additions_wan"][yi] * pure
        elif "nev_rates" in veh:
            st = stocks[veh["stock_source"]] if "stock_source" in veh else veh["stock_wan"]
            out[v] = st / veh["replacement_cycle_years"] * veh["nev_rates"][yi] * pure
        else:
            out[v] = None
    return out


def _station_capex(c: Ctx) -> dict:
    """站体 CAPEX（亿元）= 站数 × 单站投资(万元) ÷ 1e4，按池分摊到车型。"""
    out = {k: 0.0 for k in ALL_VEHICLES}
    for pool, n in c.snap.scale.target_station_demand.items():
        val = n * c.cfg["stations"][pool]["station_body_capex_wan"] / 1e4
        for (p, v), w in c.pool_share.items():
            if p == pool:
                out[v] += val * w
    return out


def _battery_capex(c: Ctx) -> dict:
    """电池初装 CAPEX（亿元）= 初装合计 − 站体CAPEX（保证与模型口径完全加总一致）。"""
    total = _capex_by_pool_alloc(c, "total_initial_capex_by_pool")
    station = _station_capex(c)
    return {k: total[k] - station[k] for k in ALL_VEHICLES}


def _swap_total(c: Ctx, field: str) -> dict:
    """仅全网口径存在的量（模型不按车型拆），只进总计列。"""
    return {"__total__": getattr(c.snap.swap_business, field)}


def _wavg_cons(c: Ctx, v: str) -> float:
    rs = c.rows_for(v)
    tot = sum(r.catl_swap_vehicles_wan for r in rs)
    if tot <= 0:
        return 0.0
    return sum(r.catl_swap_vehicles_wan * _cons_of(c, r) for r in rs) / tot


def _cons_of(c: Ctx, row) -> float:
    """row 的电耗：场景电耗，无则车型电耗。"""
    for s in c.cfg["vehicles"][row.vehicle_key].get("scenes", []):
        if s["name"] == row.scene:
            return s.get("energy_consumption_kwh_km",
                         c.cfg["vehicles"][row.vehicle_key].get("energy_consumption_kwh_km", 0.0))
    return c.cfg["vehicles"][row.vehicle_key].get("energy_consumption_kwh_km", 0.0)


def _phys(c: Ctx) -> dict:
    out = {}
    for v in ALL_VEHICLES:
        rs = c.rows_for(v)
        pools = sorted({r.battery_pool for r in rs})
        tot = sum(r.catl_swap_vehicles_wan for r in rs)
        if not pools or tot <= 0:
            out[v] = None
            continue
        val = 0.0
        for p in pools:
            w = sum(r.catl_swap_vehicles_wan for r in rs if r.battery_pool == p)
            val += c.snap.scale.station_capacity_diagnostics[p]["physical_limit"] * w
        out[v] = val / tot
    return out


def _station_param(field: str):
    def f(c: Ctx) -> dict:
        out = {}
        for v in ALL_VEHICLES:
            rs = c.rows_for(v)
            pools = sorted({r.battery_pool for r in rs})
            tot = sum(r.catl_swap_vehicles_wan for r in rs)
            if not pools or tot <= 0:
                out[v] = None
                continue
            val = 0.0
            for p in pools:
                w = sum(r.catl_swap_vehicles_wan for r in rs if r.battery_pool == p)
                val += c.cfg["stations"][p][field] * w
            out[v] = val / tot
        return out
    return f


def _station_gwh(c: Ctx, v: str) -> float:
    """站内周转电池 GWh：按该车型的站数份额分摊。"""
    st = c.alloc_stations()
    rs = c.rows_for(v)
    pools = sorted({r.battery_pool for r in rs})
    tot = sum(r.catl_swap_vehicles_wan for r in rs)
    if not pools or tot <= 0:
        return 0.0
    out = 0.0
    for p in pools:
        share = sum(r.catl_swap_vehicles_wan for r in rs if r.battery_pool == p) / tot
        pool_stations = c.snap.scale.target_station_demand[p] * share
        s = c.cfg["stations"][p]
        out += pool_stations * s["inventory_blocks"] * s["block_kwh"] / 1e6
    return out


def _pool_life_alloc(c: Ctx) -> dict:
    out = {}
    for v in ALL_VEHICLES:
        rs = c.rows_for(v)
        pools = sorted({r.battery_pool for r in rs})
        tot = sum(r.catl_swap_vehicles_wan for r in rs)
        if not pools or tot <= 0:
            out[v] = None
            continue
        val = 0.0
        for p in pools:
            w = sum(r.catl_swap_vehicles_wan for r in rs if r.battery_pool == p)
            val += c.snap.scale.battery_pool_life_years[p] * w
        out[v] = val / tot
    return out


def _capex_by_pool_alloc(c: Ctx, field: str) -> dict:
    d = getattr(c.snap.capex, field, {})
    out = {k: 0.0 for k in ALL_VEHICLES}
    for pool, val in d.items():
        for (p, v), w in c.pool_share.items():
            if p == pool:
                out[v] += val * w
    return out


_capex_total_alloc = _capex_by_pool_alloc


def _capex_alloc(c: Ctx, field: str) -> dict:
    return c.alloc_pool(c.snap.swap_business.pool_operations, field)


def _three_costs(c: Ctx) -> dict:
    a = c.alloc_pool(c.snap.swap_business.pool_operations, "insurance_yi")
    b = c.alloc_pool(c.snap.swap_business.pool_operations, "pooling_maintenance_yi")
    d = c.alloc_pool(c.snap.swap_business.pool_operations, "warehouse_logistics_yi")
    return {k: a[k] + b[k] + d[k] for k in ALL_VEHICLES}


def _ratio(c: Ctx, num: str, den: str) -> dict:
    a = c.alloc_pool(c.snap.swap_business.pool_operations, num)
    b = c.alloc_pool(c.snap.swap_business.pool_operations, den)
    return {k: (a[k] / b[k] if b[k] else None) for k in ALL_VEHICLES}


def _margin(c: Ctx) -> dict:
    a = c.alloc_pool(c.snap.swap_business.pool_operations, "ebitda_yi")
    b = c.alloc_pool(c.snap.swap_business.pool_operations, "required_fcff_yi")
    return {k: (a[k] / b[k] if b[k] else None) for k in ALL_VEHICLES}


def _payback(c: Ctx) -> dict:
    a = c.alloc_pool(c.snap.swap_business.pool_operations, "catl_initial_equity_yi")
    b = c.alloc_pool(c.snap.swap_business.pool_operations, "catl_minimum_distributable_yi")
    return {k: (a[k] / b[k] if b[k] else None) for k in ALL_VEHICLES}


def _total_only(c: Ctx, field: str) -> dict:
    """仅总计列有意义的量（集团层面，不可按车型拆）。"""
    val = getattr(c.snap.ledger, field, None)
    return {"__total__": val}


# ---------------------------------------------------------------- 聚合到列
def aggregate(values: dict, agg: str, ctx: Ctx) -> dict:
    """{车型: 值} → {分组: 值}。"""
    out = {}
    for gname, members in GROUPS:
        if agg == "global":
            vals = [values.get(v) for v in ALL_VEHICLES if values.get(v) is not None]
            out[gname] = vals[0] if vals else None
            continue
        if "__total__" in values:
            out[gname] = values["__total__"] if gname == "总计" else None
            continue
        vs = [values.get(v) for v in members]
        vs = [v for v in vs if v is not None]
        if not vs:
            out[gname] = None
        elif agg == "sum":
            out[gname] = sum(vs)
        elif agg == "solo":
            # 分场景明细：仅当该分组恰好由「唯一一个有值的车型」构成时才显示，
            # 否则（营运合计/总计等含多车型）留空，避免把单车型的场景值误冒成汇总。
            present = {v for v in members if values.get(v) is not None}
            out[gname] = (values[next(iter(present))]
                          if present == set(members) and len(members) == 1 else None)
        else:  # wavg
            w = {v: ctx.stock.get(v, 0.0) for v in members}
            tw = sum(w[v] for v in members if values.get(v) is not None)
            out[gname] = (sum(values[v] * w[v] for v in members
                              if values.get(v) is not None) / tw) if tw else None
    return out


def build_rows() -> list[dict]:
    ctxs = {name: build_ctx(s) for name, s in SCENARIOS}
    # 自校验
    errors = []
    for name, s in SCENARIOS:
        for row in ROWS:
            ck = row.get("check")
            if ck and not ck(ctxs[name]):
                errors.append(f"[{name}] 自校验失败：{row['name']}")
    if errors:
        raise SystemExit("自校验未通过：\n" + "\n".join(errors))

    out = []
    base_cfg = ctxs["中性"].cfg  # 配置对各情景相同，供可调用公式取真实数值
    for row in ROWS:
        if row["kind"] == "sec":
            out.append({"kind": "sec", "name": row["name"]})
            continue
        per_scen = {}
        for name, _ in SCENARIOS:
            if row.get("fetch") is None:
                vals = {v: None for v in ALL_VEHICLES}
            else:
                vals = row["fetch"](ctxs[name])
            per_scen[name] = aggregate(vals, row["agg"], ctxs[name])
        # 参数行名带 "↳ " 缩进前缀，查信源前先去掉
        plain_name = row["name"].lstrip("↳ ").strip()
        # 计算链允许是「由 config 实跑生成真实推导式」的可调用对象
        ftext = row["formula"](base_cfg) if callable(row["formula"]) else row["formula"]
        # 行级 src 优先（叶状基础假设可自带 取值依据+链接）；否则走全局 src_for
        _s = row.get("src")
        if isinstance(_s, tuple):
            src_text, src_url = _s
        elif _s:
            src_text, src_url = _s, None
        else:
            src_text, src_url = src_for(plain_name)
        out.append({
            "kind": row["kind"], "name": row["name"], "eng": row["eng"],
            "formula": ftext, "unit": row["unit"],
            "vals": per_scen, "src": src_text, "url": src_url,
        })
    return out


# ---------------------------------------------------------------- Excel 导出
SCEN = [s for s, _ in SCENARIOS]
GROUP_NAMES = [g for g, _ in GROUPS]

BLOCK_FILLS = ["E2EFDA", "DDEBF7", "FFF2CC", "FCE4D6", "E4DFEC", "D0CECE"]
SECTION_FILL = "BDD7EE"


def _num_fmt(unit: str) -> str:
    if unit == "%":
        return "0.0%"
    if unit in ("倍", "kWh/km", "次/天"):
        return "0.00"
    return "#,##0.0"


def export_excel(rows: list[dict], path: Path, cfg: dict, funnel: dict) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "全链条主表"

    ncols = 5 + len(GROUP_NAMES) * len(SCEN) + 1
    head_font = Font(bold=True, color="FFFFFF", size=10)
    head_fill = PatternFill("solid", fgColor="1F4E78")
    wrap = Alignment(vertical="top", wrap_text=True)
    center = Alignment(horizontal="center", vertical="center")
    right = Alignment(horizontal="right", vertical="center")
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)

    ws.cell(row=1, column=1,
            value="「从假设到决策」全链条主表 —— 由 configs/base.toml + src/ 实跑生成，公式自校验").font = \
        Font(bold=True, size=13, color="1F4E78")
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=ncols)
    notes = [
        "列的排布：4 类车型 + 营运合计 + 总计，各 3 情景（悲观/中性/乐观）。中性档 == 模型基线。",
        "行的排布：先主项、再把依赖参数逐层展开（↳ 为上一主项的输入参数），一直拆到 config 里的根本假设。",
        "口径：choco25 电池池由乘用营运与私家共享，池级指标（收入/成本/站数等）按换电量份额分摊到车型，已在计算链注明。",
        "强度量（渗透率/里程/电耗/频次等）按「当情景换电车辆」加权；故总计列会随车型结构变化——例如乐观情景私家车占比"
        "上升会拉低全网加权换电渗透率，这是口径定义而非错误。",
        "可用续航=背电量×补能比例÷电耗、频次=里程÷可用续航；模型先按场景算、再加权，本表是跨场景加权后的算术均值，"
        "故「频次」未必精确等于「里程÷可用续航」（加权次序不同），但量级一致。",
        "数值全部来自模型实跑，非手抄；公式重算与模型值不符时脚本直接报错（自校验），模型改版重跑即得新表。",
        "分场景明细行（如「重卡·短途 场景权重」）只在所属车型列显示数值，营运合计/总计列留空，避免把单车型的场景值误当汇总。",
        "逐年展开仅在值真正逐年变化时才展开行（NEV渗透率、净增）；场景结构逐年恒定者只保留分场景行（如换电渗透/CATL份额），不重复 3×5 行。",
    ]
    r = 2
    for n in notes:
        ws.cell(row=r, column=1, value=n).font = Font(italic=True, size=9, color="595959")
        ws.merge_cells(start_row=r, start_column=1, end_row=r, end_column=ncols)
        r += 1

    # 分组表头（车型，跨 3 列合并）
    gr = r + 1
    ws.cell(row=gr, column=5, value="单位")
    col = 6
    for g in GROUP_NAMES:
        c = ws.cell(row=gr, column=col, value=g)
        c.font = head_font
        c.fill = head_fill
        c.alignment = center
        ws.merge_cells(start_row=gr, start_column=col, end_row=gr, end_column=col + 2)
        for k in range(3):
            ws.cell(row=gr, column=col + k).fill = head_fill
            ws.cell(row=gr, column=col + k).border = border
        col += 3
    for cc in range(1, 6):
        cell = ws.cell(row=gr, column=cc)
        cell.font = head_font
        cell.fill = head_fill
        cell.alignment = center
        cell.border = border
    s_cell = ws.cell(row=gr, column=col, value="信源（最终可用版本·点击可开链接）")
    s_cell.font = head_font
    s_cell.fill = head_fill
    s_cell.alignment = center
    s_cell.border = border

    # 子表头（情景）
    hr = gr + 1
    for i, h in enumerate(["编号", "指标（中文）", "英文参数名 / 代码路径",
                           "计算链（真实公式）", "单位"], 1):
        c = ws.cell(row=hr, column=i, value=h)
        c.font = head_font
        c.fill = head_fill
        c.alignment = center
        c.border = border
    col = 6
    for _ in GROUP_NAMES:
        for s in SCEN:
            c = ws.cell(row=hr, column=col, value=s)
            c.font = head_font
            c.fill = head_fill
            c.alignment = center
            c.border = border
            col += 1
    c = ws.cell(row=hr, column=col, value="信源（最终可用）")
    c.font = head_font
    c.fill = head_fill
    c.alignment = center
    c.border = border
    ws.freeze_panes = ws.cell(row=hr + 1, column=6)

    # 数据
    r = hr + 1
    block_i = -1
    fill = None
    seq = 0
    for row in rows:
        if row["kind"] == "sec":
            block_i += 1
            fill = PatternFill("solid", fgColor=BLOCK_FILLS[block_i % len(BLOCK_FILLS)])
            c = ws.cell(row=r, column=2, value=row["name"])
            c.font = Font(bold=True, size=11, color="1F4E78")
            for cc in range(2, ncols + 1):
                ws.cell(row=r, column=cc).fill = PatternFill("solid", fgColor=SECTION_FILL)
            ws.cell(row=r, column=2).fill = PatternFill("solid", fgColor=SECTION_FILL)
            r += 1
            continue
        is_main = row["kind"] == "main"
        if is_main:
            seq += 1
            ws.cell(row=r, column=1, value=seq).alignment = center
            ws.cell(row=r, column=1).font = Font(bold=True)
        for i, val in enumerate([row["name"], row["eng"], row["formula"], row["unit"]], 2):
            c = ws.cell(row=r, column=i, value=val)
            c.alignment = wrap
            c.font = Font(bold=is_main, size=10 if is_main else 9)
            if is_main and i == 2:
                c.fill = fill
            c.border = border
        fmt = _num_fmt(row["unit"])
        col = 6
        for g in GROUP_NAMES:
            for s in SCEN:
                v = row["vals"].get(s, {}).get(g)
                c = ws.cell(row=r, column=col)
                if v is None:
                    c.value = "—"
                    c.alignment = center
                else:
                    c.value = v
                    c.number_format = fmt
                    c.alignment = right
                if is_main:
                    c.fill = fill
                    c.font = Font(bold=True, size=10)
                c.border = border
                col += 1
        sc = ws.cell(row=r, column=col, value=row["src"] or "—")
        sc.alignment = wrap
        sc.font = Font(size=8, color="0563C1" if row["url"] else "595959")
        if row["url"]:
            sc.hyperlink = row["url"]
        sc.border = border
        # 多行公式/信源需撑高行高，否则被裁切
        def _est_lines(text: str, per_line: int) -> int:
            return sum(max(1, (len(seg) // per_line) + 1) for seg in str(text).split("\n"))
        lines_f = _est_lines(row["formula"], 26)   # 计算链列宽约 52，约 26 中文字/行
        lines_s = _est_lines(row["src"] or "", 30)  # 信源列宽约 46
        lines = max(lines_f, lines_s, 1)
        ws.row_dimensions[r].height = max(16, min(lines * 14 + 4, 150))
        r += 1

    widths = [6, 34, 34, 52, 8] + [11] * (len(GROUP_NAMES) * len(SCEN)) + [46]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.row_dimensions[1].height = 20

    # 信源索引
    ws2 = wb.create_sheet("信源索引")
    ws2.cell(row=1, column=1, value="参数 → 信源（来自 audit/信源审计台账.md）").font = \
        Font(bold=True, size=12, color="1F4E78")
    ws2.merge_cells("A1:D1")
    for i, h in enumerate(["指标（中文）", "英文参数名", "信源（最终可用版本）", "链接"], 1):
        c = ws2.cell(row=2, column=i, value=h)
        c.font = head_font
        c.fill = head_fill
        c.alignment = center
    rr = 3
    for row in rows:
        if row["kind"] == "sec":
            continue
        ws2.cell(row=rr, column=1, value=row["name"]).alignment = wrap
        ws2.cell(row=rr, column=2, value=row["eng"]).alignment = wrap
        ws2.cell(row=rr, column=3, value=row["src"] or "—").alignment = wrap
        lc = ws2.cell(row=rr, column=4, value=row["url"] or "")
        lc.alignment = wrap
        if row["url"]:
            lc.hyperlink = row["url"]
            lc.font = Font(color="0563C1", underline="single", size=9)
        rr += 1
    for col, w in zip("ABCD", (34, 34, 70, 60)):
        ws2.column_dimensions[col].width = w

    path.parent.mkdir(parents=True, exist_ok=True)
    export_funnel_sheet(wb, cfg, funnel)
    wb.save(path)


def export_funnel_sheet(wb, cfg: dict, funnel: dict) -> None:
    """换电车辆漏斗「逐车×场景×年」明细 sheet：公式用参数名、数值由 config 现算。"""
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    ws = wb.create_sheet("换电车辆漏斗逐年明细")
    years = cfg["construction"]["years"]
    scen_names = [s for s, _ in SCENARIOS]
    head_font = Font(bold=True, color="FFFFFF", size=10)
    head_fill = PatternFill("solid", fgColor="1F4E78")
    wrap = Alignment(vertical="top", wrap_text=True)
    center = Alignment(horizontal="center", vertical="center")
    right = Alignment(horizontal="right", vertical="center")
    thin = Side(style="thin", color="D9D9D9")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    r = 1

    def title(text, size=12):
        nonlocal r
        c = ws.cell(r, 1, text)
        c.font = Font(bold=True, size=size, color="1F4E78")
        r += 1

    def put(row_vals, fmts=None, bold=False, header=False):
        nonlocal r
        for ci, v in enumerate(row_vals, 1):
            cell = ws.cell(r, ci, v)
            cell.border = border
            if header:
                cell.font = head_font
                cell.fill = head_fill
                cell.alignment = center
            else:
                cell.font = Font(bold=bold, size=9)
                if isinstance(v, (int, float)):
                    cell.number_format = (fmts[ci - 1] if fmts else "#,##0.0")
                    cell.alignment = right
                else:
                    cell.alignment = wrap
        r += 1

    # ---- A. 公式（参数名） ----
    title("A. 换电车辆计算链（参数名写法；数值见以下各表）", 13)
    for line in FUNNEL_FORMULA.split("\n"):
        ws.cell(r, 1, line).font = Font(size=9, color="404040")
        ws.cell(r, 1).alignment = wrap
        r += 1
    r += 1

    # ---- B. 当年电动新增 base_add（万辆/年） ----
    title("B. 当年电动新增 base_add（万辆/年）＝进入电动漏斗的当年新增（逐年不同）")
    put(["车型"] + [str(y) for y in years], header=True)
    stocks = _operating_stocks_cfg(cfg)
    for vkey, veh in cfg["vehicles"].items():
        row = [veh["label"]] + [round(_annual_ev_cfg(veh, i, stocks), 1)
                                for i in range(len(years))]
        put(row, fmts=[""] + ["#,##0.0"] * len(years))
    r += 1

    # ---- B2. NEV 逐年 / 净增 ----
    title("B2. NEV渗透率 nev_rates[y]（营运车·逐年）  ／  净增 annual_net_additions_wan[y]（私家·Robotaxi）")
    put(["车型"] + [str(y) for y in years], header=True)
    for vkey, veh in cfg["vehicles"].items():
        if "nev_rates" in veh:
            row = [veh["label"]] + [f"{x * 100:.0f}%" for x in veh["nev_rates"]]
        else:
            row = [veh["label"]] + [f"{x:.0f}" for x in veh["annual_net_additions_wan"]]
        put(row)
    r += 1

    # ---- C. 分场景结构（中性） ----
    title("C. 分场景结构（中性情景；换电渗透/CATL份额 模型内逐年恒定，不随年变）")
    put(["车型", "场景", "场景权重", "换电渗透率", "CATL份额"], header=True)
    det = funnel["中性"]
    for d in det:
        put([d["label"], d["scene"], round(d["weight"], 3),
             f"{d['swap_pen'] * 100:.0f}%", f"{d['catl_share'] * 100:.0f}%"],
            fmts=["", "", "0.000", "0%", "0%"])
    r += 1

    # ---- D. 私家车三情景换电渗透 ----
    title("D. 私家车分价格带换电渗透率（三情景不同）＝ scenario_swap_penetration")
    table = cfg["vehicles"]["private"]["scenario_swap_penetration"]
    bands = cfg["vehicles"]["private"]["scenes"]
    priv_key = {nm: sc["private"] for nm, sc in SCENARIOS}  # 情景名→私家车档位键
    put(["价格带"] + scen_names, header=True)
    for s in bands:
        put([s["name"]] + [f"{table[priv_key[nm]][s['name']] * 100:.0f}%" for nm in scen_names])
    r += 1

    # ---- E. 进宁德换电车辆 逐年（中性） ----
    title("E. 进宁德换电车辆（万辆）逐年明细（中性情景）＝ Σ场景 catl_swap(v,s,y)")
    put(["车型", "场景"] + [str(y) for y in years] + ["终局合计"], header=True)
    agg = {}
    for d in det:
        k = (d["label"], d["scene"])
        agg.setdefault(k, [0.0] * len(years))
        agg[k][years.index(d["year"])] = d["catl_swap"]
    for k in agg:
        vals = agg[k]
        put([k[0], k[1]] + [round(x, 1) for x in vals] + [round(sum(vals), 1)],
            fmts=["", ""] + ["#,##0.0"] * len(years) + ["#,##0.0"])
    r += 1

    # ---- F. 逐年累计终局（三情景） ----
    title("F. 逐年累计终局换电车辆（万辆）· 三情景（仅私家车因三档渗透而不同）")
    put(["车型"] + [str(y) for y in years] + scen_names, header=True)
    for vkey, veh in cfg["vehicles"].items():
        cumv = {sc: [] for sc in scen_names}
        term = {sc: 0.0 for sc in scen_names}
        for sc in scen_names:
            run = 0.0
            for d in funnel[sc]:
                if d["vkey"] != vkey:
                    continue
                run += d["catl_swap"]
                cumv[sc].append(run)
                term[sc] += d["catl_swap"]
        row = ([veh["label"]]
               + [round(cumv["中性"][i], 1) for i in range(len(years))]
               + [round(term[sc], 1) for sc in scen_names])
        put(row, fmts=[""] + ["#,##0.0"] * len(years) + ["#,##0.0"] * len(scen_names))
    tot = {sc: sum(d["catl_swap"] for d in funnel[sc]) for sc in scen_names}
    put(["总计"] + [""] * len(years) + [round(tot[sc], 1) for sc in scen_names],
        fmts=[""] * (1 + len(years)) + ["#,##0.0"] * len(scen_names), bold=True)

    for i in range(1, 12):
        ws.column_dimensions[get_column_letter(i)].width = 14
    ws.freeze_panes = "A2"


def main() -> None:
    rows = build_rows()
    cfg = config_loader.load_config()
    funnel = {name: _funnel_detail(cfg, s["private"]) for name, s in SCENARIOS}
    out = ROOT / "outputs" / "换电全链条表_v1.xlsx"
    export_excel(rows, out, cfg, funnel)
    n_main = sum(1 for x in rows if x["kind"] == "main")
    n_param = sum(1 for x in rows if x["kind"] == "param")
    n_src = sum(1 for x in rows if x.get("url"))
    print(f"OK -> {out}")
    print(f"主项 {n_main} 行 / 参数 {n_param} 行 / 参数行 {rows and len(rows)} 总行 / 带链接信源 {n_src}")


if __name__ == "__main__":
    main()

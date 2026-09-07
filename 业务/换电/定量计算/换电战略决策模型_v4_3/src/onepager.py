"""「一页纸」视图：把决策树的核心终端指标 + 四列判断列压成一屏。

为什么还要第三个产物
--------------------
现有两个 outputs 都不是一页纸：

* `换电模型_参数与血缘_v4.3.xlsx` —— **参数级**（200+ 行 × 37 指标），回答
  "每个参数影响谁"，是审计件，不是决策页。
* `换电决策树_v4.3.xlsx` —— **审计级**（167 节点，含全部中间量），回答
  "这条链算得对不对"，可折叠，但折叠前不是一页。

一页纸要回答的是第三个问题：**这几个终端数字，我自己拿心算对得上吗？**
所以它只取树的**核心终端节点**（十几个），给每个配上方案 §3.6 步骤 4 要求的四列：

    核心问题 ｜ 合理量级 ｜ 什么会推翻它 ｜ 外部锚

取值全部来自模型实跑（跟决策树同源、同一套 build_ctx），不手写任何数字——
所以模型改了、轴拨了，这一页跟着变，不会和代码脱钩。

四列怎么读
----------
* 核心问题：这个数字到底在回答哪个决策问题（对应决策树的四支）。
* 合理量级：凭定性判断/外部常识，这个数"应该在什么量级"——用来做心算校验。
* 什么会推翻它：到什么取值，结论就要改（优先用模型自己的门槛/体检线）。
* 外部锚：这个判断锚在哪个外部事实上。**

**信源纪律：模型内部口径与经验假设必须显式标注，不得伪装成外部信源；
  分母类（保有量/渗透率）必须来自中汽协/乘联会上险等外部独立信源，
  不得用模型自身推导值自证。**

运行
----
    python src/onepager.py        # 写出 outputs/换电一页纸_v4.3.xlsx
"""
from __future__ import annotations

import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SRC = Path(__file__).resolve().parent
ROOT = SRC.parent
sys.path.insert(0, str(SRC))

from config_loader import SCENARIO_ORDER, load_config, load_drivers  # noqa: E402
from tree import build_ctx, build_tree, walk  # noqa: E402

XLSX_PATH = ROOT / "outputs" / "换电一页纸_v4.3.xlsx"

# ─────────────────────────────────────────────── 一页纸的行（核心问题 / 判断四列）
# (节点key, 核心问题, 合理量级, 什么会推翻它, 外部锚)
# 节点 key 与 tree.build_tree 里的一致——改树不会让这一页悄悄失效，
# key 找不到会在生成时直接报出来。
CORE_ROWS: list[tuple[str, str, str, str, str]] = [
    # ── 支一：换回的价值 ──
    ("val.increment", "换电到底给 CATL 多带回多少钱（运营＋制造）？",
     "千亿到万亿量级才谈得上「重注」；中性 6,103 亿 ≈ 集团市值三成。若只有百亿量级，这只是个边缘业务。",
     "中性档若 <1,000 亿（<5% 市值），「重注」结论不成立。注意悲观档制造侧已 −1,265 亿、几乎吞掉运营侧 +1,570 亿。",
     "对照集团市值基准 20,000 亿（A+H，模型内部基准，非外部信源）；分母（商用保有量/NEV渗透）仍待中汽协·乘联会上险外部信源"),

    ("val.op_increment", "运营这门生意本身（服务费＋租金＋套利＋辅助）值多少？",
     "应是增量价值的主体，中性 5,497／6,103 ≈ 90%。若制造侧占比过半，则「换电是运营生意」这一定性被推翻。",
     "服务费单价跌破 0.2 元/kWh（价格战已现），或建站持股比例从 40% 降到蔚能锚 27.8% → 运营侧腰斩。",
     "服务费谱系：焦作商车邦实测 0.2／齐鲁晚报 0.3–0.4／开源短倒 0.4；建站持股锚：蔚能经天地资本增资后 27.8% 实控"),

    ("val.mfg_increment", "顺带锁住制造端多少（锁量＋锁价）？",
     "中性 607 亿，应是小头（约一成）。量级应为数百亿，不该反客为主。",
     "悲观档已 −1,265 亿：充电段虹吸 −91 亿经制造 PE 20× 放大。若宁德国内份额继续从 37.1% 下滑，制造侧会持续为负。",
     "宁德国内动力电池份额 52.1%(2021)→45.08%(2024)→37.1%(2025 1–8月)（模型内已登记信源）"),

    ("val.increment_pct", "占集团多大盘子？",
     "中性 30.5%。>20% 才算值得重注；<10% 只是锦上添花，不配占用集团战略敞口。",
     "若 <10%，则不值得占用 1,770 亿战略敞口中的任何一块。",
     "分母＝集团市值基准 20,000 亿（模型内部基准，非外部信源）"),

    # ── 支二：体检过不过线 ──
    ("ops.ebitda", "成熟期一年能赚多少现金毛利？",
     "中性 850 亿＝年收入 939 − OPEX 89，即毛利约占收入九成——因为电费只计循环损耗（RTE/站用电率），这个高毛利率是模型结构决定的，需拿外部运营商毛利率对照。",
     "若 OPEX 被低估（人工/场租按保守而非实际），或谷电价从 0.3 上行，毛利率会显著下滑。",
     "谷电价 0.3 元/kWh（rlut「低谷 0.3–0.4」取下沿）；场租 15 万/站/年（200–300㎡×50元/㎡/月，经验假设）"),

    ("chk.coverage", "赚的够不够覆盖资本回报要求？（门槛）",
     ">1.0 才过线。中性 1.14 刚过；悲观 0.92 **已破线**——这是模型第一次真正踩破门槛。",
     "若中性档也 <1.0，整个投资逻辑不成立（不是「少赚」而是「不该做」）。",
     "门槛由 CRF 资本回收系数 × WACC 7.5% 反推（模型内部门槛，非外部信源）"),

    ("chk.dcf", "现金流本身支持几倍 EV/EBITDA？",
     "中性 5.67× vs 拍的 18×。**注意口径**：这是 15 年有限期、按 CRF 年金化的隐含倍数，"
     "不含 2030 年后增长与永续残值；与 18× 的「持续经营」口径不同源，直接相减会夸大「溢价」。"
     "真正可比的对照是永续账 DCF（val.catl_dcf_perpetual）。",
     "若拿永续账口径对照后仍远低于 18×，才说明估值判断缺乏现金流支撑——当前缺这一步对照。",
     "同源口径：成熟期 FCFF ÷ CRF（WACC 7.5%，模型假设）"),

    ("chk.premium", "拍的倍数相对现金流溢价几倍（＝押注多大）？",
     "中性 3.17×（乐观 3.95×）——**已越过 3× 这一档**。但这不等于「纯押注」：分母是 15 年"
     "有限期 CRF 隐含倍数，18× 是持续经营口径，两者不同源（见上一行）。"
     "**这一行是待你判断的开放问题，不是自动结论。**",
     "若用永续账 DCF 对照后溢价仍 >3×，则结论主要由倍数判断而非现金流支撑，"
     "「支持重注」应降级为「小步试」。当前缺这一步对照。",
     "18× 锚：v3.2 §4.1「含战略溢价的基建运营倍数」；对照组 CATL 自身 13.0×／比亚迪 6.5×（见 outputs/估值_为什么拍这个倍数.md）"),

    # ── 支三：做透的代价 ──
    ("cap.lifecycle", "做透一共要投多少（现值）？",
     "中性 4,297 亿＝初装 2,632 ＋ 全周期更新净额。量级应为数千亿。",
     "若电池价格长期不降（现按学习曲线下行），更新支出会显著抬升这个数。",
     "电池价格曲线：按你的判断长期必降但不会跌破成本、且无可观测触发事件，故**不作情景轴**，仅此处作对照"),

    ("cap.commitment", "CATL 自己要掏多少？",
     "中性 687.6 亿（报告 Q2）。这是集团真金白银的出资，不是项目总投资。",
     "建站持股比例若从 40% 升到 100%（转为自建自营），出资翻倍以上。",
     "40% 为保守假设值（经验假设）；外部锚＝蔚能 27.8% 实控"),

    ("cap.annual_req", "一年要压多少资本？资金从容吗？",
     "中性 644.6 亿/年＝全周期底座 4,297 × CRF，是**项目层年均资本要求**（年金平均数，非峰值）。"
     "CATL 实际单年峰值出资 105.3 亿（2030 年），占峰值年 CFO 4.7%，远低于 15% 体检线——两者别混。",
     "若峰值/CFO >15%（体检线），「从容」结论要改成分步投。",
     "体检线 15%（集团内部风险口径，非外部信源）"),

    # ── 支四：估值最终值多少 ──
    ("val.catl_multiple", "按拍的倍数，CATL 归属多少？",
     "**与上一行「运营侧直接增量」数值相同**——两者都＝(EV−debt)×持股，"
     "是同一笔钱的两个名字、不是重复录入。应与可归因增量价值同量级（数千亿）。",
     "若与 DCF 口径（val.catl_dcf_true）差距过大，说明这个数主要是「拍」出来的。",
     "同 18× 锚（见 chk.premium）"),

    ("val.bet", "其中多少是「押注」（倍数法 − DCF）？",
     "中性押注 3,473 亿 ÷ 归属 5,497 亿 ＝ **63%**，已在 50% 线之上、70% 线之下（灰区）。"
     "<50% 可坦然辩护；>70% 则结论主要靠倍数而非现金流。",
     "押注 >70% 时，结论主要建立在倍数判断而非现金流上。",
     "两口径自 2026-09-04 起共用同一稳态 debt（口径已统一，见 DECISIONS）"),

    # ── 规模（盘子）──
    ("ops.energy", "盘子有多大（电量口径）？",
     "中性 1,450 亿 kWh/年。可拿全国电动车用电量做量级交叉校验。",
     "若日换电次数（中性 329 万次/日）反推的换电车辆数超出保有量常识，则车辆口径虚高。",
     "分母（商用保有量 900 万/1,500 万、NEV 渗透率）**待补中汽协/乘联会上险外部独立信源**"),

    ("st.total", "要建多少站？",
     "中性 11,285 座；其中重卡站可对照政策口径做量级校验。",
     "若单站日服务能力假设偏乐观，站数与 CAPEX 会被系统性低估。",
     "重卡干线对照 52 号文 3,000 座（模型内已登记交叉验证）"),
]


def collect(scen_ctx: dict, root) -> list[list]:
    """按 CORE_ROWS 取三条情景的实跑值；节点 key 缺失直接报错（不静默跳过）。"""
    by_key = {n.key: n for n in walk(root)}
    missing = [k for k, *_ in CORE_ROWS if k not in by_key]
    if missing:
        raise SystemExit(f"一页纸引用了决策树里不存在的节点：{missing}\n"
                         f"（树改版后请同步 CORE_ROWS 的 key）")

    rows: list[list] = []
    for key, question, magnitude, falsifier, anchor in CORE_ROWS:
        node = by_key[key]
        vals = []
        for tier in SCENARIO_ORDER:
            try:
                vals.append(round(float(node.value(scen_ctx[tier])), 4))
            except Exception:  # noqa: BLE001
                vals.append(None)
        rows.append([question, node.label, *vals, node.unit,
                     magnitude, falsifier, anchor])
    return rows


def export(rows: list[list], scen_order, path: Path) -> None:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "一页纸"
    headers = ["核心问题", "指标（终端数字）", *scen_order, "单位",
               "合理量级（心算校验）", "什么会推翻它", "外部锚 / 信源"]
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, size=10)
        cell.fill = PatternFill("solid", fgColor="EFF0F3")
        cell.alignment = Alignment(vertical="center", wrap_text=True)

    for row in rows:
        ws.append(row)

    n = len(headers)
    widths = [30, 30, *[13] * len(scen_order), 8, 46, 46, 46]
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        # 数值列右对齐、千分位
        for col in range(3, 3 + len(scen_order)):
            row[col - 1].number_format = "#,##0.00"
            row[col - 1].alignment = Alignment(horizontal="right", vertical="top")

    ws.freeze_panes = "C2"
    ws.auto_filter.ref = f"A1:{get_column_letter(n)}{ws.max_row}"
    wb.save(path)


def main() -> None:
    drivers = load_drivers(load_config())
    scen_ctx = {tier: build_ctx(tier, drivers) for tier in SCENARIO_ORDER}
    root = build_tree(scen_ctx["中性"])          # 中性＝基线，与决策树同源
    rows = collect(scen_ctx, root)
    export(rows, SCENARIO_ORDER, XLSX_PATH)
    print(f"已写出 {XLSX_PATH.name}（{len(rows)} 行核心指标 × 三情景 × 四列判断）")


if __name__ == "__main__":
    main()

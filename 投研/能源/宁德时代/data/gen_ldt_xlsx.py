# -*- coding: utf-8 -*-
"""把 换电db - LDT.csv 的逻辑转成带公式的 xlsx。
公式全部写成 Excel 公式字符串，Excel 打开即自动计算。
外部信源占位单元格留空/标注，由用户后续填入真实值。
"""
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

wb = Workbook()
ws = wb.active
ws.title = "轻卡换电测算"

# 样式
title_font = Font(bold=True, size=14)
hdr_font = Font(bold=True)
note_fill = PatternFill("solid", fgColor="FFF2CC")   # 黄：说明/外部信源
calc_fill = PatternFill("solid", fgColor="E2EFDA")   # 绿：公式计算
input_fill = PatternFill("solid", fgColor="DDEBF7")  # 蓝：手动输入
thin = Side(style="thin", color="BFBFBF")
border = Border(left=thin, right=thin, top=thin, bottom=thin)
wrap = Alignment(wrap_text=True, vertical="top")

# 表头
ws.append(["换电规模测算逻辑表（2026–2030，轻卡 LDT）"])
ws["A1"].font = title_font
ws.append(["数据项", "公式 / 计算逻辑", "单位", "数值", "数据来源 / 备注"])

# 用 rows 列表管理，便于互相引用单元格。结构: (item, formula_text, unit, value_or_formula, note, kind)
# kind: 'input' 手动输入, 'calc' 公式, 'note' 纯说明, 'hdr' 表头子项
rows = [
    ("总换电装机规模", "存量换电规模 + 增量换电规模", "万kWh", "=E5+E11", "=E5+E11 为公式", "calc"),
    ("总换电车辆规模", "LDT NEV存量车辆数 + LDT NEV增量车辆数", "万辆", "=E6+E14", "", "calc"),
    ("存量换电装机规模（2025年及之前已售车辆）", "单车带电量 × LDT NEV存量车辆数", "万kWh", 0, "见下一行结论", "calc"),
    ("▸ 存量换电装机规模（结论）", "2025年前换电轻卡尚未成规模上市，存量项视为0", "万kWh", 0,
     "依据：江淮巧克力换电轻卡2025/7才联调成功、2026/6发四款车型；中燃400余站2026/8开放。2025年前无成规模换电轻卡在售，存量换电装机≈0。与HDT不同——重卡换电早有运营(存量渗透率20%)，轻卡换电是从零起步的新增量", "note"),
    ("▸ 单车带电量(存量)", "(手动输入)", "kWh", 81, "巧克力换电版81度（江淮EV5/恺达EX6/坤鹏ET9），文档第208行", "input"),
    ("▸ LDT NEV存量车辆数", "2025 LDT NEV销量 × 换电渗透率 × CATL市占率", "万辆", "=E8*E9*E10", "", "calc"),
    (" └ 2025 LDT NEV销量", "(外部信源，待填)", "万辆", None,
     "外部信源：中汽协/乘联会轻卡销量 × 约10% NEV渗透率；分母不可自证，须外部获取", "note"),
    (" └ 换电渗透率(存量)", "(手动输入)", "", 0, "存量阶段换电轻卡未上市，取0", "input"),
    (" └ CATL市占率", "(手动输入)", "", 0.5, "全阶段一致，50%（沿用HDT假设）", "input"),
    ("增量换电装机规模（2026–2030年新车）", "单车带电量 × LDT NEV增量车辆数", "万kWh", "=E12*E14", "", "calc"),
    ("▸ 单车带电量（增量）", "(手动输入)", "kWh", 81, "巧克力换电版81度；轻卡无重卡420-500kWh大电量需求（文档第125、208行）", "input"),
    ("▸ LDT NEV增量车辆数", "新能源轻卡总销量 × 换电占比 × CATL市占率", "万辆", "=E15*E20*E21", "", "calc"),
    (" └ 新能源轻卡总销量（2026-2030）", "轻卡总销量 × NEV平均渗透率", "万辆", "=E16*E18", "", "calc"),
    ("    └ 轻卡总销量（2026-2030）", "平均年销量 × 5年", "万辆", "=E17*5", "", "calc"),
    ("       └ 平均年销量", "(外部信源，待填)", "万辆", None,
     "外部信源：中汽协轻卡年销量（约200万辆级，待核实）；分母不可自证，须外部获取", "note"),
    ("       └ 更新周期", "轻卡约8-10年", "年", 9, "历史经验取中位数；用于交叉校验 保有量/更新周期≈年销量", "input"),
    ("    └ NEV平均渗透率（2026-2030）", "S型曲线插值平均", "", "=AVERAGE(E23:E27)", "见下方逐年插值", "calc"),
    ("       └ 2025", "基准年", "", 0.1, "轻卡电动化约10%（文档第11行）", "input"),
    ("       └ 2026", "插值", "", 0.15, "", "input"),
    ("       └ 2027", "插值", "", 0.22, "", "input"),
    ("       └ 2028", "插值", "", 0.3, "", "input"),
    ("       └ 2029", "插值", "", 0.38, "", "input"),
    ("       └ 2030", "插值", "", 0.45, "轻卡渗透节奏滞后于重卡，低于重卡50%目标", "input"),
    (" └ 换电占比（增量阶段）", "里程分布倒推，非手动输入", "", 0.225,
     "由里程分布表倒推：200-300km(20%)高频子集~10% + 300-400km(10%)~10% + 400km以上(<1%)≈2.5%，合计约22.5%；对应文档第62、139-141、178行“20-25%走换电”", "input"),
    (" └ CATL市占率", "(手动输入)", "", 0.5, "全阶段一致，50%（沿用HDT假设）", "input"),
    ("说明1", "存量可视为0的核心原因", "文本", "轻卡换电是2026年才起步的新增量，2025年前无成规模换电轻卡在售；与HDT“存量20%”不同，轻卡只需算增量一项", "", "note"),
    ("说明2", "与HDT测算的关键差异", "文本", "①单车带电量81kWh(非420-500kWh)；②换电占比20-25%由里程分布倒推(非手动50%)；③存量项归零", "", "note"),
    ("说明3", "分母外部信源纪律", "文本", "轻卡总销量、NEV渗透率曲线、里程分布须来自中汽协/乘联会/上险/券商研报等独立信源，不可模型自证（记忆ID 86332462）", "", "note"),
]

r = 3  # 从第3行开始（1表标题, 2表头）
for item, formula, unit, value, note, kind in rows:
    ws.cell(r, 1, item)
    ws.cell(r, 2, formula)
    ws.cell(r, 3, unit)
    c4 = ws.cell(r, 4)
    if value is None:
        c4.value = None  # 外部信源占位，留空待填
    elif isinstance(value, str) and value.startswith("="):
        c4.value = value  # 公式
    else:
        c4.value = value
    ws.cell(r, 5, note)
    # 着色
    if kind == "calc":
        c4.fill = calc_fill
    elif kind == "input":
        c4.fill = input_fill
    elif kind == "note":
        for cc in range(1, 6):
            ws.cell(r, cc).fill = note_fill
    r += 1

# 列宽与换行
widths = [34, 42, 10, 14, 70]
for i, w in enumerate(widths, start=1):
    ws.column_dimensions[get_column_letter(i)].width = w
for row in ws.iter_rows(min_row=2, max_row=r-1, max_col=5):
    for cell in row:
        cell.alignment = wrap
        cell.border = border

# 冻结表头
ws.freeze_panes = "A3"

out = r"d:\AI\证券投资\投研\能源\宁德时代\data\换电db - LDT.xlsx"
wb.save(out)
print("saved:", out)

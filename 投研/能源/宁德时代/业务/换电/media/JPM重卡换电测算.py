"""
摩根大通《中国重卡电动化》报告核心三表计算还原
作者: 还原自JPM Report "China Heavy-Duty Truck Electrification" (2026-06-19)
依赖: pip install openpyxl
运行: python build_jpm_model.py
"""

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

wb = Workbook()

# ========== 样式定义 ==========
BLUE = PatternFill("solid", fgColor="DDEBF7")   # 原始输入(信源数据)
WHITE = PatternFill("solid", fgColor="FFFFFF")  # 公式
ORANGE = PatternFill("solid", fgColor="FCE4D6") # 信源标注
YELLOW = PatternFill("solid", fgColor="FFF2CC") # 关键输出
bold = Font(bold=True)
thin = Side(style="thin", color="BBBBBB")
border = Border(left=thin, right=thin, top=thin, bottom=thin)

def style_cell(c, fill=None, font=None, align=None):
    if fill: c.fill = fill
    if font: c.font = font
    if align: c.alignment = align
    c.border = border

# =====================================================================
# Sheet 1: Table 1 — 重卡销量与电池装机快照
# =====================================================================
ws1 = wb.active
ws1.title = "Table1_销量快照"
ws1["A1"] = "Table 1: 中国重卡销量与电池装机快照 (信源: CAAM + GGII)"
ws1["A1"].font = bold

# --- 区块A: CAAM原始数据 ---
ws1["A3"] = "区块A: CAAM原始数据 (中汽协月度产销快报)"
ws1["A3"].font = Font(bold=True, color="1F4E78")

headers_a = ["指标", "2024", "2025", "2026年1-4月", "信源"]
for col, h in enumerate(headers_a, 1):
    ws1.cell(4, col, h)

rows_a = [
    # 行5: 重卡总批发销量(含出口)
    ("重卡总批发销量(万辆, 含出口)", 90.2, 114.4, 43.5, "CAAM"),
    # 行6: 国内重卡销量
    ("国内重卡销量(万辆)", 61.1, 78.3, 27.3, "CAAM"),
    # 行7: 国内NEV销量
    ("国内新能源重卡销量(万辆)", 6.9, 19.2, 7.8, "CAAM"),
]
r = 5
for row in rows_a:
    for col, val in enumerate(row, 1):
        c = ws1.cell(r, col, val)
        if col <= 4 and isinstance(val, (int, float)):
            style_cell(c, BLUE)
        elif col == 5:
            style_cell(c, ORANGE)
        else:
            style_cell(c, BLUE)
    r += 1

# --- 公式行: 渗透率 = NEV销量 / 国内销量 ---
ws1.cell(8, 1, "→ 国内NEV渗透率 (%) [公式: =C7/C6]")
ws1.cell(8, 2, "=B7/B6 * 100")
ws1.cell(8, 3, "=C7/C6 * 100")
ws1.cell(8, 4, "=D7/D6 * 100")
for col in range(2, 5):
    style_cell(ws1.cell(8, col), WHITE, bold)

# --- 区块B: GGII原始数据 ---
ws1["A10"] = "区块B: GGII原始数据 (高工锂电动力电池装机数据库)"
ws1["A10"].font = Font(bold=True, color="1F4E78")

# 行11-12: NEV重卡销量(千辆) 和 电池装机(GWh) — GGII口径
ws1.cell(11, 1, "NEV重卡销量(千辆)")
ws1.cell(11, 3, 224)  # 2025年 19.2万辆 = 192千辆, 但GGII口径为224千辆
ws1.cell(11, 4, 30)   # 2026年1-4月
ws1.cell(11, 5, "GGII")
ws1.cell(12, 1, "NEV重卡电池装机(GWh)")
ws1.cell(12, 3, 93)
ws1.cell(12, 4, 30)
ws1.cell(12, 5, "GGII")
for r in (11, 12):
    for col in (3, 4):
        style_cell(ws1.cell(r, col), BLUE)
    style_cell(ws1.cell(r, 5), ORANGE)

# 行13: 单车带电量 = 装机(GWh)*1e6 / 销量(辆)
ws1.cell(13, 1, "→ 单车带电量 (kWh) [公式: =装机GWh*1000000/(销量千辆*1000)]")
ws1.cell(13, 3, "=C12 * 1000000/(C11 * 1000)")
ws1.cell(13, 4, "=D12 * 1000000/(D11 * 1000)")
for col in (3, 4):
    style_cell(ws1.cell(13, col), WHITE, bold)

# --- 区块C: 占比计算 ---
ws1["A15"] = "区块C: 结构性占比 (GGII卡车总电池 + 中国动力电池总盘)"
ws1["A15"].font = Font(bold=True, color="1F4E78")

# 行16-17: 卡车总电池 和 中国动力电池总销量
ws1.cell(16, 1, "卡车总电池装机(GWh) [GGII]")
ws1.cell(16, 3, 124)  # 2025年卡车电池约124GWh
ws1.cell(16, 4, 41)
ws1.cell(17, 1, "中国动力电池总销量(GWh) [CAAM]")
ws1.cell(17, 3, 715)  # 2025年中国动力电池销量为 715 GWh
ws1.cell(17, 4, 240)  # 2026年1-4月
for r in (16, 17):
    for col in (3, 4):
        style_cell(ws1.cell(r, col), BLUE)

# 行18: 重卡电池 / 卡车总电池
ws1.cell(18, 1, "→ 重卡电池占卡车总电池比重 (%) [公式: =重卡装机/卡车总装机]")
ws1.cell(18, 3, "=C12/C16 * 100")
ws1.cell(18, 4, "=D12/D16 * 100")
for col in (3, 4):
    style_cell(ws1.cell(18, col), WHITE, bold)

# 行19: 重卡电池 / 中国动力电池总盘
ws1.cell(19, 1, "→ 重卡电池占中国动力电池总盘比重 (%) [公式: =重卡装机/总盘]")
ws1.cell(19, 3, "=C12/C17 * 100")
ws1.cell(19, 4, "=D12/D17 * 100")
for col in (3, 4):
    style_cell(ws1.cell(19, col), WHITE, bold)

# 列宽
for col in range(1, 6):
    ws1.column_dimensions[get_column_letter(col)].width = 22

# =====================================================================
# Sheet 2: Figure 1 — 商用车电池需求预测
# =====================================================================
ws2 = wb.create_sheet("Figure1_电池需求预测")
ws2["A1"] = "Figure 1: 中国商用车电池需求预测 2022-2030E (CAGR >20%)"
ws2["A1"].font = bold

# --- Part 1: 重卡电池需求 (自下而上) ---
ws2["A3"] = "Part 1: 重卡电池需求 [公式: 国内销量 × 渗透率 × 单车带电量 / 100]"
ws2["A3"].font = Font(bold=True, color="1F4E78")

h2 = ["年份", "国内重卡销量(万辆)", "NEV渗透率(%)", "NEV销量(万辆)[=B*C]", 
      "单车带电量(kWh)", "重卡电池需求(GWh)[=D*E/100]", "信源"]
for col, h in enumerate(h2, 1):
    ws2.cell(4, col, h)

# 2025实际值（信源CAAM+GGII）
ws2.cell(5, 1, 2025)
ws2.cell(5, 2, 78.3)   # CAAM
ws2.cell(5, 3, 25)     # 实际渗透率
ws2.cell(5, 4, "=B5*C5")
ws2.cell(5, 5, 416)    # GGII实测
ws2.cell(5, 6, "=D5*E5/100")
ws2.cell(5, 7, "CAAM+GGII")

# 2026E-2030E 预测 (JPM假设)
hd_predictions = [
    # 年份, 国内销量, 渗透率, 带电量
    (2026, 80, 35, 460),
    (2027, 80, 42, 500),
    (2028, 82, 46, 530),
    (2029, 82, 48, 550),
    (2030, 82, 50, 570),  # JPM核心假设: 50%渗透率(政策40%被超额完成)
]
r = 6
for yr, vol, pen, cap in hd_predictions:
    ws2.cell(r, 1, yr)
    ws2.cell(r, 2, vol)       # JPM假设
    ws2.cell(r, 3, pen)      # JPM假设
    ws2.cell(r, 4, f"=B{r}*C{r}")
    ws2.cell(r, 5, cap)       # JPM假设(大电量趋势)
    ws2.cell(r, 6, f"=D{r}*E{r}/100")
    ws2.cell(r, 7, "JPM假设")
    r += 1

# 样式 Part 1
for rr in range(5, r):
    style_cell(ws2.cell(rr, 1))
    for cc in (2, 3, 5):
        style_cell(ws2.cell(rr, cc), BLUE)
    for cc in (4, 6):
        style_cell(ws2.cell(rr, cc), WHITE)
    style_cell(ws2.cell(rr, 7), ORANGE)

# --- Part 2: 其他商用车 (轻卡+中卡+客车) ---
ws2["A12"] = "Part 2: 其他商用车电池需求 [公式: 销量 × 渗透率 × 单车带电量 / 100]"
ws2["A12"].font = Font(bold=True, color="1F4E78")

h3 = ["细分市场", "2030E销量(万辆)", "NEV渗透率(%)", "单车带电量(kWh)", 
      "电池需求(GWh)[=B*C*D/100]", "信源/假设依据"]
for col, h in enumerate(h3, 1):
    ws2.cell(13, col, h)

# 其他商用车明细 (JPM假设, 基于CAAM商用车总盘子推算)
other_cv = [
    # 市场, 销量, 渗透率, 带电量
    ("轻型卡车(电动) ", 150, 15, 100),   # 轻卡电动化率较低, 带电量小
    ("中型卡车(电动) ", 15, 30, 200),    # 中卡带电量中等
    ("新能源客车(电动) ", 12, 60, 350),  # 客车渗透率已较高
    ("其他商用车(物流/专用) ", 20, 25, 150),
]
r = 14
for market, vol, pen, cap in other_cv:
    ws2.cell(r, 1, market)
    ws2.cell(r, 2, vol)
    ws2.cell(r, 3, pen)
    ws2.cell(r, 4, cap)
    ws2.cell(r, 5, f"=B{r}*C{r}*D{r}/100")
    ws2.cell(r, 6, "JPM假设 (基于CAAM商用车总量倒推)")
    r += 1

# 其他商用车合计
ws2.cell(r, 1, "其他商用车合计 (GWh)")
ws2.cell(r, 5, f"=SUM(E14:E{r-1})")
ws2.cell(r, 1).font = bold
ws2.cell(r, 5).font = bold
other_total_row = r

for rr in range(14, r):
    style_cell(ws2.cell(rr, 1))
    for cc in (2, 3, 4):
        style_cell(ws2.cell(rr, cc), BLUE)
    style_cell(ws2.cell(rr, 5), WHITE, bold)
    style_cell(ws2.cell(rr, 6), ORANGE)

# --- Part 3: 商用车电池总需求汇总 ---
total_row = r + 2
ws2.cell(total_row, 1, "商用车电池总需求 (GWh)")
ws2.cell(total_row, 6, f"=F10+{get_column_letter(5)}{other_total_row}")
ws2.cell(total_row, 1).font = Font(bold=True, size=12)
ws2.cell(total_row, 6).font = Font(bold=True, size=12)
ws2.cell(total_row, 6).fill = YELLOW
style_cell(ws2.cell(total_row, 1))
style_cell(ws2.cell(total_row, 6), YELLOW, bold)

# CAGR计算: 2025重卡实际 81.4 GWh → 2030 233.7 GWh
cagr_row = total_row + 2
ws2.cell(cagr_row, 1, "重卡电池需求CAGR 2025-2030 [公式: =(2030/2025)^(1/5)-1]")
ws2.cell(cagr_row, 6, "=(F10*B6)")  # 占位, 实际CAGR需手动算
ws2.cell(cagr_row+1, 1, "→ 实际CAGR (%)")
# 用2025实际81.4 GWh 和 2030预测233.7 GWh算
ws2.cell(cagr_row+1, 6, "=((F10/81.4)^(1/5)-1)*100")
style_cell(ws2.cell(cagr_row+1, 6), YELLOW, bold)

for col in range(1, 7):
    ws2.column_dimensions[get_column_letter(col)].width = 20

# =====================================================================
# Sheet 3: Table 3/4/5 — TCO全生命周期成本
# =====================================================================
ws3 = wb.create_sheet("Table3-5_TCO分析")
ws3["A1"] = "TCO全生命周期成本分析 (3年/5年/10年) — 信源: 报告Table 3-5"
ws3["A1"].font = bold

# --- 共同假设参数块 ---
ws3["A3"] = "共同假设参数 (JPM自建)"
ws3["A3"].font = Font(bold=True, color="1F4E78")

params = [
    ("电动重卡购置价(万元)", 70, "JPM假设(参考福田/一汽解放报价)"),
    ("LNG重卡购置价(万元)", 45, "JPM假设"),
    ("柴油重卡购置价(万元)", 40, "JPM假设"),
    ("年行驶里程(万公里)", 15, "JPM假设(高频运营)"),
    ("电动重卡能耗(kWh/km)", 1.5, "JPM假设(满载+空调)"),
    ("LNG重卡能耗(kg/km)", 0.4, "JPM假设"),
    ("柴油重卡能耗(L/km)", 0.4, "JPM假设"),
    ("电价(元/kWh)", 0.85, "JPM假设(工商业充电)"),
    ("LNG价格(元/kg) - 基准", 6.2, "2026年6月现货价"),
    ("LNG价格(元/kg) - 回落情景", 4.2, "2025年均价"),
    ("柴油价格(元/L)", 7.2, "2026年6月零售价"),
    ("电动重卡年维护(万元)", 1.5, "JPM假设(三电免维护)"),
    ("LNG重卡年维护(万元)", 2.5, "JPM假设"),
    ("柴油重卡年维护(万元)", 3.0, "JPM假设"),
    ("电动重卡年载重损失(万元)", 7.0, "JPM假设(电池自重导致载货减少)"),
    ("LNG重卡年载重损失(万元)", 1.5, "JPM假设"),
    ("柴油重卡年载重损失(万元)", 0, "无电池自重"),
    ("电动重卡购置税率(%)", 5, "2026年新能源减半征收"),
    ("LNG/柴油购置税率(%)", 10, "传统燃油车10%"),
    ("电动重卡购车补贴(万元)", 9.5, "2026年以旧换新"),
    ("LNG重卡购车补贴(万元)", 6.5, "2026年以旧换新"),
    ("柴油重卡购车补贴(万元)", 0, "无"),
    ("报废补贴(万元, 电动/LNG统一)", 4.5, "2026年以旧换新"),
]
r = 4
for name, val, src in params:
    ws3.cell(r, 1, name)
    ws3.cell(r, 2, val)
    ws3.cell(r, 3, src)
    style_cell(ws3.cell(r, 1))
    style_cell(ws3.cell(r, 2), BLUE)
    style_cell(ws3.cell(r, 3), ORANGE)
    r += 1

param_end = r - 1

# --- Table 3: 基准情景 (LNG=6.2, 有补贴) ---
t3_row = param_end + 2
ws3.cell(t3_row, 1, "Table 3: 基准情景 (LNG=6.2元/kg, 有购置税优惠+补贴)")
ws3[f"A{t3_row}"].font = Font(bold=True, color="C00000")

# TCO计算
# 公式: 购置总成本 = 车价 + 车价*税率 - (购车补贴+报废补贴)
#      年运营成本 = 年里程*能耗*能源单价 + 年维护 + 年载重损失
#      TCO(N) = 购置总成本 + 年运营成本 * N

# 行: 电动重卡
er = t3_row + 1
ws3.cell(er, 1, "电动重卡")
ws3.cell(er+1, 1, "  ↓购置总成本(万元) [=车价+车价*税率-(购车补贴+报废补贴)]")
ws3.cell(er+1, 2, f"=B4+B4*B20/100-(B21+B22)")
ws3.cell(er+2, 1, "  ↓年运营成本(万元) [=里程*能耗*电价+维护+载重损失]")
ws3.cell(er+2, 2, f"=B7*B10*B8/10000+B13+B17")
ws3.cell(er+3, 1, "  TCO 3年(万元)")
ws3.cell(er+3, 2, f"=B{er+1}+B{er+2}*3")
ws3.cell(er+4, 1, "  TCO 5年(万元)")
ws3.cell(er+4, 2, f"=B{er+1}+B{er+2}*5")
ws3.cell(er+5, 1, "  TCO 10年(万元)")
ws3.cell(er+5, 2, f"=B{er+1}+B{er+2}*10")

# 行: LNG重卡
lr = er + 7
ws3.cell(lr, 1, "LNG重卡")
ws3.cell(lr+1, 1, "  ↓购置总成本(万元)")
ws3.cell(lr+1, 2, f"=B5+B5*B21/100-(B22+B23)")
ws3.cell(lr+2, 1, "  ↓年运营成本(万元) [=里程*能耗*LNG价+维护+载重损失]")
ws3.cell(lr+2, 2, f"=B7*B11*B9/10000+B14+B18")
ws3.cell(lr+3, 1, "  TCO 3年(万元)")
ws3.cell(lr+3, 2, f"=B{lr+1}+B{lr+2}*3")
ws3.cell(lr+4, 1, "  TCO 5年(万元)")
ws3.cell(lr+4, 2, f"=B{lr+1}+B{lr+2}*5")
ws3.cell(lr+5, 1, "  TCO 10年(万元)")
ws3.cell(lr+5, 2, f"=B{lr+1}+B{lr+2}*10")

# 行: 柴油重卡
dr = lr + 7
ws3.cell(dr, 1, "柴油重卡")
ws3.cell(dr+1, 1, "  ↓购置总成本(万元)")
ws3.cell(dr+1, 2, f"=B6+B6*B21/100-B23")
ws3.cell(dr+2, 1, "  ↓年运营成本(万元)")
ws3.cell(dr+2, 2, f"=B7*B12*B11/10000+B15+B19")
ws3.cell(dr+3, 1, "  TCO 3年(万元)")
ws3.cell(dr+3, 2, f"=B{dr+1}+B{dr+2}*3")
ws3.cell(dr+4, 1, "  TCO 5年(万元)")
ws3.cell(dr+4, 2, f"=B{dr+1}+B{dr+2}*5")
ws3.cell(dr+5, 1, "  TCO 10年(万元)")
ws3.cell(dr+5, 2, f"=B{dr+1}+B{dr+2}*10")

# 样式 Table 3
for rr in range(er, dr+6):
    style_cell(ws3.cell(rr, 1))
    if ws3.cell(rr, 2).value and isinstance(ws3.cell(rr, 2).value, str) and ws3.cell(rr, 2).value.startswith("="):
        style_cell(ws3.cell(rr, 2), WHITE)
    else:
        style_cell(ws3.cell(rr, 2))

# --- Table 4: LNG回落情景 (LNG=4.2, 有补贴) ---
t4_row = dr + 8
ws3.cell(t4_row, 1, "Table 4: LNG价格回落情景 (LNG=4.2元/kg, 有补贴)")
ws3[f"A{t4_row}"].font = Font(bold=True, color="ED7D31")

# 把LNG价格改为4.2 (参数B10改为4.2)
ws3.cell(t4_row+1, 1, "  [注: 将参数B10从6.2改为4.2]")
ws3.cell(t4_row+1, 2, 4.2)
ws3.cell(t4_row+1, 2).fill = YELLOW

# 电动TCO (同Table 3, 因LNG价格不影响电动)
e4 = t4_row + 2
ws3.cell(e4, 1, "电动重卡 TCO 3/5/10年")
ws3.cell(e4, 2, f"=B{er+3}")
ws3.cell(e4, 3, f"=B{er+4}")
ws3.cell(e4, 4, f"=B{er+5}")

# LNG TCO (使用新LNG价格)
l4 = e4 + 1
ws3.cell(l4, 1, "LNG重卡 TCO 3/5/10年 [年运营成本用B10=4.2]")
ws3.cell(l4, 2, f"=B{lr+1}+(B7*B11*$B${t4_row+1}/10000+B14+B18)*3")
ws3.cell(l4, 3, f"=B{lr+1}+(B7*B11*$B${t4_row+1}/10000+B14+B18)*5")
ws3.cell(l4, 4, f"=B{lr+1}+(B7*B11*$B${t4_row+1}/10000+B14+B18)*10")

# 差异
d4 = l4 + 1
ws3.cell(d4, 1, "电动 vs LNG 3年TCO差异(%)")
ws3.cell(d4, 2, f"=(B{e4}-B{l4})/B{l4}*100")
style_cell(ws3.cell(d4, 2), YELLOW, bold)

# --- Table 5: 零补贴情景 (LNG=6.2, 无补贴+全额10%税率) ---
t5_row = d4 + 2
ws3.cell(t5_row, 1, "Table 5: 补贴退坡情景 (LNG=6.2, 购置税全征10%, 零补贴)")
ws3[f"A{t5_row}"].font = Font(bold=True, color="548235")

# 零补贴: 购置税全征 + 补贴归零
# 电动: 税率10%, 补贴0
# LNG: 税率10%, 补贴0
e5 = t5_row + 1
ws3.cell(e5, 1, "电动重卡 购置总成本(零补贴) [=车价+车价*10%-0]")
ws3.cell(e5, 2, "=B4+B4 * 10/100")
ws3.cell(e5+1, 1, "电动 TCO 3/5/10年")
ws3.cell(e5+1, 2, f"=B{e5}+B{er+2}*3")
ws3.cell(e5+1, 3, f"=B{e5}+B{er+2}*5")
ws3.cell(e5+1, 4, f"=B{e5}+B{er+2}*10")

l5 = e5 + 2
ws3.cell(l5, 1, "LNG重卡 购置总成本(零补贴) [=车价+车价*10%-0]")
ws3.cell(l5, 2, "=B5+B5 * 10/100")
ws3.cell(l5+1, 1, "LNG TCO 3/5/10年")
ws3.cell(l5+1, 2, f"=B{l5}+(B7*B11*B9/10000+B14+B18)*3")
ws3.cell(l5+1, 3, f"=B{l5}+(B7*B11*B9/10000+B14+B18)*5")
ws3.cell(l5+1, 4, f"=B{l5}+(B7*B11*B9/10000+B14+B18)*10")

# 差异
d5 = l5 + 2
ws3.cell(d5, 1, "电动 vs LNG 3年TCO差异(%) [零补贴]")
ws3.cell(d5, 2, f"=(B{e5+1}-B{l5+1})/B{l5+1}*100")
style_cell(ws3.cell(d5, 2), YELLOW, bold)

# 列宽
for col in range(1, 5):
    ws3.column_dimensions[get_column_letter(col)].width = 55

# ========== 保存 ==========
output_file = "HDT_Electrification_Model_JPM.xlsx"
wb.save(output_file)
print(f"✅ 已生成: {output_file}")
print(f"📊 包含3个工作表:")
print(f"   1. Table1_销量快照 — CAAM/GGII原始数据 + 公式")
print(f"   2. Figure1_电池需求预测 — 自下而上测算 + CAGR")
print(f"   3. Table3-5_TCO分析 — 三种情景敏感性分析")
print(f"\n📌 信源标注:")
print(f"   🔵 浅蓝 = 原始数据输入")
print(f"   🟠 橙   = 信源说明")
print(f"   ⚪ 白   = Excel公式 (修改输入自动重算)")
print(f"   🟡 黄   = 关键输出")
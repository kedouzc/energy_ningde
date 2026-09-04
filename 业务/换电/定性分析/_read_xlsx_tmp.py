# -*- coding: utf-8 -*-
import openpyxl
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

path = r"d:/AI/证券投资/投研/能源/宁德时代/业务/换电/定性分析/重卡HDT换电规模测算.xlsx"
wb = openpyxl.load_workbook(path, data_only=True)
for ws in wb.worksheets:
    print("=" * 80)
    print("SHEET:", ws.title, " dims:", ws.dimensions)
    print("=" * 80)
    for row in ws.iter_rows():
        vals = []
        for c in row:
            if c.value is not None:
                vals.append(f"{c.coordinate}={c.value}")
        if vals:
            print(" | ".join(vals))

# -*- coding: utf-8 -*-
"""从 七环结论数.json 生成 outputs/换电沙盘_v6.html（单文件）。

研究者不用读本程序：沙盘里的每个数都能在 01_逻辑七环.md 的表里找到。
运行：python3 七环毛估.py && python3 生成沙盘v6.py
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))          # 换电战略决策模型_v4_3
R = json.load(open(os.path.join(HERE, "七环结论数.json"), encoding="utf-8"))

ST_MW_R = R["params"]["对手站含回报"]["超充"]
ST_MW = 0.098
VOL = {"接力": 700, "多班倒": 300, "要停的车_蹭站": 1000}
CITY = [0.02, 0.04, 0.07]

def r3(x):
    return round(x, 4)

blocks = {}
for name, b in R["blocks"].items():
    rows = []
    for t in b["tiers"]:
        st_ret = t["rival_station"] - (ST_MW if t["rival"] == "超充" else 0.080)
        real = (t["gap_station"] - st_ret) + t["gap_time"] + t["gap_batt_premium_tax"] + t["gap_batt_life"]
        ret = st_ret + t["gap_batt_return"]
        rows.append({
            "gap": r3(t["gap"]), "gap0": r3(t["gap0"]), "real": r3(real), "ret": r3(ret),
            "inv": r3(t["inv"]), "roi": r3(t["roi"]), "rent": r3(t["rent"]), "rent5": r3(t["rent5"]),
            "left": r3(t["left"]), "left5": r3(t["left5"]), "left0": r3(t["left0"]),
            "payback": round(t["payback"], 1),
        })
    blocks[name] = rows

val = []
for v in R["valuation_2030"]:
    val.append({k: round(v[k], 1) for k in ("sys_pre", "sys_pre5", "sys_pre0", "fee", "spread", "mgr_fee",
                                             "spread_v", "lock_incr", "lock_full", "main", "main5", "main0",
                                             "total_full", "inv_heavy", "pie_heavy", "roi_heavy")})

DATA = {
    "cap": 13500,
    "vol": VOL, "city": CITY,
    "blocks": blocks, "val": val,
    "y2035": {k: round(R["y2035"][k], 1) for k in ("sys_pre", "main", "total_incr", "inv")},
    "net": {k: round(v, 1) for k, v in R["network_2030"].items()},
}

tpl = open(os.path.join(HERE, "沙盘v6_模板.html"), encoding="utf-8").read()
out = tpl.replace("__DATA__", json.dumps(DATA, ensure_ascii=False))
dst = os.path.join(ROOT, "outputs", "换电沙盘_v6.html")
open(dst, "w", encoding="utf-8").write(out)
print("写出", dst, len(out.encode("utf-8")), "字节")

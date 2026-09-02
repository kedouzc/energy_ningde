import re
p = "重卡与城配物流换电规模测算_合并对比.py"
t = open(p, encoding="utf-8").read()
for i, l in enumerate(t.splitlines()):
    if re.search(r"rent|租金|站内|周转|spare|station", l, re.I):
        print(i+1, l.rstrip())

# 验证产物可复现：用**不同** PYTHONHASHSEED 各跑一次，产物必须字节一致。
# 修复前 axis_members 是 set，顺序随哈希种子变 → 每次跑出的 HTML 都不同。
# 用完即删。
import hashlib
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent
OUT = ROOT / "outputs" / "换电沙盘_v4.3.html"
LOG = ROOT / "_tmp_repro.log"
lines: list[str] = []


def run(seed: str):
    env = dict(os.environ, PYTHONHASHSEED=seed, PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, str(ROOT / "src" / "sandbox.py")],
                       cwd=str(ROOT), capture_output=True, env=env)
    if r.returncode != 0:
        lines.append(f"seed={seed} ❌ 失败")
        lines.append(r.stderr.decode("utf-8", errors="replace")[-1200:])
        return None
    b = OUT.read_bytes()
    return hashlib.md5(b).hexdigest(), len(b)


res = {}
for seed in ("0", "1", "12345", "99991"):
    r = run(seed)
    if r:
        res[seed] = r
        lines.append(f"seed={seed:<6} {r[1]:>12,} 字节  md5={r[0]}")

uniq = set(res.values())
lines.append("")
if len(res) == 4 and len(uniq) == 1:
    lines.append("✅ 四种哈希种子下产物完全一致 —— 产物可复现")
else:
    lines.append(f"❌ 出现 {len(uniq)} 种不同产物 —— 仍不可复现")

LOG.write_text("\n".join(lines), encoding="utf-8")
print("done")

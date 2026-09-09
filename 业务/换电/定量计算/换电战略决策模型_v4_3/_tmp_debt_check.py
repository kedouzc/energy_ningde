import sys, time
sys.path.insert(0, "src")
from config_loader import load_config, load_drivers, apply_scenario
from model import build_model
from lab import read_metrics, INFLUENCE_ANCHOR

cfg = load_config()
import importlib, sys as _s
# 模型耗时
t0 = time.time()
for dr in (0.50, 0.60, 0.75):
    c = load_config()
    c["finance"]["debt_ratio"] = dr
    kw = apply_scenario(c, load_drivers(c), "中性")
    v = read_metrics(build_model(c, **kw))
    print(f"debt_ratio={dr}: swap_increment={v[INFLUENCE_ANCHOR]:.1f}  "
          f"EV={v.get('swap_business.enterprise_value_yi'):.1f}  "
          f"equity={v.get('swap_business.project_equity_value_yi'):.1f}  "
          f"steady_debt={v.get('capex.steady_state_debt_yi'):.1f}")
print("model run time (one):", round(time.time() - t0, 3), "s")

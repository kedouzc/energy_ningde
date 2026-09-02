import importlib.util, sys

spec = importlib.util.spec_from_file_location(
    "m", r"d:\AI\证券投资\投研\能源\宁德时代\业务\换电\定性分析\重卡与城配物流换电规模测算_合并对比.py"
)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

r = m.compute_incremental_model()
print("=== GWh 地基 ===")
for k in r["fgwh"]:
    veh = m.CONFIG_INC["fleet_wan"][k]
    print(f"  {k:<8} 车辆 {veh:.0f}万 x 带电 {m.CONFIG_INC['battery_kwh'][k]:.0f}kWh -> {r['fgwh'][k]:.1f} GWh")
print(f"  总供货 GWh = {r['fgwh_tot']:.1f}")
print(f"    换电 GWh = {r['gwh_swap']:.1f}")
print(f"    充电 GWh = {r['gwh_charge']:.1f}")

# 估值对账
print("\n=== 估值 ===")
print(f"  VO_eco (换电侧, EV/EBITDA) = {r['VO_eco']:.0f} 亿")
print(f"  VS_real (有换电时充电侧销售) = {r['VS_real']:.0f} 亿")
print(f"  VS_no   (无换电基准销售)     = {r['VS_no']:.0f} 亿")
print(f"  SOTP 有换电 = VO_eco + VS_real = {r['VO_eco']+r['VS_real']:.0f} 亿")
print(f"  无换电基准 = VS_no = {r['VS_no']:.0f} 亿")
print(f"  净增量 Delta = {r['delta_value']:.0f} 亿")

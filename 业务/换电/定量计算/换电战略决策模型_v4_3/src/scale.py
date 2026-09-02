"""换电规模测算：车辆漏斗、换电频次、装机、站数与电池寿命。

变更历史
--------

v4.4（2026-08-30）
- 【重构｜4站型独立】站数反推从 heavy/choco 两个站组改为四个站型分别反推：
  qiji75_short/qiji75_trunk/choco25_passenger/choco35_city（池键=站型键，1:1 对应）。
  重卡短途/中长途分别建骐骥站（不混用），乘用车/城配分别建巧克力站（不混用）；
  target_station_demand/mature_daily_swaps/mature_annual_energy_yi_kwh 全部改为四池键，
  两大类汇总（重卡=短途+中长途、巧克力=乘用+城配）由 ScaleResult property 派生，仅供 v3.2 对照与总表展示。
- 【重构｜存量站拆分】2025年末存量站与2026累计目标按池拆分：骐骥站按短途/中长途池
  换电需求份额拆分；巧克力站全部计入乘用池（城配35#专门站2026起才建设）。
- 【重构｜InventoryMultiplier】站端配比按供需恒等式自动派生：
  站数(池)=ceil(池车日换电次数÷站日接待能力)；站端配比=池站内电池GWh÷池装车GWh；
  InventoryMultiplier=站端配比+1。删除 station_group_pool_shares()（共享站近似的产物，
  4站型独立架构下不再需要），[battery_pool_model] 配置段随之清空。
- 【修正｜换电装机口径】catl_swap_gwh 改按场景实际装车电量（onboard_battery_kwh：
  重卡短途342/中长途513、乘用56、城配81），不再按车型均值（重卡原用500虚增装机）；
  ScaleRow 新增 onboard_battery_kwh 字段；年换电电量按池用池内加权装车电量计算。
- 【新增｜四池】寿命核算从 heavy/choco 两个站组改为四个实际电池流转池：
  qiji75_short（骐骥75#倒短）、qiji75_trunk（骐骥75#中长途干线）、
  choco25_passenger（巧克力25#乘用车）、choco35_city（巧克力35#城配）。
- 【修改｜寿命归属】车型/场景只决定池内使用强度；derived 模式下 ScaleRow.battery_life_years
  统一继承所属电池池寿命，不再保留“每车型各算一个寿命”的口径；
  ScaleRow 新增 battery_pool 字段记录池归属，供 capex/report 直接读取。
- 【修改｜站内库存】inventory_multiplier 不再默认 1.0（那等于“CAPEX 付了站内电池的钱、
  EFC 分母却不含站内电池”，系统性高估池均频次）——未显式配置时按
  「组站内库存GWh（终局站数×块数×块容量）×池换电需求份额 ÷ 池终局装车GWh + 1」自动派生；
  显式配置 [battery_pool_model.inventory_multiplier.<pool>] 仍可覆盖。
- 【新增｜池级寿命参数】支持 [battery_pool_model.life_override.<pool>] 覆盖原全局寿命参数，
  便于75#/25#/35#以后采用不同循环临界点或日历寿命；未配置时沿用原全局参数。
- 【更名】ScaleResult 字段正式更名为 battery_pool_life_years（原 station_battery_life_years
  已同步删除，schemas/capex/report/v32_audit 全链路一致）。
- 【新增】station_group_pool_shares()：站内电池按池换电需求强度份额拆分，
  capex 用它把（年份×站组）站内电池批次拆成四池×年度cohort。

【建模思路】
0. **原则**

车型决定“这个池子有多累”；电池规格+实际流转范围决定“谁和谁是一个池”；cohort决定“哪一年该换”。
最终数据结构其实应该是：

$$ \text{车辆类型} \rightarrow \text{换电需求} \rightarrow \text{电池池吞吐量} \rightarrow EFC \rightarrow SOH/寿命 \rightarrow Replacement \rightarrow CAPEX+\ Depreciation $$

而不是：

$$ \text{车辆类型} \rightarrow \text{直接指定寿命} \rightarrow Replacement $$

1. **四个物理电池池**

   * `qiji75_short`：骐骥75#倒短/短途
   * `qiji75_trunk`：骐骥75#中长途干线
   * `choco25_passenger`：巧克力25#，出租车+网约车+Robotaxi+私家车共池
   * `choco35_city`：巧克力35#，城配物流车，信源：[轻卡专门建站](https://www.catl.com/news/9884.html?utm_source=chatgpt.com)

2. **车型不再各算一个寿命**

   车型/场景只贡献不同的使用强度：

   $$
   Usage_p=\sum_i GWh_i\times f_i
   $$

   池内平均等效换电频次：

   $$
   \bar f_p=
   \frac{\sum_i GWh_i\times f_i}
   {GWh_{vehicle,p}\times InventoryMultiplier_p}
   $$

   其中 `InventoryMultiplier` 用来把**站内周转电池+备用电池**纳入共享池。例如未来若确认站内及备用相当于装车电池的15%，则取1.15。现在没有可靠资料，我没有替你拍数，默认1.0。

3. **池寿命**

   $$
   Life_p= \min\left(
   \frac{CriticalCycles_p} {\bar f_p\times OperatingDays},
   CalendarLife_p \right)
   $$

   75#、25#、35#未来如果查到不同循环寿命，可以分别配置；没数据时仍沿用你原来的全局 `battery_life_model`。

4. **重置CAPEX以后按 pool × cohort 做**

   例如2027年新增的25#电池属于 `choco25_passenger × 2027 cohort`，
   达到该池寿命/EFC阈值以后再产生 replacement CAPEX。**不要把整个25#池在某一年一次性全部重置。**

原v4.3实际上还有一点口径冲突：`ScaleRow.battery_life_years` 按各车型/场景频次单独计算，
但后面的“站内电池寿命”又按 `heavy/choco` 两组汇总，因此下游若引用row级寿命，会重新退回“车型各有寿命”的逻辑。
原来池级汇总也只有 `heavy/choco` 两组。

【对程序做的主要修】

代码里已经直接用 **`【新增】`、`【修改】`、`【删除】`** 标出来，重点是：

* **【新增】** `BATTERY_POOLS` 四池定义。
* **【新增】** `_battery_pool_key()`：把车型×场景映射到四池。

  * 重卡“短途/倒短” → `qiji75_short`
  * 其他重卡场景 → `qiji75_trunk`
  * taxi/ridehail/robotaxi/private → `choco25_passenger`
  * city → `choco35_city`
* **【删除】** 原先 `heavy/choco` 两组“站内周转电池寿命”逻辑。
* **【修改】** `derived` 模式下，所有row最终统一继承所属池寿命，不再保留出租车、网约车、Robotaxi等各自独立寿命。
* **【修改】** `inventory_multiplier` 默认值不再拍 1.0，改为从模型自身的站体参数自动派生
  （终局站数×库存块数×块容量 → 组站内GWh，按池换电需求份额归属后进入该池EFC分母）。
* **【新增】** `life_override`，以后75#/25#/35#可以使用不同循环寿命和日历寿命参数。
* **【更名】** `ScaleResult.station_battery_life_years` → `battery_pool_life_years`，
  `ScaleRow` 增加 `battery_pool` 字段；capex/report/v32_audit 已同步。
* **保留** `legacy_v32`，旧版附录对照仍然可用（四池回放时映射回旧站组取旧硬编码寿命）。

`base.toml` 已为重卡三场景与各车型**显式写明 `battery_pool`**，不再依赖“短途/倒短”关键词识别：

```toml
[[vehicles.heavy.scenes]]
name = "短途"
battery_pool = "qiji75_short"
```

池级寿命参数接口（不写这些配置就继续沿用原模型参数）：

```toml
[battery_pool_model.life_override.qiji75_short]
critical_cycles = ...
calendar_cap_years = ...
```

【本轮已知的近似（后续可升级，不影响当前口径自洽）】
1. 池寿命按终局稳态口径计算，再统一套用到各年度cohort——早期年份车辆少、
   站内电池占比更高，实际强度结构略有不同；毛估估层面接受。
2. 城配35#池共享 choco 站组（站数/站体参数与乘用站共用），仅电池寿命按池拆分——
   官方轻卡站“乘商兼容、同站可服务25#/35#电池”（catl.com/news/9884），
   该近似有物理依据；若未来拿到城配专门站参数可拆第三站组。
3. replacement 已实现“四池×年度cohort”分批到期；进一步升级为逐cohort累计EFC
   触发（而非池统一寿命）需引入逐年强度路径，暂无此精度需求。


v4.3（2026-08-29）
- 【充电份额】删除实现率中间层与场景级 catl_charge_share；新增 _charge_share() 按悲观/中性/乐观取档，
  FALLBACK_CHARGE_SHARE 在 [charge_share] 配置缺失时兜底；legacy_v32 对照不再锁旧充电份额，使A.2纯对比寿命维度。
- 【寿命】删除各车型/站组的硬编码 battery_life_years，改为按使用强度推算：
  life = min(critical_cycles ÷ (f̄ × days), calendar_cap)，
  f̄ = Σ(装机GWh × 频次)/Σ装机GWh，即按使用量（装机×频次）加权的使用强度。
  不可对寿命直接按装加权——寿命是频次的倒数，倒数后加权会系统性高估（Jensen不等式）。
- 【站数】改为「冗余优先」：营运车需求按规划能力建站，私家车需求先填单站物理冗余
  （物理上限552 − 规划300 = 252次/日），溢出部分才新建站。
- 【情景】新增 private_scenario（私家车保守/中枢/激进三档渗透率）。
- 【对照】新增 life_mode="legacy_v32"，沿用v3.2硬编码寿命重跑，仅供附录对比。
"""
from __future__ import annotations

import math
from dataclasses import is_dataclass, replace

from derived import (
    LEGACY_V32_STATION_LIFE_YEARS,
    LEGACY_V32_VEHICLE_LIFE_YEARS,
    battery_life_years as derived_battery_life_years,
    station_capacity,
    swap_frequency_per_day,
)
from schemas import ScaleResult, ScaleRow, SourcingAdjustment


def _operating_stocks(config: dict) -> dict[str, float]:
    d = config["operating_demand"]
    robotaxi_km = d["robotaxi_fleet_wan"] * d["robotaxi_daily_km"] * d["robotaxi_days"] / 1e4
    human_stock = (d["pool_2030_yi_km"] - robotaxi_km) / (
        d["human_daily_km"] * d["human_days"] / 1e4
    )
    return {"taxi": d["taxi_stock_wan"], "ridehail": human_stock - d["taxi_stock_wan"]}


def _annual_ev_wan(vehicle: dict, year_index: int, stocks: dict[str, float]) -> float:
    pure = vehicle.get("pure_electric_share", 1.0)
    if "annual_net_additions_wan" in vehicle:
        return vehicle["annual_net_additions_wan"][year_index] * pure
    stock = stocks[vehicle["stock_source"]] if "stock_source" in vehicle else vehicle["stock_wan"]
    return stock / vehicle["replacement_cycle_years"] * vehicle["nev_rates"][year_index] * pure


# 充电段市占率三档的兜底值。正式口径以 configs/base.toml 的 [charge_share] 段为准
# （该段含完整的取值理由与信源链接）。此处仅在配置缺失时兜底，保证模型可运行。
FALLBACK_CHARGE_SHARE: dict[str, tuple[float, float]] = {
    "heavy": (0.35, 0.55),
    "city": (0.35, 0.45),
    "taxi": (0.35, 0.45),
    "ridehail": (0.35, 0.45),
    "robotaxi": (0.40, 0.40),  # 全量换电(swap_pen=1)：有换电侧充电份额恒为0（被 swap_pen 归零），该档仅用于无换电反事实纯制造口径（中性 0.40），故无情景区间——与 base.toml [charge_share.robotaxi] 对齐
    "private": (0.33, 0.40),
}

# -------------------------------新增-----------------------------------
# 【新增｜四池】寿命按“物理可流转电池池”核算，而不是按车型核算。
BATTERY_POOLS: dict[str, str] = {
    "qiji75_short": "骐骥75#倒短（短途）",
    "qiji75_trunk": "骐骥75#干线（中长途）",
    "choco25_passenger": "巧克力25#（乘用车）",
    "choco35_city": "巧克力35#（城配物流）",
}

PASSENGER_VEHICLE_KEYS = {"taxi", "ridehail", "robotaxi", "private"}
HEAVY_SHORT_SCENE_KEYWORDS = ("短途", "倒短", "short")

# 两大类汇总键（重卡=短途+中长途，巧克力=乘用+城配）：站数/需求/电量按四池独立
# 计算后仅作汇总对照（v3.2 接口、总表）；legacy_v32 寿命也按此映射回旧站组。
POOL_STATION_GROUP = {
    "qiji75_short": "heavy",
    "qiji75_trunk": "heavy",
    "choco25_passenger": "choco",
    "choco35_city": "choco",
}


def split_group_station_count(
    count: int, group: str, pool_demand: dict[str, float]
) -> dict[str, int]:
    """【新增｜4站型】把大类站数（2025存量/2026累计目标/可复用站）拆到所属池。

    拆分规则（用户确认）：
    - 骐骥站（heavy）：按短途/中长途池的换电需求份额（池车日换电次数）拆分；
    - 巧克力站（choco）：全部计入乘用池——城配35#专门站2026起才建设，历史站
      均为25#乘用站。
    最大余数法分配整数，保证四池拆分结果之和恒等于原大类站数（不凭空增减站）。
    """
    pools = [pk for pk in BATTERY_POOLS if POOL_STATION_GROUP[pk] == group]
    if group == "heavy":
        total = sum(pool_demand.get(pk, 0.0) for pk in pools)
        if total > 0:
            shares = {pk: pool_demand.get(pk, 0.0) / total for pk in pools}
        else:  # 需求为零时均分（正常输入下不可达）
            shares = {pk: 1.0 / len(pools) for pk in pools}
    else:  # choco：全部计入乘用池
        shares = {"choco25_passenger": 1.0, "choco35_city": 0.0}
    raw = {pk: count * shares[pk] for pk in pools}
    result = {pk: int(math.floor(raw[pk] + 1e-9)) for pk in pools}
    remainder = count - sum(result.values())
    # 余数按小数部分从大到小补 1（最大余数法）
    for pk in sorted(pools, key=lambda k: raw[k] - math.floor(raw[k] + 1e-9), reverse=True):
        if remainder <= 0:
            break
        result[pk] += 1
        remainder -= 1
    return result


def _battery_pool_key(vehicle_key: str, vehicle: dict, scene: dict) -> str:
    """【新增】把每一条车型×场景记录映射到四个电池流转池。

    优先读取配置中的 battery_pool，便于以后精确指定；当前配置若尚未增加该字段，
    则按既定四池规则自动映射：重卡短途/倒短 -> qiji75_short，其余重卡 -> qiji75_trunk；
    出租/网约/Robotaxi/私家 -> choco25_passenger；城配 -> choco35_city。
    """
    explicit = scene.get("battery_pool") or vehicle.get("battery_pool")
    if explicit is not None:
        if explicit not in BATTERY_POOLS:
            raise ValueError(f"未知 battery_pool={explicit}，可用：{list(BATTERY_POOLS)}")
        return explicit

    if vehicle["station_group"] == "heavy":
        scene_name = str(scene.get("name", ""))
        if any(keyword.lower() in scene_name.lower() for keyword in HEAVY_SHORT_SCENE_KEYWORDS):
            return "qiji75_short"
        return "qiji75_trunk"

    if vehicle_key in PASSENGER_VEHICLE_KEYS:
        return "choco25_passenger"
    if vehicle_key == "city":
        return "choco35_city"

    raise ValueError(
        f"车型 {vehicle_key} 无法自动归入四池；请在 vehicle 或 scene 配置中显式增加 battery_pool"
    )


def _pool_inventory_multiplier(config: dict, pool_key: str, derived_multiplier: float) -> float:
    """【新增】总池容量/装车容量。

    不再默认 1.0：站内电池的 CAPEX 在 capex 中单列，EFC 分母若不含站内电池，
    会系统性高估池均频次、低估寿命。默认按供需恒等式自动派生（derived_multiplier
    由调用方按「本池站数×库存块数×块容量 ÷ 本池装车GWh + 1」算好传入）；
    显式配置 [battery_pool_model.inventory_multiplier.<pool>] 时以配置为准（覆盖自动派生）。
    """
    mapping = config.get("battery_pool_model", {}).get("inventory_multiplier", {})
    multiplier = float(mapping[pool_key]) if pool_key in mapping else derived_multiplier
    if multiplier < 1.0:
        raise ValueError(f"{pool_key} inventory_multiplier={multiplier} 不应小于1.0")
    return multiplier


def _pool_life_config(config: dict, pool_key: str) -> dict:
    """【新增】允许四池分别覆盖循环临界点/日历寿命等参数，但不在代码中拍具体值。

    配置示例：
      [battery_pool_model.life_override.qiji75_short]
      critical_cycles = ...
      calendar_cap_years = ...

    若不配置，则完整沿用原 [battery_life_model]。override 的键名直接透传给
    derived.battery_life_years，因此与原寿命函数保持同一参数体系。
    """
    override = config.get("battery_pool_model", {}).get("life_override", {}).get(pool_key, {})
    if not override:
        return config
    pool_config = dict(config)
    pool_config["battery_life_model"] = {**config["battery_life_model"], **override}
    return pool_config


def _pool_derived_life_years(config: dict, pool_key: str, frequency: float) -> float:
    """【新增】按所属池参数计算寿命；未设置池级参数时等同原 derived 口径。"""
    return derived_battery_life_years(_pool_life_config(config, pool_key), frequency)


def _pool_calendar_cap(config: dict, pool_key: str) -> float:
    """【新增】按所属池参数计算日历寿命。"""
    return float(_pool_life_config(config, pool_key)["battery_life_model"]["calendar_cap_years"])


def _replace_row_life(row: ScaleRow, life_years: float) -> ScaleRow:
    """【新增】兼容 dataclass / Pydantic 的不可变或可变 ScaleRow。"""
    if hasattr(row, "model_copy"):  # Pydantic v2
        return row.model_copy(update={"battery_life_years": life_years})
    if is_dataclass(row):
        return replace(row, battery_life_years=life_years)
    if hasattr(row, "copy"):  # Pydantic v1
        try:
            return row.copy(update={"battery_life_years": life_years})
        except TypeError:
            pass
    setattr(row, "battery_life_years", life_years)
    return row
# -------------------------------新增END-----------------------------------


def _charge_share(config: dict, vehicle_key: str, scenario: str) -> float:
    """充电段CATL市占率：按悲观/中性/乐观直接取档，不再用"份额提升实现率"插值。

    悲观 = 无换电保护、充分竞争下的份额；乐观 = 换电标准锁定后能保持的份额；
    中性 = (悲观+乐观)/2，由程序派生，不手工拍值。
    """
    entry = config.get("charge_share", {}).get(vehicle_key)
    if entry is None:
        pessimistic, optimistic = FALLBACK_CHARGE_SHARE[vehicle_key]
    else:
        pessimistic = entry["pessimistic"]
        optimistic = entry["optimistic"]
    if scenario == "悲观":
        return pessimistic
    if scenario == "乐观":
        return optimistic
    if scenario == "中性":
        return (pessimistic + optimistic) / 2.0
    raise ValueError(f"未知充电段市占率情景 {scenario}")


def _city_stock_layer(config: dict) -> dict:
    """城配存量层（高不确定·单列·不并入 headline）。

    补回自 _archive/重卡与城配物流换电规模测算_合并对比.py v2：
    城配换电2025才起步，存量层基准用 2025 单年 NEV销量(62.8万)；
    换电渗透率极低(2%)、CATL市占率高(80%，少数带换电者走巧克力标准)。
    该存量层与重卡 existing_catl_swap_stock_wan（已是CATL换电存量）不同：
    此处是"历史NEV存量"，需按存量换电渗透率/CATL市占率二次折算，且**单列不并入增量漏斗**。
    """
    city = config["vehicles"].get("city", {})
    nev_stock = city.get("city_existing_nev_stock_wan", 0.0)
    swap_pen = city.get("city_stock_swap_penetration", 0.0)
    catl_share = city.get("city_stock_catl_share", 0.0)
    battery_kwh = city.get("battery_kwh", 81.0)
    if nev_stock <= 0:
        return {}
    stock_swap_veh = nev_stock * swap_pen               # 存量层换电车辆（万辆）
    stock_catl_veh = stock_swap_veh * catl_share        # 存量层进CATL换电车辆（万辆）
    stock_catl_gwh = stock_catl_veh * battery_kwh / 100.0  # 存量层装机（GWh）
    # 频次沿用城配高频子集口径（f = 日均里程 ÷ (背电×余电折扣÷电耗)）
    usable = config["swap_business"]["usable_energy_factor"]
    f = city["daily_km"] / (battery_kwh * usable / city.get("energy_consumption_kwh_km", 0.27))
    return {
        "nev_stock_wan": round(nev_stock, 1),
        "swap_penetration": swap_pen,
        "catl_share": catl_share,
        "catl_swap_vehicles_wan": round(stock_catl_veh, 2),
        "catl_swap_gwh": round(stock_catl_gwh, 2),
        "swap_frequency_per_day": round(f, 2),
        "note": "城配存量层·高不确定·单列不并入 headline 增量（类比 _archive v2 城配C 存量支线）",
    }


def build_scale(
    config: dict,
    sourcing: SourcingAdjustment,
    private_scenario: str = "中枢",
    life_mode: str = "derived",
) -> ScaleResult:
    """private_scenario：私家车分档换电渗透率情景，取 保守/中枢/激进（见 base.toml
    [vehicles.private.scenario_swap_penetration]）。中枢即 scenes 内的默认口径。

    life_mode：电池寿命口径。
      "derived"    = 先按四个电池池汇总使用强度（含站内库存电池），再按[battery_life_model]
                     以循环临界点÷池内EFC强度推算（基准）；
      "legacy_v32" = 沿用v3.2硬编码寿命，仅供附录新旧口径对比重跑，不用于基准结论。
    """
    if life_mode not in ("derived", "legacy_v32"):
        raise ValueError(f"未知寿命口径 {life_mode}")
    legacy_vehicle_life = LEGACY_V32_VEHICLE_LIFE_YEARS
    legacy_station_life = LEGACY_V32_STATION_LIFE_YEARS
    years = config["construction"]["years"]
    stocks = _operating_stocks(config)
    # 私家车三情景：非中枢档时按情景表覆盖各价格带分档的换电渗透率。
    private_scene_pen: dict[str, float] = {}
    if private_scenario != "中枢":
        table = config["vehicles"].get("private", {}).get("scenario_swap_penetration", {})
        if private_scenario not in table:
            raise ValueError(
                f"未知私家车情景 {private_scenario}，可用：{list(table)}"
            )
        private_scene_pen = table[private_scenario]
    # 充电段市占率：直接按悲观/中性/乐观取档（见[charge_share]），不再用实现率插值。
    # 中性档为程序派生的两档均值，基准不再默认取最乐观值。
    charge_scenario = config.get("charge_share", {}).get("scenario", "中性")
    rows: list[ScaleRow] = []

    # 【新增】与 rows 一一对应，记录每条车型×场景属于哪个电池流转池。
    row_pool_keys: list[str] = []
    # 【新增】结束

    operating_stock: dict[str, float] = {}
    annual_swap = {year: 0.0 for year in years}
    annual_charge = {year: 0.0 for year in years}
    annual_no_swap = {year: 0.0 for year in years}
    identity_error = 0.0

    for key, vehicle in config["vehicles"].items():
        operating_stock[key] = 0.0
        share_uplift = sourcing.heavy_share_uplift if vehicle["station_group"] == "heavy" else sourcing.passenger_share_uplift
        existing_stock = vehicle.get("existing_catl_swap_stock_wan", 0.0)
        existing_weights = [
            scene["weight"] * scene["swap_penetration"] * scene["catl_swap_share"]
            for scene in vehicle["scenes"]
        ]
        existing_weight_sum = sum(existing_weights)
        for year_index, year in enumerate(years):
            annual_ev = _annual_ev_wan(vehicle, year_index, stocks)
            for scene_index, scene in enumerate(vehicle["scenes"]):
                ev = annual_ev * scene["weight"]
                swap_penetration = private_scene_pen.get(
                    scene["name"], scene["swap_penetration"]
                ) if private_scene_pen else scene["swap_penetration"]
                charge_penetration = 1.0 - swap_penetration
                identity_error = max(identity_error, abs(swap_penetration + charge_penetration - 1.0))
                catl_swap_share = min(1.0, scene["catl_swap_share"] + share_uplift)
                market_swap = ev * swap_penetration
                market_charge = ev * charge_penetration
                catl_swap = market_swap * catl_swap_share
                # 充电段份额按三档取档（与寿命口径正交；A.2仅对比寿命维度，不混入充电份额变更）。
                catl_charge = market_charge * _charge_share(config, key, charge_scenario)
                # 无换电反事实基准：充电段份额取「中性」档，作用于全市场（swap_pen=0），
                # 与有换电侧充电段（_charge_share(charge_scenario)）同口径派生，不再单列 no_swap_catl_share。
                catl_no_swap = ev * _charge_share(config, key, "中性")
                # 已有CATL换电存量不是本年新车漏斗，按原场景构成分摊到首年累计底座。
                if year_index == 0 and existing_stock and existing_weight_sum:
                    existing_scene_stock = (
                        existing_stock * existing_weights[scene_index] / existing_weight_sum
                    )
                    ev += existing_scene_stock
                    market_swap += existing_scene_stock
                    catl_swap += existing_scene_stock
                gwh_factor = vehicle["battery_kwh"] / 100.0
                # 【修正｜4池口径】换电车装机按场景实际装车电量（重卡短途342/中长途513、
                # 乘用56、城配81），与换电频次分母同源；充电/无换电装机仍按车型均值
                # （battery_kwh，非换电配置不受池约束）。
                onboard_kwh = scene.get("onboard_battery_kwh", vehicle["battery_kwh"])
                frequency = swap_frequency_per_day(
                    vehicle, scene, config["swap_business"]["usable_energy_factor"]
                )
                daily_km = scene["daily_km"] if "daily_km" in scene else vehicle["daily_km"]

                # 【新增】车型/场景先归入四个物理电池池；最终寿命在全部 rows 建完后统一回填。
                pool_key = _battery_pool_key(key, vehicle, scene)
                # 【新增】结束

                row = ScaleRow(
                    year=year,
                    vehicle_key=key,
                    vehicle_label=vehicle["label"],
                    scene=scene["name"],
                    station_group=vehicle["station_group"],
                    battery_pool=pool_key,
                    ev_vehicles_wan=ev,
                    market_swap_vehicles_wan=market_swap,
                    market_charge_vehicles_wan=market_charge,
                    catl_swap_vehicles_wan=catl_swap,
                    catl_charge_vehicles_wan=catl_charge,
                    catl_no_swap_vehicles_wan=catl_no_swap,
                    catl_swap_gwh=catl_swap * onboard_kwh / 100.0,
                    catl_charge_gwh=catl_charge * gwh_factor,
                    catl_no_swap_gwh=catl_no_swap * gwh_factor,
                    battery_kwh=vehicle["battery_kwh"],
                    onboard_battery_kwh=onboard_kwh,
                    swap_frequency_per_day=frequency,
                    daily_km=daily_km,
                    usable_range_km=daily_km / frequency,
                    # 寿命口径：基准按2000次循环临界点÷年循环次数，与日历寿命封顶取min；
                    # derived 模式这里仅放临时值；四池寿命会在汇总后统一回填，
                    # 避免下游误把“车型/场景寿命”当作最终更新周期，
                    # legacy_v32仅用于附录新旧口径对照重跑。
                    battery_life_years=(
                        legacy_vehicle_life[key]
                        if life_mode == "legacy_v32"
                        else derived_battery_life_years(config, frequency)
                    ),
                )
                rows.append(row)

                # 【新增】记录每条车型×场景属于哪个电池流转池
                row_pool_keys.append(pool_key)
                # 【新增】结束

                operating_stock[key] += catl_swap
                annual_swap[year] += row.catl_swap_gwh
                annual_charge[year] += row.catl_charge_gwh
                annual_no_swap[year] += row.catl_no_swap_gwh

    # “毛估估”取整发生在终局车型节点，而不是在漏斗每一层反复取整。
    # 这样既能消除无意义尾差，也不会重演v3把56.25先取57后层层放大的复合偏差。
    vehicle_decimals = config["modeling"]["rounding"]["terminal_vehicle_decimals"]
    frequency_decimals = config["modeling"]["rounding"]["terminal_frequency_decimals"]
    # 【重构｜4站型】日换电需求/私家车需求/年换电电量全部按四池（=四站型）独立累计，
    # 站数按池独立反推；两大类汇总（重卡=短途+中长途、巧克力=乘用+城配）由
    # ScaleResult property 派生，仅供 v3.2 对照与总表，不在本段混算。
    daily_swaps = {pool_key: 0.0 for pool_key in BATTERY_POOLS}
    # 私家车日换电需求单列（全部落在乘用池）：站数反推时先填乘用站物理冗余，溢出才新建站。
    private_daily_swaps = {pool_key: 0.0 for pool_key in BATTERY_POOLS}
    annual_energy_yi = {pool_key: 0.0 for pool_key in BATTERY_POOLS}
    terminal_frequency: dict[str, float] = {}
    days = config["swap_business"]["operating_days"]
    usable = config["swap_business"]["usable_energy_factor"]
    for key, vehicle in config["vehicles"].items():
        relevant = [row for row in rows if row.vehicle_key == key]
        raw_vehicles = sum(row.catl_swap_vehicles_wan for row in relevant)
        raw_frequency = (
            sum(
                row.catl_swap_vehicles_wan * row.swap_frequency_per_day
                for row in relevant
            ) / raw_vehicles
            if raw_vehicles else 0.0
        )
        canonical_vehicles = round(raw_vehicles, vehicle_decimals)
        canonical_frequency = round(raw_frequency, frequency_decimals)
        operating_stock[key] = canonical_vehicles
        terminal_frequency[key] = canonical_frequency
        # 【重构｜4站型】车型可能跨池（重卡短途/中长途分属两池），池级分别按
        # 「池内车辆数×池内加权频次」（各自终局取整）推日需求；车型级取整仅供报告展示。
        for pool_key in sorted({row.battery_pool for row in relevant}):
            pool_rows = [row for row in relevant if row.battery_pool == pool_key]
            pool_raw_vehicles = sum(row.catl_swap_vehicles_wan for row in pool_rows)
            pool_vehicles = round(pool_raw_vehicles, vehicle_decimals)
            pool_raw_freq = (
                sum(
                    row.catl_swap_vehicles_wan * row.swap_frequency_per_day
                    for row in pool_rows
                ) / pool_raw_vehicles
                if pool_raw_vehicles
                else 0.0
            )
            pool_freq = round(pool_raw_freq, frequency_decimals)
            daily = pool_vehicles * 1e4 * pool_freq
            daily_swaps[pool_key] += daily
            if key == "private":
                private_daily_swaps[pool_key] += daily
            # 池内加权装车电量：换电度数与频次分母同源（重卡短途342/中长途513，
            # 不再按车型均值500虚增年电量）。
            pool_onboard = (
                sum(
                    row.catl_swap_vehicles_wan * row.onboard_battery_kwh
                    for row in pool_rows
                ) / pool_raw_vehicles
                if pool_raw_vehicles
                else 0.0
            )
            annual_energy_yi[pool_key] += (
                daily * pool_onboard * usable * days / 1e8
            )

    stations = {}
    capacity_diagnostics = {}
    for pool_key in BATTERY_POOLS:
        # 【重构｜4站型】池键=站型键：站体参数、能力诊断、站数反推全部按本池站型独立进行。
        diagnostics = station_capacity(config, pool_key)
        capacity_diagnostics[pool_key] = diagnostics
        capacity = diagnostics["planning_capacity"]
        category = POOL_STATION_GROUP[pool_key]
        reusable = (
            sourcing.reusable_heavy_stations
            if category == "heavy"
            else sourcing.reusable_choco_stations
        )
        # 大类可复用站拆到池（骐骥按池需求份额拆；巧克力全给乘用池），与存量站拆分同规则。
        split_reusable = split_group_station_count(
            reusable, category, daily_swaps
        )[pool_key]
        demand = daily_swaps[pool_key]
        # 站数反推：营运车需求按规划能力建站；私家车需求先填这些站相对物理上限的冗余，
        # 只有在冗余被填满后才为溢出部分新建站（冗余吸收只发生在乘用池——重卡两池
        # 无私家车，private_daily_swaps 恒为0）。
        # 依据：巧克力站规划300次/日、物理上限552次/日，单站冗余252次/日——
        # 这个冗余本来就是为后续需求（含私家车）预留的，不应让私家车按300重新摊一遍站数。
        private_demand = private_daily_swaps[pool_key]
        base_demand = max(0.0, demand - private_demand)
        base_stations = math.ceil(base_demand / capacity) if base_demand > 0 else 0
        headroom_per_station = max(0.0, diagnostics["physical_limit"] - capacity)
        absorbable = base_stations * headroom_per_station
        overflow = max(0.0, private_demand - absorbable)
        extra_stations = math.ceil(overflow / capacity) if overflow > 0 else 0
        stations[pool_key] = max(0, base_stations + extra_stations - split_reusable)

    # 【删除】不再按 heavy/choco 两个站组计算“站内周转电池寿命”。
    # 原因：站内电池与装车电池属于同一个共享流转池，寿命应按四个实际电池池统一核算。
    # # 站内周转电池寿命同样不再硬编码，且**按使用量加权的使用强度推算**，而非对寿命直接加权。
    # #
    # # 使用量是双因素驱动的：使用频次 × 每次使用的度数。对每类车：
    # #     使用量 = 装机GWh × 换电频次 × 余电折扣
    # # 与计算换电收入时的「换电度数」是同一逻辑（余电折扣为全局常数，归一化时抵消）。
    # #
    # # 物理守恒：池子总装机 ΣGWh 承担总换电需求 Σ(GWh×f)，故每单位装机的等效频次
    # #     f̄ = Σ(GWh×f) / ΣGWh
    # # 再取 life = min(critical_cycles ÷ (f̄ × operating_days), calendar_cap_years)。
    # #
    # # 不可对寿命直接按装机加权：寿命是频次的**倒数**，倒数后再加权会因 Jensen 不等式
    # # 系统性高估（低频的长寿命被放大）。重卡三场景即典型：对寿命加权得3.91年，
    # # 按使用量加权仅3.13年。
    # station_battery_life: dict[str, float] = {}
    # fallback_life = float(config["battery_life_model"]["calendar_cap_years"])
    # for group in ("heavy", "choco"):
    #     if life_mode == "legacy_v32":
    #         station_battery_life[group] = float(legacy_station_life[group])
    #         continue
    #     group_rows = [row for row in rows if row.station_group == group]
    #     gwh_total = sum(row.catl_swap_gwh for row in group_rows)
    #     usage_weighted_freq = (
    #         sum(row.catl_swap_gwh * row.swap_frequency_per_day for row in group_rows) / gwh_total
    #         if gwh_total else 0.0
    #     )
    #     station_battery_life[group] = (
    #         derived_battery_life_years(config, usage_weighted_freq)
    #         if usage_weighted_freq > 0 else fallback_life
    #     )

    # 【新增｜四池口径】对每个池（池键=站型键，4站型独立）：
    #   车辆侧换电需求强度 = Σ(装车GWh × 日均换电频次)
    #   池站内库存GWh     = 本池终局站数 × 本池库存块数 × 块容量（站数已按池独立反推，
    #                       供需恒等：站数×站日接待能力 = 池车日换电次数，无需份额拆分）
    #   总池容量          = Σ装车GWh × inventory_multiplier（=装车 + 站内库存）
    #   池均等效频次 f_bar = 车辆侧换电需求强度 / 总池容量
    #   life               = min(critical_cycles ÷ (f_bar × operating_days), calendar_cap)
    #
    # inventory_multiplier 按供需恒等式自动派生：站端配比=池站内电池GWh÷池装车GWh，
    # multiplier=站端配比+1。站内电池的 CAPEX 在 capex 中按同一站数登记付钱，
    # EFC 分母与 CAPEX 口径自动互洽（不存在"付了站内电池的钱、分母却不含站内电池"的偏差）。
    battery_pool_life: dict[str, float] = {}
    pool_vehicle_gwh: dict[str, float] = {pool_key: 0.0 for pool_key in BATTERY_POOLS}
    pool_usage: dict[str, float] = {pool_key: 0.0 for pool_key in BATTERY_POOLS}
    for row, row_pool in zip(rows, row_pool_keys):
        pool_vehicle_gwh[row_pool] += row.catl_swap_gwh
        pool_usage[row_pool] += row.catl_swap_gwh * row.swap_frequency_per_day

    for pool_key in BATTERY_POOLS:
        if life_mode == "legacy_v32":
            legacy_group = POOL_STATION_GROUP[pool_key]
            battery_pool_life[pool_key] = float(legacy_station_life[legacy_group])
            continue

        station = config["stations"][pool_key]
        pool_station_gwh = (
            stations[pool_key] * station["inventory_blocks"] * station["block_kwh"] / 1e6
        )
        vehicle_gwh = pool_vehicle_gwh[pool_key]
        derived_multiplier = (
            1.0 + pool_station_gwh / vehicle_gwh if vehicle_gwh > 0 else 1.0
        )
        inventory_multiplier = _pool_inventory_multiplier(config, pool_key, derived_multiplier)
        total_pool_gwh = vehicle_gwh * inventory_multiplier

        pooled_frequency = pool_usage[pool_key] / total_pool_gwh if total_pool_gwh else 0.0

        battery_pool_life[pool_key] = (
            _pool_derived_life_years(config, pool_key, pooled_frequency)
            if pooled_frequency > 0
            else _pool_calendar_cap(config, pool_key)
        )

    # 【修改】derived 模式下，每条 row 统一继承所属电池池寿命。
    # 这样出租/网约/Robotaxi/私家车不会各自形成独立更新周期；
    # 它们只是共同决定 choco25_passenger 池的使用强度。
    if life_mode == "derived":
        rows = [
            _replace_row_life(row, battery_pool_life[pool_key])
            for row, pool_key in zip(rows, row_pool_keys)
        ]
    # 【新增】结束

    return ScaleResult(
        years=years,
        rows=rows,
        operating_stock_by_vehicle_wan=operating_stock,
        terminal_frequency_by_vehicle=terminal_frequency,
        annual_catl_swap_gwh=annual_swap,
        annual_catl_charge_gwh=annual_charge,
        annual_catl_no_swap_gwh=annual_no_swap,
        target_station_demand=stations,
        mature_daily_swaps=daily_swaps,
        mature_annual_energy_yi_kwh=annual_energy_yi,
        station_capacity_diagnostics=capacity_diagnostics,
        route_identity_error=identity_error,
        battery_pool_life_years=battery_pool_life,
        city_stock_layer=_city_stock_layer(config),
    )

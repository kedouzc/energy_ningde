# 换电战略决策模型 v4.3 — 骨架报告（数据层）

> 本报告由 `$model_name` 自动生成，是**骨架版**：只含必答问题与数据表，不含叙述论证。
> 三层分工：**叙述层**住在 [MANIFEST.md](../MANIFEST.md)（唯一事实源）；
> **必答问题层**在下方第一章；**数据层**为第二章程式化明细表。
> 正文所有数字来自 `outputs/decision_snapshot_v4_3.json`（`python src/run.py` 可复算）；
> 叙述层数字用 `python src/backscan.py` 回扫校验，防止叙述与模型脱钩。

## 版本说明

| 版本 | 定位 |
|---|---|
| v4.2 及以前 | 叙述长文模板（冻结于 v4_2 目录，含完整论证文本） |
| v4.3（本版） | 模板降级为骨架＋必答问题；论证与叙述移驻 MANIFEST.md |

---

## 一、必答问题层：换电要做多透？

**决策问题**：换电必做（定性已决，见 MANIFEST §1.0），定量只回答"做透到什么程度"——
做多大规模、花多少钱、换回多少价值、占用集团多大资金盘子。

### Q1 做透的规模

$qa_scale_table

### Q2 做透的代价

$qa_cost_table

### Q3 换回的价值

$qa_value_table

### Q4 资金从容度

$qa_funding_table

---

## 二、数据层：明细表

### 2.1 车辆底座（四类车异构推算）

**车辆底座大表（场景级，营运车在前、私家车在后）**

$vehicle_base_table

$vehicle_base_note

**各年车辆底座（车型×年份，含5年汇总）**

$vehicle_year_table

**四池底座汇总（4类车各用各站、电池不混流）**

$pool_base_table

$annual_scale_table

$private_scenario_table

### 2.2 站点层（站数反推与单站经济）

$station_demand_table

$station_economics_table

### 2.3 CAPEX 与资本因子

$capex_table

$capex_summary

$capital_factor_table

$required_ebitda_table

### 2.4 运营层（收入—成本—EBITDA 链）

$operating_table

$cash_return_table

### 2.5 制造与动力电池总账（对照实验）

$manufacturing_table

$power_total_table

$bridge_table

### 2.6 资金与战略敞口

$funding_table

$commitment_table

$exposure_table

### 2.7 敏感性与口径对照

$sensitivity_table

$life_mode_comparison_table

---

## 附录

### A.1 参数登记表

$parameter_table

### A.2 信源索引

$source_table

### A.3 v3.2 → v4.3 口径审计

$v32_audit_table

$v32_outcome_audit_table

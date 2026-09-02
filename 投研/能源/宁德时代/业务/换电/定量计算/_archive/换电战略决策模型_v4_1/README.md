# 换电战略决策模型 v4.1

本目录是独立于旧版大脚本、且独立于v4.0的校准版本。旧Python、旧MD与v4.0均不参与v4.1运行；旧报告只作为方法链和参数差异的审计基准，不作为结果校准锚。

## 数据流

`configs/base.toml → scale → capex → business → consolidation → capital_cycle/group_constraints → decision → report`

- `base.toml`：只存外生参数、来源和研究情景，不存派生结果。
- `scale.py`：生成唯一的车辆、充换电路线、CATL市占、装机和交易量底座。
- `derived.py`：由价格曲线、寿命、物理参数推导电池价格、EAC/残值、换电频次与单站能力。
- `capex.py`：按批次生成建设期年度CAPEX、更新计划、等效全周期资本底座及CRF资本要求。
- `business.py`：分别计算换电正算、CRF要求回报和制造线回报。
- `consolidation.py`：生成2026E、2030E无换电和2030E重资产换电总账，并区分完整情景差额与部门可归因价值。
- `capital_cycle.py`：比较成熟后的权益档、回款、持续价值、资管平台和未来资本释放。
- `group_constraints.py`：扣除分红、回购、已承诺投资、换电和并购后的集团资金上限。
- `model.py`：接入并购扰动并组装统一决策快照。
- `report.py`：使用无业务结果数字的模板生成MD、JSON和Dashboard参数注册表。

## 运行

在本目录执行 `python run.py`。生成物包括：

- `outputs/decision_snapshot_v4_1.json`
- `outputs/dashboard_parameter_registry_v4_1.json`
- `分析结论/换电毛估估_战略投入产出与资本循环_v4.1.md`

## 测试

执行 `python -B -m unittest discover -s tests -v`。测试覆盖路线恒等式、站数勾稽、价值桥、权益情景、参数传导以及旧版结果锚隔离。

## Dashboard接口

Dashboard不应重写任何公式，只读取参数注册表、修改配置副本、重新调用 `build_model()`，再展示新的决策快照。这样MD、静态HTML和未来交互界面共享同一套计算内核。

## 版本历史

- v4.0：模块化重构与自动报告首版。
- v4.1：校准城配车辆取整、2025年末存量站、站数对EBITDA传导、期末残值、可分派现金、滚动AUM、集团CFO和并购债务口径；报告按“问题—方法—参数—推导—判断—敏感性—拍板”重写。

逐项变更见 [CHANGELOG.md](CHANGELOG.md)。

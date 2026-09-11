# 口径/ —— 每份文档服务哪几个收口读数

> **准入判据**（`交接.md` §5.5，本目录的存废就看这一条）：
>
> **每一份口径文档必须能指名道姓说出「我服务的是报告里的哪几个数」。**
> 说不出来的，它就是按**来源**组织的、不是按**用途**组织的——降级为素材，等章来点名。
>
> 2026-09-11 补齐本表：五份文档一对一挂到 `configs/report_map.toml` 的收口读数上。
> **改口径文档前先查这里**：它服务的读数变了，就是口径变了，要同步改索引表。

## 一、五份文档的归属

| 文档 | 服务哪一章 | 服务哪几个**收口**读数 | 涉及哪些**支撑**读数 |
|---|---|---|---|
| `capex_debt_估值公式链.md` | 4 可行性 · 6 冲击与重估 | `swap.coverage`、`capex.peak_call`、`val.op_ev_multiple`、`val.ev_dcf_perpetual` | `capex.initial_capex`、`capex.project_debt`、`capex.lifecycle_base` |
| `TCO口径_JPM整套引用.md` | 3 目标市场 | `tco.swap_wan`（含 N1/N2 两个持有期共 12 个）、`ops.veh_ops` | `tco.lng_wan`、`tco.diesel_wan`、`ops.heavy_market_stock`、`ops.heavy_pen_pct` |
| `车辆与站数_推算方法.md` | 3 目标市场 · 4 可行性 | `ops.veh_ops`、`ops.veh_heavy`、`scale.stations_total` | `ops.market_total`、`ops.share_of_market`、`ops.veh_city`、`ops.veh_passenger_ops` |
| `运营收入与成本_口径.md` | 5 阶段性业绩 | `swap.revenue`、`swap.ebitda` | `ops.annual_energy`、`swap.service_rev`、`swap.rent_rev`、`swap.ancillary` |
| `终局处置_出表与轻资产化.md` | 4 可行性 · 6 冲击与重估 | `capex.peak_call`、`val.reit_multiple`、`val.op_ev_multiple` | `fund.peak_cash_to_cfo`、`fund.closing_liquidity` |

> 收口读数（1–2 个／章）＝这章要**证明**的数；支撑读数（5–10 个／章）＝论证中**引用**的数。
> 两者的区分见 `configs/report_map.toml` 的注释与 `框架提案.md` §1.1.1。

## 二、计算层与判断层的分界（2026-09-11 定）

v3.2 §211–816 那条完整链路（车辆数五层漏斗 → 单站能力 → 站数 → CAPEX → 门槛 EBITDA →
可交付 EBITDA → SOTP → 增量价值）在报告里**不是一个整体**，要拆成两层归位：

| 层 | 内容 | 归哪 | 为什么 |
|---|---|---|---|
| **计算层** | 谁由谁算出来、公式与中间量 | **⑥ 决策树下钻**（`tree.py`，166 节点） | 树装得了计算，且能自动派生、不会与代码脱钩 |
| **判断层** | 为什么这么定口径、为什么取这个值不取那个 | **八章正文 + 本目录的文档** | 树装不了判断。例如"站数取反推值而非规划值""辅助服务三项不能相加" |

**这条分界的直接用途**：一页纸只放终端读数，不补完整计算链路（补了就失去"能对账"的
价值）；想看链路的人点下钻，想看"凭什么这么算"的人读正文与口径文档。

## 三、写新口径文档前先答三句

1. 我服务的是**哪几个收口读数**（写 key，不写中文名）？
2. 我论证的是**计算**（怎么算）还是**判断**（为什么这么定）？判断类必须能说出一个
   可观察的推翻条件。
3. 我的数字是**外部信源**（带可点击链接与抓取日期）还是**经验假设**（须显式标注）？

三句答不出来 → 先别建这份文档，它是素材不是口径。

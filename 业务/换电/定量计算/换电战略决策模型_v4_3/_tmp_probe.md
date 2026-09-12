# MD 占位符溯源（一次性核对）

| 占位符 | 渲染值 | 走哪条路 | 在字典里的对应 
|---|---|---|---|
| EBITDA | 1,308.2亿元 | 字典中文名→字典 key | swap.ebitda |
| EBITDA覆盖倍数 | 1.17× | 字典中文名→字典 key | swap.coverage |
| base.catl_blended_share | 16% | facts 手写事实 | —｜字典里没有这条 |
| base.cfo_gate | 15% | facts 手写事实 | —｜字典里没有这条 |
| base.debt_ratio | 60% | facts 手写事实 | —｜字典里没有这条 |
| base.equity_share | 40% | facts 手写事实 | 建站持股比例｜✓ 已机械断言同值 |
| base.ev_ebitda | 18× | facts 手写事实 | 拍定EV/EBITDA倍数｜✓ 已机械断言同值 |
| base.group_mktcap | 20,000亿元 | facts 手写事实 | 集团市值基准（A+H）｜✓ 已机械断言同值 |
| base.horizon_years | 15年 | facts 手写事实 | —｜字典里没有这条 |
| base.mfg_pe | 20× | facts 手写事实 | —｜字典里没有这条 |
| base.target_year | 2,030 | facts 手写事实 | 终局年｜字典自家 key |
| base.wacc | 7.5% | facts 手写事实 | —｜字典里没有这条 |
| dcf.bet | 5,338.0亿元 | facts 手写事实 | 押注的那部分（倍数法归属 − 现金流口径归属）｜✓ 已机械断言同值 |
| dcf.catl_true | 3,129.4亿元 | facts 手写事实 | CATL归属·DCF有限期｜✓ 已机械断言同值 |
| dcf.fcff | 1,115.0亿元 | facts 手写事实 | 成熟期 FCFF｜✓ 已机械断言同值 |
| dcf.mult_crf | 5.68× | facts 手写事实 | DCF法隐含EBITDA倍数｜✓ 已机械断言同值 |
| ext.baas_capex_cut | 40–50% | facts 手写事实 | —｜字典里没有这条 |
| ext.batt_share_of_truck | 40–50% | facts 手写事实 | —｜字典里没有这条 |
| ext.elec_2030 | 135,000亿kWh | facts 手写事实 | —｜字典里没有这条 |
| ext.elec_latest | 103,682亿kWh | facts 手写事实 | —｜字典里没有这条 |
| ext.lng_price_rise | +48% | facts 手写事实 | —｜字典里没有这条 |
| ext.mult_byd | 6.5× | facts 手写事实 | —｜字典里没有这条 |
| ext.mult_catl_self | 13.0× | facts 手写事实 | —｜字典里没有这条 |
| ext.mult_gp_high | 22× | facts 手写事实 | —｜字典里没有这条 |
| ext.mult_gp_low | 18× | facts 手写事实 | —｜字典里没有这条 |
| ext.mult_infra_high | 14× | facts 手写事实 | —｜字典里没有这条 |
| ext.mult_infra_low | 6.7× | facts 手写事实 | —｜字典里没有这条 |
| ext.mult_tsla | 89.7× | facts 手写事实 | —｜字典里没有这条 |
| ext.pack_400kwh_price | 30–40 万元 | facts 手写事实 | —｜字典里没有这条 |
| ext.payload_loss_ev | 7 万元/年 | facts 手写事实 | —｜字典里没有这条 |
| ext.revenue_uplift_per_truck | 约 4 万元/年 | facts 手写事实 | —｜字典里没有这条 |
| ext.storage_gwh_2025 | 351GWh | facts 手写事实 | —｜字典里没有这条 |
| ext.storage_gwh_2030 | 780GWh | facts 手写事实 | —｜字典里没有这条 |
| ext.tco_ev_vs_diesel_5y | −25% | facts 手写事实 | —｜字典里没有这条 |
| ext.tco_ev_vs_lng_3y | −4% | facts 手写事实 | —｜字典里没有这条 |
| ext.tco_ev_vs_lng_5y | −11% | facts 手写事实 | —｜字典里没有这条 |
| fact_key | 读不到 | — | 两种路径都找不到（多为文档里的示例写法） |
| key | 读不到 | — | 两种路径都找不到（多为文档里的示例写法） |
| op.equity_gross | 21,168.5亿元 | facts 手写事实 | 运营项目权益价值（100%口径）｜✓ 已机械断言同值 |
| op.ev_multiple | 23,547.5亿元 | facts 手写事实 | 运营企业价值 EV（倍数法，100%口径）｜✓ 已机械断言同值 |
| op.net_profit | 534.9亿元 | facts 手写事实 | 运营净利润（项目100%口径）｜✓ 已机械断言同值 |
| q1.energy | 2,253.6亿kWh | facts 手写事实 | 年换电交易电量｜✓ 已机械断言同值 |
| q1.gwh_station | 34.7GWh | facts 手写事实 | 换电装机保有量·站内周转｜✓ 已机械断言同值 |
| q1.gwh_total | 574.0GWh | facts 手写事实 | —｜字典里没有这条 |
| q1.gwh_vehicle | 574.2GWh | facts 手写事实 | 换电装机保有量·车端｜✓ 已机械断言同值 |
| q1.veh_ops | 249.8万辆 | facts 手写事实 | 终局覆盖·营运车合计｜✓ 已机械断言同值 |
| q1.veh_total | 394.2万辆 | facts 手写事实 | 终局覆盖车辆合计｜✓ 已机械断言同值 |
| q2.capex_initial | 3,980.6亿元 | facts 手写事实 | 终局初装CAPEX｜✓ 已机械断言同值 |
| q2.lifecycle_base | 6,489.4亿元 | facts 手写事实 | 全周期资本底座（现值）｜✓ 已机械断言同值 |
| q2.peak_year | 2030年 | facts 手写事实 | 峰值年｜✓ 已机械断言同值 |
| q2.project_debt | 3,893.7亿元 | facts 手写事实 | 项目债务｜✓ 已机械断言同值 |
| src.gov_storage_2030 | [国务院顶层文件（2030 新型储能装机 3 亿千瓦；等效 2.6h 折算 78… | facts 手写事实 | —｜字典里没有这条 |
| src.nea_elec_2025 | [国家能源局：2025 年全社会用电量 103,682 亿千瓦时（同比 +5.0… | facts 手写事实 | —｜字典里没有这条 |
| src.nea_storage_2026 | [国家能源局《中国新型储能发展报告（2026）》（2025 全国新型储能累计装机… | facts 手写事实 | —｜字典里没有这条 |
| src.society_elec_2030 | [国网能源院预测：2030 年全国全社会用电量 13.5 万亿千瓦时（权威媒体转… | facts 手写事实 | —｜字典里没有这条 |
| src.xxx | 读不到 | — | 两种路径都找不到（多为文档里的示例写法） |
| thr.bet_high | 70.0% | facts 手写事实 | —｜字典里没有这条 |
| thr.min_coverage | 1.00倍 | facts 手写事实 | —｜字典里没有这条 |
| thr.min_incr_pct | 10.0% | facts 手写事实 | —｜字典里没有这条 |
| thr.min_increment_yi | 1,000亿元 | facts 手写事实 | —｜字典里没有这条 |
| thr.target_incr_pct | 20.0% | facts 手写事实 | —｜字典里没有这条 |
| 制造侧增量价值 | 1,236.3亿元 | 字典中文名→字典 key | val.mfg_increment |
| 占位符 | 读不到 | — | 两种路径都找不到（多为文档里的示例写法） |
| 可归因换电增量价值 | 读不到 | — | 两种路径都找不到（多为文档里的示例写法） |
| 年换电交易电量 | 2,253.6亿kWh | 字典中文名→字典 key | ops.annual_energy |
| 换电增量价值合计 | 9,703.7亿元 | 字典中文名→字典 key | val.swap_increment |
| 终局年 | 2,030 | 字典中文名→字典 key | base.target_year |
| 运营OPEX | 133.9亿元 | 字典中文名→字典 key | swap.opex |
| 运营侧直接增量（CATL归属） | 8,467.4亿元 | 字典中文名→字典 key | val.op_value |
| 运营年收入 | 1,442.1亿元 | 字典中文名→字典 key | swap.revenue |

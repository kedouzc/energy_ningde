# 全面审计报告：数到底读不读得到

## A 输出字典 configs/metrics.toml
条目总数：121
A1 依赖 cfg 的条目：6 条（build.py 用 read_metrics(snapshot) 不带 cfg → 这些全是 NaN）
    - base.target_year                   终局年
    - base.power_shipments_2026e         2026E动力电池出货
    - base.ev_ebitda_multiple            拍定EV/EBITDA倍数
    - base.ownership_pct                 建站持股比例
    - ops.heavy_market_stock             重卡保有量
    - ops.heavy_repl_cycle               重卡更新周期
A2 带 cfg 也取不到值（NaN）的条目：0 条
A3 source 定位存疑（说明 source 写错，或该数不在它声称的程序里）：13 条
    - val.reit_multiple                  「reit_multiple」在 src/capital_cycle.py 里找不到
    - tco.swap_wan                       「swap_wan」在 src/tco.py 里找不到
    - tco.swap_kwh                       「swap_kwh」在 src/tco.py 里找不到
    - tco.lng_wan                        「lng_wan」在 src/tco.py 里找不到
    - tco.lng_kwh                        「lng_kwh」在 src/tco.py 里找不到
    - tco.diesel_wan                     「diesel_wan」在 src/tco.py 里找不到
    - tco.diesel_kwh                     「diesel_kwh」在 src/tco.py 里找不到
    - tco.swap_wan_9                     「swap_wan」在 src/tco.py 里找不到
    - tco.swap_kwh_9                     「swap_kwh」在 src/tco.py 里找不到
    - tco.lng_wan_9                      「lng_wan」在 src/tco.py 里找不到
    - tco.lng_kwh_9                      「lng_kwh」在 src/tco.py 里找不到
    - tco.diesel_wan_9                   「diesel_wan」在 src/tco.py 里找不到
    - tco.diesel_kwh_9                   「diesel_kwh」在 src/tco.py 里找不到
A4 key 重复 0 条　label 重复 0 条

## B 事实包 src/facts.py
B1 key 重复定义（后者覆盖前者，前者写的口径白写）：0 条
B2 取不到值／值是 NaN：0 条
B3 mirror 指向的 key 不在输出字典（onepager 检查④会静默跳过）：0 条
B4 镜像值与字典不一致（两条取数路径给出两个数）：0 条
B5 facts.json 里值是 NaN 的条目：0 条（渲染出来是 nan＋单位）
B6 与字典同值同单位、却未声明镜像的手写事实（隐性双胞胎）：0 条


## C 占位符：所有能写 {{...}} 的文件
### _tmp_audit_report.md　占位符 1 个，出口=无（不在任何检查里）
    - ... → 找不到

### DECISIONS.md　占位符 5 个，出口=无（不在任何检查里）
    - a.b.c → 找不到
    - src.xxx → 找不到
    - target_year → 找不到

### narrative\chapters\README.md　占位符 2 个，出口=无（不在任何检查里）
    - src.xxx → 找不到
    - 占位符 → 找不到

### narrative\README.md　占位符 5 个，出口=无（不在任何检查里）
    - key → 找不到
    - 可归因换电增量价值 → 找不到

### narrative\topics\业务本质_第一性原理拆解.src.md　占位符 2 个，出口=inject/check
    - 全部可解析

### narrative\topics\估值_为什么拍这个倍数.src.md　占位符 14 个，出口=inject/check
    - 全部可解析

### narrative\topics\目标用户_谁的痛点.src.md　占位符 7 个，出口=inject/check
    - 全部可解析

### narrative\一页纸.md　占位符 48 个，出口=无（不在任何检查里）
    - fact_key → 找不到
    - src.xxx → 找不到

### README.md　占位符 1 个，出口=无（不在任何检查里）
    - q3.increment → 找不到

### review-plan_claude_20260907.md　占位符 9 个，出口=无（不在任何检查里）
    - a.b.c → 找不到
    - key → 找不到
    - src.xxx → 找不到
    - target_year → 找不到
    - vehicles.heavy.stock_wan → 找不到

### sandbox-ux-draft.md　占位符 1 个，出口=无（不在任何检查里）
    - a.b.c → 找不到

### 交接.md　占位符 8 个，出口=无（不在任何检查里）
    - gate.econ.flip_value → 找不到
    - gate.econ.margin → 找不到
    - q3.coverage → 找不到
    - q3.xxx → 找不到
    - src.xxx → 找不到
    - token → 找不到
    - 中文名 → 找不到

### 口径\车辆与站数_推算方法.md　占位符 1 个，出口=无（不在任何检查里）
    - ... → 找不到

### 框架提案.md　占位符 5 个，出口=无（不在任何检查里）
    - val.xxx → 找不到
    - 中文名 → 找不到

### 研究项目约定.md　占位符 1 个，出口=无（不在任何检查里）
    - a.b.c → 找不到

### C1b 在叙述/一页纸里仍以「手写事实 key」形式出现的占位符：35 个
base.catl_blended_share、base.cfo_gate、base.debt_ratio、base.equity_share、base.ev_ebitda、base.group_mktcap、base.horizon_years、base.mfg_pe、base.wacc、dcf.bet、dcf.catl_true、dcf.fcff、dcf.mult_crf、ext.elec_2030、ext.elec_latest、ext.storage_gwh_2025、ext.storage_gwh_2030、op.equity_gross、op.ev_multiple、op.net_profit、q1.energy、q1.gwh_station、q1.gwh_total、q1.gwh_vehicle、q1.veh_ops、q1.veh_total、q2.capex_initial、q2.lifecycle_base、q2.peak_year、q2.project_debt、thr.bet_high、thr.min_coverage、thr.min_incr_pct、thr.min_increment_yi、thr.target_incr_pct

### C2 浏览器/一页纸线路（无敏感性表与三情景表）下解析不了的占位符
共 17 个：...、a.b.c、src.xxx、target_year、占位符、key、可归因换电增量价值、fact_key、q3.increment、vehicles.heavy.stock_wan、gate.econ.flip_value、gate.econ.margin、q3.coverage、q3.xxx、token、中文名、val.xxx

### C3 已渲染 outputs/*.md 里的残留问题

### C4 定义了但没人引用的事实：65 条
base.rev_2025a、base.np_2025a、base.cash_2025a、base.group_np、base.group_pe、base.power_value_2026、q1.st_heavy、q1.st_heavy_short、q1.st_heavy_trunk、q1.st_choco、q1.st_choco_pass、q1.st_choco_city、q1.veh_heavy、q1.veh_city、q1.veh_taxi、q1.veh_ridehail、q1.veh_robotaxi、q1.veh_private、q2.eac_factor、q2.equity_call、q2.peak_call、q2.commitment、q2.external_equity、dcf.ev_crf、dcf.ev_wacc、dcf.mult_wacc、dcf.premium、dcf.npv、dcf.catl_value、q4.peak_to_cfo、q4.closing_liquidity、q4.min_reserve、q4.exposure、q4.verdict、sens.private_low、sens.private_mid、sens.private_high、sens.increment_low、sens.increment_high、sens.coverage_low、sens.coverage_high、sens.ev14、sens.ev18、sens.ev22、sens.ev25、sens.fee_low、sens.fee_low_cov、sens.batt_high、sens.margin_zero、sens.ev14_x、sens.ev18_x、sens.ev22_x、sens.ev25_x、thr.bet_low、thr.max_premium、op.catl_net_profit、dcf.ev_true、dcf.ev_perpetual、dcf.catl_perpetual、q2.nominal_total、q1.st_total、mk.share_storage_2025、mk.share_storage_2030、mk.share_elec_latest、mk.share_elec_2030

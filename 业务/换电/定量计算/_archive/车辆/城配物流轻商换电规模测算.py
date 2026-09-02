"""
城配物流轻型商用车（轻卡/微卡/轻客）换电规模测算
================================================================
测算口径：2026–2030 年宁德时代(CATL)在城配物流轻商换电市场的装车规模（带电量 + 车辆数）
框架来源：复刻《重卡HDT换电规模测算.xlsx》/ 重卡HDT换电规模测算.py 的存量+增量逻辑

适用性说明（重卡框架 → 轻商）：
  - 链路一致：总销量 → NEV渗透率(S曲线) → 换电渗透率 → CATL市占率 → 单车带电量 → 装机
  - 差异点：轻商按 轻卡 / 微卡 / 轻客 三个品类分别测算（带电量、渗透率、换电适用性差异大），
    每品类独立跑"存量+增量"，最后汇总。测算为毛估估，量级自洽即可。

阅读顺序：
  1) 存量部分：2025 年已售 NEV 中换电+CATL 份额（2025 年换电轻商刚起步，占比极小）
  2) 增量部分：2026–2030 新车 → 各品类总销量 → NEV总销量 → 换电渗透率 → CATL份额 → 装机
  3) 汇总：总装机 = 存量 + 增量；总车辆 = 存量 + 增量

改参数只动 CONFIG，其余为复刻公式，无需修改。
"""

# ============================================================
# CONFIG —— 参数区（集中放置，改这里即可调整测算）
# ============================================================

CONFIG = {
    "测算年限_年": 5,   # 2026-2030 共 5 年

    # ============================================================
    # 品类参数：轻卡（城配主力）/ 微卡 / 轻客
    # 每品类字段说明：
    #   stock_nev_sales_2025  2025年NEV销量(万辆)【外部信源】→ 存量部分直接输入NEV销量
    #                         （与重卡框架D8一致；轻卡202.4万辆为产销口径含出口，
    #                          与渗透率口径不一致，故不采用"销量×渗透率"）
    #   stock_swap_pen    2025年换电渗透率【经验假设：2025年换电轻商刚起步(江淮2025-07联调)】
    #   catl_share        CATL市占率（换电场景）【新能源物流车电池54.5%+换电生态主导，经验上调】
    #   battery_kwh       换电版单车带电量(kWh)【外部信源/经验】
    #   fleet_2030        2030年保有量(万辆)【估算：年销量×更新周期量级】
    #   renewal_years     更新周期(年)【法规报废年限10-15年取中】
    #   nev_pen_2026~30   NEV渗透率 S 曲线逐年值【外部信源/插值】→ 均值用于增量
    #   increment_swap_pen 增量阶段换电渗透率【外部信源/经验假设】
    # ============================================================
    "品类": [
        {
            "name": "轻卡",   # 城配主力，换电核心场景
            # ---- 存量部分 ----
            "stock_nev_sales_2025": 15.7, # 2025年新能源轻卡销量(万辆)。第一商用车网：全年15.7万辆、同比+64%
                                          #   https://news.yiche.com/hao/wenzhang/106814090/
                                          #   （渗透率1-11月29.56%、12月41.65%）
                                          #   https://weibo.com/ttarticle/p/show?id=2309405244429425836113
            "stock_swap_pen": 0.02,       # 2025年换电渗透率【经验假设】江淮巧克力换电2025-07才联调成功、年底才批量交付
                                          #   https://m.ithome.com/html/867506.htm
            "catl_share": 0.60,           # CATL市占率【新能源物流车电池宁德54.5%居首(电车资源/界面新闻)
                                          #   https://m.jiemian.com/article/13924462.html
                                          #   + 换电是宁德巧克力生态主导(地上铁/中燃/极兔合作)，经验上调至60%】
            "battery_kwh": 81,            # 换电版带电量(kWh)。江淮EV5/恺达EX6/坤鹏ET9均为81度
                                          #   https://www.bitauto.com/article/1003110990370/
            # ---- 增量部分 ----
            "fleet_2030": 2000,           # 2030年轻卡保有量(万辆)【估算】年销约200万×更新周期10年
                                          #   (公安部载货汽车保有量约3300万辆量级，扣除重卡/中卡/微卡后粗估)
            "renewal_years": 10,          # 更新周期(年)。法规报废年限10-15年取中
                                          #   https://baike.pcauto.com.cn/344010.html
            "nev_pen_2026": 0.34,         # 2026年NEV渗透率。乘联分会预计轻卡34%
                                          #   https://baijiahao.baidu.com/s?id=1865607949451635069
            "nev_pen_2027": 0.40,         # （插值）
            "nev_pen_2028": 0.47,         # （插值）
            "nev_pen_2029": 0.53,         # （插值）
            "nev_pen_2030": 0.60,         # 2030年微轻型货车NEV渗透率60%（师建华/中汽协）
                                          #   https://baijiahao.baidu.com/s?id=1821573072861707087
            "increment_swap_pen": 0.225,  # 增量换电渗透率。城配轻卡20-25%走换电取中值（本文件核心结论）
                                          #   对应里程分布：200-300km占20%+300-400km占10%的高频子场景
        },
        {
            "name": "微卡",
            # ---- 存量部分 ----
            "stock_nev_sales_2025": 4.0,  # 2025年新能源微卡销量(万辆)【估算】电车资源：新能源微小卡总销量超12万辆
                                          #   （其中小卡81952辆、同比+65.8%），扣除小卡后微卡约4万辆
                                          #   https://www.evpartner.com/news/262/detail-82356.html
            "stock_swap_pen": 0.01,       # 2025年换电渗透率【经验假设】微卡里程短、几乎无换电
            "catl_share": 0.50,           # CATL市占率【经验假设】同新能源物流车电池格局略降
            "battery_kwh": 56,            # 换电版带电量(kWh)。江淮Van宝路56度
                                          #   https://www.bitauto.com/article/1003110990370/
            # ---- 增量部分 ----
            "fleet_2030": 500,            # 2030年微卡保有量(万辆)【估算】年销约43万×更新周期~12年
            "renewal_years": 12,          # 更新周期(年)。微卡价格低、更耐用，比轻卡略长
            "nev_pen_2026": 0.32,         # 2026年NEV渗透率。乘联分会预计小卡32%
                                          #   https://baijiahao.baidu.com/s?id=1865607949451635069
            "nev_pen_2027": 0.38,         # （插值）
            "nev_pen_2028": 0.43,         # （插值）
            "nev_pen_2029": 0.47,         # （插值）
            "nev_pen_2030": 0.50,         # （插值，向微轻型货车60%收敛但微卡基数低）
            "increment_swap_pen": 0.05,   # 增量换电渗透率【经验假设】微卡里程短、换电经济性差，取5%
        },
        {
            "name": "轻客",
            # ---- 存量部分 ----
            "stock_nev_sales_2025": 30.0, # 2025年新能源轻客销量(万辆)。方得网：全年超30万辆、渗透率超64%
                                          #   https://www.cvworld.cn/news/Onedata/260129/236395.html
            "stock_swap_pen": 0.01,       # 2025年换电渗透率【经验假设】轻客以客货两用/微面为主，换电少
            "catl_share": 0.50,           # CATL市占率【经验假设】
            "battery_kwh": 60,            # 换电版带电量(kWh)【经验假设】轻客主流电池60-100度取低档
                                          #   （江铃E路达100度充电版为参考，换电版小电量）
                                          #   https://news.yiche.com/hao/wenzhang/91025587/
            # ---- 增量部分 ----
            "fleet_2030": 500,            # 2030年轻客保有量(万辆)【估算】年销约45万×更新周期~11年
            "renewal_years": 10,          # 更新周期(年)。法规报废年限10-15年取中
            "nev_pen_2026": 0.75,         # 2026年NEV渗透率。乘联分会预计轻客75%
                                          #   https://baijiahao.baidu.com/s?id=1865607949451635069
            "nev_pen_2027": 0.78,         # （插值）
            "nev_pen_2028": 0.80,         # （插值）
            "nev_pen_2029": 0.83,         # （插值）
            "nev_pen_2030": 0.85,         # （插值，轻客电动化已过拐点、趋稳）
            "increment_swap_pen": 0.05,   # 增量换电渗透率【经验假设】轻客城配换电场景少，取5%
        },
    ],
}

# ============================================================
# 计算逻辑（无需修改，复刻重卡框架）
# ============================================================

def compute_category(c: dict, years: int):
    """对单个品类跑 存量+增量 逻辑，返回该品类的明细。"""
    R = {}

    # ---- 存量部分（2025 年已售 NEV 中换电+CATL 份额）----
    # 存量换电车辆 = 2025年NEV销量 × 2025年换电渗透率 × CATL市占率
    # （NEV销量直接取外部信源，避免产销口径与渗透率口径混搭——与重卡框架D8一致）
    stock_nev_sales = c["stock_nev_sales_2025"]                     # 2025年NEV销量(万辆)
    stock_swap_vehicles = round(                                     # 存量换电车辆(万辆)
        stock_nev_sales * c["stock_swap_pen"] * c["catl_share"], 3)
    stock_capacity = c["battery_kwh"] * stock_swap_vehicles          # 存量换电装机(万kWh)

    # ---- 增量部分（2026–2030 新车）----
    # 平均年销量 = 保有量 ÷ 更新周期；总销量 = 平均年销量 × 年限
    avg_annual_sales = c["fleet_2030"] / c["renewal_years"]          # 平均年销量(万辆)
    total_sales = avg_annual_sales * years                           # 品类总销量(万辆)

    # NEV 平均渗透率(2026–2030)，S 曲线逐年值取均值
    nev_rates = [c[f"nev_pen_{y}"] for y in ("2026", "2027", "2028", "2029", "2030")]
    nev_avg_rate = sum(nev_rates) / len(nev_rates)

    nev_total_sales = total_sales * nev_avg_rate                     # 品类NEV总销量(万辆)

    # 增量换电车辆 = NEV总销量 × 增量换电渗透率 × CATL市占率
    increment_swap_vehicles = round(nev_total_sales * c["increment_swap_pen"] * c["catl_share"], 3)
    increment_capacity = c["battery_kwh"] * increment_swap_vehicles  # 增量换电装机(万kWh)

    R.update({
        "品类": c["name"],
        "存量_NEV销量_万辆": stock_nev_sales,
        "存量换电车辆_万辆": stock_swap_vehicles,
        "存量换电装机_万kWh": stock_capacity,
        "平均年销量_万辆": avg_annual_sales,
        "品类总销量_万辆": total_sales,
        "NEV平均渗透率": nev_avg_rate,
        "品类NEV总销量_万辆": nev_total_sales,
        "增量换电车辆_万辆": increment_swap_vehicles,
        "增量换电装机_万kWh": increment_capacity,
        "总换电车辆_万辆": stock_swap_vehicles + increment_swap_vehicles,
        "总换电装机_万kWh": stock_capacity + increment_capacity,
    })
    return R


def compute(cfg: dict):
    """对轻卡/微卡/轻客逐品类测算并汇总。"""
    years = cfg["测算年限_年"]
    cats = [compute_category(c, years) for c in cfg["品类"]]

    R = {
        "总换电装机_万kWh": sum(c["总换电装机_万kWh"] for c in cats),
        "总换电车辆_万辆": sum(c["总换电车辆_万辆"] for c in cats),
        "_明细_品类": cats,
    }
    return R


# ============================================================
# 输出
# ============================================================
if __name__ == "__main__":
    res = compute(CONFIG)
    cats = res["_明细_品类"]

    print("=" * 72)
    print("城配物流轻商（轻卡/微卡/轻客）换电规模测算（2026–2030，CATL）")
    print("=" * 72)

    for c in cats:
        print(f"\n【{c['品类']}】")
        print(f"  {'存量换电车辆(万辆)':26s}: {c['存量换电车辆_万辆']:.3f}")
        print(f"  {'存量换电装机(万kWh)':26s}: {c['存量换电装机_万kWh']:.1f}")
        print(f"  {'品类总销量(万辆)':26s}: {c['品类总销量_万辆']:.0f}  (保有量÷更新周期×{CONFIG['测算年限_年']}年)")
        print(f"  {'NEV平均渗透率':26s}: {c['NEV平均渗透率']:.4f}  (AVERAGE 2026–2030)")
        print(f"  {'品类NEV总销量(万辆)':26s}: {c['品类NEV总销量_万辆']:.1f}")
        print(f"  {'增量换电车辆(万辆)':26s}: {c['增量换电车辆_万辆']:.3f}")
        print(f"  {'增量换电装机(万kWh)':26s}: {c['增量换电装机_万kWh']:.1f}")
        print(f"  {'品类小计 车辆(万辆)':26s}: {c['总换电车辆_万辆']:.3f}")
        print(f"  {'品类小计 装机(万kWh)':26s}: {c['总换电装机_万kWh']:.1f}")

    print("\n" + "=" * 72)
    print("[汇总]")
    print(f"  {'轻商总换电装机规模(万kWh)':26s}: {res['总换电装机_万kWh']:.1f}  (≈{res['总换电装机_万kWh']/100:.1f} GWh)")
    print(f"  {'轻商总换电车辆规模(万辆)':26s}: {res['总换电车辆_万辆']:.1f}")
    print("=" * 72)

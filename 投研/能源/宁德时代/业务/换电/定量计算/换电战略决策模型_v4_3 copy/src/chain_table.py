"""【已停用】职责并入 src/tree.py（2026-09-01）。

原 chain_table 做两件事，现在分别有了更合适的去处：

| 原职责 | 现在在哪 | 为什么更好 |
|---|---|---|
| 从参数到结论的计算链条表 | `src/tree.py` | 树是真的递归结构：根是决策不是车辆，可折叠、可从任意节点下钻，且每个内部节点都跑「父＝f(子)」自校验——公式和模型脱钩会当场报错，而不是静默错下去 |
| 六组车型 × 三情景的横向对比 | `src/tree.py` | 情景归入每个节点的三档值（悲观／中性／乐观）；车型分组归入子节点——分组本来就是树的自然结构，不需要另开一个维度 |
| 手写公式 ＋ 逐行 check | `src/tree.py` | 保留了「公式只写中文名运算、绝不写数字」这条纪律，但自校验从"每行一个、可选"升级成"每个节点、强制" |
| 信源字典 FINAL_SRC | `configs/base.toml` 注释 | 信源回到参数身边（单一事实源），tree 直接读注释；缺注释的参数会在审计里被列出来 |

原文件完整保留在 `_archive/chain_table.py`，只读对照用。确认不再需要后可以删掉本文件与存档。

    python src/tree.py            # 跑审计（三情景）
    python src/tree.py --json     # outputs/tree.json，供报告与前端下钻
    python src/tree.py --xlsx     # outputs/换电决策树_v4.3.xlsx，Excel 可折叠层级表
"""
import sys

print(__doc__)
sys.exit(0)

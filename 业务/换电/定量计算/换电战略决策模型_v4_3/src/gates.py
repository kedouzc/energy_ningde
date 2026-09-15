# -*- coding: utf-8 -*-
"""门的形状：把 decision.py 按 owner 分的备忘录，映射成报告要的五道门。

【2026-09-13g】为什么要单独一层
──────────────────────────────────────────────────────────────────────
`decision.py` 的六道备忘录是按**责任人**（规模与网络／资本开支／换电经营…）分的，
与报告第 4 章的**五道门**（物理／经济／资金／博弈／能力）不同构。直接拿来用会让
"这道门通没通"取决于读者自己去对应，那就不是一个可被引用的读数。

**门的形状 = 五件事**：名字 / 通过与否 / 余量 / 翻转参数 / 翻转阈值。
其中**翻转阈值才是可行性分析的价值**——"调到什么程度结论会翻"，
比"现在是绿的"信息量大得多。`lab.py` 的点弹性给不出阈值，要二分求解。

【本轮只做经济门】其余四道留形状占位。理由见 交接.md §5.2。

【经济门有两条翻转轴，不是一条】（2026-09-13f 用户提问引出）
──────────────────────────────────────────────────────────────────────
覆盖倍数 = 稳态 EBITDA ÷ (全周期资本底座 × CRF)。分子分母各有一条翻转轴：

  · **服务费**（分子侧）：经营变量，降到某个价这道门翻红——二分求解。
  · **要求回报**（分母侧）：**判断变量**，不是测出来的。CRF 由要求回报 i 决定
    （CRF(i,15) = i ÷ (1−(1+i)^−15)），i 定得越高门槛越高。

**第二条轴必须显式给出，否则"门通没通"会被读成模型的结论，而它其实是门槛定在哪的结果。**

【2026-09-15·A8 改了门槛的口径】
──────────────────────────────────────────────────────────────────────
原来 i = 12.4%（CRF 拍 0.15），而现金流按 WACC 7.5% 折现——**同一个模型里两个"资本的价格"**。
现在 CRF ≡ CRF(WACC, 运营年限)，**覆盖 1.0 ＝ 刚好赚回资本成本**（不是盈亏平衡）。
安全边际不再焊在门槛里，改由**余量**和**这条翻转轴**表达。

**信息一个没丢，只是换了位置**：三档翻红阈值 9.94% / 16.69% / 22.50%，
把原来的 12.4% 放回去比一比，红绿格局与改口径前**完全一致**（悲观红、中性乐观绿）。
差别在于现在读者能看见"红在门槛，不在生意"——而以前这句话要靠注释去说。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Callable

from config_loader import cloned_config, get_path, _set_path


# ─────────────────────────────────────────── 数据契约
@dataclass
class Flip:
    """一条翻转轴：这个参数调到什么值，这道门会翻。"""
    param: str          # 参数的点分路径（或 "—" 表示判断变量）
    label: str          # 中文名
    current: float      # 当前值
    flip_value: float   # 翻转阈值
    unit: str
    direction: str      # "降到" / "升到"
    note: str = ""


@dataclass
class Gate:
    """一道门的形状：五件事齐全才算一道门。"""
    key: str
    name: str
    passed: bool
    reading: float      # 这道门的读数（如覆盖倍数）
    threshold: float    # 体检线
    margin: float       # 余量 = 读数 − 体检线
    flips: list[Flip]
    # 扁平化的翻转阈值：`at` 点分路径取不了列表下标，所以把解析可得的那条轴平铺出来。
    flip_required_return: float = 0.0   # 要求回报调到多少这道门翻
    implemented: bool = True
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["flips"] = [asdict(f) for f in self.flips]
        return d


# ─────────────────────────────────────────── 求解器
def crf(i: float, n: int = 15) -> float:
    """资本回收因子：把一笔全周期投入年金化成每年必须回收的钱。"""
    return i / (1.0 - (1.0 + i) ** -n)


def solve_required_return(crf_target: float, n: int = 15) -> float:
    """CRF 的反函数：给定 CRF，反解出它隐含的要求回报 i。单调，二分即可。"""
    lo, hi = 1e-4, 0.60
    for _ in range(120):
        mid = (lo + hi) / 2.0
        if crf(mid, n) < crf_target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def bisect_param(
    config: dict,
    path: str,
    reading: Callable[[Any], float],
    target: float,
    lo: float,
    hi: float,
    build,
    iters: int = 22,
) -> float | None:
    """二分求解：把 `path` 这个参数调到多少，`reading` 恰好等于 `target`。

    **为什么必须整模型重跑而不是用弹性外推**：外推只在 ±10% 内可信，
    而翻转阈值经常落在区间边缘。外推值长得像精确实跑值就是骗（同沙盘坑 18/19）。
    """
    def read_at(v: float) -> float:
        cfg = cloned_config(config)
        _set_path(cfg, path, v)
        return reading(build(cfg))

    f_lo, f_hi = read_at(lo) - target, read_at(hi) - target
    if f_lo * f_hi > 0:
        return None                      # 区间内不翻，说明这条轴翻不动这道门
    for _ in range(iters):
        mid = (lo + hi) / 2.0
        if (read_at(mid) - target) * f_lo > 0:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# ─────────────────────────────────────────── 五道门
_PENDING = [
    ("physical", "物理门", "能不能建：兑现年目标装机必须远小于现有＋规划产能，且给储能/AIDC 留余量"),
    ("funding",  "资金门", "钱够不够：峰值占用占 CFO 的比例；含回购对照的财务纪律检验"),
    ("game",     "博弈门", "会不会被替代：快充路线、绿色甲醇路线、合作方配不配合"),
    ("capacity", "能力门", "自己干不干得了：组织能力、人才结构、执行记录（用人信号是推不是拉，且滞后）"),
]


def build_gates(config: dict, snapshot, build=None) -> list[Gate]:
    """产出五道门。本轮只有经济门是实的，其余四道给形状不给数。"""
    gates: list[Gate] = []
    fin = config["finance"]
    thr_cfg = config["decision_thresholds"]["min_forward_to_required_ebitda"]
    threshold = thr_cfg["v"] if isinstance(thr_cfg, dict) else thr_cfg
    coverage = snapshot.swap_business.forward_to_required_ebitda
    crf0 = fin["capital_recovery_factor"]

    flips: list[Flip] = []

    # ── 轴一（分子侧·经营变量）：服务费降到多少翻红
    if build is not None:
        fee_path = "swap_business.service_fee_rmb_kwh"
        fee_now = get_path(config, fee_path)
        fee_flip = bisect_param(
            config, fee_path,
            lambda s: s.swap_business.forward_to_required_ebitda,
            threshold, 0.05, max(fee_now, 0.60), build,
        )
        if fee_flip is not None:
            flips.append(Flip(
                param=fee_path, label="换电服务费", current=fee_now,
                flip_value=fee_flip, unit="元/kWh",
                direction="降到" if fee_flip < fee_now else "升到",
                note="经营变量：可被竞争压下去，也可被标准地位撑住",
            ))

    # ── 轴二（分母侧·判断变量）：要求回报定到多少翻红
    # 覆盖倍数 ∝ 1/CRF，所以 CRF* = coverage × CRF0 ÷ threshold，解析解，不必二分。
    crf_flip = coverage * crf0 / threshold if threshold else 0.0
    i_now = solve_required_return(crf0)
    i_flip = solve_required_return(crf_flip)
    flips.append(Flip(
        param="finance.capital_recovery_factor", label="全投资口径要求回报",
        current=i_now, flip_value=i_flip, unit="%",
        direction="降到" if i_flip < i_now else "升到",
        note="**判断变量，不是测量值**。门槛现取 ≡ WACC（覆盖 1.0 ＝ 刚好赚回资本成本）。"
             "参照谱系：蔚能 4.68% / 协鑫 8.5–9.1% / 启源 10.34% / 本项目原口径 12.4%。"
             "**这条轴才是第 4 章要写的东西**——门槛定在谱系的哪一档，结论就翻在哪一档",
    ))

    gates.append(Gate(
        key="econ", name="经济门", passed=coverage >= threshold,
        reading=coverage, threshold=threshold, margin=coverage - threshold,
        flips=flips, flip_required_return=i_flip,
        note="稳态 EBITDA ÷ (全周期资本底座 × CRF)。分母的 required_ebitda 是把全周期资本要求"
             "（含更新）反算回 EBITDA 层的等价值——**恒等式：EBITDA＝required_ebitda ⟺ "
             "税后经营现金＝资本要求**，所以这个比值本来就是现金覆盖测试，不需要再把分子换成 FCFF"
             "（实测 FCFF 口径 1.15 对 EBITDA 口径 1.17，差的就是这条恒等式的舍入）。"
             "分子分母各有一条翻转轴，两条都要给",
    ))

    for key, name, note in _PENDING:
        gates.append(Gate(key=key, name=name, passed=False, reading=0.0, threshold=0.0,
                          margin=0.0, flips=[], implemented=False, note=note))
    return gates


def print_gates(gates: list[Gate]) -> None:
    print("\n" + "═" * 76)
    print("五道门 · 形状（名字 / 通过 / 余量 / 翻转参数 / 翻转阈值）")
    print("═" * 76)
    for g in gates:
        if not g.implemented:
            print(f"  ○ {g.name}　（形状占位，本轮未实现）　{g.note}")
            continue
        mark = "✓ 通过" if g.passed else "✗ 不通过"
        print(f"  {mark}　{g.name}：读数 {g.reading:.2f}　体检线 {g.threshold:.2f}　"
              f"余量 {g.margin:+.2f}")
        for f in g.flips:
            cur = f.current * 100 if f.unit == "%" else f.current
            flip = f.flip_value * 100 if f.unit == "%" else f.flip_value
            print(f"      · {f.label} {cur:.2f}{f.unit} → {f.direction} "
                  f"{flip:.2f}{f.unit} 时翻转")

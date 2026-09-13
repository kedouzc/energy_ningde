"""模型实验室：给"不写代码但要改模型"的人准备的追踪器。

解决的问题
----------
模型拆成 configs/src/outputs 三件套后，参数改一个值，人看不出它影响了谁。
Excel 里这件事由"追踪引用单元格/从属单元格"解决；本模块用**实测**解决：

    改一个参数 → 重跑同一条计算链 → 对比全部指标

血缘关系因此不是人工登记的注释，而是每次跑出来的真值，模型改版不会失效。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
一、数据流与分工：数字在哪、逻辑在哪、本文件在哪
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    configs/base.toml  ──►  src/model.py  ──►  outputs/（报告·决策树·一页纸·血缘表）
    ★全部数字都在这        ★只跑逻辑，
     参数值 / 情景档位       不含任何业务数字
     不可调名单 / 微扰幅度
              │
              └──►  src/lab.py（本文件）：把 model 反复重跑，
                    用"实测"回答"谁影响了谁、影响多大"

**分工原则（最重要的一条）**：
    base.toml  = 你改数字的地方（唯一事实源）
    src/*.py   = 程序跑逻辑的地方（里面不该有业务数字）

所以：**调参数、改情景档位、加减不可调项 —— 全部去 base.toml，不要动 Python。**
本文件里剩下的数字只是"怎么量"的方法参数（微扰幅度 step），而且它**也已经提到
base.toml 的 [sensitivity] 段**了。

**lab.py 的边界**：只负责「客观发现谁影响大」（数值法实测）；「是否把它做成情景轴、
档位取多少、配什么外部信源」是人的主观判断，lab 不代劳。它的「漏网的轴」审计（弹性大却没进轴）
只是提醒人去拍板，不是自动加轴。
（另：`lab.py metrics` 是**输出字典查询器**——列出模型算出了哪些数、每个数在哪个程序
 `src/<source>.py` 算出、写错中文名时给最像的 3 个候选；结果注册表 `METRICS`
 由 `configs/metrics.toml` 加载，lab.py 只当加载器，不写任何取数公式。）

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
二、两个"幅度"千万别搞混（最容易踩的坑）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

  ┌──────────┬─────────────────────────┬───────────────────────────┐
  │          │ ① 微扰幅度 step         │ ② 情景档位（drivers）      │
  ├──────────┼─────────────────────────┼───────────────────────────┤
  │ 在哪设    │ base.toml [sensitivity] │ base.toml [drivers.xxx]   │
  │          │ .step（默认 0.10）       │ 的 悲观/中性/乐观 三档      │
  ├──────────┼─────────────────────────┼───────────────────────────┤
  │ 干什么用  │ **测量**：轻轻推一下参数 │ **判断**：你认为世界会变成 │
  │          │ ，量它有多敏感（是尺子） │ 什么样，这条轴该摆多远     │
  ├──────────┼─────────────────────────┼───────────────────────────┤
  │ 谁定      │ 程序默认，一般不用改     │ **你定** ← 这才要校准      │
  └──────────┴─────────────────────────┴───────────────────────────┘

  例：step=0.10 = "把每个参数单独 +10%，看指标变化百分之几"。
  它是**尺子不是预测**——改大改小只影响灵敏度读数的精度，不改变谁重要谁不重要的排序。
  而"±15% 怎么校准"（review-plan §3.6 那条）说的是 **②情景档位**，
  要去 base.toml 的 [drivers.commercial_nev_penetration] / [drivers.catl_swap_share] 改，
  跟 step 无关。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
三、命令（从最常用开始）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    python src/run.py                     ★一键出全部（报告+血缘+决策树+一页纸）
    python src/lab.py metrics            查模型算出了哪些数、每个数在哪个程序算出（输出字典）
    python src/lab.py scan                谁最能撬动换电增量价值（看【表 0】【表 1】）
    python src/lab.py workbook            生成 outputs/换电模型_参数与血缘_v4.3.xlsx
    python src/lab.py impact <参数> +10%  改这一个参数，看所有结果怎么动
    python src/lab.py lineage <指标键>    这个结果由谁决定
    python src/lab.py list                全部可调参数（值 + 为什么这么假设）

    scan / workbook 后可加 `--step 0.2` 临时换微扰幅度（不用改 base.toml）。

输出约定：一律 UTF-8；每条命令都先打印“怎么用”再打印结果。
`workbook` 产出的 Excel 含 01_假设参数、02_结果总表、03_敏感性矩阵、04_溯源、05_影响，
对应用户熟悉的财务建模三表习惯。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
四、弹性怎么读
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    弹性 = （指标变化百分之几） ÷ （参数变化百分之几）

    +1.00 → 参数涨 10%、指标涨 10%（同比例）
    -1.50 → 参数涨 10%、指标跌 15%（放大且反向）
     0.00 → 这个参数根本没进这条链，调它不影响该结果

「总影响力」只取它对**最终投资指标** val.swap_increment（换电增量价值）的弹性，
不做多项加总——理由见下方"五、口径修正"。

扫描方法：对 base.toml 的全部可调数值参数（当前约 200+ 个，随 [drivers] 轴增减）单独 +10%
重跑，比对 37 个输出指标得弹性，全扫描约 1 秒（精确数量以 `lab.py list` 实跑打印为准，不硬编码）。
**刻意不解析代码、不人工登记公式**：血缘是每次重跑出来的真值，模型改版后重跑即得新血缘，永不与代码脱钩。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
五、四项关键口径修正（2026-09-08）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

1. 总影响力锚定在最终投资指标 val.swap_increment（换电增量价值合计），
不再按「受影响指标个数/多个终端指标求和」加总，
否则 rte 之类成本参数会顺着 电量→EBITDA→估值 链式传染、被虚高排名。 
2. 参数枚举必须能穿透数组：scenes 是对象数组（换电渗透率/CATL市占率在里面）、nev_rates 是曲线数组；
早期 iter_numeric_params 遇到 list 直接 pass + set_path 不支持下标，
导致「车辆规模」整条轴在敏感性表里隐形。
现在 scenes 带下标展开、曲线型按「整条曲线同比平移」作为一个参数参与扫描
（但不进 01 表/trial/commit，Excel 单格放不下一条曲线）。 
3. 新增【表 0】轴级敏感性 compute_axis_leverage：
把一条 [drivers] 轴的全部 targets 一起 +step，看增量价值怎么动。
因为轴是「一组参数同时平移」，单参数扫描一次只动一个、必然低估整条轴的合力。
4. 不可调事实常量用 base.toml [sensitivity].not_adjustable 名单排除
（如 swap_business.operating_days=350 是运营事实不是假设），不扫、不进 01 表；
想恢复就从名单里删掉，不用改代码。
"""
from __future__ import annotations

import copy
import difflib
import fnmatch
import inspect
import re
import sys
import time
from pathlib import Path
from typing import Any, Callable

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config_loader import (  # noqa: E402
    DEFAULT_CONFIG,
    ROOT,
    SCENARIO_ORDER,
    _SKIP_SECTIONS,
    _scene_name,
    apply_scenario,
    load_config,
    load_config_raw,
    load_drivers,
)
from model import _build_core, build_model  # noqa: E402
from schemas import ModelSnapshot  # noqa: E402

try:
    from openpyxl import Workbook, load_workbook
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter
except ImportError:  # pragma: no cover
    Workbook = None
else:
    HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
    HEADER_FONT = Font(bold=True, color="FFFFFF")
    EDIT_FILL = PatternFill("solid", fgColor="DDEBF7")
    BLOCK_FILL = PatternFill("solid", fgColor="F2F2F2")
    WRAP = Alignment(vertical="top", wrap_text=True)

    def style_header(ws, row_index: int, ncols: int) -> None:
        for col in range(1, ncols + 1):
            cell = ws.cell(row=row_index, column=col)
            cell.fill = HEADER_FILL
            cell.font = HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.freeze_panes = ws.cell(row=row_index + 1, column=1)

    def set_widths(ws, widths: list[int]) -> None:
        for index, width in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(index)].width = width

# ══════════════════════════════════════════════════════════════════════
# 一、参数路径工具（支持 "vehicles.heavy.battery_kwh" 这类点分路径）
# ══════════════════════════════════════════════════════════════════════

DEFAULT_STEP = 0.10   # 微扰幅度兜底值；优先读 base.toml [sensitivity].step


def get_path(config: dict, path: str) -> Any:
    node: Any = config
    for part in path.split("."):
        node = node[part]
    return node


def set_path(config: dict, path: str, value: Any) -> None:
    """按点分路径写值，支持数组下标（如 vehicles.heavy.scenes.0.swap_penetration）。

    数组下标按"位置"定位（改第 0 个场景，不是名叫 0 的字段），故列表用 int(part)。
    scenes 这类对象数组里的参数靠它才写得进去——也才进得了扫描。
    """
    parts = path.split(".")
    node: Any = config
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


def _cfg_get(config: dict, path: str) -> Any:
    """set_path 的读侧配套：同样支持数组下标。"""
    node: Any = config
    for part in path.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def _perturb(old: Any, step: float) -> Any:
    """+step 微扰：标量直接乘；数值数组整条曲线逐元素乘（与 [drivers].relative 同义）。"""
    if isinstance(old, list):
        return [x * (1.0 + step) for x in old]
    return step if abs(old) < 1e-12 else old * (1.0 + step)


def sensitivity_step(config: dict) -> float:
    """敏感性微扰幅度：base.toml [sensitivity].perturb，缺省 DEFAULT_STEP。

    ★ 这是"测量用的尺子"，**不是**情景档位，也**不是**滑块步长：
      情景档位在 [drivers.*] 的悲观/中性/乐观；滑块步长是 [drivers.*].step。
    """
    sens = config.get("sensitivity") or {}
    value = sens.get("perturb", sens.get("step"))   # 旧名 step 仍兼容
    try:
        return float(value)
    except (TypeError, ValueError):
        return DEFAULT_STEP


def _not_adjustable(config: dict) -> set[str]:
    """「不可调事实常量」名单（base.toml [sensitivity].not_adjustable）。

    这些不是假设、没有可调区间（是事实/制度/会计常量），故不扫描、不进 01 表——
    避免把根本不能动的数当成可调旋钮摆在那儿。
    """
    sens = config.get("sensitivity") or {}
    return set(sens.get("not_adjustable") or [])


def _is_excluded(path: str, excluded: set[str]) -> bool:
    """精确前缀匹配 + 通配匹配（not_adjustable 支持 "vehicles.*.scenes.*.weight"）。

    —不是可调假设的量（权重合计恒为 1、车型物理参数）不必逐个抄路径。
    """
    def hit(pattern: str) -> bool:
        if "*" in pattern or "?" in pattern:
            return fnmatch.fnmatchcase(path, pattern)
        return path == pattern or path.startswith(pattern + ".")

    return any(hit(p) for p in excluded)


def iter_numeric_params(
    config: dict, include_arrays: bool = False, also: tuple[str, ...] = ()
) -> list[tuple[str, Any]]:
    """扁平列出全部可调的数值参数，跳过开关/字符串/URL/事实台账/不可调名单。

    · 对象数组（scenes）会带下标展开 → 场景级参数（换电渗透率/CATL 市占率）可见可扫。
    · include_arrays=True 时额外纳入"数值数组型"参数（如 nev_rates 渗透率 S 曲线），
      语义＝整条曲线同比平移（与 [drivers] 的 relative 同义）。这类只进扫描，
      不进 01_假设参数/trial/commit——Excel 单格放不下一条曲线。
    · also：把这些段从 _SKIP_SECTIONS 临时捞出（如沙盘给 charge_share 测弹性）；
      敏感性扫描不传它——情景轴仍不当自由旋钮。
    """
    excluded = _not_adjustable(config)
    skip = tuple(s for s in _SKIP_SECTIONS if s not in also)
    out: list[tuple[str, Any]] = []

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                walk(f"{prefix}.{key}" if prefix else key, child)
        elif isinstance(node, list):
            numeric = node and all(
                isinstance(x, (int, float)) and not isinstance(x, bool) for x in node
            )
            if numeric:
                # 数组分支也必须过 _SKIP_SECTIONS——否则 [param_bounds] 的
                # [min, max] 会被当成"可调参数"混进扫描（它是元数据不是参数）
                if (include_arrays
                        and not _is_excluded(prefix, excluded)
                        and not any(prefix == s or prefix.startswith(s + ".")
                                    for s in skip)):
                    out.append((prefix, [float(x) for x in node]))
                return
            for i, child in enumerate(node):
                walk(f"{prefix}.{i}", child)
        elif isinstance(node, bool):
            pass
        elif isinstance(node, (int, float)):
            if _is_excluded(prefix, excluded):
                return
            if any(prefix == s or prefix.startswith(s + ".") for s in skip):
                return
            out.append((prefix, float(node)))

    walk("", config)
    return out


# ══════════════════════════════════════════════════════════════════════
# 二、参数档案：从 base.toml 的注释里取"为什么这么假设"
# ══════════════════════════════════════════════════════════════════════

_KEY_RE = re.compile(r'^\s*(?:\[\[?\s*([^\]]+?)\s*\]\]?|"?([^"=]+?)"?\s*=)')


def load_param_docs(path: Path = DEFAULT_CONFIG) -> dict[str, dict[str, str]]:
    """解析 base.toml，把每个键上方紧邻的注释块作为它的'一句话理由'。

    tomllib 丢弃注释，理由只能靠文本解析取回——这是唯一需要读原文的地方。
    """
    docs: dict[str, dict[str, str]] = {}
    stack: list[str] = []       # 当前表路径
    pending: list[str] = []     # 尚未归属的注释行
    array_of_tables: str | None = None

    with path.open(encoding="utf-8") as handle:
        for raw in handle:
            line = raw.rstrip("\n")
            stripped = line.strip()

            if not stripped:
                pending = []
                continue

            if stripped.startswith("#"):
                text = stripped.lstrip("#").strip()
                # 分隔符（──── / ┌─┐ 之类）只作视觉分节，不进理由
                if text and not re.fullmatch(r"[\s\-─=━┌┐└┘│├┤·]+", text):
                    pending.append(text)
                continue

            match = _KEY_RE.match(line)
            if not match:
                continue

            if match.group(1):  # 表头
                header = match.group(1).strip()
                if header.startswith("["):  # [[array of tables]]
                    header = header.strip("[]").strip()
                    array_of_tables = header
                    stack = [header]
                else:
                    first = header.split(".")[0]
                    if array_of_tables and first == array_of_tables and len(header.split(".")) == 1:
                        stack = [array_of_tables]
                    else:
                        array_of_tables = None
                        stack = [p.strip().strip('"') for p in header.split(".")]
                pending = []
                continue

            key = match.group(2).strip().strip('"')
            full = ".".join([*stack, key]) if stack else key
            # 理由取前两行有效注释，避免整段推导搬进来（推导在 MANIFEST）
            reason = " / ".join(pending[:2])
            docs[full] = {"reason": reason, "section": ".".join(stack)}
            # 就地信封：注释挂在 <键>.v 上方，但参数语义路径是 <键> 本身
            # （iter_numeric_params/tree 拿到的是解包后的 finance.wacc），
            # 同一条理由在语义路径再登记一份，别让信封化把"为什么这么假设"弄丢。
            if key.endswith(".v"):
                semantic = ".".join([*stack, key[:-2]]) if stack else key[:-2]
                docs.setdefault(semantic, {"reason": reason, "section": ".".join(stack)})
            pending = []

    return docs


# ══════════════════════════════════════════════════════════════════════
# 三、指标注册表：要盯住哪些结果（输出字典 configs/metrics.toml 的加载器）
#
# 数据流（2026-09-12 重构后）：
#   计算程序（scale/capex/business/consolidation/group_constraints/capital_cycle）
#     └─ 把结果算好、挂在快照的 dataclass 字段上（schemas.py）
#   configs/metrics.toml（输出字典，纯声明、无公式）
#     └─ 每条写 `at="scale.xxx"` ＋ `source="scale"`（只有 at，没有公式）
#   configs/base.toml 的输入侧（2026-09-13 定稿）
#     └─ 就地信封：被叙述引用的参数在功能段原地写成 <键>.v＋label/unit/…，
#        注册表 key 就是点分路径（如 meta.target_year），值不重复登记、不造别名
#     └─ [[external_quote]]：ext.* 外部引述（倍数/TCO，不进本表，由 facts 直接装配）
#   load_metrics()  ← 读 metrics.toml＋自动发现信封并升格进同一注册表（内部以 at_cfg
#                     取值器现读 base），逐条验证路径找得到（审计①），建 METRICS
#   read_metrics(snap, cfg)  ← 沿 at 路径取值，返回 {key: 数值}
#   facts.build_facts(..., metrics_values=read_metrics(...))  ← 把数值灌进事实包
#   叙述层（MD 的 {{中文名}}）← inject 经 resolve() 先译成中文名→内部 key→facts 取值
#
# 本文件**只做加载与取值**，不含任何"怎么算"的代码（计算都已下沉回各计算程序）。
# 用户视角的取数：写中文名即可，resolve() 负责"中文名→key→容错"的语义寻址；
# 找不到一律抛错并给 3 个最像的候选，绝不静默。source 字段让心算存疑时能直接定位程序。
# ══════════════════════════════════════════════════════════════════════


class Metric:
    """结果注册表的一项。

    **本表是结果层的唯一注册表**（2026-09-09 升格）：沙盘顶部读数、三道门、可行性验证、
    敏感性矩阵、血缘 Excel、一页纸的数值列，全部经 `read_metrics()` 从本表取数——
    **下游不得再各自写一条取数路径**（同一个量在 lab / facts / tree / report 各登记一遍，
    就是"一个数字两个出处"的根因）。新增可对外引用的结果，一律先在这里登记。

    note＝口径说明：写清它是什么口径、与谁的区别（存量/流量、100%/归属、现值/名义），
    免得下游按自己的理解复用。

    source＝**这个数在哪个程序里算出来的**（不是函数名，是模块文件名，如 scale / capex /
    business / consolidation / group_constraints / capital_cycle / model / external）。
    有了它，心算觉得不对时，直接 `python src/lab.py metrics 名字` 就能看到出处，
    不用跳 README 去猜 `ops`/`swap`/`val`/`fund` 这些 key 前缀到底对应哪个程序。
    `source` 由加载器从 configs/metrics.toml 的 `source` 字段读出；程序自动验证它对得上
    （见 load_metrics 的审计），所以**不会写错**。

    needs_cfg=False 的量，getter 只收 snapshot；needs_cfg=True 的量（外部事实常量、
    跨模块派生）getter 收 (snapshot, cfg)，由 `read_metrics(snap, cfg)` 传入。**调用方
    必须传 cfg**，否则这些量为 NaN（而不是悄悄给一个错值）。

    为什么允许 needs_cfg：有些量根本不是模型算出来的——它们是 `base.toml` 功能段里的
    外部锚（目标年份、2026E 出货、重卡保有量）或需要 cfg 才能算的跨模块派生（REIT 回笼
    倍数）。2026-09-13 定稿后，外部锚在 base.toml 功能段**就地信封化**
    （<键>.v ＋ 呈现要素，key 就是点分路径），由 load_envelopes 发现、加载时升格进本
    注册表、内部走 at_cfg 取值器现读；以前这些只存在于 `verdict.build_vals` 里，
    一页纸与章取不到，就是"第三套数值源"。升格进本表后，"一个数只有一个家"
    才对全部视图成立。
    """

    def __init__(self, key: str, label: str, getter: Callable[..., float] | None = None,
                 decimals: int = 1, unit: str = "", group: str = "", note: str = "",
                 needs_cfg: bool = False, at: str = "", at_cfg: str = "",
                 scale: float = 1.0, source: str = "", fmt: str = ""):
        if getter is None:
            if not (at or at_cfg):
                raise ValueError(
                    f"指标 {key} 必须给 getter、at（快照路径）或 at_cfg（配置路径）之一")
            getter = _at(at, scale) if at else _at_cfg(at_cfg, scale)
        # fmt＝呈现格式（2026-09-13 立）："" 普通千分位数值；"year" 年份＝整数无千分位
        # （2030，不是 2,030.0）。渲染规则只此一家：facts 事实包、verdict 沙盘 vals、
        # JS 占位符替换全部调用本类的 format_text/format_bare，不再各写一套格式化。
        if fmt not in ("", "year"):
            raise ValueError(f"指标 {key} 的 fmt={fmt!r} 非法，只允许 '' 或 'year'")
        self.key = key
        self.label = label
        self.getter = getter
        # 保留取值路径与出处：事实包与审计都要用（"这个数从哪儿来"要能说清）
        self.at = at
        self.at_cfg = at_cfg
        self.source = source
        self.decimals = decimals
        self.unit = unit
        self.group = group
        self.note = note
        self.fmt = fmt
        # needs_cfg **由 getter 的参数个数兜底**：写了第二个参数就必然需要 cfg。
        # 为什么不能只靠手工标：2026-09-11 一次漏标了 6 个，read_metrics 于是按一参调用
        # 两参 getter → TypeError → 安静地变成 NaN → 页面上就是 [待补]，
        # 看起来和"这个数今天算不出来"一模一样。**能机械判的就不要靠记得标。**
        self.needs_cfg = needs_cfg or len(inspect.signature(getter).parameters) >= 2

    # ── 呈现（facts / verdict / 沙盘 JS 三侧同源，改规则只改这里）──────────────
    def format_bare(self, value: float) -> str:
        """裸数字串（`{{中文名:n}}`）：只做数字格式化，不带单位。

        年份（fmt="year"）取整且**不加千分位**；NaN 如实给 "nan"
        （上游 read_metrics 已集中报过，这里不静默改成破折号冒充零值）。
        """
        v = float(value)
        if v != v:
            return "nan"
        if self.fmt == "year":
            return f"{int(round(v))}"
        return f"{v:,.{self.decimals}f}"

    def format_text(self, value: float) -> str:
        """完整呈现（`{{中文名}}`）：裸数字后直接拼字典里的 unit。

        MD 里因此不必手写单位——单位改了，所有引用处跟着变，不会两边漂移。
        """
        return self.format_bare(value) + (self.unit or "")


# ── 存量口径 vs 流量口径（两个最容易混的口径，必须显式区分）──────────────
# 存量 = 终局在役多少（operating_stock_by_vehicle_wan）：报告 Q1 的"CATL换电车辆 351.9 万辆"。
# 流量 = 2030 当年交付多少（scale.rows[year==2030]）：出货量口径，用于制造侧收入。
# 二者相差 3 倍以上，混用会让"覆盖了多少车"和"今年卖了多少电池"互相污染。
_COMMERCIAL = ("heavy", "city")                        # 商用营运车：重卡 + 城配
_PASSENGER_OPS = ("taxi", "ridehail", "robotaxi")      # 乘用营运车：出租 + 网约 + Robotaxi
_PRIVATE = ("private",)                                # 私家车
_ALL_VEHICLES = _COMMERCIAL + _PASSENGER_OPS + _PRIVATE


# 2026-09-12：以下派生函数已全部删除——它们的计算逻辑下沉回各自的计算程序：
#   车辆/规模类 → scale.py        资本类 → capex.py        经营类 → business.py
#   合并类     → consolidation.py  资金类 → group_constraints.py  轻资产 → capital_cycle.py
# 本文件不再保留任何"怎么算"的代码，只做加载字典与沿路径取值。


# ── 声明式取值：加指标不必再写函数 ─────────────────────────────────────────
# 以前每个指标都要写一个 `lambda s: s.a.b.c`——60 多个指标里有八成是这种纯样板，
# 快照字段名一改就要来改代码，改漏了还是静默的 NaN。
# 现在输出量写成 `at="a.b.c"` 即可（metrics.toml 只有 at）；cfg 侧被叙述引用的参数
# 在 base.toml 功能段就地信封化（`target_year.v`＋呈现要素，key＝点分路径本身），
# load_envelopes 自动发现后升格为内部 at_cfg 取值器，由下面的通用取值器沿点分路径取；
# **只有真正需要计算的派生量才写函数**。
#
# 判据：**加一个"只是取个已有字段"的指标，应该只改一行，不写函数。**
# 反过来，如果一个量需要求和／比值／跨模块调用，那它值得有一个具名函数——
# 因为那里才有需要说清楚的口径。
def _at(path: str, scale: float = 1.0):
    """沿点分路径取值（dict 也用 `.` 递进，如 `scale.station_demand_by_category.heavy`）。"""
    parts = path.split(".")

    def get(s: ModelSnapshot) -> float:
        cur: Any = s
        for p in parts:
            if cur is None:
                return float("nan")
            cur = cur.get(p) if isinstance(cur, dict) else getattr(cur, p, None)
        return float(cur) * scale if cur is not None else float("nan")

    return get


def _at_cfg(path: str, scale: float = 1.0):
    """沿点分路径从 **cfg** 取值（外部事实常量，不是模型算出来的量）。"""
    parts = path.split(".")

    def get(_s: ModelSnapshot, cfg: dict | None) -> float:
        cur: Any = cfg or {}
        for p in parts:
            cur = cur.get(p) if isinstance(cur, dict) else None
            if cur is None:
                return float("nan")
        return float(cur) * scale

    return get


# 注：原「⑨ 外部锚与跨模块派生」那批 getter（_cfg_num / _cfg_heavy / _operating_market_total /
# _reit_multiple / _energy_unit_price / _veh_ops / _total_gwh_2030 / _share_of_market /
# _repl_share_pct / _heavy_pen_pct / _tco_field）已于 2026-09-12 随旧登记表一起删除——
# 模型输出量住在 configs/metrics.toml（at 声明、source 标程序）；cfg 侧外部锚/阈值
# 2026-09-13 定稿为 configs/base.toml 功能段里的就地信封（<键>.v＋呈现要素，
# key＝点分路径，load_envelopes 自动发现并升格为内部 at_cfg 取值器）。都由上面的
# 通用取值器 _at / _at_cfg 沿点分路径取，本文件不再保留任何"怎么算"的代码。


# ══════════════════════════════════════════════════════════════════════════
# 输出字典：模型算得出哪些数，住在 configs/metrics.toml（与 base.toml 输入输出对称）
#
# 本文件**不再登记任何指标**——那是字典的事。这里只负责：
#   ① 加载字典  ② 通用取值器（沿点分路径取）  ③ 敏感性/血缘工具
#
# 这样做的原因（用户 2026-09-12 定的）：改一个论述要引用某个数时，
# 只需要知道"这个数是什么意思"（中文名），不该需要知道程序里它叫什么、更不该来改本文件。
# ══════════════════════════════════════════════════════════════════════════
# 注意：config_loader.ROOT 指向 src/，项目根在它上一级
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = Path(__file__).resolve().parent
METRICS_PATH = PROJECT_ROOT / "configs" / "metrics.toml"
BASE_PATH = PROJECT_ROOT / "configs" / "base.toml"


def load_envelopes(path: Path = BASE_PATH) -> list[tuple[str, dict]]:
    """扫描 base.toml 原文，发现全部「就地信封」参数（含 ``v`` 键的虚线子表）。

    信封长这样（值与名片同住、路径即 key，不另登记、不造别名）::

        [finance]
        wacc.v = 0.075
        wacc.label = "WACC"
        wacc.unit = "%"

    config_loader.load_config 会把信封解成裸标量供程序消费；本函数读**原文**，
    把信封的呈现要素交给 load_metrics 升格为 Metric（key＝点分路径本身，
    如 finance.wacc；at_cfg＝同一路径；source="external"）。

    两条硬闸：
      * 信封的 v 必须是数值（bool 不算）；
      * 必须给 label——要进叙述注册表就得有中文名。若某张表只是恰好有个业务键
        叫 v，请改名：信封判定只认 v 键，没有第二套判据。
    """
    raw = load_config_raw(path)
    found: list[tuple[str, dict]] = []

    def walk(prefix: str, node: Any) -> None:
        if isinstance(node, dict):
            if "v" in node:
                env = node
                v = env["v"]
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise SystemExit(
                        f"✗ 信封 {prefix} 的 v 必须是数值（现在是 {type(v).__name__}）")
                if not str(env.get("label") or "").strip():
                    raise SystemExit(
                        f"✗ 信封 {prefix} 有 v 但缺 label——要被叙述引用必须给中文名；"
                        f"若它不是信封，请把 v 改名（信封判定只认 v 键）")
                found.append((prefix, env))
                return  # 信封内部（label/unit/note…）不再下钻
            for key, child in node.items():
                walk(f"{prefix}.{key}" if prefix else key, child)
        elif isinstance(node, list):
            for i, child in enumerate(node):
                walk(f"{prefix}.{i}" if prefix else str(i), child)

    walk("", raw)
    return found


def load_external_quotes(path: Path = BASE_PATH) -> list[dict]:
    """读 base.toml 末尾的 ``[[external_quote]]`` 外部原文引述段。

    这类输入**不当参数、不进任何计算**，仅供叙述层 {{ext.xxx}} 引用（可比公司倍数、
    JPM TCO）；value=变更侦测代表值（区间取中点），text=正文显示形式。

    本函数只做字段级硬校验（ext. 前缀、key/label 唯一、text/value/src/as_of 必填、
    src 必须是台账 src. key）；与输出字典/信封的跨表撞名（一词一名）由 load_metrics
    合并时统一拦——几处只在那里碰一次面。
    """
    if not path.exists():
        raise SystemExit(f"✗ 输入字典不存在：{path}")
    raw = load_config_raw(path)
    items = raw.get("external_quote") or []
    if not items:
        raise SystemExit(f"✗ {path.name} 里没有 [[external_quote]] 条目（外部引述段缺失）")
    out: list[dict] = []
    seen_key: set[str] = set()
    seen_label: dict[str, str] = {}
    for i, item in enumerate(items, 1):
        key = (item.get("key") or "").strip()
        label = (item.get("label") or "").strip()
        if not key:
            raise SystemExit(f"✗ base.toml [[external_quote]] 第 {i} 条缺 key")
        if not label:
            raise SystemExit(f"✗ base.toml [[external_quote]] 第 {i} 条（{key}）缺 label")
        if not key.startswith("ext."):
            raise SystemExit(f"✗ {key}：外部引述 key 必须以 ext. 开头（命名空间隔离）")
        if key in seen_key:
            raise SystemExit(f"✗ [[external_quote]] key 重复：{key}（一词一名）")
        if label in seen_label:
            raise SystemExit(
                f"✗ [[external_quote]] label 重复：「{label}」（{seen_label[label]} / {key}）")
        for field in ("text", "value", "src", "as_of"):
            if not str(item.get(field) or "").strip():
                raise SystemExit(f"✗ {key}：外部引述缺 {field}（引述必须给显示形式/代表值/信源/时点）")
        if not str(item["src"]).strip().startswith("src."):
            raise SystemExit(
                f"✗ {key}：引述的 src 必须是台账机读表 key（src. 开头），"
                f"信源 URL 的唯一家是 audit/信源审计台账.md")
        seen_key.add(key)
        seen_label[label] = key
        out.append(item)
    return out


def load_metrics(path: Path = METRICS_PATH) -> list[Metric]:
    """读输出字典，逐条构造指标；并把 base.toml 的就地信封参数升格并入。

    合并后注册表＝**模型输出**（metrics.toml 的 [[metric]]，at 取快照）＋
    **被叙述引用的输入参数**（base.toml 功能段里的就地信封，key＝点分路径、
    at_cfg 取同一路径现读配置）。[[external_quote]] 引述不是数值指标，不进本表，
    由 facts 直接装配，只参与一词一名撞名检查。

    **审计①**：每条必须给 `at`（模型结果路径）或信封的 at_cfg（配置路径）之一，
    且不能两者都没有——否则这条就是"想要但程序里不存在"的数，趁早失败好过页面 [待补]。
    **一词一名**：输出字典、信封、外部引述之间 key/label 撞名即中断。
    """
    if not path.exists():
        raise SystemExit(f"✗ 输出字典不存在：{path}")
    conf = load_config(path)
    items = conf.get("metric") or []
    if not items:
        raise SystemExit(f"✗ 输出字典里没有 [[metric]] 条目：{path}")

    out: list[Metric] = []
    seen_key: set[str] = set()
    seen_label: dict[str, str] = {}

    def _check_name(key: str, label: str, where: str) -> None:
        """key/label 跨表唯一性检查（输出字典 ↔ 输入侧共用一个裁判）。"""
        if key in seen_key:
            raise SystemExit(f"✗ 注册表 key 重复：{key}（{where}；一词一名）")
        if label in seen_label:
            raise SystemExit(
                f"✗ 注册表 label 重复：「{label}」（{seen_label[label]} 与 {where} 撞名）")
        seen_key.add(key)
        seen_label[label] = where

    for i, item in enumerate(items, 1):
        key = (item.get("key") or "").strip()
        label = (item.get("label") or "").strip()
        if not key:
            raise SystemExit(f"✗ 输出字典第 {i} 条缺 key")
        if not label:
            raise SystemExit(f"✗ 输出字典第 {i} 条（{key}）缺 label——中文名是它唯一的查找名")
        _check_name(key, label, "metrics.toml")
        out.append(Metric(
            key=key,
            label=label,
            at=(item.get("at") or "").strip(),
            at_cfg=(item.get("at_cfg") or "").strip(),
            scale=float(item.get("scale", 1.0)),
            decimals=int(item.get("decimals", 1)),
            unit=item.get("unit", ""),
            group=item.get("group", ""),
            note=item.get("note", ""),
            source=(item.get("source") or "").strip(),
            fmt=(item.get("fmt") or "").strip(),
        ))

    # 就地信封：路径即 key，呈现要素与值同住 base.toml 功能段（at_cfg 现读，driver 改档即新值）
    for env_path, env in load_envelopes():
        _check_name(env_path, str(env["label"]).strip(), "base.toml 就地信封")
        out.append(Metric(
            key=env_path,
            label=str(env["label"]).strip(),
            at_cfg=env_path,
            scale=float(env.get("scale", 1.0)),
            decimals=int(env.get("decimals", 1)),
            unit=env.get("unit", ""),
            note=env.get("note", ""),
            source="external",
            fmt=str(env.get("fmt") or "").strip(),
        ))

    # 外部引述不进结果注册表，只做一词一名撞名检查（装配在 facts.build_facts）
    for q in load_external_quotes():
        _check_name(q["key"].strip(), q["label"].strip(), "base.toml [[external_quote]]")

    _verify_source(out)
    return out


# source 允许的取值：必须是**真正算这个数的程序**（模块文件名，不含 .py）。
# tco 是重卡全成本模块；external／derived 之类泛名字不许再出现（说了等于没说）。
_SOURCE_CACHE: dict[str, tuple[str, list[str]]] = {}


def _source_text(source: str) -> tuple[str, list[str]]:
    """返回 (源码文本, 里面的函数名列表)，带缓存避免逐条读文件。"""
    if source not in _SOURCE_CACHE:
        f = SRC_DIR / f"{source}.py"
        text = f.read_text("utf-8") if f.exists() else ""
        funcs = re.findall(r"^def\s+([A-Za-z_][A-Za-z0-9_]*)", text, flags=re.M)
        _SOURCE_CACHE[source] = (text, funcs)
    return _SOURCE_CACHE[source]


def _field_owner_classes() -> dict[str, set[str]]:
    """字段名 → 定义它的 dataclass 们（全部定义在 schemas.py）。

    为什么要查这张表：有些字段是**按位置构造**的（如 `TcoRow(None, None, …)`），
    源码里根本没有字段名，只看字面量必然误判成"这条没算"。改看它属于哪个
    dataclass、那个类又被谁构造，才是真的追到算式所在的程序。
    """
    cache = getattr(_field_owner_classes, "_cache", None)
    if cache is not None:
        return cache
    owners: dict[str, set[str]] = {}
    owner: str | None = None
    for line in (SRC_DIR / "schemas.py").read_text("utf-8").splitlines():
        if m := re.match(r"class\s+([A-Za-z_][A-Za-z0-9_]*)", line):
            owner = m.group(1)
            continue
        if owner and (m := re.match(r"\s{4}([a-z_][a-z0-9_]*)\s*[:=]", line)):
            owners.setdefault(m.group(1), set()).add(owner)
    _field_owner_classes._cache = owners  # type: ignore[attr-defined]
    return owners


def _verify_source(metrics: list) -> None:
    """**审计②**：source 必须对得上它声称的程序，否则报错并指出去哪找。

    为什么这条要硬失败（2026-09-12 立）：`source` 是"心算觉得不对时该去哪儿查"的
    唯一线索。写错了不会让数字变错，但会让人**按图索骥走到错误的程序里**，
    半天找不到算式的那种错误就是这么来的——它骗的不是程序，是人的时间。

    三条判据，任一条对上就算找得到（依次试）：
    ① 字面量：最后一段在 `src/<source>.py` 里出现——构造结果对象时传的关键字参数；
    ② 归属类：最后一段是 schemas.py 里某个 dataclass 的字段，而那个类名出现在
       `src/<source>.py` 里——字段按**位置**构造时源码里没有字面名，只能这么追
       （如 `TcoRow(None, None, …)` 里的 `swap_wan`）；
    ③ 近似函数：最后一段与 source.py 里某个函数名高度相似
       （如 `reit_multiple` ← `reit_recycle_multiple()`）。
    三条都对不上，才判"写错了"。
    """
    try:
        base_text = (METRICS_PATH.parent / "base.toml").read_text("utf-8")
    except Exception:
        base_text = ""
    problems: list[str] = []
    for m in metrics:
        if not m.source:
            problems.append(f"{m.key}：缺 source（不知道它是哪个程序算出来的）")
            continue
        if not m.at:
            # 走 at_cfg 的数不是程序算出来的（外部锚常量），source 允许写 external——
            # 但它的路径必须在 configs/base.toml 里真实存在，否则也是指错路。
            if m.source != "external":
                problems.append(f"{m.key}：走 at_cfg 的量 source 只能写 external，"
                                f"现在写的是 {m.source}")
            tail = m.at_cfg.split(".")[-1]
            if tail and tail not in base_text:
                problems.append(
                    f"{m.key}：「{tail}」在 configs/base.toml 里找不到"
                    f"（at_cfg 必须指向真实存在的配置项）")
            continue
        text, funcs = _source_text(m.source)
        if not text:
            problems.append(f"{m.key}：source={m.source} —— src/{m.source}.py 不存在")
            continue
        tail = m.at.split(".")[-1]
        if not tail:
            continue
        if m.at:
            if tail in text:
                continue                                        # ① 字面量
            owners = _field_owner_classes().get(tail, set())
            if any(cls in text for cls in owners):
                continue                                        # ② 归属的 dataclass
            if difflib.get_close_matches(tail, funcs, n=1, cutoff=0.6):
                continue                                        # ③ 近似函数名
            problems.append(
                f"{m.key}：「{tail}」在 src/{m.source}.py 里找不到，"
                f"也不像那里任何一个函数——它是别的模块算的吧？改 source，或去那里把它算出来")
    if problems:
        raise SystemExit(
            f"✗ 输出字典的 source/at 对不上（{len(problems)} 处）——"
            f"source 是「去哪个程序查」的唯一线索，写错等于指错路：\n  "
            + "\n  ".join(problems))


METRICS: list[Metric] = load_metrics()
# 外部原文引述登记（[[external_quote]]，不进计算），facts 装配 ext.* 时读；
# 就地信封参数（功能段里的 v 子表）已由 load_metrics 升格进 METRICS，不在这里。
EXTERNAL_QUOTES: list[dict] = load_external_quotes()

# （旧登记表已于 2026-09-12 删除——指标现在只住在 configs/metrics.toml，
#  留第二份就是"一个数两个家"，正是要根除的病。）

METRIC_BY_KEY = {m.key: m for m in METRICS}
METRIC_BY_LABEL = {m.label: m for m in METRICS}


def _norm(text: str) -> str:
    """归一化：去掉空格、标点与括号内容，用于**容错匹配**。

    不是别名机制——字典里仍是一词一名；这里只是让人少写几个字也能命中
    （例如把"年换电交易电量"写成"年换电量"）。
    """
    s = (text or "").strip().replace("　", "")
    s = re.sub(r"[（(][^）)]*[）)]", "", s)          # 去括号及其中内容
    s = re.sub(r"[\s·、,，.。:：/\\\-—_+*%()（）]", "", s)
    return s


def resolve(name: str) -> Metric:
    """按 **中文名 → 内部 key → 归一化容错** 找一个指标。

    这是"语义寻址"：写论述的人只要知道"这个数是什么意思"，不需要知道程序里它叫什么。
    找不到一律抛错（绝不静默），由调用方用 `suggest()` 给出最像的候选。
    """
    key = (name or "").strip()
    if not key:
        raise KeyError("（空）")
    m = METRIC_BY_LABEL.get(key) or METRIC_BY_KEY.get(key)
    if m is not None:
        return m
    nk = _norm(key)
    if nk:
        for m in METRICS:
            if _norm(m.label) == nk:
                return m
        # 包含关系：写得比全名短（或长）也能命中，但**必须唯一**，否则算找不到
        hit = [m for m in METRICS if nk and (nk in _norm(m.label) or _norm(m.label) in nk)]
        if len(hit) == 1:
            return hit[0]
    raise KeyError(key)


def suggest(name: str, n: int = 3) -> list[tuple[str, str]]:
    """给最像的 n 个候选，返回 [(中文名, key)]，按相似度从高到低。"""
    nk = _norm(name)
    scored: list[tuple[int, str, str]] = []
    for m in METRICS:
        ml = _norm(m.label)
        if not nk or not ml:
            score = 0
        elif nk == ml:
            score = 100
        elif nk in ml or ml in nk:
            score = 60
        else:
            score = len(set(nk) & set(ml))          # 公共字符数
        scored.append((score, m.label, m.key))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [(label, key) for score, label, key in scored[:n] if score > 0]


_NAN_SETS_SEEN: set[frozenset] = set()


def _report_nan(metrics: list) -> None:
    """取值为 NaN 的条目，报一次就够（同一组合不重复刷屏）。

    为什么只报不中断：有些量的 NaN 是**设计如此**（REIT 回笼倍数跨模块派生失败时
    宁可空着也不冒充，见 metrics.toml 该条 note）。但"值为 NaN"必须让人看见——
    它渲染出来是 `nan亿元` 或一个破折号，与"这个数今天算不出来"长得一模一样。
    """
    if not metrics:
        return
    sig = frozenset(m.key for m in metrics)
    if sig in _NAN_SETS_SEEN:
        return
    _NAN_SETS_SEEN.add(sig)
    lines = [f"    {m.key:26} {m.label}（at={m.at or m.at_cfg}）" for m in metrics[:12]]
    tail = f"\n    ……另有 {len(metrics) - 12} 条" if len(metrics) > 12 else ""
    print(f"⚠ {len(metrics)} 个输出字典条目本次没有值（渲染成 nan／—）：\n"
          + "\n".join(lines) + tail)


def read_metrics(snapshot: ModelSnapshot, cfg: dict | None = None,
                 strict: bool = True) -> dict[str, float]:
    """按注册表取全部指标的值。

    `cfg` 给不给，决定 `needs_cfg=True` 的那批量算不算得出来——**必须给**。

    **strict（默认 True）：取不到就中断并点名。**
    为什么要由参数改为默认中断（2026-09-12 立）：以前 `except → NaN` 是完全静默的，
    `build.py` 一句 `read_metrics(snapshot)` 漏传 cfg，就让 6 条外部锚指标变成
    NaN，facts.json 里直接落成 `'nanGWh'`——一个 nan 和"这个数今天算不出来"
    在页面上长得一模一样，事后极难追回。**没值和值为零是两件事，都不能靠沉默打发。**

    两类失败分开处理：
    * **结构性失败**（`at` 路径走不通／调用方没传 cfg）→ 默认中断，列出每一条
      并指明去哪个程序查；
    * **数值为 NaN**（路径走通、程序主动给空，如 REIT 回笼倍数派生失败）→
      集中报一次，不中断（metrics.toml 的 note 里已写明它允许为空）。

    取不到一律 NaN，绝不用 0 或其他值冒充（"没有值"和"值为零"是两件事）。
    """
    values: dict[str, float] = {}
    broken: list[tuple] = []
    nans: list = []
    for metric in METRICS:
        if metric.needs_cfg and cfg is None:
            # 必须显式判：这批量的 getter 遇到 cfg=None 会**安静地返回 NaN**
            # （不是抛错），只靠 try/except 抓不到——这正是 bug 藏了这么久的原因。
            broken.append((metric, "调用方没传 cfg，这条配置侧（at_cfg）的量取不到"))
            values[metric.key] = float("nan")
            continue
        try:
            v = float(
                metric.getter(snapshot, cfg) if metric.needs_cfg else metric.getter(snapshot))
        except Exception as exc:
            broken.append((metric, f"{type(exc).__name__}: {exc}"))
            v = float("nan")
        else:
            if v != v:
                nans.append(metric)
        values[metric.key] = v

    _report_nan(nans)

    if broken and strict:
        raise SystemExit(_fmt_broken_metrics(broken, cfg is None))
    return values


def _fmt_broken_metrics(broken: list[tuple], no_cfg: bool) -> str:
    """把"取不到值"写成能照着修的话：每条给出处路径与去哪个程序查。"""
    head = f"✗ 输出字典里有 {len(broken)} 条取不到值（路径走不通，与值为空是两回事）："
    lines = []
    for metric, err in broken:
        where = f"at={metric.at}" if metric.at else f"at_cfg={metric.at_cfg}"
        lines.append(f"  - {metric.key}（{metric.label}）\n"
                     f"      {where}　source={metric.source or '—'}　错误：{err}")
    hint = ("\n  全部都报 KeyError 且 source 标了 external/at_cfg：调用方没传 cfg。"
            if no_cfg else "")
    fix = ("\n  怎么办：① 路径写错——去 metrics.toml 改 `at`；"
           "② 程序没算出这个数——去 `src/<source>.py` 里把它算出来；"
           "③ 确实是允许缺值的量——调用方显式写 `strict=False`。")
    return head + "\n" + "\n".join(lines) + hint + fix


# ══════════════════════════════════════════════════════════════════════
# 四、重跑：只跑核心链（不含并购对比与内置敏感性，故快）
# ══════════════════════════════════════════════════════════════════════

def rerun(config: dict, scenario_name: str | None = None) -> ModelSnapshot:
    return _build_core(config, scenario_name, "derived")


def perturbed(config: dict, path: str, factor: float | None = None,
              value: float | None = None) -> tuple[dict, float, float]:
    """返回 (新config, 原值, 新值)。factor 与 value 二选一。"""
    new_config = copy.deepcopy(config)
    old = float(get_path(new_config, path))
    if value is not None:
        new = float(value)
    else:
        new = old * factor if old else (abs(factor - 1.0) or 0.01)
    set_path(new_config, path, new)
    return new_config, old, new


# ══════════════════════════════════════════════════════════════════════
# 五、终端输出辅助（中文按 2 宽度对齐）
# ══════════════════════════════════════════════════════════════════════


def _width(text: str) -> int:
    return sum(2 if ord(ch) > 0x2E80 else 1 for ch in str(text))


def _ljust(text: Any, width: int) -> str:
    text = str(text)
    return text + " " * max(0, width - _width(text))


def _rjust(text: Any, width: int) -> str:
    text = str(text)
    return " " * max(0, width - _width(text)) + text


def _fmt(value: float, decimals: int) -> str:
    if value != value:  # NaN
        return "—"
    if abs(value) >= 1e6:
        return f"{value:,.0f}"
    return f"{value:,.{decimals}f}"


# ══════════════════════════════════════════════════════════════════════
# 六、命令实现
# ══════════════════════════════════════════════════════════════════════


def cmd_metrics(query: str = "") -> None:
    """查输出字典（configs/metrics.toml）。

    - 不带参数：列出全部指标（中文名 / 单位 / 分组），一眼看全模型算出了什么。
    - 带参数：按中文名查它对应哪个数（语义寻址），查不到就给最像的候选。
    """
    print("═" * 72)
    print(f"输出字典 configs/metrics.toml　共 {len(METRICS)} 个指标")
    print("═" * 72)
    if not query:
        by_group: dict[str, list[Metric]] = {}
        for m in METRICS:
            by_group.setdefault(m.group or "（未分组）", []).append(m)
        for group in sorted(by_group):
            print(f"\n【{group}】")
            for m in by_group[group]:
                unit = f" {m.unit}" if m.unit else ""
                src = f"　（src/{m.source}.py）" if m.source else ""
                print(f"  {m.label}{unit}　← {m.key}{src}")
        return
    try:
        m = resolve(query)
    except KeyError:
        print(f"\n✗ 「{query}」在字典里找不到")
        cands = suggest(query, 3)
        if cands:
            print("  最像的是：")
            for i, (label, key) in enumerate(cands, 1):
                print(f"   {i}. {label}　← {key}")
        else:
            print("  没有相似的条目——确实缺这个数的话，去 configs/metrics.toml 登记，")
            print("  并确认对应计算程序已把它算出来。")
        return
    print(f"\n✓ 「{query}」→ {m.label}　（内部名 {m.key}）")
    print(f"  单位 {m.unit or '—'}　精度 {m.decimals} 位　分组 {m.group or '—'}")
    print(f"  出处：src/{m.source}.py"
          if m.source else "  出处：（未登记 source）")
    if m.note:
        print(f"  口径：{m.note}")


def cmd_list(config: dict) -> None:
    docs = load_param_docs()
    params = iter_numeric_params(config)
    print(f"\n可调数值参数共 {len(params)} 个（已排除 URL/交易台账/参照公司事实/开关项）\n")
    print(_ljust("参数路径（改它就用这个完整路径）", 58) + _rjust("当前值", 12) + "   " + "一句话理由（完整推导见 MANIFEST）")
    print("─" * 132)
    last_section = ""
    for path, value in params:
        doc = docs.get(path, {})
        section = doc.get("section", path.rsplit(".", 1)[0])
        if section != last_section:
            print(f"\n■ {section}")
            last_section = section
        reason = doc.get("reason", "")
        if _width(reason) > 60:
            reason = reason[:58] + "…"
        print("  " + _ljust(path, 56) + _rjust(f"{value:g}", 12) + "   " + reason)
    print("\n提示：改参数用 impact 先看影响，再改 configs/base.toml。")


def cmd_impact(config: dict, base_values: dict[str, float], path: str, spec: str) -> None:
    if spec.endswith("%"):
        delta = float(spec[:-1]) / 100.0
        new_config, old, new = perturbed(config, path, factor=1.0 + delta)
        how = f"{old:g} → {new:g}（{spec}）"
    else:
        new_config, old, new = perturbed(config, path, value=float(spec))
        how = f"{old:g} → {new:g}"

    print(f"\n改动：{path}    {how}\n")
    try:
        # 扫描/微扰线路允许缺值：某些参数组合会让某个分部本身不存在
        # （如 heavy_economics 在重卡规模为零时没有值），那不是注册表写错。
        values = read_metrics(rerun(new_config), new_config, strict=False)
    except AssertionError as exc:
        print(f"✗ 该取值触发模型硬约束，未通过校验：\n  {exc}")
        print("  这不是程序错误——模型在告诉你这个参数不能单独这么调。")
        return
    except Exception as exc:  # noqa: BLE001
        print(f"✗ 重跑失败：{type(exc).__name__}: {exc}")
        return

    print(_ljust("指标", 26) + _rjust("改前", 14) + _rjust("改后", 14) + _rjust("变化", 12) + _rjust("幅度", 10))
    print("─" * 78)
    last_group = ""
    for metric in METRICS:
        if metric.group != last_group:
            print(f"\n{metric.group}")
            last_group = metric.group
        before = base_values[metric.key]
        after = values[metric.key]
        if before != before or after != after:
            continue
        diff = after - before
        pct = (diff / before * 100) if before else float("nan")
        flag = "  ←" if abs(pct if pct == pct else 0) >= 1 else ""
        print(
            "  " + _ljust(metric.label, 24)
            + _rjust(_fmt(before, metric.decimals), 14)
            + _rjust(_fmt(after, metric.decimals), 14)
            + _rjust(_fmt(diff, metric.decimals), 12)
            + _rjust(("—" if pct != pct else f"{pct:+.1f}%"), 10)
            + flag
        )
    print("\n（← 标记 = 变化超过 1%；未列出的指标未受影响）")


def cmd_lineage(config: dict, base_values: dict[str, float], metric_key: str,
                top: int = 15, step: float = 0.10) -> None:
    metric = METRIC_BY_KEY.get(metric_key)
    if metric is None:
        print(f"✗ 未知指标 {metric_key}。可用指标（python src/lab.py scan 也能看到）：")
        for m in METRICS:
            print(f"    {m.key:<28}{m.label}")
        return
    base_value = base_values[metric.key]
    print(f"\n追溯：{metric.label}（当前 {_fmt(base_value, metric.decimals)} {metric.unit}）")
    print(f"做法：逐个参数单独 {step:+.0%}，实测该指标的反应（弹性 = 指标变化% ÷ 参数变化%）\n")

    params = iter_numeric_params(config)
    rows: list[tuple[str, float, float, float]] = []
    t0 = time.time()
    for index, (path, old) in enumerate(params, 1):
        if abs(old) < 1e-12:
            factor = 1.0 + step  # 零值参数改用绝对微扰，避免除零
            new_config, _, _ = perturbed(config, path, value=step)
        else:
            new_config, _, _ = perturbed(config, path, factor=1.0 + step)
            factor = 1.0 + step
        try:
            after = metric.getter(rerun(new_config))
        except Exception:  # noqa: BLE001 - 触发硬约束的参数记 0 影响
            continue
        if after != after:
            continue
        diff = after - base_value
        if base_value:
            pct = diff / base_value
        else:
            pct = 0.0 if abs(diff) < 1e-12 else float("inf") if diff else 0.0
        elasticity = pct / (factor - 1.0) if factor != 1.0 else 0.0
        rows.append((path, old, diff, elasticity))
        if index % 40 == 0:
            print(f"    …已试 {index}/{len(params)} 个参数（{time.time() - t0:.0f}s）", flush=True)

    rows.sort(key=lambda r: abs(r[3]), reverse=True)
    print(_ljust("上游参数", 54) + _rjust("参数值", 12) + _rjust(f"{step:+.0%}后的变化", 16) + _rjust("弹性", 10))
    print("─" * 94)
    for path, old, diff, elasticity in rows[:top]:
        bar = "█" * min(20, int(abs(elasticity) * 20))
        print(
            _ljust(path, 54)
            + _rjust(f"{old:g}", 12)
            + _rjust(_fmt(diff, metric.decimals), 16)
            + _rjust(f"{elasticity:+.2f}", 10)
            + "  " + bar
        )
    print(f"\n共 {len(params)} 个参数参与实测，上表为影响最大的前 {top} 个。")
    print("弹性读法：+1.00 = 参数涨 10%、指标涨 10%；0.00 = 该参数根本没进这条链。")


def _is_pair(v) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == 2


def _pair(v) -> list[float]:
    return [float(v[0]), float(v[1])]


def param_bounds_dict(config: dict) -> dict[str, list[float]]:
    """合并所有「可选区间」：情景轴参数从 [drivers.*].bounds 取，
    非情景轴参数从 [param_bounds."路径"].bounds 取。供沙盘滑块/反解约束用。

    ★ 相对轴（mode="relative"）的 bounds 是**乘数**的允许范围，不是取值区间
    （见 base.toml [drivers] 段头注释）。必须按「取值 = 基线 × 乘数」换算后再用，
    否则沙盘会把「换电渗透率」的滑块直接设成 [0.5, 1.5]——既能拖到 150%，
    又把现值 0.30 卡在滑块下限之下被静默 clamp。换算后再受该轴 cap 约束。
    """
    out: dict[str, list[float]] = {}
    for spec in config.get("drivers", {}).values():
        b = spec.get("bounds")
        if not _is_pair(b):
            continue
        lo_m, hi_m = _pair(b)
        cap = spec.get("cap")
        for path in spec.get("targets", [spec.get("target")]):
            if not path:
                continue
            if spec.get("mode") != "relative":
                out[path] = [lo_m, hi_m]      # 绝对模式：bounds 就是取值区间
                continue
            try:
                base = _cfg_get(config, path)
            except (KeyError, IndexError, TypeError):
                continue
            if isinstance(base, list) or not isinstance(base, (int, float)):
                continue          # 数组型（S 曲线）不进滑块，不设区间
            lo, hi = base * lo_m, base * hi_m
            if cap is not None:
                hi = min(hi, float(cap))
            if hi <= lo:
                continue          # 基线为 0（如城配低频）→ 区间退化，不设
            out[path] = [lo, hi]
    # 向量型轴（三档是 dict，如 charge_share／private_penetration）：没有 bounds 声明，
    # 区间直接取三档分量的 [最小, 最大]——沙盘滑块即可在三档之间连续取值。
    for spec in config.get("drivers", {}).values():
        tiers = [spec.get(t) for t in SCENARIO_ORDER]
        if not all(isinstance(t, dict) for t in tiers):
            continue
        b = spec.get("bounds")
        for path in spec.get("targets", []):
            if _is_pair(b):                    # 向量轴也可直接声明区间（如私家车渗透率 [0,1]）
                out[path] = _pair(b)
                continue
            key = _scene_name(config, path) or path.split(".")[-1]
            try:
                comps = [t[key] for t in tiers]
            except KeyError:
                continue
            lo, hi = min(comps), max(comps)
            if hi > lo:
                out[path] = [lo, hi]
    # 场景级结构边界：权重/渗透率/份额天然在 [0,1]（同车型权重和恒为 1，
    # 余下场景自动倒扣——联动在沙盘里做）。驱动轴算出的区间优先，故用 setdefault。
    for vkey, vspec in (config.get("vehicles") or {}).items():
        if not isinstance(vspec, dict):
            continue
        for i in range(len(vspec.get("scenes") or [])):
            base = f"vehicles.{vkey}.scenes.{i}."
            out.setdefault(base + "weight", [0.0, 1.0])
            out.setdefault(base + "swap_penetration", [0.0, 1.0])
            out.setdefault(base + "catl_swap_share", [0.0, 1.0])
    for path, spec in (config.get("param_bounds") or {}).items():
        if isinstance(spec, dict):
            b = spec.get("bounds")
            if _is_pair(b):
                out[path] = _pair(b)
        elif _is_pair(spec):
            out[path] = _pair(spec)
    return out


def param_cn_dict(config: dict) -> dict[str, str]:
    """参数路径 → 中文名（从 [drivers.*].cn 与 [param_bounds."路径"].cn 合并）。"""
    out: dict[str, str] = {}
    for spec in config.get("drivers", {}).values():
        cn = spec.get("cn")
        if cn:
            for path in spec.get("targets", [spec.get("target")]):
                if path:
                    out[path] = cn
    for path, spec in (config.get("param_bounds") or {}).items():
        if isinstance(spec, dict) and spec.get("cn"):
            out[path] = spec["cn"]
    return out


def scene_label_map(config: dict) -> dict[str, str]:
    """「vehicles.<车型>.scenes.<下标>」→「车型·场景」中文名。

    场景级参数在沙盘/工作簿里显示为 vehicles.heavy.scenes.0.swap_penetration，
    光看下标 0/1/2 不知道是短途还是长途。这里把下标换成场景自己的 name
    （重卡·短途 / 重卡·中途 / 重卡·长途 / 城配物流·高频 …），全车型统一。
    """
    out: dict[str, str] = {}
    for vkey, vspec in (config.get("vehicles") or {}).items():
        if not isinstance(vspec, dict):
            continue
        vlabel = vspec.get("label") or vkey
        for i, scene in enumerate(vspec.get("scenes") or []):
            if isinstance(scene, dict) and scene.get("name"):
                name = scene["name"]
                # 单车单场景（出租车/网约车/Robotaxi）会出现「出租车·出租车」，去重
                out[f"vehicles.{vkey}.scenes.{i}"] = (
                    vlabel if name == vlabel else f"{vlabel}·{name}"
                )
    return out


def compute_elasticity(
    config: dict,
    base_values: dict[str, float],
    step: float = 0.10,
    quiet: bool = True,
    also: tuple[str, ...] = (),
) -> dict[str, dict[str, float]]:
    """逐个参数单独微扰、重跑、比对——用实测得出完整的「参数 × 指标」血缘矩阵。

    不解析代码、不登记公式：模型改版后重跑即得新血缘，永远不会和代码脱钩。
    触发模型硬约束（assert）的参数记为 {} ——那不是错误，是模型在说它不能单独这么调。
    also：透传给 iter_numeric_params（沙盘要测 charge_share 的弹性）。
    """
    params = iter_numeric_params(config, include_arrays=True, also=also)
    elasticity: dict[str, dict[str, float]] = {}
    t0 = time.time()
    for index, (path, old) in enumerate(params, 1):
        new_config = copy.deepcopy(config)
        set_path(new_config, path, _perturb(old, step))
        try:
            # 扫描/微扰线路允许缺值：某些参数组合会让某个分部本身不存在
            # （如 heavy_economics 在重卡规模为零时没有值），那不是注册表写错。
            values = read_metrics(rerun(new_config), new_config, strict=False)
        except Exception:  # noqa: BLE001
            elasticity[path] = {}
            continue
        row: dict[str, float] = {}
        for metric in METRICS:
            before, after = base_values[metric.key], values[metric.key]
            if before != before or after != after:
                continue
            row[metric.key] = (((after - before) / before) / step) if before else 0.0
        elasticity[path] = row
        if not quiet and index % 50 == 0:
            print(f"    …{index}/{len(params)}（{time.time() - t0:.0f}s）", flush=True)
    return elasticity


def compute_axis_matrix(
    config: dict,
    base_values: dict[str, float],
    step: float = 0.10,
) -> dict[str, dict[str, float]]:
    """轴级敏感性：把一条 [drivers] 轴的全部 targets **一起** +step，返回「轴 × 指标」弹性矩阵。

    为什么单参数表里看不出「车辆规模」：轴是"一组参数同时平移"（如
    commercial_swap_share 同时动 5 个场景的换电渗透率），而单参数扫描一次只动一个
    参数，单个场景的渗透率弹性当然很小。这里补的正是「整条轴的合力」，
    而且是**全指标**的——不只告诉你增量价值变多少，还告诉你收入/EBITDA/装机/站数
    各被动了多少，用来挑出"最该跟踪的那几个指标"。
    """
    from config_loader import load_drivers  # 局部导入，避免与顶层 import 重复

    out: dict[str, dict[str, float]] = {}   # 轴 → {指标键: 弹性}
    for name, spec in load_drivers(config).items():
        if "pass_as" in spec:
            continue
        targets = spec["targets"] if "targets" in spec else ([spec["target"]] if "target" in spec else [])
        if not targets:
            continue
        cap = spec.get("cap")
        # 非数值型 target（如字符串档位选择器）跳过——它不是数字旋钮。
        # charge_share 已是数值型逐车型活值，正常走下方 +step 扰动。
        new_config = copy.deepcopy(config)
        used = 0
        try:
            for t in targets:
                base = _cfg_get(new_config, t)
                if not isinstance(base, (int, float)) and not (
                    isinstance(base, list) and base
                    and all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in base)
                ):
                    continue  # 字符串/档位选择器
                val = [x * (1.0 + step) for x in base] if isinstance(base, list) else base * (1.0 + step)
                if cap is not None:
                    val = [min(x, cap) for x in val] if isinstance(val, list) else min(val, cap)
                set_path(new_config, t, val)
                used += 1
            if not used:
                out[name] = {}  # 纯档位选择器，无数值旋钮可摆
                continue
            # 扫描/微扰线路允许缺值：某些参数组合会让某个分部本身不存在
            # （如 heavy_economics 在重卡规模为零时没有值），那不是注册表写错。
            values = read_metrics(rerun(new_config), new_config, strict=False)
        except Exception:  # noqa: BLE001  # 触发模型硬约束的轴记为不可算
            out[name] = {}
            continue
        row: dict[str, float] = {}
        for metric in METRICS:
            before, after = base_values[metric.key], values[metric.key]
            if before != before or after != after:  # NaN 跳过
                continue
            row[metric.key] = (((after - before) / before) / step) if before else 0.0
        out[name] = row
    return out


def compute_axis_leverage(config: dict, base_values: dict[str, float],
                          step: float = 0.10) -> dict[str, float]:
    """每条轴对「最终投资指标」的杠杆（＝轴级矩阵的锚点那一列），供排序用。"""
    return {
        name: abs(row.get(INFLUENCE_ANCHOR, float("nan")))
        for name, row in compute_axis_matrix(config, base_values, step).items()
    }


def axis_tier_effect(config: dict, drivers: dict, neutral_kwargs: dict,
                     base_values: dict) -> list[tuple]:
    """每条轴**单独**摆到悲观/乐观档（其余轴保持中性），实测各指标变了多少。

    与 03_敏感性矩阵同族：那边是"单参数 × 指标"的弹性，这里是"整条轴 × 指标"的
    **真实档位影响**。回答："这条轴调到乐观，增量价值多多少？收入/EBITDA 各变多少？"
    """
    rows: list[tuple] = []
    for name, spec in drivers.items():
        for tier in ("悲观", "乐观"):
            cfg = copy.deepcopy(config)
            kw = dict(neutral_kwargs)
            try:
                kw.update(apply_scenario(cfg, {name: spec}, tier))
                values = read_metrics(build_model(cfg, **kw), cfg, strict=False)
            except Exception:  # noqa: BLE001
                continue
            d_abs = values.get(INFLUENCE_ANCHOR, 0.0) - base_values.get(INFLUENCE_ANCHOR, 0.0)
            d_pct = {}
            for m in METRICS:
                b, a = base_values.get(m.key), values.get(m.key)
                if b is None or a is None or b != b or a != a or not b:
                    continue
                d_pct[m.key] = (a - b) / b
            rows.append((name, tier, _tier_text(spec, tier), d_abs, d_pct))
    return rows


def _tier_text(spec: dict, tier: str) -> str:
    v = spec.get(tier)
    if spec.get("mode") == "relative":
        return f"×{v}"
    if "pass_as" in spec:
        return f"→ {v}"
    # 注意：不能以 "=" 开头——Excel 会当成公式，读回来是空值
    return f"定档 {v}"


def export_axis_sheet(wb, axis_rows) -> None:
    """03b：轴级影响 —— 一条轴整体摆档后，各指标实际变了多少（放 03 旁边，同族同址）。"""
    from openpyxl.formatting.rule import ColorScaleRule
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    # 与 03_敏感性矩阵同族同址：物理位置也紧跟在它后面
    titles = wb.sheetnames
    idx = titles.index("03_敏感性矩阵") + 1 if "03_敏感性矩阵" in titles else None
    ws = wb.create_sheet("03b_轴级影响（整条轴一起摆）", idx)
    head = ["情景轴", "档位", "档位取值", "换电增量价值 Δ(亿元)",
            *[m.label + " Δ%" for m in METRICS]]
    ws.append(head)
    for cell in ws[1]:
        cell.font = Font(bold=True, size=10)
        cell.fill = PatternFill("solid", fgColor="EFF0F3")
        cell.alignment = Alignment(vertical="center", wrap_text=True)

    for name, tier, tier_text, d_abs, d_pct in axis_rows:
        ws.append([name, tier, tier_text, round(d_abs, 2),
                   *[round(d_pct.get(m.key, 0.0) * 100, 2) for m in METRICS]])

    ws.freeze_panes = "E2"
    for i, w in enumerate([26, 8, 12, 20, *[13] * len(METRICS)], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    last = get_column_letter(4 + len(METRICS))
    ws.conditional_formatting.add(
        f"E2:{last}{ws.max_row}",
        ColorScaleRule(start_type="min", start_color="F8CBAD",
                       mid_type="num", mid_value=0, mid_color="FFFFFF",
                       end_type="max", end_color="C6E0B4"))
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=(cell.column <= 3))


# 总影响力口径（问题1修正）：只算「估值相关终端指标」，排除物理中间量(①运营规模/②制造出货)
# 且在终端层内剔除「合计值 vs 其分项」的恒等式重复：
#   · ④ 运营年收入 已含 服务费/租金/辅助 → 剔除那三个分项
#   · EBITDA = 年收入 − OPEX（可由二者推出）→ 剔除 EBITDA，保留覆盖倍数(比率)
#   · ⑤ 增量价值/集团市值 与 换电增量价值 弹性完全相同(市值=外部常数) → 只留归一化口径
#   · 有/无换电动力价值 是绝对值、增量=有−无 → 只留 增量价值/市值 与 有换电制造净利
# 这样排名不再把「电量→EBITDA→估值」这类链式传染重复加总。
VALUATION_TERMINAL_METRICS = [
    # ③ 资本层（投入与出资）
    "capex.initial_capex", "capex.equity_call", "capex.peak_call", "capex.project_debt",
    # ④ 运营财务层（实际业绩；已剔除分项与可推导项）
    "swap.revenue", "swap.opex", "swap.coverage", "swap.operating_value",
    # ⑤ 估值层（资本市场影响；已剔除绝对值恒等式重复）
    "mfg.with_swap_np", "val.incr_over_mktcap",
    # ⑥ 资金层（资金压力与战略敞口）
    "fund.peak_cash_to_cfo", "fund.closing_liquidity", "fund.exposure",
]
_VALUATION_TERMINAL_SET = set(VALUATION_TERMINAL_METRICS)


# 总影响力口径（问题1修正）：锚定在「最终投资指标」——换电给 CATL 的增量价值
# （val.swap_increment，含运营侧 + 制造侧，是这门生意最终值多少钱的唯一综合口径），
# 不再按「受影响指标个数 / 多个终端指标求和」加总。理由：rte 之类成本参数会顺着
# 电量→EBITDA→估值链式传染到一堆中间/终端指标，按个数或多项求和会被它虚高排名；
# 锚定到增量价值后，排名直接回答「这个参数动一下，CATL 的换电增量价值变多少」，
# 才是决策该看的重要度。03_敏感性矩阵仍展示全指标弹性明细，本锚只用于排序与星级。
INFLUENCE_ANCHOR = "val.swap_increment"


def total_influence(row: dict[str, float]) -> float:
    """锚定在最终投资指标（换电增量价值）的单指标弹性绝对值，不作多项加总。"""
    return abs(row.get(INFLUENCE_ANCHOR, 0.0))


def _short(path: str) -> str:
    """参数路径的简短显示：保留末两段，避免表格被撑爆。"""
    parts = path.split(".")
    return ".".join(parts[-2:]) if len(parts) > 2 else path


def _display_value(value: Any) -> Any:
    """表里「当前值」的显示：数值原样；曲线型数组压成紧凑文本（单元格放不下整条曲线）。"""
    if isinstance(value, list):
        return "[" + ", ".join(f"{x:g}" for x in value) + "]"
    return value


def cmd_workbook(config: dict, base_values: dict[str, float], step: float = 0.10) -> None:
    """生成 Excel 工作簿：假设表 / 结果表 / 敏感性矩阵 / 双向血缘。

    对应财务建模的三张表习惯，但血缘不是人写的注释，是实测出来的。
    """
    if Workbook is None:
        print("缺少 openpyxl，请先安装：pip install openpyxl")
        return

    print(f"正在实测全参数血缘（每个参数单独 {step:+.0%}）…", flush=True)
    t0 = time.time()
    elasticity = compute_elasticity(config, base_values, step)
    print(f"血缘实测完成（{time.time() - t0:.0f}s）")

    docs = load_param_docs()
    params = dict(iter_numeric_params(config))  # 标量：进 01 表，可试算/可落盘
    # 含曲线型：03 矩阵要展示它们（NEV 渗透率 S 曲线等），但 01 表不放
    all_params = dict(iter_numeric_params(config, include_arrays=True))
    influence = {p: total_influence(row) for p, row in elasticity.items()}

    def new_sheet(wb, title: str, first: bool = False):
        return wb.active if first else wb.create_sheet(title)

    wb = Workbook()

    # ── Sheet 0：怎么用 ────────────────────────────────────────────
    ws = wb.active
    ws.title = "00_怎么用"
    guide = [
        ("换电战略决策模型 v4.3 — 参数与血缘工作簿", True),
        ("", False),
        ("生成方式：python src/lab.py workbook（改模型后重跑本命令即可刷新全部内容）", False),
        ("", False),
        ("【这张表解决什么问题】", True),
        ("模型拆成 configs/src/outputs 之后，改一个参数看不出它影响了谁——Excel 里靠「追踪引用/从属单元格」，", False),
        ("这里靠实测：把每个参数单独 +10%，重跑同一条计算链，比对全部指标。所以下面的血缘不是注释，是测量值。", False),
        ("", False),
        ("【五个页签怎么读】", True),
        ("01_假设参数　　全部可调参数：值 + 为什么这么假设 + 影响力星级。浅蓝底＝可调。", False),
        (f"02_结果总表　　{len(METRICS)} 个输出结果，每个都标出「决定它的三个参数」。", False),
        ("03_敏感性矩阵　参数 × 指标的完整弹性表，红绿配色＝方向和强弱。", False),
        ("04_溯源　　　　选中一个结果，看它由哪些参数决定（＝Excel 追踪引用单元格）。", False),
        ("05_影响　　　　选中一个参数，看它推动哪些结果（＝Excel 追踪从属单元格）。", False),
        ("", False),
        ("【弹性怎么读】", True),
        ("弹性 = 参数 +10% 时，该指标变化百分之几 ÷ 10%。例：+1.00＝参数涨 10%、指标涨 10%（同比例）；", False),
        ("-1.50＝参数涨 10%、指标跌 15%（放大且反向）；0.00＝这个参数根本没进这条链，调它不影响该结果。", False),
        ("", False),
        ("【影响力/弹性是怎么算出来的】", True),
        ("只做一件事：把参数单独 +10%，重跑同一条计算链，比对全部结果。不解析代码、不登记公式，", False),
        ("所以模型改版后重跑即得新血缘，永远不会和代码脱钩。完整逐步演算见 06_算法演示 页签。", False),
        ("「总影响力」＝该参数对「最终投资指标」换电增量价值(val.swap_increment) 的弹性绝对值。", False),
        ("　　锚定在『这门生意最终值多少钱』这一个口径，不再按『受影响指标个数 / 多个终端指标求和』加总——", False),
        ("　　否则 rte 之类成本参数会顺着 电量→EBITDA→估值 链式传染到一堆指标、被虚高排名。总影响力只用来给参数排重要度，不作决策数字。", False),
        ("", False),
        ("【改参数的标准动作（不想碰代码，全在 Excel 里完成）】", True),
        ("1. python src/lab.py workbook  → 生成本工作簿，01_假设参数 多出一列「试算值(改这里)」", False),
        ("2. 在 Excel 里把想试的参数那格改成新值（其余别动）", False),
        ("3. python src/lab.py trial  → 看 07_试算对比：基准值 vs 试算值，变化≥±5% 自动标黄", False),
        ("4. 满意了 → python src/lab.py commit  → 改动安全写回 base.toml（保留原注释）", False),
        ("5. python src/run.py 刷新快照与报告，再 python src/backscan.py MANIFEST.md 验收 15/15", False),
        ("", False),
        ("【只想知道单个参数动一下会怎样（不进 Excel）】", True),
        ("命令行：python src/lab.py impact <参数路径> <新值|±%>  只看结果，不动任何文件", False),
        ("", False),
        ("【口径纪律】", True),
        ("· 本工作簿的所有数字都来自 outputs/decision_snapshot，与骨架报告同源，不存在第二套数。", False),
        ("· 一句话理由取自 base.toml 注释（前两行）；完整推导与信源一律见 MANIFEST.md，不在此展开。", False),
        ("· 影响力星级：★★★ 弹性≥1.0（动它要慎，直接撼动换电增量价值）｜★★ ≥0.4｜★ ≥0.15｜空白＝几乎不影响增量价值。", False),
    ]
    for row_index, (text, bold) in enumerate(guide, 1):
        cell = ws.cell(row=row_index, column=1, value=text)
        if bold:
            cell.font = Font(bold=True, size=12 if row_index == 1 else 11)
    set_widths(ws, [118])

    # ── Sheet 1：假设参数表 ────────────────────────────────────────
    ws = wb.create_sheet("01_假设参数")
    headers = ["序号", "所属段", "参数路径", "当前值", "试算值(改这里)", "一句话理由（为什么这么假设）", "总影响力", "关键度"]
    ws.append(headers)
    style_header(ws, 1, len(headers))

    grouped: dict[str, list[str]] = {}
    for path in params:
        section = docs.get(path, {}).get("section", path.rsplit(".", 1)[0])
        grouped.setdefault(section, []).append(path)

    row_index = 1
    serial = 0
    for section in sorted(grouped):
        paths = sorted(grouped[section], key=lambda p: influence.get(p, 0.0), reverse=True)
        for path in paths:
            serial += 1
            row_index += 1
            total = influence.get(path, 0.0)
            stars = "★★★" if total >= 1.0 else "★★" if total >= 0.4 else "★" if total >= 0.15 else ""
            ws.append([
                serial,
                section,
                path,
                params[path],
                params[path],   # 试算值：初始=当前值，用户在 Excel 里改这一格
                docs.get(path, {}).get("reason", ""),
                round(total, 3),
                stars,
            ])
            ws.cell(row=row_index, column=4).fill = EDIT_FILL
            ws.cell(row=row_index, column=5).fill = EDIT_FILL
            for col in (1, 4, 5, 7, 8):
                ws.cell(row=row_index, column=col).alignment = Alignment(horizontal="center")
            ws.cell(row=row_index, column=6).alignment = WRAP
    set_widths(ws, [6, 24, 52, 13, 13, 58, 10, 7])

    # ── Sheet 2：结果总表 ─────────────────────────────────────────
    ws = wb.create_sheet("02_结果总表")
    headers = ["分组", "指标", "当前值", "单位", "决定它的三个参数（弹性）"]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    for row_index, metric in enumerate(METRICS, 2):
        column = [(p, elasticity.get(p, {}).get(metric.key, 0.0)) for p in elasticity]
        column = [c for c in column if abs(c[1]) >= 0.005]
        column.sort(key=lambda c: abs(c[1]), reverse=True)
        drivers = "；".join(f"{_short(p)} {v:+.2f}" for p, v in column[:3]) or "（不受单参数显著影响）"
        ws.append([metric.group, metric.label, base_values[metric.key], metric.unit, drivers])
        # 年份整数无千分位（2030，不是 2,030）；其余按 decimals 给千分位格式
        if metric.fmt == "year":
            number_format = "0"
        else:
            number_format = f"#,##0.{'0' * metric.decimals}" if metric.decimals > 0 else "#,##0"
        ws.cell(row=row_index, column=3).number_format = number_format
        ws.cell(row=row_index, column=5).alignment = WRAP
    set_widths(ws, [8, 26, 16, 10, 62])

    # ── Sheet 3：敏感性矩阵 ────────────────────────────────────────
    ws = wb.create_sheet("03_敏感性矩阵")
    headers = ["参数路径", "当前值", "总影响力", *[m.label for m in METRICS]]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    ordered = sorted(elasticity, key=lambda p: influence.get(p, 0.0), reverse=True)
    for row_index, path in enumerate(ordered, 2):
        row = elasticity.get(path, {})
        ws.append([
            path,
            _display_value(all_params.get(path)),
            round(influence.get(path, 0.0), 2),
            *[round(row.get(m.key, 0.0), 3) for m in METRICS],
        ])
    last_row = len(ordered) + 1
    ws.conditional_formatting.add(
        f"D2:{get_column_letter(3 + len(METRICS))}{last_row}",
        ColorScaleRule(
            start_type="num", start_value=-1.5, start_color="F8696B",
            mid_type="num", mid_value=0, mid_color="FFFFFF",
            end_type="num", end_value=1.5, end_color="63BE7B",
        ),
    )
    set_widths(ws, [56, 12, 10, *[13] * len(METRICS)])

    # ── Sheet 4：溯源（结果 ← 参数）─────────────────────────────────
    ws = wb.create_sheet("04_溯源_谁决定这个结果")
    headers = ["结果指标", "当前值", "单位", "上游参数", "参数值", "弹性", "方向"]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    row_index = 1
    for metric in METRICS:
        row_index += 1
        ws.cell(row=row_index, column=1, value=metric.label).fill = BLOCK_FILL
        ws.cell(row=row_index, column=1).font = Font(bold=True)
        ws.cell(row=row_index, column=2, value=base_values[metric.key]).font = Font(bold=True)
        ws.cell(row=row_index, column=3, value=metric.unit)
        column = [(p, elasticity.get(p, {}).get(metric.key, 0.0)) for p in elasticity]
        column = [c for c in column if abs(c[1]) >= 0.005]
        column.sort(key=lambda c: abs(c[1]), reverse=True)
        if not column:
            ws.cell(row=row_index, column=4, value="（不受任何单参数显著影响）")
            continue
        for path, value in column[:12]:
            row_index += 1
            ws.append([None, None, None, path, _display_value(all_params.get(path)), round(value, 3),
                       "↑同向" if value > 0 else "↓反向"])
            ws.cell(row=row_index, column=6).alignment = Alignment(horizontal="center")
    set_widths(ws, [26, 14, 10, 54, 14, 10, 10])

    # ── Sheet 5：影响（参数 → 结果）─────────────────────────────────
    ws = wb.create_sheet("05_影响_这个参数推动哪些结果")
    headers = ["参数路径", "参数值", "受影响的结果", "结果当前值", "弹性"]
    ws.append(headers)
    style_header(ws, 1, len(headers))
    row_index = 1
    for path in ordered[:40]:
        row = {k: v for k, v in elasticity.get(path, {}).items() if abs(v) >= 0.005}
        if not row:
            continue
        row_index += 1
        ws.cell(row=row_index, column=1, value=path).fill = BLOCK_FILL
        ws.cell(row=row_index, column=1).font = Font(bold=True)
        ws.cell(row=row_index, column=2, value=_display_value(all_params.get(path)))
        for metric_key, value in sorted(row.items(), key=lambda kv: abs(kv[1]), reverse=True)[:10]:
            metric = METRIC_BY_KEY[metric_key]
            row_index += 1
            ws.append([None, None, metric.label, base_values[metric_key], round(value, 3)])
            ws.cell(row=row_index, column=5).alignment = Alignment(horizontal="center")
    set_widths(ws, [56, 14, 28, 16, 10])

    # ── Sheet 6：算法演示（把弹性的计算过程摊开，不留黑箱）────────────
    demo_param = "swap_business.service_fee_rmb_kwh"
    demo_metric = "val.swap_increment"
    metric = METRIC_BY_KEY[demo_metric]
    demo_old = float(get_path(config, demo_param))
    demo_cfg = copy.deepcopy(config)
    set_path(demo_cfg, demo_param, demo_old * (1.0 + step))
    demo_after = read_metrics(rerun(demo_cfg), demo_cfg, strict=False)[demo_metric]
    demo_before = base_values[demo_metric]
    demo_diff = demo_after - demo_before
    demo_pct = (demo_diff / demo_before) if demo_before else 0.0
    demo_elas = demo_pct / step

    ws = wb.create_sheet("06_算法演示_弹性怎么算出来的")
    ws.append(["弹性的计算过程——拿一个真实例子从头算一遍"])
    ws.cell(row=1, column=1).font = Font(bold=True, size=12)
    ws.append([])
    ws.append(["被调参数", demo_param, "（换电服务费，元/kWh）"])
    ws.append(["被看指标", metric.label, metric.unit])
    ws.append([])
    headers = ["步骤", "这一步在做什么", "算式", "结果"]
    ws.append(headers)
    style_header(ws, 6, len(headers))
    steps = [
        ("① 读基准参数", "从 configs/base.toml 原样读出", "—", f"{demo_old:g} 元/kWh"),
        ("② 扰动参数", f"只把这一个参数 {step:+.0%}，其余一律不动",
         f"{demo_old:g} × {1 + step:g}", f"{demo_old * (1 + step):g} 元/kWh"),
        ("③ 基准重跑", "用原参数跑完整计算链，读该指标", "—", f"{demo_before:,.1f} {metric.unit}"),
        ("④ 扰动重跑", "用②的参数再跑一遍同一条链", "—", f"{demo_after:,.1f} {metric.unit}"),
        ("⑤ 算变化额", "④ − ③", f"{demo_after:,.1f} − {demo_before:,.1f}", f"{demo_diff:+,.1f} {metric.unit}"),
        ("⑥ 算变化率", "⑤ ÷ ③", f"{demo_diff:,.1f} ÷ {demo_before:,.1f}", f"{demo_pct:+.2%}"),
        ("⑦ 算弹性", f"⑥ ÷ {step:.0%}（换算成「每 1%」的力道）",
         f"{demo_pct:+.2%} ÷ {step:.0%}", f"{demo_elas:+.2f}"),
    ]
    for text, what, formula, result in steps:
        ws.append([text, what, formula, result])
        ws.cell(row=ws.max_row, column=4).alignment = Alignment(horizontal="right")
    ws.append([])
    ws.append(["结论", f"服务费每涨 1%，『{metric.label}』就涨约 {demo_elas:.2f}——03 表每一行就是这样一个『参数→指标』的弹性。", "", ""])
    ws.append(["", "而『总影响力』那一列不把这些弹性相加，只取它对最终指标『换电增量价值(val.swap_increment)』的弹性绝对值。", "", ""])
    ws.append([])
    ws.append(["「总影响力」又是什么", "", "", ""])
    ws.append(["", "把同一个参数对「最终投资指标」换电增量价值(val.swap_increment) 的弹性取绝对值，得到它撬动这门生意总价值的力度。", "", ""])
    ws.append(["", "不再按『受影响指标个数 / 多个终端指标求和』加总——rte 之类成本参数会顺着 电量→EBITDA→估值 链式传染，", "", ""])
    ws.append(["", "按个数或多项求和会被它虚高排名；锚定到增量价值后，排名直接回答『动它一下，CATL 换电增量价值变多少』。", "", ""])
    ws.append(["", "要看具体哪个结果、变了多少，请回到 03/05 表。", "", ""])
    ws.append([])
    ws.append(["这方法的三条局限（必须知道）", "", "", ""])
    ws.append(["", "1. 一次只动一个参数，不含「两个一起变」的交互效应；真实世界常常是联动的。", "", ""])
    ws.append(["", f"2. 步长固定 {step:+.0%}。若关系是弯曲的（取整、min/max、ceil 都会造成弯折），", "", ""])
    ws.append(["", "　　换个步长算出的弹性会变——所以它叫「局部弹性」。", "", ""])
    ws.append(["", "3. 触发模型硬约束（assert）的参数会被跳过、弹性留空。那不是报错，", "", ""])
    ws.append(["", "　　是模型在告诉你：这个参数不能单独这么调（例如规划能力不能超过物理上限）。", "", ""])
    set_widths(ws, [22, 62, 30, 24])

    out_dir = ROOT.parent / "outputs"
    out_dir.mkdir(parents=True, exist_ok=True)
    xlsx_path = out_dir / "换电模型_参数与血缘_v4.3.xlsx"
    try:
        wb.save(xlsx_path)
    except PermissionError:
        fallback = out_dir / "换电模型_参数与血缘_v4.3_新.xlsx"
        wb.save(fallback)
        print(f"\n⚠ 目标文件被占用（多半是 Excel 正打开它），已改写到：\n  {fallback}")
        print("  关闭 Excel 里的旧文件后重新运行本命令，即可覆盖回原文件名。")
        return
    # ── Sheet 03b：轴级影响（与 03 同族：都是「× 指标」矩阵，
    #    只是一个是单参数粒度、一个是整条轴粒度，故必须放同一个工作簿）
    _cfg = load_config()
    _drv = load_drivers(_cfg)
    _nk = apply_scenario(_cfg, _drv, "中性")
    export_axis_sheet(wb, axis_tier_effect(
        _cfg, _drv, _nk, read_metrics(build_model(_cfg, **_nk), _cfg, strict=False)))

    print(f"\n已生成：{xlsx_path}")
    print("  00_怎么用 / 01_假设参数 / 02_结果总表 / 03_敏感性矩阵 / 03b_轴级影响 / 04_溯源 / 05_影响")


# ══════════════════════════════════════════════════════════════════════
# 五、试算闭环：在 Excel 里改「试算值」→ trial 看结果 → commit 落盘
# ══════════════════════════════════════════════════════════════════════

def _locate_workbook() -> Path:
    """优先用规范文件名；被 Excel 占用时回退到 _新 副本。"""
    out_dir = ROOT.parent / "outputs"
    canonical = out_dir / "换电模型_参数与血缘_v4.3.xlsx"
    fallback = out_dir / "换电模型_参数与血缘_v4.3_新.xlsx"
    if canonical.exists():
        return canonical
    if fallback.exists():
        return fallback
    raise SystemExit("找不到工作簿，请先跑：python src/lab.py workbook")


def _read_trials(xlsx_path: Path) -> dict[str, tuple[float, float]]:
    """从 01_假设参数 的「试算值」列读出 (当前值, 试算值)，只保留改过的。"""
    wb = load_workbook(xlsx_path, data_only=True)
    ws = wb["01_假设参数"]
    rows = list(ws.iter_rows(values_only=True))
    header = list(rows[0])
    i_path = header.index("参数路径")
    i_cur = header.index("当前值")
    i_trial = header.index("试算值(改这里)")
    trials: dict[str, tuple[float, float]] = {}
    for r in rows[1:]:
        if not r or r[i_path] is None:
            continue
        try:
            cur = float(r[i_cur])
            trial = float(r[i_trial])
        except (TypeError, ValueError):
            continue
        if trial != cur:
            trials[str(r[i_path])] = (cur, trial)
    return trials


def _fmt_toml_value(v: float) -> str:
    fv = float(v)
    return str(int(fv)) if fv.is_integer() else repr(fv)


def _section_matches(current: str | None, target: str) -> bool:
    return current is not None and current.strip() == target.strip()


def _apply_toml(toml_path: Path, trials: dict[str, tuple[float, float]]) -> list[str]:
    """把试算值安全写回 base.toml：只在对应 [section] 下替换 leaf 的值，保留注释与缩进。"""
    lines = toml_path.read_text(encoding="utf-8").splitlines()
    targets = {p: (p.rsplit(".", 1)[0], p.rsplit(".", 1)[1]) for p in trials}
    remaining = set(targets)
    current_section = None
    out: list[str] = []
    changed: list[str] = []
    for line in lines:
        m_sec = re.match(r"^\s*\[([^\]]+)\]\s*", line)
        if m_sec:
            current_section = m_sec.group(1)
            out.append(line)
            continue
        hit = None
        for path in list(remaining):
            section, leaf = targets[path]
            if _section_matches(current_section, section):
                m = re.match(rf"^(\s*{re.escape(leaf)}\s*=\s*)([^\s#]+)(\s*(#.*)?)$", line)
                if m:
                    hit = path
                    break
        if hit:
            _cur, trial = trials[hit]
            m = re.match(rf"^(\s*{re.escape(targets[hit][1])}\s*=\s*)([^\s#]+)(\s*(#.*)?)$", line)
            prefix, _old, comment = m.group(1), m.group(2), m.group(3) or ""
            out.append(f"{prefix}{_fmt_toml_value(trial)}{comment}")
            changed.append(hit)
            remaining.discard(hit)
        else:
            out.append(line)
    if remaining:
        print(f"  ⚠ 以下参数在 base.toml 未找到对应行，已跳过：{sorted(remaining)}")
    toml_path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def cmd_trial(config: dict, base_values: dict[str, float]) -> None:
    ALERT_FILL = PatternFill("solid", fgColor="FFF2CC")
    xlsx_path = _locate_workbook()
    trials = _read_trials(xlsx_path)
    if not trials:
        print("01_假设参数 的「试算值」与当前值完全一致，没有要试算的改动。")
        print("先在 Excel 里把想试的参数那格改成新值，再跑本命令。")
        return

    # 逐个测可行性：触发硬约束的参数不参与合并试算，避免整组崩掉
    feasible: dict[str, tuple[float, float]] = {}
    blocked: list[str] = []
    for path, (cur, trial) in trials.items():
        c = copy.deepcopy(config)
        set_path(c, path, trial)
        try:
            rerun(c)
            feasible[path] = (cur, trial)
        except Exception:  # noqa: BLE001
            blocked.append(path)

    if blocked:
        print(f"⚠ 以下 {len(blocked)} 个试算值触发模型硬约束，已排除在合并试算之外：")
        for p in blocked:
            print(f"   · {p}（试算值 {trials[p][1]:g}）")

    trial_config = copy.deepcopy(config)
    for path, (cur, trial) in feasible.items():
        set_path(trial_config, path, trial)
    trial_values = read_metrics(rerun(trial_config), trial_config, strict=False)

    wb = load_workbook(xlsx_path)
    if "07_试算对比" in wb.sheetnames:
        del wb["07_试算对比"]
    ws = wb.create_sheet("07_试算对比")
    ws.append(["试算对比：基准值 vs 你在 Excel 里填的试算值"])
    ws.cell(row=1, column=1).font = Font(bold=True, size=12)
    ws.append([])
    ws.append(["改动参数", "当前值", "试算值"])
    style_header(ws, 3, 3)
    for path, (cur, trial) in feasible.items():
        ws.append([path, cur, trial])
    ws.append([])
    headers = ["分组", "指标", "基准值", "试算值", "变化额", "变化率", "单位"]
    ws.append(headers)
    style_header(ws, ws.max_row, len(headers))
    for metric in METRICS:
        b = base_values[metric.key]
        t = trial_values[metric.key]
        if b != b or t != t:
            continue
        delta = t - b
        pct = (delta / b) if b else 0.0
        ws.append([metric.group, metric.label,
                   round(b, metric.decimals), round(t, metric.decimals),
                   round(delta, metric.decimals), pct, metric.unit])
        if abs(pct) >= 0.05:
            for col in range(1, 8):
                ws.cell(row=ws.max_row, column=col).fill = ALERT_FILL
    ws.append([])
    ws.append(["提示：变化率≥±5% 的行已标黄。确认满意后跑 python src/lab.py commit 把试算值落盘。"])
    set_widths(ws, [22, 30, 14, 14, 14, 10, 10])

    try:
        wb.save(xlsx_path)
    except PermissionError:
        wb.save(str(xlsx_path).replace(".xlsx", "_新.xlsx"))
    print(f"\n已写入 07_试算对比 页签（{len(feasible)} 个参数生效，{len(blocked)} 个被硬约束挡下）。")
    print("打开 Excel 看 07_试算对比，确认后再跑 commit。")


def cmd_commit(config: dict, base_values: dict[str, float]) -> None:
    xlsx_path = _locate_workbook()
    trials = _read_trials(xlsx_path)
    if not trials:
        print("没有可提交的改动（试算值都与当前值一致）。")
        return
    toml_path = ROOT.parent / "configs" / "base.toml"
    changed = _apply_toml(toml_path, trials)
    print(f"已落盘 {len(changed)} 个参数到 base.toml：")
    for p in changed:
        print(f"   · {p}：{trials[p][0]:g} → {trials[p][1]:g}")
    print("\n下一步：python src/run.py 刷新快照与报告，再 python src/backscan.py MANIFEST.md 验收。")


def commit_edits(edited_config: dict) -> list[str]:
    """把与默认配置不同的数值参数安全写回 base.toml（保留注释与缩进）。

    供实时沙盘（app.py）在用户点「落盘」时调用；逻辑复用 _apply_toml，单一真相源。
    """
    base = load_config()
    trials: dict[str, tuple[float, float]] = {}
    for path, old in iter_numeric_params(base):
        try:
            new = get_path(edited_config, path)
        except Exception:
            continue
        if float(new) != float(old):
            trials[path] = (float(old), float(new))
    if not trials:
        return []
    toml_path = ROOT.parent / "configs" / "base.toml"
    return _apply_toml(toml_path, trials)


def cmd_scan(config: dict, base_values: dict[str, float], step: float = 0.10,
             top_per_metric: int = 8) -> None:
    params = iter_numeric_params(config, include_arrays=True)
    print(f"\n全参数扫描：{len(params)} 个参数（含 scenes 场景级 + 曲线型）× {len(METRICS)} 个指标，每个参数单独 {step:+.0%}")
    print("（这是数值法实测的血缘矩阵，不是人工登记的注释）\n")

    t0 = time.time()
    elasticity = compute_elasticity(config, base_values, step)
    print(f"\n扫描完成，用时 {time.time() - t0:.0f}s\n")

    # ── 表 0：情景轴合力（每条轴的全部 targets 一起 +step）──
    anchor_label = METRIC_BY_KEY[INFLUENCE_ANCHOR].label if INFLUENCE_ANCHOR in METRIC_BY_KEY else INFLUENCE_ANCHOR
    print("【表 0】各情景轴的杠杆（整条轴同时 +10% —— 不是单参数）")
    print(_ljust("情景轴", 54) + _rjust("轴级弹性", 12) + "   锚定指标")
    print("─" * 110)
    for name, lev in sorted(
        compute_axis_leverage(config, base_values, step).items(),
        key=lambda kv: abs(kv[1]) if kv[1] == kv[1] else -1,
        reverse=True,
    ):
        shown = "不可算" if lev != lev else f"{lev:.2f}"
        print(_ljust(name, 54) + _rjust(shown, 12) + f"   {anchor_label}")
    print("")

    # ── 表 1：参数影响力排序（锚定最终投资指标：换电增量价值）──
    print(f"【表 1】谁最能撬动 CATL 的换电增量价值（按对 {anchor_label} 的弹性排序）")
    print(_ljust("参数", 54) + _rjust("总影响力", 12) + "   锚定指标")
    print("─" * 110)
    ranked = sorted(
        elasticity.items(),
        key=lambda kv: total_influence(kv[1]),
        reverse=True,
    )
    for path, row in ranked[:25]:
        total = total_influence(row)
        if total < 0.005:
            continue
        print(
            _ljust(path, 54)
            + _rjust(f"{total:.2f}", 12)
            + f"   {anchor_label}"
        )

    # ── 表 2：每个关键指标的 Top 上游（龙卷风数据）──
    print("\n【表 2】每个结果由谁决定（各指标影响最大的上游参数）")
    for metric in METRICS:
        col = [(p, row.get(metric.key, 0.0)) for p, row in elasticity.items()]
        col = [c for c in col if abs(c[1]) >= 0.005]
        if not col:
            continue
        col.sort(key=lambda c: abs(c[1]), reverse=True)
        print(f"\n  ▸ {metric.label}  = {_fmt(base_values[metric.key], metric.decimals)} {metric.unit}")
        for path, value in col[:top_per_metric]:
            print("      " + _ljust(path, 52) + _rjust(f"{value:+.2f}", 8) + "  " + "█" * min(24, int(abs(value) * 12)))

    # ── 落盘：完整矩阵仅在可读的 xlsx（03_敏感性矩阵）产出，不再写裸 CSV ──


# ══════════════════════════════════════════════════════════════════════


USAGE = """用法：
  python src/lab.py list                          列出全部可调参数（值 + 理由）
  python src/lab.py impact <参数路径> <新值|±%>    改一个参数，看所有结果怎么动
  python src/lab.py lineage <指标键>               追溯：哪些参数在影响这个结果
  python src/lab.py scan                          全参数扫描 → 敏感性矩阵（终端）
  python src/lab.py workbook                      生成 Excel 工作簿（假设表/结果表/敏感性/双向血缘）
  python src/lab.py trial                         读回 01 表「试算值」→ 重跑 → 写 07_试算对比
  python src/lab.py commit                        把 01 表「试算值」安全落盘到 base.toml（保留注释）

闭环用法（不碰代码也能改模型）：
  1. python src/lab.py workbook       生成 Excel，01_假设参数 里多出一列「试算值(改这里)」
  2. 在 Excel 里把想试的参数那格改成新值（其余别动）
  3. python src/lab.py trial          看 07_试算对比：基准值 vs 试算值，变化≥±5% 自动标黄
  4. 满意了 → python src/lab.py commit   改动写回 base.toml
  5. python src/run.py                 刷新快照与报告

例子：
  python src/lab.py impact swap_business.service_fee_rmb_kwh 0.35
  python src/lab.py impact finance.wacc +20%
  python src/lab.py lineage val.swap_increment
  python src/lab.py workbook
  python src/lab.py trial
  python src/lab.py commit
"""


def cmd_target(config: dict, base_values: dict[str, float], metric_key: str,
               target_pct: float, step: float = 0.10, top: int = 15) -> None:
    """反解：要让某指标涨跌 target_pct%，每个参数 / 每条轴各自需要动多少。

    典型用法——回答"这个估值倍数里到底含了多少增长想象"：
        python src/lab.py target swap.ebitda +38.5%
    （+38.5% 来自 18÷13−1：把 18× 拆成"13× 的成熟倍数 × 大 38.5% 的盈利基数"）
    """
    metric = METRIC_BY_KEY.get(metric_key)
    if metric is None:
        print(f"✗ 未知指标 {metric_key}。可用指标：")
        for m in METRICS:
            print(f"    {m.key:<28}{m.label}")
        return

    base = base_values[metric.key]
    goal = base * (1 + target_pct / 100.0)
    print(f"\n反解：{metric.label}  {_fmt(base, metric.decimals)} → "
          f"{_fmt(goal, metric.decimals)} {metric.unit}（{target_pct:+.1f}%）")
    print("倒推公式：参数需变动% = 目标变动% ÷ 该参数的实测弹性\n")

    values = dict(iter_numeric_params(config, include_arrays=True))

    def _pair(cur, need_pct):
        if isinstance(cur, list):
            return ("[" + ", ".join(f"{x:g}" for x in cur) + "]",
                    "[" + ", ".join(f"{x * (1 + need_pct / 100):g}" for x in cur) + "]")
        return f"{cur:g}", f"{cur * (1 + need_pct / 100):g}"

    rows = []
    for path, row in compute_elasticity(config, base_values, step).items():
        e = row.get(metric.key)
        if not e or abs(e) < 0.01:
            continue
        rows.append((abs(target_pct / e), path, target_pct / e, e))
    rows.sort()
    print("【单参数】各自单独调，需要动多少（按最省力排序，只列 ≤100% 的）")
    print(_ljust("参数", 50) + _rjust("需变动", 10) + _rjust("弹性", 8) + "   当前值 → 需要取值")
    print("─" * 116)
    n = 0
    for _, path, need, e in rows:
        if abs(need) > 100 or n >= top:
            continue
        c, v = _pair(values.get(path), need)
        print(_ljust(path, 50) + _rjust(f"{need:+.1f}%", 10) + _rjust(f"{e:+.2f}", 8)
              + f"   {c} → {v}")
        n += 1

    arows = []
    for name, row in compute_axis_matrix(config, base_values, step).items():
        e = row.get(metric.key)
        if not e or abs(e) < 0.01:
            continue
        arows.append((abs(target_pct / e), name, target_pct / e, e))
    arows.sort()
    print("\n【情景轴】整条轴一起摆，需要摆多少")
    print(_ljust("情景轴", 50) + _rjust("需摆动", 10) + _rjust("轴弹性", 8))
    print("─" * 116)
    for _, name, need, e in arows[:top]:
        print(_ljust(name, 50) + _rjust(f"{need:+.1f}%", 10) + _rjust(f"{e:+.2f}", 8))


def _pop_step(argv: list[str], config: dict) -> float:
    """微扰幅度：命令行 `--step 0.2` 优先，否则取 base.toml [sensitivity].step。"""
    if "--step" in argv:
        i = argv.index("--step")
        try:
            return float(argv[i + 1])
        except (IndexError, ValueError):
            print("⚠ `--step` 后面要跟一个数字（如 0.2），已改用 base.toml 的设置")
    return sensitivity_step(config)


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] in ("-h", "--help"):
        print(USAGE)
        return 0

    command = argv[1]
    config = load_config()
    step = _pop_step(argv, config)   # --step 优先，其次 base.toml [sensitivity].step

    if command == "list":
        cmd_list(config)
        return 0

    if command == "metrics":
        # 查输出字典：python src/lab.py metrics [要查的名字]
        cmd_metrics(argv[2] if len(argv) > 2 else "")
        return 0

    print("正在跑基准情景…", flush=True)
    t0 = time.time()
    base_values = read_metrics(rerun(config), config)
    print(f"基准完成（{time.time() - t0:.1f}s）")

    if command == "impact":
        if len(argv) < 4:
            print(USAGE)
            return 1
        cmd_impact(config, base_values, argv[2], argv[3])
    elif command == "lineage":
        if len(argv) < 3:
            print(USAGE)
            return 1
        cmd_lineage(config, base_values, argv[2])
    elif command == "target":
        if len(argv) < 4:
            print(USAGE)
            return 1
        try:
            pct = float(str(argv[3]).rstrip("%"))
        except ValueError:
            print("⚠ 目标要写成 `+38.5%` 或 `-20` 这样的形式")
            return 1
        cmd_target(config, base_values, argv[2], pct, step)
    elif command == "scan":
        cmd_scan(config, base_values, step)
    elif command == "workbook":
        cmd_workbook(config, base_values, step)
    elif command == "trial":
        cmd_trial(config, base_values)
    elif command == "commit":
        cmd_commit(config, base_values)
    else:
        print(USAGE)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

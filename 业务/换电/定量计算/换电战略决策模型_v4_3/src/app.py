"""换电战略决策模型 v4.3 · 实时沙盘（Streamlit）

与骨架报告 / Excel 工作簿同源：改参即重跑同一条 Python 计算链（model._build_core），
不重复实现逻辑——所以这里看到的数字和报告、Excel 永远一致。

运行：
    cd 换电战略决策模型_v4_3
    streamlit run src/app.py
然后在浏览器打开终端里给出的本地地址（默认 http://localhost:8501）。
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

import lab
from lab import (
    load_config,
    rerun,
    read_metrics,
    iter_numeric_params,
    set_path,
    get_path,
    METRICS,
    METRIC_BY_KEY,
    total_influence,
    VALUATION_TERMINAL_METRICS,
    compute_elasticity,
    load_param_docs,
)

st.set_page_config(
    page_title="换电战略决策模型 v4.3 · 实时沙盘",
    layout="wide",
)

# ── 配置与基准（缓存，不随每次交互重算）────────────────
@st.cache_data
def get_base() -> dict:
    return load_config()


@st.cache_data
def get_base_metrics(cfg: dict) -> dict:
    # cfg 必须传给 read_metrics：否则输入名片那批（base [[input_fact]] 升格的 cfg 侧取值器）
    # 取不到，静默变 NaN
    return read_metrics(rerun(cfg), cfg)


@st.cache_data
def get_influence(cfg: dict) -> dict:
    """基准情景下各参数的总影响力（终端口径），用于排名与高亮。"""
    base_metrics = read_metrics(rerun(cfg), cfg)
    elast = compute_elasticity(cfg, base_metrics)
    return {p: total_influence(row) for p, row in elast.items()}


BASE = get_base()
BASE_METRICS = get_base_metrics(BASE)
INFLUENCE = get_influence(BASE)

if "cfg" not in st.session_state:
    st.session_state.cfg = copy.deepcopy(BASE)
CFG = st.session_state.cfg

# ── 侧栏：参数编辑 ─────────────────────────────────
GROUPED: dict[str, list[tuple[str, float]]] = {}
for path, val in iter_numeric_params(CFG):
    section = load_param_docs().get(path, {}).get("section", path.rsplit(".", 1)[0])
    GROUPED.setdefault(section, []).append((path, val))

TOP = sorted(INFLUENCE, key=lambda p: INFLUENCE[p], reverse=True)
TOP_SET = set(TOP[:40])

with st.sidebar:
    st.header("参数编辑")
    st.caption("改任意数值 → 主区实时重算。带 ★★★ 的是高影响力参数。")
    show_all = st.checkbox("显示全部参数（212 个，较慢）", value=False)
    for section in sorted(GROUPED):
        paths = GROUPED[section]
        visible = paths if show_all else [(p, v) for p, v in paths if p in TOP_SET]
        if not visible:
            continue
        st.subheader(section, divider="blue")
        for path, _val in visible:
            cur = float(get_path(CFG, path))
            stars = "★★★" if INFLUENCE.get(path, 0) >= 5 else "★★" if INFLUENCE.get(path, 0) >= 2 else "★" if INFLUENCE.get(path, 0) >= 0.5 else ""
            label = f"{path}  {stars}".strip()
            new = st.number_input(label, value=cur, format="%.4g", key=f"inp_{path}")
            if new != cur:
                set_path(CFG, path, float(new))

# ── 主区：实时结果 ─────────────────────────────────
try:
    M = read_metrics(rerun(CFG), CFG)
except Exception as exc:  # noqa: BLE001
    st.error(f"当前参数组合触发模型硬约束，结果未刷新：{exc}")
    M = BASE_METRICS

st.title("宁德时代换电 · 实时沙盘（v4.3）")
st.caption(
    "与骨架报告 / Excel 工作簿同源：改参即重跑同一条 Python 计算链，不重复实现逻辑。"
    "左侧改参数，下方结果实时刷新。带 ★★★ 的参数（电池价格、站效率 RTE、债务比、价格平台期）动一下要慎。"
)

st.header("关键结果（估值相关终端指标）")
kpi_cols = st.columns(3)
for i, key in enumerate(VALUATION_TERMINAL_METRICS):
    metric = METRIC_BY_KEY[key]
    before = BASE_METRICS[key]
    after = M[key]
    pct = ((after - before) / before * 100) if before else 0.0
    with kpi_cols[i % 3]:
        st.metric(
            metric.label,
            f"{after:,.{metric.decimals}f} {metric.unit}",
            delta=f"{pct:+.1f}%",
            delta_color="normal",
        )

st.header("全部输出指标（基准 vs 当前）")
rows = []
for metric in METRICS:
    before = BASE_METRICS[metric.key]
    after = M[metric.key]
    pct = ((after - before) / before * 100) if before else 0.0
    rows.append(
        {
            "指标": metric.label,
            "当前值": round(after, metric.decimals),
            "单位": metric.unit,
            "基准值": round(before, metric.decimals),
            "变化%": round(pct, 2),
        }
    )
st.dataframe(rows, use_container_width=True, height=600)

st.header("参数影响力排名（基准情景 · 终端口径）")
rank_rows = []
for path in TOP[:25]:
    changed = float(get_path(CFG, path)) != float(get_path(BASE, path))
    rank_rows.append(
        {
            "参数": path,
            "总影响力": round(INFLUENCE[path], 2),
            "你改了吗": "✏️ 已改" if changed else "",
        }
    )
st.dataframe(rank_rows, use_container_width=True)

# ── 操作 ─────────────────────────────────────────
col1, col2 = st.columns(2)
with col1:
    if st.button("重置所有改动", type="secondary"):
        st.session_state.cfg = copy.deepcopy(BASE)
        st.rerun()
with col2:
    if st.button("写入 base.toml（落盘）", type="primary"):
        changed = lab.commit_edits(CFG)
        if changed:
            st.success(f"已落盘 {len(changed)} 个参数：\n" + "\n".join(changed))
        else:
            st.info("没有改动可落盘。")

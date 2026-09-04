"""生成 v4.1 → v4.2 报告的红绿对照删改痕迹版。

以正式 v4.1 报告为基准：v4.1 中被删除或被替换的内容标红色删除线，
v4.2 新增或修改后的内容标绿色底色。表格行做单元格级对照（旧值+新值并排），
其余行做行级对照。输出为同名 _红绿对照版.md，正式版报告不受影响。
"""
from __future__ import annotations

import difflib
import html
from pathlib import Path

ROOT = Path(__file__).parent
CONCLUSION = ROOT.parent.parent / "分析结论"
OLD_PATH = (
    CONCLUSION / "换电毛估估_宁德时代应不应该下重注，以及什么时候能见分晓_v4.1.md"
)
NEW_PATH = (
    CONCLUSION / "换电毛估估_宁德时代应不应该下重注，以及什么时候能见分晓_v4.2.md"
)
OUT_PATH = (
    CONCLUSION
    / "换电毛估估_宁德时代应不应该下重注，以及什么时候能见分晓_v4.2_红绿对照版.md"
)

DEL_STYLE = "color:#c00;background:#fdeaea;text-decoration:line-through"
INS_STYLE = "color:#070;background:#eaffea"


def _is_table_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("|") and stripped.endswith("|")


def _del(text: str) -> str:
    return f'<span style="{DEL_STYLE}">{html.escape(text)}</span>'


def _ins(text: str) -> str:
    return f'<span style="{INS_STYLE}">{html.escape(text)}</span>'


def _mark_whole_line(line: str, deleted: bool) -> str:
    """整行着色：非表格行整体包裹，表格行逐格包裹以保持表格结构。"""
    if _is_table_line(line):
        cells = line.split("|")

        def _mark(cell: str) -> str:
            if cell.strip() == "":
                return cell
            return _del(cell) if deleted else _ins(cell)

        return "|".join(_mark(cell) for cell in cells)
    return _del(line) if deleted else _ins(line)


def _cell_level_pair(old_line: str, new_line: str) -> str | None:
    """两行同为表格行且列数一致时，逐格对照；无差异返回 None。"""
    if not (_is_table_line(old_line) and _is_table_line(new_line)):
        return None
    old_cells = old_line.split("|")
    new_cells = new_line.split("|")
    if len(old_cells) != len(new_cells):
        return None
    parts: list[str] = []
    changed = False
    for old_cell, new_cell in zip(old_cells, new_cells):
        if old_cell == new_cell:
            parts.append(old_cell)
        else:
            changed = True
            parts.append(f"{_del(old_cell)}{_ins(new_cell)}")
    if not changed:
        return new_line
    return "|".join(parts)


def _render_replace(
    old_block: list[str], new_block: list[str]
) -> list[str]:
    """replace 块：优先行对行配对做单元格级对照，剩余行整行红/绿。"""
    out: list[str] = []
    pairs = min(len(old_block), len(new_block))
    for i in range(pairs):
        old_line = old_block[i]
        new_line = new_block[i]
        paired = _cell_level_pair(old_line, new_line)
        if paired is not None:
            out.append(paired)
        else:
            out.append(_mark_whole_line(old_line, deleted=True))
            out.append(_mark_whole_line(new_line, deleted=False))
    for line in old_block[pairs:]:
        out.append(_mark_whole_line(line, deleted=True))
    for line in new_block[pairs:]:
        out.append(_mark_whole_line(line, deleted=False))
    return out


def build_diff() -> str:
    old_lines = OLD_PATH.read_text(encoding="utf-8").splitlines()
    new_lines = NEW_PATH.read_text(encoding="utf-8").splitlines()
    matcher = difflib.SequenceMatcher(
        None, old_lines, new_lines, autojunk=False
    )
    out: list[str] = [
        "# 换电毛估估 v4.2 红绿对照删改痕迹版",
        "",
        (
            "> 本文件由 `make_diff_report.py` 自动生成："
            f'<span style="{DEL_STYLE}">红色删除线 = v4.1 中被删除或修改前的内容</span>，'
            f'<span style="{INS_STYLE}">绿色底色 = v4.2 新增或修改后的内容</span>。'
            "表格中仅变化的单元格显示“旧值+新值”并排对照。"
            "干净的正式版见"
            "`换电毛估估_宁德时代应不应该下重注，以及什么时候能见分晓_v4.2.md`。"
        ),
        "",
        "---",
        "",
    ]
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            out.extend(old_lines[i1:i2])
        elif tag == "delete":
            for line in old_lines[i1:i2]:
                out.append(_mark_whole_line(line, deleted=True))
        elif tag == "insert":
            for line in new_lines[j1:j2]:
                out.append(_mark_whole_line(line, deleted=False))
        elif tag == "replace":
            out.extend(_render_replace(old_lines[i1:i2], new_lines[j1:j2]))
    return "\n".join(out) + "\n"


def main() -> None:
    text = build_diff()
    OUT_PATH.write_text(text, encoding="utf-8")
    print(f"红绿对照版: {OUT_PATH}")
    print(f"行数: {text.count(chr(10))}")


if __name__ == "__main__":
    main()

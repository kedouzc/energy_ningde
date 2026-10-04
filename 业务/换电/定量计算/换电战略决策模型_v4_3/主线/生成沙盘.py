#!/usr/bin/env python3
"""生成换电沙盘页面。

用法（在仓库根目录或任何地方运行都可以）：
    python 主线/生成沙盘.py [数据json路径] [文字md路径] [输出html路径]

三个参数都可省略，默认分别是：
    主线/结论数.json   主线/沙盘文字.md   outputs/换电沙盘_v5.html
相对路径一律按仓库根目录（本脚本所在目录的上一级）解析。

脚本做的事：
    1. 读数据 JSON，检查结构（缺字段、某档缺值、表格列数对不上会提示）；
    2. 把文字 md 按 "## 版面名" 切成五段，每段转成简单 HTML（段落、**粗体**、- 列表）；
    3. 把两者嵌进 templates/沙盘_v5.html 的两个占位符，写出 HTML。
旧页面 outputs/换电沙盘_v4.3.html 永远不会被写入。
只用 Python 标准库。
"""

import html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "templates" / "沙盘_v5.html"
DEFAULT_DATA = "主线/结论数.json"
DEFAULT_TEXT = "主线/沙盘文字.md"
DEFAULT_OUT = "outputs/换电沙盘_v5.html"

# 绝不能写入的旧页面
PROTECTED = {(ROOT / "outputs" / "换电沙盘_v4.3.html").resolve()}
PROTECTED_NAME = re.compile(r"^换电沙盘_v4(\.\d+)*\.html$")

SECTIONS = ["结论", "什么会推翻", "为什么这么想", "怎么算出来的", "跟踪"]
DATA_MARK = "/*__DATA__*/null"
TEXT_MARK = "/*__TEXT__*/null"

CJK = re.compile(r"[\u2e80-\u303f\u3400-\u9fff\uf900-\ufaff\uff00-\uffef]")


class 生成失败(Exception):
    pass


# ---------- 路径 ----------

def resolve(arg, default):
    p = Path(arg if arg else default)
    if not p.is_absolute():
        p = ROOT / p
    return p.resolve()


def rel(p):
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


# ---------- 数据检查 ----------

def check_data(d):
    """返回 (错误列表, 提醒列表)。有错误就不生成。"""
    errors, warns = [], []
    if not isinstance(d, dict):
        return ["数据 JSON 最外层必须是一个对象 {...}"], warns

    tiers = d.get("三档")
    if not (isinstance(tiers, list) and tiers and all(isinstance(t, str) for t in tiers)):
        errors.append('缺少 "三档"，或它不是文字列表（应为 ["悲观","中性","乐观"]）')
        tiers = ["悲观", "中性", "乐观"]
    elif len(tiers) != 3:
        warns.append(f'"三档" 有 {len(tiers)} 个，页面按实际个数显示切换按钮')
    if d.get("默认档") not in tiers:
        warns.append(f'"默认档" = {d.get("默认档")!r} 不在三档里，页面改用中间一档')
    if not isinstance(d.get("版本"), str) or not d.get("版本"):
        warns.append('缺少 "版本"，页面顶部不显示版本')

    def is_tier_obj(v):
        return isinstance(v, dict) and any(t in v for t in tiers)

    def check_tiers(v, where):
        if is_tier_obj(v):
            missing = [t for t in tiers if t not in v]
            if missing:
                warns.append(f"{where} 缺 {'、'.join(missing)} 档，这几档显示为 —")

    def need_list(key):
        v = d.get(key)
        if v is None:
            warns.append(f'缺少 "{key}"，该版面显示（暂无）')
            return []
        if not isinstance(v, list):
            errors.append(f'"{key}" 应该是列表 [...]')
            return []
        return v

    concl = d.get("结论")
    if not isinstance(concl, dict):
        warns.append('缺少 "结论"，结论版面显示（暂无）')
        concl = {}
    check_tiers(concl.get("一句话"), "结论.一句话")
    metrics = concl.get("指标", [])
    if not isinstance(metrics, list):
        errors.append('"结论.指标" 应该是列表 [...]')
        metrics = []
    for i, m in enumerate(metrics, 1):
        name = m.get("名", f"第 {i} 个") if isinstance(m, dict) else f"第 {i} 个"
        if not isinstance(m, dict):
            errors.append(f"结论.指标 第 {i} 项不是对象")
            continue
        if "名" not in m:
            warns.append(f"结论.指标 第 {i} 项没有 \"名\"")
        if "值" not in m:
            warns.append(f"指标「{name}」没有 \"值\"")
        check_tiers(m.get("值"), f"指标「{name}」的值")

    for i, r in enumerate(need_list("推翻"), 1):
        if not isinstance(r, dict):
            errors.append(f"推翻 第 {i} 项不是对象")
            continue
        for k in ("参数", "现值", "阈值与后果", "会不会发生", "跟踪信源"):
            if k not in r:
                warns.append(f"推翻 第 {i} 项缺 \"{k}\"")
            check_tiers(r.get(k), f"推翻 第 {i} 项的 {k}")

    for i, r in enumerate(need_list("论证链"), 1):
        if not isinstance(r, dict):
            errors.append(f"论证链 第 {i} 项不是对象")
            continue
        if "环" not in r:
            warns.append(f"论证链 第 {i} 项缺 \"环\"")
        for k in ("一句话", "关键数"):
            check_tiers(r.get(k), f"论证链 第 {i} 环的 {k}")

    for i, ch in enumerate(need_list("计算链"), 1):
        if not isinstance(ch, dict):
            errors.append(f"计算链 第 {i} 项不是对象")
            continue
        title = ch.get("章", f"第 {i} 项")
        cols = ch.get("列")
        if not isinstance(cols, list) or not cols:
            warns.append(f"计算链「{title}」缺 \"列\"（表头）")
            cols = []
        rows = ch.get("行")
        groups = {}
        if is_tier_obj(rows):
            check_tiers(rows, f"计算链「{title}」的行")
            groups = {t: rows[t] for t in tiers if t in rows}
        elif isinstance(rows, list):
            groups = {"（各档共用）": rows}
        else:
            warns.append(f"计算链「{title}」缺 \"行\"")
        for t, rs in groups.items():
            if not isinstance(rs, list):
                errors.append(f"计算链「{title}」{t} 的行应该是列表")
                continue
            for j, r in enumerate(rs, 1):
                if not isinstance(r, list):
                    errors.append(f"计算链「{title}」{t} 第 {j} 行应该是列表 [...]")
                elif cols and len(r) != len(cols):
                    warns.append(f"计算链「{title}」{t} 第 {j} 行有 {len(r)} 格，表头有 {len(cols)} 列")

    for i, r in enumerate(need_list("跟踪"), 1):
        if not isinstance(r, dict):
            errors.append(f"跟踪 第 {i} 项不是对象")
            continue
        for k in ("看什么", "信源", "什么说明我错了"):
            if k not in r or r.get(k) in (None, ""):
                warns.append(f"跟踪 第 {i} 项缺 \"{k}\"")

    return errors, warns


# ---------- 文字 md → HTML ----------

def inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
    return s


def join_lines(lines):
    """中文行之间直接相连，西文行之间补一个空格。"""
    out = ""
    for ln in lines:
        if out and not (CJK.match(out[-1]) or CJK.match(ln[0])):
            out += " "
        out += ln
    return out


def md_to_html(md, where, warns):
    out, para, items, kind = [], [], [], None

    def flush_para():
        if para:
            out.append(f"<p>{inline(join_lines(para))}</p>")
            para.clear()

    def flush_list():
        nonlocal kind
        if items:
            lis = "".join(f"<li>{inline(join_lines(it))}</li>" for it in items)
            out.append(f"<{kind}>{lis}</{kind}>")
            items.clear()
        kind = None

    for raw in md.splitlines():
        s = raw.strip()
        if not s:
            flush_para()
            flush_list()
            continue
        h = re.match(r"^#{3,6}\s+(.*)$", s)
        ul = re.match(r"^[-*+]\s+(.*)$", s)
        ol = re.match(r"^\d+\.\s+(.*)$", s)
        if h:
            flush_para()
            flush_list()
            out.append(f"<h4>{inline(h.group(1))}</h4>")
        elif ul or ol:
            flush_para()
            want = "ul" if ul else "ol"
            if kind and kind != want:
                flush_list()
            kind = want
            items.append([(ul or ol).group(1)])
        elif items and raw[:1] in (" ", "\t"):
            items[-1].append(s)  # 列表项的续行
        else:
            if s.startswith("|"):
                warns.append(f"「{where}」里有表格行，暂不支持表格，按普通文字显示")
            flush_list()
            para.append(s)
    flush_para()
    flush_list()
    return "".join(out)


def split_sections(md, warns):
    sections, cur, buf, ignored = {}, None, [], False

    def close():
        if cur is None:
            return
        body = md_to_html("\n".join(buf), cur, warns)
        sections[cur] = sections.get(cur, "") + body

    for line in md.splitlines():
        m = re.match(r"^##\s+(.+?)\s*#*\s*$", line)
        if m and not line.startswith("###"):
            close()
            cur, buf = m.group(1).strip(), []
            if cur in sections:
                warns.append(f"文字里「## {cur}」出现了不止一次，内容接在一起显示")
            if cur not in SECTIONS:
                warns.append(f"文字里的「## {cur}」不是版面名（应为：{'、'.join(SECTIONS)}），页面不会显示它")
            continue
        if cur is None:
            if line.strip() and not line.lstrip().startswith("# "):
                ignored = True
            continue
        buf.append(line)
    close()
    if ignored:
        warns.append("文字里第一个「## 版面名」之前的内容被忽略")
    for s in SECTIONS:
        if not sections.get(s):
            warns.append(f"文字里没有「## {s}」段（或该段为空），该版面顶部不显示说明")
    return {k: v for k, v in sections.items() if k in SECTIONS}


# ---------- 嵌入 ----------

def js_literal(obj):
    """转成可以直接放进 <script> 的 JSON：< > & 都转义，不会提前结束 script。"""
    s = json.dumps(obj, ensure_ascii=False, indent=1)
    return (s.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
             .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def build(data_path, text_path, out_path):
    warns = []
    for p, label in ((data_path, "数据 JSON"), (text_path, "文字 md"), (TEMPLATE, "模板")):
        if not p.is_file():
            raise 生成失败(f"找不到{label}：{rel(p)}")

    if out_path in PROTECTED or PROTECTED_NAME.match(out_path.name):
        raise 生成失败(f"拒绝写入 {rel(out_path)}：这是旧版页面，不能覆盖")
    if out_path in {data_path, text_path, TEMPLATE.resolve()}:
        raise 生成失败("输出路径不能和输入文件或模板相同")
    if out_path.suffix.lower() != ".html":
        raise 生成失败(f"输出文件应以 .html 结尾：{rel(out_path)}")

    try:
        data = json.loads(data_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise 生成失败(f"数据 JSON 格式错误（第 {e.lineno} 行第 {e.colno} 列）：{e.msg}")
    errors, w = check_data(data)
    warns += w
    if errors:
        raise 生成失败("数据结构有错，未生成：\n  - " + "\n  - ".join(errors))

    md = text_path.read_text(encoding="utf-8")
    text = {
        "段落": split_sections(md, warns),
        "来源": {"数据": rel(data_path), "文字": rel(text_path)},
    }

    tpl = TEMPLATE.read_text(encoding="utf-8")
    for mark in (DATA_MARK, TEXT_MARK):
        n = tpl.count(mark)
        if n != 1:
            raise 生成失败(f"模板里占位符 {mark} 应出现 1 次，实际 {n} 次")

    repl = {DATA_MARK: js_literal(data), TEXT_MARK: js_literal(text)}
    pattern = re.compile("|".join(re.escape(k) for k in repl))
    page = pattern.sub(lambda m: repl[m.group(0)], tpl)  # 一次替换，不会二次扫描嵌入的内容

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text(page, encoding="utf-8")
    tmp.replace(out_path)
    return data, text, warns


def main(argv):
    if any(a in ("-h", "--help") for a in argv):
        print(__doc__)
        return 0
    if len(argv) > 3:
        print("参数太多。用法：python 主线/生成沙盘.py [数据json] [文字md] [输出html]", file=sys.stderr)
        return 2
    args = list(argv) + [None] * (3 - len(argv))
    data_path = resolve(args[0], DEFAULT_DATA)
    text_path = resolve(args[1], DEFAULT_TEXT)
    out_path = resolve(args[2], DEFAULT_OUT)
    try:
        data, text, warns = build(data_path, text_path, out_path)
    except 生成失败 as e:
        print(f"生成失败：{e}", file=sys.stderr)
        return 1

    concl = data.get("结论") or {}
    print(f"已生成：{rel(out_path)}")
    print(f"  数据：{rel(data_path)}（版本：{data.get('版本', '未写')}）")
    print(f"  文字：{rel(text_path)}（读到 {len(text['段落'])}/{len(SECTIONS)} 段）")
    print(f"  指标 {len(concl.get('指标') or [])} 个，推翻 {len(data.get('推翻') or [])} 条，"
          f"论证链 {len(data.get('论证链') or [])} 环，计算链 {len(data.get('计算链') or [])} 章，"
          f"跟踪 {len(data.get('跟踪') or [])} 条")
    if "示例" in str(data.get("版本", "")):
        print("  注意：版本里含“示例”，页面顶部会显示“示例数据”横条")
    if warns:
        print(f"提醒（{len(warns)} 条，不影响生成）：")
        for w in warns:
            print(f"  - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

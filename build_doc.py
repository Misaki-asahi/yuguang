# -*- coding: utf-8 -*-
"""把 content/*.md 渲染成排好版的 Word 设计方案。"""
import os
import re
from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

BASE = os.path.dirname(os.path.abspath(__file__))
CONTENT = os.path.join(BASE, "content")
OUT = os.path.join(BASE, "余光_流程_大纲_设计方案_v1.1.docx")

NAVY = "1F4E79"
ACCENT = "B45309"
INK = "1F2937"
SUB = "4B5563"
MUTED = "7A8699"
LIGHT = "DEE9F4"
BORDER = "C9D2DB"
ZEBRA = "F5F7FA"
CODE_BG = "F7F8FA"
CALL_BG = "F1F6FB"

EA_BODY = "宋体"
EA_HEAD = "微软雅黑"
ASCII_BODY = "Times New Roman"
ASCII_HEAD = "Microsoft YaHei"
ASCII_MONO = "Consolas"

CONTENT_W = 16.0  # cm

# ---------------------------------------------------------------- 元素顺序
ORDER = {
    "pPr": ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr",
            "widowControl", "numPr", "suppressLineNumbers", "pBdr", "shd",
            "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap",
            "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN",
            "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind",
            "contextualSpacing", "mirrorIndents", "suppressOverlap", "jc",
            "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl",
            "divId", "cnfStyle", "rPr", "sectPr", "pPrChange"],
    "tblPr": ["tblStyle", "tblpPr", "tblOverlap", "bidiVisual",
              "tblStyleRowBandSize", "tblStyleColBandSize", "tblW", "jc",
              "tblCellSpacing", "tblInd", "tblBorders", "shd", "tblLayout",
              "tblCellMar", "tblLook", "tblCaption", "tblDescription"],
    "trPr": ["cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore",
             "wAfter", "cantSplit", "trHeight", "tblHeader", "tblCellSpacing",
             "jc", "hidden"],
    "tcPr": ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders",
             "shd", "noWrap", "tcMar", "textDirection", "tcFitText", "vAlign",
             "hideMark"],
    "rPr": ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps",
            "strike", "dstrike", "outline", "shadow", "emboss", "imprint",
            "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
            "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
            "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang",
            "eastAsianLayout", "specVanish", "oMath"],
}


def _local(el):
    return el.tag.split("}")[1] if "}" in el.tag else el.tag


def insert_ordered(parent, child, kind):
    order = ORDER[kind]
    name = _local(child)
    pos = order.index(name) if name in order else len(order) - 1
    for existing in list(parent):
        en = _local(existing)
        epos = order.index(en) if en in order else len(order) - 1
        if epos > pos:
            existing.addprevious(child)
            return child
    parent.append(child)
    return child


def replace_child(parent, tag, kind):
    old = parent.find(qn(tag))
    if old is not None:
        parent.remove(old)
    el = OxmlElement(tag)
    insert_ordered(parent, el, kind)
    return el


# ---------------------------------------------------------------- 文本工具
def set_run(run, size=10.5, bold=False, color=INK, ea=EA_BODY, ascii_=ASCII_BODY,
            italic=False, spacing=None):
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.name = ascii_
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), ascii_)
    rFonts.set(qn("w:hAnsi"), ascii_)
    rFonts.set(qn("w:eastAsia"), ea)
    rFonts.set(qn("w:cs"), ascii_)
    if spacing is not None:
        run.font.spacing = Pt(spacing)


def para_fmt(p, before=0, after=6, line=1.35, align=None, left=0, first=0,
             right=0, keep_next=False):
    pf = p.paragraph_format
    pf.space_before = Pt(before)
    pf.space_after = Pt(after)
    pf.line_spacing = line
    pf.left_indent = Cm(left)
    pf.right_indent = Cm(right)
    pf.first_line_indent = Cm(first)
    pf.keep_with_next = keep_next
    pf.widow_control = True
    if align is not None:
        p.alignment = align


def shade_cell(cell, color):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = replace_child(tcPr, "w:shd", "tcPr")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), color)


def cell_border(cell, edges, color=BORDER, sz=4):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = tcPr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        insert_ordered(tcPr, borders, "tcPr")
    for edge, width in edges.items():
        el = OxmlElement(f"w:{edge}")
        if width <= 0:
            el.set(qn("w:val"), "nil")
        else:
            el.set(qn("w:val"), "single")
            el.set(qn("w:sz"), str(width))
            el.set(qn("w:space"), "0")
            el.set(qn("w:color"), color)
        borders.append(el)


def no_pic_border(doc):
    """显式去掉图片边框（LibreOffice 预览会画默认框线）。"""
    for spPr in doc.element.body.iter(qn("pic:spPr")):
        if spPr.find(qn("a:ln")) is None:
            ln = OxmlElement("a:ln")
            ln.append(OxmlElement("a:noFill"))
            spPr.append(ln)


def table_borders(table, color=BORDER, sz=4, inside=True):
    tblPr = table._tbl.tblPr
    borders = replace_child(tblPr, "w:tblBorders", "tblPr")
    edges = ["top", "left", "bottom", "right"]
    if inside:
        edges += ["insideH", "insideV"]
    for edge in edges:
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)


def table_no_borders(table):
    tblPr = table._tbl.tblPr
    borders = replace_child(tblPr, "w:tblBorders", "tblPr")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "nil")
        borders.append(el)


def table_fixed(table, widths_cm):
    table.autofit = False
    tblPr = table._tbl.tblPr
    layout = replace_child(tblPr, "w:tblLayout", "tblPr")
    layout.set(qn("w:type"), "fixed")
    w = replace_child(tblPr, "w:tblW", "tblPr")
    w.set(qn("w:w"), str(int(sum(widths_cm) / 2.54 * 1440)))
    w.set(qn("w:type"), "dxa")
    for row in table.rows:
        for i, cell in enumerate(row.cells):
            cell.width = Cm(widths_cm[i])
    grid = table._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        for gc, wcm in zip(grid.findall(qn("w:gridCol")), widths_cm):
            gc.set(qn("w:w"), str(int(wcm / 2.54 * 1440)))


def cell_margins(table, top=50, bottom=50, left=90, right=90):
    tblPr = table._tbl.tblPr
    mar = replace_child(tblPr, "w:tblCellMar", "tblPr")
    for edge, val in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:w"), str(val))
        el.set(qn("w:type"), "dxa")
        mar.append(el)


def no_split(row):
    trPr = row._tr.get_or_add_trPr()
    insert_ordered(trPr, OxmlElement("w:cantSplit"), "trPr")


def repeat_header(row):
    trPr = row._tr.get_or_add_trPr()
    insert_ordered(trPr, OxmlElement("w:tblHeader"), "trPr")


def para_bottom_border(p, color=NAVY, sz=8, space=4):
    pPr = p._p.get_or_add_pPr()
    old = pPr.find(qn("w:pBdr"))
    if old is not None:
        pPr.remove(old)
    pbdr = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(sz))
    bottom.set(qn("w:space"), str(space))
    bottom.set(qn("w:color"), color)
    pbdr.append(bottom)
    insert_ordered(pPr, pbdr, "pPr")


def add_field(paragraph, code, size=9, color=MUTED):
    run = paragraph.add_run()
    set_run(run, size=size, color=color)
    fld_begin = OxmlElement("w:fldChar")
    fld_begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = code
    fld_sep = OxmlElement("w:fldChar")
    fld_sep.set(qn("w:fldCharType"), "separate")
    txt = OxmlElement("w:t")
    txt.text = "1"
    fld_end = OxmlElement("w:fldChar")
    fld_end.set(qn("w:fldCharType"), "end")
    run._r.append(fld_begin)
    run._r.append(instr)
    run._r.append(fld_sep)
    run._r.append(txt)
    run._r.append(fld_end)


# ---------------------------------------------------------------- 行内解析
QUOTE_STATE = {"open": True}


def smart_quotes(text):
    out = []
    for ch in text:
        if ch == '"':
            out.append("“" if QUOTE_STATE["open"] else "”")
            QUOTE_STATE["open"] = not QUOTE_STATE["open"]
        else:
            out.append(ch)
    return "".join(out)


def sq(text):
    QUOTE_STATE["open"] = True
    return smart_quotes(text)


def add_rich(p, text, size=10.5, color=INK, bold_all=False, ea=EA_BODY,
             quotes=True):
    QUOTE_STATE["open"] = True
    pattern = re.compile(r"(\*\*.+?\*\*|`[^`]+`)")
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            seg = text[pos:m.start()]
            r = p.add_run(smart_quotes(seg) if quotes else seg)
            set_run(r, size=size, bold=bold_all, color=color, ea=ea)
        tok = m.group(0)
        if tok.startswith("**"):
            r = p.add_run(smart_quotes(tok[2:-2]) if quotes else tok[2:-2])
            set_run(r, size=size, bold=True,
                    color=NAVY if not bold_all else color, ea=ea)
        else:
            r = p.add_run(tok[1:-1])
            set_run(r, size=size - 0.7, bold=False, color="8A3A0E", ea=ea,
                    ascii_=ASCII_MONO)
        pos = m.end()
    if pos < len(text):
        seg = text[pos:]
        r = p.add_run(smart_quotes(seg) if quotes else seg)
        set_run(r, size=size, bold=bold_all, color=color, ea=ea)


def disp_width(s):
    return sum(2 if ord(ch) > 127 else 1 for ch in s)


# ---------------------------------------------------------------- 块级渲染
class Renderer:
    def __init__(self, doc):
        self.doc = doc

    def h1(self, text):
        text = sq(text)
        p = self.doc.add_paragraph()
        p.paragraph_format.page_break_before = True
        para_fmt(p, before=0, after=4, line=1.1, keep_next=True)
        r = p.add_run(text)
        set_run(r, size=19, bold=True, color=NAVY, ea=EA_HEAD, ascii_=ASCII_HEAD)
        para_bottom_border(p, color=NAVY, sz=12, space=6)

    def h2(self, text):
        text = sq(text)
        p = self.doc.add_paragraph()
        para_fmt(p, before=16, after=7, line=1.2, keep_next=True)
        r = p.add_run(text)
        set_run(r, size=14, bold=True, color=NAVY, ea=EA_HEAD, ascii_=ASCII_HEAD)
        para_bottom_border(p, color="D6E0EC", sz=6, space=3)

    def h3(self, text):
        text = sq(text)
        p = self.doc.add_paragraph()
        para_fmt(p, before=11, after=5, line=1.25, keep_next=True)
        r = p.add_run(text)
        set_run(r, size=11.5, bold=True, color="2E4A66", ea=EA_HEAD, ascii_=ASCII_HEAD)

    def page_title(self, text):
        p = self.doc.add_paragraph()
        p.paragraph_format.page_break_before = True
        para_fmt(p, before=0, after=6, line=1.1, keep_next=True)
        r = p.add_run(text)
        set_run(r, size=19, bold=True, color=NAVY, ea=EA_HEAD, ascii_=ASCII_HEAD)
        para_bottom_border(p, color=NAVY, sz=12, space=6)

    def para(self, text):
        p = self.doc.add_paragraph()
        para_fmt(p, before=0, after=6, line=1.4, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
        add_rich(p, text, size=10.5)

    def bullet(self, text, level=0):
        p = self.doc.add_paragraph()
        left = 0.62 + level * 0.6
        para_fmt(p, before=0, after=3, line=1.4, left=left, first=-0.45,
                 align=WD_ALIGN_PARAGRAPH.JUSTIFY)
        r = p.add_run("·　")
        set_run(r, size=10.5, bold=True, color=NAVY)
        add_rich(p, text, size=10.5)

    def numbered(self, text, num):
        p = self.doc.add_paragraph()
        para_fmt(p, before=0, after=3, line=1.4, left=0.75, first=-0.7,
                 align=WD_ALIGN_PARAGRAPH.JUSTIFY)
        r = p.add_run(f"{num}. ")
        set_run(r, size=10.5, bold=True, color=NAVY)
        add_rich(p, text, size=10.5)

    def callout(self, lines):
        t = self.doc.add_table(rows=1, cols=1)
        table_fixed(t, [CONTENT_W])
        cell = t.cell(0, 0)
        cell_margins(t, 110, 110, 170, 140)
        table_no_borders(t)
        shade_cell(cell, CALL_BG)
        cell_border(cell, {"left": 24}, color=NAVY, sz=24)
        for edge in ("top", "bottom", "right"):
            cell_border(cell, {edge: 2}, color="DCE6F1", sz=2)
        cell.paragraphs[0].text = ""
        first = True
        for ln in lines:
            p = cell.paragraphs[0] if first else cell.add_paragraph()
            first = False
            para_fmt(p, before=0, after=2, line=1.35, align=WD_ALIGN_PARAGRAPH.JUSTIFY)
            add_rich(p, ln, size=10)
        self.spacer(4)

    def code(self, lines):
        t = self.doc.add_table(rows=1, cols=1)
        table_fixed(t, [CONTENT_W])
        cell = t.cell(0, 0)
        cell_margins(t, 110, 110, 150, 120)
        table_no_borders(t)
        shade_cell(cell, CODE_BG)
        for edge in ("top", "left", "bottom", "right"):
            cell_border(cell, {edge: 2}, color="E3E6EA", sz=2)
        cell.paragraphs[0].text = ""
        first = True
        for ln in lines:
            p = cell.paragraphs[0] if first else cell.add_paragraph()
            first = False
            para_fmt(p, before=0, after=0, line=1.15)
            r = p.add_run(ln if ln else " ")
            set_run(r, size=8.6, color="333B44", ea=EA_HEAD, ascii_=ASCII_MONO)
        self.spacer(6)

    def table(self, rows):
        header, body = rows[0], rows[1:]
        ncol = len(header)
        if ncol == 0:
            return
        raw = []
        for c in range(ncol):
            w = 4
            for r in rows:
                if c < len(r):
                    w = max(w, min(disp_width(r[c]), 60))
            raw.append(w)
        tot = sum(raw)
        widths = [m * CONTENT_W / tot for m in raw]
        widths = [max(1.9, w) for w in widths]
        s = sum(widths)
        widths = [w * CONTENT_W / s for w in widths]
        for _ in range(3):
            deficit = CONTENT_W - sum(widths)
            if abs(deficit) < 0.01:
                break
            flex = [i for i, w in enumerate(widths) if w > 1.95]
            if not flex:
                break
            for i in flex:
                widths[i] += deficit / len(flex)
        fs = 8.4 if ncol >= 5 else 8.9

        t = self.doc.add_table(rows=len(rows), cols=ncol)
        table_borders(t, color=BORDER, sz=4)
        cell_margins(t, 45, 45, 85, 85)
        table_fixed(t, widths)
        keep_all = len(rows) <= 22
        for ri, row_data in enumerate(rows):
            row = t.rows[ri]
            no_split(row)
            if ri == 0:
                repeat_header(row)
            for ci in range(ncol):
                cell = row.cells[ci]
                cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                p = cell.paragraphs[0]
                txt = row_data[ci] if ci < len(row_data) else ""
                if keep_all and ri < len(rows) - 1:
                    p.paragraph_format.keep_with_next = True
                if ri == 0:
                    shade_cell(cell, NAVY)
                    para_fmt(p, before=0, after=0, line=1.15,
                             align=WD_ALIGN_PARAGRAPH.CENTER)
                    add_rich(p, txt, size=fs + 0.2, color="FFFFFF", bold_all=True,
                             ea=EA_HEAD)
                else:
                    if ri % 2 == 0:
                        shade_cell(cell, ZEBRA)
                    para_fmt(p, before=0, after=0, line=1.22)
                    add_rich(p, txt, size=fs, color=INK)
        self.spacer(8)

    def figure(self, path, caption, width=15.2):
        p = self.doc.add_paragraph()
        para_fmt(p, before=6, after=2, line=1.0, align=WD_ALIGN_PARAGRAPH.CENTER,
                 keep_next=True)
        p.add_run().add_picture(path, width=Cm(width))
        cap = self.doc.add_paragraph()
        para_fmt(cap, before=2, after=12, line=1.0, align=WD_ALIGN_PARAGRAPH.CENTER)
        r = cap.add_run(caption)
        set_run(r, size=9, color=SUB, ea=EA_HEAD, ascii_=ASCII_HEAD)

    def spacer(self, pt=6):
        p = self.doc.add_paragraph()
        para_fmt(p, before=0, after=0, line=1.0)
        set_run(p.add_run(""), size=pt)

    def render(self, md_text):
        lines = md_text.split("\n")
        i = 0
        while i < len(lines):
            line = lines[i].rstrip()
            if not line.strip():
                i += 1
                continue
            if line.strip().startswith("```"):
                i += 1
                buf = []
                while i < len(lines) and not lines[i].strip().startswith("```"):
                    buf.append(lines[i].rstrip("\n"))
                    i += 1
                i += 1
                self.code(buf)
                continue
            m = re.match(r"\[\[fig:([^|]+)\|([^\]]+)\]\]", line.strip())
            if m:
                self.figure(os.path.join(BASE, m.group(1)), m.group(2),
                            width=_fig_width(m.group(1)))
                i += 1
                continue
            if line.startswith("# "):
                self.h1(line[2:].strip())
                i += 1
                continue
            if line.startswith("## "):
                self.h2(line[3:].strip())
                i += 1
                continue
            if line.startswith("### "):
                self.h3(line[4:].strip())
                i += 1
                continue
            if line.strip().startswith("|"):
                rows = []
                while i < len(lines) and lines[i].strip().startswith("|"):
                    raw = lines[i].strip()
                    if re.match(r"^\|[\s\-:|]+\|$", raw):
                        i += 1
                        continue
                    rows.append([c.strip() for c in raw.strip("|").split("|")])
                    i += 1
                if rows:
                    self.table(rows)
                continue
            if line.startswith(">"):
                buf = []
                while i < len(lines) and lines[i].startswith(">"):
                    c = lines[i][1:]
                    if c.startswith(" "):
                        c = c[1:]
                    buf.append(c.rstrip())
                    i += 1
                while buf and not buf[0]:
                    buf.pop(0)
                while buf and not buf[-1]:
                    buf.pop()
                if buf:
                    self.callout(buf)
                continue
            m = re.match(r"^(\s*)-\s+(.*)$", line)
            if m:
                level = 1 if len(m.group(1)) >= 2 else 0
                self.bullet(m.group(2).strip(), level)
                i += 1
                continue
            m = re.match(r"^(\d+)\.\s+(.*)$", line)
            if m:
                self.numbered(m.group(2).strip(), m.group(1))
                i += 1
                continue
            buf = [line.strip()]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(
                    r"^(#|\||>|```|- |\d+\.\s|\[\[fig:)", lines[i].strip()):
                buf.append(lines[i].strip())
                i += 1
            self.para("".join(buf))


def _fig_width(path):
    name = os.path.basename(path)
    return {"fig1_arch.png": 15.4, "fig2_flow.png": 13.2,
            "fig3_decide.png": 13.4, "fig4_data.png": 15.6,
            "fig5_report.png": 15.2}.get(name, 15.2)


# ---------------------------------------------------------------- 文档骨架
def setup(doc):
    sec = doc.sections[0]
    sec.page_width = Cm(21.0)
    sec.page_height = Cm(29.7)
    sec.top_margin = Cm(2.4)
    sec.bottom_margin = Cm(2.2)
    sec.left_margin = Cm(2.5)
    sec.right_margin = Cm(2.5)
    sec.header_distance = Cm(1.3)
    sec.footer_distance = Cm(1.1)
    sec.different_first_page_header_footer = True

    st = doc.styles["Normal"]
    st.font.name = ASCII_BODY
    st.font.size = Pt(10.5)
    rPr = st.element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:ascii"), ASCII_BODY)
    rFonts.set(qn("w:hAnsi"), ASCII_BODY)
    rFonts.set(qn("w:eastAsia"), EA_BODY)
    st.paragraph_format.line_spacing = 1.35
    st.paragraph_format.space_after = Pt(6)

    hp = sec.header.paragraphs[0]
    para_fmt(hp, before=0, after=2, line=1.0, align=WD_ALIGN_PARAGRAPH.LEFT)
    r = hp.add_run("余光　·　AI 屏幕行为监测与桌宠提醒工具")
    set_run(r, size=8.5, color=MUTED, ea=EA_HEAD, ascii_=ASCII_HEAD)
    r = hp.add_run("　　　　　　　　　　　　　　　　　　　　流程 / 大纲 / 设计方案")
    set_run(r, size=8.5, color=MUTED, ea=EA_HEAD, ascii_=ASCII_HEAD)
    para_bottom_border(hp, color="DCE3EA", sz=4, space=2)

    fp = sec.footer.paragraphs[0]
    para_fmt(fp, before=0, after=0, line=1.0, align=WD_ALIGN_PARAGRAPH.CENTER)
    r = fp.add_run("— ")
    set_run(r, size=9, color=MUTED)
    add_field(fp, " PAGE ", size=9)
    r = fp.add_run(" —")
    set_run(r, size=9, color=MUTED)


def cover(doc):
    for _ in range(3):
        p = doc.add_paragraph()
        para_fmt(p, before=0, after=0, line=1.0)
        set_run(p.add_run(""), size=14)

    t = doc.add_table(rows=1, cols=1)
    table_fixed(t, [CONTENT_W])
    cell = t.cell(0, 0)
    shade_cell(cell, NAVY)
    cell.paragraphs[0].text = ""
    para_fmt(cell.paragraphs[0], before=0, after=0, line=0.7)
    set_run(cell.paragraphs[0].add_run(" "), size=5)

    p = doc.add_paragraph()
    para_fmt(p, before=26, after=0, line=1.0)
    r = p.add_run("余光")
    set_run(r, size=13, bold=True, color=ACCENT, ea=EA_HEAD, ascii_=ASCII_HEAD,
            spacing=2)

    p = doc.add_paragraph()
    para_fmt(p, before=12, after=2, line=1.22)
    r = p.add_run("AI 屏幕行为监测与\n桌宠提醒工具")
    set_run(r, size=30, bold=True, color=INK, ea=EA_HEAD, ascii_=ASCII_HEAD)

    p = doc.add_paragraph()
    para_fmt(p, before=10, after=0, line=1.4)
    r = p.add_run("流程设计　·　项目大纲　·　技术方案")
    set_run(r, size=15, color=NAVY, ea=EA_HEAD, ascii_=ASCII_HEAD)
    para_bottom_border(p, color=NAVY, sz=8, space=10)

    p = doc.add_paragraph()
    para_fmt(p, before=16, after=0, line=1.5)
    r = p.add_run("「它不该盯着你，它只是用余光瞥见你。」")
    set_run(r, size=10.5, color=SUB, ea=EA_BODY, ascii_=ASCII_BODY)

    for _ in range(6):
        p = doc.add_paragraph()
        para_fmt(p, before=0, after=0, line=1.0)
        set_run(p.add_run(""), size=12)

    info = [
        ("文档类型", "产品设计方案（个人自用工具 · MVP 导向）"),
        ("版本", "v1.1"),
        ("日期", "2026 年 11 月 6 日"),
        ("适用范围", "Windows 单机 · 个人使用"),
        ("状态", "待评审 · 可直接进入开发"),
    ]
    for k, v in info:
        p = doc.add_paragraph()
        para_fmt(p, before=5, after=5, line=1.25)
        p.paragraph_format.tab_stops.add_tab_stop(Cm(3.6))
        r = p.add_run(k)
        set_run(r, size=9.5, color=MUTED, ea=EA_HEAD, ascii_=ASCII_HEAD)
        r = p.add_run("\t")
        set_run(r, size=9.5, color=MUTED)
        r = p.add_run(v)
        set_run(r, size=9.5, color=INK)
        para_bottom_border(p, color="E8EDF2", sz=2, space=4)


ABSTRACT = """## 一句话

一个常驻后台的本地小程序：每 5 秒看一眼你在用什么窗口，每分钟截一张图，用视觉大模型判断你此刻在干什么；白天在你跑偏时以一只小桌宠的形式轻轻戳你一下，晚上给你一张「今天的时间去哪了」的账单。

## 三个反直觉的结论

这份方案里有三个判断，和最初的设想不完全一致，但每一个都直接决定项目能不能活下去：

1. **截图不是主角，窗口标题和进程名才是。** 最初的想法是"每隔一段时间截张图让 AI 看"。但截图贵、慢、还会误判；而前台窗口的标题和进程名几乎零成本、零延迟、准确率极高。正确的做法是**结构化信号优先、截图兜底**——先花 0 成本判断这 80% 的情况，剩下 20% 再花钱看画面。这样成本降一个数量级，准确率反而更高。

2. **没有"目标声明"，就没有"摸鱼"。** "摸鱼"不是一个客观状态，而是一个关于意图的判断。同样的 B 站页面，在赶稿时是摸鱼，在找资料时是工作。所以系统必须先知道"你原本要干什么"，否则只能做分类，不能做提醒。这就是为什么方案里反复出现"专注会话"。

3. **提醒的价值不在"响"，而在"少而准"。** 误报一次，用户就会关掉提醒；关掉提醒，产品就死了。所以整个判定链设计成"全否才退出"：任何一环存疑都只记录、不提醒。宁可漏报十次，也不误报一次。

## 文档结构

| 部分 | 回答什么问题 | 建议读法 |
|---|---|---|
| 第一部分　流程设计 | 人怎么用、机器怎么跑、怎么判断摸鱼 | 全员必读，是全案骨架 |
| 第二部分　项目大纲 | 做什么、做多少、先做哪个 | 排期和砍需求时看 |
| 第三部分　设计方案 | 每一层具体怎么实现 | 动手写代码时对着看 |
| 附录 | 提示词、规则表、配置、文案 | 实现时直接抄 |

> **怎么读**：赶时间的人直接翻到第三部分第 18 节的「七天开工清单」，按天做，第七天就能看到东西；要判断这事值不值得做，读摘要这一页和第 5 节功能地图就够了；要拿去评审，按目录顺序讲——第一部分是骨架，第二部分是可执行计划，第三部分是技术深度。
"""


def toc_page(doc, r, entries):
    r.page_title("目　录")
    for level, text in entries:
        p = doc.add_paragraph()
        text = sq(text)
        if level == 1:
            para_fmt(p, before=13, after=4, line=1.2, keep_next=True)
            run = p.add_run(text)
            set_run(run, size=12, bold=True, color=NAVY, ea=EA_HEAD, ascii_=ASCII_HEAD)
        else:
            para_fmt(p, before=1, after=1, line=1.35, left=0.9)
            run = p.add_run(text)
            set_run(run, size=10, color=INK)


def collect_entries(paths):
    entries = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            fenced = False
            for line in f:
                s = line.rstrip("\n")
                if s.strip().startswith("```"):
                    fenced = not fenced
                    continue
                if fenced:
                    continue
                if s.startswith("# "):
                    entries.append((1, s[2:].strip()))
                elif s.startswith("## "):
                    entries.append((2, s[3:].strip()))
    return entries


def main():
    doc = Document()
    setup(doc)
    cover(doc)

    r = Renderer(doc)
    r.page_title("摘　要")
    r.render(ABSTRACT)

    paths = [os.path.join(CONTENT, f) for f in
             ("part1.md", "part2.md", "part3.md", "appendix.md")]
    toc_page(doc, r, collect_entries(paths))

    for path in paths:
        with open(path, encoding="utf-8") as f:
            r.render(f.read())

    no_pic_border(doc)
    doc.core_properties.title = "余光 · AI 屏幕行为监测与桌宠提醒工具 — 流程 / 大纲 / 设计方案"
    doc.core_properties.subject = "个人自用工具的设计方案 v1.1"
    doc.core_properties.author = ""
    doc.save(OUT)
    print("saved:", OUT)


if __name__ == "__main__":
    main()

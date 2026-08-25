"""Design system + helpers for the PulseOS Review-1 deck."""
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.oxml.ns import qn
import copy

# ---------- palette ----------
NAVY    = RGBColor(0x1F, 0x3A, 0x5F)   # primary dark
TEAL    = RGBColor(0x0E, 0x7C, 0x86)   # accent
TEAL_LT = RGBColor(0xDD, 0xEF, 0xF1)   # light teal fill
BLUE_LT = RGBColor(0xEA, 0xF1, 0xF8)   # light blue fill
ORANGE  = RGBColor(0xC5, 0x5A, 0x11)   # highlight (sparing)
AMBER_LT= RGBColor(0xFB, 0xEA, 0xD4)
GRAY    = RGBColor(0x40, 0x40, 0x40)   # body text
GRAY_MED= RGBColor(0x7F, 0x7F, 0x7F)
GRAY_LT = RGBColor(0xF2, 0xF3, 0xF5)
WHITE   = RGBColor(0xFF, 0xFF, 0xFF)
GREEN   = RGBColor(0x2E, 0x7D, 0x32)
RED     = RGBColor(0xB0, 0x3A, 0x2E)
BORDER  = RGBColor(0xC9, 0xD3, 0xDD)

SW, SH = Inches(13.333), Inches(7.5)
MARGIN = Inches(0.55)
DATE = "29-07-2026"

def set_fill(shape, color):
    shape.fill.solid(); shape.fill.fore_color.rgb = color
    shape.line.fill.background()

def set_line(shape, color, w=0.75):
    shape.line.color.rgb = color; shape.line.width = Pt(w)

def _set_text(tf, runs_spec, size, color, bold=False, align=PP_ALIGN.LEFT,
              font="Calibri", space_after=4, line=None):
    tf.word_wrap = True
    first = True
    for spec in runs_spec:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.alignment = align
        p.space_after = Pt(space_after)
        if line: p.line_spacing = line
        if isinstance(spec, str):
            spec = [(spec, {})]
        for txt, ov in spec:
            r = p.add_run(); r.text = txt
            f = r.font
            f.size = Pt(ov.get("size", size)); f.bold = ov.get("bold", bold)
            f.italic = ov.get("italic", False)
            f.color.rgb = ov.get("color", color); f.name = ov.get("font", font)

def textbox(slide, x, y, w, h, runs, size=14, color=GRAY, bold=False,
            align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, font="Calibri",
            space_after=4, line=None):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = Pt(2); tf.margin_top = tf.margin_bottom = Pt(1)
    _set_text(tf, runs if isinstance(runs, list) else [runs], size, color, bold, align,
              font, space_after, line)
    return tb

def box(slide, x, y, w, h, fill=BLUE_LT, text=None, size=13, color=NAVY, bold=False,
        align=PP_ALIGN.CENTER, shape=MSO_SHAPE.ROUNDED_RECTANGLE, line_color=None,
        anchor=MSO_ANCHOR.MIDDLE, radius=0.12, space_after=2, font="Calibri", ln=None):
    s = slide.shapes.add_shape(shape, x, y, w, h)
    set_fill(s, fill)
    if line_color: set_line(s, line_color)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        try: s.adjustments[0] = radius
        except Exception: pass
    if text is not None:
        tf = s.text_frame
        tf.word_wrap = True
        tf.margin_left = tf.margin_right = Pt(6); tf.margin_top = tf.margin_bottom = Pt(3)
        tf.vertical_anchor = anchor
        _set_text(tf, text if isinstance(text, list) else [text], size, color, bold,
                  align, font, space_after, ln)
    s.shadow.inherit = False
    return s

def arrow_r(slide, x, y, w=Inches(0.32), h=Inches(0.26), color=TEAL):
    s = slide.shapes.add_shape(MSO_SHAPE.RIGHT_ARROW, x, y, w, h)
    set_fill(s, color); s.shadow.inherit = False
    return s

def arrow_d(slide, x, y, w=Inches(0.26), h=Inches(0.30), color=TEAL):
    s = slide.shapes.add_shape(MSO_SHAPE.DOWN_ARROW, x, y, w, h)
    set_fill(s, color); s.shadow.inherit = False
    return s

def chip(slide, x, y, w, h, text, fill=TEAL, color=WHITE, size=11, bold=True):
    return box(slide, x, y, w, h, fill=fill, text=text, size=size, color=color,
               bold=bold, radius=0.5)

# ---------- slide chrome ----------
_page = [0]

def new_slide(prs, title=None, subtitle=None, kicker=None):
    """Title-only chrome: kicker chip, title, teal rule, footer."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # Blank
    _page[0] += 1
    n = _page[0]
    if n > 1:
        # footer
        ln = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, MARGIN, Inches(7.08),
                                        SW - MARGIN, Inches(7.08))
        ln.line.color.rgb = BORDER; ln.line.width = Pt(0.75)
        textbox(slide, MARGIN, Inches(7.12), Inches(2.5), Inches(0.3), DATE,
                size=10, color=GRAY_MED)
        textbox(slide, Inches(5.9), Inches(7.12), Inches(1.5), Inches(0.3), "SCOPE",
                size=10, color=GRAY_MED, align=PP_ALIGN.CENTER)
        textbox(slide, Inches(12.3), Inches(7.12), Inches(0.5), Inches(0.3), str(n),
                size=10, color=GRAY_MED, align=PP_ALIGN.RIGHT)
    if title:
        ty = Inches(0.32)
        if kicker:
            chip(slide, MARGIN, Inches(0.28), Inches(0.06 + 0.082 * len(kicker)),
                 Inches(0.26), kicker, size=10)
            ty = Inches(0.60)
        textbox(slide, MARGIN, ty, SW - 2 * MARGIN, Inches(0.55), title,
                size=26, color=NAVY, bold=True, font="Calibri Light")
        bar = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, MARGIN,
                                     ty + Inches(0.52), Inches(1.15), Pt(3.2))
        set_fill(bar, TEAL)
        if subtitle:
            textbox(slide, MARGIN + Inches(1.35), ty + Inches(0.44),
                    SW - 2 * MARGIN - Inches(1.4), Inches(0.3), subtitle,
                    size=12.5, color=GRAY_MED)
    return slide

def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text

def bullets(slide, x, y, w, h, items, size=15, gap=6, color=GRAY, marker="▪",
            mcolor=TEAL, line=1.06):
    """items: list of (bold_lead, rest) or plain string."""
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame; tf.word_wrap = True
    first = True
    for it in items:
        p = tf.paragraphs[0] if first else tf.add_paragraph()
        first = False
        p.space_after = Pt(gap); p.line_spacing = line
        m = p.add_run(); m.text = marker + "  "
        m.font.size = Pt(size); m.font.color.rgb = mcolor; m.font.bold = True
        if isinstance(it, tuple):
            lead, rest = it
            r = p.add_run(); r.text = lead
            r.font.size = Pt(size); r.font.bold = True; r.font.color.rgb = NAVY
            if rest:
                r2 = p.add_run(); r2.text = rest
                r2.font.size = Pt(size); r2.font.color.rgb = color
        else:
            r = p.add_run(); r.text = it
            r.font.size = Pt(size); r.font.color.rgb = color
    return tb

# ---------- tables ----------
def style_cell(cell, text, size=11, color=GRAY, bold=False, fill=None,
               align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.MIDDLE, line=1.0):
    if fill is not None:
        cell.fill.solid(); cell.fill.fore_color.rgb = fill
    cell.margin_left = Pt(5); cell.margin_right = Pt(5)
    cell.margin_top = Pt(2.5); cell.margin_bottom = Pt(2.5)
    cell.vertical_anchor = anchor
    tf = cell.text_frame; tf.word_wrap = True
    _set_text(tf, text if isinstance(text, list) else [text], size, color, bold, align,
              "Calibri", 0, line)

def make_table(slide, x, y, w, h, rows_data, col_widths, header_fill=NAVY,
               header_color=WHITE, size=11, header_size=11.5, banded=True,
               aligns=None, first_col_bold=True):
    nrows, ncols = len(rows_data), len(rows_data[0])
    g = slide.shapes.add_table(nrows, ncols, x, y, w, h)
    table = g.table
    total = sum(col_widths)
    for i, cw in enumerate(col_widths):
        table.columns[i].width = Emu(int(w * cw / total))
    for ri, row in enumerate(rows_data):
        for ci, val in enumerate(row):
            cell = table.cell(ri, ci)
            if ri == 0:
                style_cell(cell, val, size=header_size, color=header_color, bold=True,
                           fill=header_fill,
                           align=(aligns[ci] if aligns else PP_ALIGN.LEFT))
            else:
                fill = GRAY_LT if (banded and ri % 2 == 0) else WHITE
                style_cell(cell, val, size=size,
                           bold=(first_col_bold and ci == 0),
                           color=(NAVY if (first_col_bold and ci == 0) else GRAY),
                           fill=fill,
                           align=(aligns[ci] if aligns else PP_ALIGN.LEFT))
    # thin borders
    tbl = table._tbl
    return table

def vflow(slide, x, y, w, steps, bh, gap=Inches(0.16), size=12.5,
          fills=None, tcolors=None):
    """vertical flow of boxes with down-arrows; steps = list of text/spec."""
    cy = y
    for i, st in enumerate(steps):
        f = fills[i] if fills else BLUE_LT
        c = tcolors[i] if tcolors else NAVY
        box(slide, x, cy, w, bh, fill=f, text=st, size=size, color=c, bold=True)
        cy += bh
        if i < len(steps) - 1:
            arrow_d(slide, x + w / 2 - Inches(0.10), cy + Inches(0.01),
                    w=Inches(0.20), h=gap - Inches(0.02))
            cy += gap
    return cy

def hflow(slide, x, y, steps, bw, bh, gap=Inches(0.34), size=12,
          fills=None, tcolors=None, sub=None):
    cx = x
    for i, st in enumerate(steps):
        f = fills[i] if fills else BLUE_LT
        c = tcolors[i] if tcolors else NAVY
        box(slide, cx, y, bw, bh, fill=f, text=st, size=size, color=c, bold=True)
        if sub and sub[i]:
            textbox(slide, cx - Inches(0.05), y + bh + Inches(0.05), bw + Inches(0.1),
                    Inches(0.55), sub[i], size=9.5, color=GRAY_MED, align=PP_ALIGN.CENTER)
        cx += bw
        if i < len(steps) - 1:
            arrow_r(slide, cx + Inches(0.02), y + bh / 2 - Inches(0.11),
                    w=gap - Inches(0.04), h=Inches(0.22))
            cx += gap
    return cx

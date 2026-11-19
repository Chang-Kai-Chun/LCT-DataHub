"""G-5：PD 報告（PowerPoint，2026-11-19 定案）。

- 樣式沿用 LCT DataHub（lct. 設計：淺灰底、深色字、深藍與橘色點綴）；中文標楷體、英文與數字 Times New Roman；16:9
- 每個表格「每個條件一欄」（每個條件由使用者選一顆代表 pixel）；算不出來的格子留空
- 投影片：封面 → 暗電流（偏移／未偏移兩張圖）→ EQE／R／D*(λ) → 理論 D* → 實際 D* → Noise；沒有資料的頁不產生
- 每張圖下方有英文圖說；同一頁的圖大小相同；理論 D* 與實際 D* 的表格大小相同（2026-11-19 依 Gino 調整的 PPT）
這裡只負責排版：數值與圖（PNG）由呼叫端（API）整理成 PdReport 傳入。
"""
import re
from dataclasses import dataclass, field
from io import BytesIO

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

# ---------- 樣式（lct.css 的色票） ----------
BG = RGBColor(0xEF, 0xEF, 0xEF)
SURFACE = RGBColor(0xF8, 0xF8, 0xF8)
INK = RGBColor(0x11, 0x11, 0x11)
MUTED = RGBColor(0x55, 0x55, 0x55)
LINE = RGBColor(0xC9, 0xC9, 0xC9)
NAVY = RGBColor(0x14, 0x25, 0x4D)
ORANGE = RGBColor(0xF2, 0x6B, 0x1D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT_LATIN = "Times New Roman"
FONT_EAST_ASIA = "標楷體"
SLIDE_W, SLIDE_H = Emu(12192000), Emu(6858000)  # 16:9（13.333 × 7.5 in，與 PowerPoint 寬螢幕相同）
MARGIN = Inches(0.6)


# ---------- 資料 ----------
@dataclass(frozen=True)
class TableRow:
    """表格的一列：標籤（可含下標，見 label_sub）與每個條件的值（None 留空）。"""

    label: str
    values: list[float | None]
    label_sub: str = ""  # 標籤的下標（例如 J 的 d）
    unit: str = ""  # 標籤後的單位
    section: bool = False  # 分段標題列（整列合併，例如「0 V」）
    digits: int = 3  # 有效位數


@dataclass(frozen=True)
class PdReport:
    """一份 PD 報告的內容。"""

    title: str
    conditions: list[str]  # 欄名（條件），與每列 values 同順序
    pixels: list[str]  # 每個條件的代表 pixel
    recipe: str = ""
    concentration: str = ""
    structure_image: bytes | None = None
    dark_plots: list[tuple[str, bytes]] = field(default_factory=list)  # (英文圖說, PNG)
    dark_rows: list[TableRow] = field(default_factory=list)
    spectral_plots: list[tuple[str, bytes]] = field(default_factory=list)  # EQE、R、D*(λ)
    r_rows: list[TableRow] = field(default_factory=list)
    theory_rows: list[TableRow] = field(default_factory=list)  # 理論 D*（Shot + Thermal）
    measured_rows: list[TableRow] = field(default_factory=list)  # 實際 D*（實測 noise）
    noise_plots: list[tuple[str, bytes]] = field(default_factory=list)
    noise_rows: list[TableRow] = field(default_factory=list)
    footnote: str = ""  # 每頁底部的設定說明（偏壓、定義…）


# ---------- 文字工具 ----------
def _set_fonts(run, size: float, bold: bool = False, color: RGBColor = INK) -> None:
    """設定一段文字的字型：英文 Times New Roman、中文標楷體。"""
    font = run.font
    font.size = Pt(size)
    font.bold = bold
    font.color.rgb = color
    font.name = FONT_LATIN
    rpr = run._r.get_or_add_rPr()
    for tag in ("a:ea", "a:cs"):
        element = rpr.find(qn(tag))
        if element is None:
            element = rpr.makeelement(qn(tag), {})
            rpr.append(element)
        element.set("typeface", FONT_EAST_ASIA if tag == "a:ea" else FONT_LATIN)


def _add_run(paragraph, text: str, size: float, bold: bool = False, color: RGBColor = INK,
             baseline: int | None = None):
    """在段落加一段文字；baseline 為上下標（30000 上標、-25000 下標）。"""
    run = paragraph.add_run()
    run.text = text
    _set_fonts(run, size, bold, color)
    if baseline is not None:
        run._r.get_or_add_rPr().set("baseline", str(baseline))
    return run


def sci_parts(value: float | None, digits: int = 3) -> tuple[str, str]:
    """數值轉成（本體, 指數）：6.70×10 與 12；指數為 0 或 −1～2 之間直接寫數字；None 為空白。"""
    if value is None:
        return "", ""
    if value == 0:
        return "0", ""
    exponent = int(f"{value:e}".split("e")[1])
    if -1 <= exponent <= 2:
        return f"{value:.{digits}g}", ""
    mantissa = value / 10 ** exponent
    return f"{mantissa:.{digits - 1}f}×10", str(exponent)


_SUPERSCRIPT = re.compile(r"\^(-?[0-9.]+)")
_FORMULA_NUMBER = re.compile(r"(?<=[A-Za-z)])([0-9]+(?:\.[0-9]+)?)")


def _write_marked(paragraph, text: str, size: float, bold: bool = False, color: RGBColor = INK,
                  pattern: re.Pattern = _SUPERSCRIPT, baseline: int = 30000) -> None:
    """寫入文字，pattern 比對到的部分改為上標（單位 Hz^0.5）或下標（化學式的數字）。"""
    position = 0
    for match in pattern.finditer(text):
        if match.start() > position:
            _add_run(paragraph, text[position:match.start()], size, bold, color)
        _add_run(paragraph, match.group(1), size, bold, color, baseline=baseline)
        position = match.end()
    if position < len(text):
        _add_run(paragraph, text[position:], size, bold, color)


def formula_text(paragraph, text: str, size: float, bold: bool = False, color: RGBColor = INK) -> None:
    """化學式：元素後的數字為下標（Cs0.025FA0.475… 的數字縮小放低）。"""
    _write_marked(paragraph, text, size, bold, color, _FORMULA_NUMBER, -25000)


def _write_value(paragraph, value: float | None, size: float, digits: int = 3) -> None:
    """把數值寫成「6.70×10¹²」（指數為上標）。"""
    body, exponent = sci_parts(value, digits)
    if body:
        _add_run(paragraph, body, size)
    if exponent:
        _add_run(paragraph, exponent, size, baseline=30000)


def _textbox(slide, x, y, w, h, text: str, size: float, bold: bool = False, color: RGBColor = INK,
             align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP):
    """文字方塊（無內距）。"""
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = anchor
    for i, line in enumerate(text.split("\n")):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        paragraph.alignment = align
        _add_run(paragraph, line, size, bold, color)
    return box


def _background(slide, color: RGBColor) -> None:
    """投影片背景色。"""
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = color


def _rect(slide, x, y, w, h, color: RGBColor):
    """實心矩形（無框線）。"""
    shape = slide.shapes.add_shape(1, x, y, w, h)  # 1 = 矩形
    shape.fill.solid()
    shape.fill.fore_color.rgb = color
    shape.line.fill.background()
    shape.shadow.inherit = False
    return shape


def _wordmark(slide, x, y, size: float = 20, color: RGBColor = INK) -> None:
    """字標 lct.（句點橘色）。"""
    box = slide.shapes.add_textbox(x, y, Inches(1.2), Inches(0.5))
    frame = box.text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    paragraph = frame.paragraphs[0]
    _add_run(paragraph, "lct", size, True, color)
    _add_run(paragraph, ".", size, True, ORANGE)


# ---------- 版面 ----------
def _content_slide(prs: Presentation, letter: str, title: str, report: PdReport, page: int):
    """內容頁：左上「字母＋標題」（同網站頁首）、右上專案名稱、底部設定說明與頁碼。"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])  # 空白版面
    _background(slide, BG)
    box = slide.shapes.add_textbox(MARGIN, Inches(0.35), Inches(9), Inches(0.8))
    frame = box.text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.BOTTOM
    paragraph = frame.paragraphs[0]
    _add_run(paragraph, letter, 40, True, INK)
    _add_run(paragraph, "  " + title, 24, True, INK)
    _textbox(slide, Inches(8.4), Inches(0.55), Inches(4.33), Inches(0.4), report.title, 12, color=MUTED,
             align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.BOTTOM)
    _rect(slide, MARGIN, Inches(1.25), SLIDE_W - 2 * MARGIN, Emu(9525), LINE)  # 細分隔線（同網站 .tabs 底線）
    if report.footnote:
        _textbox(slide, MARGIN, Inches(7.05), Inches(10.5), Inches(0.3), report.footnote, 10, color=MUTED)
    _textbox(slide, Inches(11.6), Inches(7.05), Inches(1.13), Inches(0.3), str(page), 10, color=MUTED,
             align=PP_ALIGN.RIGHT)
    return slide


def _picture(slide, png: bytes, x, y, max_w, max_h) -> None:
    """放圖（等比例縮放到 max_w × max_h 內，置中）。"""
    picture = slide.shapes.add_picture(BytesIO(png), x, y)
    ratio = min(max_w / picture.width, max_h / picture.height)
    picture.width, picture.height = int(picture.width * ratio), int(picture.height * ratio)
    picture.left = int(x + (max_w - picture.width) / 2)
    picture.top = int(y + (max_h - picture.height) / 2)


def _cell_text(cell, size: float, color: RGBColor, fill: RGBColor | None, bold: bool = False,
               align=PP_ALIGN.CENTER):
    """清空儲存格並設定底色、邊距，回傳第一個段落。"""
    if fill is not None:
        cell.fill.solid()
        cell.fill.fore_color.rgb = fill
    cell.margin_left = cell.margin_right = Inches(0.06)
    cell.margin_top = cell.margin_bottom = Inches(0.03)
    cell.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = cell.text_frame.paragraphs[0]
    paragraph.alignment = align
    for run in list(paragraph.runs):
        run._r.getparent().remove(run._r)
    # 段落結尾的字級：空白儲存格的列高由它決定（沒設會是 PowerPoint 預設 18 pt）
    paragraph._p.get_or_add_endParaRPr().set("sz", str(int(size * 100)))
    return paragraph


TABLE_BOTTOM = Inches(6.9)  # 表格最低到這裡（下面是設定說明與頁碼）


def _table(slide, rows: list[TableRow], conditions: list[str], x, y, w, row_h=Inches(0.36), size: float = 12,
           label_w=Inches(2.4)) -> None:
    """數值表：第一列為條件（深藍底白字），第一欄為項目；分段標題列整列合併；列高依可用高度縮小。"""
    row_h = min(int(row_h), int((TABLE_BOTTOM - y) / (len(rows) + 1)))
    n_cols = len(conditions) + 1
    table = slide.shapes.add_table(len(rows) + 1, n_cols, x, y, w, row_h * (len(rows) + 1)).table
    table.first_row = True
    table.columns[0].width = label_w
    other = int((w - label_w) / max(1, len(conditions)))
    for j in range(1, n_cols):
        table.columns[j].width = other
    for i in range(len(rows) + 1):
        table.rows[i].height = row_h
    # 表頭
    _add_run(_cell_text(table.cell(0, 0), size, WHITE, NAVY), "", size, True, WHITE)
    for j, name in enumerate(conditions, start=1):
        _add_run(_cell_text(table.cell(0, j), size, WHITE, NAVY), name, size, True, WHITE)
    # 內容
    stripe = 0
    for i, row in enumerate(rows, start=1):
        if row.section:
            table.cell(i, 0).merge(table.cell(i, n_cols - 1))
            paragraph = _cell_text(table.cell(i, 0), size, INK, LINE, bold=True)
            _add_run(paragraph, row.label, size, True)
            stripe = 0
            continue
        fill = WHITE if stripe % 2 == 0 else SURFACE
        stripe += 1
        paragraph = _cell_text(table.cell(i, 0), size, INK, fill, bold=True)
        _add_run(paragraph, row.label, size, True)
        if row.label_sub:
            _add_run(paragraph, row.label_sub, size, True, baseline=-25000)
        if row.unit:
            _write_marked(paragraph, " " + row.unit, size - 1, False, MUTED)
        for j, value in enumerate(row.values, start=1):
            _write_value(_cell_text(table.cell(i, j), size, INK, fill), value, size, row.digits)


# ---------- 各頁 ----------
def _cover(prs: Presentation, report: PdReport) -> None:
    """封面：深藍底（同網站登入頁），標題、配方與濃度、條件與代表 pixel、元件結構圖。"""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _background(slide, NAVY)
    _wordmark(slide, MARGIN, Inches(0.45), 22, WHITE)
    _textbox(slide, MARGIN, Inches(1.2), Inches(12), Inches(0.9), report.title, 36, True, WHITE,
             anchor=MSO_ANCHOR.BOTTOM)
    _textbox(slide, MARGIN, Inches(2.15), Inches(6), Inches(0.4), "PD 報告", 16, color=RGBColor(0xC9, 0xD2, 0xE6))
    # 左：配方、濃度、條件
    lines = []
    if report.recipe:
        lines.append(("配方", report.recipe))
    if report.concentration:
        lines.append(("前驅液濃度", report.concentration))
    y = Inches(3.0)
    for label, value in lines:
        _textbox(slide, MARGIN, y, Inches(1.8), Inches(0.4), label, 16, color=RGBColor(0xC9, 0xD2, 0xE6))
        box = _textbox(slide, MARGIN + Inches(1.9), y, Inches(4.8), Inches(0.4), "", 16, True, WHITE)
        paragraph = box.text_frame.paragraphs[0]
        for run in list(paragraph.runs):
            run._r.getparent().remove(run._r)
        formula_text(paragraph, value, 16, True, WHITE)
        y += Inches(0.5)
    y += Inches(0.2)
    _textbox(slide, MARGIN, y, Inches(1.8), Inches(0.4), "條件", 16, color=RGBColor(0xC9, 0xD2, 0xE6))
    for name, pixel in zip(report.conditions, report.pixels):
        _textbox(slide, MARGIN + Inches(1.9), y, Inches(2.6), Inches(0.4), name, 16, True, WHITE)
        _textbox(slide, MARGIN + Inches(4.5), y, Inches(2.0), Inches(0.4), pixel, 14, color=RGBColor(0xC9, 0xD2, 0xE6))
        y += Inches(0.42)
    # 右：元件結構圖（白底框）
    if report.structure_image:
        frame_x, frame_y, frame_w, frame_h = Inches(7.3), Inches(2.9), Inches(5.4), Inches(4.0)
        _rect(slide, frame_x, frame_y, frame_w, frame_h, WHITE)
        _picture(slide, report.structure_image, frame_x + Inches(0.15), frame_y + Inches(0.15),
                 frame_w - Inches(0.3), frame_h - Inches(0.3))
        _textbox(slide, frame_x, frame_y + frame_h + Inches(0.08), frame_w, Inches(0.3), "Device structure", 12,
                 color=RGBColor(0xC9, 0xD2, 0xE6), align=PP_ALIGN.CENTER)


CAPTION_H = Inches(0.3)  # 圖說高度
DSTAR_TABLE_BOTTOM = Inches(6.7)  # 理論、實際 D* 表格的下緣（兩頁相同，表格大小一致）


def _figure_row(slide, plots: list[tuple[str, bytes]], y, h) -> None:
    """一列圖：每張佔相同寬度的格子、等比例縮放置中；圖下方為英文圖說。"""
    content_w = SLIDE_W - 2 * MARGIN
    cell_w = int(content_w / max(1, len(plots)))
    for k, (caption, png) in enumerate(plots):
        x = int(MARGIN + k * cell_w)
        _picture(slide, png, x, y, cell_w - Inches(0.15), h - CAPTION_H)
        _textbox(slide, x, y + h - CAPTION_H, cell_w - Inches(0.15), CAPTION_H, caption, 12, color=MUTED,
                 align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.TOP)


def _dstar_slide(prs: Presentation, title: str, rows: list[TableRow], report: PdReport, page: int) -> None:
    """D* 表的一頁：表格固定從 1.5 in 到 6.7 in（理論、實際兩頁大小相同）。"""
    slide = _content_slide(prs, "e.", title, report, page)
    top = Inches(1.5)
    row_h = int((DSTAR_TABLE_BOTTOM - top) / (len(rows) + 1))
    _table(slide, rows, report.conditions, MARGIN, top, SLIDE_W - 2 * MARGIN, row_h=row_h, size=12,
           label_w=Inches(3.6))


def build_pd_report(report: PdReport) -> bytes:
    """產生 PD 報告 PPTX，回傳檔案內容。"""
    prs = Presentation()
    prs.slide_width, prs.slide_height = SLIDE_W, SLIDE_H
    _cover(prs, report)
    page = 2
    content_w = SLIDE_W - 2 * MARGIN
    if report.dark_plots or report.dark_rows:
        slide = _content_slide(prs, "b.", "暗電流", report, page)
        if report.dark_plots:
            _figure_row(slide, report.dark_plots, Inches(1.4), Inches(3.0))
        if report.dark_rows:
            _table(slide, report.dark_rows, report.conditions, MARGIN, Inches(4.5), content_w, row_h=Inches(0.34),
                   label_w=Inches(3.0))
        page += 1
    if report.spectral_plots or report.r_rows:
        slide = _content_slide(prs, "c.", "EQE、響應度與 D*", report, page)
        if report.spectral_plots:
            _figure_row(slide, report.spectral_plots, Inches(1.45), Inches(3.35))
        if report.r_rows:
            _table(slide, report.r_rows, report.conditions, MARGIN, Inches(5.0), content_w)
        page += 1
    if report.theory_rows:
        _dstar_slide(prs, "理論 D* (based on Thermal + Shot)", report.theory_rows, report, page)
        page += 1
    if report.measured_rows:
        _dstar_slide(prs, "實際 D*", report.measured_rows, report, page)
        page += 1
    if report.noise_plots or report.noise_rows:
        slide = _content_slide(prs, "d.", "Noise", report, page)
        if report.noise_plots:
            _figure_row(slide, report.noise_plots, Inches(1.4), Inches(3.35))
        if report.noise_rows:
            _table(slide, report.noise_rows, report.conditions, MARGIN, Inches(4.9), content_w, row_h=Inches(0.36),
                   label_w=Inches(3.4))
    buffer = BytesIO()
    prs.save(buffer)
    return buffer.getvalue()

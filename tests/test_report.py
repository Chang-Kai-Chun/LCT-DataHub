"""G-5 PD 報告（core/report/pd_report.py）的測試。"""
from io import BytesIO

import pytest
from pptx import Presentation
from pptx.oxml.ns import qn

from lct_datahub.core.report.pd_report import (
    FONT_EAST_ASIA, FONT_LATIN, PdReport, TableRow, build_pd_report, sci_parts,
)

PNG = (  # 1×1 白色 PNG
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00"
    b"\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa75\x81\x84\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [(6.70e12, ("6.70×10", "12")), (0.36, ("0.36", "")), (None, ("", "")), (0.0, ("0", "")),
     (4.59e-11, ("4.59×10", "-11")), (123.0, ("123", ""))],
)
def test_sci_parts(value, expected):
    """科學記號拆成本體與上標指數；−1～2 次方直接寫數字；None 為空白。"""
    assert sci_parts(value) == expected


def _report(**kwargs) -> PdReport:
    """測試用報告（兩個條件）。"""
    values = dict(title="20261114 添加劑：HD", conditions=["ref", "1 mol%"], pixels=["G1-2", "G6-1"],
                  recipe="Cs0.025FA0.475", concentration="1.8M")
    values.update(kwargs)
    return PdReport(**values)


def _texts(slide) -> str:
    """一張投影片的所有文字（含表格）。"""
    parts = []
    for shape in slide.shapes:
        if shape.has_text_frame:
            parts.append(shape.text_frame.text)
        if shape.has_table:
            parts += [cell.text for row in shape.table.rows for cell in row.cells]
    return " ".join(parts)


def test_cover_only_when_no_data():
    """沒有任何資料：只有封面；16:9。"""
    prs = Presentation(BytesIO(build_pd_report(_report())))
    assert len(prs.slides) == 1 and prs.slide_width == 12192000
    text = _texts(prs.slides[0])
    assert "20261114 添加劑：HD" in text and "ref" in text and "G6-1" in text


def test_full_report_slides_tables_and_fonts():
    """完整資料：封面、暗電流、EQE、理論 D*、實際 D*、Noise 共 6 頁；圖下方英文圖說；兩張 D* 表大小相同。"""
    rows = [TableRow("R", [1.2e8, None], "sh", "(Ω)")]
    dstar = [TableRow("0 V", [], section=True), TableRow("實測 D* 最大值", [6.7e12, 8.1e12], unit="(Jones)"),
             TableRow("-0.1 V", [], section=True), TableRow("實測 D* 最大值", [None, None], unit="(Jones)")]
    report = _report(dark_plots=[("Dark J–V (shifted to 0 V)", PNG), ("Dark J–V (as measured)", PNG)],
                     dark_rows=rows, spectral_plots=[("EQE & integrated Jsc", PNG), ("Responsivity", PNG)],
                     r_rows=[TableRow("R @ 530 nm", [0.36, 0.36], unit="(A/W)")], theory_rows=dstar,
                     measured_rows=dstar, noise_plots=[("Noise spectrum, 0 V", PNG)],
                     noise_rows=[TableRow("1 Hz 實測 (0 V)", [1e-12, 2e-12])], structure_image=PNG, footnote="說明")
    prs = Presentation(BytesIO(build_pd_report(report)))
    assert len(prs.slides) == 6
    assert "Device structure" in _texts(prs.slides[0]) and "Dark J–V (as measured)" in _texts(prs.slides[1])
    assert sum(s.shape_type == 13 for s in prs.slides[1].shapes) == 2  # 13 = 圖片：偏移與未偏移兩張
    dark = prs.slides[1]
    table = next(s for s in dark.shapes if s.has_table).table
    assert [c.text for c in table.rows[0].cells] == ["", "ref", "1 mol%"]
    assert table.cell(1, 1).text == "1.20×108" and table.cell(1, 2).text == ""  # 指數為上標（文字相連）
    run = table.cell(1, 1).text_frame.paragraphs[0].runs[0]
    assert run.font.name == FONT_LATIN and run._r.rPr.find(qn("a:ea")).get("typeface") == FONT_EAST_ASIA
    theory, measured = (next(s for s in prs.slides[k].shapes if s.has_table) for k in (3, 4))
    assert "理論 D*" in _texts(prs.slides[3]) and "實際 D*" in _texts(prs.slides[4])
    assert theory.table.cell(1, 0).text == "0 V" and theory.table.cell(4, 1).text == ""
    assert theory.height == measured.height and theory.table.rows[1].height == measured.table.rows[1].height
    assert "Noise" in _texts(prs.slides[5])


def test_slides_skipped_without_data():
    """只有 Noise：封面＋Noise 兩頁。"""
    prs = Presentation(BytesIO(build_pd_report(_report(noise_plots=[("Noise spectrum, 0 V", PNG)]))))
    assert len(prs.slides) == 2 and "Noise" in _texts(prs.slides[1])

"""jv.integrate 與 jv.export 的測試（使用 JV_test_file 內的真實檔案）。"""
from pathlib import Path

import openpyxl
import pytest

from lct_datahub.core.jv.export import PARAM_SHEET_NAMES, SheetName, write_excel
from lct_datahub.core.jv.integrate import (
    all_data,
    curves_frame,
    file_params_frame,
    make_condition,
    missing_samples,
    param_sheet,
)
from lct_datahub.core.jv.reader import list_jv_csv, read_jv_files
from lct_datahub.core.jv.types import Direction, JVParam, TableColumn
from lct_datahub.core.sample_id import SampleId, expand_samples

TEST_DIR = Path(__file__).resolve().parent.parent / "JV_test_file"

pytestmark = pytest.mark.skipif(not TEST_DIR.exists(), reason="沒有 JV_test_file")


@pytest.fixture(scope="module")
def files():
    """讀入全部測試檔（9 個樣品，FW 與 RV 各一）。"""
    return read_jv_files(list_jv_csv(TEST_DIR))


def test_expand_samples():
    """逗號清單、範圍混用，全形逗號可用，重複者只留一個。"""
    got = expand_samples("G1-G3，g2, G7")
    assert [str(s) for s in got] == ["G1", "G2", "G3", "G7"]


def test_curves_frame(files):
    """第一欄電壓，之後每個 Pixel 一欄 J；I10 FW 236 有 3 條曲線，共 4 欄。"""
    jv = next(f for f in files if str(f.name.sample) == "I10" and f.name.direction is Direction.FW)
    frame = curves_frame(jv)
    assert frame.shape == (121, 4)
    assert list(frame.columns) == ["Volt (V)", "I10_FW_2", "I10_FW_3", "I10_FW_6"]
    assert frame["Volt (V)"].iloc[0] == pytest.approx(-0.2)


def test_file_params_frame(files):
    """參數表第一欄 Sample ID，欄位順序為 Voc、Efficiency、FF、Jsc、Rsh。"""
    jv = next(f for f in files if str(f.name.sample) == "I10" and f.name.direction is Direction.FW)
    table = file_params_frame(jv)
    assert list(table.columns) == [
        "Sample ID", "Voc (V)", "Efficiency (%)", "Fill Factor (%)", "Jsc (mA/cm^2)", "Rsh (ohm)",
    ]
    assert table["Sample ID"].tolist() == ["I10_FW_2", "I10_FW_3", "I10_FW_6"]
    assert table["Voc (V)"].iloc[0] == pytest.approx(0.87497)


def test_all_data(files):
    """長表列數＝所有檔案的曲線數總和，且依傳入順序。"""
    table = all_data(files)
    assert len(table) == sum(len(f.curves) for f in files)
    first = table.iloc[0]
    assert first[TableColumn.SAMPLE.value] == "I5"
    assert first[TableColumn.PIXEL.value] == 2
    for p in JVParam:
        assert p.value in table.columns


def test_param_sheet_by_condition(files):
    """條件 A = I5–I7、B = I8–I9，只取 FW；欄長度依條件內曲線數。"""
    conds = [make_condition("A", "I5-I7"), make_condition("B", "I8-I9")]
    sheet = param_sheet(files, conds, JVParam.PCE)
    fw = {str(f.name.sample): f for f in files if f.name.direction is Direction.FW}
    expected_a = sum(len(fw[s].curves) for s in ("I5", "I6", "I7"))
    expected_b = sum(len(fw[s].curves) for s in ("I8", "I9"))
    assert list(sheet.columns) == ["A", "B"]
    assert sheet["A"].notna().sum() == expected_a
    assert sheet["B"].notna().sum() == expected_b
    # I5 FW 的第一個值
    assert sheet["A"].iloc[0] == pytest.approx(fw["I5"].params.iloc[0][JVParam.PCE.value])


def test_param_sheet_directions(files):
    """FW+RV 時資料量為兩倍。"""
    conds = [make_condition("A", "I5-I7")]
    fw = param_sheet(files, conds, JVParam.VOC)["A"].notna().sum()
    both = param_sheet(files, conds, JVParam.VOC, (Direction.FW, Direction.RV))["A"].notna().sum()
    assert both == fw * 2


def test_duplicate_condition_name(files):
    """條件名稱重複時拋出例外。"""
    conds = [make_condition("A", "I5"), make_condition("A", "I6")]
    with pytest.raises(ValueError):
        param_sheet(files, conds, JVParam.VOC)


def test_missing_samples(files):
    """條件中的 I13 沒有檔案，會被列出（FW、RV 各一）。"""
    cond = make_condition("A", "I12-I14")
    gaps = missing_samples(files, [cond], (Direction.FW, Direction.RV))
    assert gaps == [("A", SampleId("I", 13), Direction.FW), ("A", SampleId("I", 13), Direction.RV)]


def _book(files, tmp_path, conditions):
    """寫出 Excel 並用 openpyxl 讀回。"""
    out = tmp_path / "out.xlsx"
    write_excel(out, files, conditions)
    return openpyxl.load_workbook(out)


def test_write_excel_sheets(files, tmp_path):
    """sheet 順序：ALL_Data、五張參數 sheet、每檔一個 sheet（原檔名）。"""
    book = _book(files, tmp_path, [make_condition("A", "I5-I7")])
    names = book.sheetnames
    assert names[0] == SheetName.ALL_DATA.value
    assert names[1 : 1 + len(PARAM_SHEET_NAMES)] == list(PARAM_SHEET_NAMES.values())
    assert len(names) == 1 + len(PARAM_SHEET_NAMES) + len(files)
    assert "I10 FW 236" in names and "I10 RV 236" in names


def test_write_excel_without_conditions(files, tmp_path):
    """沒有條件時不產生參數 sheet。"""
    book = _book(files, tmp_path, None)
    assert len(book.sheetnames) == 1 + len(files)


def test_file_sheet_layout(files, tmp_path):
    """每檔 sheet：上方電壓與 J，空兩列後是 Sample ID 參數表。"""
    ws = _book(files, tmp_path, None)["I10 FW 236"]
    assert [ws.cell(1, c).value for c in range(1, 5)] == ["Volt (V)", "I10_FW_2", "I10_FW_3", "I10_FW_6"]
    assert ws.max_row == 1 + 121 + 2 + 1 + 3
    assert ws.cell(125, 1).value == "Sample ID"
    assert ws.cell(126, 1).value == "I10_FW_2"


def test_all_data_layout(files, tmp_path):
    """ALL_Data：條件各佔一列帶、樣品橫向排列不限 4 個、區塊格式正確。"""
    conds = [make_condition("A", "I5-I9"), make_condition("B", "I10-I12")]  # A 有 5 個樣品
    ws = _book(files, tmp_path, conds)["ALL_Data"]

    # 表頭：5 個區塊，每個 7 欄、間隔一欄
    assert [ws.cell(1, c).value for c in range(1, 8)] == [
        "Sample Name", "Pixel", "Voc (V)", "Efficiency (%)", "Fill Factor (%)", "Jsc (mA/cm^2)", "Rsh (ohm)",
    ]
    assert ws.cell(1, 33).value == "Sample Name"  # 第 5 個區塊起點 = 1 + 4*8
    assert ws.cell(1, 41).value is None  # 沒有第 6 個區塊

    # 條件 A：第 2–6 列 FW、第 7–11 列 RV；第 12 列空白；條件 B 從第 13 列開始
    assert ws["A2"].value == "I5 FW" and ws["A7"].value == "I5 RV"
    assert ws["I2"].value == "I6 FW" and ws["AG2"].value == "I9 FW"
    assert ws["A12"].value is None and ws["A13"].value == "I10 FW" and ws["I13"].value == "I11 FW"
    assert ws["Q13"].value == "I12 FW" and ws["Y13"].value is None  # 條件 B 只有 3 個樣品

    # Pixel 由上而下 6、5、4、3、2；I5 FW 236 沒有 Pixel 4、5
    assert [ws.cell(r, 2).value for r in range(2, 7)] == ["6", "5", "4", "3", "2"]
    assert ws["C2"].value is not None and ws["C3"].value is None and ws["C4"].value is None
    assert ws["C6"].value is not None

    # 合併、置中、粗框
    assert "A2:A6" in {str(r) for r in ws.merged_cells.ranges}
    assert ws["A2"].alignment.horizontal == "center" and ws["A2"].alignment.vertical == "center"
    assert ws["A2"].border.left.style == "thick" and ws["A2"].border.top.style == "thick"
    assert ws["G6"].border.right.style == "thick" and ws["G6"].border.bottom.style == "thick"
    assert ws["D4"].border.left is None or ws["D4"].border.left.style is None  # 區塊內不畫格線
    assert ws.column_dimensions["A"].width == 12


def test_all_data_red_marks_max_efficiency(files, tmp_path):
    """每個區塊只有效率最高的那一格是紅色粗體。"""
    ws = _book(files, tmp_path, [make_condition("A", "I5-I6")])["ALL_Data"]
    jv = next(f for f in files if str(f.name.sample) == "I5" and f.name.direction is Direction.FW)
    best = jv.params[JVParam.PCE.value].idxmax()
    row = 2 + [6, 5, 4, 3, 2].index(best)
    red = [
        c.coordinate
        for r in ws.iter_rows(min_row=2, max_row=6, min_col=1, max_col=7)
        for c in r
        if c.font.bold and c.font.color is not None and c.font.color.rgb.endswith("FF0000")
    ]
    assert red == [f"D{row}"]


def test_all_data_skips_samples_without_files(files, tmp_path):
    """條件中的 I13 沒有檔案，不會產生空白區塊。"""
    ws = _book(files, tmp_path, [make_condition("A", "I12-I14")])["ALL_Data"]
    assert ws["A2"].value == "I12 FW" and ws["I2"].value == "I14 FW" and ws["Q2"].value is None

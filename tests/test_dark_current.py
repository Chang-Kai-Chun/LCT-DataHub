"""B-1 暗電流整合（truncate、pdqe、mingchi、integrate、area、export）的測試。"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from matplotlib.colors import to_hex

from lct_datahub.core.area_check import check_areas
from lct_datahub.core.dark_current.area import apply_dark_area
from lct_datahub.core.dark_current.export import (
    SheetName,
    sheet_names,
    split_by_instrument,
    write_dark_excel,
    write_dark_excels,
)
from lct_datahub.core.dark_current.integrate import (
    dark_areas,
    list_dark_files,
    read_dark_file,
    read_dark_files,
    unique_names,
)
from lct_datahub.core.dark_current.select import curve_names, select_dark_curves
from lct_datahub.core.dark_current.shift import minimum_voltage, shift_curve, shift_curves
from lct_datahub.core.dark_current.truncate import keep_count
from lct_datahub.core.dark_current.types import (
    DarkColumn,
    DarkCurve,
    DarkFailure,
    DarkFileError,
    ShiftMode,
    Instrument,
)
from lct_datahub.core.jv.types import InvalidAreaError
from lct_datahub.core.plotting import figure_to_png, plot_dark_current

TEST_DIR = Path(__file__).resolve().parent.parent / "JD_test_file"
# 檔名可能被改過，所以用內容特徵找檔：PD-QE 是 .txt，明志是 .xls
PDQE = next(iter(TEST_DIR.glob("JD_*.txt")), TEST_DIR / "missing.txt")
MINGCHI = next(iter(TEST_DIR.glob("*.xls")), TEST_DIR / "missing.xls")
needs_files = pytest.mark.skipif(not TEST_DIR.exists(), reason="沒有 JD_test_file")


# ---------- 智慧截取 ----------
def test_keep_count_regular_scan_keeps_all():
    """步距固定的掃描全部保留。"""
    assert keep_count(np.arange(-0.2, 1.0001, 0.01)) == 121


def test_keep_count_cuts_at_backward_jump():
    """電壓突然往回跳：在跳之前截斷。"""
    v = np.concatenate([np.arange(0, 1.0, 0.01), [0.3, 0.31, 0.32]])
    assert keep_count(v) == 100


def test_keep_count_cuts_at_forward_jump():
    """電壓往前跳超過容許值也截斷。"""
    v = np.concatenate([np.arange(0, 0.5, 0.01), [2.0, 2.01]])
    assert keep_count(v) == 50


def test_keep_count_short_input():
    """點數太少不判斷，原樣保留。"""
    assert keep_count(np.array([0.0, 0.1])) == 2


# ---------- PD-QE ----------
@needs_files
def test_pdqe_reads_all_samples():
    """57 個樣品、每條 121 點，單位轉成 A/cm²（原檔 A/mm² 的 100 倍）。"""
    curves = read_dark_file(PDQE)
    assert len(curves) == 57
    first = curves[0]
    assert first.name == "G1-3" and first.instrument is Instrument.PDQE
    assert first.area == pytest.approx(0.045) and first.area_from_file
    assert first.timestamp == "2026-06-23_09-55-31"
    assert len(first.data) == 121
    # 第一點：原檔 J = -4.776733E-8 A/mm² → 4.776733E-6 A/cm²（取絕對值）
    assert first.data[DarkColumn.J.value].iloc[0] == pytest.approx(4.776733e-6)
    assert first.data[DarkColumn.VOLTAGE.value].iloc[0] == pytest.approx(-0.2)
    # 電流 I 保留正負號
    assert first.data[DarkColumn.CURRENT.value].iloc[0] == pytest.approx(-2.14953e-7)


@needs_files
def test_pdqe_density_consistent_with_current_and_area():
    """J（A/cm²）應約等於 |I| ÷ 面積（cm²）。"""
    for c in read_dark_file(PDQE)[:5]:
        d = c.data
        assert (d[DarkColumn.J.value] * c.area / d[DarkColumn.CURRENT.value].abs()).median() == pytest.approx(1, rel=1e-3)


@needs_files
def test_pdqe_ignores_summary_table_and_nan():
    """分隔線之後的彙整表不會混進數據；所有曲線沒有 NaN。"""
    for c in read_dark_file(PDQE):
        assert not c.data.isna().any().any()
        assert c.removed_points == 0


# ---------- 明志 ----------
@needs_files
def test_mingchi_text_xls():
    """副檔名 .xls 的 tab 文字：依內容讀取；樣品名去掉 _abs；面積由 I/J 反推約 0.045。"""
    [c] = read_dark_file(MINGCHI)
    assert c.name == "G1 REF-1_330 K"
    assert c.instrument is Instrument.MINGCHI
    assert c.area == pytest.approx(0.045) and not c.area_from_file
    assert len(c.data) == 121
    assert c.data[DarkColumn.J.value].iloc[0] == pytest.approx(2.36464e-7)


def test_mingchi_comma_csv_and_abs_and_truncate(tmp_path):
    """逗號分隔的 csv：表頭略過、J 取絕對值、尾端異常資料被截掉。"""
    v = list(np.round(np.arange(-0.2, 0.5, 0.01), 2)) + [0.1, 0.11]  # 尾端往回跳
    lines = ["V (V),I (A),abs[J (A/cm^2)]"] + [f"{x},{-x * 1e-6 - 1e-8},{(x * 1e-6 + 1e-8) / 0.045}" for x in v]
    path = tmp_path / "S1_abs.csv"
    path.write_text("\n".join(lines), encoding="utf-8")
    [c] = read_dark_file(path)
    assert c.name == "S1"
    assert len(c.data) == 70 and c.removed_points == 2
    assert (c.data[DarkColumn.J.value] >= 0).all()
    assert c.area == pytest.approx(0.045)


def test_mingchi_garbage_raises(tmp_path):
    """沒有數字數據的檔案：拋出 BAD_FORMAT。"""
    path = tmp_path / "x.txt"
    path.write_text("hello\nworld\n", encoding="utf-8")
    with pytest.raises(DarkFileError) as e:
        read_dark_file(path)
    assert e.value.reason is DarkFailure.BAD_FORMAT


def test_mingchi_too_few_points_raises(tmp_path):
    """有效點數太少：拋出 TOO_FEW_POINTS。"""
    path = tmp_path / "x.txt"
    path.write_text("0\t1e-9\t1e-8\n0.01\t1e-9\t1e-8\n", encoding="utf-8")
    with pytest.raises(DarkFileError) as e:
        read_dark_file(path)
    assert e.value.reason is DarkFailure.TOO_FEW_POINTS


def test_mingchi_real_xlsx(tmp_path):
    """真正的 xlsx（檔名含 _abs）也能讀。"""
    v = np.round(np.arange(-0.2, 0.3, 0.01), 2)
    pd.DataFrame({"V (V)": v, "I (A)": v * 1e-6, "abs[J (A/cm^2)]": v * 1e-6 / 0.05}).to_excel(
        tmp_path / "S2_abs.xlsx", index=False
    )
    [c] = read_dark_file(tmp_path / "S2_abs.xlsx")
    assert c.name == "S2" and len(c.data) == 50 and c.area == pytest.approx(0.05)


# ---------- 整合 ----------
@needs_files
def test_list_dark_files_and_integrate_both_formats():
    """資料夾內兩種格式合併：57 + 1 條曲線。"""
    files = list_dark_files(TEST_DIR)
    assert {f.name for f in files} == {PDQE.name, MINGCHI.name}
    curves = read_dark_files(files)
    assert len(curves) == 58
    assert len({c.name for c in curves}) == 58


def test_list_dark_files_filters(tmp_path):
    """Excel 檔名沒有 _abs、Office 暫存檔、其他副檔名都略過。"""
    for name in ["a_abs.xlsx", "b.xlsx", "~$a_abs.xlsx", "c.txt", "d.dat", "e.csv", "f.jpg"]:
        (tmp_path / name).write_bytes(b"")
    assert [p.name for p in list_dark_files(tmp_path)] == ["a_abs.xlsx", "c.txt", "d.dat", "e.csv"]


def _curve(name: str, source: str = "f.txt", area: float = 0.045) -> DarkCurve:
    """建立測試用曲線。"""
    v = np.arange(0, 0.5, 0.1)
    data = pd.DataFrame(
        {DarkColumn.VOLTAGE.value: v, DarkColumn.CURRENT.value: -(v + 0.1) * 1e-6, DarkColumn.J.value: (v + 0.1) * 1e-6 / area}
    )
    return DarkCurve(name, Instrument.PDQE, source, area, True, None, 0, data)


def test_unique_names():
    """同名加 _2、_3；若 _2 已被占用則繼續遞增。"""
    result = unique_names([_curve("A"), _curve("A"), _curve("A_2"), _curve("A")])
    assert [c.name for c in result] == ["A", "A_2", "A_2_2", "A_3"]


def test_dark_areas_with_check_areas():
    """面積整理後可直接交給 check_areas。"""
    report = check_areas(dark_areas([_curve("A", "f1"), _curve("B", "f1"), _curve("C", "f2", area=0.09)]))
    assert not report.is_uniform and report.values == (0.045, 0.09)
    assert report.files_with(0.09) == ["f2"]


# ---------- 面積 ----------
def test_apply_dark_area_recomputes_j_only():
    """面積加倍：J 減半，I 不變，原資料不被改動。"""
    old = _curve("A")
    [new] = apply_dark_area([old], 0.09)
    assert new.area == 0.09 and not new.area_from_file
    assert (new.data[DarkColumn.J.value] * 2 - old.data[DarkColumn.J.value]).abs().max() < 1e-15
    assert (new.data[DarkColumn.CURRENT.value] == old.data[DarkColumn.CURRENT.value]).all()
    assert old.area == 0.045


@pytest.mark.parametrize("bad", [0, -1, float("nan"), float("inf")])
def test_apply_dark_area_rejects_invalid(bad):
    """面積必須是大於 0 的有限數值。"""
    with pytest.raises(InvalidAreaError):
        apply_dark_area([_curve("A")], bad)


# ---------- Excel ----------
def test_sheet_names_clean_and_unique():
    """不允許字元換成底線、超過 31 字截斷、與 Combined 及彼此不重複。"""
    names = sheet_names([_curve("a/b"), _curve("Combined"), _curve("x" * 40), _curve("x" * 40 + "y")])
    assert names[0] == "a_b"
    assert names[1] == "Combined_2"
    assert all(len(n) <= 31 for n in names) and len({n.lower() for n in names}) == 4


def test_write_dark_excel(tmp_path):
    """第一個 sheet 是 Combined，之後每條曲線一個 sheet。"""
    path = tmp_path / "out.xlsx"
    write_dark_excel(path, [_curve("A"), _curve("B")])
    book = pd.read_excel(path, sheet_name=None)
    assert list(book) == [SheetName.COMBINED.value, "A", "B"]
    assert list(book["Combined"].columns) == ["V_A (V)", "J_A (A/cm²)", "V_B (V)", "J_B (A/cm²)"]
    assert list(book["A"].columns) == [DarkColumn.VOLTAGE.value, DarkColumn.CURRENT.value, DarkColumn.J.value]


def test_write_dark_excels_one_file_per_instrument(tmp_path):
    """兩種儀器各輸出一份；只有一種儀器就只輸出一份。"""
    import dataclasses

    a, b = _curve("A"), dataclasses.replace(_curve("B"), instrument=Instrument.MINGCHI)
    assert list(split_by_instrument([a, b, _curve("C")])) == [Instrument.PDQE, Instrument.MINGCHI]
    paths = write_dark_excels(tmp_path, [a, b, _curve("C")])
    assert [p.name for p in paths] == ["Dark_PD-QE.xlsx", "Dark_明志.xlsx"]
    assert list(pd.read_excel(paths[0], sheet_name=None)) == ["Combined", "A", "C"]
    assert list(pd.read_excel(paths[1], sheet_name=None)) == ["Combined", "B"]
    assert len(write_dark_excels(tmp_path, [a])) == 1


# ---------- B-2 偏移 ----------
def _v_curve(name: str = "S", dip: float = 0.03) -> DarkCurve:
    """建立 |J| 最低點在 dip 的曲線（-0.2～0.5 V，步距 0.01）。"""
    v = np.round(np.arange(-0.2, 0.5, 0.01), 2)
    dens = np.abs(v - dip) * 1e-6 + 1e-9
    data = pd.DataFrame(
        {DarkColumn.VOLTAGE.value: v, DarkColumn.CURRENT.value: (v - dip) * 1e-6 * 0.045, DarkColumn.J.value: dens}
    )
    return DarkCurve(name, Instrument.PDQE, "f.txt", 0.045, True, None, 0, data)


def test_shift_moves_minimum_to_zero_without_touching_i_and_j():
    """偏移：最低點電壓變 0、偏移量記錄正確、I 與 J 完全不變、原始電壓保留。"""
    old = _v_curve(dip=0.03)
    new = shift_curve(old, ShiftMode.SHIFT)
    d = new.data
    assert new.shift == pytest.approx(0.03) and new.is_shifted
    assert d.loc[d[DarkColumn.J.value].idxmin(), DarkColumn.VOLTAGE.value] == 0.0
    assert d[DarkColumn.VOLTAGE.value].iloc[0] == pytest.approx(-0.23)
    assert (d[DarkColumn.J.value] == old.data[DarkColumn.J.value]).all()
    assert (d[DarkColumn.CURRENT.value] == old.data[DarkColumn.CURRENT.value]).all()
    assert (d[DarkColumn.ORIGINAL_VOLTAGE.value] == old.data[DarkColumn.VOLTAGE.value]).all()
    assert DarkColumn.ORIGINAL_VOLTAGE.value not in old.data.columns  # 原本的不變


def test_shift_already_at_zero_is_not_shifted():
    """最低點本來就在 0 V：偏移量 0，不算被偏移（圖上不需註記）。"""
    assert not shift_curve(_v_curve(dip=0.0), ShiftMode.SHIFT).is_shifted


def test_keep_restores_original_and_shift_is_repeatable():
    """保持原始會還原電壓；重複偏移結果相同（不會越偏越遠）。"""
    old = _v_curve(dip=0.03)
    once = shift_curve(old, ShiftMode.SHIFT)
    twice = shift_curve(once, ShiftMode.SHIFT)
    assert twice.shift == pytest.approx(0.03) and twice.data.equals(once.data)
    [kept] = shift_curves([once], ShiftMode.KEEP)
    assert kept.shift == 0.0 and kept.data.equals(old.data)


def test_shift_uses_absolute_value_for_minimum():
    """最低點看 |J|：J 欄是負值時也一樣（統一 |J| 最小值）。"""
    c = _v_curve(dip=0.05)
    c.data[DarkColumn.J.value] = -c.data[DarkColumn.J.value]
    assert minimum_voltage(c) == pytest.approx(0.05)


def test_shifted_excel_has_both_voltages_and_shift_sheet(tmp_path):
    """Excel：偏移後 Combined 同時有原始與偏移後電壓，另有 Shift sheet 記錄偏移量。"""
    path = tmp_path / "s.xlsx"
    write_dark_excel(path, shift_curves([_v_curve("A", 0.03), _v_curve("B", 0.0)], ShiftMode.SHIFT))
    book = pd.read_excel(path, sheet_name=None)
    assert list(book)[:2] == ["Combined", "Shift"]
    assert "Vorig_A (V)" in book["Combined"].columns and "V_A (V)" in book["Combined"].columns
    assert book["Shift"]["Shift (V)"].tolist() == pytest.approx([0.03, 0.0])
    assert DarkColumn.ORIGINAL_VOLTAGE.value in book["A"].columns


@needs_files
def test_shift_on_real_files_keeps_row_counts():
    """真實資料：偏移不改變點數，且每條曲線偏移後 |J| 最低點都在 0 V。"""
    curves = read_dark_files([PDQE, MINGCHI])
    for old, new in zip(curves, shift_curves(curves, ShiftMode.SHIFT)):
        assert len(new.data) == len(old.data)
        d = new.data
        assert d.loc[d[DarkColumn.J.value].abs().idxmin(), DarkColumn.VOLTAGE.value] == 0.0


# ---------- B-3 暗電流圖 ----------
def _notes(fig):
    """取出圖上的 shift 註記文字物件。"""
    return [t for t in fig.axes[0].texts if t.get_text() == "shift"]


def test_select_dark_curves_order_and_missing():
    """依名稱順序挑曲線；找不到的名稱一次列出。"""
    curves = [_curve("A"), _curve("B"), _curve("C")]
    assert curve_names(curves) == ["A", "B", "C"]
    assert [c.name for c in select_dark_curves(curves, ["C", "A"])] == ["C", "A"]
    with pytest.raises(KeyError, match="X"):
        select_dark_curves(curves, ["A", "X"])


def test_plot_dark_current_is_log_with_one_line_per_curve():
    """對數 Y 軸、一條曲線一條線；J 為 0 的點略過而不是報錯。"""
    a = _v_curve("A")
    a.data.loc[3, DarkColumn.J.value] = 0.0
    fig = plot_dark_current([a, _v_curve("B", 0.0)])
    ax = fig.axes[0]
    assert ax.get_yscale() == "log"
    assert len([ln for ln in ax.lines if ln.get_label() in {"A", "B"}]) == 2
    assert ax.get_ylabel() == "|J| (A/cm²)" and ax.get_xlabel() == "Voltage (V)"


def test_shift_note_only_when_shifted_and_styled():
    """偏移過才有 shift 註記；樣式：紅框、黑字、斜體、粗體。"""
    plain = _v_curve("A")
    assert _notes(plot_dark_current([plain])) == []
    # 最低點本來就在 0 V：沒有被偏移，不註記
    assert _notes(plot_dark_current([shift_curve(_v_curve("B", 0.0), ShiftMode.SHIFT)])) == []

    [note] = _notes(plot_dark_current([shift_curve(plain, ShiftMode.SHIFT)]))
    assert note.get_color() == "black"
    assert note.get_fontstyle() == "italic" and note.get_fontweight() == "bold"
    box = note.get_bbox_patch()
    assert to_hex(box.get_edgecolor()) == "#ff0000"
    assert (note.get_horizontalalignment(), note.get_verticalalignment()) == ("right", "top")


def test_plot_dark_current_ranges_validated():
    """範圍：下限須小於上限；Y 軸（對數）下限須大於 0。"""
    with pytest.raises(ValueError):
        plot_dark_current([_curve("A")], y_range=(1e-3, 1e-6))
    with pytest.raises(ValueError):
        plot_dark_current([_curve("A")], y_range=(0, 1))
    with pytest.raises(ValueError):
        plot_dark_current([_curve("A")], x_range=(1, 0))
    ax = plot_dark_current([_curve("A")], y_range=(1e-9, 1e-3), x_range=(-0.1, 0.5)).axes[0]
    assert ax.get_ylim() == pytest.approx((1e-9, 1e-3)) and ax.get_xlim() == pytest.approx((-0.1, 0.5))


def test_plot_dark_current_png_and_empty():
    """可輸出 PNG；沒有曲線也能畫出空圖。"""
    assert figure_to_png(plot_dark_current([_v_curve("A")])).startswith(b"\x89PNG")
    ax = plot_dark_current([]).axes[0]
    assert not ax.get_legend() and len(ax.lines) == 1  # 只剩 0 V 參考線

"""B-1 暗電流整合（truncate、pdqe、mingchi、integrate、area、export）的測試。"""
import dataclasses
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
    is_dark_file,
    list_dark_files,
    read_dark_file,
    read_dark_files,
    unique_names,
)
from lct_datahub.core.dark_current.select import curve_names, device_of, select_dark_curves
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

TEST_DIR = Path(__file__).resolve().parent.parent / "test_for_develop" / "JD_test_file"
# 檔名可能被改過，所以用內容特徵找檔：PD-QE 是 .txt，明志是 .xls
PDQE = next(iter(TEST_DIR.glob("JD_*.txt")), TEST_DIR / "missing.txt")
MINGCHI = next(iter(TEST_DIR.glob("G1 REF*_abs*.xls")), TEST_DIR / "missing.xls")
# 2026-11-19 加入：明志 5 顆 pixel，各有 _abs（畫圖）與未取絕對值（B-4）兩個檔
SIGNED_SAMPLES = ["G1-2", "G6-1", "G10-1", "G11-1", "G14-1"]
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
    """資料夾內兩種格式合併：PD-QE 57 條＋明志 _abs 6 條；未取絕對值的檔不算曲線。"""
    files = list_dark_files(TEST_DIR)
    assert {PDQE.name, MINGCHI.name} <= {f.name for f in files}
    assert all("_abs" in f.name.lower() for f in files if f.suffix == ".xls")
    curves = read_dark_files(files)
    assert len(curves) == 57 + 1 + len(SIGNED_SAMPLES)
    assert len({c.name for c in curves}) == len(curves)


@pytest.mark.parametrize(
    ("name", "expected"),
    [("G6-1_330 K.xls", True), ("a.xlsx", True), ("G6-1_330 K_abs.xls", False), ("~$a.xls", False), ("a.txt", False)],
)
def test_is_signed_file(name, expected):
    """未取絕對值的檔：Excel、檔名沒有 _abs、不是暫存檔。"""
    from lct_datahub.core.dark_current.integrate import accepts_upload, is_signed_file

    assert is_signed_file(name) is expected
    assert accepts_upload(name) is (expected or is_dark_file(name))


def test_pair_key():
    """配對鍵：去掉副檔名與 _abs，不分大小寫、空白統一。"""
    from lct_datahub.core.dark_current.integrate import pair_key

    assert pair_key("G6-1_330 K_abs.xls") == pair_key("g6-1_330  k.XLS") == "g6-1_330 k"
    assert pair_key("G1 REF-1_330 K_abs (明志).xls") == "g1 ref-1_330 k (明志)"


@needs_files
def test_signed_files_attach_to_curves():
    """未取絕對值的檔附到同名 _abs 曲線；G1 REF-1 沒有同名檔。"""
    from lct_datahub.core.dark_current.integrate import list_signed_files, read_dark_files_with_signed

    signed = list_signed_files(TEST_DIR)
    assert len(signed) == len(SIGNED_SAMPLES)
    curves, unpaired = read_dark_files_with_signed(list_dark_files(TEST_DIR) + signed)
    assert unpaired == []
    mingchi = {c.name: c for c in curves if c.instrument is Instrument.MINGCHI}
    assert all(mingchi[f"{s}_330 K"].signed is not None for s in SIGNED_SAMPLES)
    assert mingchi["G1 REF-1_330 K"].signed is None
    assert all(c.signed is None for c in curves if c.instrument is Instrument.PDQE)


def test_only_signed_files_raises(tmp_path):
    """只有未取絕對值的檔、沒有 _abs 曲線檔：拋出 NO_CURVES。"""
    from lct_datahub.core.dark_current.integrate import read_dark_files_with_signed

    v = np.round(np.arange(-0.2, 0.3, 0.01), 2)
    pd.DataFrame({"V": v, "I": v * 1e-6, "J": v * 1e-6 / 0.05}).to_excel(tmp_path / "S2.xlsx", index=False)
    with pytest.raises(DarkFileError) as e:
        read_dark_files_with_signed([tmp_path / "S2.xlsx"])
    assert e.value.reason is DarkFailure.NO_CURVES


def test_unpaired_signed_file_reported(tmp_path):
    """找不到同名 _abs 曲線的未取絕對值檔：列在 unpaired，不影響曲線。"""
    from lct_datahub.core.dark_current.integrate import read_dark_files_with_signed

    v = np.round(np.arange(-0.2, 0.3, 0.01), 2)
    frame = pd.DataFrame({"V": v, "I": v * 1e-6, "J": np.abs(v) * 1e-6 / 0.05})
    frame.to_excel(tmp_path / "S2_abs.xlsx", index=False)
    frame.to_excel(tmp_path / "S3.xlsx", index=False)
    curves, unpaired = read_dark_files_with_signed([tmp_path / "S2_abs.xlsx", tmp_path / "S3.xlsx"])
    assert [c.name for c in curves] == ["S2"] and curves[0].signed is None and unpaired == ["S3.xlsx"]


def test_list_dark_files_filters(tmp_path):
    """Excel 檔名沒有 _abs、Office 暫存檔、其他副檔名都略過。"""
    for name in ["a_abs.xlsx", "b.xlsx", "~$a_abs.xlsx", "c.txt", "d.dat", "e.csv", "f.jpg"]:
        (tmp_path / name).write_bytes(b"")
    assert [p.name for p in list_dark_files(tmp_path)] == ["a_abs.xlsx", "c.txt", "d.dat", "e.csv"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("G1 REF-1_330 K_abs (明志).xls", True),
        ("a_ABS.xlsx", True),  # _abs 不分大小寫
        ("a.xls", False),  # Excel 檔名沒有 _abs 不讀取
        ("a.xlsx", False),
        ("~$a_abs.xlsx", False),  # Office 暫存檔
        ("a.txt", True),  # 文字檔不需要 _abs
        ("a.jpg", False),
    ],
)
def test_is_dark_file(name, expected):
    """資料夾讀取與 API 上傳共用的檔名規則。"""
    assert is_dark_file(name) is expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("G1-3", "G1"),
        ("G10-4", "G10"),
        ("G7-1_second", "G7"),
        ("G1 REF-1_330 K", "G1"),  # 明志：取開頭代號
        ("g01-2", "G1"),  # 正規化：大寫、去前導零
        ("I10", "I10"),
        ("G1x-1", None),  # 代號後緊接字母，不是代號
        ("Sample-1", None),
        ("REF", None),
    ],
)
def test_device_of(name, expected):
    """曲線名稱 → 元件。"""
    device = device_of(name)
    assert (str(device) if device else None) == expected


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
    assert list(book) == [SheetName.COMBINED.value, SheetName.EXTRACT.value, "A", "B"]
    assert list(book["Combined"].columns) == ["V_A (V)", "J_A (A/cm²)", "V_B (V)", "J_B (A/cm²)"]
    assert list(book["A"].columns) == [DarkColumn.VOLTAGE.value, DarkColumn.CURRENT.value, DarkColumn.J.value]


def test_write_dark_excels_one_file_per_instrument(tmp_path):
    """兩種儀器各輸出一份；只有一種儀器就只輸出一份。"""
    import dataclasses

    a, b = _curve("A"), dataclasses.replace(_curve("B"), instrument=Instrument.MINGCHI)
    assert list(split_by_instrument([a, b, _curve("C")])) == [Instrument.PDQE, Instrument.MINGCHI]
    paths = write_dark_excels(tmp_path, [a, b, _curve("C")])
    assert [p.name for p in paths] == ["Dark_PD-QE.xlsx", "Dark_明志.xlsx"]
    assert list(pd.read_excel(paths[0], sheet_name=None)) == ["Combined", "Rsh_Jd", "A", "C"]
    assert list(pd.read_excel(paths[1], sheet_name=None)) == ["Combined", "Rsh_Jd", "B"]
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
    assert list(book)[:3] == ["Combined", "Shift", "Rsh_Jd"]
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


# ---------- B-4 擷取值 ----------
def test_fit_rsh_and_current_at():
    """Rsh 為 ±0.03 V 的最小平方擬合；內插取值；超出範圍為 None。"""
    from lct_datahub.core.dark_current.extract import current_at, fit_rsh

    v = np.round(np.arange(-0.2, 0.5, 0.01), 2)
    i = v / 2e6 + 1e-12 * v**3  # Rsh ≈ 2 MΩ
    assert fit_rsh(v, i) == pytest.approx(2e6, rel=1e-6)
    assert fit_rsh(np.array([0.0, 0.1]), np.array([0.0, 1.0])) is None  # 區間內只有 1 點
    assert current_at(v, i, -0.1) == pytest.approx(-0.1 / 2e6, rel=1e-6)
    assert current_at(v, i, -0.5) is None  # 量測從 -0.2 V 開始


def test_extract_uses_shifted_voltage():
    """有偏移時用偏移後的電壓：0 V 的暗電流＝|J| 最低點；Jd＝Id ÷ 面積。"""
    from lct_datahub.core.dark_current.extract import extract
    from lct_datahub.core.dark_current.types import ExtractBias

    raw = _v_curve("A", 0.03)
    shifted = shift_curves([raw], ShiftMode.SHIFT)[0]
    e_raw, e_shift = extract(raw), extract(shifted)
    assert e_raw.id[ExtractBias.ZERO] == pytest.approx(0.03 * 1e-6 * 0.045)
    assert e_shift.id[ExtractBias.ZERO] == pytest.approx(0.0, abs=1e-15)
    assert e_shift.jd[ExtractBias.NEG_0_1] == pytest.approx(e_shift.id[ExtractBias.NEG_0_1] / 0.045)
    assert e_shift.rsh_area == pytest.approx(e_shift.rsh * 0.045)


@needs_files
def test_extract_matches_pdqe_summary():
    """真實檔：自己算的 Rsh 與 PD-QE 彙整表一致（未偏移＝表上 Rsh；偏移後＝表上 Rs），0 V 電流＝表上 Isc。"""
    from lct_datahub.core.dark_current.extract import extract_all
    from lct_datahub.core.dark_current.types import ExtractBias

    curves = [c for c in read_dark_files([PDQE]) if c.instrument is Instrument.PDQE]
    assert all(c.reference is not None for c in curves)
    for e in extract_all(curves):
        assert e.rsh == pytest.approx(e.reference.rsh, rel=1e-3)
        assert e.id[ExtractBias.ZERO] == pytest.approx(abs(e.reference.isc), rel=1e-3)
    shifted = shift_curves(curves, ShiftMode.SHIFT)
    for e in extract_all(shifted):
        assert e.rsh == pytest.approx(e.reference.rs, rel=1e-3)
        assert e.reference_rsh == (e.reference.rs if e.shift else e.reference.rsh)


# ---------- B-4：明志 _abs 檔的電流正負號（2026-11-19） ----------
def test_restore_sign_and_absolute_detection():
    """V 形的絕對值電流：最低點左側改為負號；有負值或最低點在端點都不算絕對值資料。"""
    from lct_datahub.core.dark_current.extract import fit_rsh, is_absolute_current, restore_sign

    v = np.round(np.arange(-0.1, 0.11, 0.01), 2)
    true_i = (v - 0.02) / 5e8  # Rsh 5×10⁸ Ω，零點在 0.02 V
    assert is_absolute_current(v, np.abs(true_i))
    assert not is_absolute_current(v, true_i)  # 有負值
    assert not is_absolute_current(v, np.abs(v + 0.2))  # 最低點在端點
    restored = restore_sign(v, np.abs(true_i))
    assert np.allclose(restored, true_i)
    assert fit_rsh(v - 0.02, restored) == pytest.approx(5e8, rel=1e-6)


def test_extract_restores_sign_for_absolute_mingchi(tmp_path):
    """明志 _abs 檔沒有同名檔：自動還原正負號，Rsh 為正；來源標示「由絕對值還原」。"""
    from lct_datahub.core.dark_current.extract import extract
    from lct_datahub.core.dark_current.types import CurrentSource

    v = np.round(np.arange(-0.2, 0.31, 0.01), 2)
    i = np.abs(v / 4e8)
    pd.DataFrame({"V": v, "I": i, "J": i / 0.045}).to_excel(tmp_path / "S9_abs.xlsx", index=False)
    [curve] = read_dark_files([tmp_path / "S9_abs.xlsx"])
    e = extract(curve)
    assert e.current_source is CurrentSource.RESTORED and e.rsh == pytest.approx(4e8, rel=1e-6)


@needs_files
def test_extract_uses_signed_file_with_same_shift():
    """有同名未取絕對值的檔：B-4 用它（套用相同偏移）；結果與還原正負號一致，Rsh 皆為正。"""
    from lct_datahub.core.dark_current.extract import extract
    from lct_datahub.core.dark_current.integrate import list_signed_files
    from lct_datahub.core.dark_current.types import CurrentSource, ExtractBias

    curves = read_dark_files(list_dark_files(TEST_DIR) + list_signed_files(TEST_DIR))
    mingchi = {c.name: c for c in curves if c.instrument is Instrument.MINGCHI}
    for sample in SIGNED_SAMPLES:
        for mode in ShiftMode:
            curve = shift_curve(mingchi[f"{sample}_330 K"], mode)
            paired = extract(curve)
            restored = extract(dataclasses.replace(curve, signed=None))
            assert paired.current_source is CurrentSource.SIGNED_FILE
            assert restored.current_source is CurrentSource.RESTORED
            assert paired.rsh > 0 and paired.rsh == pytest.approx(restored.rsh, rel=1e-6)
            for bias in ExtractBias:
                assert paired.id[bias] == pytest.approx(restored.id[bias], rel=1e-6)
    # PD-QE 檔內電流本來就有正負號
    pdqe = next(c for c in curves if c.instrument is Instrument.PDQE)
    assert extract(pdqe).current_source is CurrentSource.FILE
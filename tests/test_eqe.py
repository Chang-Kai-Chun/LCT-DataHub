"""C-1 EQE 整合（pdqe、old、integrate、export）的測試。"""
import io
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import xlrd

from lct_datahub.core.eqe.export import (
    SheetName,
    combined_frame,
    jsc_frame,
    sheet_names,
    split_by_instrument,
    write_eqe_excel,
    write_eqe_excels,
)
from lct_datahub.core.eqe.integrate import (
    list_eqe_files,
    read_eqe_file,
    read_eqe_files,
    rename_curves,
    unique_names,
)
from lct_datahub.core.eqe.old import is_old_grid, parse_old_eqe, sample_count
from lct_datahub.core.eqe.select import curve_names, select_eqe_curves
from lct_datahub.core.plotting import (
    DEFAULT_EQE_RANGE,
    EQE_SINGLE_COLOR,
    JSC_SINGLE_COLOR,
    figure_to_png,
    plot_eqe,
    plot_rplot,
)
from matplotlib.colors import to_hex
from lct_datahub.core.eqe.types import (
    EqeColumn,
    EqeCurve,
    EqeFailure,
    EqeFileError,
    EqeInstrument,
    EqeNameError,
    Spectrum,
)

TEST_DIR = Path(__file__).resolve().parent.parent / "EQE_test_file"
# 檔名可能被改過，所以用副檔名找檔：PD-QE 是 .txt，舊型是 .xls
PDQE = next(iter(TEST_DIR.glob("*.txt")), TEST_DIR / "missing.txt")
OLD = next(iter(TEST_DIR.glob("*.xls")), TEST_DIR / "missing.xls")
needs_files = pytest.mark.skipif(not TEST_DIR.exists(), reason="沒有 EQE_test_file")


# ---------- 新型 PD-QE ----------
@needs_files
def test_pdqe_reads_all_samples():
    """27 個樣品、每個 161 點（300–1100 nm，步距 5）；樣品名與資訊欄正確。"""
    curves = read_eqe_file(PDQE)
    assert len(curves) == 27
    first = curves[0]
    assert first.name == "G1-3" and first.instrument is EqeInstrument.PDQE
    assert first.timestamp == "2026-06-23_10-00-46" and first.bias == 0.0
    d = first.data
    assert len(d) == 161
    assert d[EqeColumn.WAVELENGTH.value].iloc[[0, -1]].tolist() == [300.0, 1100.0]
    assert d[EqeColumn.EQE.value].iloc[0] == pytest.approx(9.746953)
    assert d[EqeColumn.SR.value].iloc[0] == pytest.approx(0.023581)
    assert curves[-1].name == "G15-4"


@needs_files
def test_pdqe_jsc_matches_reported_am15g():
    """積分電流（最後一點）與檔內 AM1.5G 的 Jsc 一致。"""
    for c in read_eqe_file(PDQE):
        assert c.jsc == pytest.approx(c.spectrum_jsc[Spectrum.AM15G], abs=2e-3)
        assert set(c.spectrum_jsc) == set(Spectrum)


@needs_files
def test_pdqe_eqe_consistent_with_sr():
    """EQE (%) ≈ SR × 1240 / 波長 × 100（驗證欄位沒有讀錯位）。"""
    d = read_eqe_file(PDQE)[0].data
    expected = d[EqeColumn.SR.value] * 1240 / d[EqeColumn.WAVELENGTH.value] * 100
    mid = d[EqeColumn.WAVELENGTH.value].between(400, 900)
    assert np.allclose(d.loc[mid, EqeColumn.EQE.value], expected[mid], rtol=2e-2)


# ---------- 舊型 ----------
@needs_files
def test_old_xls_skips_calibration_and_names_samples():
    """舊型 xls：170 欄 = 14 + 12×13，跳過校正檔，得 S1–S13；EQE 乘 100 成 %。"""
    curves = read_eqe_file(OLD)
    assert [c.name for c in curves] == [f"S{i}" for i in range(1, 14)]
    assert all(c.instrument is EqeInstrument.OLD and c.timestamp is None for c in curves)
    d = curves[0].data
    assert len(d) == 161 and d[EqeColumn.WAVELENGTH.value].iloc[0] == 300
    # 檔內第一個樣品（校正檔之後）的 EQE 小數值 0.0278… → 2.78…%
    assert d[EqeColumn.EQE.value].iloc[0] == pytest.approx(2.7835265, rel=1e-5)


@needs_files
def test_old_integrated_current_matches_value_in_file():
    """積分電流（電流 × 步距的累積和）的終點，等於檔內單獨記錄的各樣品 Jsc。"""
    sheet = xlrd.open_workbook(str(OLD), logfile=io.StringIO()).sheet_by_index(0)
    for k, c in enumerate(read_eqe_file(OLD), start=1):
        recorded = sheet.cell_value(1, 12 * k + 13)  # 該組自己的 Jsc 單值（第 1 列）
        # 檔內單值以較高精度計算，與累積值相差約百萬分之幾，容許 1e-4
        assert c.jsc == pytest.approx(recorded, rel=1e-4)


@needs_files
def test_old_detected_by_content_not_extension(tmp_path):
    """儀器依內容判斷：把舊型檔改成別的副檔名仍然讀得到。"""
    renamed = tmp_path / "data.bin"
    renamed.write_bytes(OLD.read_bytes())
    assert len(read_eqe_file(renamed)) == 13


def _old_grid(n_samples: int) -> list[list]:
    """建立舊型表格：表頭 X、Y 交替，校正檔 + n 個樣品，3 個波長點。"""
    ncols = 14 + 12 * n_samples
    grid = [[("X", "Y")[i % 2] for i in range(ncols)]]
    for r, wl in enumerate((300.0, 305.0, 310.0)):
        row = [wl if i % 2 == 0 else 0.0 for i in range(ncols)]
        for k in range(1, n_samples + 1):
            row[12 * k + 5] = 0.1 * k  # SR
            row[12 * k + 9] = 0.5  # EQE 小數
            row[12 * k + 11] = 2.0  # 電流
        grid.append(row)
    return grid


def test_old_parse_synthetic_grid():
    """合成表格：EQE ×100、積分電流 = 電流 × 步距的累積和（步距 5）。"""
    curves = parse_old_eqe(_old_grid(2), "f.xls")
    assert [c.name for c in curves] == ["S1", "S2"]
    d = curves[1].data
    assert d[EqeColumn.EQE.value].tolist() == [50.0, 50.0, 50.0]
    assert d[EqeColumn.SR.value].tolist() == [0.2, 0.2, 0.2]
    assert d[EqeColumn.JSC.value].tolist() == [10.0, 20.0, 30.0]


def test_old_grid_shape_checks():
    """欄數不是 14 + 12n、或表頭不是 X、Y 交替：不是舊型，解析時拋出 BAD_FORMAT。"""
    assert sample_count(14) == 0 and sample_count(170) == 13 and sample_count(15) is None
    bad = _old_grid(1)
    bad[0][3] = "X"
    assert not is_old_grid(bad)
    with pytest.raises(EqeFileError) as e:
        parse_old_eqe(bad, "f.xls")
    assert e.value.reason is EqeFailure.BAD_FORMAT
    with pytest.raises(EqeFileError) as e:
        parse_old_eqe(_old_grid(0), "f.xls")
    assert e.value.reason is EqeFailure.NO_CURVES


def test_old_real_xlsx(tmp_path):
    """真正的 xlsx（舊型版面）也能讀。"""
    grid = _old_grid(2)
    pd.DataFrame(grid[1:], columns=grid[0]).to_excel(tmp_path / "old.xlsx", index=False)
    assert [c.name for c in read_eqe_file(tmp_path / "old.xlsx")] == ["S1", "S2"]


def test_garbage_files_raise(tmp_path):
    """兩種格式都不符的文字檔：拋出 BAD_FORMAT。"""
    path = tmp_path / "x.txt"
    path.write_text("hello\nworld\n", encoding="utf-8")
    with pytest.raises(EqeFileError) as e:
        read_eqe_file(path)
    assert e.value.reason is EqeFailure.BAD_FORMAT


# ---------- 整合 ----------
@needs_files
def test_integrate_both_instruments():
    """資料夾內兩種儀器合併：13 + 27 = 40 條，名稱不重複。"""
    files = list_eqe_files(TEST_DIR)
    assert {f.suffix for f in files} == {".txt", ".xls"}
    curves = read_eqe_files(files)
    assert len(curves) == 40 and len({c.name for c in curves}) == 40


def test_list_eqe_files_filters(tmp_path):
    """只列 txt、xls、xlsx；Office 暫存檔與其他副檔名略過。"""
    for name in ["a.txt", "b.xls", "c.xlsx", "~$c.xlsx", "d.csv", "e.jpg"]:
        (tmp_path / name).write_bytes(b"")
    assert [p.name for p in list_eqe_files(tmp_path)] == ["a.txt", "b.xls", "c.xlsx"]


def _curve(name: str, instrument=EqeInstrument.PDQE, wavelengths=(300.0, 305.0, 310.0)) -> EqeCurve:
    """建立測試用樣品。"""
    w = np.array(wavelengths)
    data = pd.DataFrame(
        {
            EqeColumn.WAVELENGTH.value: w,
            EqeColumn.EQE.value: w / 10,
            EqeColumn.SR.value: w / 1000,
            EqeColumn.JSC.value: np.cumsum(np.ones_like(w)),
        }
    )
    return EqeCurve(name, instrument, "f.txt", data)


def test_unique_names():
    """同名加 _2、_3。"""
    assert [c.name for c in unique_names([_curve("S1"), _curve("S1"), _curve("S1")])] == ["S1", "S1_2", "S1_3"]


def test_rename_curves():
    """改名：對應正確、未提到的不變；原資料不被改動。"""
    old = [_curve("S1"), _curve("S2")]
    new = rename_curves(old, {"S1": " G5-1 "})
    assert [c.name for c in new] == ["G5-1", "S2"] and [c.name for c in old] == ["S1", "S2"]


@pytest.mark.parametrize(
    "mapping",
    [{"S9": "X"}, {"S1": "  "}, {"S1": "S2"}, {"S1": "A", "S2": "A"}],
    ids=["不存在", "空白", "與既有名稱重複", "兩個改成同名"],
)
def test_rename_curves_rejects_bad_names(mapping):
    """舊名不存在、新名空白、改名後重複：拋出 EqeNameError。"""
    with pytest.raises(EqeNameError):
        rename_curves([_curve("S1"), _curve("S2")], mapping)


# ---------- Excel ----------
def test_combined_merges_on_wavelength():
    """Combined：以波長合併，缺的點留空；依波長排序。"""
    frame = combined_frame([_curve("A"), _curve("B", wavelengths=(305.0, 310.0, 315.0))])
    assert list(frame.columns) == ["Lambda (nm)", "EQE_A (%)", "EQE_B (%)"]
    assert frame["Lambda (nm)"].tolist() == [300.0, 305.0, 310.0, 315.0]
    assert frame["EQE_A (%)"].isna().tolist() == [False, False, False, True]
    assert frame["EQE_B (%)"].isna().tolist() == [True, False, False, False]


def test_jsc_frame_and_sheet_names():
    """Jsc 彙整一個樣品一列；sheet 名稱合法化且不與固定名稱重複。"""
    frame = jsc_frame([_curve("A")])
    assert frame["Jsc (mA/cm^2)"].tolist() == [3.0] and "AM1.5G (mA/cm^2)" in frame.columns
    assert sheet_names([_curve("a/b"), _curve("Jsc")]) == ["a_b", "Jsc_2"]


def test_write_excel_and_per_instrument(tmp_path):
    """單一檔案：Combined、Jsc、每樣品一個 sheet；依儀器各輸出一份。"""
    path = tmp_path / "one.xlsx"
    write_eqe_excel(path, [_curve("A"), _curve("B")])
    book = pd.read_excel(path, sheet_name=None)
    assert list(book) == [SheetName.COMBINED.value, SheetName.JSC.value, "A", "B"]
    assert list(book["A"].columns) == [c.value for c in EqeColumn]

    curves = [_curve("A"), _curve("S1", EqeInstrument.OLD)]
    assert list(split_by_instrument(curves)) == [EqeInstrument.PDQE, EqeInstrument.OLD]
    assert [p.name for p in write_eqe_excels(tmp_path, curves)] == ["Eqe_PD-QE.xlsx", "Eqe_Old.xlsx"]
    assert len(write_eqe_excels(tmp_path, curves[:1])) == 1


# ---------- C-2、C-3 曲線挑選與繪圖 ----------
def test_select_eqe_curves():
    """依指定順序挑出；有不存在的名稱拋出 KeyError。"""
    curves = [_curve("A"), _curve("B"), _curve("C")]
    assert curve_names(curves) == ["A", "B", "C"]
    assert [c.name for c in select_eqe_curves(curves, ["C", "A"])] == ["C", "A"]
    with pytest.raises(KeyError):
        select_eqe_curves(curves, ["A", "Z"])


def test_plot_eqe_single_sample_colors():
    """單一樣品：EQE 藍、積分電流紅，右軸存在；EQE 軸預設 0–100，X 軸未輸入時自動。"""
    fig = plot_eqe([_curve("A")])
    ax, ax_jsc = fig.axes
    assert to_hex(ax.lines[0].get_color()) == EQE_SINGLE_COLOR.lower()
    assert to_hex(ax_jsc.lines[0].get_color()) == JSC_SINGLE_COLOR.lower()
    assert ax.get_ylim() == DEFAULT_EQE_RANGE
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["A"]
    assert figure_to_png(fig).startswith(b"\x89PNG")


def test_plot_eqe_multi_sample_styles_and_ranges():
    """多樣品：同樣品同色、積分電流虛線；圖例為樣品名加線型說明，不含 Jsc 數值；範圍套用使用者輸入。"""
    fig = plot_eqe([_curve("A"), _curve("B")], x_range=(350, 1000), jsc_range=(0, 30))
    ax, ax_jsc = fig.axes
    assert [l.get_color() for l in ax.lines[:2]] == [l.get_color() for l in ax_jsc.lines]
    assert all(l.get_linestyle() == "--" for l in ax_jsc.lines)
    assert ax.get_xlim() == (350, 1000) and ax_jsc.get_ylim() == (0, 30)
    texts = [t.get_text() for t in ax.get_legend().get_texts()]
    assert texts == ["A", "B", "EQE", "Integrated Jsc"]


def test_plot_eqe_without_jsc_axis():
    """show_jsc=False：只有一個座標軸。"""
    assert len(plot_eqe([_curve("A")], show_jsc=False).axes) == 1


@pytest.mark.parametrize("kwargs", [{"x_range": (900, 300)}, {"eqe_range": (50, 50)}, {"jsc_range": (10, 0)}])
def test_plot_eqe_rejects_bad_range(kwargs):
    """下限不小於上限時拋出 ValueError。"""
    with pytest.raises(ValueError):
        plot_eqe([_curve("A")], **kwargs)


def test_plot_rplot():
    """R-plot：每樣品一條 SR 曲線、圖例為樣品名；範圍可指定，錯誤範圍拋出 ValueError。"""
    fig = plot_rplot([_curve("A"), _curve("B")], x_range=(300, 310), y_range=(0, 0.5))
    ax = fig.axes[0]
    assert len(ax.lines) == 2 and ax.get_ylim() == (0, 0.5)
    assert np.allclose(ax.lines[0].get_ydata(), [0.3, 0.305, 0.31])
    assert [t.get_text() for t in ax.get_legend().get_texts()] == ["A", "B"]
    with pytest.raises(ValueError):
        plot_rplot([_curve("A")], y_range=(1, 0))

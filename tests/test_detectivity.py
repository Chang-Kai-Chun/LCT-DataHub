"""E 區 D*（core/detectivity：compute、pairing、export，與 plotting.plot_detectivity）的測試。"""
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lct_datahub.core.dark_current.extract import DarkExtract
from lct_datahub.core.dark_current.types import ExtractBias, Instrument
from lct_datahub.core.detectivity.compute import (
    DStarKind, PixelInput, check_wavelengths, compute_pixel, detectivity,
)
from lct_datahub.core.detectivity.export import spectrum_frame, spectrum_sheet_name, summary_frame, write_detectivity_excel
from lct_datahub.core.detectivity.pairing import NOT_USED, SourceKind, pair_pixels, shot_current, to_input
from lct_datahub.core.eqe.types import EqeColumn, EqeCurve, EqeInstrument
from lct_datahub.core.noise.group import build_groups
from lct_datahub.core.noise.reference import shot_noise, thermal_noise
from lct_datahub.core.noise.types import BiasSource, NoiseInstrument, NoiseRecord
from lct_datahub.core.plotting import figure_to_png, plot_detectivity

ROOT = Path(__file__).resolve().parent.parent / "test_for_develop"
EQE_DIR = ROOT / "EQE_test_file"
EXCEL = ROOT / "integrated_file" / "20261114數據計算.xlsx"
PNG_MAGIC = b"\x89PNG"


def _curve(name: str = "G1-2", bias: float | None = -0.1, instrument=EqeInstrument.PDQE) -> EqeCurve:
    """合成 EQE 曲線：300–1100 nm（5 nm），SR 在 700 nm 最高 0.4 A/W。"""
    lam = np.arange(300.0, 1101.0, 5.0)
    sr = 0.4 * np.exp(-(((lam - 700.0) / 200.0) ** 2))
    data = pd.DataFrame({EqeColumn.WAVELENGTH.value: lam, EqeColumn.SR.value: sr,
                         EqeColumn.EQE.value: sr * 1240 / lam * 100})
    return EqeCurve(name=name, instrument=instrument, source="x.txt", data=data, bias=bias)


def _input(**kwargs) -> PixelInput:
    """預設輸入：G1-2、−0.1 V、A 0.045、noise 4.6E-11、Id 8.2E-10、Rsh 2.57E8。"""
    values = dict(pixel="G1-2", bias=-0.1, eqe=_curve(), area=0.045, noise=4.6e-11, noise_bias=-0.1,
                  dark_current=8.2e-10, rsh=2.57e8)
    values.update(kwargs)
    return PixelInput(**values)


def _extract(name: str, instrument=Instrument.MINGCHI, rsh: float = 2.57e8) -> DarkExtract:
    """測試用的 B-4 擷取值（Id：0 V 3E-11、−0.1 V 8.2E-10、−0.5 V 2E-9；最低點 5E-12）。"""
    ids = {ExtractBias.ZERO: 3e-11, ExtractBias.NEG_0_1: 8.2e-10, ExtractBias.NEG_0_5: 2e-9}
    return DarkExtract(name=name, instrument=instrument, area=0.045, shift=0.0, rsh=rsh, jd={}, id=ids, id_min=5e-12)


def _noise_group(sample: str, bias: float, instrument=NoiseInstrument.MINGCHI):
    """測試用的 noise 組（白雜訊 1E-12）。"""
    rng = np.random.default_rng(0)
    current = rng.normal(0, 1e-12 * np.sqrt(100), 2000)
    record = NoiseRecord(source=f"{sample} 1st {bias:g}V.csv", instrument=instrument, sample=sample, bias=bias,
                         bias_source=BiasSource.FILENAME, run=1, time=np.arange(2000) * 0.005, current=current)
    [group] = build_groups([record])
    return group


# ---------- 計算 ----------
def test_detectivity_formula():
    """D* = R√A / i_n；陣列也可；缺值或 i_n ≤ 0 為 None。"""
    assert detectivity(0.3, 0.045, 4.6e-11) == pytest.approx(1.383e9, rel=1e-3)
    assert np.allclose(detectivity(np.array([0.3, 0.6]), 0.045, 1e-12), np.array([0.3, 0.6]) * np.sqrt(0.045) / 1e-12)
    assert detectivity(0.3, 0.045, 0.0) is None and detectivity(0.3, None, 1e-12) is None


def test_check_wavelengths():
    """最多 3 個、大於 0、不重複；回傳排序後的清單。"""
    assert check_wavelengths([700.0, 530.0]) == [530.0, 700.0]
    for bad in ([1.0, 2.0, 3.0, 4.0], [0.0], [530.0, 530.0]):
        with pytest.raises(ValueError):
            check_wavelengths(bad)


def test_compute_pixel_four_kinds():
    """四種雜訊與 D*(λ)；最大值在 700 nm；指定波長內插；理論極限介於 Shot 與 Thermal 之下。"""
    result = compute_pixel(_input())
    combine = np.hypot(shot_noise(8.2e-10), thermal_noise(2.57e8))
    assert result.noises[DStarKind.COMBINE] == pytest.approx(combine)
    peak, at = result.peak(DStarKind.MEASURED)
    assert at == 700.0 and peak == pytest.approx(0.4 * np.sqrt(0.045) / 4.6e-11)
    assert result.at(DStarKind.COMBINE, 700.0) == pytest.approx(0.4 * np.sqrt(0.045) / combine)
    assert result.at(DStarKind.COMBINE, 702.5) is not None and result.at(DStarKind.COMBINE, 2000.0) is None
    assert result.peak(DStarKind.SHOT)[0] > result.peak(DStarKind.COMBINE)[0]
    assert result.warnings == []


def test_compute_without_noise_and_bias_mismatch():
    """沒有 noise：只有理論；noise 偏壓不同：實測不算；EQE 偏壓不同：全部不算；舊型 EQE 沒偏壓照算。"""
    no_noise = compute_pixel(_input(noise=None, noise_bias=None))
    assert no_noise.spectra[DStarKind.MEASURED] is None and no_noise.spectra[DStarKind.COMBINE] is not None
    noise_off = compute_pixel(_input(noise_bias=0.0))
    assert noise_off.spectra[DStarKind.MEASURED] is None and any("Noise 偏壓 0 V" in w for w in noise_off.warnings)
    eqe_off = compute_pixel(_input(eqe=_curve(bias=0.0)))
    assert all(v is None for v in eqe_off.spectra.values()) and any("EQE 偏壓 0 V" in w for w in eqe_off.warnings)
    old = compute_pixel(_input(eqe=_curve(bias=None, instrument=EqeInstrument.OLD)))
    assert old.spectra[DStarKind.MEASURED] is not None and any("舊型" in w for w in old.warnings)
    none = compute_pixel(_input(eqe=None, dark_current=None, rsh=None))
    assert none.peak(DStarKind.COMBINE) is None and len(none.warnings) >= 3


@pytest.mark.skipif(not EXCEL.exists(), reason="沒有整合 Excel")
def test_matches_gino_integrated_excel():
    """Gino 的整合 Excel（REF，0 V）：Thermal、Shot、Combine 的 D* 與 Excel 差異 < 0.1%（只差常數位數）。"""
    import openpyxl

    sheet = openpyxl.load_workbook(EXCEL, data_only=True)["D Total"]
    lam = np.array([sheet.cell(r, 1).value for r in range(4, 165)], dtype=float)
    lam_r = openpyxl.load_workbook(EXCEL, data_only=True)["Thermal"]
    sr = np.array([lam_r.cell(r, 6).value for r in range(2, 163)], dtype=float)
    data = pd.DataFrame({EqeColumn.WAVELENGTH.value: lam, EqeColumn.SR.value: sr, EqeColumn.EQE.value: sr})
    curve = EqeCurve(name="REF", instrument=EqeInstrument.PDQE, source="x", data=data, bias=0.0)
    result = compute_pixel(PixelInput(pixel="REF", bias=0.0, eqe=curve, area=0.045, dark_current=9.99999e-12,
                                      rsh=127365400))
    for kind, column in ((DStarKind.THERMAL, 2), (DStarKind.SHOT, 8), (DStarKind.COMBINE, 14)):
        excel = np.array([sheet.cell(r, column).value for r in range(4, 165)], dtype=float)
        assert np.allclose(result.spectra[kind], excel, rtol=1e-3)
        assert result.peak(kind)[0] == pytest.approx(sheet.cell(3, column).value, rel=1e-3)


# ---------- 配對 ----------
def test_pairing_by_name_and_instrument():
    """名稱取底線前配對；暗電流與 noise 優先同儀器；noise 只取同偏壓；手動指定與不使用。"""
    extracts = [_extract("G6-1", Instrument.PDQE), _extract("G6-1_330 K", Instrument.MINGCHI), _extract("G7-1", Instrument.PDQE)]
    curves = [_curve("G6-1"), _curve("G9-9")]
    groups = [(f"{g.sample} {g.bias:g}V", g) for g in (_noise_group("G6-1", -0.1), _noise_group("G6-1", 0.0))]
    pairs = {p.pixel: p for p in pair_pixels(-0.1, extracts, curves, groups)}
    assert list(pairs) == ["G6-1", "G7-1", "G9-9"]
    g6 = pairs["G6-1"]
    assert g6.dark.name == "G6-1_330 K" and g6.noise_name == "G6-1 -0.1V" and g6.eqe.name == "G6-1"
    assert [c.instrument for c in g6.candidates[SourceKind.DARK]] == ["PD-QE", "明志"]
    assert len(g6.candidates[SourceKind.NOISE]) == 1  # 0 V 的組不列
    assert pairs["G7-1"].eqe is None and pairs["G9-9"].dark is None
    manual = {p.pixel: p for p in pair_pixels(-0.1, extracts, curves, groups,
                                              {"G6-1": {"dark": "G6-1", "noise": NOT_USED}})}["G6-1"]
    assert manual.dark.name == "G6-1" and manual.noise is None and manual.manual == {SourceKind.DARK, SourceKind.NOISE}
    assert manual.chosen_text("dark") == "G6-1 (PD-QE)" and manual.chosen_text("noise") == ""


def test_shot_current_and_input():
    """0 V 用最低點的 |I|，其他偏壓用 B-4 該偏壓；不在 B-4 的偏壓為 None；轉成 D* 輸入。"""
    dark = _extract("G6-1_330 K")
    assert shot_current(dark, 0.0) == 5e-12 and shot_current(dark, -0.1) == 8.2e-10 and shot_current(dark, -0.2) is None
    [pairing] = pair_pixels(-0.1, [dark], [_curve("G6-1")], [("G6-1 -0.1V", _noise_group("G6-1", -0.1))])
    inp = to_input(pairing, -0.1)
    assert inp.area == 0.045 and inp.dark_current == 8.2e-10 and inp.noise_bias == -0.1 and inp.noise > 0


# ---------- Excel 與圖 ----------
def test_excel_and_plot(tmp_path):
    """Summary（最大值、指定波長）、四種 D*(λ)（第一列 Max）；D*(λ) 圖。"""
    extracts = [_extract("G6-1_330 K"), _extract("G7-1", Instrument.PDQE)]
    curves = [_curve("G6-1"), _curve("G7-1")]
    pairings = pair_pixels(-0.1, extracts, curves, [("G6-1 -0.1V", _noise_group("G6-1", -0.1))])
    results = [compute_pixel(to_input(p, -0.1)) for p in pairings]
    summary = summary_frame(results, pairings, [530.0, 700.0])
    assert list(summary["Pixel"]) == ["G6-1", "G7-1"]
    assert summary["D* Measured max at (nm)"][0] == 700.0 and pd.isna(summary["D* Measured max (Jones)"][1])
    assert summary["R @ 700 nm (A/W)"][0] == pytest.approx(0.4)
    measured = spectrum_frame(results, DStarKind.MEASURED)
    assert list(measured.columns) == ["Wavelength (nm)", "G6-1"] and measured.iloc[0, 0] == "Max"
    path = tmp_path / "Dstar.xlsx"
    write_detectivity_excel(path, results, pairings, [700.0])
    book = pd.read_excel(path, sheet_name=None)
    assert list(book) == ["Summary", *[spectrum_sheet_name(k) for k in DStarKind]]
    fig = plot_detectivity(results, DStarKind.COMBINE, [530.0, 700.0])
    assert figure_to_png(fig).startswith(PNG_MAGIC)
    with pytest.raises(ValueError):
        plot_detectivity(results, DStarKind.COMBINE, y_range=(0, 1))

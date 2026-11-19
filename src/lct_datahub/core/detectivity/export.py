"""E 區：D* 寫成 Excel（仿 Gino 的整合 Excel「D Total」，可直接貼到 Origin）。

- Summary：每個 pixel 一列（來源、偏壓、面積、Rsh、Id、四種雜訊、每種 D* 的最大值與波長、指定波長的 R 與 D*、警告）
- D Measured／D Shot+Thermal／D Thermal／D Shot：第一欄波長，每個 pixel 一欄；第一列為 Max
"""
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd

from lct_datahub.core.detectivity.compute import DStarKind, PixelResult
from lct_datahub.core.detectivity.pairing import PixelPairing

WAVELENGTH_COLUMN = "Wavelength (nm)"
MAX_LABEL = "Max"
_DECIMALS = 6  # 合併波長軸時四捨五入的位數


class DStarSheet(Enum):
    """固定的 sheet 名稱。"""

    SUMMARY = "Summary"


def spectrum_sheet_name(kind: DStarKind) -> str:
    """各種 D*(λ) 的 sheet 名稱（Excel 不允許 *，沿用 Gino 原本的「D Combine」命名方式）。"""
    return f"D {kind.value}"


def summary_frame(results: list[PixelResult], pairings: list[PixelPairing], wavelengths: list[float]) -> pd.DataFrame:
    """Summary 表：每個 pixel 一列。"""
    rows = []
    for result, pairing in zip(results, pairings):
        inp = result.input
        row = {
            "Pixel": inp.pixel, "Bias (V)": inp.bias,
            "Dark": pairing.chosen_text("dark"), "EQE": pairing.chosen_text("eqe"), "Noise": pairing.chosen_text("noise"),
            "Area (cm^2)": inp.area, "Rsh (ohm)": inp.rsh, "Id for shot (A)": inp.dark_current,
        }
        for kind in DStarKind:
            row[f"i_n {kind.value} (A/Hz^0.5)"] = result.noises[kind]
        for kind in DStarKind:
            peak = result.peak(kind)
            row[f"D* {kind.value} max (Jones)"] = peak[0] if peak else None
            row[f"D* {kind.value} max at (nm)"] = peak[1] if peak else None
        for wl in wavelengths:
            row[f"R @ {wl:g} nm (A/W)"] = result.r_at(wl)
            for kind in DStarKind:
                row[f"D* {kind.value} @ {wl:g} nm (Jones)"] = result.at(kind, wl)
        row["Warnings"] = "; ".join(result.warnings)
        rows.append(row)
    return pd.DataFrame(rows)


def spectrum_frame(results: list[PixelResult], kind: DStarKind) -> pd.DataFrame:
    """某一種 D*(λ)：波長＋每個 pixel 一欄（波長取聯集），第一列為各欄最大值（Max）。"""
    columns = [
        pd.Series(r.spectra[kind], index=np.round(r.wavelength, _DECIMALS), name=r.input.pixel)
        for r in results if r.spectra.get(kind) is not None
    ]
    if not columns:
        return pd.DataFrame(columns=[WAVELENGTH_COLUMN])
    body = pd.concat(columns, axis=1).sort_index()
    body.index.name = WAVELENGTH_COLUMN
    body = body.reset_index()
    peak = {WAVELENGTH_COLUMN: MAX_LABEL, **{c.name: c.max() for c in columns}}
    return pd.concat([pd.DataFrame([peak]), body], ignore_index=True)


def write_detectivity_excel(path: Path, results: list[PixelResult], pairings: list[PixelPairing],
                            wavelengths: list[float]) -> None:
    """寫出 Excel：Summary＋四種 D*(λ)。"""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary_frame(results, pairings, wavelengths).to_excel(writer, sheet_name=DStarSheet.SUMMARY.value, index=False)
        for kind in DStarKind:
            spectrum_frame(results, kind).to_excel(writer, sheet_name=spectrum_sheet_name(kind), index=False)

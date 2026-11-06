"""C-1：把 EQE 整合結果寫成 Excel（Combined、Jsc 彙整，加每個樣品一個 sheet）。

依儀器各輸出一份檔案（與暗電流相同）；只有一種儀器的資料就只輸出一份。

Combined：第一欄為波長，其後每個樣品一欄 EQE (%)；各樣品波長不同時以波長合併（缺的點留空）。
Jsc：每個樣品一列，記錄積分電流密度，PD-QE 另有檔內以 AM1.5G、AM1.5D、AM0 算出的值。
每個樣品 sheet：波長、EQE、SR、積分電流四欄。
"""
from enum import Enum
from functools import reduce
from pathlib import Path

import pandas as pd

from lct_datahub.core import naming
from lct_datahub.core.eqe.types import EqeColumn, EqeCurve, EqeInstrument, Spectrum

_WAVELENGTH_DECIMALS = 4  # 合併波長時四捨五入的位數，避免浮點誤差使同一波長對不上


class SheetName(Enum):
    """固定的 sheet 名稱。"""

    COMBINED = "Combined"
    JSC = "Jsc"


# 輸出檔名中的儀器代號
FILE_TAG = {EqeInstrument.PDQE: "PD-QE", EqeInstrument.OLD: "Old"}


def combined_frame(curves: list[EqeCurve]) -> pd.DataFrame:
    """Combined 表：波長加每個樣品一欄 EQE (%)，依波長由小到大。"""
    wavelength = EqeColumn.WAVELENGTH.value
    parts = []
    for c in curves:
        part = c.data[[wavelength, EqeColumn.EQE.value]].copy()
        part[wavelength] = part[wavelength].round(_WAVELENGTH_DECIMALS)
        parts.append(part.rename(columns={EqeColumn.EQE.value: f"EQE_{c.name} (%)"}))
    if not parts:
        return pd.DataFrame(columns=[wavelength])
    merged = reduce(lambda a, b: a.merge(b, on=wavelength, how="outer"), parts)
    return merged.sort_values(wavelength).reset_index(drop=True)


def jsc_frame(curves: list[EqeCurve]) -> pd.DataFrame:
    """Jsc 彙整表：每個樣品一列（積分電流密度與 PD-QE 檔內各光譜的值）。"""
    rows = []
    for c in curves:
        row = {"Name": c.name, "Instrument": c.instrument.value, "Source": c.source, EqeColumn.JSC.value: c.jsc}
        for s in Spectrum:
            row[f"{s.value} (mA/cm^2)"] = c.spectrum_jsc.get(s)
        rows.append(row)
    return pd.DataFrame(rows)


def sheet_names(curves: list[EqeCurve]) -> list[str]:
    """各樣品的 sheet 名稱：合法化，且與固定 sheet 名稱及彼此都不重複。"""
    return naming.safe_sheet_names([c.name for c in curves], {s.value for s in SheetName})


def write_eqe_excel(path: Path, curves: list[EqeCurve]) -> None:
    """寫出 Excel：Combined、Jsc，之後每個樣品一個 sheet（以樣品名稱命名）。"""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        combined_frame(curves).to_excel(writer, sheet_name=SheetName.COMBINED.value, index=False)
        jsc_frame(curves).to_excel(writer, sheet_name=SheetName.JSC.value, index=False)
        for name, c in zip(sheet_names(curves), curves):
            c.data.to_excel(writer, sheet_name=name, index=False)


def split_by_instrument(curves: list[EqeCurve]) -> dict[EqeInstrument, list[EqeCurve]]:
    """依儀器分組（保持原順序；沒有資料的儀器不會出現）。"""
    groups: dict[EqeInstrument, list[EqeCurve]] = {}
    for c in curves:
        groups.setdefault(c.instrument, []).append(c)
    return groups


def write_eqe_excels(folder: Path, curves: list[EqeCurve]) -> list[Path]:
    """依儀器各寫一份 Excel 到 folder（檔名 Eqe_<儀器代號>.xlsx），回傳寫出的路徑。"""
    paths = []
    for instrument, group in split_by_instrument(curves).items():
        path = Path(folder) / f"Eqe_{FILE_TAG[instrument]}.xlsx"
        write_eqe_excel(path, group)
        paths.append(path)
    return paths

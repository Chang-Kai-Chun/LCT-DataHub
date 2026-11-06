"""B-1：把暗電流整合結果寫成 Excel（Combined 加每個樣品一個 sheet）。

依儀器各輸出一份檔案（沿用 V5：PD-QE 與明志是兩個獨立流程）；只有一種儀器的資料就只輸出一份。

Combined：每條曲線並排兩欄（V_名稱、J_名稱），長度不同的以空白補齊。
偏移（B-2）過的曲線多放一欄原始電壓（Vorig_名稱），原始與偏移後都保留。
每個樣品 sheet：Volt、I、J 三欄（偏移後多一欄原始電壓）。
有曲線被偏移時，另有 Shift sheet 記錄每條曲線的偏移量。
"""
from enum import Enum
from pathlib import Path

import pandas as pd

from lct_datahub.core import naming
from lct_datahub.core.dark_current.types import DarkColumn, DarkCurve, Instrument


class SheetName(Enum):
    """固定的 sheet 名稱。"""

    COMBINED = "Combined"
    SHIFT = "Shift"


def combined_frame(curves: list[DarkCurve]) -> pd.DataFrame:
    """Combined 表：每條曲線兩欄 V_名稱 (V)、J_名稱 (A/cm²)。"""
    columns = {}
    for c in curves:
        # 偏移過的曲線，原始電壓放在偏移後電壓的左邊
        if DarkColumn.ORIGINAL_VOLTAGE.value in c.data.columns:
            columns[f"Vorig_{c.name} (V)"] = c.data[DarkColumn.ORIGINAL_VOLTAGE.value].reset_index(drop=True)
        columns[f"V_{c.name} (V)"] = c.data[DarkColumn.VOLTAGE.value].reset_index(drop=True)
        columns[f"J_{c.name} (A/cm²)"] = c.data[DarkColumn.J.value].reset_index(drop=True)
    return pd.DataFrame(columns)


def sheet_names(curves: list[DarkCurve]) -> list[str]:
    """各曲線的 sheet 名稱：合法化，且與固定 sheet 名稱及彼此都不重複。"""
    return naming.safe_sheet_names([c.name for c in curves], {s.value for s in SheetName})


def shift_frame(curves: list[DarkCurve]) -> pd.DataFrame:
    """Shift 表：每條曲線的偏移量（V）與 |J| 最低值。"""
    rows = [
        {"Name": c.name, "Shift (V)": c.shift, "Min |J| (A/cm^2)": c.data[DarkColumn.J.value].abs().min()}
        for c in curves
    ]
    return pd.DataFrame(rows, columns=["Name", "Shift (V)", "Min |J| (A/cm^2)"])


def write_dark_excel(path: Path, curves: list[DarkCurve]) -> None:
    """寫出 Excel：Combined、（有偏移才有的）Shift，之後每條曲線一個 sheet（以曲線名稱命名）。"""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        combined_frame(curves).to_excel(writer, sheet_name=SheetName.COMBINED.value, index=False)
        if any(c.is_shifted for c in curves):
            shift_frame(curves).to_excel(writer, sheet_name=SheetName.SHIFT.value, index=False)
        for name, c in zip(sheet_names(curves), curves):
            c.data.to_excel(writer, sheet_name=name, index=False)


def split_by_instrument(curves: list[DarkCurve]) -> dict[Instrument, list[DarkCurve]]:
    """依儀器分組（保持原順序；沒有資料的儀器不會出現）。"""
    groups: dict[Instrument, list[DarkCurve]] = {}
    for c in curves:
        groups.setdefault(c.instrument, []).append(c)
    return groups


def write_dark_excels(folder: Path, curves: list[DarkCurve]) -> list[Path]:
    """依儀器各寫一份 Excel 到 folder（檔名 Dark_<儀器>.xlsx），回傳寫出的路徑。"""
    paths = []
    for instrument, group in split_by_instrument(curves).items():
        path = Path(folder) / f"Dark_{instrument.value}.xlsx"
        write_dark_excel(path, group)
        paths.append(path)
    return paths

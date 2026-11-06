"""讀取 Excel 成「列的清單」（各功能共用）：支援 xlsx（openpyxl）、舊版 xls（xlrd，含沒有 OLE 包裝的原始 BIFF 串流）。

依檔案「內容」（檔頭）判斷格式，不看副檔名。數字為 float，空白為空字串，文字為 str。
"""
import io
from pathlib import Path

import pandas as pd

_ZIP_MAGIC = b"PK"  # 真正的 xlsx
_OLE_MAGIC = bytes.fromhex("D0CF11E0")  # OLE 包裝的 xls
# 儀器輸出的 xls 可能是沒有 OLE 包裝的 BIFF 串流：開頭為 BOF 紀錄（BIFF2～BIFF8 的紀錄代碼）
_BIFF_MAGICS = tuple(bytes.fromhex(h) for h in ("0900", "0902", "0904", "0908"))
_HEAD_BYTES = 8


class ExcelReadError(Exception):
    """檔案是 Excel，但無法讀取時拋出（損毀、加密、不支援的版本等）。"""


def is_excel(path: Path) -> bool:
    """依檔頭判斷是否為 Excel（xlsx、OLE xls、或原始 BIFF 串流）。"""
    with open(path, "rb") as f:
        head = f.read(_HEAD_BYTES)
    return head.startswith((_ZIP_MAGIC, _OLE_MAGIC, *_BIFF_MAGICS))


def read_excel_grid(path: Path) -> list[list]:
    """把 Excel 的第一個工作表讀成列的清單；無法讀取時拋出 ExcelReadError。"""
    path = Path(path)
    try:
        with open(path, "rb") as f:
            is_xlsx = f.read(len(_ZIP_MAGIC)) == _ZIP_MAGIC
        if is_xlsx:
            frame = pd.read_excel(path, header=None, engine="openpyxl")
            return [
                ["" if pd.isna(v) else (float(v) if isinstance(v, (int, float)) else str(v)) for v in row]
                for row in frame.itertuples(index=False)
            ]
        import xlrd  # 只有讀 xls 才需要

        # logfile 吞掉 xlrd 的警告訊息（儀器輸出的舊檔沒有 CODEPAGE 紀錄）
        sheet = xlrd.open_workbook(str(path), logfile=io.StringIO()).sheet_by_index(0)
        return [sheet.row_values(r) for r in range(sheet.nrows)]
    except Exception as e:  # openpyxl、xlrd 的例外種類很多，統一轉成 ExcelReadError
        raise ExcelReadError(f"{type(e).__name__}: {e}") from e

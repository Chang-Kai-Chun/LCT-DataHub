"""B-1：暗電流整合（偵測儀器、讀檔、名稱去重、面積檢查資料）。

只負責讀取與整合；有效面積確認（check_areas）、最低點偏移（B-2）、繪圖（B-3）由呼叫端另外處理。
"""
import dataclasses
from pathlib import Path

from lct_datahub.core import naming
from lct_datahub.core.dark_current.mingchi import (
    ABS_MARK,
    parse_mingchi,
    split_text,
    text_rows_to_array,
)
from lct_datahub.core.dark_current.pdqe import is_pdqe_text, parse_pdqe
from lct_datahub.core.dark_current.types import DarkCurve, DarkFailure, DarkFileError
from lct_datahub.core.excel_read import ExcelReadError, is_excel, read_excel_grid

_SUFFIXES = {".txt", ".csv", ".dat", ".xlsx", ".xls"}
_EXCEL_SUFFIXES = {".xlsx", ".xls"}
_ENCODINGS = ("utf-8-sig", "cp950")  # 先試 utf-8，失敗改 cp950


def list_dark_files(folder: Path) -> list[Path]:
    """列出資料夾內可處理的暗電流檔，依檔名排序。

    支援 txt、csv、dat、xlsx、xls；Excel 副檔名的檔名必須含 '_abs'；Office 暫存檔（~$）略過。
    """
    result = []
    for p in Path(folder).iterdir():
        if p.suffix.lower() not in _SUFFIXES or p.name.startswith("~$"):
            continue
        if p.suffix.lower() in _EXCEL_SUFFIXES and ABS_MARK not in p.name.lower():
            continue
        result.append(p)
    return sorted(result)


def _read_text(path: Path) -> str:
    """讀取文字檔：先 utf-8，失敗改 cp950。"""
    raw = path.read_bytes()
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise DarkFileError(path.name, DarkFailure.BAD_FORMAT, "utf-8 或 cp950 文字", "無法解碼")


def _require_values(values, path: Path):
    """確認有讀到數據列；沒有就拋出 BAD_FORMAT。"""
    if len(values) == 0:
        raise DarkFileError(path.name, DarkFailure.BAD_FORMAT, "電壓、電流、電流密度三欄數字", "找不到數據列")
    return values


def read_dark_file(path: Path) -> list[DarkCurve]:
    """讀取單一暗電流檔，依「內容」判斷儀器（不只看副檔名）；回傳檔內全部曲線。"""
    path = Path(path)

    # 真正的 Excel（明志）：xlsx 或舊版 xls
    if is_excel(path):
        try:
            grid = read_excel_grid(path)
        except ExcelReadError as e:
            raise DarkFileError(path.name, DarkFailure.UNSUPPORTED, "可讀的 Excel 檔", str(e)) from None
        rows = [[str(v) for v in r] for r in grid]
        return [parse_mingchi(_require_values(text_rows_to_array(rows), path), path)]

    text = _read_text(path)
    # PD-QE 只用 tab 分隔；先以 tab 切開判斷是否為 PD-QE
    tab_rows = [line.split("\t") for line in text.splitlines()]
    if is_pdqe_text(tab_rows):
        return parse_pdqe(tab_rows, path.name)
    # 否則視為明志：tab 或逗號分隔的三欄數字
    return [parse_mingchi(_require_values(text_rows_to_array(split_text(text)), path), path)]


def unique_names(curves: list[DarkCurve]) -> list[DarkCurve]:
    """同名曲線依出現順序加 _2、_3…（第一個保持原名）。"""
    names = naming.unique_names([c.name for c in curves])
    return [c if n == c.name else dataclasses.replace(c, name=n) for c, n in zip(curves, names)]


def read_dark_files(paths: list[Path]) -> list[DarkCurve]:
    """讀取多個暗電流檔並整合成一份曲線清單（依檔案順序、檔內順序；同名自動編號）。"""
    curves: list[DarkCurve] = []
    for p in paths:
        curves.extend(read_dark_file(p))
    return unique_names(curves)


def dark_areas(curves: list[DarkCurve]) -> dict[str, list[float]]:
    """整理成 check_areas 需要的格式：來源檔名 → 該檔所有曲線的面積。"""
    result: dict[str, list[float]] = {}
    for c in curves:
        result.setdefault(c.source, []).append(c.area)
    return result

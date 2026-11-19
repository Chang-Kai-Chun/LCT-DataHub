"""B-1：暗電流整合（偵測儀器、讀檔、名稱去重、面積檢查資料）。

只負責讀取與整合；有效面積確認（check_areas）、最低點偏移（B-2）、繪圖（B-3）由呼叫端另外處理。

明志 Excel（2026-11-19）：檔名有 _abs 的是暗電流曲線（畫圖用，電流與 J 都是絕對值）；
同名但沒有 _abs 的是「未取絕對值的檔」，不加入曲線，只附在對應曲線上供 B-4 計算 Rsh 與 Id。
"""
import dataclasses
import re
from pathlib import Path

import pandas as pd

from lct_datahub.core import naming
from lct_datahub.core.dark_current.mingchi import (
    ABS_MARK,
    parse_mingchi,
    split_text,
    text_rows_to_array,
)
from lct_datahub.core.dark_current.pdqe import is_pdqe_text, parse_pdqe
from lct_datahub.core.dark_current.types import DarkColumn, DarkCurve, DarkFailure, DarkFileError
from lct_datahub.core.excel_read import ExcelReadError, is_excel, read_excel_grid

_SUFFIXES = {".txt", ".csv", ".dat", ".xlsx", ".xls"}
_EXCEL_SUFFIXES = {".xlsx", ".xls"}
_ENCODINGS = ("utf-8-sig", "cp950")  # 先試 utf-8，失敗改 cp950
_SPACES = re.compile(r"\s+")


def is_dark_file(name: str) -> bool:
    """判斷檔名是否為暗電流曲線檔（畫圖用；資料夾讀取與 API 上傳共用同一規則）。

    支援 txt、csv、dat、xlsx、xls；Excel 副檔名的檔名必須含 '_abs'（明志）；Office 暫存檔（~$）不算。
    """
    suffix = Path(name).suffix.lower()
    if suffix not in _SUFFIXES or name.startswith("~$"):
        return False
    # Excel 檔名沒有 _abs 的不是曲線檔（可能是未取絕對值的檔，見 is_signed_file）
    return suffix not in _EXCEL_SUFFIXES or ABS_MARK in name.lower()


def is_signed_file(name: str) -> bool:
    """判斷檔名是否為明志「未取絕對值的檔」：Excel 副檔名、檔名沒有 _abs、不是 Office 暫存檔。"""
    suffix = Path(name).suffix.lower()
    return suffix in _EXCEL_SUFFIXES and not name.startswith("~$") and ABS_MARK not in name.lower()


def accepts_upload(name: str) -> bool:
    """API 上傳接受的檔案：暗電流曲線檔或未取絕對值的檔。"""
    return is_dark_file(name) or is_signed_file(name)


def list_dark_files(folder: Path) -> list[Path]:
    """列出資料夾內可處理的暗電流曲線檔（規則見 is_dark_file），依檔名排序。"""
    return sorted(p for p in Path(folder).iterdir() if is_dark_file(p.name))


def list_signed_files(folder: Path) -> list[Path]:
    """列出資料夾內明志未取絕對值的檔（規則見 is_signed_file），依檔名排序。"""
    return sorted(p for p in Path(folder).iterdir() if is_signed_file(p.name))


def pair_key(name: str) -> str:
    """配對用的鍵：檔名去掉副檔名與 '_abs'，不分大小寫、空白統一（G6-1_330 K_abs.xls ↔ G6-1_330 K.xls）。"""
    stem = re.sub(ABS_MARK, "", Path(name).stem, flags=re.IGNORECASE)
    return _SPACES.sub(" ", stem).strip().lower()


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


def attach_signed(curves: list[DarkCurve], signed_paths: list[Path]) -> tuple[list[DarkCurve], list[str]]:
    """把未取絕對值的檔附到同名曲線（依 pair_key 比對來源檔名）；回傳 (曲線, 找不到對應曲線的檔名)。"""
    signed: dict[str, pd.DataFrame] = {}
    names: dict[str, str] = {}
    for p in signed_paths:
        [curve] = read_dark_file(p)  # 明志 Excel 一個檔一條曲線
        columns = [DarkColumn.VOLTAGE.value, DarkColumn.CURRENT.value]
        signed[pair_key(p.name)] = curve.data[columns].reset_index(drop=True)
        names[pair_key(p.name)] = p.name
    used: set[str] = set()
    result = []
    for c in curves:
        key = pair_key(c.source)
        if key in signed:
            used.add(key)
            c = dataclasses.replace(c, signed=signed[key])
        result.append(c)
    return result, [names[k] for k in signed if k not in used]


def read_dark_files_with_signed(paths: list[Path]) -> tuple[list[DarkCurve], list[str]]:
    """讀取多個檔：曲線檔整合成曲線清單（同名自動編號），未取絕對值的檔附到同名曲線。

    回傳 (曲線, 找不到對應曲線的未取絕對值檔名)。只有未取絕對值的檔、沒有曲線檔時拋出 NO_CURVES。
    """
    paths = [Path(p) for p in paths]
    signed_paths = [p for p in paths if is_signed_file(p.name)]
    curve_paths = [p for p in paths if p not in signed_paths]
    if signed_paths and not curve_paths:
        raise DarkFileError(
            signed_paths[0].name, DarkFailure.NO_CURVES, "檔名含 _abs 的暗電流檔", "只有未取絕對值的檔",
        )
    curves: list[DarkCurve] = []
    for p in curve_paths:
        curves.extend(read_dark_file(p))
    return attach_signed(unique_names(curves), signed_paths)


def read_dark_files(paths: list[Path]) -> list[DarkCurve]:
    """讀取多個暗電流檔並整合成一份曲線清單（依檔案順序、檔內順序；同名自動編號；未取絕對值的檔附到同名曲線）。"""
    return read_dark_files_with_signed(paths)[0]


def dark_areas(curves: list[DarkCurve]) -> dict[str, list[float]]:
    """整理成 check_areas 需要的格式：來源檔名 → 該檔所有曲線的面積。"""
    result: dict[str, list[float]] = {}
    for c in curves:
        result.setdefault(c.source, []).append(c.area)
    return result

"""C-1：EQE 整合（偵測儀器、讀檔、名稱去重、改名）。

只負責讀取與整合；繪圖（C-2、C-3）與 Excel 輸出由其他模組處理。
儀器依檔案「內容」判斷，不只看副檔名。
"""
import dataclasses
from pathlib import Path

from lct_datahub.core import naming
from lct_datahub.core.excel_read import ExcelReadError, is_excel, read_excel_grid
from lct_datahub.core.eqe.old import is_old_grid, parse_old_eqe
from lct_datahub.core.eqe.pdqe import is_pdqe_eqe_text, parse_pdqe_eqe
from lct_datahub.core.eqe.types import EqeCurve, EqeFailure, EqeFileError, EqeNameError

_SUFFIXES = {".txt", ".xls", ".xlsx"}
_ENCODINGS = ("utf-8-sig", "cp950")  # 先試 utf-8，失敗改 cp950


def list_eqe_files(folder: Path) -> list[Path]:
    """列出資料夾內可處理的 EQE 檔（txt、xls、xlsx），依檔名排序；Office 暫存檔（~$）略過。"""
    return sorted(
        p for p in Path(folder).iterdir() if p.suffix.lower() in _SUFFIXES and not p.name.startswith("~$")
    )


def _read_text(path: Path) -> str:
    """讀取文字檔：先 utf-8，失敗改 cp950。"""
    raw = path.read_bytes()
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise EqeFileError(path.name, EqeFailure.BAD_FORMAT, "utf-8 或 cp950 文字", "無法解碼")


def read_eqe_file(path: Path) -> list[EqeCurve]:
    """讀取單一 EQE 檔，依內容判斷儀器；回傳檔內全部樣品（舊型已跳過校正檔）。"""
    path = Path(path)
    if is_excel(path):
        try:
            grid = read_excel_grid(path)
        except ExcelReadError as e:
            raise EqeFileError(path.name, EqeFailure.UNSUPPORTED, "可讀的 Excel 檔", str(e)) from None
        if not is_old_grid(grid):
            raise EqeFileError(path.name, EqeFailure.BAD_FORMAT, "舊型 EQE（X、Y 交替表頭，14 + 12n 欄）", "格式不符")
        return parse_old_eqe(grid, path.name)

    rows = [line.split("\t") for line in _read_text(path).splitlines()]
    if is_pdqe_eqe_text(rows):
        return parse_pdqe_eqe(rows, path.name)
    raise EqeFileError(path.name, EqeFailure.BAD_FORMAT, "PD-QE 的 EQE TXT 或舊型 EQE Excel", "兩種格式都不符")


def unique_names(curves: list[EqeCurve]) -> list[EqeCurve]:
    """同名樣品依出現順序加 _2、_3…（第一個保持原名）。"""
    names = naming.unique_names([c.name for c in curves])
    return [c if n == c.name else dataclasses.replace(c, name=n) for c, n in zip(curves, names)]


def read_eqe_files(paths: list[Path]) -> list[EqeCurve]:
    """讀取多個 EQE 檔並整合成一份樣品清單（依檔案順序、檔內順序；同名自動編號）。"""
    curves: list[EqeCurve] = []
    for p in paths:
        curves.extend(read_eqe_file(p))
    return unique_names(curves)


def rename_curves(curves: list[EqeCurve], mapping: dict[str, str]) -> list[EqeCurve]:
    """依 mapping（舊名 → 新名）替樣品改名，用於舊型的 S1、S2… 存檔前命名；回傳新的清單。

    舊名不存在、新名為空白、或改名後有重複，都拋出 EqeNameError（一個都不改）。
    """
    existing = {c.name for c in curves}
    unknown = [old for old in mapping if old not in existing]
    if unknown:
        raise EqeNameError(f"找不到樣品：{unknown}")
    renamed = [dataclasses.replace(c, name=mapping.get(c.name, c.name).strip()) for c in curves]
    if any(not c.name for c in renamed):
        raise EqeNameError("樣品名稱不可為空白")
    names = [c.name for c in renamed]
    duplicated = sorted({n for n in names if names.count(n) > 1})
    if duplicated:
        raise EqeNameError(f"改名後名稱重複：{duplicated}")
    return renamed

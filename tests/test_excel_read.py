"""excel_read（xlsx、舊版 xls 的共用讀取）與暗電流接上舊版 xls 的測試。"""
from pathlib import Path

import pandas as pd
import pytest

from lct_datahub.core.dark_current import integrate as dark_integrate
from lct_datahub.core.dark_current.types import DarkColumn, DarkFailure, DarkFileError
from lct_datahub.core.excel_read import ExcelReadError, is_excel, read_excel_grid

EQE_DIR = Path(__file__).resolve().parent.parent / "EQE_test_file"
OLD_XLS = next(iter(EQE_DIR.glob("*.xls")), EQE_DIR / "missing.xls")
needs_xls = pytest.mark.skipif(not OLD_XLS.exists(), reason="沒有舊型 xls 測試檔")


@needs_xls
def test_read_old_biff_xls():
    """舊版 xls（沒有 OLE 包裝的 BIFF 串流）：依檔頭判斷為 Excel，數字讀成 float、空白為空字串。"""
    assert is_excel(OLD_XLS)
    grid = read_excel_grid(OLD_XLS)
    assert (len(grid), len(grid[0])) == (162, 170)
    assert grid[0][:2] == ["X", "Y"] and grid[1][0] == 300.0 and grid[2][12] == ""


def test_read_xlsx(tmp_path):
    """xlsx：數字 float、空白為空字串、文字為 str。"""
    pd.DataFrame({"a": [1, None], "b": ["x", "y"]}).to_excel(tmp_path / "t.xlsx", index=False, header=False)
    assert is_excel(tmp_path / "t.xlsx")
    assert read_excel_grid(tmp_path / "t.xlsx") == [[1.0, "x"], ["", "y"]]


def test_text_file_is_not_excel_and_broken_excel_raises(tmp_path):
    """純文字不是 Excel；檔頭像 Excel 但內容損毀時拋出 ExcelReadError。"""
    text = tmp_path / "t.xls"
    text.write_text("V (V)\tI (A)\n", encoding="utf-8")
    assert not is_excel(text)
    broken = tmp_path / "b.xls"
    broken.write_bytes(bytes.fromhex("0908") + b"\x00" * 20)
    assert is_excel(broken)
    with pytest.raises(ExcelReadError):
        read_excel_grid(broken)


def test_dark_current_reads_binary_xls_through_shared_reader(tmp_path, monkeypatch):
    """暗電流遇到舊版 xls：走共用讀取器，內容（V、I、abs[J]）整理成明志曲線；讀取失敗轉成 UNSUPPORTED。"""
    grid = [["V (V)", "I (A)", "abs[J (A/cm^2)]"]] + [[round(-0.2 + 0.01 * i, 2), -1e-8 * (i + 1), 2e-7 * (i + 1)] for i in range(30)]
    path = tmp_path / "S3_abs.xls"
    path.write_bytes(b"")
    monkeypatch.setattr(dark_integrate, "is_excel", lambda p: True)
    monkeypatch.setattr(dark_integrate, "read_excel_grid", lambda p: grid)
    [c] = dark_integrate.read_dark_file(path)
    assert c.name == "S3" and len(c.data) == 30 and c.area == pytest.approx(0.05)
    assert c.data[DarkColumn.J.value].iloc[0] == pytest.approx(2e-7)

    def broken(_):
        raise ExcelReadError("壞了")

    monkeypatch.setattr(dark_integrate, "read_excel_grid", broken)
    with pytest.raises(DarkFileError) as e:
        dark_integrate.read_dark_file(path)
    assert e.value.reason is DarkFailure.UNSUPPORTED

"""area_check 的測試（含 JV_test_file 真實檔案）。"""
import dataclasses
from pathlib import Path

import pytest

from lct_datahub.core.area_check import check_areas
from lct_datahub.core.jv.integrate import jv_areas
from lct_datahub.core.jv.reader import list_jv_csv, read_jv_files

TEST_DIR = Path(__file__).resolve().parent.parent / "JV_test_file"


def test_uniform():
    """全部相同：一致，並可取得面積值。"""
    report = check_areas({"a": [0.045, 0.045], "b": [0.045]})
    assert report.is_uniform and report.uniform_value == 0.045


def test_not_uniform():
    """不同檔案面積不同：不一致，並能指出哪些檔案是哪個面積。"""
    report = check_areas({"a": [0.045], "b": [0.1], "c": [0.045]})
    assert not report.is_uniform and report.uniform_value is None
    assert report.values == (0.045, 0.1)
    assert report.files_with(0.045) == ["a", "c"]
    assert report.files_with(0.1) == ["b"]


def test_mixed_inside_one_file():
    """同一檔案內的曲線面積不同，也算不一致。"""
    assert not check_areas({"a": [0.045, 0.09]}).is_uniform


def test_float_noise_ignored():
    """浮點誤差不會被當成不同面積。"""
    assert check_areas({"a": [0.045], "b": [0.045 + 1e-13]}).is_uniform


def test_empty():
    """沒有檔案時視為一致，但沒有面積值。"""
    report = check_areas({})
    assert report.is_uniform and report.uniform_value is None


@pytest.mark.skipif(not TEST_DIR.exists(), reason="沒有 JV_test_file")
def test_real_jv_files():
    """測試檔的面積全為 0.045；把其中一個檔案的面積改掉就會被偵測出來。"""
    files = read_jv_files(list_jv_csv(TEST_DIR))
    report = check_areas(jv_areas(files))
    assert report.is_uniform and report.uniform_value == 0.045

    changed = dataclasses.replace(
        files[0], curves=tuple(dataclasses.replace(c, area=0.1) for c in files[0].curves)
    )
    report = check_areas(jv_areas([changed] + files[1:]))
    assert not report.is_uniform
    assert report.files_with(0.1) == [files[0].name.filename]

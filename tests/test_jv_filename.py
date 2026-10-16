"""jv.filename 的測試（含 JV_test_file 內的真實檔名）。"""
from pathlib import Path

import pytest

from lct_datahub.core.jv.filename import (
    check_curve_count,
    parse_jv_filename,
    parse_jv_filenames,
)
from lct_datahub.core.jv.types import Direction, FailureReason, JVFileError
from lct_datahub.core.sample_id import SampleId

TEST_DIR = Path(__file__).resolve().parent.parent / "JV_test_file"


def test_parse_basic():
    """基本解析：Pixel 順序即測量順序。"""
    r = parse_jv_filename("G1 FW 432.csv")
    assert r.sample == SampleId("G", 1)
    assert r.direction is Direction.FW
    assert r.pixels == (4, 3, 2)


def test_parse_normalizes_sample_and_direction():
    """代號大小寫、前導零與方向大小寫都會正規化。"""
    r = parse_jv_filename("i05 rv 236")
    assert (r.sample, r.direction, r.pixels) == (SampleId("I", 5), Direction.RV, (2, 3, 6))


@pytest.mark.parametrize(
    "name, reason",
    [
        ("G1 432.csv", FailureReason.MISSING_DIRECTION),
        ("G1.csv", FailureReason.MISSING_DIRECTION),
        ("G1 FW.csv", FailureReason.MISSING_PIXELS),
        ("G1 FW 417.csv", FailureReason.INVALID_PIXEL),
        ("G1 FW 4a3.csv", FailureReason.INVALID_PIXEL),
        ("G1 FW 443.csv", FailureReason.INVALID_PIXEL),  # 重複 Pixel
        ("123 FW 43.csv", FailureReason.BAD_FORMAT),
        ("G1 FW 43 x.csv", FailureReason.BAD_FORMAT),
    ],
)
def test_parse_failures(name, reason):
    """各種失敗情況對應到正確的原因。"""
    with pytest.raises(JVFileError) as exc:
        parse_jv_filename(name)
    assert exc.value.reason is reason
    assert exc.value.filename == name


def test_curve_count_mismatch():
    """數字串長度與曲線組數不符。"""
    parsed = parse_jv_filename("G1 FW 432.csv")
    check_curve_count(parsed, 3)  # 相符不拋例外
    with pytest.raises(JVFileError) as exc:
        check_curve_count(parsed, 2)
    assert exc.value.reason is FailureReason.COUNT_MISMATCH
    assert "3" in exc.value.expected and "2" in exc.value.actual


def test_duplicate_same_direction():
    """同一樣品同一方向有兩個檔案：視為重複。"""
    with pytest.raises(JVFileError) as exc:
        parse_jv_filenames(["I14 FW 326.csv", "I14 FW 3265.csv", "I5 FW 234.csv"])
    assert exc.value.reason is FailureReason.DUPLICATE
    assert "I14 FW 326.csv" in exc.value.filename and "I14 FW 3265.csv" in exc.value.filename


def test_duplicate_after_normalization():
    """G1 與 g01 正規化後相同，也算重複。"""
    with pytest.raises(JVFileError):
        parse_jv_filenames(["G1 FW 23.csv", "g01 fw 34.csv"])


def test_fw_and_rv_may_differ():
    """同一樣品的 FW 與 RV 各自解析，Pixel 可不同，不算重複；結果依數字大小排序。"""
    out = parse_jv_filenames(["G10 FW 23", "G2 RV 342", "G2 FW 432"])
    assert [(str(r.sample), r.direction.value) for r in out] == [
        ("G2", "FW"),
        ("G2", "RV"),
        ("G10", "FW"),
    ]


@pytest.mark.skipif(not TEST_DIR.exists(), reason="沒有 JV_test_file")
def test_real_files():
    """JV_test_file 內的 CSV 檔名全部可解析，且無重複。"""
    names = [p.name for p in TEST_DIR.glob("*.csv")]
    assert names
    assert len(parse_jv_filenames(names)) == len(names)

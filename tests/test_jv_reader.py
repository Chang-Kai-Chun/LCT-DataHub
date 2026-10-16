"""jv.reader 的測試（真實檔案＋用 tmp_path 製造的壞檔）。"""
import shutil
from pathlib import Path

import pytest

from lct_datahub.core.jv.reader import list_jv_csv, read_jv_csv, read_jv_files
from lct_datahub.core.jv.types import CurveColumn, FailureReason, JVFileError, JVParam

TEST_DIR = Path(__file__).resolve().parent.parent / "JV_test_file"
SAMPLE = TEST_DIR / "I10 FW 236.csv"

pytestmark = pytest.mark.skipif(not TEST_DIR.exists(), reason="沒有 JV_test_file")


def test_list_ignores_non_csv():
    """只列出 CSV，不含 txt、jpg。"""
    files = list_jv_csv(TEST_DIR)
    assert files and all(p.suffix == ".csv" for p in files)


def test_read_single_file():
    """I10 FW 236：3 條曲線，Pixel 順序為 2、3、6，數值與檔內彙整表一致。"""
    jv = read_jv_csv(SAMPLE)
    assert jv.name.pixels == (2, 3, 6)
    assert [c.pixel for c in jv.curves] == [2, 3, 6]
    assert all(c.area == 0.045 for c in jv.curves)
    # 曲線欄位依表頭辨識；FW 由 -0.2 V 掃到 1 V，步距 0.01 V，共 121 點
    first = jv.curves[0].data
    assert list(first.columns) == [c.value for c in CurveColumn]
    assert len(first) == 121
    assert first[CurveColumn.VOLTAGE.value].iloc[0] == pytest.approx(-0.2)
    assert first[CurveColumn.VOLTAGE.value].iloc[-1] == pytest.approx(1.0)
    # 彙整表第一列（Pixel 2）
    row = jv.params.loc[2]
    assert row[JVParam.VOC.value] == pytest.approx(0.87497)
    assert row[JVParam.PCE.value] == pytest.approx(19.81653)
    assert row[JVParam.FF.value] == pytest.approx(75.95391)
    assert row[JVParam.JSC.value] == pytest.approx(29.8294)
    assert row[JVParam.RSH.value] == pytest.approx(9622.81104)


def test_read_rv_file():
    """RV 檔由 1 V 掃到 -0.2 V。"""
    jv = read_jv_csv(TEST_DIR / "I10 RV 236.csv")
    volts = jv.curves[0].data[CurveColumn.VOLTAGE.value]
    assert volts.iloc[0] == pytest.approx(1.0)
    assert volts.iloc[-1] == pytest.approx(-0.2)


def test_read_all_real_files():
    """全部真實檔案都能讀；曲線數、參數列數與檔名 Pixel 數一致。"""
    out = read_jv_files(list_jv_csv(TEST_DIR))
    assert len(out) == 18
    for jv in out:
        assert len(jv.curves) == len(jv.name.pixels) == len(jv.params)
        assert not jv.params.isna().any().any()


def test_count_mismatch(tmp_path):
    """檔名只有 2 個 Pixel，但檔內有 3 條曲線。"""
    bad = tmp_path / "I10 FW 23.csv"
    shutil.copy(SAMPLE, bad)
    with pytest.raises(JVFileError) as exc:
        read_jv_csv(bad)
    assert exc.value.reason is FailureReason.COUNT_MISMATCH


def test_missing_summary_rows(tmp_path):
    """彙整表少一列：內容無法辨識。"""
    lines = SAMPLE.read_text(encoding="utf-8-sig").splitlines()
    bad = tmp_path / "I10 FW 236.csv"
    bad.write_text("\n".join(lines[:-1]), encoding="utf-8")
    with pytest.raises(JVFileError) as exc:
        read_jv_csv(bad)
    assert exc.value.reason is FailureReason.BAD_CONTENT


def test_missing_separator(tmp_path):
    """沒有分隔列：內容無法辨識。"""
    text = SAMPLE.read_text(encoding="utf-8-sig").replace("==========", "")
    bad = tmp_path / "I10 FW 236.csv"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(JVFileError) as exc:
        read_jv_csv(bad)
    assert exc.value.reason is FailureReason.BAD_CONTENT


def test_missing_column_header(tmp_path):
    """表頭缺少電壓欄：內容無法辨識（證明是依表頭辨識，不是依位置）。"""
    text = SAMPLE.read_text(encoding="utf-8-sig").replace("[Volt (V)]", "[X]")
    bad = tmp_path / "I10 FW 236.csv"
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(JVFileError) as exc:
        read_jv_csv(bad)
    assert exc.value.reason is FailureReason.BAD_CONTENT


def test_batch_duplicate_stops(tmp_path):
    """批次讀取時，同一樣品同一方向有兩個檔案就停止。"""
    a = tmp_path / "I10 FW 236.csv"
    b = tmp_path / "i10 FW 236 .csv"
    shutil.copy(SAMPLE, a)
    shutil.copy(SAMPLE, b)
    with pytest.raises(JVFileError) as exc:
        read_jv_files([a, b])
    assert exc.value.reason is FailureReason.DUPLICATE

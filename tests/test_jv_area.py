"""jv.area（改用指定有效面積並重算）的測試。"""
import math
from pathlib import Path

import pytest

from lct_datahub.core.area_check import check_areas
from lct_datahub.core.jv.area import AREA_OVERRIDE_NOTICE, apply_area
from lct_datahub.core.jv.integrate import jv_areas
from lct_datahub.core.jv.reader import read_jv_csv
from lct_datahub.core.jv.types import CurveColumn, InvalidAreaError, JVParam

TEST_DIR = Path(__file__).resolve().parent.parent / "JV_test_file"
SAMPLE = TEST_DIR / "I10 FW 236.csv"

pytestmark = pytest.mark.skipif(not TEST_DIR.exists(), reason="沒有 JV_test_file")


def test_recompute_when_area_doubles():
    """面積 0.045 → 0.09：J、Jsc、PCE 減半；I、Voc、FF、Rsh 不變；原資料不被改動。"""
    old = read_jv_csv(SAMPLE)
    [new] = apply_area([old], 0.09)

    assert all(c.area == 0.09 for c in new.curves)
    # J = I / 面積，且等於舊 J 的一半
    for c_old, c_new in zip(old.curves, new.curves):
        cur = c_new.data[CurveColumn.CURRENT.value]
        assert (c_new.data[CurveColumn.J.value] - cur / 0.09).abs().max() < 1e-12
        assert (c_new.data[CurveColumn.J.value] * 2 - c_old.data[CurveColumn.J.value]).abs().max() < 1e-6
        assert (c_new.data[CurveColumn.CURRENT.value] == c_old.data[CurveColumn.CURRENT.value]).all()

    for p in (JVParam.JSC, JVParam.PCE):
        assert new.params[p.value].tolist() == pytest.approx((old.params[p.value] / 2).tolist())
    for p in (JVParam.VOC, JVParam.FF, JVParam.RSH):
        assert new.params[p.value].tolist() == old.params[p.value].tolist()

    # 原本的檔案沒有被修改
    assert all(c.area == 0.045 for c in old.curves)
    assert old.params.iloc[0][JVParam.PCE.value] == pytest.approx(19.81653)


def test_jsc_matches_isc_over_area():
    """重算後的 Jsc 應等於彙整表的 Isc ÷ 新面積（對照檔案內的 Isc 驗證公式）。"""
    old = read_jv_csv(SAMPLE)
    isc_first = 1.34232  # I10 FW 236 第一條曲線的 Isc（mA）
    [new] = apply_area([old], 0.1)
    assert new.params.iloc[0][JVParam.JSC.value] == pytest.approx(isc_first / 0.1, rel=1e-4)


def test_mixed_areas_become_uniform():
    """原本面積不同的檔案，套用後面積一致。"""
    a = read_jv_csv(SAMPLE)
    [b] = apply_area([read_jv_csv(TEST_DIR / "I10 RV 236.csv")], 0.09)
    out = apply_area([a, b], 0.06)
    assert check_areas(jv_areas(out)).uniform_value == 0.06
    # 0.045 → 0.06 與 0.09 → 0.06 的 PCE 比例不同，但各自都按自己的舊面積換算
    assert out[0].params.iloc[0][JVParam.PCE.value] == pytest.approx(19.81653 * 0.045 / 0.06)


@pytest.mark.parametrize("bad", [0, -0.1, math.nan, math.inf])
def test_invalid_area(bad):
    """面積需為大於 0 的有限數值。"""
    with pytest.raises(InvalidAreaError):
        apply_area([read_jv_csv(SAMPLE)], bad)


def test_notice_mentions_change():
    """警告文字要明確告知數據將被更動。"""
    assert "數據將被更動" in AREA_OVERRIDE_NOTICE

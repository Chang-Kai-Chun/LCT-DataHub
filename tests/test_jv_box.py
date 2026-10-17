"""jv.box 的測試（使用 JV_test_file 內的真實檔案）。"""
from pathlib import Path

import pytest

from lct_datahub.core.jv.box import apply_ranges, box_data, build_box_table, set_keep
from lct_datahub.core.jv.integrate import make_condition
from lct_datahub.core.jv.reader import list_jv_csv, read_jv_files
from lct_datahub.core.jv.types import (
    BoxColumn,
    Direction,
    DirectionMode,
    JVParam,
    TableColumn,
    ValueRange,
)
from lct_datahub.core.sample_id import parse_sample_id

TEST_DIR = Path(__file__).resolve().parent.parent / "JV_test_file"

pytestmark = pytest.mark.skipif(not TEST_DIR.exists(), reason="沒有 JV_test_file")

KEEP = BoxColumn.KEEP.value
CONDITION = BoxColumn.CONDITION.value


@pytest.fixture(scope="module")
def files():
    """讀入全部測試檔。"""
    return read_jv_files(list_jv_csv(TEST_DIR))


@pytest.fixture
def conds():
    """兩個條件：A = I5–I7、B = I8–I9。"""
    return [make_condition("A", "I5-I7"), make_condition("B", "I8-I9")]


def test_build_modes(files, conds):
    """FW、RV 各自只含該方向；FW＋RV 為兩者之和；Keep 預設全為 True。"""
    fw = build_box_table(files, conds, DirectionMode.FW)
    rv = build_box_table(files, conds, DirectionMode.RV)
    both = build_box_table(files, conds, DirectionMode.BOTH)
    assert set(fw[TableColumn.DIRECTION.value]) == {"FW"}
    assert set(rv[TableColumn.DIRECTION.value]) == {"RV"}
    assert len(both) == len(fw) + len(rv)
    assert fw[KEEP].all()
    assert list(dict.fromkeys(fw[CONDITION])) == ["A", "B"]


def test_per_sample_direction(files, conds):
    """逐樣品：I5 取 RV，其餘未指定的預設 FW。"""
    table = build_box_table(
        files, conds, DirectionMode.PER_SAMPLE, {parse_sample_id("I5"): Direction.RV}
    )
    i5 = table[table[TableColumn.SAMPLE.value] == "I5"]
    i6 = table[table[TableColumn.SAMPLE.value] == "I6"]
    assert set(i5[TableColumn.DIRECTION.value]) == {"RV"}
    assert set(i6[TableColumn.DIRECTION.value]) == {"FW"}


def test_per_sample_requires_map(files, conds):
    """逐樣品模式沒給方向表要報錯。"""
    with pytest.raises(ValueError):
        build_box_table(files, conds, DirectionMode.PER_SAMPLE)


def test_duplicate_condition_names(files):
    """條件名稱重複要報錯。"""
    with pytest.raises(ValueError):
        build_box_table(files, [make_condition("A", "I5"), make_condition("A", "I6")])


def test_apply_ranges(files, conds):
    """PCE 範圍篩選：超出者 Keep 為 False，且不更動原表。"""
    table = build_box_table(files, conds)
    pce = table[JVParam.PCE.value]
    cut = float(pce.median())
    filtered = apply_ranges(table, {JVParam.PCE: ValueRange(minimum=cut)})
    assert filtered[KEEP].tolist() == (pce >= cut).tolist()
    assert table[KEEP].all()


def test_empty_ranges_skip(files, conds):
    """空範圍或兩端皆不限制，等於略過。"""
    table = build_box_table(files, conds)
    assert apply_ranges(table, {}).equals(table)
    assert apply_ranges(table, {JVParam.VOC: ValueRange()}).equals(table)


def test_invalid_ranges(files, conds):
    """最小值大於最大值、或對 Rsh 篩選，都要報錯。"""
    table = build_box_table(files, conds)
    with pytest.raises(ValueError):
        apply_ranges(table, {JVParam.PCE: ValueRange(minimum=10, maximum=1)})
    with pytest.raises(ValueError):
        apply_ranges(table, {JVParam.RSH: ValueRange(minimum=1)})


def test_set_keep_and_box_data(files, conds):
    """手動剔除一列後，該條件的 Box 資料少一個值；不存在的列要報錯。"""
    table = build_box_table(files, conds)
    before = box_data(table, JVParam.PCE)
    edited = set_keep(table, [0], False)
    after = box_data(edited, JVParam.PCE)
    assert list(after.columns) == ["A", "B"]
    assert after["A"].notna().sum() == before["A"].notna().sum() - 1
    assert after["B"].notna().sum() == before["B"].notna().sum()
    with pytest.raises(KeyError):
        set_keep(table, [10_000], False)


def test_filter_then_manual_keep(files, conds):
    """篩選之後再手動把某列改回 True（使用者可推翻篩選結果）。"""
    table = build_box_table(files, conds)
    filtered = apply_ranges(table, {JVParam.PCE: ValueRange(minimum=1e9)})
    assert not filtered[KEEP].any()
    restored = set_keep(filtered, [0], True)
    assert restored[KEEP].sum() == 1

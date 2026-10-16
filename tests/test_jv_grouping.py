"""jv.grouping 的測試。"""
import pytest

from lct_datahub.core.jv.grouping import (
    group_auto,
    group_custom,
    group_even,
    move_sample,
    require_complete,
    start_grouping,
    to_grouping,
)
from lct_datahub.core.jv.types import GroupingError
from lct_datahub.core.sample_id import SampleId, parse_sample_id


def samples(n):
    """G1…Gn。"""
    return [SampleId("G", i) for i in range(1, n + 1)]


def names(conds):
    """方便比對：每個條件轉成 (名稱, [樣品字串])。"""
    return [(c.name, [str(s) for s in c.samples]) for c in conds]


def test_even_divisible():
    """16 個樣品、4 個條件：每組 4 個。"""
    out = group_even(samples(16), ["A", "B", "C", "D"])
    assert [len(c.samples) for c in out] == [4, 4, 4, 4]
    assert names(out)[0] == ("A", ["G1", "G2", "G3", "G4"])
    assert names(out)[3][1][-1] == "G16"


def test_even_remainder_goes_to_first_groups():
    """9 個樣品、4 個條件：3、2、2、2。"""
    out = group_even(samples(9), ["A", "B", "C", "D"])
    assert [len(c.samples) for c in out] == [3, 2, 2, 2]


@pytest.mark.parametrize("bad", [[], ["A", "A"], ["A", " "], ["A"] * 0])
def test_even_invalid_names(bad):
    """沒有條件、名稱重複或空白都不允許。"""
    with pytest.raises(GroupingError):
        group_even(samples(4), bad)


def test_even_more_conditions_than_samples():
    """條件數多於樣品數。"""
    with pytest.raises(GroupingError):
        group_even(samples(2), ["A", "B", "C"])


def test_custom():
    """自訂：範圍與逗號清單。"""
    out = group_custom([("Ref", "G1-G2"), ("New", "G5, G7")])
    assert names(out) == [("Ref", ["G1", "G2"]), ("New", ["G5", "G7"])]


def test_custom_overlap_and_duplicate_name():
    """樣品重複歸組、名稱重複都拋出例外。"""
    with pytest.raises(GroupingError):
        group_custom([("A", "G1-G3"), ("B", "G3")])
    with pytest.raises(GroupingError):
        group_custom([("A", "G1"), ("A", "G2")])


def test_auto():
    """自動：每 4 個一組，餘數放最後一組。"""
    out = group_auto(samples(10))
    assert [c.name for c in out] == ["Group 1", "Group 2", "Group 3"]
    assert [len(c.samples) for c in out] == [4, 4, 2]
    assert [len(c.samples) for c in group_auto(samples(8))] == [4, 4]
    assert [len(c.samples) for c in group_auto(samples(3))] == [3]


def test_auto_empty():
    """沒有樣品不能分組。"""
    with pytest.raises(GroupingError):
        group_auto([])


def test_start_grouping():
    """手動分組開始時，所有樣品都在未分配區，條件框是空的。"""
    g = start_grouping(samples(4), ["A", "B"])
    assert [c.name for c in g.conditions] == ["A", "B"]
    assert all(not c.samples for c in g.conditions)
    assert len(g.unassigned) == 4 and not g.is_complete


def test_move_sample_between_conditions_and_pool():
    """拖進條件、換條件、拖回未分配區；原狀態不變。"""
    g0 = start_grouping(samples(3), ["A", "B"])
    g1 = move_sample(g0, parse_sample_id("G2"), "A")
    g2 = move_sample(g1, parse_sample_id("G2"), "B")
    g3 = move_sample(g2, parse_sample_id("G2"), None)
    assert names(g1.conditions) == [("A", ["G2"]), ("B", [])]
    assert names(g2.conditions) == [("A", []), ("B", ["G2"])]
    assert [str(s) for s in g3.unassigned] == ["G1", "G2", "G3"]
    assert len(g0.unassigned) == 3  # 原狀態不變


def test_move_sample_sorted_by_number():
    """條件內依數字大小排序（G10 在 G2 之後）。"""
    g = start_grouping(samples(10), ["A"])
    for n in (10, 2, 1):
        g = move_sample(g, SampleId("G", n), "A")
    assert names(g.conditions) == [("A", ["G1", "G2", "G10"])]


def test_move_sample_invalid():
    """目標不存在、樣品不在分組中。"""
    g = start_grouping(samples(4), ["A", "B"])
    with pytest.raises(GroupingError):
        move_sample(g, parse_sample_id("G1"), "Z")
    with pytest.raises(GroupingError):
        move_sample(g, parse_sample_id("G9"), "A")


def test_prefill_then_adjust():
    """先平均分配預填，再微調：3、2、2、2 → 把一個樣品拖到別組。"""
    pre = group_even(samples(9), ["A", "B", "C", "D"])
    g = to_grouping(samples(9), pre)
    assert g.is_complete
    g = move_sample(g, parse_sample_id("G1"), "D")
    assert [len(c.samples) for c in g.conditions] == [2, 2, 2, 3]


def test_to_grouping_leftover_and_unknown():
    """沒被分到的樣品進未分配區；條件含不存在的樣品則報錯。"""
    g = to_grouping(samples(4), group_custom([("A", "G1-G2")]))
    assert [str(s) for s in g.unassigned] == ["G3", "G4"]
    with pytest.raises(GroupingError):
        to_grouping(samples(4), group_custom([("A", "G9")]))


def test_require_complete():
    """分配完成才放行；否則列出未分配的樣品。"""
    g = start_grouping(samples(2), ["A"])
    with pytest.raises(GroupingError) as exc:
        require_complete(g)
    assert "G1" in str(exc.value) and "G2" in str(exc.value)
    g = move_sample(move_sample(g, SampleId("G", 1), "A"), SampleId("G", 2), "A")
    assert names(require_complete(g)) == [("A", ["G1", "G2"])]

"""sample_id 的測試。"""
import pytest

from lct_datahub.core.sample_id import (
    InvalidSampleIdError,
    SampleId,
    expand_range,
    parse_sample_id,
    sort_samples,
)


def test_normalize_case_and_leading_zero():
    """字母轉大寫、去前導零。"""
    assert parse_sample_id("g01") == SampleId("G", 1)
    assert str(parse_sample_id("Qwe13")) == "QWE13"


@pytest.mark.parametrize("bad", ["", "1", "G", "abcd1", "G1a", "G-1", "G 1"])
def test_invalid_sample(bad):
    """格式不符會拋出例外。"""
    with pytest.raises(InvalidSampleIdError):
        parse_sample_id(bad)


def test_expand_range():
    """範圍展開。"""
    assert [str(s) for s in expand_range("G1-G4")] == ["G1", "G2", "G3", "G4"]
    assert expand_range("g01-g01") == [SampleId("G", 1)]
    assert expand_range("fat7") == [SampleId("FAT", 7)]


@pytest.mark.parametrize("bad", ["G1-H3", "G4-G1", "G1-G2-G3"])
def test_expand_range_invalid(bad):
    """字母不同、起點大於終點、多段範圍都不允許。"""
    with pytest.raises(InvalidSampleIdError):
        expand_range(bad)


def test_sort_by_number_not_string():
    """G10 要排在 G2 之後。"""
    samples = [parse_sample_id(x) for x in ["G10", "G2", "A3", "G1"]]
    assert [str(s) for s in sort_samples(samples)] == ["A3", "G1", "G2", "G10"]

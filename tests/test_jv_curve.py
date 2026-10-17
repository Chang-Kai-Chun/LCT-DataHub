"""jv.curve 與 plotting 的測試（使用 JV_test_file 內的真實檔案）。"""
from pathlib import Path

import pytest

from lct_datahub.core.jv.box import box_data, build_box_table
from lct_datahub.core.jv.curve import LineStyle, available_samples, select_curves
from lct_datahub.core.jv.integrate import make_condition
from lct_datahub.core.jv.reader import list_jv_csv, read_jv_files
from lct_datahub.core.jv.types import Direction, JVParam
from lct_datahub.core.plotting import figure_to_png, plot_box, plot_jv_curves
from lct_datahub.core.sample_id import parse_sample_id

TEST_DIR = Path(__file__).resolve().parent.parent / "JV_test_file"

pytestmark = pytest.mark.skipif(not TEST_DIR.exists(), reason="沒有 JV_test_file")

PNG_MAGIC = b"\x89PNG"


@pytest.fixture(scope="module")
def files():
    """讀入全部測試檔。"""
    return read_jv_files(list_jv_csv(TEST_DIR))


def test_available_samples_sorted(files):
    """樣品依數字排序（I5…I12、I14），I10 排在 I9 之後。"""
    got = [str(s) for s in available_samples(files)]
    assert got[0] == "I5"
    assert got.index("I9") < got.index("I10")


def test_select_curves_styles(files):
    """FW 實線、RV 虛線；I10 FW 有 3 條曲線、RV 同樣依檔案而定。"""
    i10 = parse_sample_id("I10")
    lines = select_curves(files, [i10], (Direction.RV, Direction.FW))
    assert {l.direction for l in lines} == {Direction.FW, Direction.RV}
    assert all(l.style is LineStyle.SOLID for l in lines if l.direction is Direction.FW)
    assert all(l.style is LineStyle.DASHED for l in lines if l.direction is Direction.RV)
    # FW 排在 RV 前面
    assert lines[0].direction is Direction.FW
    assert [l.pixel for l in lines if l.direction is Direction.FW] == [2, 3, 6]


def test_select_curves_missing_sample(files):
    """沒有檔案的樣品略過，不報錯。"""
    assert select_curves(files, [parse_sample_id("Z99")]) == []


def test_plot_jv_png(files):
    """疊圖可輸出 PNG；Y 軸範圍生效；下限大於上限要報錯。"""
    lines = select_curves(files, available_samples(files)[:2], (Direction.FW, Direction.RV))
    fig = plot_jv_curves(lines, y_range=(-30, 5))
    assert fig.axes[0].get_ylim() == (-30, 5)
    assert figure_to_png(fig).startswith(PNG_MAGIC)
    with pytest.raises(ValueError):
        plot_jv_curves(lines, y_range=(5, -5))


def test_plot_box_png(files):
    """Box 圖可輸出 PNG。"""
    conds = [make_condition("A", "I5-I7"), make_condition("B", "I8-I9")]
    data = box_data(build_box_table(files, conds), JVParam.PCE)
    assert figure_to_png(plot_box(data, JVParam.PCE)).startswith(PNG_MAGIC)


def test_plot_box_y_range(files):
    """Box 圖的 Y 軸範圍生效；下限大於上限要報錯。"""
    conds = [make_condition("A", "I5-I7")]
    data = box_data(build_box_table(files, conds), JVParam.PCE)
    assert plot_box(data, JVParam.PCE, y_range=(8, 24)).axes[0].get_ylim() == (8, 24)
    with pytest.raises(ValueError):
        plot_box(data, JVParam.PCE, y_range=(24, 8))

"""A-3：JV 曲線資料整理（截掉參數表、FW 實線／RV 虛線）；繪圖交給 plotting.py。

曲線資料在 reader 讀檔時已截掉檔底的彙整表，這裡只負責依樣品與方向挑出要畫的曲線。
"""
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

import pandas as pd

from lct_datahub.core.jv.types import CurveColumn, Direction, JVFile
from lct_datahub.core.sample_id import SampleId


class LineStyle(Enum):
    """曲線線型；value 為 matplotlib 的 linestyle 名稱。"""

    SOLID = "solid"
    DASHED = "dashed"


# 方向對應的線型：FW 實線、RV 虛線
DIRECTION_STYLE = {Direction.FW: LineStyle.SOLID, Direction.RV: LineStyle.DASHED}

# Y 軸預設範圍（mA/cm²），與 V5 相同；UI 可調整
DEFAULT_Y_RANGE = (-40.0, 10.0)


@dataclass(frozen=True)
class CurveLine:
    """一條要畫的 JV 曲線。"""

    label: str  # 例如 I5_FW_2
    sample: SampleId
    direction: Direction
    pixel: int
    voltage: pd.Series  # V
    current_density: pd.Series  # mA/cm²
    style: LineStyle


def available_samples(files: list[JVFile]) -> list[SampleId]:
    """檔案中出現的樣品，依數字排序，供 UI 做勾選清單。"""
    return sorted({jv.name.sample for jv in files})


def select_curves(
    files: list[JVFile],
    samples: Iterable[SampleId],
    directions: Iterable[Direction] = (Direction.FW,),
) -> list[CurveLine]:
    """依勾選的樣品與方向挑出曲線；順序為樣品排序、FW 在 RV 之前、再依檔內測量順序。

    勾選的樣品／方向找不到檔案時直接略過（缺檔提示由 integrate.missing_samples 負責）。
    """
    wanted_samples = set(samples)
    wanted_directions = set(directions)
    chosen = [
        jv for jv in files
        if jv.name.sample in wanted_samples and jv.name.direction in wanted_directions
    ]
    direction_order = {Direction.FW: 0, Direction.RV: 1}
    chosen.sort(key=lambda jv: (jv.name.sample, direction_order[jv.name.direction]))

    lines = []
    for jv in chosen:
        for curve in jv.curves:
            lines.append(CurveLine(
                label=f"{jv.name.sample}_{jv.name.direction.value}_{curve.pixel}",
                sample=jv.name.sample,
                direction=jv.name.direction,
                pixel=curve.pixel,
                voltage=curve.data[CurveColumn.VOLTAGE.value].reset_index(drop=True),
                current_density=curve.data[CurveColumn.J.value].reset_index(drop=True),
                style=DIRECTION_STYLE[jv.name.direction],
            ))
    return lines

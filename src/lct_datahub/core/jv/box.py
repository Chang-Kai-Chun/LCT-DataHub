"""A-2：Box 圖的數據篩選與分組（FW、RV、FW+RV）。

流程（只回傳 DataFrame，繪圖在 plotting.py）：
1. build_box_table：依條件與方向選擇，建立 Box 表（每條曲線一列，Keep 預設 True）
2. apply_ranges：數值範圍篩選（可略過），超出範圍的列 Keep 設為 False
3. set_keep：使用者在 True/False map 上手動微調
4. box_data：依條件整理成單一參數表，只含 Keep 為 True 的值，供繪圖
"""
from collections.abc import Iterable, Mapping

import pandas as pd

from lct_datahub.core.jv.integrate import all_data
from lct_datahub.core.jv.types import (
    BOX_FILTER_PARAMS,
    BoxColumn,
    Condition,
    Direction,
    DirectionMode,
    JVFile,
    JVParam,
    TableColumn,
    ValueRange,
)
from lct_datahub.core.sample_id import SampleId


def _wanted_directions(mode: DirectionMode) -> tuple[Direction, ...]:
    """非逐樣品模式下要取用的方向。"""
    if mode is DirectionMode.FW:
        return (Direction.FW,)
    if mode is DirectionMode.RV:
        return (Direction.RV,)
    return (Direction.FW, Direction.RV)


def build_box_table(
    files: list[JVFile],
    conditions: list[Condition],
    mode: DirectionMode = DirectionMode.FW,
    sample_directions: Mapping[SampleId, Direction] | None = None,
) -> pd.DataFrame:
    """建立 Box 表：每條曲線一列，含 Condition、Sample、Direction、Pixel 與五項參數、Keep。

    mode 為 PER_SAMPLE 時，sample_directions 指定各樣品的方向（未列出的樣品預設 FW）。
    不屬於任何條件的樣品不會出現；條件順序即傳入順序；Keep 一律從 True 開始。
    """
    names = [c.name for c in conditions]
    if len(set(names)) != len(names):
        raise ValueError("條件名稱不可重複")
    if mode is DirectionMode.PER_SAMPLE and sample_directions is None:
        raise ValueError("逐樣品選擇需提供 sample_directions")

    table = all_data(files)
    columns = [
        BoxColumn.CONDITION.value,
        TableColumn.SAMPLE.value,
        TableColumn.DIRECTION.value,
        TableColumn.PIXEL.value,
        *[p.value for p in JVParam],
        BoxColumn.KEEP.value,
    ]
    if table.empty:
        return pd.DataFrame(columns=columns)

    parts = []
    for cond in conditions:
        for sample in cond.samples:
            if mode is DirectionMode.PER_SAMPLE:
                directions = (sample_directions.get(sample, Direction.FW),)
            else:
                directions = _wanted_directions(mode)
            is_sample = table[TableColumn.SAMPLE.value] == str(sample)
            in_direction = table[TableColumn.DIRECTION.value].isin([d.value for d in directions])
            part = table[is_sample & in_direction].copy()
            part[BoxColumn.CONDITION.value] = cond.name
            parts.append(part)

    if not parts:
        return pd.DataFrame(columns=columns)
    box = pd.concat(parts, ignore_index=True)
    box[BoxColumn.KEEP.value] = True
    return box[columns]


def apply_ranges(table: pd.DataFrame, ranges: Mapping[JVParam, ValueRange]) -> pd.DataFrame:
    """數值範圍篩選：任一參數超出範圍的列，Keep 設為 False；沒超出者維持原本的 Keep。

    只接受 BOX_FILTER_PARAMS（PCE、Voc、Jsc、FF）；ranges 為空或兩端皆 None 等於略過。
    回傳新的 DataFrame，不更動傳入的表。
    """
    for param, rng in ranges.items():
        if param not in BOX_FILTER_PARAMS:
            raise ValueError(f"{param.value} 不支援範圍篩選")
        if rng.minimum is not None and rng.maximum is not None and rng.minimum > rng.maximum:
            raise ValueError(f"{param.value} 的最小值大於最大值")

    result = table.copy()
    inside = pd.Series(True, index=result.index)
    for param, rng in ranges.items():
        values = result[param.value]
        if rng.minimum is not None:
            inside &= values >= rng.minimum
        if rng.maximum is not None:
            inside &= values <= rng.maximum
    result[BoxColumn.KEEP.value] = result[BoxColumn.KEEP.value] & inside
    return result


def set_keep(table: pd.DataFrame, rows: Iterable[int], keep: bool) -> pd.DataFrame:
    """手動微調：把指定列（Box 表的 index）的 Keep 設為 keep，回傳新的 DataFrame。"""
    rows = list(rows)
    unknown = [r for r in rows if r not in table.index]
    if unknown:
        raise KeyError(f"Box 表沒有這些列：{unknown}")
    result = table.copy()
    result.loc[rows, BoxColumn.KEEP.value] = keep
    return result


def box_data(table: pd.DataFrame, param: JVParam) -> pd.DataFrame:
    """單一參數的 Box 圖資料：每欄一個條件（依 Box 表中的條件順序），只含 Keep 為 True 的值。"""
    kept = table[table[BoxColumn.KEEP.value].astype(bool)]
    order = list(dict.fromkeys(table[BoxColumn.CONDITION.value]))
    columns = {
        name: kept.loc[kept[BoxColumn.CONDITION.value] == name, param.value].reset_index(drop=True)
        for name in order
    }
    # 各欄長度不同時以空值補齊
    return pd.DataFrame(columns)

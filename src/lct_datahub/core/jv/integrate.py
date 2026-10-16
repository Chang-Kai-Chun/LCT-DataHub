"""A-1：JV 數據整合（只回傳 DataFrame；寫 Excel 在 export.py）。

- curves_frame：單一檔案的曲線（供「每檔一個 sheet」使用）
- all_data：全部檔案的長表（每條曲線一列，含五項參數）
- param_sheet：依條件整理的單一參數表（每欄一個條件）
"""
import pandas as pd

from lct_datahub.core.jv.types import (
    ALL_DATA_PARAMS,
    Condition,
    CurveColumn,
    Direction,
    FailureReason,
    JVFile,
    JVFileError,
    JVParam,
    TableColumn,
)
from lct_datahub.core.sample_id import SampleId, expand_samples


def make_condition(name: str, samples_text: str) -> Condition:
    """由名稱與樣品範圍字串建立條件，例如 make_condition('Ref', 'G1-G4')。"""
    name = name.strip()
    if not name:
        raise ValueError("條件名稱不可空白")
    return Condition(name=name, samples=tuple(expand_samples(samples_text)))


VOLT_LABEL = "Volt (V)"  # 每檔 sheet 的電壓欄名
SAMPLE_ID_LABEL = "Sample ID"  # 每檔參數表的第一欄名


def _curve_label(jv: JVFile, pixel: int) -> str:
    """曲線與參數表共用的名稱，例如 I5_FW_2。"""
    return f"{jv.name.sample}_{jv.name.direction.value}_{pixel}"


def curves_frame(jv: JVFile) -> pd.DataFrame:
    """單一檔案的曲線：第一欄電壓，之後每個 Pixel 一欄 J（mA/cm²），欄名如 I5_FW_2。

    同一檔案內各曲線的電壓必須相同；不同時拋出 JVFileError。
    """
    volt = jv.curves[0].data[CurveColumn.VOLTAGE.value].reset_index(drop=True)
    columns = {VOLT_LABEL: volt}
    for curve in jv.curves:
        v = curve.data[CurveColumn.VOLTAGE.value].reset_index(drop=True)
        if len(v) != len(volt) or (v - volt).abs().max() > 1e-9:
            raise JVFileError(
                jv.name.filename,
                FailureReason.BAD_CONTENT,
                "同一檔案各曲線的電壓相同",
                f"Pixel {curve.pixel} 的電壓不同",
            )
        columns[_curve_label(jv, curve.pixel)] = curve.data[CurveColumn.J.value].reset_index(drop=True)
    return pd.DataFrame(columns)


def file_params_frame(jv: JVFile) -> pd.DataFrame:
    """單一檔案的參數表：第一欄 Sample ID（如 I5_FW_2），之後依 ALL_DATA_PARAMS 的順序。"""
    table = jv.params[[p.value for p in ALL_DATA_PARAMS]].copy()
    table.insert(0, SAMPLE_ID_LABEL, [_curve_label(jv, px) for px in table.index])
    return table.reset_index(drop=True)


def all_data(files: list[JVFile]) -> pd.DataFrame:
    """全部檔案的長表：每條曲線一列；列順序依傳入的檔案順序與檔內測量順序。"""
    rows = []
    for jv in files:
        # params 的列順序與 curves 相同，逐條配對
        for curve, (_, values) in zip(jv.curves, jv.params.iterrows()):
            row = {
                TableColumn.SAMPLE.value: str(jv.name.sample),
                TableColumn.DIRECTION.value: jv.name.direction.value,
                TableColumn.PIXEL.value: curve.pixel,
                TableColumn.AREA.value: curve.area,
                TableColumn.TIMESTAMP.value: curve.timestamp,
            }
            row.update({p.value: values[p.value] for p in JVParam})
            rows.append(row)
    return pd.DataFrame(rows)


def param_sheet(
    files: list[JVFile],
    conditions: list[Condition],
    param: JVParam,
    directions: tuple[Direction, ...] = (Direction.FW,),
) -> pd.DataFrame:
    """單一參數表：每欄是一個條件，欄內是該條件下所有樣品、所有 Pixel 的值。

    directions 預設只取 FW（與 V5 相同）；可改成 RV 或兩者。
    """
    names = [c.name for c in conditions]
    if len(set(names)) != len(names):
        raise ValueError("條件名稱不可重複")

    table = all_data(files)
    if table.empty:
        return pd.DataFrame(columns=names)
    direction_values = [d.value for d in directions]
    in_direction = table[TableColumn.DIRECTION.value].isin(direction_values)

    columns = {}
    for cond in conditions:
        wanted = {str(s) for s in cond.samples}
        mask = in_direction & table[TableColumn.SAMPLE.value].isin(wanted)
        columns[cond.name] = table.loc[mask, param.value].reset_index(drop=True)
    # 各欄長度不同時以空值補齊
    return pd.DataFrame(columns)


def jv_areas(files: list[JVFile]) -> dict[str, list[float]]:
    """各檔案的有效面積（每條曲線一個），供 area_check.check_areas 使用。"""
    return {jv.name.filename: [c.area for c in jv.curves] for jv in files}


def missing_samples(
    files: list[JVFile],
    conditions: list[Condition],
    directions: tuple[Direction, ...] = (Direction.FW,),
) -> list[tuple[str, SampleId, Direction]]:
    """條件中列出、但找不到對應檔案的 (條件名稱, 樣品, 方向)，供呼叫端提示使用者。"""
    present = {(jv.name.sample, jv.name.direction) for jv in files}
    return [
        (cond.name, sample, direction)
        for cond in conditions
        for sample in cond.samples
        for direction in directions
        if (sample, direction) not in present
    ]

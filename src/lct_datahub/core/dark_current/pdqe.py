"""B-1：PD-QE 暗電流 TXT 解析。

檔案結構（tab 分隔，換行 \\r\\n）：
  - 'Name' 列：每個樣品一組 5 欄，樣品名寫在該組第 1 欄（電壓欄）
  - 'Time Stamp'、'Area (mm^2)' 等參數列，值同樣寫在該組第 1 欄
  - '[Result]' 列為各欄表頭：Volt. (V)、I (A)、I (A)_Semi-Log、J (A/mm^2)、Dark (A)
  - '[Raw Data]' 列起為數據，遇到空白列結束；其後的 '==========' 與彙整表忽略
電流密度單位 A/mm^2，整合時轉成 A/cm^2（×100）並取絕對值。
"""
import numpy as np
import pandas as pd

from lct_datahub.core.dark_current.truncate import keep_count
from lct_datahub.core.dark_current.types import (
    DarkColumn,
    DarkCurve,
    DarkFailure,
    DarkFileError,
    Instrument,
)

_MM2_TO_CM2 = 0.01  # 1 mm^2 = 0.01 cm^2
_GROUP_WIDTH = 5  # 每個樣品 5 欄
_MIN_POINTS = 3


class _Label:
    """PD-QE 檔內的列標籤與欄位表頭文字（避免手打錯字）。"""

    NAME = "Name"
    TIMESTAMP = "Time Stamp"
    AREA = "Area (mm^2)"
    RESULT = "[Result]"
    RAW = "[Raw Data]"
    VOLTAGE = "Volt. (V)"
    CURRENT = "I (A)"
    J = "J (A/mm^2)"


def is_pdqe_text(rows: list[list[str]]) -> bool:
    """判斷內容是否為 PD-QE 格式：同時有 'Name' 列與 '[Result]' 列。"""
    firsts = {r[0].strip() for r in rows if r}
    return _Label.NAME in firsts and _Label.RESULT in firsts


def _find_row(rows: list[list[str]], label: str, start: int = 0) -> int | None:
    """找第一欄等於 label 的列號；找不到回傳 None。"""
    for i in range(start, len(rows)):
        if rows[i] and rows[i][0].strip() == label:
            return i
    return None


def _cell(row: list[str], col: int) -> str:
    """取得儲存格；超出列長度視為空字串。"""
    return row[col].strip() if col < len(row) else ""


def _to_float(text: str) -> float:
    """轉成 float；空白或無法轉換回傳 NaN。"""
    try:
        return float(text)
    except ValueError:
        return float("nan")


def parse_pdqe(rows: list[list[str]], filename: str) -> list[DarkCurve]:
    """解析 PD-QE 的 tab 分隔列，回傳檔內全部曲線（名稱可能與其他檔重複，由整合步驟處理）。"""
    name_row = _find_row(rows, _Label.NAME)
    result_row = _find_row(rows, _Label.RESULT)
    raw_row = _find_row(rows, _Label.RAW)
    if name_row is None or result_row is None or raw_row is None:
        raise DarkFileError(filename, DarkFailure.BAD_FORMAT, "Name、[Result]、[Raw Data] 三列", "缺少其中一列")
    time_row = _find_row(rows, _Label.TIMESTAMP)
    area_row = _find_row(rows, _Label.AREA)
    if area_row is None:
        raise DarkFileError(filename, DarkFailure.BAD_FORMAT, _Label.AREA, "找不到面積列")

    # 資料區：從 [Raw Data] 起，到第一個電壓欄全空的列為止（資料之後是空白列與彙整表）
    header = [h.strip() for h in rows[result_row]]
    volt_cols = [j for j, h in enumerate(header) if h == _Label.VOLTAGE]
    if not volt_cols:
        raise DarkFileError(filename, DarkFailure.NO_CURVES, _Label.VOLTAGE, "表頭沒有電壓欄")
    data_end = len(rows)
    for i in range(raw_row, len(rows)):
        if not _cell(rows[i], volt_cols[0]):
            data_end = i
            break
    body = rows[raw_row:data_end]

    curves = []
    for j in volt_cols:
        group = header[j : j + _GROUP_WIDTH]
        try:
            col_i, col_j = j + group.index(_Label.CURRENT), j + group.index(_Label.J)
        except ValueError:
            raise DarkFileError(
                filename, DarkFailure.BAD_FORMAT, f"{_Label.CURRENT} 與 {_Label.J}", "該組缺少電流欄"
            ) from None
        name = _cell(rows[name_row], j)
        if not name:
            raise DarkFileError(filename, DarkFailure.BAD_FORMAT, "樣品名稱", f"第 {j + 1} 欄沒有名稱")
        area_mm2 = _to_float(_cell(rows[area_row], j))
        if not np.isfinite(area_mm2) or area_mm2 <= 0:
            raise DarkFileError(filename, DarkFailure.BAD_FORMAT, "大於 0 的面積", f"{name}：{_cell(rows[area_row], j)!r}")

        volt = np.array([_to_float(_cell(r, j)) for r in body])
        cur = np.array([_to_float(_cell(r, col_i)) for r in body])
        dens = np.array([_to_float(_cell(r, col_j)) for r in body])
        valid = np.isfinite(volt) & np.isfinite(dens)  # 含 NaN 的點略過
        volt, cur, dens = volt[valid], cur[valid], dens[valid]
        keep = keep_count(volt)
        if keep < _MIN_POINTS:
            raise DarkFileError(filename, DarkFailure.TOO_FEW_POINTS, f"至少 {_MIN_POINTS} 點", f"{name}：{keep} 點")

        data = pd.DataFrame(
            {
                DarkColumn.VOLTAGE.value: volt[:keep],
                DarkColumn.CURRENT.value: cur[:keep],
                # A/mm^2 → A/cm^2（×100），並取絕對值
                DarkColumn.J.value: np.abs(dens[:keep]) / _MM2_TO_CM2,
            }
        )
        curves.append(
            DarkCurve(
                name=name,
                instrument=Instrument.PDQE,
                source=filename,
                area=area_mm2 * _MM2_TO_CM2,
                area_from_file=True,
                timestamp=_cell(rows[time_row], j) or None if time_row is not None else None,
                removed_points=int(valid.sum()) - keep,
                data=data,
            )
        )
    return curves

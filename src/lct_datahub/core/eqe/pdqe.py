"""C-1：新型 PD-QE 的 EQE TXT 解析。

檔案結構（tab 分隔，換行 \\r\\n）：每個樣品一組 6 欄，並排；
  - 表頭列：Lambda(nm)、EQE (%)、SR (A/W)、Jsc (mA/cm^2)，其後兩欄為「資訊」的標籤與值
  - 資訊欄（第 5、6 欄）：Name、Mode、Range、Volt. Bias (V)、Date、Time (sec)、Comment，
    以及 AM1.5G、AM1.5D、AM0 三種光譜算出的 Jsc
  - 數據從表頭列的下一列開始，波長欄空白即結束
積分電流（Jsc 欄）由儀器算好，直接讀取。
"""
import numpy as np
import pandas as pd

from lct_datahub.core.eqe.types import (
    EqeColumn,
    EqeCurve,
    EqeFailure,
    EqeFileError,
    EqeInstrument,
    Spectrum,
)

_INFO_LABEL_OFFSET = 4  # 資訊標籤在組內的欄位位置（第 5 欄）
_INFO_VALUE_OFFSET = 5  # 資訊值在組內的欄位位置（第 6 欄）
_MIN_POINTS = 3


class _Label:
    """PD-QE EQE 檔內的表頭與資訊標籤文字（避免手打錯字）。"""

    WAVELENGTH = "Lambda(nm)"
    EQE = "EQE (%)"
    SR = "SR (A/W)"
    JSC = "Jsc (mA/cm^2)"
    NAME = "Name"
    BIAS = "Volt. Bias (V)"
    DATE = "Date"


def _cell(row: list[str], col: int) -> str:
    """取得儲存格；超出列長度視為空字串。"""
    return row[col].strip() if col < len(row) else ""


def _to_float(text: str) -> float:
    """轉成 float；空白或無法轉換回傳 NaN。"""
    try:
        return float(text)
    except ValueError:
        return float("nan")


def find_header_row(rows: list[list[str]]) -> int | None:
    """表頭列的列號（含 'Lambda(nm)' 欄的那一列）；找不到回傳 None。"""
    for i, row in enumerate(rows):
        if any(c.strip() == _Label.WAVELENGTH for c in row):
            return i
    return None


def is_pdqe_eqe_text(rows: list[list[str]]) -> bool:
    """判斷內容是否為 PD-QE 的 EQE 檔：有 Lambda(nm) 表頭，且該列同時有 EQE (%) 欄。"""
    header = find_header_row(rows)
    return header is not None and any(c.strip() == _Label.EQE for c in rows[header])


def _group_info(rows: list[list[str]], start: int) -> dict[str, str]:
    """收集一組的資訊欄：標籤 → 值（整份檔案由上到下，空標籤略過）。"""
    info: dict[str, str] = {}
    for row in rows:
        label = _cell(row, start + _INFO_LABEL_OFFSET)
        if label and label not in info:
            info[label] = _cell(row, start + _INFO_VALUE_OFFSET)
    return info


def parse_pdqe_eqe(rows: list[list[str]], filename: str) -> list[EqeCurve]:
    """解析 PD-QE EQE 的 tab 分隔列，回傳檔內全部樣品（名稱可能與其他檔重複，由整合步驟處理）。"""
    header_row = find_header_row(rows)
    if header_row is None:
        raise EqeFileError(filename, EqeFailure.BAD_FORMAT, _Label.WAVELENGTH, "找不到表頭列")
    header = [c.strip() for c in rows[header_row]]
    starts = [j for j, h in enumerate(header) if h == _Label.WAVELENGTH]

    # 資料區：表頭下一列起，到第一個波長欄空白的列為止
    body = []
    for row in rows[header_row + 1 :]:
        if not _cell(row, starts[0]):
            break
        body.append(row)

    curves = []
    for j in starts:
        labels = {_Label.EQE: None, _Label.SR: None, _Label.JSC: None}
        for k in range(1, 4):
            if header[j + k : j + k + 1] and header[j + k] in labels:
                labels[header[j + k]] = j + k
        if None in labels.values():
            raise EqeFileError(
                filename, EqeFailure.BAD_FORMAT, f"{_Label.EQE}、{_Label.SR}、{_Label.JSC}", f"第 {j + 1} 欄起的組別缺少欄位"
            )
        info = _group_info(rows, j)
        name = info.get(_Label.NAME, "")
        if not name:
            raise EqeFileError(filename, EqeFailure.BAD_FORMAT, "樣品名稱（Name）", f"第 {j + 1} 欄起的組別沒有名稱")

        values = np.array(
            [
                [_to_float(_cell(r, c)) for c in (j, labels[_Label.EQE], labels[_Label.SR], labels[_Label.JSC])]
                for r in body
            ]
        ).reshape(-1, 4)
        values = values[np.isfinite(values).all(axis=1)]  # 含 NaN 的點略過
        if len(values) < _MIN_POINTS:
            raise EqeFileError(filename, EqeFailure.TOO_FEW_POINTS, f"至少 {_MIN_POINTS} 點", f"{name}：{len(values)} 點")

        data = pd.DataFrame(
            values,
            columns=[EqeColumn.WAVELENGTH.value, EqeColumn.EQE.value, EqeColumn.SR.value, EqeColumn.JSC.value],
        )
        bias = _to_float(info.get(_Label.BIAS, ""))
        spectrum_jsc = {
            s: _to_float(info[s.value]) for s in Spectrum if s.value in info and np.isfinite(_to_float(info[s.value]))
        }
        curves.append(
            EqeCurve(
                name=name,
                instrument=EqeInstrument.PDQE,
                source=filename,
                data=data,
                timestamp=info.get(_Label.DATE) or None,
                bias=bias if np.isfinite(bias) else None,
                spectrum_jsc=spectrum_jsc,
            )
        )
    return curves

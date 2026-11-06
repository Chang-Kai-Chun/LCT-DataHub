"""B-1：明志暗電流解析（自行搭建系統，搭配 Keithley 2636A）。

檔案為每個樣品一個檔；可能是 txt、csv、dat，或副檔名為 .xls 的 tab 分隔純文字，
也可能是真正的 Excel（xlsx；Excel 檔名必須含 '_abs'）。內容依序為三欄：
  電壓 V (V)、電流 I (A)、電流密度 abs[J (A/cm^2)]
樣品名取檔名（去掉 '_abs' 之後的部分）。檔內沒有面積，由 I/J 反推。
"""
import re
from pathlib import Path

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

ABS_MARK = "_abs"  # Excel 檔名必須含此字串
_MIN_POINTS = 3
_AREA_DIGITS = 4  # 反推面積保留的有效位數（檔內 J 只有 6 位有效數字）
_SPLIT = re.compile(r"[\t,]")  # 欄位以 tab 或逗號分隔


def sample_name_from_file(path: Path) -> str:
    """樣品名：檔名去掉副檔名，並去掉 '_abs' 以及其後的部分。"""
    return re.split(ABS_MARK, Path(path).stem, maxsplit=1, flags=re.IGNORECASE)[0]


def text_rows_to_array(rows: list[list[str]]) -> np.ndarray:
    """從列中取出數據：前三欄皆為數字的列才算數據（表頭與空白列自動略過），回傳 N×3 陣列。"""
    out = []
    for r in rows:
        cells = [c.strip() for c in r if c.strip() != ""][:3]
        if len(cells) < 3:
            continue
        try:
            out.append([float(c) for c in cells])
        except ValueError:
            continue
    return np.array(out, dtype=float).reshape(-1, 3)


def split_text(text: str) -> list[list[str]]:
    """把文字依 tab 或逗號切成列。"""
    return [_SPLIT.split(line) for line in text.splitlines()]


def parse_mingchi(values: np.ndarray, path: Path) -> DarkCurve:
    """把 N×3（V、I、J）陣列整理成 DarkCurve：略過 NaN、智慧截取、J 取絕對值、反推面積。"""
    name = sample_name_from_file(path)
    volt, cur, dens = values[:, 0], values[:, 1], values[:, 2]
    valid = np.isfinite(volt) & np.isfinite(cur) & np.isfinite(dens)
    volt, cur, dens = volt[valid], cur[valid], dens[valid]
    keep = keep_count(volt)
    if keep < _MIN_POINTS:
        raise DarkFileError(path.name, DarkFailure.TOO_FEW_POINTS, f"至少 {_MIN_POINTS} 點", f"{keep} 點")
    volt, cur, dens = volt[:keep], cur[:keep], np.abs(dens[:keep])

    # 面積 = |I| / J（取中位數；J 為 0 的點不能用）
    usable = dens > 0
    if not usable.any():
        raise DarkFileError(path.name, DarkFailure.BAD_FORMAT, "J 不為 0 的數據點", "J 全為 0")
    area = float(np.median(np.abs(cur[usable]) / dens[usable]))
    area = float(f"{area:.{_AREA_DIGITS}g}")

    data = pd.DataFrame(
        {
            DarkColumn.VOLTAGE.value: volt,
            DarkColumn.CURRENT.value: cur,
            DarkColumn.J.value: dens,
        }
    )
    return DarkCurve(
        name=name,
        instrument=Instrument.MINGCHI,
        source=path.name,
        area=area,
        area_from_file=False,
        timestamp=None,
        removed_points=int(valid.sum()) - keep,
        data=data,
    )

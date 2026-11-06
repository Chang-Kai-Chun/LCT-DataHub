"""C-1：舊型（五樓）EQE 的 Excel 解析。

檔案結構（已用 20250306 eqe raw.ivr.xls 驗證）：第 0 列為 X、Y 交替的表頭，每條曲線佔 X、Y 兩欄，
各樣品往右每 12 欄一組；第一組（含額外的前導曲線，共 14 欄）是校正檔，**跳過**。
每組內（k 為組序，從 0 起算）：
  - 波長     第 8 + 12k 欄（0 起算）
  - SR (A/W) 第 5 + 12k 欄
  - EQE      第 9 + 12k 欄（小數，乘 100 轉成 %）
  - 電流     第 11 + 12k 欄（mA/cm^2，每個波長點的值）
積分電流 = 電流 × 波長步距，由短波長起累積加總；原始電流已是 mA/cm^2，**不除以有效面積**。
樣品名自動編號 S1、S2…（之後可用 rename_curves 改名）。
"""
import numpy as np
import pandas as pd

from lct_datahub.core.eqe.types import (
    EqeColumn,
    EqeCurve,
    EqeFailure,
    EqeFileError,
    EqeInstrument,
)

_FIRST_BLOCK_WIDTH = 14  # 校正檔那一組的欄數（多一條前導曲線）
_BLOCK_WIDTH = 12  # 每個樣品往右 12 欄
_WAVELENGTH_COL = 8  # 組內欄位位置（以該組在整張表的第 12k 欄為基準）
_SR_COL = 5
_EQE_COL = 9
_CURRENT_COL = 11
_AXIS_MARK, _VALUE_MARK = "X", "Y"
_MIN_POINTS = 3
_EQE_TO_PERCENT = 100.0


def sample_count(ncols: int) -> int | None:
    """由總欄數算出樣品數（不含校正檔）；欄數不符 14 + 12n 的格式時回傳 None。"""
    rest = ncols - _FIRST_BLOCK_WIDTH
    return rest // _BLOCK_WIDTH if rest >= 0 and rest % _BLOCK_WIDTH == 0 else None


def is_old_grid(grid: list[list]) -> bool:
    """判斷表格是否為舊型 EQE：第 0 列是 X、Y 交替，且欄數符合 14 + 12n。"""
    if not grid or sample_count(len(grid[0])) is None:
        return False
    return all(str(v).strip() == (_AXIS_MARK, _VALUE_MARK)[i % 2] for i, v in enumerate(grid[0]))


def _column(grid: list[list], col: int) -> np.ndarray:
    """取出一欄的數據（略過表頭列；遇到第一個空白或非數字就結束）。"""
    values = []
    for row in grid[1:]:
        v = row[col] if col < len(row) else ""
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not np.isfinite(v):
            break
        values.append(float(v))
    return np.array(values)


def parse_old_eqe(grid: list[list], filename: str) -> list[EqeCurve]:
    """解析舊型 EQE 表格（第 0 列表頭加數據列），回傳各樣品（不含校正檔）。"""
    n = sample_count(len(grid[0])) if grid else None
    if n is None or not is_old_grid(grid):
        ncols = len(grid[0]) if grid else 0
        raise EqeFileError(filename, EqeFailure.BAD_FORMAT, "欄數為 14 + 12×樣品數，且表頭為 X、Y 交替", f"{ncols} 欄")
    if n == 0:
        raise EqeFileError(filename, EqeFailure.NO_CURVES, "校正檔之外至少一個樣品", "只有校正檔")

    curves = []
    for k in range(1, n + 1):  # k = 0 是校正檔，跳過
        base = _BLOCK_WIDTH * k
        wavelength = _column(grid, base + _WAVELENGTH_COL)
        cols = {
            EqeColumn.SR: _column(grid, base + _SR_COL),
            EqeColumn.EQE: _column(grid, base + _EQE_COL),
            "current": _column(grid, base + _CURRENT_COL),
        }
        name = f"S{k}"
        lengths = {len(wavelength), *(len(v) for v in cols.values())}
        if len(lengths) != 1:
            raise EqeFileError(filename, EqeFailure.BAD_FORMAT, "波長、SR、EQE、電流欄長度一致", f"{name}：{sorted(lengths)}")
        if len(wavelength) < _MIN_POINTS:
            raise EqeFileError(filename, EqeFailure.TOO_FEW_POINTS, f"至少 {_MIN_POINTS} 點", f"{name}：{len(wavelength)} 點")

        step = float(np.median(np.diff(wavelength)))  # 波長步距（nm）
        data = pd.DataFrame(
            {
                EqeColumn.WAVELENGTH.value: wavelength,
                EqeColumn.EQE.value: cols[EqeColumn.EQE] * _EQE_TO_PERCENT,
                EqeColumn.SR.value: cols[EqeColumn.SR],
                # 積分電流 = (電流 × 步距) 的累積和
                EqeColumn.JSC.value: np.cumsum(cols["current"] * step),
            }
        )
        curves.append(EqeCurve(name=name, instrument=EqeInstrument.OLD, source=filename, data=data))
    return curves

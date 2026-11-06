"""B-2：最低點位置處理（把 |J| 最低點偏移到 0 V，或保持原始）。

做法：只平移電壓軸（V' = V − V_min），每個測量點的 I、J 完全不變，不內插；
偏移量記錄在 DarkCurve.shift，原始電壓保留在 ORIGINAL_VOLTAGE 欄，隨時可還原。
兩種儀器統一用 |J| 的最小值（V5 的明志版沒取絕對值）。
"""
import dataclasses

import numpy as np

from lct_datahub.core.dark_current.types import DarkColumn, DarkCurve, ShiftMode

_DECIMALS = 9  # 平移後四捨五入的位數，避免 0.03000000000000003 這類浮點雜訊


def original_voltage(curve: DarkCurve) -> np.ndarray:
    """曲線的原始電壓：已偏移過就取 ORIGINAL_VOLTAGE 欄，否則就是 Volt 欄。"""
    column = DarkColumn.ORIGINAL_VOLTAGE.value
    if column in curve.data.columns:
        return curve.data[column].to_numpy()
    return curve.data[DarkColumn.VOLTAGE.value].to_numpy()


def minimum_voltage(curve: DarkCurve) -> float:
    """整條曲線中 |J| 最小那一點的原始電壓（有並列時取第一個）。"""
    dens = curve.data[DarkColumn.J.value].abs().to_numpy()
    return float(original_voltage(curve)[int(np.argmin(dens))])


def shift_curve(curve: DarkCurve, mode: ShiftMode) -> DarkCurve:
    """依模式處理單條曲線，一律從原始電壓重算，所以可重複切換模式；回傳新曲線，原本的不變。"""
    original = original_voltage(curve)
    data = curve.data.drop(columns=[DarkColumn.ORIGINAL_VOLTAGE.value], errors="ignore").copy()
    if mode is ShiftMode.KEEP:
        data[DarkColumn.VOLTAGE.value] = original
        return dataclasses.replace(curve, data=data, shift=0.0)

    shift = minimum_voltage(curve)
    data[DarkColumn.VOLTAGE.value] = np.round(original - shift, _DECIMALS)
    data[DarkColumn.ORIGINAL_VOLTAGE.value] = original
    return dataclasses.replace(curve, data=data, shift=shift)


def shift_curves(curves: list[DarkCurve], mode: ShiftMode) -> list[DarkCurve]:
    """對全部曲線套用同一種模式。"""
    return [shift_curve(c, mode) for c in curves]

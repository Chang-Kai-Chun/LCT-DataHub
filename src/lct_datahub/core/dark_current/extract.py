"""B-4 擷取值：每條暗電流曲線的 Rsh，以及指定電壓（0、−0.1、−0.5 V）的暗電流（2026-11-15 定案）。

- Rsh：−0.03～0.03 V 的 I-V 最小平方擬合，Rsh = 1／斜率（Ω）；與 PD-QE 軟體相同（57 個 pixel 驗證過）
- 暗電流：指定電壓的電流以線性內插取得，Id = |I(V)|（A），Jd = Id ÷ 面積（A/cm²）
- 一律使用曲線目前的電壓欄：曲線有偏移（B-2）時就是偏移後的電壓（0 V 即 |J| 最低點）
- PD-QE 與明志相同做法；PD-QE 另附儀器彙整表的值只當對照
  （未偏移時自己算的 Rsh＝表上 Rsh，偏移後＝表上 Rs）
- 明志 _abs 檔的電流也是絕對值（2026-11-19 發現），直接擬合 Rsh 會得到負值；改用有正負號的電流：
  1. 有同名但沒有 _abs 的檔 → 用它（套用與曲線相同的 B-2 偏移量）
  2. 沒有 → 以 |I| 最低點為零點，左側（電壓較低）改為負號
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from lct_datahub.core.dark_current.shift import original_voltage
from lct_datahub.core.dark_current.types import (
    CurrentSource, DarkColumn, DarkCurve, ExtractBias, Instrument, InstrumentRef,
)

RSH_WINDOW = 0.03  # Rsh 擬合區間半寬（V）：−0.03～0.03 V
_EPS = 1e-9  # 浮點誤差容許（電壓 0.03 可能存成 0.030000000000000002）
_DECIMALS = 9  # 套用偏移後四捨五入的位數（與 shift.py 相同）


@dataclass(frozen=True)
class DarkExtract:
    """一條曲線的擷取值。"""

    name: str
    instrument: Instrument
    area: float  # cm²
    shift: float  # 偏移量（V）；0 表示未偏移
    rsh: float | None  # Ω；區間內點數不足或斜率為 0 時為 None
    jd: dict[ExtractBias, float | None] = field(default_factory=dict)  # A/cm²；電壓超出量測範圍為 None
    id: dict[ExtractBias, float | None] = field(default_factory=dict)  # A
    reference: InstrumentRef | None = None  # PD-QE 儀器對照值
    current_source: CurrentSource = CurrentSource.FILE  # Rsh、Id 所用電流的來源
    id_min: float | None = None  # 曲線最低點的 |I|（A）：E 區 0 V 的 Shot 使用（2026-11-19），與偏移設定無關

    @property
    def rsh_area(self) -> float | None:
        """A·Rsh（Ω·cm²），Thermal 雜訊與 D* 使用。"""
        return self.rsh * self.area if self.rsh is not None else None

    @property
    def reference_rsh(self) -> float | None:
        """儀器對應目前電壓基準的 Rsh：未偏移取表上 Rsh、偏移後取表上 Rs（沒有對照值為 None）。"""
        if self.reference is None:
            return None
        return self.reference.rs if self.shift != 0.0 else self.reference.rsh


def fit_rsh(volt: np.ndarray, current: np.ndarray, window: float = RSH_WINDOW) -> float | None:
    """|V| ≤ window 的點做 I 對 V 的最小平方直線，回傳 1／斜率（Ω）；少於 2 個不同電壓或斜率為 0 回傳 None。"""
    mask = np.abs(volt) <= window + _EPS
    v, i = volt[mask], current[mask]
    if len(np.unique(v)) < 2:
        return None
    slope = float(np.polyfit(v, i, 1)[0])
    return 1.0 / slope if slope != 0.0 else None


def current_at(volt: np.ndarray, current: np.ndarray, target: float) -> float | None:
    """target 電壓的電流（線性內插）；target 超出量測範圍回傳 None。"""
    order = np.argsort(volt)
    v, i = volt[order], current[order]
    if target < v[0] - _EPS or target > v[-1] + _EPS:
        return None
    return float(np.interp(target, v, i))


def is_absolute_current(original: np.ndarray, current: np.ndarray) -> bool:
    """電流是否為取過絕對值的資料：全部 ≥ 0，且 |I| 最低點兩側都有量測點（V 形）。"""
    if len(current) < 3 or np.any(current < 0):
        return False
    lowest = int(np.argmin(np.abs(current)))
    return bool(np.any(original < original[lowest]) and np.any(original > original[lowest]))


def restore_sign(original: np.ndarray, current: np.ndarray) -> np.ndarray:
    """以 |I| 最低點為零點還原正負號：電壓低於該點的電流改為負值，其餘維持正值。"""
    zero = original[int(np.argmin(np.abs(current)))]
    return np.where(original < zero, -np.abs(current), np.abs(current))


def signed_iv(curve: DarkCurve) -> tuple[np.ndarray, np.ndarray, CurrentSource]:
    """B-4 使用的 (電壓, 有正負號電流, 來源)；電壓已套用曲線目前的 B-2 偏移。"""
    if curve.signed is not None:
        # 未取絕對值的同名檔：套用與曲線相同的偏移量
        volt = np.round(curve.signed[DarkColumn.VOLTAGE.value].to_numpy(float) - curve.shift, _DECIMALS)
        return volt, curve.signed[DarkColumn.CURRENT.value].to_numpy(float), CurrentSource.SIGNED_FILE
    volt = curve.data[DarkColumn.VOLTAGE.value].to_numpy(float)
    current = curve.data[DarkColumn.CURRENT.value].to_numpy(float)
    original = original_voltage(curve).astype(float)
    if curve.instrument is Instrument.MINGCHI and is_absolute_current(original, current):
        return volt, restore_sign(original, current), CurrentSource.RESTORED
    return volt, current, CurrentSource.FILE


def extract(curve: DarkCurve) -> DarkExtract:
    """算出一條曲線的 Rsh 與三個電壓的暗電流（使用目前的電壓欄，偏移後即偏移後的電壓；電流來源見 signed_iv）。"""
    volt, current, source = signed_iv(curve)
    ids: dict[ExtractBias, float | None] = {}
    jds: dict[ExtractBias, float | None] = {}
    for bias in ExtractBias:
        value = current_at(volt, current, bias.value)
        ids[bias] = abs(value) if value is not None else None
        jds[bias] = abs(value) / curve.area if value is not None else None
    return DarkExtract(
        name=curve.name, instrument=curve.instrument, area=curve.area, shift=curve.shift,
        rsh=fit_rsh(volt, current), jd=jds, id=ids, reference=curve.reference, current_source=source,
        id_min=float(np.min(np.abs(current))) if len(current) else None,
    )


def extract_all(curves: list[DarkCurve]) -> list[DarkExtract]:
    """全部曲線的擷取值（維持曲線順序）。"""
    return [extract(c) for c in curves]


def bias_label(bias: ExtractBias) -> str:
    """電壓的顯示文字（例如 0 V、-0.1 V）。"""
    return f"{bias.value:g} V"


def extract_frame(extracts: list[DarkExtract]) -> pd.DataFrame:
    """Excel 的 Rsh_Jd sheet：每條曲線一列（Rsh、A·Rsh、三個電壓的 Jd 與 Id、PD-QE 儀器對照）。"""
    rows = []
    for e in extracts:
        row = {
            "Name": e.name,
            "Shift (V)": e.shift,
            "Area (cm^2)": e.area,
            "Rsh (ohm)": e.rsh,
            "A*Rsh (ohm*cm^2)": e.rsh_area,
        }
        for bias in ExtractBias:
            row[f"Jd @ {bias_label(bias)} (A/cm^2)"] = e.jd.get(bias)
        for bias in ExtractBias:
            row[f"Id @ {bias_label(bias)} (A)"] = e.id.get(bias)
        row["Instrument Rsh (ohm)"] = e.reference_rsh  # 未偏移＝表上 Rsh、偏移後＝表上 Rs
        row["Current source"] = e.current_source.value  # Rsh、Id 所用電流的來源
        rows.append(row)
    return pd.DataFrame(rows)

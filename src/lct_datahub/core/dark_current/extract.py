"""B-4 擷取值：每條暗電流曲線的 Rsh，以及指定電壓（0、−0.1、−0.5 V）的暗電流（2026-11-15 定案）。

- Rsh：−0.03～0.03 V 的 I-V 最小平方擬合，Rsh = 1／斜率（Ω）；與 PD-QE 軟體相同（57 個 pixel 驗證過）
- 暗電流：指定電壓的電流以線性內插取得，Id = |I(V)|（A），Jd = Id ÷ 面積（A/cm²）
- 一律使用曲線目前的電壓欄：曲線有偏移（B-2）時就是偏移後的電壓（0 V 即 |J| 最低點）
- PD-QE 與明志相同做法；PD-QE 另附儀器彙整表的值只當對照
  （未偏移時自己算的 Rsh＝表上 Rsh，偏移後＝表上 Rs）
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from lct_datahub.core.dark_current.types import DarkColumn, DarkCurve, ExtractBias, Instrument, InstrumentRef

RSH_WINDOW = 0.03  # Rsh 擬合區間半寬（V）：−0.03～0.03 V
_EPS = 1e-9  # 浮點誤差容許（電壓 0.03 可能存成 0.030000000000000002）


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


def extract(curve: DarkCurve) -> DarkExtract:
    """算出一條曲線的 Rsh 與三個電壓的暗電流（使用目前的電壓欄，偏移後即偏移後的電壓）。"""
    volt = curve.data[DarkColumn.VOLTAGE.value].to_numpy(float)
    current = curve.data[DarkColumn.CURRENT.value].to_numpy(float)
    ids: dict[ExtractBias, float | None] = {}
    jds: dict[ExtractBias, float | None] = {}
    for bias in ExtractBias:
        value = current_at(volt, current, bias.value)
        ids[bias] = abs(value) if value is not None else None
        jds[bias] = abs(value) / curve.area if value is not None else None
    return DarkExtract(
        name=curve.name, instrument=curve.instrument, area=curve.area, shift=curve.shift,
        rsh=fit_rsh(volt, current), jd=jds, id=ids, reference=curve.reference,
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
        rows.append(row)
    return pd.DataFrame(rows)

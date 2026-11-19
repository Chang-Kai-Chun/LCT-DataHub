"""D-2：Shot 與 Thermal 參考線（選用；暗電流與 Rsh 取自 B-4 的同一偏壓）。

i_shot = √(2 q |I_dark|)、i_thermal = √(4 k T ÷ Rsh)，單位 A/√Hz（每 1 Hz 頻寬）。
理論白雜訊 √(i_shot² + i_thermal²) 是物理下限：實測值低於它代表量測或換算有問題。
"""
from dataclasses import dataclass
from enum import Enum

import numpy as np

ELEMENTARY_CHARGE = 1.602176634e-19  # C
BOLTZMANN = 1.380649e-23  # J/K
ROOM_TEMPERATURE = 300.0  # K（預設溫度）


class ReferenceKind(Enum):
    """參考線種類（值為圖例文字）。"""

    SHOT = "Shot"
    THERMAL = "Thermal"
    TOTAL = "Shot + Thermal"


@dataclass(frozen=True)
class ReferenceLine:
    """一條水平參考線。"""

    kind: ReferenceKind
    value: float  # A/√Hz
    sample: str = ""  # 對應的樣品（圖例用）

    @property
    def label(self) -> str:
        """圖例文字。"""
        return f"{self.sample} {self.kind.value}".strip()


def shot_noise(dark_current: float) -> float:
    """散粒雜訊 √(2q|I|)（A/√Hz）。"""
    return float(np.sqrt(2.0 * ELEMENTARY_CHARGE * abs(dark_current)))


def thermal_noise(rsh: float, temperature: float = ROOM_TEMPERATURE) -> float:
    """熱雜訊 √(4kT/Rsh)（A/√Hz）；Rsh 須大於 0。"""
    if rsh <= 0:
        raise ValueError("Rsh 必須大於 0")
    return float(np.sqrt(4.0 * BOLTZMANN * temperature / rsh))


def reference_lines(sample: str, dark_current: float | None, rsh: float | None,
                    temperature: float = ROOM_TEMPERATURE) -> list[ReferenceLine]:
    """依可用的數值產生參考線：有暗電流畫 Shot、有 Rsh 畫 Thermal，兩者都有再加總和。"""
    lines = []
    if dark_current is not None:
        lines.append(ReferenceLine(ReferenceKind.SHOT, shot_noise(dark_current), sample))
    if rsh is not None and rsh > 0:
        lines.append(ReferenceLine(ReferenceKind.THERMAL, thermal_noise(rsh, temperature), sample))
    if len(lines) == 2:
        total = float(np.hypot(lines[0].value, lines[1].value))
        lines.append(ReferenceLine(ReferenceKind.TOTAL, total, sample))
    return lines

"""E 區：比偵測率 D*（2026-11-19 定案，以 pixel 計算）。

    D*(λ) = R(λ) × √A ÷ i_n        單位 Jones（cm·Hz^0.5/W）

- R(λ)：C 區 EQE 曲線的響應度 SR（A/W），整條曲線都算，可取指定波長（最多 3 個，線性內插）與最大值
- A：有效面積（cm²，取自 B 區）
- i_n 四種（DStarKind）：
  - 實測：D 區 n 次平均後 1 Hz 的雜訊密度（A/√Hz，標準定義）
  - Shot：√(2q|Id|)；0 V 用曲線最低點的 |I|，其他偏壓用 B-4 該偏壓的 Id
  - Thermal：√(4kT/Rsh)
  - Shot＋Thermal：√(Shot² + Thermal²)（理論極限；沒有量 noise 也能先看）
- 偏壓：EQE、noise 必須與 D* 偏壓相同；對不上的那一項不算並寫明原因；
  EQE 檔沒有偏壓資訊（舊型儀器）時照算，但提醒
- 常數用精確值（k = 1.380649e-23、q = 1.602176634e-19，見 noise/reference.py）；溫度預設 300 K
已用 Gino 的整合 Excel（20261114數據計算.xlsx）驗證：Thermal、Shot、Combine 與 Excel 差異 < 0.03%（只差常數位數）。
"""
from dataclasses import dataclass, field
from enum import Enum

import numpy as np

from lct_datahub.core.eqe.types import EqeColumn, EqeCurve
from lct_datahub.core.noise.reference import ROOM_TEMPERATURE, shot_noise, thermal_noise

BIAS_TOLERANCE = 1e-6  # 偏壓相同的容許差（V）
MAX_WAVELENGTHS = 3  # 最多指定幾個波長


class DStarKind(Enum):
    """D* 的四種雜訊來源（value 為顯示與 Excel 名稱）。"""

    MEASURED = "Measured"  # 實測 noise（1 Hz）
    COMBINE = "Shot+Thermal"  # 理論極限
    THERMAL = "Thermal"
    SHOT = "Shot"


def check_wavelengths(values: list[float]) -> list[float]:
    """檢查指定波長：最多 MAX_WAVELENGTHS 個、皆大於 0、不重複；回傳依大小排序的清單，不合理拋出 ValueError。"""
    if len(values) > MAX_WAVELENGTHS:
        raise ValueError(f"最多指定 {MAX_WAVELENGTHS} 個波長")
    if any(v <= 0 for v in values):
        raise ValueError("波長必須大於 0")
    if len(set(values)) != len(values):
        raise ValueError("波長不可重複")
    return sorted(values)


def responsivity_curve(curve: EqeCurve) -> tuple[np.ndarray, np.ndarray]:
    """EQE 曲線的 (波長 nm, 響應度 A/W)，依波長排序。"""
    data = curve.data.sort_values(EqeColumn.WAVELENGTH.value)
    return data[EqeColumn.WAVELENGTH.value].to_numpy(float), data[EqeColumn.SR.value].to_numpy(float)


def interp_at(x: np.ndarray, y: np.ndarray, target: float) -> float | None:
    """target 處的線性內插；超出範圍為 None。"""
    if len(x) == 0 or target < x[0] or target > x[-1]:
        return None
    return float(np.interp(target, x, y))


def detectivity(responsivity, area: float | None, noise: float | None):
    """D* = R × √A ÷ i_n（R 可為陣列）；面積或雜訊缺少、≤ 0 時為 None。"""
    if responsivity is None or area is None or noise is None or noise <= 0 or area <= 0:
        return None
    return responsivity * np.sqrt(area) / noise


def _same_bias(a: float | None, b: float) -> bool:
    """偏壓是否相同（None 視為未知，不算相同）。"""
    return a is not None and abs(a - b) <= BIAS_TOLERANCE


@dataclass(frozen=True, eq=False)
class PixelInput:
    """一個 pixel 的輸入（B、C、D 各區配對好的值）。"""

    pixel: str
    bias: float  # D* 的偏壓（V）
    eqe: EqeCurve | None  # C 區
    area: float | None  # cm²（B 區）
    noise: float | None = None  # A/√Hz（D 區 1 Hz）
    noise_bias: float | None = None
    dark_current: float | None = None  # A（Shot 用；0 V 為最低點的 |I|）
    rsh: float | None = None  # Ω
    temperature: float = ROOM_TEMPERATURE


@dataclass(frozen=True, eq=False)
class PixelResult:
    """一個 pixel 的 D*：四種雜訊與各自的 D*(λ)。"""

    input: PixelInput
    wavelength: np.ndarray  # nm
    responsivity: np.ndarray  # A/W
    noises: dict[DStarKind, float | None]  # A/√Hz
    spectra: dict[DStarKind, np.ndarray | None]  # Jones；不能算為 None
    warnings: list[str] = field(default_factory=list)

    def r_at(self, wavelength: float) -> float | None:
        """指定波長的響應度。"""
        return interp_at(self.wavelength, self.responsivity, wavelength)

    def at(self, kind: DStarKind, wavelength: float) -> float | None:
        """指定波長的 D*。"""
        spectrum = self.spectra.get(kind)
        return None if spectrum is None else interp_at(self.wavelength, spectrum, wavelength)

    def peak(self, kind: DStarKind) -> tuple[float, float] | None:
        """最大 D* 與所在波長（nm）；不能算為 None。"""
        spectrum = self.spectra.get(kind)
        if spectrum is None or len(spectrum) == 0:
            return None
        index = int(np.nanargmax(spectrum))
        return float(spectrum[index]), float(self.wavelength[index])


def compute_pixel(inp: PixelInput) -> PixelResult:
    """計算一個 pixel 的四種 D*(λ)；偏壓不符或缺資料的項目為 None 並寫入 warnings。"""
    warnings: list[str] = []
    wavelength, responsivity = (np.array([]), np.array([])) if inp.eqe is None else responsivity_curve(inp.eqe)
    usable = inp.eqe is not None
    if inp.eqe is None:
        warnings.append("沒有 EQE（C 區）")
    elif inp.eqe.bias is None:
        warnings.append("EQE 檔沒有偏壓資訊（舊型儀器），假設與 D* 偏壓相同")
    elif not _same_bias(inp.eqe.bias, inp.bias):
        warnings.append(f"EQE 偏壓 {inp.eqe.bias:g} V 與 D* 偏壓 {inp.bias:g} V 不同，不計算")
        usable = False
    if inp.area is None:
        warnings.append("沒有面積（B 區）")

    measured = inp.noise
    if measured is None:
        warnings.append("沒有實測 noise（D 區），只有理論極限")
    elif not _same_bias(inp.noise_bias, inp.bias):
        shown = "未知" if inp.noise_bias is None else f"{inp.noise_bias:g} V"
        warnings.append(f"Noise 偏壓 {shown} 與 D* 偏壓 {inp.bias:g} V 不同，實測 D* 不計算")
        measured = None
    shot = shot_noise(inp.dark_current) if inp.dark_current is not None else None
    thermal = thermal_noise(inp.rsh, inp.temperature) if inp.rsh is not None and inp.rsh > 0 else None
    if shot is None:
        warnings.append("沒有同偏壓的暗電流（B 區），Shot 不計算")
    if thermal is None:
        warnings.append("沒有 Rsh（B 區），Thermal 不計算")
    parts = [v for v in (shot, thermal) if v is not None]
    combine = float(np.sqrt(sum(v ** 2 for v in parts))) if parts else None

    noises = {DStarKind.MEASURED: measured, DStarKind.COMBINE: combine, DStarKind.THERMAL: thermal,
              DStarKind.SHOT: shot}
    spectra = {k: detectivity(responsivity, inp.area, v) if usable else None for k, v in noises.items()}
    return PixelResult(inp, wavelength, responsivity, noises, spectra, warnings)

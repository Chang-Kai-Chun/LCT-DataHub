"""D-1：由時域電流計算雜訊密度（2026-11-19 定案，驗證見 noise_guide.html 2-4、2-7）。

1. 扣掉平均電流（直流成分）：避免平均值經 Hann 窗洩漏到第一個頻率點（0.1 Hz）
2. 乘上 Hann 窗後做 FFT，峰值振幅 a = 2 × |FFT| ÷ Σw（＝光焱軟體輸出的振幅欄，已用明志檔逐點驗證）
3. 換算雜訊密度：
   - 標準定義：a ÷ √(2 × 1.5 × Δf)（÷√2 峰值換 RMS；1.5 為 Hann 等效雜訊頻寬；符合 Parseval 定理）
   - 儀器定義：a ÷ √f（光焱軟體的 Noise Current 欄，只供與舊數據對照）
頻率範圍：Δf 到 Nyquist 頻率之前（例如 2000 點、5 ms：0.1～99.9 Hz，與儀器輸出相同）。
"""
import numpy as np

from lct_datahub.core.noise.types import NoiseDefinition, NoiseRecord

HANN_ENBW = 1.5  # Hann 窗的等效雜訊頻寬（單位：頻率格）
TARGET_FREQUENCY = 1.0  # D* 使用的頻率（Hz）


def amplitude(current: np.ndarray, interval: float) -> tuple[np.ndarray, np.ndarray]:
    """Hann 窗 FFT 的峰值振幅（已扣平均值）；回傳 (頻率, 振幅)，不含 0 Hz 與 Nyquist 頻率。"""
    n = len(current)
    window = np.hanning(n)
    spectrum = np.fft.rfft((current - current.mean()) * window)
    amp = 2.0 * np.abs(spectrum) / window.sum()
    freq = np.fft.rfftfreq(n, interval)
    keep = slice(1, n // 2)  # 去掉 0 Hz 與 Nyquist 頻率
    return freq[keep], amp[keep]


def to_density(freq: np.ndarray, amp: np.ndarray, resolution: float, definition: NoiseDefinition) -> np.ndarray:
    """峰值振幅換成雜訊密度（A/√Hz）；resolution 為頻率間隔 Δf（Hz）。"""
    if definition is NoiseDefinition.INSTRUMENT:
        return amp / np.sqrt(freq)
    return amp / np.sqrt(2.0 * HANN_ENBW * resolution)


def noise_density(record: NoiseRecord, definition: NoiseDefinition = NoiseDefinition.STANDARD
                  ) -> tuple[np.ndarray, np.ndarray]:
    """一個檔的雜訊密度；回傳 (頻率 Hz, 雜訊 A/√Hz)。"""
    freq, amp = amplitude(record.current, record.interval)
    return freq, to_density(freq, amp, record.resolution, definition)


def value_at(freq: np.ndarray, density: np.ndarray, target: float = TARGET_FREQUENCY) -> float | None:
    """最接近 target 的頻率點的值；最近的點與 target 相差超過半個頻率間隔（不在範圍內）時為 None。"""
    if len(freq) == 0:
        return None
    index = int(np.argmin(np.abs(freq - target)))
    step = freq[1] - freq[0] if len(freq) > 1 else freq[0]
    if abs(freq[index] - target) > step / 2:
        return None
    return float(density[index])

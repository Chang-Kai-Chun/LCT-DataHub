"""D-1：異常檔偵測（2026-11-19 定案：溢位、削平自動排除並告知使用者；未穩定預設只警告，見 group.py）。

- 溢位：電表超出量程時回傳 9.91E+37 等溢位代碼（或非數字）；只要 1 點，整條頻譜就不能用
- 削平：超出量程的讀值卡在同一個極值；正常數據的最大、最小值通常只出現 1～2 次
- 未穩定：把數據切成 10 段取每段平均（1 秒以上的平均會濾掉 60 Hz 干擾），
  第一段平均與後半段（第 6～10 段）中位數的差，超過後半段各段平均標準差的 UNSTABLE_RATIO 倍
  （2026-11-19 以明志 36 檔與 PD-QE 12 檔校正：0 V 檔多在 5 以下；−0.1 V 檔常見 10～50，
  即加偏壓後的衰減；合成的 1E-10 A 衰減約 15～25）
"""
import numpy as np

from lct_datahub.core.noise.types import Exclusion, NoiseAnomaly, NoiseRecord

OVERFLOW_LIMIT = 1e30  # 絕對值超過這個值視為溢位代碼（A）
CLIP_MIN_COUNT = 5  # 最大或最小值重複出現至少這麼多次視為削平
STABILITY_BLOCKS = 10  # 未穩定檢查切成幾段
UNSTABLE_RATIO = 10.0  # 第一段偏離程度的門檻（倍）


def overflow_count(current: np.ndarray) -> int:
    """溢位點數：非數字或絕對值超過 OVERFLOW_LIMIT。"""
    return int(np.sum(~np.isfinite(current) | (np.abs(current) > OVERFLOW_LIMIT)))


def clipped_count(current: np.ndarray) -> int:
    """最大值或最小值重複出現的次數（取較多者）。"""
    return int(max(np.sum(current == current.max()), np.sum(current == current.min())))


def instability(current: np.ndarray, blocks: int = STABILITY_BLOCKS) -> float:
    """第一段平均偏離後半段中位數的程度（以後半段各段平均的標準差為單位）。"""
    means = np.array([part.mean() for part in np.array_split(current, blocks)])
    late = means[blocks // 2:]
    spread = float(np.std(late, ddof=1))
    deviation = abs(float(means[0] - np.median(late)))
    if spread == 0.0:
        return 0.0 if deviation == 0.0 else float("inf")
    return deviation / spread


def detect_anomaly(record: NoiseRecord) -> Exclusion | None:
    """檢查一個檔；有異常回傳排除原因（依溢位、削平、未穩定的順序取第一個），正常回傳 None。"""
    current = record.current
    overflow = overflow_count(current)
    if overflow:
        return Exclusion(record.source, NoiseAnomaly.OVERFLOW, f"{overflow} 個溢位點（例如 9.91E+37）")
    clipped = clipped_count(current)
    if clipped >= CLIP_MIN_COUNT:
        return Exclusion(record.source, NoiseAnomaly.CLIPPED, f"{clipped} 個讀值卡在同一個極值")
    ratio = instability(current)
    if ratio > UNSTABLE_RATIO:
        seconds = record.duration / STABILITY_BLOCKS
        return Exclusion(
            record.source, NoiseAnomaly.UNSTABLE,
            f"前 {seconds:g} 秒的平均電流偏離穩定值（{ratio:.0f} 倍於後半段的變動）",
        )
    return None

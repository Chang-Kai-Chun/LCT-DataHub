"""B-1：智慧截取（依電壓步距截掉檔案尾端附加的異常資料）。"""
import numpy as np

_STEP_POINTS = 20  # 用前幾個間隔的中位數當步距
_TOLERANCE_RATIO = 0.5  # 與步距相差超過步距的 50% 視為異常
_MIN_TOLERANCE = 0.005  # 容許值下限（V），避免步距很小時過度敏感


def keep_count(voltages: np.ndarray) -> int:
    """回傳應保留的點數：從開頭起，電壓間隔都符合步距的連續範圍。

    步距取前 20 個間隔的中位數；某點與前一點的間隔偏離步距太多（往回跳或往前跳）就在該處截斷。
    """
    n = len(voltages)
    if n < 3:
        return n
    diffs = np.diff(voltages)
    step = float(np.median(diffs[:_STEP_POINTS]))
    tolerance = max(abs(step) * _TOLERANCE_RATIO, _MIN_TOLERANCE)
    # 第一個間隔異常的位置 i（diffs[i] 連接第 i 與 i+1 點）→ 保留 i+1 個點
    bad = np.flatnonzero(np.abs(diffs - step) > tolerance)
    return int(bad[0]) + 1 if bad.size else n

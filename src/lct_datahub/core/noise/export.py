"""D-1：把 noise 分組結果寫成 Excel。

- Summary：每組一列（樣品、偏壓、n、1 Hz 雜訊、量測參數、使用與排除的檔、提醒）
- Mean：頻率＋每組的平均雜訊密度（不同量測設定的頻率點以聯集排列，沒有的留空）
- Runs：頻率＋每個納入平均的檔
- Excluded：被排除的檔與原因（沒有就不輸出）
"""
from enum import Enum
from pathlib import Path

import numpy as np
import pandas as pd

from lct_datahub.core.noise.spectrum import HANN_ENBW, TARGET_FREQUENCY, value_at
from lct_datahub.core.noise.types import NoiseDefinition, NoiseGroup

FREQ_COLUMN = "Frequency (Hz)"
_FREQ_DECIMALS = 9  # 合併頻率軸時四捨五入的位數
_DEFINITION_TEXT = {
    NoiseDefinition.STANDARD: f"standard: a / sqrt(2 x {HANN_ENBW:g} x df)",
    NoiseDefinition.INSTRUMENT: "instrument: a / sqrt(f)",
}


class NoiseSheet(Enum):
    """固定的 sheet 名稱。"""

    SUMMARY = "Summary"
    MEAN = "Mean"
    RUNS = "Runs"
    EXCLUDED = "Excluded"


def _series(freq: np.ndarray, values: np.ndarray, name: str) -> pd.Series:
    """以頻率為索引的一欄（頻率四捨五入，方便不同組合併）。"""
    return pd.Series(values, index=np.round(freq, _FREQ_DECIMALS), name=name)


def _wide(columns: list[pd.Series]) -> pd.DataFrame:
    """多欄依頻率聯集合併成一張表，第一欄為頻率。"""
    if not columns:
        return pd.DataFrame(columns=[FREQ_COLUMN])
    frame = pd.concat(columns, axis=1).sort_index()
    frame.index.name = FREQ_COLUMN
    return frame.reset_index()


def column_names(groups: list[NoiseGroup]) -> list[str]:
    """各組的欄名：預設為 label；label 重複時（同樣品同偏壓、不同儀器）加上儀器名稱。"""
    labels = [g.label for g in groups]
    return [f"{g.label} [{g.instrument.value}]" if labels.count(g.label) > 1 else g.label for g in groups]


def mean_frame(groups: list[NoiseGroup]) -> pd.DataFrame:
    """Mean 表：每組的平均雜訊密度（全部被排除的組不列）。"""
    drawn = [g for g in groups if g.mean is not None]
    return _wide([_series(g.freq, g.mean, name) for g, name in zip(drawn, column_names(drawn))])


def runs_frame(groups: list[NoiseGroup]) -> pd.DataFrame:
    """Runs 表：每個納入平均的檔一欄（欄名為檔名）。"""
    return _wide([_series(g.freq, d, r.source) for g in groups for r, d in zip(g.members, g.runs)])


def summary_frame(groups: list[NoiseGroup]) -> pd.DataFrame:
    """Summary 表：每組一列。"""
    rows = []
    for g in groups:
        rows.append({
            "Sample": g.sample,
            "Bias (V)": g.bias,
            "Bias source": g.bias_source.value,
            "Instrument": g.instrument.value,
            "n": g.n,
            f"Noise @ {TARGET_FREQUENCY:g} Hz (A/Hz^0.5)": value_at(g.freq, g.mean) if g.mean is not None else None,
            "Peak |I| (A)": g.peak_current,
            "Floor ratio": g.floor_ratio,
            "Definition": _DEFINITION_TEXT[g.definition],
            "Window": "Hann",
            "df (Hz)": 1.0 / g.duration,
            "Interval (s)": g.interval,
            "Points": g.points,
            "Duration (s)": g.duration,
            "Used files": "; ".join(r.source for r in g.members),
            "Excluded files": "; ".join(f"{e.source} ({e.anomaly.value})" for e in g.excluded),
            "Notes": "; ".join(g.notes),
        })
    return pd.DataFrame(rows)


def excluded_frame(groups: list[NoiseGroup]) -> pd.DataFrame:
    """Excluded 表：被排除的檔與原因。"""
    rows = [
        {"File": e.source, "Sample": g.sample, "Bias (V)": g.bias, "Reason": e.anomaly.value, "Detail": e.detail}
        for g in groups for e in g.excluded
    ]
    return pd.DataFrame(rows, columns=["File", "Sample", "Bias (V)", "Reason", "Detail"])


def write_noise_excel(path: Path, groups: list[NoiseGroup]) -> None:
    """寫出 Excel：Summary、Mean、Runs，有被排除的檔才多一張 Excluded。"""
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        summary_frame(groups).to_excel(writer, sheet_name=NoiseSheet.SUMMARY.value, index=False)
        mean_frame(groups).to_excel(writer, sheet_name=NoiseSheet.MEAN.value, index=False)
        runs_frame(groups).to_excel(writer, sheet_name=NoiseSheet.RUNS.value, index=False)
        excluded = excluded_frame(groups)
        if not excluded.empty:
            excluded.to_excel(writer, sheet_name=NoiseSheet.EXCLUDED.value, index=False)

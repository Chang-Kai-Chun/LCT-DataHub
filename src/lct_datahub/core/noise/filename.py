"""D-1：從 noise 檔名讀出樣品、第幾次量測與偏壓。

檔名以空白或底線分隔，例如：
- 明志：`G1-2 1st -0.1V`、`g1-2 3rd 0v`、`G1-2 3nd -0.1V`（次數只讀數字）
- PD-QE：`G6-1`（0 V）、`G6-1_-0.1V`
- 之後可能出現：`EMPTY 1st 0V 1E-9`（檔位等其他標記會被略過）

樣品名＝第一個次數或偏壓標記之前的所有片段（不分大小寫，一律轉大寫）；
沒有次數標記為 None；沒有偏壓標記時預設 0 V（BiasSource.DEFAULT）。
"""
import re
from dataclasses import dataclass
from pathlib import Path

from lct_datahub.core.noise.types import BiasSource

DEFAULT_BIAS = 0.0  # 檔名沒有偏壓時的預設值（V）
_SEPARATOR = re.compile(r"[\s_]+")
_RUN = re.compile(r"^(\d+)(st|nd|rd|th)$", re.IGNORECASE)  # 1st、2nd、3rd、3nd、4th…
_BIAS = re.compile(r"^([+-]?\d+(?:\.\d+)?)v$", re.IGNORECASE)  # 0V、-0.1V、0v


@dataclass(frozen=True)
class NoiseName:
    """檔名解析結果。"""

    sample: str
    run: int | None
    bias: float
    bias_source: BiasSource


def parse_noise_name(name: str) -> NoiseName:
    """解析檔名（可含副檔名）；樣品名讀不出來時以整個檔名當樣品名。"""
    tokens = [t for t in _SEPARATOR.split(Path(name).stem.strip()) if t]
    sample_parts: list[str] = []
    run: int | None = None
    bias: float | None = None
    for token in tokens:
        run_match, bias_match = _RUN.match(token), _BIAS.match(token)
        if run_match and run is None:
            run = int(run_match.group(1))
        elif bias_match and bias is None:
            bias = float(bias_match.group(1)) + 0.0  # + 0.0 把 -0.0 變成 0.0
        elif run is None and bias is None:
            sample_parts.append(token)  # 還沒遇到次數或偏壓標記：屬於樣品名
        # 其他標記（檔位 1E-9、OVER…）略過
    sample = " ".join(sample_parts) or Path(name).stem.strip()
    source = BiasSource.FILENAME if bias is not None else BiasSource.DEFAULT
    return NoiseName(sample.upper(), run, DEFAULT_BIAS if bias is None else bias, source)

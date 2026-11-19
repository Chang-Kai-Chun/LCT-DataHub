"""D 區共用的 Enum、dataclass 與例外（2026-11-19 定案）。

- 頻譜一律由原始的時間與電流重算（明志、PD-QE 相同），不使用儀器算好的頻譜
- 預設標準定義 i_n = a ÷ √(2 × 1.5 × Δf)（Hann 窗），可切換成儀器定義 a ÷ √f
- 同一樣品＋偏壓的檔案做 n 次功率平均；溢位、削平的檔警告並排除，未穩定的檔只警告
"""
from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class NoiseInstrument(Enum):
    """Noise 儀器（兩台都使用光焱科技的軟體）。"""

    MINGCHI = "明志"  # [PARM] 參數表＋時域（第 C、D 欄）＋儀器頻譜
    PDQE = "PD-QE"  # 時域（第 A、B 欄）＋儀器頻譜


class NoiseDefinition(Enum):
    """雜訊密度的換算定義（a 為 Hann 窗 FFT 的峰值振幅）。"""

    STANDARD = "標準"  # a ÷ √(2 × 1.5 × Δf)：峰值換 RMS，再除以 Hann 等效雜訊頻寬（預設）
    INSTRUMENT = "儀器"  # a ÷ √f：光焱軟體的定義，只供與舊數據對照


class BiasSource(Enum):
    """偏壓的來源。"""

    FILENAME = "檔名"
    DEFAULT = "預設 0 V"  # 檔名沒有偏壓


class NoiseAnomaly(Enum):
    """異常檔的原因（溢位、削平自動排除；未穩定預設只警告）。"""

    OVERFLOW = "溢位（爆量程）"  # 出現 9.91E+37 等溢位代碼
    CLIPPED = "削平（爆量程）"  # 多個讀值剛好等於同一個極值
    UNSTABLE = "電流未穩定"  # 開頭的電流明顯偏離之後的穩定值


class NoiseFailure(Enum):
    """Noise 檔案讀取失敗原因。"""

    BAD_FORMAT = "檔案格式無法辨識"
    TOO_FEW_POINTS = "有效數據點太少"
    IRREGULAR_TIME = "時間間隔不固定"


class NoiseFileError(Exception):
    """Noise 檔案問題：帶有檔名、失敗原因、期望與實際，供警告視窗顯示。"""

    def __init__(self, filename: str, reason: NoiseFailure, expected: str, actual: str):
        self.filename = filename
        self.reason = reason
        self.expected = expected
        self.actual = actual
        super().__init__(f"{filename}：{reason.value}（期望：{expected}；實際：{actual}）")


@dataclass(frozen=True, eq=False)
class NoiseRecord:
    """一個 noise 檔：檔名解析結果與時域電流。"""

    source: str  # 來源檔名
    instrument: NoiseInstrument
    sample: str  # 樣品名（大寫）
    bias: float  # 偏壓（V）
    bias_source: BiasSource
    run: int | None  # 第幾次量測；檔名沒有次數標記為 None
    time: np.ndarray  # s
    current: np.ndarray  # A
    header_bias: float | None = None  # 明志參數表的 Volt Level（V）；PD-QE 沒有

    @property
    def points(self) -> int:
        """數據點數。"""
        return len(self.current)

    @property
    def interval(self) -> float:
        """取樣間隔（s）。"""
        return float(np.median(np.diff(self.time)))

    @property
    def duration(self) -> float:
        """量測總時間（s）＝點數 × 取樣間隔。"""
        return self.points * self.interval

    @property
    def resolution(self) -> float:
        """頻率間隔 Δf（Hz）＝1 ÷ 量測總時間。"""
        return 1.0 / self.duration


@dataclass(frozen=True)
class Exclusion:
    """被排除的檔與原因。"""

    source: str
    anomaly: NoiseAnomaly
    detail: str  # 給使用者看的說明（例如 3 個溢位點）


@dataclass(frozen=True, eq=False)
class NoiseGroup:
    """同一樣品、偏壓、儀器與量測設定的 n 次量測結果。"""

    sample: str
    bias: float
    bias_source: BiasSource
    instrument: NoiseInstrument
    definition: NoiseDefinition
    points: int  # 每次量測的點數
    interval: float  # 取樣間隔（s）
    members: list[NoiseRecord]  # 納入平均的檔
    excluded: list[Exclusion]  # 被排除的檔
    freq: np.ndarray  # Hz（不含 0 Hz）
    runs: list[np.ndarray]  # 每個納入檔的雜訊密度（與 members 同順序）
    notes: list[str] = field(default_factory=list)  # 其他提醒（偏壓不一致、設定不同已分開、次數重複…）
    split: bool = False  # 同一樣品與偏壓有不同量測設定而被分開
    floors: list[float] = field(default_factory=list)  # 每個納入檔的白雜訊底線（與 members 同順序）

    @property
    def floor_ratio(self) -> float | None:
        """n 次量測白雜訊底線的最大÷最小（一致性）；n < 2 時為 None。"""
        if len(self.floors) < 2 or min(self.floors) <= 0:
            return None
        return max(self.floors) / min(self.floors)

    @property
    def n(self) -> int:
        """納入平均的量測次數。"""
        return len(self.members)

    @property
    def mean(self) -> np.ndarray | None:
        """n 次功率平均（先平方、平均後開根號）；n 為 0 時為 None。"""
        if not self.runs:
            return None
        return np.sqrt(np.mean(np.square(self.runs), axis=0))

    @property
    def low(self) -> np.ndarray | None:
        """n 次中每個頻率的最小值（n 為 0 時為 None）。"""
        return np.min(self.runs, axis=0) if self.runs else None

    @property
    def high(self) -> np.ndarray | None:
        """n 次中每個頻率的最大值（n 為 0 時為 None）。"""
        return np.max(self.runs, axis=0) if self.runs else None

    @property
    def duration(self) -> float:
        """每次量測的總時間（s）。"""
        return self.points * self.interval

    @property
    def peak_current(self) -> float | None:
        """納入檔中電流絕對值的最大值（A，主要是 60 Hz 干擾的峰值）；n 為 0 時為 None。"""
        return max(float(np.max(np.abs(r.current))) for r in self.members) if self.members else None

    @property
    def label(self) -> str:
        """圖例與 Excel 欄名：樣品 偏壓 (n=…)；設定不同被分開時加上量測時間。"""
        extra = f", {self.duration:g} s" if self.split else ""
        return f"{self.sample} {self.bias:g}V (n={self.n}{extra})"

"""C 區共用的 Enum、dataclass 與例外（C-1、C-2、C-3 共用）。"""
from dataclasses import dataclass, field
from enum import Enum

import pandas as pd


class EqeInstrument(Enum):
    """EQE 儀器（兩台）。"""

    PDQE = "PD-QE"  # 新型：tab 分隔 TXT，積分電流由儀器算好
    OLD = "舊型（五樓）"  # 舊型：Excel（xls），積分電流由「電流 × 步距」累積


class EqeColumn(Enum):
    """整合後 EQE 資料的欄位名稱（同時作為 DataFrame 欄名）。"""

    WAVELENGTH = "Lambda (nm)"
    EQE = "EQE (%)"
    SR = "SR (A/W)"
    JSC = "Jsc (mA/cm^2)"  # 由短波長累積到該波長的積分電流密度


class Spectrum(Enum):
    """PD-QE 檔內以各標準光譜算出的 Jsc 項目名稱（同時是檔內的標籤文字）。"""

    AM15G = "AM1.5G"
    AM15D = "AM1.5D"
    AM0 = "AM0"


class EqeFailure(Enum):
    """EQE 檔案失敗原因（出現任何一種都警告並停止作業）。"""

    BAD_FORMAT = "檔案格式無法辨識"
    NO_CURVES = "找不到任何樣品"
    TOO_FEW_POINTS = "有效數據點太少"
    UNSUPPORTED = "不支援的檔案類型"


class EqeFileError(Exception):
    """EQE 檔案問題：帶有檔名、失敗原因、期望與實際，供警告視窗顯示。"""

    def __init__(self, filename: str, reason: EqeFailure, expected: str, actual: str):
        self.filename = filename
        self.reason = reason
        self.expected = expected
        self.actual = actual
        super().__init__(f"{filename}：{reason.value}（期望：{expected}；實際：{actual}）")


class EqeNameError(ValueError):
    """替樣品重新命名時，名稱為空白、重複或對不到原樣品時拋出。"""


@dataclass(frozen=True)
class EqeCurve:
    """一個樣品的 EQE 曲線。"""

    name: str  # 樣品名稱（整合後保證不重複）；舊型為自動編號 S1、S2…
    instrument: EqeInstrument
    source: str  # 來源檔名
    data: pd.DataFrame  # 欄位為 EqeColumn 的 value
    timestamp: str | None = None  # 測量時間（舊型檔內沒有）
    bias: float | None = None  # 偏壓 V（舊型檔內沒有）
    # PD-QE 檔內以各光譜算出的 Jsc（mA/cm^2）；舊型為空
    spectrum_jsc: dict[Spectrum, float] = field(default_factory=dict)

    @property
    def jsc(self) -> float:
        """積分電流密度（mA/cm^2）：積分電流欄的最後一點。"""
        return float(self.data[EqeColumn.JSC.value].iloc[-1])

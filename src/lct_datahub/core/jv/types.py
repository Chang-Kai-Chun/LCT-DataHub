"""A 區共用的 Enum、dataclass 與例外（A-1、A-2、A-3 共用）。"""
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import pandas as pd

from lct_datahub.core.sample_id import SampleId

# Pixel 只會是 2–6（可跳號、順序不固定）
VALID_PIXELS = frozenset({2, 3, 4, 5, 6})


class Direction(Enum):
    """掃描方向：正掃 FW、反掃 RV。value 即檔名中的文字。"""

    FW = "FW"
    RV = "RV"


class JVParam(Enum):
    """JV 參數；value 為檔底彙整表的欄位名稱。"""

    VOC = "Voc (V)"
    JSC = "Jsc (mA/cm^2)"
    PCE = "Efficiency (%)"
    FF = "Fill Factor (%)"
    RSH = "Rsh (ohm)"


# ALL_Data 與每檔參數表的參數欄順序（與 V5 範例相同）
ALL_DATA_PARAMS = (JVParam.VOC, JVParam.PCE, JVParam.FF, JVParam.JSC, JVParam.RSH)


class CurveColumn(Enum):
    """曲線資料的欄位名稱（檔內表頭文字，同時作為 DataFrame 欄名）。"""

    VOLTAGE = "[Volt (V)]"
    CURRENT = "[Current (mA)]"
    J = "[J (mA/cm^2)]"


class InfoField(Enum):
    """每個曲線區塊「資訊欄」的項目名稱。"""

    AREA = "Area (cm^2)"
    TIMESTAMP = "Time stamp"


class TableColumn(Enum):
    """整合表（ALL_Data 長表）中，參數以外的欄位名稱。"""

    SAMPLE = "Sample"
    DIRECTION = "Direction"
    PIXEL = "Pixel"
    AREA = "Area (cm^2)"
    TIMESTAMP = "Time stamp"


class GroupMode(Enum):
    """樣品分組方式（A-1）。"""

    EVEN = "平均分配"  # 問條件數與名稱，樣品平均分到各條件
    CUSTOM = "使用者自訂"  # 使用者手動輸入條件名稱與樣品
    AUTO = "自動"  # 每 4 個樣品一組，餘數放最後一組


class GroupingError(ValueError):
    """分組設定不合理（名稱重複、樣品重複歸組、條件數不合等）時拋出。"""


class InvalidAreaError(ValueError):
    """指定的有效面積不是大於 0 的有限數值時拋出。"""


class FailureReason(Enum):
    """JV 檔案失敗原因（出現任何一種都警告並停止作業）。"""

    BAD_FORMAT = "檔名格式不符"
    MISSING_DIRECTION = "缺少 FW/RV"
    MISSING_PIXELS = "Pixel 數字串缺漏"
    INVALID_PIXEL = "Pixel 出現 2–6 以外的數字（或重複）"
    COUNT_MISMATCH = "數字串長度與檔內曲線組數不符"
    BAD_CONTENT = "檔案內容無法辨識"
    DUPLICATE = "檔案重複"


class JVFileError(Exception):
    """JV 檔案問題：帶有檔名、失敗原因、期望與實際，供警告視窗顯示。"""

    def __init__(self, filename: str, reason: FailureReason, expected: str, actual: str):
        self.filename = filename
        self.reason = reason
        self.expected = expected
        self.actual = actual
        super().__init__(f"{filename}：{reason.value}（期望：{expected}；實際：{actual}）")


@dataclass(frozen=True)
class JVFileName:
    """檔名解析結果。pixels 由左到右即檔內曲線由左到右的順序（測量順序）。"""

    sample: SampleId
    direction: Direction
    pixels: tuple[int, ...]
    filename: str  # 原始檔名，供錯誤訊息使用


@dataclass(frozen=True)
class JVCurve:
    """檔內一組 JV 曲線。"""

    pixel: int  # 由檔名數字串對應而來
    area: float  # 有效面積 cm²（資訊欄的 Area）
    timestamp: datetime  # 測量時間（資訊欄的 Time stamp）
    data: pd.DataFrame  # 欄位為 CurveColumn 的 value


@dataclass(frozen=True)
class JVFile:
    """讀取完成的一個 JV 檔案。

    params 以 Pixel 為 index、JVParam 的 value 為欄名，列順序與 curves 相同。
    """

    name: JVFileName
    curves: tuple[JVCurve, ...]
    params: pd.DataFrame


@dataclass(frozen=True)
class Condition:
    """一個實驗條件：名稱＋樣品範圍（例如 Ref、G1-G4）。"""

    name: str
    samples: tuple[SampleId, ...]


@dataclass(frozen=True)
class Grouping:
    """分組狀態：各條件加上尚未分配的樣品（對應 UI 的條件框與未分配區）。"""

    conditions: tuple[Condition, ...]
    unassigned: tuple[SampleId, ...]

    @property
    def is_complete(self) -> bool:
        """是否所有樣品都已分配到條件。"""
        return not self.unassigned

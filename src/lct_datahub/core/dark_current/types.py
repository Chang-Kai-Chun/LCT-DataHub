"""B 區共用的 Enum、dataclass 與例外（B-1、B-2、B-3 共用）。"""
from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Instrument(Enum):
    """暗電流儀器（只有這兩種，沒有第三種）。"""

    PDQE = "PD-QE"  # 貴儀，tab 分隔 TXT，電流密度 A/mm^2
    MINGCHI = "明志"  # 明志自行搭建、搭配 Keithley 2636A，電流密度 A/cm^2


class DarkColumn(Enum):
    """整合後暗電流資料的欄位名稱（同時作為 DataFrame 欄名）。"""

    VOLTAGE = "Volt (V)"
    CURRENT = "I (A)"  # 保留原始正負號
    J = "J (A/cm^2)"  # 絕對值，單位統一為 A/cm^2
    ORIGINAL_VOLTAGE = "Original Volt (V)"  # 只有偏移後才有：儀器量到的原始電壓


class ShiftMode(Enum):
    """B-2 最低點位置處理：二選一。"""

    SHIFT = "偏移到 0 V"  # 整條曲線的電壓平移，使 |J| 最低點落在 0 V（圖右上角註記 shift）
    KEEP = "保持原始"


class DarkFailure(Enum):
    """暗電流檔案失敗原因（出現任何一種都警告並停止作業）。"""

    BAD_FORMAT = "檔案格式無法辨識"
    NO_CURVES = "找不到任何曲線"
    TOO_FEW_POINTS = "有效數據點太少"
    UNSUPPORTED = "不支援的檔案類型"


class DarkFileError(Exception):
    """暗電流檔案問題：帶有檔名、失敗原因、期望與實際，供警告視窗顯示。"""

    def __init__(self, filename: str, reason: DarkFailure, expected: str, actual: str):
        self.filename = filename
        self.reason = reason
        self.expected = expected
        self.actual = actual
        super().__init__(f"{filename}：{reason.value}（期望：{expected}；實際：{actual}）")


@dataclass(frozen=True)
class DarkCurve:
    """一條暗電流曲線（已轉成 A/cm^2、已做智慧截取）。"""

    name: str  # 樣品／曲線名稱（整合後保證不重複）
    instrument: Instrument
    source: str  # 來源檔名（供面積檢查與錯誤訊息）
    area: float  # 有效面積 cm^2
    area_from_file: bool  # True：面積讀自檔內；False：由 I/J 反推（明志檔內沒有面積）
    timestamp: str | None  # 測量時間（檔內沒有則為 None）
    removed_points: int  # 智慧截取掉的點數
    data: pd.DataFrame  # 欄位為 DarkColumn 的 value；偏移後多一欄 ORIGINAL_VOLTAGE
    shift: float = 0.0  # 偏移量 V：Volt = 原始電壓 − shift（沒偏移為 0）

    @property
    def is_shifted(self) -> bool:
        """是否真的被偏移過（偏移量不為 0；最低點本來就在 0 V 時不算）。"""
        return self.shift != 0.0

"""前端使用的 Enum。

前端不直接 import lct_datahub（完整文件 3-4），因此這裡另外定義一份；
value 必須與核心（core/jv/types.py、api/errors.py）完全相同，API 才能辨識。
核心的 Enum 有修改時，這裡要同步更新。
"""
from enum import Enum


class Direction(Enum):
    """JV 掃描方向（core.jv.types.Direction）。"""

    FW = "FW"
    RV = "RV"


class JVParam(Enum):
    """JV 參數；value 為 API 回傳 Box 表的欄位名稱（core.jv.types.JVParam）。"""

    VOC = "Voc (V)"
    JSC = "Jsc (mA/cm^2)"
    PCE = "Efficiency (%)"
    FF = "Fill Factor (%)"
    RSH = "Rsh (ohm)"


# 可用數值範圍篩選的參數（Rsh 不篩選，與 core.jv.types.BOX_FILTER_PARAMS 相同）
BOX_FILTER_PARAMS = (JVParam.PCE, JVParam.VOC, JVParam.JSC, JVParam.FF)


class GroupMode(Enum):
    """樣品分組的預填方式（core.jv.types.GroupMode）。"""

    EVEN = "平均分配"
    CUSTOM = "使用者自訂"
    AUTO = "自動"


class DirectionMode(Enum):
    """Box 圖取用的方向（core.jv.types.DirectionMode）。"""

    FW = "FW"
    RV = "RV"
    BOTH = "FW＋RV"
    PER_SAMPLE = "逐樣品選擇"


class BoxColumn(Enum):
    """API Box 表中，參數以外的欄位名稱。"""

    ROW = "row"
    CONDITION = "Condition"
    SAMPLE = "Sample"
    DIRECTION = "Direction"
    PIXEL = "Pixel"
    KEEP = "Keep"


class ErrorKind(Enum):
    """API 錯誤回應的 kind（api/errors.py），另加前端自己的連線錯誤。"""

    FILE = "file"  # 檔案問題：顯示檔名、原因、期望、實際並停止作業
    INPUT = "input"  # 輸入問題：顯示訊息，讓使用者修正
    NOT_FOUND = "not_found"  # 找不到工作
    CONNECTION = "connection"  # 前端連不到 API
    UNKNOWN = "unknown"  # 其他非預期錯誤


class JVTab(Enum):
    """JV 頁面的分頁。"""

    UPLOAD = "upload"
    GROUPING = "grouping"
    EXCEL = "excel"
    BOX = "box"
    CURVES = "curves"


class ShiftMode(Enum):
    """B-2 最低點位置處理（core.dark_current.types.ShiftMode）。"""

    SHIFT = "偏移到 0 V"
    KEEP = "保持原始"


class DarkTab(Enum):
    """暗電流頁面的分頁。"""

    UPLOAD = "upload"
    SHIFT = "shift"
    EXCEL = "excel"
    GROUPING = "grouping"
    PLOT = "plot"


class Route(Enum):
    """頁面路徑。"""

    HOME = "/"
    JV = "/jv"
    DARK = "/dark"
    EQE = "/eqe"

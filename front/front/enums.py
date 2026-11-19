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


class Section(Enum):
    """API 的功能區；value 為網址與專案 jobs 的鍵（api/jobs.py 的 Section）。"""

    JV = "jv"
    DARK = "dark"
    EQE = "eqe"
    NOISE = "noise"


class NoiseDefinition(Enum):
    """雜訊密度的換算定義（core.noise.types.NoiseDefinition）。"""

    STANDARD = "標準"  # a ÷ √(2 × 1.5 × Δf)（預設）
    INSTRUMENT = "儀器"  # a ÷ √f（光焱軟體，只供對照）


class NoiseTab(Enum):
    """Noise 頁面的步驟標籤：d-1 上傳、d-2 分組、d-3 雜訊圖、d-4 數值與參考線。"""

    UPLOAD = "upload"
    GROUPING = "grouping"
    PLOT = "plot"
    VALUES = "values"


class IntegrationTab(Enum):
    """PD 數據整合頁面的步驟標籤：e-1 設定、e-2 配對、e-3 D* 表、e-4 D*(λ) 圖。"""

    SETTINGS = "settings"
    PAIRING = "pairing"
    TABLE = "table"
    PLOT = "plot"


class DStarKind(Enum):
    """D* 的四種雜訊來源（core.detectivity.compute.DStarKind）。"""

    MEASURED = "Measured"
    COMBINE = "Shot+Thermal"
    THERMAL = "Thermal"
    SHOT = "Shot"


class SourceKind(Enum):
    """E 區配對的資料來源（core.detectivity.pairing.SourceKind）。"""

    DARK = "dark"
    EQE = "eqe"
    NOISE = "noise"


class ProjectSort(Enum):
    """專案大廳的排序方式。"""

    UPDATED = "最新修改"
    NAME = "名稱排序"


class ShiftMode(Enum):
    """B-2 最低點位置處理（core.dark_current.types.ShiftMode）。"""

    SHIFT = "偏移到 0 V"
    KEEP = "保持原始"


class DarkTab(Enum):
    """暗電流頁面的步驟標籤：b-1 整合（上傳、面積、偏移、Excel）、b-2 分組、b-3 暗電流圖、b-4 擷取值（規劃中）。"""

    INTEGRATE = "integrate"
    GROUPING = "grouping"
    PLOT = "plot"
    EXTRACT = "extract"


class EqeTab(Enum):
    """EQE 頁面的步驟標籤：c-1 上傳（含舊型命名、Excel）、c-2 分組、c-3 EQE 與積分電流、c-4 R-plot。"""

    UPLOAD = "upload"
    GROUPING = "grouping"
    EQE = "eqe"
    RPLOT = "rplot"


class Route(Enum):
    """頁面路徑。"""

    HOME = "/"
    LOGIN = "/login"
    PROJECTS = "/projects"  # 專案大廳（登入後先選專案，不顯示側欄）
    OVERVIEW = "/overview"  # 作業區第一頁：專案總覽
    JV = "/jv"
    DARK = "/dark"
    EQE = "/eqe"
    NOISE = "/noise"
    INTEGRATION = "/integration"
    REPORT = "/report"

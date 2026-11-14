"""各功能 State 共用的資料列與小工具（A JV、B 暗電流、之後的 C EQE）。"""
import base64
from dataclasses import dataclass


@dataclass
class AreaRow:
    """面積檢查：檔名與該檔出現的面積（給 rx.foreach 使用）。"""

    filename: str = ""
    areas: str = ""


def fmt(value) -> str:
    """數值轉顯示文字（4 位有效數字）；None 顯示空白。"""
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def parse_float(text: str, label: str) -> float | None:
    """把輸入框文字轉成數值；空白回傳 None，格式錯誤拋出 ValueError（訊息含欄位名稱）。"""
    text = text.strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise ValueError(f"「{label}」必須是數值，目前輸入：{text}") from None


def png_data_url(data: bytes) -> str:
    """PNG 內容轉成 data URL，直接給 rx.image 顯示，也可直接下載。"""
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")

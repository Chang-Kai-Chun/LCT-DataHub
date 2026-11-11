"""前端設定：FastAPI 位址與逾時；可用環境變數覆寫。"""
import os
from dataclasses import dataclass


class EnvVar:
    """可覆寫設定的環境變數名稱。"""

    API_URL = "LCT_API_URL"  # FastAPI 位址；Reflex 後端與 FastAPI 同在 813 時用 127.0.0.1 即可
    API_TIMEOUT = "LCT_API_TIMEOUT"  # 秒；大量檔案或畫圖可能較久


@dataclass(frozen=True)
class FrontSettings:
    """前端設定值。"""

    api_url: str
    api_timeout: float


def load_settings() -> FrontSettings:
    """讀取設定：有環境變數就用環境變數，否則用預設值（FastAPI 預設 port 8000）。"""
    return FrontSettings(
        api_url=os.environ.get(EnvVar.API_URL, "http://127.0.0.1:8000").rstrip("/"),
        api_timeout=float(os.environ.get(EnvVar.API_TIMEOUT, "120")),
    )


SETTINGS = load_settings()

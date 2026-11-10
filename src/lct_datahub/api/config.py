"""API 設定：工作資料夾根目錄、監聽位址與 port；可用環境變數覆寫。"""
import os
from dataclasses import dataclass
from pathlib import Path

# 專案根目錄：src/lct_datahub/api/config.py 往上三層
PROJECT_ROOT = Path(__file__).resolve().parents[3]


class EnvVar:
    """可覆寫設定的環境變數名稱。"""

    WORK_ROOT = "LCT_WORK_ROOT"  # 工作資料夾根目錄（G-2）
    HOST = "LCT_API_HOST"
    PORT = "LCT_API_PORT"


@dataclass(frozen=True)
class ApiConfig:
    """API 服務設定。"""

    work_root: Path  # 每次作業一個資料夾，放在這底下；不自動清除
    host: str  # 813 部署時監聽 0.0.0.0，讓同網域電腦連線
    port: int  # FastAPI 用 8000；Reflex 後端已改用 8001，兩者不可重複


def load_config() -> ApiConfig:
    """讀取設定：有環境變數就用環境變數，否則用預設值。"""
    return ApiConfig(
        work_root=Path(os.environ.get(EnvVar.WORK_ROOT, PROJECT_ROOT / "data" / "jobs")),
        host=os.environ.get(EnvVar.HOST, "0.0.0.0"),
        port=int(os.environ.get(EnvVar.PORT, "8000")),
    )

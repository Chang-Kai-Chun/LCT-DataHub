"""LCT DataHub 前端（Reflex）進入點。

前端只透過 HTTP 呼叫 FastAPI（預設 http://127.0.0.1:8000，可用環境變數 LCT_API_URL 覆寫），
不直接 import lct_datahub（完整文件 3-4）。
啟動：先在專案根目錄 uv run lct-api，再於 front/ 執行 uv run reflex run。
"""
import reflex as rx

# 匯入頁面模組時，@rx.page 會自動註冊頁面
from front.pages import dark, home, jv, login, projects  # noqa: F401

app = rx.App()  # 主題設定在 rxconfig.py 的 RadixThemesPlugin

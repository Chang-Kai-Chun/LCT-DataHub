"""LCT DataHub 前端（Reflex）進入點。

前端只透過 HTTP 呼叫 FastAPI（預設 http://127.0.0.1:8000，可用環境變數 LCT_API_URL 覆寫），
不直接 import lct_datahub（完整文件 3-4）。
啟動：先在專案根目錄 uv run lct-api，再於 front/ 執行 uv run reflex run。

外觀：assets/lct.css（lct. 設計，原型在 site/）。Radix 主題暫時保留給尚未改版的頁面，A、B 改完後移除。
"""
import reflex as rx

# 匯入頁面模組時，@rx.page 會自動註冊頁面
from front.pages import dark, eqe, jv, login, overview, projects  # noqa: F401

# 字體（皆為 SIL OFL 1.1）：Sora（英數字標、大標）、JetBrains Mono（數值）、
# 中文為源流明體 GenRyuMin（https://github.com/ButTaiwan/genryu-font，需安裝在電腦上），
# 沒裝的電腦退回 Noto Serif TC（下方 Google Fonts）。
# TODO：部署到 813 前改為放在 assets/fonts/ 自行提供（區網可能連不到 Google Fonts，各電腦也不一定裝了源流明體）
FONTS_URL = (
    "https://fonts.googleapis.com/css2?family=Sora:wght@400;600;800"
    "&family=Noto+Serif+TC:wght@400;500;700&family=JetBrains+Mono:wght@400;600&display=swap"
)

app = rx.App(stylesheets=[FONTS_URL, "/lct.css"])

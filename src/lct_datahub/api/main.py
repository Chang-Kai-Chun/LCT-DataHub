"""FastAPI 入口：建立 app、註冊路由與錯誤處理；`uv run lct-api` 啟動服務。

路由都是 async def，讀檔、計算、畫圖等同步工作以 asyncio.to_thread() 交給執行緒，不會擋住其他使用者的請求。
"""
from pathlib import Path

import uvicorn
from fastapi import FastAPI

from lct_datahub.api.config import load_config
from lct_datahub.api.errors import register_error_handlers
from lct_datahub.api.jobs import JobStore
from lct_datahub.api.routes import dark, eqe, jv


def create_app(work_root: Path | None = None) -> FastAPI:
    """建立 app；work_root 可指定工作資料夾根目錄（測試用），預設讀設定。"""
    app = FastAPI(title="LCT DataHub API", version="0.1.0")
    app.state.store = JobStore(work_root or load_config().work_root)
    register_error_handlers(app)
    for module in (jv, dark, eqe):
        app.include_router(module.router)

    @app.get("/api/health", tags=["系統"])
    def health() -> dict:
        """健康檢查：前端用來確認 API 是否在線。"""
        return {"status": "ok"}

    return app


app = create_app()


def run() -> None:
    """依設定啟動 uvicorn（813 部署時監聽 0.0.0.0:8000）。"""
    config = load_config()
    uvicorn.run("lct_datahub.api.main:app", host=config.host, port=config.port)

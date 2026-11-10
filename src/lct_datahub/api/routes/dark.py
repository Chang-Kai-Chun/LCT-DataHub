"""B 區暗電流：上傳 → 面積確認 → 最低點偏移 → 下載 Excel；暗電流圖（B-3）。

路由為 async def，讀檔、計算、畫圖等同步工作以 asyncio.to_thread() 交給執行緒（規則見完整文件 3-4）。
"""
import asyncio
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from lct_datahub.api.common import (
    AreaReportOut, AxisRange, download_response, get_store, png_response, read_uploads,
)
from lct_datahub.api.jobs import Job, JobStore, Section
from lct_datahub.core.area_check import check_areas
from lct_datahub.core.dark_current.area import AREA_OVERRIDE_NOTICE, apply_dark_area
from lct_datahub.core.dark_current.export import write_dark_excels
from lct_datahub.core.dark_current.integrate import dark_areas, read_dark_files
from lct_datahub.core.dark_current.select import select_dark_curves
from lct_datahub.core.dark_current.shift import shift_curves
from lct_datahub.core.dark_current.types import DarkCurve, ShiftMode
from lct_datahub.core.plotting import plot_dark_current

SECTION = Section.DARK
router = APIRouter(prefix=f"/api/{SECTION.value}", tags=["B 暗電流"])


# ---------- 資料模型 ----------
class DarkSettings(BaseModel):
    """工作設定：指定面積（null 為沿用檔內面積）與最低點處理方式。"""

    area: float | None = None
    shift_mode: ShiftMode = ShiftMode.KEEP


class DarkCurveOut(BaseModel):
    """一條曲線的摘要（給勾選清單與面積確認）。"""

    name: str
    instrument: str
    source: str
    area: float  # 目前使用的面積（cm²）
    area_from_file: bool  # False：明志由 |I|/J 反推，或已改用指定面積
    timestamp: str | None
    points: int
    removed_points: int  # 智慧截取掉的點數
    shift: float  # 偏移量（V）
    is_shifted: bool


class DarkJobOut(BaseModel):
    """工作內容。"""

    job_id: str
    skipped: list[str] = []
    settings: DarkSettings
    area_report: AreaReportOut  # 依檔內（原始）面積檢查
    area_notice: str = AREA_OVERRIDE_NOTICE  # 改用指定面積前要給使用者看的警告
    curves: list[DarkCurveOut]


class DarkPlotIn(BaseModel):
    """B-3 暗電流圖參數：Y 軸為對數，下限需大於 0。"""

    names: list[str]
    x_range: AxisRange = None
    y_range: AxisRange = None


# ---------- 同步工作（在執行緒中執行） ----------
@lru_cache(maxsize=32)
def _read_raw(paths: tuple[Path, ...]) -> tuple[DarkCurve, ...]:
    """讀原始檔（快取：原始檔上傳後不會再變）。"""
    return tuple(read_dark_files(list(paths)))


def _state(store: JobStore, job: Job) -> tuple[list[DarkCurve], DarkSettings, list[DarkCurve]]:
    """回傳 (原始曲線, 設定, 套用面積與偏移後的曲線)。"""
    raw = list(_read_raw(tuple(job.raw_files())))
    settings = store.load_settings(job, DarkSettings)
    curves = apply_dark_area(raw, settings.area) if settings.area is not None else raw
    return raw, settings, shift_curves(curves, settings.shift_mode)


def _job_out(store: JobStore, job: Job, skipped: list[str] | None = None) -> DarkJobOut:
    """組出工作內容回應。"""
    raw, settings, curves = _state(store, job)
    return DarkJobOut(
        job_id=job.id,
        skipped=skipped or [],
        settings=settings,
        area_report=AreaReportOut.from_report(check_areas(dark_areas(raw))),
        curves=[
            DarkCurveOut(
                name=c.name, instrument=c.instrument.value, source=c.source, area=c.area,
                area_from_file=c.area_from_file, timestamp=c.timestamp, points=len(c.data),
                removed_points=c.removed_points, shift=c.shift, is_shifted=c.is_shifted,
            )
            for c in curves
        ],
    )


def _create(store: JobStore, uploads: list[tuple[str, bytes]]) -> DarkJobOut:
    """建立工作並讀檔。"""
    result = store.create(SECTION, uploads)
    return _job_out(store, result.job, result.skipped)


def _update(store: JobStore, job_id: str, body: DarkSettings) -> DarkJobOut:
    """驗證並儲存設定。"""
    job = store.get(SECTION, job_id)
    if body.area is not None:
        apply_dark_area([], body.area)  # 只做驗證：面積必須是大於 0 的數值
    store.save_settings(job, body)
    return _job_out(store, job)


def _excel(store: JobStore, job_id: str):
    """寫出 Excel 並組出下載回應。"""
    job = store.get(SECTION, job_id)
    _, _, curves = _state(store, job)
    paths = write_dark_excels(job.output_dir, curves)
    return download_response(paths, job.output_dir / "Dark.zip")


def _dark_png(store: JobStore, job_id: str, body: DarkPlotIn):
    """畫 B-3 暗電流圖。"""
    _, _, curves = _state(store, store.get(SECTION, job_id))
    chosen = select_dark_curves(curves, body.names)
    return png_response(plot_dark_current(chosen, body.y_range, body.x_range))


# ---------- 路由 ----------
@router.post("/jobs", response_model=DarkJobOut)
async def create_job(files: list[UploadFile] = File(...), store: JobStore = Depends(get_store)) -> DarkJobOut:
    """上傳暗電流檔（PD-QE、明志）並讀取；回應含面積檢查結果。"""
    uploads = await read_uploads(files)
    return await asyncio.to_thread(_create, store, uploads)


@router.get("/jobs/{job_id}", response_model=DarkJobOut)
async def get_job(job_id: str, store: JobStore = Depends(get_store)) -> DarkJobOut:
    """取得工作內容。"""
    return await asyncio.to_thread(lambda: _job_out(store, store.get(SECTION, job_id)))


@router.put("/jobs/{job_id}/settings", response_model=DarkJobOut)
async def update_settings(job_id: str, body: DarkSettings, store: JobStore = Depends(get_store)) -> DarkJobOut:
    """設定面積（會更動數據，前端須先顯示 area_notice）與最低點處理；面積不合理回 400。"""
    return await asyncio.to_thread(_update, store, job_id, body)


@router.get("/jobs/{job_id}/excel")
async def download_excel(job_id: str, store: JobStore = Depends(get_store)):
    """下載整合 Excel：依儀器各一份，兩份時打包成 zip。"""
    return await asyncio.to_thread(_excel, store, job_id)


@router.post("/jobs/{job_id}/plots/dark")
async def dark_plot(job_id: str, body: DarkPlotIn, store: JobStore = Depends(get_store)):
    """B-3：暗電流圖 PNG（有偏移時右上角註記 shift）。"""
    return await asyncio.to_thread(_dark_png, store, job_id, body)

"""B 區暗電流：上傳 → 面積確認 → 最低點偏移 → 下載 Excel；元件分組（只影響畫圖勾選）；暗電流圖（B-3）。

路由為 async def，讀檔、計算、畫圖等同步工作以 asyncio.to_thread() 交給執行緒（規則見完整文件 3-4）。
"""
import asyncio
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from lct_datahub.api.common import (
    AreaReportOut, AxisRange, download_response, get_store, png_response, read_uploads, upload_project,
)
from lct_datahub.api.projects import Project
from lct_datahub.api.grouping import (
    ConditionModel, ConditionsIn, GroupingIn, GroupingOut, confirm_grouping, preview_grouping,
)
from lct_datahub.api.jobs import Job, JobStore, Section
from lct_datahub.core.area_check import check_areas
from lct_datahub.core.dark_current.area import AREA_OVERRIDE_NOTICE, apply_dark_area
from lct_datahub.core.dark_current.export import write_dark_excels
from lct_datahub.core.dark_current.integrate import dark_areas, is_dark_file, read_dark_files
from lct_datahub.core.dark_current.select import device_list, device_of, select_dark_curves
from lct_datahub.core.dark_current.shift import shift_curves
from lct_datahub.core.dark_current.types import DarkCurve, ShiftMode
from lct_datahub.core.plotting import plot_dark_current
from lct_datahub.core.sample_id import SampleId

SECTION = Section.DARK
router = APIRouter(prefix=f"/api/{SECTION.value}", tags=["B 暗電流"])


# ---------- 資料模型 ----------
class DarkSettingsIn(BaseModel):
    """PUT settings 的內容：指定面積（null 為沿用檔內面積）與最低點處理方式。"""

    area: float | None = None
    shift_mode: ShiftMode = ShiftMode.KEEP


class DarkSettings(DarkSettingsIn):
    """工作設定（存在 settings.json）：另含已確認的元件分組（null 為尚未分組，只影響畫圖勾選的排列）。

    area_confirmed：使用者已在面積視窗做過選擇（重開專案時不必再問）。
    """

    area_confirmed: bool = False
    conditions: list[ConditionModel] | None = None


class DarkCurveOut(BaseModel):
    """一條曲線的摘要（給勾選清單與面積確認）。"""

    name: str
    device: str | None  # 所屬元件（名稱開頭的代號，G1-1 → G1）；無法辨識為 null
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
    devices: list[str]  # 所有元件（分組用的樣品清單），依代號排序
    project_conditions: list[str]  # 專案統一的條件名稱（分組只能用這些）
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
        devices=[str(d) for d in device_list(curves)],
        project_conditions=store.project_conditions(job),
        curves=[
            DarkCurveOut(
                name=c.name, device=_device_text(c.name), instrument=c.instrument.value, source=c.source, area=c.area,
                area_from_file=c.area_from_file, timestamp=c.timestamp, points=len(c.data),
                removed_points=c.removed_points, shift=c.shift, is_shifted=c.is_shifted,
            )
            for c in curves
        ],
    )


def _create(store: JobStore, uploads: list[tuple[str, bytes]], project: Project) -> DarkJobOut:
    """在專案中建立工作並讀檔（取代專案原本的 B 區工作）；Excel 檔名沒有 _abs 的略過（is_dark_file）。"""
    result = store.create(SECTION, uploads, project, accept=is_dark_file)
    return _job_out(store, result.job, result.skipped)


def _device_text(name: str) -> str | None:
    """曲線所屬元件的文字（無法辨識為 None）。"""
    device = device_of(name)
    return str(device) if device else None


def _devices(store: JobStore, job: Job) -> list[SampleId]:
    """工作中所有元件（由原始檔的曲線名稱取得，與面積、偏移無關）。"""
    return device_list(list(_read_raw(tuple(job.raw_files()))))


def _update(store: JobStore, job_id: str, body: DarkSettingsIn) -> DarkJobOut:
    """驗證並儲存面積與偏移方式（已確認的分組保留不動）。"""
    job = store.get(SECTION, job_id)
    if body.area is not None:
        apply_dark_area([], body.area)  # 只做驗證：面積必須是大於 0 的數值
    settings = store.load_settings(job, DarkSettings)
    store.save_settings(job, settings.model_copy(update={**body.model_dump(), "area_confirmed": True}))
    return _job_out(store, job)


def _preview(store: JobStore, job_id: str, body: GroupingIn) -> GroupingOut:
    """依分組方式預填元件分組（不存檔）。"""
    job = store.get(SECTION, job_id)
    return preview_grouping(_devices(store, job), body, store.project_conditions(job))


def _confirm(store: JobStore, job_id: str, body: ConditionsIn) -> DarkJobOut:
    """驗證並儲存元件分組（所有元件都須分配）。"""
    job = store.get(SECTION, job_id)
    models = confirm_grouping(_devices(store, job), body, store.project_conditions(job))
    settings = store.load_settings(job, DarkSettings)
    store.save_settings(job, settings.model_copy(update={"conditions": models}))
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
async def create_job(
    files: list[UploadFile] = File(...),
    project: Project = Depends(upload_project),
    store: JobStore = Depends(get_store),
) -> DarkJobOut:
    """上傳暗電流檔（PD-QE、明志）到專案（?user=&project=）並讀取；回應含面積檢查結果。"""
    uploads = await read_uploads(files)
    return await asyncio.to_thread(_create, store, uploads, project)


@router.get("/jobs/{job_id}", response_model=DarkJobOut)
async def get_job(job_id: str, store: JobStore = Depends(get_store)) -> DarkJobOut:
    """取得工作內容。"""
    return await asyncio.to_thread(lambda: _job_out(store, store.get(SECTION, job_id)))


@router.put("/jobs/{job_id}/settings", response_model=DarkJobOut)
async def update_settings(job_id: str, body: DarkSettingsIn, store: JobStore = Depends(get_store)) -> DarkJobOut:
    """設定面積（會更動數據，前端須先顯示 area_notice）與最低點處理；面積不合理回 400。"""
    return await asyncio.to_thread(_update, store, job_id, body)


@router.post("/jobs/{job_id}/grouping/preview", response_model=GroupingOut)
async def preview_groups(job_id: str, body: GroupingIn, store: JobStore = Depends(get_store)) -> GroupingOut:
    """依分組方式預填元件分組（不存檔）；前端微調後再用 PUT conditions 確認。"""
    return await asyncio.to_thread(_preview, store, job_id, body)


@router.put("/jobs/{job_id}/conditions", response_model=DarkJobOut)
async def confirm_conditions(job_id: str, body: ConditionsIn, store: JobStore = Depends(get_store)) -> DarkJobOut:
    """確認元件分組（只影響畫圖勾選的排列，不影響 Excel）；未全部分配回 400。"""
    return await asyncio.to_thread(_confirm, store, job_id, body)


@router.get("/jobs/{job_id}/excel")
async def download_excel(job_id: str, store: JobStore = Depends(get_store)):
    """下載整合 Excel：依儀器各一份，兩份時打包成 zip。"""
    return await asyncio.to_thread(_excel, store, job_id)


@router.post("/jobs/{job_id}/plots/dark")
async def dark_plot(job_id: str, body: DarkPlotIn, store: JobStore = Depends(get_store)):
    """B-3：暗電流圖 PNG（有偏移時右上角註記 shift）。"""
    return await asyncio.to_thread(_dark_png, store, job_id, body)

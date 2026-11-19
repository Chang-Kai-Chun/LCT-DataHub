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
from lct_datahub.core.dark_current.integrate import accepts_upload, dark_areas, read_dark_files_with_signed
from lct_datahub.core.dark_current.select import device_list, device_of, select_dark_curves
from lct_datahub.core.dark_current.shift import shift_curves
from lct_datahub.core.dark_current.extract import DarkExtract, extract_all
from lct_datahub.core.dark_current.types import DarkCurve, ExtractBias, ShiftMode
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
    extract_bias: ExtractBias = ExtractBias.ZERO  # B-4：E 區與報告使用的暗電流電壓（預設 0 V）


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
    unpaired_signed: list[str] = []  # 明志未取絕對值的檔中，找不到同名 _abs 曲線的檔名（未使用）
    settings: DarkSettings
    area_report: AreaReportOut  # 依檔內（原始）面積檢查
    area_notice: str = AREA_OVERRIDE_NOTICE  # 改用指定面積前要給使用者看的警告
    devices: list[str]  # 所有元件（分組用的樣品清單），依代號排序
    project_conditions: list[str]  # 專案統一的條件名稱（分組只能用這些）
    curves: list[DarkCurveOut]


class ExtractRowOut(BaseModel):
    """B-4 一條曲線的擷取值；電壓的鍵為字串（"0"、"-0.1"、"-0.5"）。"""

    name: str
    device: str | None
    instrument: str
    shift: float  # 偏移量（V）；0 為未偏移
    area: float  # cm²
    rsh: float | None  # Ω（−0.03～0.03 V 擬合）
    rsh_area: float | None  # Ω·cm²
    jd: dict[str, float | None]  # A/cm²
    id: dict[str, float | None]  # A
    reference_rsh: float | None  # PD-QE 儀器對照（未偏移＝表上 Rsh、偏移後＝表上 Rs）
    current_source: str  # Rsh、Id 所用電流的來源（檔內電流／未取絕對值的同名檔／由絕對值還原）


class ExtractOut(BaseModel):
    """B-4 擷取值：目前選定的暗電流電壓與每條曲線的值。"""

    bias: ExtractBias
    biases: list[ExtractBias] = list(ExtractBias)
    rows: list[ExtractRowOut]


class ExtractBiasIn(BaseModel):
    """選擇 E 區使用的暗電流電壓。"""

    bias: ExtractBias


class DarkPlotIn(BaseModel):
    """B-3 暗電流圖參數：Y 軸為對數，下限需大於 0。"""

    names: list[str]
    x_range: AxisRange = None
    y_range: AxisRange = None


# ---------- 同步工作（在執行緒中執行） ----------
@lru_cache(maxsize=32)
def _read_all(paths: tuple[Path, ...]) -> tuple[tuple[DarkCurve, ...], tuple[str, ...]]:
    """讀原始檔（快取：原始檔上傳後不會再變）；回傳 (曲線, 找不到對應曲線的未取絕對值檔名)。"""
    curves, unpaired = read_dark_files_with_signed(list(paths))
    return tuple(curves), tuple(unpaired)


def _read_raw(paths: tuple[Path, ...]) -> tuple[DarkCurve, ...]:
    """原始曲線（未取絕對值的檔已附到同名曲線）。"""
    return _read_all(paths)[0]


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
        unpaired_signed=list(_read_all(tuple(job.raw_files()))[1]),
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
    """在專案中建立工作並讀檔（取代專案原本的 B 區工作）；明志 Excel 沒有 _abs 的作為未取絕對值的檔（只供 B-4）。"""
    result = store.create(SECTION, uploads, project, accept=accepts_upload)
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


def _bias_key(bias: ExtractBias) -> str:
    """電壓的字串鍵（0.0 → "0"、-0.1 → "-0.1"）。"""
    return f"{bias.value:g}"


def _extract(store: JobStore, job_id: str) -> ExtractOut:
    """B-4 擷取值（使用目前的面積與偏移設定）。"""
    job = store.get(SECTION, job_id)
    _, settings, curves = _state(store, job)
    rows = [
        ExtractRowOut(
            name=e.name, device=_device_text(e.name), instrument=e.instrument.value, shift=e.shift, area=e.area,
            rsh=e.rsh, rsh_area=e.rsh_area,
            jd={_bias_key(b): v for b, v in e.jd.items()}, id={_bias_key(b): v for b, v in e.id.items()},
            reference_rsh=e.reference_rsh, current_source=e.current_source.value,
        )
        for e in extract_all(curves)
    ]
    return ExtractOut(bias=settings.extract_bias, rows=rows)


def _set_extract_bias(store: JobStore, job_id: str, bias: ExtractBias) -> ExtractOut:
    """儲存 E 區使用的暗電流電壓。"""
    job = store.get(SECTION, job_id)
    settings = store.load_settings(job, DarkSettings)
    store.save_settings(job, settings.model_copy(update={"extract_bias": bias}))
    return _extract(store, job_id)


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


def job_samples(store: JobStore, job: Job) -> list[str]:
    """工作中的樣品（給專案總覽分組；B 區樣品＝曲線名稱開頭代號）。"""
    return [str(d) for d in _devices(store, job)]


def project_extracts(store: JobStore, project: Project) -> list[DarkExtract]:
    """專案目前 B 區工作的 B-4 擷取值（套用目前的面積與偏移）；專案沒有 B 區工作時為空清單（D、E 區使用）。"""
    job_id = project.info.jobs.get(SECTION.value)
    if not job_id:
        return []
    _, _, curves = _state(store, store.get(SECTION, job_id))
    return extract_all(curves)


@router.get("/jobs/{job_id}/extract", response_model=ExtractOut)
async def get_extract(job_id: str, store: JobStore = Depends(get_store)) -> ExtractOut:
    """B-4 擷取值：每條曲線的 Rsh、A·Rsh、0／−0.1／−0.5 V 的 Jd 與 Id（有偏移時用偏移後的電壓）。"""
    return await asyncio.to_thread(_extract, store, job_id)


@router.put("/jobs/{job_id}/extract-bias", response_model=ExtractOut)
async def set_extract_bias(job_id: str, body: ExtractBiasIn, store: JobStore = Depends(get_store)) -> ExtractOut:
    """選擇 E 區使用的暗電流電壓（0、-0.1、-0.5 V；其他值回 422）。"""
    return await asyncio.to_thread(_set_extract_bias, store, job_id, body.bias)


def project_dark_curves(store: JobStore, project: Project) -> list[DarkCurve]:
    """專案目前 B 區工作的暗電流曲線（套用目前的面積與偏移）；沒有 B 區工作時為空清單（報告輸出使用）。"""
    job_id = project.info.jobs.get(SECTION.value)
    if not job_id:
        return []
    _, _, curves = _state(store, store.get(SECTION, job_id))
    return curves

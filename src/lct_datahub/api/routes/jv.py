"""A 區 JV：上傳 → 面積確認 → 分組 → 下載 ALL_Data；Box 圖（A-2）與 JV 曲線圖（A-3）。

Box 表與篩選不存在伺服器：每次由前端送出方向、範圍與手動保留設定，伺服器重新計算。
路由為 async def，讀檔、計算、畫圖等同步工作以 asyncio.to_thread() 交給執行緒（規則見完整文件 3-4）。
"""
import asyncio
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel

from lct_datahub.api.common import (
    AreaIn, AreaReportOut, AxisRange, download_response, get_store, json_value, png_response, read_uploads,
    upload_project,
)
from lct_datahub.api.projects import Project
from lct_datahub.api import grouping as shared_grouping  # 路由函式名稱與共用函式同名，以模組名稱呼叫
from lct_datahub.api.grouping import ConditionModel, ConditionsIn, GroupingIn, GroupingOut
from lct_datahub.api.grouping import to_core as _to_conditions
from lct_datahub.api.jobs import Job, JobStore, Section
from lct_datahub.core.area_check import check_areas
from lct_datahub.core.jv.area import AREA_OVERRIDE_NOTICE, RECOMPUTED_PARAMS, apply_area
from lct_datahub.core.jv.box import apply_ranges, box_data, build_box_table, set_keep
from lct_datahub.core.jv.curve import DEFAULT_Y_RANGE, available_samples, select_curves
from lct_datahub.core.jv.export import write_excel
from lct_datahub.core.jv.integrate import jv_areas, missing_samples
from lct_datahub.core.jv.reader import read_jv_files
from lct_datahub.core.jv.types import Condition, Direction, DirectionMode, GroupingError, JVFile, JVParam, ValueRange
from lct_datahub.core.plotting import plot_box, plot_jv_curves
from lct_datahub.core.sample_id import parse_sample_id

SECTION = Section.JV
router = APIRouter(prefix=f"/api/{SECTION.value}", tags=["A JV"])
EXCEL_NAME = "ALL_Data.xlsx"


# ---------- 資料模型（分組相關的模型在 api/grouping.py，與 B 區共用） ----------
class JVSettings(BaseModel):
    """工作設定：指定面積（null 為沿用檔內面積）與已確認的分組（null 為尚未分組）。

    area_confirmed：使用者已在面積視窗做過選擇（重開專案時不必再問）。
    """

    area: float | None = None
    area_confirmed: bool = False
    conditions: list[ConditionModel] | None = None


class JVFileOut(BaseModel):
    """一個檔案的摘要。"""

    filename: str
    sample: str
    direction: Direction
    pixels: list[int]


class MissingOut(BaseModel):
    """條件中列出、但找不到檔案的樣品與方向。"""

    condition: str
    sample: str
    direction: Direction


class JVJobOut(BaseModel):
    """工作內容。"""

    job_id: str
    skipped: list[str] = []
    settings: JVSettings
    area_report: AreaReportOut  # 依檔內（原始）面積檢查
    area_notice: str = AREA_OVERRIDE_NOTICE
    recomputed_params: list[JVParam] = list(RECOMPUTED_PARAMS)  # 改面積會重算的參數
    samples: list[str]  # 依數字排序
    project_conditions: list[str]  # 專案統一的條件名稱（分組只能用這些）
    files: list[JVFileOut]
    missing: list[MissingOut]  # 依已確認的分組檢查（FW、RV 都列，前端依需要篩選）


class RangeIn(BaseModel):
    """單一參數的篩選範圍；null 表示該端不限制。"""

    minimum: float | None = None
    maximum: float | None = None


class BoxIn(BaseModel):
    """Box 表參數：方向、數值範圍篩選、手動保留（列號 → True/False，最後套用）。"""

    mode: DirectionMode = DirectionMode.FW
    sample_directions: dict[str, Direction] = {}  # 只有 mode 為逐樣品選擇時使用
    ranges: dict[JVParam, RangeIn] = {}  # 只接受 PCE、Voc、Jsc、FF
    keep: dict[int, bool] = {}


class BoxPlotIn(BoxIn):
    """Box 圖參數。"""

    param: JVParam
    y_range: AxisRange = None


class CurvePlotIn(BaseModel):
    """JV 曲線圖參數。"""

    samples: list[str]
    directions: list[Direction] = [Direction.FW]
    y_range: tuple[float, float] = DEFAULT_Y_RANGE


# ---------- 讀檔與目前狀態 ----------
@lru_cache(maxsize=32)
def _read_raw(paths: tuple[Path, ...]) -> tuple[JVFile, ...]:
    """讀原始檔（快取：原始檔上傳後不會再變）。"""
    return tuple(read_jv_files(list(paths)))


def _state(store: JobStore, job: Job) -> tuple[list[JVFile], JVSettings, list[JVFile]]:
    """回傳 (原始檔案, 設定, 套用面積後的檔案)。"""
    raw = list(_read_raw(tuple(job.raw_files())))
    settings = store.load_settings(job, JVSettings)
    files = apply_area(raw, settings.area) if settings.area is not None else raw
    return raw, settings, files


def _require_conditions(settings: JVSettings) -> list[Condition]:
    """取出已確認的分組；尚未分組時拋出 GroupingError（400）。"""
    if not settings.conditions:
        raise GroupingError("請先完成分組")
    return _to_conditions(settings.conditions)


def _job_out(store: JobStore, job: Job, skipped: list[str] | None = None) -> JVJobOut:
    """組出工作內容回應。"""
    raw, settings, files = _state(store, job)
    missing = []
    if settings.conditions:
        missing = [
            MissingOut(condition=c, sample=str(s), direction=d)
            for c, s, d in missing_samples(files, _to_conditions(settings.conditions), (Direction.FW, Direction.RV))
        ]
    return JVJobOut(
        job_id=job.id,
        skipped=skipped or [],
        settings=settings,
        area_report=AreaReportOut.from_report(check_areas(jv_areas(raw))),
        samples=[str(s) for s in available_samples(files)],
        project_conditions=store.project_conditions(job),
        files=[
            JVFileOut(
                filename=f.name.filename, sample=str(f.name.sample), direction=f.name.direction,
                pixels=list(f.name.pixels),
            )
            for f in files
        ],
        missing=missing,
    )


def _box_table(files: list[JVFile], conditions: list[Condition], body: BoxIn):
    """依前端參數建立 Box 表：方向 → 範圍篩選 → 手動保留。"""
    sample_directions = {parse_sample_id(k): v for k, v in body.sample_directions.items()}
    table = build_box_table(files, conditions, body.mode, sample_directions or None)
    ranges = {p: ValueRange(r.minimum, r.maximum) for p, r in body.ranges.items()}
    table = apply_ranges(table, ranges)
    for keep in (True, False):
        rows = [row for row, value in body.keep.items() if value is keep]
        if rows:
            table = set_keep(table, rows, keep)
    return table


# ---------- 同步工作：上傳、面積、分組、Excel（在執行緒中執行） ----------
def _create(store: JobStore, uploads: list[tuple[str, bytes]], project: Project) -> JVJobOut:
    """在專案中建立工作並讀檔（取代專案原本的 A 區工作）。"""
    result = store.create(SECTION, uploads, project)
    return _job_out(store, result.job, result.skipped)


def _set_area(store: JobStore, job_id: str, area: float | None) -> JVJobOut:
    """驗證並儲存指定面積。"""
    job = store.get(SECTION, job_id)
    if area is not None:
        apply_area([], area)  # 只做驗證：面積必須是大於 0 的數值
    settings = store.load_settings(job, JVSettings)
    store.save_settings(job, settings.model_copy(update={"area": area, "area_confirmed": True}))
    return _job_out(store, job)


def _preview(store: JobStore, job_id: str, body: GroupingIn) -> GroupingOut:
    """依分組方式預填條件（不存檔）。"""
    job = store.get(SECTION, job_id)
    _, _, files = _state(store, job)
    return shared_grouping.preview_grouping(available_samples(files), body, store.project_conditions(job))


def _confirm(store: JobStore, job_id: str, body: ConditionsIn) -> JVJobOut:
    """驗證並儲存分組。"""
    job = store.get(SECTION, job_id)
    _, settings, files = _state(store, job)
    models = shared_grouping.confirm_grouping(available_samples(files), body, store.project_conditions(job))
    store.save_settings(job, settings.model_copy(update={"conditions": models}))
    return _job_out(store, job)


def _excel(store: JobStore, job_id: str, directions: list[Direction]):
    """寫出 ALL_Data.xlsx 並組出下載回應。"""
    job = store.get(SECTION, job_id)
    _, settings, files = _state(store, job)
    conditions = _to_conditions(settings.conditions) if settings.conditions else None
    path = job.output_dir / EXCEL_NAME
    write_excel(path, files, conditions, tuple(directions))
    return download_response([path], path)


# ---------- 同步工作：Box 圖、JV 曲線 ----------
def _box_rows(store: JobStore, job_id: str, body: BoxIn) -> list[dict]:
    """Box 表轉成 JSON 列。"""
    _, settings, files = _state(store, store.get(SECTION, job_id))
    table = _box_table(files, _require_conditions(settings), body)
    return [
        {"row": int(row), **{k: json_value(v) for k, v in record.items()}}
        for row, record in zip(table.index, table.to_dict("records"))
    ]


def _box_png(store: JobStore, job_id: str, body: BoxPlotIn):
    """畫單一參數的 Box 圖。"""
    _, settings, files = _state(store, store.get(SECTION, job_id))
    table = _box_table(files, _require_conditions(settings), body)
    return png_response(plot_box(box_data(table, body.param), body.param, y_range=body.y_range))


def _curve_png(store: JobStore, job_id: str, body: CurvePlotIn):
    """畫 JV 曲線疊圖。"""
    _, _, files = _state(store, store.get(SECTION, job_id))
    lines = select_curves(files, [parse_sample_id(s) for s in body.samples], body.directions)
    return png_response(plot_jv_curves(lines, body.y_range))


# ---------- 路由：上傳、面積、分組、Excel ----------
@router.post("/jobs", response_model=JVJobOut)
async def create_job(
    files: list[UploadFile] = File(...),
    project: Project = Depends(upload_project),
    store: JobStore = Depends(get_store),
) -> JVJobOut:
    """上傳 JV CSV（檔名如 G1 FW 432.csv）到專案（?user=&project=）並讀取；檔名或內容有問題回 422。"""
    uploads = await read_uploads(files)
    return await asyncio.to_thread(_create, store, uploads, project)


@router.get("/jobs/{job_id}", response_model=JVJobOut)
async def get_job(job_id: str, store: JobStore = Depends(get_store)) -> JVJobOut:
    """取得工作內容。"""
    return await asyncio.to_thread(lambda: _job_out(store, store.get(SECTION, job_id)))


@router.put("/jobs/{job_id}/area", response_model=JVJobOut)
async def set_area(job_id: str, body: AreaIn, store: JobStore = Depends(get_store)) -> JVJobOut:
    """面積確認：null 為忽略並繼續；數值會重算 J、Jsc、PCE（前端須先顯示 area_notice）。"""
    return await asyncio.to_thread(_set_area, store, job_id, body.area)


@router.post("/jobs/{job_id}/grouping/preview", response_model=GroupingOut)
async def preview_grouping(job_id: str, body: GroupingIn, store: JobStore = Depends(get_store)) -> GroupingOut:
    """依分組方式預填條件（不存檔）；之後由前端拖拉調整，再用 PUT conditions 確認。"""
    return await asyncio.to_thread(_preview, store, job_id, body)


@router.put("/jobs/{job_id}/conditions", response_model=JVJobOut)
async def confirm_conditions(job_id: str, body: ConditionsIn, store: JobStore = Depends(get_store)) -> JVJobOut:
    """確認分組並存檔；有樣品未分配、名稱重複或樣品重複歸組時回 400。"""
    return await asyncio.to_thread(_confirm, store, job_id, body)


@router.get("/jobs/{job_id}/excel")
async def download_excel(
    job_id: str,
    directions: list[Direction] = Query(default=[Direction.FW]),
    store: JobStore = Depends(get_store),
):
    """下載 ALL_Data.xlsx；已確認分組時依條件排版並加五張參數 sheet，否則全部樣品視為一個條件。"""
    return await asyncio.to_thread(_excel, store, job_id, directions)


# ---------- 路由：Box 圖（A-2）、JV 曲線（A-3） ----------
@router.post("/jobs/{job_id}/box/table")
async def box_table(job_id: str, body: BoxIn, store: JobStore = Depends(get_store)) -> list[dict]:
    """Box 表：每條曲線一列（row 為列號，手動保留時用），含條件、樣品、方向、Pixel、參數與 Keep。"""
    return await asyncio.to_thread(_box_rows, store, job_id, body)


@router.post("/jobs/{job_id}/box/plot")
async def box_plot(job_id: str, body: BoxPlotIn, store: JobStore = Depends(get_store)):
    """單一參數的 Box 圖 PNG（只畫 Keep 為 True 的值）。"""
    return await asyncio.to_thread(_box_png, store, job_id, body)


@router.post("/jobs/{job_id}/curves/plot")
async def curve_plot(job_id: str, body: CurvePlotIn, store: JobStore = Depends(get_store)):
    """JV 曲線疊圖 PNG：FW 實線、RV 虛線。"""
    return await asyncio.to_thread(_curve_png, store, job_id, body)


def job_samples(store: JobStore, job: Job) -> list[str]:
    """工作中的樣品（給專案總覽分組；A 區樣品即檔名的樣品代號）。"""
    _, _, files = _state(store, job)
    return [str(s) for s in available_samples(files)]

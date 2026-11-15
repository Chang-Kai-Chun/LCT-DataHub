"""C 區 EQE：上傳 → 樣品清單 → 舊型命名 → 分組 → 下載 Excel；EQE 圖（C-2）與 R-plot（C-3）。

- 舊型儀器的樣品會自動編號 S1、S2…，**必須先命名才能分組**（2026-11-15）：
  目前名稱仍等於原始自動編號的舊型樣品列在 unnamed，分組預覽與確認在 unnamed 不為空時回 400
- 分組單位與 B 區相同：樣品＝名稱開頭代號（G1-1、G1-2 → G1，core.sample_id.device_of）
- 改名後樣品組成改變時，已確認的分組失效（清除，須重新分組）

路由為 async def，讀檔、計算、畫圖等同步工作以 asyncio.to_thread() 交給執行緒（規則見完整文件 3-4）。
"""
import asyncio
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel

from lct_datahub.api.common import AxisRange, download_response, get_store, png_response, read_uploads, upload_project
from lct_datahub.api.grouping import (
    ConditionModel, ConditionsIn, GroupingIn, GroupingOut, confirm_grouping, preview_grouping,
)
from lct_datahub.api.jobs import Job, JobStore, Section
from lct_datahub.api.projects import Project
from lct_datahub.core.eqe.export import write_eqe_excels
from lct_datahub.core.eqe.integrate import read_eqe_files, rename_curves
from lct_datahub.core.eqe.select import select_eqe_curves
from lct_datahub.core.eqe.types import EqeCurve, EqeInstrument
from lct_datahub.core.jv.types import GroupingError
from lct_datahub.core.plotting import DEFAULT_EQE_RANGE, plot_eqe, plot_rplot
from lct_datahub.core.sample_id import SampleId, device_of, devices_of

SECTION = Section.EQE
router = APIRouter(prefix=f"/api/{SECTION.value}", tags=["C EQE"])


# ---------- 資料模型 ----------
class EqeSettings(BaseModel):
    """工作設定：改名對照（原名 → 新名，每次送出完整對照）與已確認的分組（null 為尚未分組）。"""

    names: dict[str, str] = {}
    conditions: list[ConditionModel] | None = None


class EqeCurveOut(BaseModel):
    """一個樣品（pixel）的摘要（給勾選清單）。"""

    name: str  # 目前名稱（改名後）
    original_name: str  # 讀檔時的名稱，改名對照以此為鍵
    device: str | None  # 所屬樣品（名稱開頭代號，G1-1 → G1）；無法辨識為 null
    instrument: str
    source: str
    points: int
    jsc: float  # 積分電流（mA/cm²）
    timestamp: str | None
    bias: float | None


class EqeJobOut(BaseModel):
    """工作內容。"""

    job_id: str
    skipped: list[str] = []  # 上傳時略過的檔案
    settings: EqeSettings
    devices: list[str]  # 所有樣品（分組用），依代號排序
    unnamed: list[str]  # 尚未命名的舊型樣品（目前名稱＝原始自動編號）；不為空時不能分組
    project_conditions: list[str]  # 專案統一的條件名稱（分組只能用這些）
    curves: list[EqeCurveOut]


class RenameIn(BaseModel):
    """改名：原名 → 新名（舊型樣品預設 S1、S2…）。"""

    names: dict[str, str]


class EqePlotIn(BaseModel):
    """C-2 EQE 圖參數：X 軸由使用者輸入（null 為自動），EQE 軸預設 0–100。"""

    names: list[str]
    x_range: AxisRange = None
    eqe_range: AxisRange = DEFAULT_EQE_RANGE
    jsc_range: AxisRange = None
    show_jsc: bool = True


class RplotIn(BaseModel):
    """C-3 R-plot 參數。"""

    names: list[str]
    x_range: AxisRange = None
    y_range: AxisRange = None


# ---------- 同步工作（在執行緒中執行） ----------
@lru_cache(maxsize=32)
def _read_raw(paths: tuple[Path, ...]) -> tuple[EqeCurve, ...]:
    """讀原始檔（快取：原始檔上傳後不會再變）。"""
    return tuple(read_eqe_files(list(paths)))


def _curves(store: JobStore, job: Job) -> tuple[list[EqeCurve], EqeSettings, list[EqeCurve]]:
    """回傳 (原始曲線, 設定, 套用改名後的曲線)。"""
    raw = list(_read_raw(tuple(job.raw_files())))
    settings = store.load_settings(job, EqeSettings)
    return raw, settings, rename_curves(raw, settings.names)


def _unnamed(raw: list[EqeCurve], curves: list[EqeCurve]) -> list[str]:
    """尚未命名的舊型樣品：目前名稱仍等於原始自動編號（S1、S2…）。"""
    return [c.name for r, c in zip(raw, curves) if r.instrument is EqeInstrument.OLD and c.name == r.name]


def _devices(curves: list[EqeCurve]) -> list[SampleId]:
    """所有樣品（分組的樣品清單）。"""
    return devices_of([c.name for c in curves])


def _device_text(name: str) -> str | None:
    """名稱所屬樣品的文字（無法辨識為 None）。"""
    device = device_of(name)
    return str(device) if device else None


def _job_out(store: JobStore, job: Job, skipped: list[str] | None = None) -> EqeJobOut:
    """組出工作內容回應。"""
    raw, settings, curves = _curves(store, job)
    return EqeJobOut(
        job_id=job.id,
        skipped=skipped or [],
        settings=settings,
        devices=[str(d) for d in _devices(curves)],
        unnamed=_unnamed(raw, curves),
        project_conditions=store.project_conditions(job),
        curves=[
            EqeCurveOut(
                name=c.name, original_name=r.name, device=_device_text(c.name), instrument=c.instrument.value,
                source=c.source, points=len(c.data), jsc=c.jsc, timestamp=c.timestamp, bias=c.bias,
            )
            for r, c in zip(raw, curves)
        ],
    )


def _create(store: JobStore, uploads: list[tuple[str, bytes]], project: Project) -> EqeJobOut:
    """在專案中建立工作並讀檔（取代專案原本的 C 區工作）。"""
    result = store.create(SECTION, uploads, project)
    return _job_out(store, result.job, result.skipped)


def _rename(store: JobStore, job_id: str, names: dict[str, str]) -> EqeJobOut:
    """驗證並儲存改名對照；樣品組成改變時清除已確認的分組（須重新分組）。"""
    job = store.get(SECTION, job_id)
    raw, settings, before = _curves(store, job)
    after = rename_curves(raw, names)  # 先驗證，不合理就拋出 EqeNameError
    conditions = settings.conditions
    if conditions and _devices(after) != _devices(before):
        conditions = None
    store.save_settings(job, settings.model_copy(update={"names": names, "conditions": conditions}))
    return _job_out(store, job)


def _require_named(raw: list[EqeCurve], curves: list[EqeCurve]) -> None:
    """還有未命名的舊型樣品時拋出 GroupingError（400）。"""
    unnamed = _unnamed(raw, curves)
    if unnamed:
        raise GroupingError(f"請先為舊型儀器的樣品命名再分組：{'、'.join(unnamed)}")


def _preview(store: JobStore, job_id: str, body: GroupingIn) -> GroupingOut:
    """依分組方式預填樣品分組（不存檔）。"""
    job = store.get(SECTION, job_id)
    raw, _, curves = _curves(store, job)
    _require_named(raw, curves)
    return preview_grouping(_devices(curves), body, store.project_conditions(job))


def _confirm(store: JobStore, job_id: str, body: ConditionsIn) -> EqeJobOut:
    """驗證並儲存樣品分組（所有樣品都須分配）。"""
    job = store.get(SECTION, job_id)
    raw, settings, curves = _curves(store, job)
    _require_named(raw, curves)
    models = confirm_grouping(_devices(curves), body, store.project_conditions(job))
    store.save_settings(job, settings.model_copy(update={"conditions": models}))
    return _job_out(store, job)


def _excel(store: JobStore, job_id: str):
    """寫出 Excel 並組出下載回應。"""
    job = store.get(SECTION, job_id)
    _, _, curves = _curves(store, job)
    paths = write_eqe_excels(job.output_dir, curves)
    return download_response(paths, job.output_dir / "EQE.zip")


def _eqe_png(store: JobStore, job_id: str, body: EqePlotIn):
    """畫 C-2 EQE 圖。"""
    _, _, curves = _curves(store, store.get(SECTION, job_id))
    chosen = select_eqe_curves(curves, body.names)
    return png_response(plot_eqe(chosen, body.x_range, body.eqe_range, body.jsc_range, body.show_jsc))


def _rplot_png(store: JobStore, job_id: str, body: RplotIn):
    """畫 C-3 R-plot。"""
    _, _, curves = _curves(store, store.get(SECTION, job_id))
    chosen = select_eqe_curves(curves, body.names)
    return png_response(plot_rplot(chosen, body.x_range, body.y_range))


# ---------- 路由 ----------
@router.post("/jobs", response_model=EqeJobOut)
async def create_job(
    files: list[UploadFile] = File(...),
    project: Project = Depends(upload_project),
    store: JobStore = Depends(get_store),
) -> EqeJobOut:
    """上傳 EQE 檔（txt、xls、xlsx）到專案（?user=&project=）並讀取；檔案有問題回 422。"""
    uploads = await read_uploads(files)
    return await asyncio.to_thread(_create, store, uploads, project)


@router.get("/jobs/{job_id}", response_model=EqeJobOut)
async def get_job(job_id: str, store: JobStore = Depends(get_store)) -> EqeJobOut:
    """取得工作內容。"""
    return await asyncio.to_thread(lambda: _job_out(store, store.get(SECTION, job_id)))


@router.put("/jobs/{job_id}/names", response_model=EqeJobOut)
async def rename(job_id: str, body: RenameIn, store: JobStore = Depends(get_store)) -> EqeJobOut:
    """改名（舊型樣品須先命名才能分組）；空白、重複或原名不存在回 400；樣品組成改變時清除分組。"""
    return await asyncio.to_thread(_rename, store, job_id, body.names)


@router.post("/jobs/{job_id}/grouping/preview", response_model=GroupingOut)
async def preview_groups(job_id: str, body: GroupingIn, store: JobStore = Depends(get_store)) -> GroupingOut:
    """依分組方式預填樣品分組（不存檔）；舊型樣品未命名回 400。"""
    return await asyncio.to_thread(_preview, store, job_id, body)


@router.put("/jobs/{job_id}/conditions", response_model=EqeJobOut)
async def confirm_conditions(job_id: str, body: ConditionsIn, store: JobStore = Depends(get_store)) -> EqeJobOut:
    """確認樣品分組；未全部分配、名稱不在專案條件中或舊型樣品未命名回 400。"""
    return await asyncio.to_thread(_confirm, store, job_id, body)


@router.get("/jobs/{job_id}/excel")
async def download_excel(job_id: str, store: JobStore = Depends(get_store)):
    """下載整合 Excel：依儀器各一份，兩份時打包成 zip。"""
    return await asyncio.to_thread(_excel, store, job_id)


@router.post("/jobs/{job_id}/plots/eqe")
async def eqe_plot(job_id: str, body: EqePlotIn, store: JobStore = Depends(get_store)):
    """C-2：EQE（左軸）加積分電流（右軸）的 PNG。"""
    return await asyncio.to_thread(_eqe_png, store, job_id, body)


@router.post("/jobs/{job_id}/plots/rplot")
async def rplot(job_id: str, body: RplotIn, store: JobStore = Depends(get_store)):
    """C-3：R-plot（SR，A/W）的 PNG。"""
    return await asyncio.to_thread(_rplot_png, store, job_id, body)


def job_samples(store: JobStore, job: Job) -> list[str]:
    """工作中的樣品（給專案總覽分組；C 區樣品＝改名後名稱開頭代號）。"""
    _, _, curves = _curves(store, job)
    return [str(d) for d in _devices(curves)]

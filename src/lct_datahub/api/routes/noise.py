"""D 區 Noise：上傳 → 分組平均（自動）→ 條件分組（只影響畫圖勾選）→ 雜訊圖（D-2）→ 1 Hz 數值 → Excel。

- 頻譜一律由時域電流重算；預設標準定義，可切換儀器定義（設定存在 settings.json）
- 同一樣品＋偏壓的檔做 n 次平均；溢位、削平排除，未穩定、底線不一致只警告
- 參考線（選用）：同專案 B 區的 B-4 擷取值（同偏壓的 Id、Rsh），自動配對、可手動指定
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
from lct_datahub.api.routes.dark import project_extracts
from lct_datahub.core.noise.export import column_names, write_noise_excel
from lct_datahub.core.noise.group import build_groups
from lct_datahub.core.noise.pairing import NO_PAIR, DarkPair, pair_group
from lct_datahub.core.noise.reader import is_noise_file, read_noise_files
from lct_datahub.core.noise.reference import ReferenceKind
from lct_datahub.core.noise.spectrum import value_at
from lct_datahub.core.noise.types import BiasSource, NoiseDefinition, NoiseGroup, NoiseRecord
from lct_datahub.core.plotting import plot_noise
from lct_datahub.core.sample_id import SampleId, device_of

SECTION = Section.NOISE
router = APIRouter(prefix=f"/api/{SECTION.value}", tags=["D Noise"])
EXCEL_NAME = "Noise.xlsx"
SECTION_DARK = Section.DARK.value  # 參考線取自同專案的 B 區


# ---------- 資料模型 ----------
class NoiseSettingsIn(BaseModel):
    """PUT settings 的內容：雜訊密度的換算定義。"""

    definition: NoiseDefinition = NoiseDefinition.STANDARD


class NoiseSettings(NoiseSettingsIn):
    """工作設定（存在 settings.json）：另含已確認的條件分組與參考線的手動配對。"""

    conditions: list[ConditionModel] | None = None
    reference_pairs: dict[str, str] = {}  # 組名 → 暗電流曲線名稱（"" 為不配對）


class ExclusionOut(BaseModel):
    """被排除的檔。"""

    source: str
    reason: str
    detail: str


class NoiseGroupOut(BaseModel):
    """一組（同樣品、偏壓、儀器、量測設定）的摘要。"""

    name: str  # 組名（圖例、勾選清單、Excel 欄名；不重複）
    sample: str
    device: str | None  # 所屬樣品代號（G1-2 → G1）；無法辨識為 null
    bias: float
    bias_default: bool  # 偏壓由預設推定（檔名沒有偏壓）
    instrument: str
    n: int
    files: list[str]  # 納入平均的檔
    excluded: list[ExclusionOut]
    notes: list[str]
    noise_1hz: float | None  # A/√Hz
    peak_current: float | None  # A
    floor_ratio: float | None  # n 次底線最大÷最小
    duration: float  # s
    interval: float  # s


class NoiseJobOut(BaseModel):
    """工作內容。"""

    job_id: str
    skipped: list[str] = []
    settings: NoiseSettings
    devices: list[str]  # 所有樣品代號（分組用）
    project_conditions: list[str]
    groups: list[NoiseGroupOut]


class ReferenceOut(BaseModel):
    """一組的參考線配對結果（d-4 數值表）。"""

    name: str
    dark_name: str | None  # 配對到的暗電流曲線
    dark_instrument: str | None
    manual: bool
    note: str
    rsh: float | None  # Ω
    dark_current: float | None  # A（同偏壓）
    shot: float | None  # A/√Hz
    thermal: float | None
    total: float | None
    noise_1hz: float | None
    ratio: float | None  # 實測 ÷ 理論（> 1 正常；< 1 代表量測或換算有問題）


class ReferencesOut(BaseModel):
    """全部組的配對結果與可選的暗電流曲線（手動配對的下拉選單）。"""

    has_dark: bool  # 專案是否有 B 區工作
    dark_names: list[str]
    rows: list[ReferenceOut]


class ReferencePairsIn(BaseModel):
    """手動配對：組名 → 暗電流曲線名稱（"" 為不配對；null 為取消手動、回到自動）。"""

    pairs: dict[str, str | None]


class NoisePlotIn(BaseModel):
    """D-2 雜訊圖參數：兩軸皆為對數，下限需大於 0。"""

    names: list[str]
    x_range: AxisRange = None
    y_range: AxisRange = None
    show_band: bool = True  # n ≥ 2 時畫最小～最大範圍帶
    references: bool = False  # 畫 Shot＋Thermal 參考線（需同專案有 B 區）


# ---------- 同步工作（在執行緒中執行） ----------
@lru_cache(maxsize=32)
def _read_raw(paths: tuple[Path, ...]) -> tuple[NoiseRecord, ...]:
    """讀原始檔（快取：原始檔上傳後不會再變）。"""
    return tuple(read_noise_files(list(paths)))


def _state(store: JobStore, job: Job) -> tuple[NoiseSettings, list[NoiseGroup], list[str]]:
    """回傳 (設定, 分組結果, 組名)。"""
    settings = store.load_settings(job, NoiseSettings)
    groups = build_groups(list(_read_raw(tuple(job.raw_files()))), settings.definition)
    return settings, groups, column_names(groups)


def _device_text(sample: str) -> str | None:
    """樣品所屬的樣品代號文字（無法辨識為 None）。"""
    device = device_of(sample)
    return str(device) if device else None


def _devices(groups: list[NoiseGroup]) -> list[SampleId]:
    """所有樣品代號（不重複，依代號排序）。"""
    return sorted({d for g in groups if (d := device_of(g.sample)) is not None})


def _group_out(group: NoiseGroup, name: str) -> NoiseGroupOut:
    """一組的摘要。"""
    return NoiseGroupOut(
        name=name, sample=group.sample, device=_device_text(group.sample), bias=group.bias,
        bias_default=group.bias_source is BiasSource.DEFAULT, instrument=group.instrument.value, n=group.n,
        files=[r.source for r in group.members],
        excluded=[ExclusionOut(source=e.source, reason=e.anomaly.value, detail=e.detail) for e in group.excluded],
        notes=group.notes, noise_1hz=value_at(group.freq, group.mean) if group.mean is not None else None,
        peak_current=group.peak_current, floor_ratio=group.floor_ratio, duration=group.duration,
        interval=group.interval,
    )


def _job_out(store: JobStore, job: Job, skipped: list[str] | None = None) -> NoiseJobOut:
    """組出工作內容回應。"""
    settings, groups, names = _state(store, job)
    return NoiseJobOut(
        job_id=job.id, skipped=skipped or [], settings=settings,
        devices=[str(d) for d in _devices(groups)], project_conditions=store.project_conditions(job),
        groups=[_group_out(g, n) for g, n in zip(groups, names)],
    )


def _create(store: JobStore, uploads: list[tuple[str, bytes]], project: Project) -> NoiseJobOut:
    """在專案中建立工作並讀檔（取代專案原本的 D 區工作）。"""
    result = store.create(SECTION, uploads, project, accept=is_noise_file)
    return _job_out(store, result.job, result.skipped)


def _update(store: JobStore, job_id: str, body: NoiseSettingsIn) -> NoiseJobOut:
    """儲存換算定義（分組與手動配對保留）。"""
    job = store.get(SECTION, job_id)
    settings = store.load_settings(job, NoiseSettings)
    store.save_settings(job, settings.model_copy(update=body.model_dump()))
    return _job_out(store, job)


def _preview(store: JobStore, job_id: str, body: GroupingIn) -> GroupingOut:
    """依分組方式預填條件分組（不存檔）。"""
    job = store.get(SECTION, job_id)
    _, groups, _ = _state(store, job)
    return preview_grouping(_devices(groups), body, store.project_conditions(job))


def _confirm(store: JobStore, job_id: str, body: ConditionsIn) -> NoiseJobOut:
    """驗證並儲存條件分組（所有樣品都須分配）。"""
    job = store.get(SECTION, job_id)
    _, groups, _ = _state(store, job)
    models = confirm_grouping(_devices(groups), body, store.project_conditions(job))
    settings = store.load_settings(job, NoiseSettings)
    store.save_settings(job, settings.model_copy(update={"conditions": models}))
    return _job_out(store, job)


def _pairs(store: JobStore, job: Job) -> tuple[list[DarkPair], list[str], bool, list[NoiseGroup], list[str]]:
    """每組的配對結果；回傳 (配對, 暗電流曲線名稱, 專案是否有 B 區, 組, 組名)。"""
    settings, groups, names = _state(store, job)
    project = store.project_of(job)
    extracts = project_extracts(store, project)
    pairs = [pair_group(g, extracts, settings.reference_pairs, key=n) for g, n in zip(groups, names)]
    return pairs, [e.name for e in extracts], SECTION_DARK in project.info.jobs, groups, names


def _line(pair: DarkPair, kind: ReferenceKind) -> float | None:
    """配對結果中某一種參考線的值。"""
    return next((line.value for line in pair.lines if line.kind is kind), None)


def _references(store: JobStore, job_id: str) -> ReferencesOut:
    """d-4：每組的 1 Hz 雜訊、配對到的暗電流、理論白雜訊與實測÷理論。"""
    job = store.get(SECTION, job_id)
    pairs, dark_names, has_dark, groups, names = _pairs(store, job)
    rows = []
    for pair, group, name in zip(pairs, groups, names):
        measured = value_at(group.freq, group.mean) if group.mean is not None else None
        total = pair.total
        rows.append(ReferenceOut(
            name=name, dark_name=pair.dark.name if pair.dark else None,
            dark_instrument=pair.dark.instrument.value if pair.dark else None, manual=pair.manual, note=pair.note,
            rsh=pair.dark.rsh if pair.dark else None, dark_current=pair.dark_current,
            shot=_line(pair, ReferenceKind.SHOT), thermal=_line(pair, ReferenceKind.THERMAL), total=total,
            noise_1hz=measured, ratio=measured / total if measured is not None and total else None,
        ))
    return ReferencesOut(has_dark=has_dark, dark_names=dark_names, rows=rows)


def _set_pairs(store: JobStore, job_id: str, body: ReferencePairsIn) -> ReferencesOut:
    """儲存手動配對（null 取消手動）；組名或暗電流名稱不存在時拋出 KeyError（400）。"""
    job = store.get(SECTION, job_id)
    _, dark_names, _, _, names = _pairs(store, job)
    settings = store.load_settings(job, NoiseSettings)
    pairs = dict(settings.reference_pairs)
    for name, dark in body.pairs.items():
        if name not in names:
            raise KeyError(f"沒有這一組：{name}")
        if dark is None:
            pairs.pop(name, None)
        elif dark != NO_PAIR and dark not in dark_names:
            raise KeyError(f"B 區沒有這條暗電流：{dark}")
        else:
            pairs[name] = dark
    store.save_settings(job, settings.model_copy(update={"reference_pairs": pairs}))
    return _references(store, job_id)


def _excel(store: JobStore, job_id: str):
    """寫出 Excel 並組出下載回應。"""
    job = store.get(SECTION, job_id)
    _, groups, _ = _state(store, job)
    path = job.output_dir / EXCEL_NAME
    write_noise_excel(path, groups)
    return download_response([path], job.output_dir / "Noise.zip")


def _noise_png(store: JobStore, job_id: str, body: NoisePlotIn):
    """畫 D-2 雜訊圖（勾選的組；可加範圍帶與參考線）。"""
    job = store.get(SECTION, job_id)
    if body.references:
        pairs, _, _, groups, names = _pairs(store, job)
    else:
        _, groups, names = _state(store, job)
        pairs = [None] * len(groups)
    by_name = dict(zip(names, zip(groups, pairs)))
    unknown = [n for n in body.names if n not in by_name]
    if unknown:
        raise KeyError(f"沒有這些組：{'、'.join(unknown)}")
    chosen = [by_name[n] for n in body.names]
    lines = [line for _, pair in chosen if pair is not None for line in pair.lines if line.kind is ReferenceKind.TOTAL]
    fig = plot_noise([g for g, _ in chosen], lines, body.x_range, body.y_range, show_band=body.show_band)
    return png_response(fig)


# ---------- 路由 ----------
@router.post("/jobs", response_model=NoiseJobOut)
async def create_job(
    files: list[UploadFile] = File(...),
    project: Project = Depends(upload_project),
    store: JobStore = Depends(get_store),
) -> NoiseJobOut:
    """上傳 noise 檔（明志、PD-QE 的 csv）到專案（?user=&project=）並分組平均；格式不符回 422。"""
    uploads = await read_uploads(files)
    return await asyncio.to_thread(_create, store, uploads, project)


@router.get("/jobs/{job_id}", response_model=NoiseJobOut)
async def get_job(job_id: str, store: JobStore = Depends(get_store)) -> NoiseJobOut:
    """取得工作內容（每組的 n、排除的檔、提醒、1 Hz 雜訊）。"""
    return await asyncio.to_thread(lambda: _job_out(store, store.get(SECTION, job_id)))


@router.put("/jobs/{job_id}/settings", response_model=NoiseJobOut)
async def update_settings(job_id: str, body: NoiseSettingsIn, store: JobStore = Depends(get_store)) -> NoiseJobOut:
    """切換雜訊密度的換算定義（標準／儀器）。"""
    return await asyncio.to_thread(_update, store, job_id, body)


@router.post("/jobs/{job_id}/grouping/preview", response_model=GroupingOut)
async def preview_groups(job_id: str, body: GroupingIn, store: JobStore = Depends(get_store)) -> GroupingOut:
    """依分組方式預填條件分組（不存檔）；前端微調後再用 PUT conditions 確認。"""
    return await asyncio.to_thread(_preview, store, job_id, body)


@router.put("/jobs/{job_id}/conditions", response_model=NoiseJobOut)
async def confirm_conditions(job_id: str, body: ConditionsIn, store: JobStore = Depends(get_store)) -> NoiseJobOut:
    """確認條件分組（只影響畫圖勾選的排列）；未全部分配回 400。"""
    return await asyncio.to_thread(_confirm, store, job_id, body)


@router.get("/jobs/{job_id}/references", response_model=ReferencesOut)
async def get_references(job_id: str, store: JobStore = Depends(get_store)) -> ReferencesOut:
    """d-4：每組的 1 Hz 雜訊與 B-4 配對、理論白雜訊（Shot＋Thermal）、實測÷理論。"""
    return await asyncio.to_thread(_references, store, job_id)


@router.put("/jobs/{job_id}/reference-pairs", response_model=ReferencesOut)
async def set_reference_pairs(
    job_id: str, body: ReferencePairsIn, store: JobStore = Depends(get_store),
) -> ReferencesOut:
    """手動指定參考線配對（"" 不配對、null 回到自動）；組名或暗電流不存在回 400。"""
    return await asyncio.to_thread(_set_pairs, store, job_id, body)


@router.get("/jobs/{job_id}/excel")
async def download_excel(job_id: str, store: JobStore = Depends(get_store)):
    """下載 Excel（Summary、Mean、Runs、Excluded）。"""
    return await asyncio.to_thread(_excel, store, job_id)


@router.post("/jobs/{job_id}/plots/noise")
async def noise_plot(job_id: str, body: NoisePlotIn, store: JobStore = Depends(get_store)):
    """D-2：雜訊圖 PNG（平均實線＋n 次範圍帶；可加 Shot＋Thermal 參考線）。"""
    return await asyncio.to_thread(_noise_png, store, job_id, body)


def job_samples(store: JobStore, job: Job) -> list[str]:
    """工作中的樣品代號（給專案總覽分組）。"""
    _, groups, _ = _state(store, job)
    return [str(d) for d in _devices(groups)]


def project_groups(store: JobStore, project: Project) -> list[tuple[str, NoiseGroup]]:
    """專案目前 D 區工作的 (組名, 組)，一律用標準定義（E 區算 D* 使用）；沒有 D 區工作時為空清單。"""
    job_id = project.info.jobs.get(SECTION.value)
    if not job_id:
        return []
    job = store.get(SECTION, job_id)
    groups = build_groups(list(_read_raw(tuple(job.raw_files()))), NoiseDefinition.STANDARD)
    return list(zip(column_names(groups), groups))

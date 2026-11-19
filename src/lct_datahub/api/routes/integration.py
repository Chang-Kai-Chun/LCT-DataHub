"""E 區 PD 數據整合：從同專案的 B（B-4）、C（EQE）、D（noise）算 D*（2026-11-19）。

- 不需要上傳；設定存在專案資料夾的 integration.json（偏壓、最多 3 個波長、手動配對）
- 以 pixel 計算；名稱配對、同一 pixel 有兩台儀器的數據時自動判斷並可手動選擇
- D* 四種：實測（D 區 1 Hz，標準定義）、Shot＋Thermal（理論極限）、Thermal、Shot；
  0 V 的 Shot 用曲線最低點的 |I|，其他偏壓用 B-4 該偏壓的 Id
路由為 async def，計算、畫圖以 asyncio.to_thread() 交給執行緒。
"""
import asyncio
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel

from lct_datahub.api.common import AxisRange, MediaType, get_store, png_response
from lct_datahub.api.jobs import JobStore, Section
from lct_datahub.api.projects import Project
from lct_datahub.api.routes.dark import project_extracts
from lct_datahub.api.routes.eqe import project_curves
from lct_datahub.api.routes.noise import project_groups
from lct_datahub.core.dark_current.types import ExtractBias
from lct_datahub.core.detectivity.compute import (
    MAX_WAVELENGTHS, DStarKind, PixelResult, check_wavelengths, compute_pixel,
)
from lct_datahub.core.detectivity.export import write_detectivity_excel
from lct_datahub.core.detectivity.pairing import PixelPairing, SourceKind, pair_pixels, to_input
from lct_datahub.core.plotting import plot_detectivity
from lct_datahub.core.sample_id import device_of

router = APIRouter(prefix="/api/users/{user}/projects/{project}/integration", tags=["E PD 數據整合"])
SETTINGS_FILE = "integration.json"
EXCEL_NAME = "Detectivity.xlsx"
OUTPUT_DIR = "integration"


# ---------- 資料模型 ----------
class IntegrationSettingsIn(BaseModel):
    """E 區設定：D* 偏壓（與 B-4 相同的三個）與指定波長（最多 3 個，nm）。"""

    bias: ExtractBias = ExtractBias.ZERO
    wavelengths: list[float] = []


class IntegrationSettings(IntegrationSettingsIn):
    """存在 integration.json：另含手動配對 {pixel: {區: 名稱或 ""}}。"""

    overrides: dict[str, dict[str, str]] = {}


class ChoiceIn(BaseModel):
    """手動配對一格：name 為名稱、"" 為不使用、null 為回到自動。"""

    pixel: str
    source: SourceKind
    name: str | None


class CandidateOut(BaseModel):
    """某一區的候選。"""

    name: str
    instrument: str


class SourceOut(BaseModel):
    """某一區選到的資料與候選。"""

    name: str | None
    instrument: str | None
    manual: bool
    candidates: list[CandidateOut]


class PeakOut(BaseModel):
    """最大 D* 與所在波長。"""

    value: float
    wavelength: float


class PixelOut(BaseModel):
    """一個 pixel 的配對與 D*。"""

    pixel: str
    device: str | None
    sources: dict[str, SourceOut]  # dark、eqe、noise
    area: float | None
    rsh: float | None
    dark_current: float | None  # Shot 用的 Id
    noises: dict[str, float | None]  # DStarKind value → A/√Hz
    peaks: dict[str, PeakOut | None]  # DStarKind value → 最大值
    at: dict[str, list[float | None]]  # DStarKind value → 每個指定波長的 D*
    responsivity_at: list[float | None]  # 每個指定波長的 R
    warnings: list[str]


class IntegrationOut(BaseModel):
    """E 區內容。"""

    settings: IntegrationSettings
    biases: list[ExtractBias] = list(ExtractBias)
    kinds: list[DStarKind] = list(DStarKind)
    max_wavelengths: int = MAX_WAVELENGTHS
    available: dict[str, bool]  # 專案是否有 B、C、D 區工作
    project_grouping: list[dict]  # 總覽分組（勾選清單排列用）
    pixels: list[PixelOut]


class DetectivityPlotIn(BaseModel):
    """D*(λ) 圖參數。"""

    pixels: list[str]
    kind: DStarKind = DStarKind.COMBINE
    x_range: AxisRange = None
    y_range: AxisRange = None
    log_y: bool = True


# ---------- 設定 ----------
def _settings_path(project: Project) -> Path:
    """integration.json 的路徑。"""
    return project.folder / SETTINGS_FILE


def _load(project: Project) -> IntegrationSettings:
    """讀取 E 區設定；還沒存過回傳預設值。"""
    path = _settings_path(project)
    if not path.is_file():
        return IntegrationSettings()
    return IntegrationSettings.model_validate_json(path.read_text(encoding="utf-8"))


def load_settings(project: Project) -> IntegrationSettings:
    """E 區設定（給報告輸出使用）。"""
    return _load(project)


def _save(project: Project, settings: IntegrationSettings) -> None:
    """寫入 E 區設定（先寫暫存檔再取代）。"""
    path = _settings_path(project)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


# ---------- 計算 ----------
def _compute(store: JobStore, project: Project) -> tuple[IntegrationSettings, list[PixelPairing], list[PixelResult]]:
    """配對三區並計算每個 pixel 的 D*。"""
    settings = _load(project)
    bias = settings.bias.value
    pairings = pair_pixels(
        bias, project_extracts(store, project), project_curves(store, project), project_groups(store, project),
        settings.overrides,
    )
    return settings, pairings, [compute_pixel(to_input(p, bias)) for p in pairings]


def _source_out(pairing: PixelPairing, kind: SourceKind) -> SourceOut:
    """某一區的選擇與候選。"""
    return SourceOut(
        name=pairing.chosen(kind), instrument=pairing.instrument(kind), manual=kind in pairing.manual,
        candidates=[CandidateOut(name=c.name, instrument=c.instrument) for c in pairing.candidates[kind]],
    )


def _pixel_out(pairing: PixelPairing, result: PixelResult, wavelengths: list[float]) -> PixelOut:
    """一個 pixel 的回應。"""
    inp = result.input
    device = device_of(pairing.pixel)
    peaks = {}
    for kind in DStarKind:
        peak = result.peak(kind)
        peaks[kind.value] = PeakOut(value=peak[0], wavelength=peak[1]) if peak else None
    return PixelOut(
        pixel=pairing.pixel, device=str(device) if device else None,
        sources={k.value: _source_out(pairing, k) for k in SourceKind},
        area=inp.area, rsh=inp.rsh, dark_current=inp.dark_current,
        noises={k.value: v for k, v in result.noises.items()}, peaks=peaks,
        at={k.value: [result.at(k, wl) for wl in wavelengths] for k in DStarKind},
        responsivity_at=[result.r_at(wl) for wl in wavelengths], warnings=result.warnings,
    )


def _out(store: JobStore, project: Project) -> IntegrationOut:
    """組出 E 區內容。"""
    settings, pairings, results = _compute(store, project)
    jobs = project.info.jobs
    return IntegrationOut(
        settings=settings,
        available={s.value: s.value in jobs for s in (Section.DARK, Section.EQE, Section.NOISE)},
        project_grouping=[g.model_dump() for g in project.info.grouping],
        pixels=[_pixel_out(p, r, settings.wavelengths) for p, r in zip(pairings, results)],
    )


def _get(store: JobStore, user: str, name: str) -> IntegrationOut:
    """GET：目前的配對與 D*。"""
    return _out(store, store.workspace.get_project(user, name))


def _update(store: JobStore, user: str, name: str, body: IntegrationSettingsIn) -> IntegrationOut:
    """儲存偏壓與波長（波長不合理拋出 ValueError → 400）；手動配對保留。"""
    project = store.workspace.get_project(user, name)
    wavelengths = check_wavelengths(body.wavelengths)
    settings = _load(project).model_copy(update={"bias": body.bias, "wavelengths": wavelengths})
    _save(project, settings)
    return _out(store, project)


def _choose(store: JobStore, user: str, name: str, body: ChoiceIn) -> IntegrationOut:
    """儲存一格手動配對；pixel 或名稱不存在拋出 KeyError → 400。"""
    project = store.workspace.get_project(user, name)
    _, pairings, _ = _compute(store, project)
    pairing = next((p for p in pairings if p.pixel == body.pixel), None)
    if pairing is None:
        raise KeyError(f"沒有這個 pixel：{body.pixel}")
    if body.name and body.name not in {c.name for c in pairing.candidates[body.source]}:
        raise KeyError(f"{body.pixel} 在 {body.source.value} 沒有「{body.name}」")
    settings = _load(project)
    overrides = {p: dict(v) for p, v in settings.overrides.items()}
    chosen = overrides.setdefault(body.pixel, {})
    if body.name is None:
        chosen.pop(body.source.value, None)
    else:
        chosen[body.source.value] = body.name
    overrides = {p: v for p, v in overrides.items() if v}
    _save(project, settings.model_copy(update={"overrides": overrides}))
    return _out(store, project)


def _plot(store: JobStore, user: str, name: str, body: DetectivityPlotIn):
    """D*(λ) 圖（勾選的 pixel；指定波長畫虛線）。"""
    project = store.workspace.get_project(user, name)
    settings, pairings, results = _compute(store, project)
    by_pixel = {p.pixel: r for p, r in zip(pairings, results)}
    unknown = [p for p in body.pixels if p not in by_pixel]
    if unknown:
        raise KeyError(f"沒有這些 pixel：{'、'.join(unknown)}")
    fig = plot_detectivity([by_pixel[p] for p in body.pixels], body.kind, settings.wavelengths,
                           body.x_range, body.y_range, body.log_y)
    return png_response(fig)


def _excel(store: JobStore, user: str, name: str) -> FileResponse:
    """寫出 D* Excel 並下載。"""
    project = store.workspace.get_project(user, name)
    settings, pairings, results = _compute(store, project)
    folder = project.folder / OUTPUT_DIR
    folder.mkdir(exist_ok=True)
    path = folder / EXCEL_NAME
    write_detectivity_excel(path, results, pairings, settings.wavelengths)
    return FileResponse(path, media_type=MediaType.XLSX, filename=EXCEL_NAME)


# ---------- 路由 ----------
@router.get("", response_model=IntegrationOut)
async def get_integration(user: str, project: str, store: JobStore = Depends(get_store)) -> IntegrationOut:
    """E 區內容：設定、三區是否有資料、每個 pixel 的配對與 D*（最大值與指定波長）。"""
    return await asyncio.to_thread(_get, store, user, project)


@router.put("/settings", response_model=IntegrationOut)
async def update_settings(
    user: str, project: str, body: IntegrationSettingsIn, store: JobStore = Depends(get_store),
) -> IntegrationOut:
    """設定 D* 偏壓（0、-0.1、-0.5 V）與指定波長（最多 3 個）；不合理回 400／422。"""
    return await asyncio.to_thread(_update, store, user, project, body)


@router.put("/choices", response_model=IntegrationOut)
async def set_choice(user: str, project: str, body: ChoiceIn, store: JobStore = Depends(get_store)) -> IntegrationOut:
    """手動配對：某個 pixel 在某一區用哪一筆（"" 不使用、null 回到自動）。"""
    return await asyncio.to_thread(_choose, store, user, project, body)


@router.post("/plot")
async def detectivity_plot(user: str, project: str, body: DetectivityPlotIn, store: JobStore = Depends(get_store)):
    """D*(λ) 圖 PNG。"""
    return await asyncio.to_thread(_plot, store, user, project, body)


@router.get("/excel")
async def download_excel(user: str, project: str, store: JobStore = Depends(get_store)):
    """下載 D* Excel（Summary＋四種 D*(λ)）。"""
    return await asyncio.to_thread(_excel, store, user, project)

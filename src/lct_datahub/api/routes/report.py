"""G-5 報告輸出（PD 報告，2026-11-19）：從同專案 b.、c.、d.、e. 的結果產生 PowerPoint。

- 條件：專案總覽的分組（條件 → 樣品代號）；每個條件由使用者選一顆代表 pixel（預設 D* 最高）
- 表格：每個條件一欄；暗電流與 D*、Noise 同時放 0 V 與 −0.1 V，算不出來的留空
- 封面：配方、前驅液濃度、元件結構圖（選用），存在專案資料夾（report.json、report/ 底下的圖）
路由為 async def，計算、畫圖、產生 PPT 以 asyncio.to_thread() 交給執行緒。
"""
import asyncio
import dataclasses
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from lct_datahub.api.common import get_store
from lct_datahub.api.jobs import JobStore
from lct_datahub.api.projects import Project
from lct_datahub.api.routes.dark import project_dark_curves, project_extracts
from lct_datahub.api.routes.eqe import project_curves
from lct_datahub.api.routes.integration import load_settings as load_integration
from lct_datahub.api.routes.noise import project_groups
from lct_datahub.core.dark_current.shift import shift_curves
from lct_datahub.core.dark_current.types import ExtractBias, ShiftMode
from lct_datahub.core.detectivity.compute import DStarKind, PixelResult, compute_pixel
from lct_datahub.core.detectivity.pairing import PixelPairing, pair_pixels, shot_current, to_input
from lct_datahub.core.noise.reference import shot_noise, thermal_noise
from lct_datahub.core.noise.spectrum import value_at
from lct_datahub.core.plotting import (
    figure_to_report_png, plot_dark_current, plot_detectivity, plot_eqe, plot_noise, plot_rplot,
)
from lct_datahub.core.report.pd_report import PdReport, TableRow, build_pd_report
from lct_datahub.core.sample_id import device_of

router = APIRouter(prefix="/api/users/{user}/projects/{project}/report", tags=["G 報告輸出"])
SETTINGS_FILE = "report.json"
IMAGE_DIR = "report"
IMAGE_STEM = "structure"
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg"}
PPTX_TYPE = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
REPORT_BIASES = (ExtractBias.ZERO, ExtractBias.NEG_0_1)  # 表格同時放的兩個偏壓
PLOT_DPI = 300


# ---------- 資料模型 ----------
class ReportSettings(BaseModel):
    """報告設定（存在 report.json）：標題、配方、濃度、每個條件的代表 pixel（空白為不列入）。"""

    title: str = ""
    recipe: str = ""
    concentration: str = ""
    selections: dict[str, str] = {}


class PixelChoiceOut(BaseModel):
    """條件底下的一顆 pixel。"""

    pixel: str
    dstar: float | None  # e. 目前偏壓的最大 D*（實測優先，沒有則理論極限）
    measured: bool  # dstar 為實測值


class ConditionOut(BaseModel):
    """一個條件：底下的 pixel 與目前選的代表。"""

    name: str
    pixels: list[PixelChoiceOut]
    selected: str  # 空白為不列入


class ReportOut(BaseModel):
    """報告頁內容。"""

    settings: ReportSettings
    project_name: str
    has_grouping: bool  # 專案總覽是否已分組（沒有就無法依條件選 pixel）
    has_image: bool
    conditions: list[ConditionOut]


# ---------- 設定與圖檔 ----------
def _load(project: Project) -> ReportSettings:
    """讀取報告設定；還沒存過回傳預設值。"""
    path = project.folder / SETTINGS_FILE
    if not path.is_file():
        return ReportSettings()
    return ReportSettings.model_validate_json(path.read_text(encoding="utf-8"))


def _save(project: Project, settings: ReportSettings) -> None:
    """寫入報告設定（先寫暫存檔再取代）。"""
    path = project.folder / SETTINGS_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
    tmp.replace(path)


def _image_path(project: Project) -> Path | None:
    """元件結構圖的路徑（沒有為 None）。"""
    folder = project.folder / IMAGE_DIR
    return next((p for p in sorted(folder.glob(f"{IMAGE_STEM}.*")) if p.suffix.lower() in IMAGE_SUFFIXES), None) \
        if folder.is_dir() else None


# ---------- 計算 ----------
def _pairings(store: JobStore, project: Project, bias: float) -> tuple[list[PixelPairing], list[PixelResult]]:
    """某個偏壓的配對與 D*（沿用 e. 的手動配對）。"""
    overrides = load_integration(project).overrides
    pairings = pair_pixels(bias, project_extracts(store, project), project_curves(store, project),
                           project_groups(store, project), overrides)
    return pairings, [compute_pixel(to_input(p, bias)) for p in pairings]


def _best(result: PixelResult) -> tuple[float | None, bool]:
    """最大 D*：有實測用實測，沒有用理論極限；回傳 (值, 是否實測)。"""
    measured = result.peak(DStarKind.MEASURED)
    if measured:
        return measured[0], True
    theory = result.peak(DStarKind.COMBINE)
    return (theory[0] if theory else None), False


def _conditions(store: JobStore, project: Project, settings: ReportSettings) -> list[ConditionOut]:
    """依總覽分組列出每個條件的 pixel 與代表（沒選過的預設 D* 最高）。"""
    bias = load_integration(project).bias.value
    pairings, results = _pairings(store, project, bias)
    by_device: dict[str, list[tuple[str, float | None, bool]]] = {}
    completeness: dict[str, int] = {}  # 有幾區的資料
    for pairing, result in zip(pairings, results):
        device = device_of(pairing.pixel)
        if device is not None:
            by_device.setdefault(str(device), []).append((pairing.pixel, *_best(result)))
            completeness[pairing.pixel] = sum(x is not None for x in (pairing.eqe, pairing.dark, pairing.noise))
    out = []
    for group in project.info.grouping:
        pixels = [PixelChoiceOut(pixel=p, dstar=d, measured=m) for s in group.samples for p, d, m in by_device.get(s, [])]
        if group.name in settings.selections:
            selected = settings.selections[group.name]
        else:
            # D* 最高者優先；都沒有 D* 時取資料最齊全（EQE、暗電流、noise）的
            ranked = sorted(pixels, key=lambda c: (c.dstar is not None, c.dstar or 0.0, completeness.get(c.pixel, 0)),
                            reverse=True)
            selected = ranked[0].pixel if ranked else ""
        out.append(ConditionOut(name=group.name, pixels=pixels, selected=selected))
    return out


def _out(store: JobStore, project: Project) -> ReportOut:
    """組出報告頁內容。"""
    settings = _load(project)
    return ReportOut(
        settings=settings, project_name=project.name, has_grouping=bool(project.info.grouping),
        has_image=_image_path(project) is not None, conditions=_conditions(store, project, settings),
    )


def _rename_result(result: PixelResult, name: str) -> PixelResult:
    """D* 結果改用條件名稱（圖例）。"""
    return dataclasses.replace(result, input=dataclasses.replace(result.input, pixel=name))


def _png(fig) -> bytes:
    """圖轉報告用 300 dpi PNG（固定尺寸、圖例在圖內，所有圖大小相同）。"""
    return figure_to_report_png(fig, dpi=PLOT_DPI)


def build_report(store: JobStore, project: Project) -> PdReport:
    """整理成 PdReport：每個條件一欄（代表 pixel），各區的圖與表。"""
    settings = _load(project)
    chosen = [(c.name, c.selected) for c in _conditions(store, project, settings) if c.selected]
    names = [n for n, _ in chosen]
    integration = load_integration(project)
    wavelengths = integration.wavelengths
    plot_bias = integration.bias.value
    per_bias = {b: dict(zip((p.pixel for p in pairs), zip(pairs, results)))
                for b in REPORT_BIASES for pairs, results in [_pairings(store, project, b.value)]}

    def item(bias: ExtractBias, pixel: str) -> tuple[PixelPairing | None, PixelResult | None]:
        """某偏壓、某 pixel 的配對與 D*。"""
        return per_bias[bias].get(pixel, (None, None))

    # 暗電流
    dark_curves = {c.name: c for c in project_dark_curves(store, project)}
    darks = [item(ExtractBias.ZERO, p)[0] for _, p in chosen]
    curves = [dataclasses.replace(dark_curves[d.dark.name], name=n)
              for (n, _), d in zip(chosen, darks) if d and d.dark and d.dark.name in dark_curves]
    dark_rows = []
    if any(d and d.dark for d in darks):
        extract = [d.dark if d else None for d in darks]
        dark_rows = [
            TableRow("J", [e.jd.get(ExtractBias.ZERO) if e else None for e in extract], "d", "(0 V) A/cm²"),
            TableRow("J", [e.jd.get(ExtractBias.NEG_0_1) if e else None for e in extract], "d", "(−0.1 V) A/cm²"),
            TableRow("R", [e.rsh if e else None for e in extract], "sh", "(Ω)"),
            TableRow("i", [thermal_noise(e.rsh) if e and e.rsh and e.rsh > 0 else None for e in extract], "thermal",
                     "(A/Hz^0.5)"),
        ]
        for bias in REPORT_BIASES:
            values = []
            for e in extract:
                current = shot_current(e, bias.value) if e else None
                values.append(shot_noise(current) if current is not None else None)
            dark_rows.append(TableRow("i", values, "shot", f"({bias.value:g} V) (A/Hz^0.5)"))

    # EQE、R、D*(λ)（圖用 e. 目前的偏壓）
    def bias_has_dstar(bias: ExtractBias) -> bool:
        """這個偏壓是否有任一條件算得出 D*。"""
        return any((r := item(bias, p)[1]) is not None and (r.spectra[DStarKind.MEASURED] is not None or
                   r.spectra[DStarKind.COMBINE] is not None) for _, p in chosen)

    if not bias_has_dstar(_bias_of(plot_bias)):  # e. 的偏壓沒有 D*（例如 EQE 只量 0 V）就改用有 D* 的偏壓
        plot_bias = next((b.value for b in REPORT_BIASES if bias_has_dstar(b)), plot_bias)
    eqes = [dataclasses.replace(r.input.eqe, name=n) for (n, p) in chosen
            if (r := item(_bias_of(plot_bias), p)[1]) is not None and r.input.eqe is not None]
    plot_results = [_rename_result(r, n) for (n, p) in chosen if (r := item(_bias_of(plot_bias), p)[1]) is not None]
    kind = DStarKind.MEASURED if any(r.spectra[DStarKind.MEASURED] is not None for r in plot_results) \
        else DStarKind.COMBINE
    has_dstar = any(r.spectra[kind] is not None for r in plot_results)
    r_rows = [TableRow(f"R @ {wl:g} nm", [r.r_at(wl) if r else None for r in
                                          (item(_bias_of(plot_bias), p)[1] for _, p in chosen)], unit="(A/W)")
              for wl in wavelengths] if eqes else []

    def dstar_rows(kind: DStarKind) -> list[TableRow]:
        """某一種 D* 的表：每個偏壓一段（最大值＋指定波長），算不出來留空。"""
        rows = []
        for bias in REPORT_BIASES:
            results = [item(bias, p)[1] for _, p in chosen]
            rows.append(TableRow(f"{bias.value:g} V", [], section=True))
            rows.append(TableRow("最大值", [(r.peak(kind) or (None,))[0] if r else None for r in results],
                                 unit="(Jones)"))
            for wl in wavelengths:
                rows.append(TableRow(f"@ {wl:g} nm", [r.at(kind, wl) if r else None for r in results], unit="(Jones)"))
        return rows

    theory_rows = dstar_rows(DStarKind.COMBINE) if eqes else []
    measured_rows = dstar_rows(DStarKind.MEASURED) if eqes else []

    # Noise
    noise_plots, noise_rows = [], []
    for bias in REPORT_BIASES:
        groups = [dataclasses.replace(pr.noise, sample=n) for (n, p) in chosen
                  if (pr := item(bias, p)[0]) is not None and pr.noise is not None]
        if groups:
            noise_plots.append((f"Noise spectrum, {bias.value:g} V", _png(plot_noise(groups))))
    if noise_plots:
        for bias in REPORT_BIASES:
            measured, theory = [], []
            for _, p in chosen:
                pairing, result = item(bias, p)
                group = pairing.noise if pairing else None
                measured.append(value_at(group.freq, group.mean) if group is not None and group.mean is not None
                                else None)
                theory.append(result.noises[DStarKind.COMBINE] if result else None)
            noise_rows.append(TableRow(f"1 Hz 實測 ({bias.value:g} V)", measured, unit="(A/Hz^0.5)"))
            noise_rows.append(TableRow(f"理論 Shot+Thermal ({bias.value:g} V)", theory, unit="(A/Hz^0.5)"))

    image = _image_path(project)
    dark_plots = []
    if curves:  # 偏移到 0 V 與未偏移各一張
        dark_plots = [("Dark J–V (shifted to 0 V)", _png(plot_dark_current(shift_curves(curves, ShiftMode.SHIFT)))),
                      ("Dark J–V (as measured)", _png(plot_dark_current(shift_curves(curves, ShiftMode.KEEP))))]
    spectral_plots = []
    if eqes:
        spectral_plots += [("EQE & integrated Jsc", _png(plot_eqe(eqes))), ("Responsivity", _png(plot_rplot(eqes)))]
    if has_dstar:
        spectral_plots.append((f"D* ({'measured' if kind is DStarKind.MEASURED else 'Shot+Thermal'}, {plot_bias:g} V)",
                               _png(plot_detectivity(plot_results, kind, wavelengths))))
    return PdReport(
        title=settings.title or project.name, conditions=names, pixels=[p for _, p in chosen],
        recipe=settings.recipe, concentration=settings.concentration,
        structure_image=image.read_bytes() if image else None,
        dark_plots=dark_plots, dark_rows=dark_rows, spectral_plots=spectral_plots, r_rows=r_rows,
        theory_rows=theory_rows, measured_rows=measured_rows, noise_plots=noise_plots, noise_rows=noise_rows,
        footnote=(f"D*(λ) 圖：{plot_bias:g} V、{kind.value}；表格分列 0 V 與 −0.1 V，算不出來的留空。"
                  "Noise：標準定義、1 Hz；溫度 300 K。"),
    )


def _bias_of(value: float) -> ExtractBias:
    """偏壓值對應的 ExtractBias。"""
    return next(b for b in ExtractBias if abs(b.value - value) < 1e-9)


# ---------- 同步工作 ----------
def _get(store: JobStore, user: str, name: str) -> ReportOut:
    """GET：報告頁內容。"""
    return _out(store, store.workspace.get_project(user, name))


def _update(store: JobStore, user: str, name: str, body: ReportSettings) -> ReportOut:
    """儲存標題、配方、濃度、代表 pixel；條件或 pixel 不存在拋出 KeyError → 400。"""
    project = store.workspace.get_project(user, name)
    conditions = {c.name: {p.pixel for p in c.pixels} for c in _conditions(store, project, _load(project))}
    for cond, pixel in body.selections.items():
        if cond not in conditions:
            raise KeyError(f"總覽分組沒有這個條件：{cond}")
        if pixel and pixel not in conditions[cond]:
            raise KeyError(f"條件「{cond}」沒有 pixel：{pixel}")
    _save(project, body)
    return _out(store, project)


def _set_image(store: JobStore, user: str, name: str, filename: str, content: bytes) -> ReportOut:
    """儲存元件結構圖（png、jpg）；取代舊的。"""
    project = store.workspace.get_project(user, name)
    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_SUFFIXES:
        raise ValueError("元件結構圖只接受 .png、.jpg、.jpeg")
    folder = project.folder / IMAGE_DIR
    folder.mkdir(exist_ok=True)
    for old in folder.glob(f"{IMAGE_STEM}.*"):
        old.unlink()
    (folder / f"{IMAGE_STEM}{suffix}").write_bytes(content)
    return _out(store, project)


def _clear_image(store: JobStore, user: str, name: str) -> ReportOut:
    """移除元件結構圖。"""
    project = store.workspace.get_project(user, name)
    path = _image_path(project)
    if path:
        path.unlink()
    return _out(store, project)


def _pptx(store: JobStore, user: str, name: str) -> Response:
    """產生 PPT 並下載（檔名：專案名稱_PD報告.pptx）。"""
    project = store.workspace.get_project(user, name)
    content = build_pd_report(build_report(store, project))
    filename = f"{project.name}_PD報告.pptx"
    return Response(content, media_type=PPTX_TYPE,
                    headers={"Content-Disposition": f"attachment; filename*=utf-8''{quote(filename)}"})


# ---------- 路由 ----------
@router.get("", response_model=ReportOut)
async def get_report(user: str, project: str, store: JobStore = Depends(get_store)) -> ReportOut:
    """報告頁：封面設定、每個條件的 pixel 與代表、是否有元件結構圖。"""
    return await asyncio.to_thread(_get, store, user, project)


@router.put("/settings", response_model=ReportOut)
async def update_settings(user: str, project: str, body: ReportSettings,
                          store: JobStore = Depends(get_store)) -> ReportOut:
    """儲存標題、配方、濃度與每個條件的代表 pixel（"" 為不列入）。"""
    return await asyncio.to_thread(_update, store, user, project, body)


@router.post("/image", response_model=ReportOut)
async def upload_image(user: str, project: str, file: UploadFile = File(...),
                       store: JobStore = Depends(get_store)) -> ReportOut:
    """上傳元件結構圖（png、jpg）。"""
    content = await file.read()
    return await asyncio.to_thread(_set_image, store, user, project, file.filename or "", content)


@router.post("/image/clear", response_model=ReportOut)
async def clear_image(user: str, project: str, store: JobStore = Depends(get_store)) -> ReportOut:
    """移除元件結構圖。"""
    return await asyncio.to_thread(_clear_image, store, user, project)


@router.get("/pptx")
async def download_pptx(user: str, project: str, store: JobStore = Depends(get_store)) -> Response:
    """下載 PD 報告（PowerPoint）。"""
    return await asyncio.to_thread(_pptx, store, user, project)

"""E 區 PD 數據整合的狀態：e-1 設定 → e-2 配對 → e-3 D* 表 → e-4 D*(λ) 圖。

- 不需要上傳：讀同專案 B（B-4）、C（EQE）、D（noise）的結果；設定存在專案（偏壓、最多 3 個波長、手動配對）
- 以 pixel 計算；同一 pixel 有兩台儀器的數據時自動判斷，可在 e-2 手動選擇或不使用
- D* 四種：實測、Shot＋Thermal（理論極限）、Thermal、Shot；e-3 可切換顯示哪一種
- 勾選清單依專案總覽的分組排列（沒有總覽分組時為全部樣品）
所有 API 呼叫都是 async，失敗時開啟 ErrorState 的警告視窗。
"""
from dataclasses import dataclass, field

import reflex as rx

from front import api_client as api
from front.api_client import ApiError
from front.enums import DStarKind, IntegrationTab, SourceKind
from front.states.common import parse_float, parse_range, png_data_url
from front.states.grouping import GroupingMixin
from front.states.picker import CurvePickerMixin, PickCurve, natural_key
from front.states.session import SessionState

EXCEL_FALLBACK_NAME = "Detectivity.xlsx"
PLOT_NAME = "Detectivity.png"
AUTO_PAIR = "__auto__"  # 配對選單：回到自動
NOT_USED = ""  # 配對選單：不使用（與 core.detectivity.pairing.NOT_USED 相同）
MAX_WAVELENGTHS = 3


def _sci(value) -> str:
    """科學記號 3 位有效數字；None 顯示 —。"""
    return "—" if value is None else f"{value:.3g}"


@dataclass
class SourceCell:
    """配對表的一格：選到的資料、儀器、選單目前的值、候選名稱。"""

    name: str = ""
    instrument: str = ""
    choice: str = AUTO_PAIR
    manual: bool = False
    options: list[str] = field(default_factory=list)  # 候選名稱
    labels: list[str] = field(default_factory=list)  # 候選的「名稱 (儀器)」，與 options 同順序


@dataclass
class PairRow:
    """e-2 的一列。"""

    pixel: str = ""
    dark: SourceCell = field(default_factory=SourceCell)
    eqe: SourceCell = field(default_factory=SourceCell)
    noise: SourceCell = field(default_factory=SourceCell)
    multi: bool = False  # 某一區有多筆候選（需要確認儀器）


@dataclass
class ResultRow:
    """e-3 的一列（依目前選的 D* 種類，數值已轉成顯示用文字）。"""

    pixel: str = ""
    area: str = ""
    rsh: str = ""
    dark_current: str = ""
    noise: str = ""  # 目前種類的 i_n
    peak: str = ""
    peak_at: str = ""
    at: list[str] = field(default_factory=list)  # 每個指定波長的 D*
    r_at: list[str] = field(default_factory=list)  # 每個指定波長的 R
    warnings: str = ""
    ok: bool = False  # 這一種 D* 算得出來


class IntegrationState(CurvePickerMixin, GroupingMixin, SessionState):
    """PD 數據整合頁面的狀態（SessionState 的子狀態）。"""

    tab: str = IntegrationTab.SETTINGS.value
    loading: bool = False
    loaded: bool = False

    # 設定
    has_dark: bool = False
    has_eqe: bool = False
    has_noise: bool = False
    bias: str = "0"
    wl_inputs: list[str] = ["", "", ""]
    wavelengths: list[float] = []
    wl_key: int = 0

    # 結果（API 原始內容；表格由計算屬性轉成文字）
    raw_pixels: list[dict] = []
    table_kind: str = DStarKind.COMBINE.value

    # e-4 D*(λ) 圖
    plot_kind: str = DStarKind.COMBINE.value
    x_min: str = ""
    x_max: str = ""
    y_min: str = ""
    y_max: str = ""
    log_y: bool = True
    plot_png: str = ""
    range_key: int = 0

    # ---------- 計算屬性 ----------
    @rx.var
    def bias_options(self) -> list[str]:
        """偏壓選項（與 B-4 相同）。"""
        return ["0", "-0.1", "-0.5"]

    @rx.var
    def kind_options(self) -> list[str]:
        """D* 種類。"""
        return [k.value for k in DStarKind]

    @rx.var
    def wavelength_labels(self) -> list[str]:
        """已儲存的指定波長（表頭用）。"""
        return [f"{w:g} nm" for w in self.wavelengths]

    @rx.var
    def pixel_count(self) -> int:
        """pixel 數。"""
        return len(self.raw_pixels)

    @rx.var
    def computable_count(self) -> int:
        """有 EQE 與面積、算得出理論 D* 的 pixel 數。"""
        return sum(1 for p in self.raw_pixels if p["peaks"].get(DStarKind.COMBINE.value) is not None)

    @rx.var
    def plot_locked(self) -> bool:
        """在 e-4：整頁不捲動。"""
        return self.tab == IntegrationTab.PLOT.value

    @rx.var
    def pair_rows(self) -> list[PairRow]:
        """e-2 配對表。"""
        rows = []
        for p in self.raw_pixels:
            cells = {}
            for kind in SourceKind:
                s = p["sources"][kind.value]
                choice = (s["name"] or NOT_USED) if s["manual"] else AUTO_PAIR
                cells[kind.value] = SourceCell(
                    name=s["name"] or "", instrument=s["instrument"] or "", choice=choice, manual=s["manual"],
                    options=[c["name"] for c in s["candidates"]],
                    labels=[f"{c['name']} ({c['instrument']})" for c in s["candidates"]],
                )
            multi = any(len(p["sources"][k.value]["candidates"]) > 1 for k in SourceKind)
            rows.append(PairRow(p["pixel"], cells["dark"], cells["eqe"], cells["noise"], multi))
        return rows

    @rx.var
    def result_rows(self) -> list[ResultRow]:
        """e-3 D* 表（目前選的種類）。"""
        kind = self.table_kind
        rows = []
        for p in self.raw_pixels:
            peak = p["peaks"].get(kind)
            rows.append(ResultRow(
                pixel=p["pixel"], area=_sci(p["area"]), rsh=_sci(p["rsh"]), dark_current=_sci(p["dark_current"]),
                noise=_sci(p["noises"].get(kind)), peak=_sci(peak["value"]) if peak else "—",
                peak_at=f"{peak['wavelength']:g}" if peak else "—",
                at=[_sci(v) for v in p["at"].get(kind, [])], r_at=[_sci(v) for v in p["responsivity_at"]],
                warnings="\n".join(p["warnings"]), ok=peak is not None,
            ))
        return rows

    # ---------- 事件：分頁與輸入 ----------
    @rx.event
    def set_tab(self, value: str) -> None:
        """切換分頁。"""
        self.tab = value

    @rx.event
    def go_to(self, tab: str) -> None:
        """「下一步」按鈕。"""
        self.tab = tab

    @rx.event
    def set_wl(self, index: int, value: str) -> None:
        """指定波長輸入框。"""
        items = list(self.wl_inputs)
        items[index] = value
        self.wl_inputs = items

    @rx.event
    def set_table_kind(self, value: str) -> None:
        """e-3 顯示的 D* 種類。"""
        self.table_kind = value

    @rx.event
    def set_plot_kind(self, value: str):
        """e-4 的 D* 種類；已有預覽圖時重畫。"""
        self.plot_kind = value
        return IntegrationState.plot if self.plot_png else None

    @rx.event
    def set_x_min(self, value: str) -> None:
        """X 軸下限。"""
        self.x_min = value

    @rx.event
    def set_x_max(self, value: str) -> None:
        """X 軸上限。"""
        self.x_max = value

    @rx.event
    def set_y_min(self, value: str) -> None:
        """Y 軸下限。"""
        self.y_min = value

    @rx.event
    def set_y_max(self, value: str) -> None:
        """Y 軸上限。"""
        self.y_max = value

    @rx.event
    def set_log_y(self, value: bool) -> None:
        """Y 軸是否為對數。"""
        self.log_y = value

    @rx.event
    def reset_range(self) -> None:
        """範圍回到自動。"""
        self.x_min = self.x_max = self.y_min = self.y_max = ""
        self.range_key += 1

    # ---------- API ----------
    def _base(self) -> str:
        """E 區的 API 路徑（不含 /api）。"""
        return f"{api.project_path(self.user, self.project)}/integration"

    def _apply(self, data: dict) -> None:
        """把 API 回傳的 IntegrationOut 填入狀態。"""
        settings = data["settings"]
        self.bias = f"{settings['bias']:g}"
        self.wavelengths = list(settings["wavelengths"])
        self.wl_inputs = [f"{w:g}" for w in self.wavelengths] + [""] * (MAX_WAVELENGTHS - len(self.wavelengths))
        self.wl_key += 1
        available = data["available"]
        self.has_dark, self.has_eqe, self.has_noise = available["dark"], available["eqe"], available["noise"]
        self.raw_pixels = data["pixels"]
        # 勾選清單：只列算得出 D* 曲線的 pixel；依專案總覽分組排列
        self.samples = sorted({p["device"] for p in self.raw_pixels if p["device"]}, key=natural_key)  # G6 在 G10 前
        self._load_conditions(data["project_grouping"] or None)
        self.pick_curves = [PickCurve(p["pixel"], p["device"] or "") for p in self.raw_pixels
                            if p["peaks"].get(DStarKind.COMBINE.value) or p["peaks"].get(DStarKind.MEASURED.value)]
        self._init_selection()
        self.loaded = True

    def _job_path(self) -> str:
        """GroupingMixin 需要的路徑（E 區不在這裡分組，沿用專案總覽分組）。"""
        return self._base()

    @rx.event
    async def load(self):
        """頁面載入：讀取同專案 B、C、D 的配對與 D*。"""
        if not self.user or not self.project:
            return
        self.loading = True
        yield
        try:
            data = await api.get_json(self._base())
        except ApiError as err:
            self._show_error(err)
            return
        finally:
            self.loading = False
        self._apply(data)

    async def _save(self, bias: str):
        """儲存偏壓與指定波長（空白的輸入框略過）；save_settings、set_bias 共用。"""
        try:
            wavelengths = [w for i, text in enumerate(self.wl_inputs)
                           if (w := parse_float(text, f"波長 {i + 1}")) is not None]
        except ValueError as exc:
            self._show_message(str(exc))
            return
        body = {"bias": float(bias), "wavelengths": wavelengths}
        self.loading = True
        yield
        try:
            data = await api.put_json(f"{self._base()}/settings", body)
        except ApiError as err:
            self._show_error(err)
            return
        finally:
            self.loading = False
        self._apply(data)
        self.plot_png = ""
        yield rx.toast.success("設定已儲存")

    @rx.event
    async def save_settings(self):
        """「儲存設定」按鈕：儲存目前偏壓與輸入的波長。"""
        async for event in self._save(self.bias):
            yield event

    @rx.event
    async def set_bias(self, value: str):
        """切換偏壓（立即儲存並重算）。"""
        async for event in self._save(value):
            yield event

    @rx.event
    async def set_choice(self, pixel: str, source: str, choice: str):
        """手動配對：選某一筆、不使用、或回到自動。"""
        body = {"pixel": pixel, "source": source, "name": None if choice == AUTO_PAIR else choice}
        try:
            data = await api.put_json(f"{self._base()}/choices", body)
        except ApiError as err:
            self._show_error(err)
            return
        self._apply(data)
        self.plot_png = ""

    @rx.event
    async def download_excel(self):
        """下載 D* Excel（Summary＋四種 D*(λ)）。"""
        self.loading = True
        yield
        try:
            name, content = await api.get_file(f"{self._base()}/excel", EXCEL_FALLBACK_NAME)
        except ApiError as err:
            self._show_error(err)
            return
        finally:
            self.loading = False
        yield rx.download(data=content, filename=name)

    def _on_hidden_changed(self):
        """暫時隱藏改變：已有預覽圖時自動重畫。"""
        return IntegrationState.plot if self.plot_png else None

    @rx.event
    async def plot(self):
        """e-4：勾選的 pixel 的 D*(λ)。"""
        names = self._visible_selected()
        if not names:
            self._show_message("請至少勾選一個 pixel（且不在暫時隱藏的區塊內）")
            return
        try:
            body = {
                "pixels": names, "kind": self.plot_kind, "log_y": self.log_y,
                "x_range": parse_range(self.x_min, self.x_max, "X 軸"),
                "y_range": parse_range(self.y_min, self.y_max, "Y 軸", positive=self.log_y),
            }
        except ValueError as exc:
            self._show_message(str(exc))
            return
        self.loading = True
        yield
        try:
            self.plot_png = png_data_url(await api.post_bytes(f"{self._base()}/plot", body))
        except ApiError as err:
            self._show_error(err)
        finally:
            self.loading = False

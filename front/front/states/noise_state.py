"""D 區 Noise 的狀態：d-1 上傳 → d-2 分組 → d-3 雜訊圖 → d-4 數值與參考線。

- 同一樣品＋偏壓的檔由 API 自動分組平均（n 次）；溢位、削平的檔排除，未穩定、底線不一致只警告
- 勾選清單的單位是「組」（例如 G1-2 -0.1V (n=3)），依樣品代號（G1）排成直行，與 B、C 區共用元件
- 預設標準定義，可切換儀器定義（存在工作設定）；參考線取自同專案 B 區的 B-4（自動配對、可手動指定）
所有 API 呼叫都是 async，失敗時開啟 ErrorState 的警告視窗。
"""
from dataclasses import dataclass

import reflex as rx

from front import api_client as api
from front.api_client import ApiError
from front.enums import ErrorKind, NoiseDefinition, NoiseTab, Section
from front.states.common import parse_range, png_data_url
from front.states.grouping import GroupingMixin
from front.states.picker import CurvePickerMixin, PickCurve
from front.states.session import SessionState

SECTION = Section.NOISE
UPLOAD_ID = "noise_upload"
UPLOAD_TYPE = "text/csv"
ACCEPT = {"text/csv": [".csv"]}  # 與 api/jobs.py 的 Section.NOISE 相同
EXCEL_FALLBACK_NAME = "Noise.xlsx"
PLOT_NAME = "Noise.png"
ALL_BIAS = "全部"  # 偏壓篩選：全部
AUTO_PAIR = "__auto__"  # 手動配對選單：回到自動
NO_PAIR = ""  # 手動配對選單：不配對（與 core.noise.pairing.NO_PAIR 相同）


def _sci(value) -> str:
    """科學記號 3 位有效數字；None 顯示 —。"""
    return "—" if value is None else f"{value:.3g}"


def _bias_text(bias: float) -> str:
    """偏壓顯示文字（0 V、-0.1 V）。"""
    return f"{bias:g} V"


@dataclass
class NoiseGroupRow:
    """一組的摘要（數值已轉成顯示用文字）。"""

    name: str = ""
    sample: str = ""
    device: str = ""
    bias: str = ""
    bias_default: bool = False
    instrument: str = ""
    n: int = 0
    files: str = ""
    excluded: str = ""  # 「檔名（原因：說明）」以換行分隔
    notes: str = ""  # 提醒以換行分隔
    has_warning: bool = False
    noise_1hz: str = ""
    peak: str = ""
    floor_ratio: str = ""


@dataclass
class ReferenceRow:
    """d-4 的一列：1 Hz 雜訊、配對到的暗電流、理論白雜訊、實測÷理論。"""

    name: str = ""
    dark_name: str = ""  # 空白＝沒有配對
    dark_instrument: str = ""
    choice: str = AUTO_PAIR  # 手動配對選單目前的值
    manual: bool = False
    note: str = ""
    rsh: str = ""
    dark_current: str = ""
    shot: str = ""
    thermal: str = ""
    total: str = ""
    noise_1hz: str = ""
    ratio: str = ""
    below_theory: bool = False  # 實測低於理論下限（量測或換算有問題）


class NoiseState(CurvePickerMixin, GroupingMixin, SessionState):
    """Noise 頁面的狀態（SessionState 的子狀態）。"""

    tab: str = NoiseTab.UPLOAD.value
    loading: bool = False
    loaded_project: str = ""

    # 上傳與工作
    job_id: str = ""
    skipped: list[str] = []
    groups: list[NoiseGroupRow] = []
    group_bias: dict[str, str] = {}  # 組名 → 偏壓文字（偏壓篩選用）
    definition: str = NoiseDefinition.STANDARD.value

    # d-3 雜訊圖
    x_min: str = ""
    x_max: str = ""
    y_min: str = ""
    y_max: str = ""
    show_band: bool = True
    show_refs: bool = False
    plot_png: str = ""
    range_key: int = 0

    # d-4 數值與參考線
    has_dark: bool = False
    dark_names: list[str] = []
    ref_rows: list[ReferenceRow] = []

    # ---------- 計算屬性 ----------
    @rx.var
    def has_job(self) -> bool:
        """已成功上傳並建立工作。"""
        return self.job_id != ""

    @rx.var
    def plot_locked(self) -> bool:
        """在 d-3：整頁不捲動，只有勾選清單捲動。"""
        return self.tab == NoiseTab.PLOT.value

    @rx.var
    def bias_options(self) -> list[str]:
        """偏壓篩選按鈕：全部＋出現過的偏壓（0 V 在前）。"""
        values = sorted(set(self.group_bias.values()), key=lambda t: -float(t.split()[0]))
        return [ALL_BIAS, *values]

    @rx.var
    def warning_count(self) -> int:
        """有提醒或排除檔的組數。"""
        return sum(1 for g in self.groups if g.has_warning)

    @rx.var
    def pair_options(self) -> list[str]:
        """手動配對選單的暗電流曲線。"""
        return self.dark_names

    # ---------- 分頁與輸入框 ----------
    @rx.event
    def set_tab(self, value: str):
        """切換分頁；進入 d-4 時載入參考線配對。"""
        self.tab = value
        if value == NoiseTab.VALUES.value and self.has_job:
            return NoiseState.load_references
        return None

    @rx.event
    def go_to(self, tab: str):
        """「下一步」按鈕。"""
        return NoiseState.set_tab(tab)

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
    def set_show_band(self, value: bool) -> None:
        """是否畫 n 次的範圍帶。"""
        self.show_band = value

    @rx.event
    def set_show_refs(self, value: bool) -> None:
        """是否畫 Shot＋Thermal 參考線。"""
        self.show_refs = value

    @rx.event
    def reset_range(self) -> None:
        """範圍回到自動。"""
        self.x_min = self.x_max = self.y_min = self.y_max = ""
        self.range_key += 1

    @rx.event
    def select_bias(self, bias: str) -> None:
        """依偏壓勾選：只勾該偏壓的組（「全部」為全選）。"""
        if bias == ALL_BIAS:
            names = {c.name for c in self.pick_curves}
        else:
            names = {n for n, b in self.group_bias.items() if b == bias}
        self.plot_selected = self._in_display_order(names)

    # ---------- 工作內容 ----------
    def _apply_job(self, data: dict) -> None:
        """把 API 回傳的工作內容（NoiseJobOut）填入狀態。"""
        self.job_id = data["job_id"]
        self.skipped = data.get("skipped", [])
        self.definition = data["settings"]["definition"]
        rows = []
        for g in data["groups"]:
            excluded = [f"{e['source']}（{e['reason']}：{e['detail']}）" for e in g["excluded"]]
            rows.append(NoiseGroupRow(
                name=g["name"], sample=g["sample"], device=g.get("device") or "", bias=_bias_text(g["bias"]),
                bias_default=g["bias_default"], instrument=g["instrument"], n=int(g["n"]),
                files="、".join(g["files"]), excluded="\n".join(excluded), notes="\n".join(g["notes"]),
                has_warning=bool(excluded or g["notes"]), noise_1hz=_sci(g["noise_1hz"]),
                peak=_sci(g["peak_current"]), floor_ratio="—" if g["floor_ratio"] is None else f"{g['floor_ratio']:.1f}",
            ))
        self.groups = rows
        self.group_bias = {g.name: g.bias for g in rows}
        self.samples = data["devices"]  # GroupingMixin 的分組單位：樣品代號
        self._load_choices(data["project_conditions"])
        self._load_conditions(data["settings"].get("conditions"))
        self.pick_curves = [PickCurve(g.name, g.device) for g in rows if g.n > 0]  # n = 0 的組不能畫
        self._init_selection()

    def _job_path(self) -> str:
        """工作的 API 路徑（GroupingMixin 使用）。"""
        return f"/noise/jobs/{self.job_id}"

    def _handle_error(self, err: ApiError) -> None:
        """顯示錯誤；檔案錯誤停止作業（清除工作）。"""
        if err.kind is ErrorKind.FILE:
            self.reset()
        self._show_error(err)

    def _on_groups_changed(self) -> None:
        """分組改變：舊的圖失效（圖例順序會變）。"""
        self.plot_png = ""

    def _on_hidden_changed(self):
        """暫時隱藏改變：已有預覽圖時自動重畫（CurvePickerMixin 的掛鉤）。"""
        return NoiseState.plot_noise if self.plot_png else None

    # ---------- 專案（G-4） ----------
    def _project_key(self) -> str:
        """目前的「使用者/專案」。"""
        return f"{self.user}/{self.project}"

    @rx.event
    async def sync_project(self):
        """頁面載入：帶出目前專案的 D 區結果（換專案或重新上傳時先清除畫面）。"""
        if not self.user or not self.project:
            return
        project = await self._refresh_project()
        if project is None:
            return
        job_id = project["jobs"].get(SECTION.value, "")
        if self.loaded_project != self._project_key() or job_id != self.job_id:
            self.reset()
            self.loaded_project = self._project_key()
        if not job_id:
            return
        self.loading = True
        yield
        try:
            data = await api.get_json(f"/noise/jobs/{job_id}")
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self._apply_job(data)

    # ---------- 上傳 ----------
    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        """上傳 noise 檔（明志、PD-QE 的 csv）到目前專案。"""
        if not files:
            self._show_message("請先選擇檔案")
            return
        uploads = [(f.filename or f.name or "", await f.read()) for f in files]
        self.reset()
        self.loaded_project = self._project_key()
        self.loading = True
        yield
        try:
            params = {"user": self.user, "project": self.project}
            data = await api.upload("/noise/jobs", uploads, UPLOAD_TYPE, params)
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self.project_jobs = {**self.project_jobs, SECTION.value: data["job_id"]}
        self._apply_job(data)
        yield rx.clear_selected_files(UPLOAD_ID)

    # ---------- 定義 ----------
    @rx.event
    async def set_definition(self, value: str):
        """切換換算定義（標準／儀器）；已有預覽圖時重畫。"""
        if value == self.definition:
            return
        try:
            data = await api.put_json(f"/noise/jobs/{self.job_id}/settings", {"definition": value})
        except ApiError as err:
            self._handle_error(err)
            return
        self._apply_job(data)
        self.ref_rows = []
        if self.plot_png:
            yield NoiseState.plot_noise

    # ---------- Excel ----------
    @rx.event
    async def download_excel(self):
        """下載 Excel（Summary、Mean、Runs、Excluded）。"""
        self.loading = True
        yield
        try:
            name, content = await api.get_file(f"/noise/jobs/{self.job_id}/excel", EXCEL_FALLBACK_NAME)
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        yield rx.download(data=content, filename=name)

    # ---------- 雜訊圖（D-2） ----------
    @rx.event
    async def plot_noise(self):
        """d-3：勾選的組（平均實線＋範圍帶，可加參考線）；兩軸皆為對數。"""
        if not self.plot_selected:
            self._show_message("請至少勾選一組")
            return
        names = self._visible_selected()
        if not names:
            self._show_message("勾選的組都在暫時隱藏的區塊內，請先取消隱藏")
            return
        try:
            body = {
                "names": names,
                "x_range": parse_range(self.x_min, self.x_max, "X 軸", positive=True),
                "y_range": parse_range(self.y_min, self.y_max, "Y 軸", positive=True),
                "show_band": self.show_band,
                "references": self.show_refs,
            }
        except ValueError as exc:
            self._show_message(str(exc))
            return
        self.loading = True
        yield
        try:
            self.plot_png = png_data_url(await api.post_bytes(f"/noise/jobs/{self.job_id}/plots/noise", body))
        except ApiError as err:
            self._handle_error(err)
        finally:
            self.loading = False

    # ---------- 數值與參考線（d-4） ----------
    def _apply_references(self, data: dict) -> None:
        """把 API 回傳的配對結果（ReferencesOut）填入狀態。"""
        self.has_dark = bool(data["has_dark"])
        self.dark_names = list(data["dark_names"])
        rows = []
        for r in data["rows"]:
            choice = (r["dark_name"] or NO_PAIR) if r["manual"] else AUTO_PAIR
            ratio = r["ratio"]
            rows.append(ReferenceRow(
                name=r["name"], dark_name=r["dark_name"] or "", dark_instrument=r["dark_instrument"] or "",
                choice=choice, manual=bool(r["manual"]), note=r["note"], rsh=_sci(r["rsh"]),
                dark_current=_sci(r["dark_current"]), shot=_sci(r["shot"]), thermal=_sci(r["thermal"]),
                total=_sci(r["total"]), noise_1hz=_sci(r["noise_1hz"]),
                ratio="—" if ratio is None else f"{ratio:.3g}", below_theory=ratio is not None and ratio < 1,
            ))
        self.ref_rows = rows

    @rx.event
    async def load_references(self):
        """取得每組的 1 Hz 雜訊與 B-4 配對。"""
        self.loading = True
        yield
        try:
            data = await api.get_json(f"/noise/jobs/{self.job_id}/references")
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self._apply_references(data)

    @rx.event
    async def set_pair(self, name: str, choice: str):
        """手動配對：選暗電流曲線、「不配對」或「自動」。"""
        dark = None if choice == AUTO_PAIR else choice
        try:
            data = await api.put_json(f"/noise/jobs/{self.job_id}/reference-pairs", {"pairs": {name: dark}})
        except ApiError as err:
            self._handle_error(err)
            return
        self._apply_references(data)
        if self.plot_png and self.show_refs:
            yield NoiseState.plot_noise

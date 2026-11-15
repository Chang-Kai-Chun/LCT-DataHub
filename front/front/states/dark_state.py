"""B 區暗電流的狀態：b-1 整合（上傳、面積、偏移、Excel）→ b-2 分組 → b-3 暗電流圖。

伺服器（FastAPI）保存工作資料夾與設定（面積、偏移方式、分組）；這裡只保存畫面需要的內容。
API 的設定是一次送出 area 與 shift_mode 兩項，因此兩者都由這裡記住並一起送出。
分組邏輯與 A 區相同（GroupingMixin），分組單位是「樣品」（G1-1、G1-2 → G1），只影響畫圖勾選清單的排列；
勾選清單（條件區塊、每個樣品一直行、暫時隱藏）來自 CurvePickerMixin，與 C 區共用。
工作放在目前專案底下（G-4）：上傳時帶 user、project；頁面載入時帶出專案已有的 B 區結果。
所有 API 呼叫都是 async，失敗時開啟 ErrorState 的警告視窗。
"""
from dataclasses import dataclass

import reflex as rx

from front import api_client as api
from front.api_client import ApiError
from front.enums import DarkTab, ErrorKind, Section, ShiftMode
from front.states.common import AreaRow, fmt, parse_float, png_data_url
from front.states.grouping import GroupingMixin
from front.states.picker import CurvePickerMixin, PickCurve
from front.states.session import SessionState

SECTION = Section.DARK

UPLOAD_ID = "dark_upload"
UPLOAD_TYPE = "application/octet-stream"  # 副檔名有 txt、csv、dat、xlsx、xls，統一用二進位上傳
EXCEL_FALLBACK_NAME = "Dark.zip"  # 伺服器沒給檔名時使用
PLOT_NAME = "Dark_current.png"
# 上傳元件接受的副檔名（與 api/jobs.py 的 Section.DARK 相同）
ACCEPT = {"application/octet-stream": [".txt", ".csv", ".dat", ".xlsx", ".xls"]}


# ---------- 給 rx.foreach 使用的資料列 ----------
@dataclass
class DarkCurveRow:
    """一條暗電流曲線的摘要（數值已轉成顯示用文字）。"""

    name: str = ""
    device: str = ""  # 所屬元件；空白表示名稱無法辨識元件
    instrument: str = ""
    source: str = ""
    area: str = ""
    area_from_file: bool = True
    timestamp: str = ""
    points: int = 0
    removed_points: int = 0
    shift: str = ""
    is_shifted: bool = False


@dataclass
class ExtractRow:
    """B-4 擷取值的一列（數值已轉成顯示用文字）。"""

    name: str = ""
    instrument: str = ""
    shifted: bool = False
    shift: str = ""
    rsh: str = ""
    reference_rsh: str = ""  # PD-QE 儀器對照；明志為空白
    rsh_area: str = ""
    jd_0: str = ""
    jd_01: str = ""
    jd_05: str = ""


def _sci(value) -> str:
    """科學記號 4 位有效數字；None 顯示 —。"""
    return "—" if value is None else f"{value:.4g}"


def _fmt_shift(value: float) -> str:
    """偏移量（V）顯示為帶正負號、3 位小數。"""
    return f"{value:+.3f}"


class DarkState(CurvePickerMixin, GroupingMixin, SessionState):
    """暗電流頁面的狀態（SessionState 的子狀態：讀得到使用者與專案，共用警告視窗）。"""

    # 共用
    tab: str = DarkTab.INTEGRATE.value
    loading: bool = False
    loaded_project: str = ""  # 目前畫面內容屬於哪個「使用者/專案」（換專案時清除）

    # 上傳與工作
    job_id: str = ""
    skipped: list[str] = []
    curves: list[DarkCurveRow] = []

    # 面積
    area_uniform: bool = True
    area_uniform_value: str = ""
    area_values: list[str] = []
    area_rows: list[AreaRow] = []
    derived_sources: list[str] = []  # 檔內沒有面積（明志，由 |I|/J 反推）的檔名
    area_notice: str = ""
    area_override: str = ""  # 已套用的指定面積；空白表示沿用檔內面積
    area_confirmed: bool = False
    area_dialog_open: bool = False
    area_notice_open: bool = False
    area_input: str = ""

    # 最低點偏移（B-2）
    shift_mode: str = ShiftMode.KEEP.value

    # 暗電流圖（B-3）；勾選、暫時隱藏在 CurvePickerMixin
    skip_dialog_open: bool = False  # 「略過分組」的二次確認視窗
    x_min: str = ""
    x_max: str = ""
    y_min: str = ""
    y_max: str = ""
    range_key: int = 0  # 範圍輸入框為非受控，改回自動時遞增 key 讓輸入框重新掛載
    plot_png: str = ""

    # 擷取值（B-4）；E 區使用哪個電壓由 E 區選擇（API 的 extract-bias），這裡只顯示數值
    extract_rows: list[ExtractRow] = []

    # ---------- 計算屬性 ----------
    @rx.var
    def has_job(self) -> bool:
        """已成功上傳並建立工作。"""
        return self.job_id != ""

    @rx.var
    def ready(self) -> bool:
        """已上傳且面積已確認，可以進行後續步驟。"""
        return self.job_id != "" and self.area_confirmed

    @rx.var
    def curve_names(self) -> list[str]:
        """所有曲線名稱（勾選清單用）。"""
        return [c.name for c in self.curves]

    @rx.var
    def shifted_count(self) -> int:
        """被偏移的曲線數（偏移量為 0 的不算）。"""
        return sum(1 for c in self.curves if c.is_shifted)

    @rx.var
    def is_shift_mode(self) -> bool:
        """目前是否為「偏移到 0 V」。"""
        return self.shift_mode == ShiftMode.SHIFT.value

    @rx.var
    def plot_locked(self) -> bool:
        """目前在 b-3 暗電流圖：整頁不捲動，只有勾選清單捲動。"""
        return self.tab == DarkTab.PLOT.value

    # ---------- 分頁與輸入框 ----------
    @rx.event
    def set_tab(self, value: str):
        """切換分頁；進入 b-4 時重新取得擷取值（面積、偏移可能改過）。"""
        self.tab = value
        if value == DarkTab.EXTRACT.value and self.job_id:
            return DarkState.load_extract

    @rx.event
    def go_to(self, tab: str):
        """「下一步」按鈕：切到指定分頁。"""
        return DarkState.set_tab(tab)

    @rx.event
    def set_area_input(self, value: str) -> None:
        """面積輸入框。"""
        self.area_input = value

    @rx.event
    def set_area_dialog_open(self, value: bool) -> None:
        """面積視窗開關。"""
        self.area_dialog_open = value

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
        """Y 軸下限（對數，需大於 0）。"""
        self.y_min = value

    @rx.event
    def set_y_max(self, value: str) -> None:
        """Y 軸上限。"""
        self.y_max = value

    # ---------- 工作內容 ----------
    def _apply_job(self, data: dict) -> None:
        """把 API 回傳的工作內容（DarkJobOut）填入狀態。"""
        self.job_id = data["job_id"]
        self.skipped = data.get("skipped", [])
        self.curves = [
            DarkCurveRow(
                name=c["name"],
                device=c.get("device") or "",
                instrument=c["instrument"],
                source=c["source"],
                area=fmt(c["area"]),
                area_from_file=bool(c["area_from_file"]),
                timestamp=c.get("timestamp") or "",
                points=int(c["points"]),
                removed_points=int(c["removed_points"]),
                shift=_fmt_shift(float(c["shift"])),
                is_shifted=bool(c["is_shifted"]),
            )
            for c in data["curves"]
        ]

        report = data["area_report"]
        self.area_uniform = report["is_uniform"]
        self.area_uniform_value = fmt(report["uniform_value"])
        self.area_values = [fmt(v) for v in report["values"]]
        self.area_rows = [
            AreaRow(name, ", ".join(fmt(v) for v in values)) for name, values in report["by_file"].items()
        ]
        self.area_notice = data["area_notice"]

        settings = data["settings"]
        self.area_override = fmt(settings.get("area"))
        self.shift_mode = settings.get("shift_mode") or ShiftMode.KEEP.value
        self.samples = data["devices"]  # GroupingMixin 的分組單位：元件
        self._load_choices(data["project_conditions"])  # 專案統一的條件名稱
        self._load_conditions(settings.get("conditions"))
        # 沒有改面積時，area_from_file = False 代表檔內沒有面積（明志反推）；改面積後全部都是 False，不再列出
        if not self.area_override:
            self.derived_sources = sorted({c.source for c in self.curves if not c.area_from_file})

        # 勾選清單（CurvePickerMixin）：第一次載入時預設全選
        self.pick_curves = [PickCurve(c.name, c.device) for c in self.curves]
        self._init_selection()

    # ---------- GroupingMixin 需要的方法 ----------
    def _job_path(self) -> str:
        """工作的 API 路徑。"""
        return f"/dark/jobs/{self.job_id}"

    def _handle_error(self, err: ApiError) -> None:
        """顯示錯誤；檔案錯誤停止作業（清除工作）。"""
        if err.kind is ErrorKind.FILE:
            self.reset()
        self._show_error(err)

    async def _put_settings(self, area: float | None) -> bool:
        """送出面積與偏移方式（API 一次收兩項）；成功回傳 True，失敗時已顯示錯誤。"""
        body = {"area": area, "shift_mode": self.shift_mode}
        try:
            data = await api.put_json(f"/dark/jobs/{self.job_id}/settings", body)
        except ApiError as err:
            self._handle_error(err)
            return False
        self._apply_job(data)
        self.plot_png = ""  # 設定改變後，舊的圖與擷取值失效（進入 b-4 時重新取得）
        self.extract_rows = []
        return True

    def _current_area(self) -> float | None:
        """目前已套用的指定面積（沒有則為 None）。"""
        return float(self.area_override) if self.area_override else None

    # ---------- 專案（G-4） ----------
    def _project_key(self) -> str:
        """目前的「使用者/專案」。"""
        return f"{self.user}/{self.project}"

    def _auto_area_confirmed(self) -> bool:
        """上傳時可直接確認面積：面積一致、且都讀自檔內（明志的面積是反推的，須讓使用者確認）。"""
        return self.area_uniform and not self.derived_sources

    @rx.event
    async def sync_project(self):
        """頁面載入：帶出目前專案的 B 區結果（換專案或其他分頁重新上傳時，先清除畫面）。"""
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
            data = await api.get_json(f"/dark/jobs/{job_id}")
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self._apply_job(data)
        self.area_confirmed = bool(data["settings"].get("area_confirmed")) or self._auto_area_confirmed()

    # ---------- 上傳 ----------
    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        """上傳暗電流檔（PD-QE、明志）到目前專案；面積不一致或含反推面積時開啟面積確認視窗。"""
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
            data = await api.upload("/dark/jobs", uploads, UPLOAD_TYPE, params)
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self.project_jobs = {**self.project_jobs, SECTION.value: data["job_id"]}
        self._apply_job(data)
        # 面積一致、且都讀自檔內才直接確認；否則讓使用者確認（明志的面積是反推的，須提示）
        self.area_confirmed = self._auto_area_confirmed()
        self.area_dialog_open = not self.area_confirmed
        yield rx.clear_selected_files(UPLOAD_ID)

    # ---------- 面積確認 ----------
    @rx.event
    def open_area_dialog(self) -> None:
        """重新開啟面積視窗（例如想改用指定面積）。"""
        self.area_input = self.area_override
        self.area_dialog_open = True

    @rx.event
    async def area_ignore(self):
        """忽略並繼續：沿用檔內（或反推）的面積。"""
        if await self._put_settings(None):
            self.area_confirmed = True
            self.area_dialog_open = False

    @rx.event
    def area_request_override(self) -> None:
        """改用指定面積：先檢查輸入，再顯示「數據將被更動」警告。"""
        try:
            area = parse_float(self.area_input, "面積")
        except ValueError as exc:
            self._show_message(str(exc))
            return
        if area is None or area <= 0:
            self._show_message("面積必須是大於 0 的數值（cm²）")
            return
        self.area_notice_open = True

    @rx.event
    def area_cancel_notice(self) -> None:
        """取消改面積。"""
        self.area_notice_open = False

    @rx.event
    async def area_confirm_override(self):
        """使用者確認警告後，套用指定面積（API 以 |I| ÷ 面積重算 J）。"""
        self.area_notice_open = False
        try:
            area = parse_float(self.area_input, "面積")
        except ValueError as exc:
            self._show_message(str(exc))
            return
        if await self._put_settings(area):
            self.area_confirmed = True
            self.area_dialog_open = False

    # ---------- 最低點偏移（B-2） ----------
    @rx.event
    async def set_shift_mode(self, value: str | list[str]):
        """二選一：偏移到 0 V／保持原始；立即存到伺服器並取回各曲線的偏移量。"""
        value = value if isinstance(value, str) else value[0]
        if value == self.shift_mode:
            return
        previous = self.shift_mode
        self.shift_mode = value
        self.loading = True
        yield
        try:
            if not await self._put_settings(self._current_area()):
                self.shift_mode = previous  # 失敗時還原選項
        finally:
            self.loading = False

    # ---------- Excel ----------
    @rx.event
    async def download_excel(self):
        """下載整合 Excel：依儀器各一份，兩份時為 zip（檔名由伺服器決定）。"""
        self.loading = True
        yield
        try:
            name, content = await api.get_file(f"/dark/jobs/{self.job_id}/excel", EXCEL_FALLBACK_NAME)
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        yield rx.download(data=content, filename=name)

    # ---------- 擷取值（B-4） ----------
    def _apply_extract(self, data: dict) -> None:
        """把 API 回傳的擷取值（ExtractOut）填入狀態。"""
        self.extract_rows = [
            ExtractRow(
                name=r["name"], instrument=r["instrument"], shifted=r["shift"] != 0, shift=_fmt_shift(r["shift"]),
                rsh=_sci(r["rsh"]), reference_rsh="" if r["reference_rsh"] is None else _sci(r["reference_rsh"]),
                rsh_area=_sci(r["rsh_area"]),
                jd_0=_sci(r["jd"].get("0")), jd_01=_sci(r["jd"].get("-0.1")), jd_05=_sci(r["jd"].get("-0.5")),
            )
            for r in data["rows"]
        ]

    @rx.event
    async def load_extract(self):
        """取得擷取值（使用目前的面積與偏移設定）。"""
        self.loading = True
        yield
        try:
            data = await api.get_json(f"/dark/jobs/{self.job_id}/extract")
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self._apply_extract(data)

    # ---------- 暗電流圖（B-3） ----------
    def _on_hidden_changed(self):
        """暫時隱藏改變：已有預覽圖時自動重畫（CurvePickerMixin 的掛鉤）。"""
        return DarkState.plot_dark if self.plot_png else None

    # ---------- 略過分組（二次確認） ----------
    @rx.event
    def open_skip_dialog(self) -> None:
        """按下「略過分組」：先開確認視窗。"""
        self.skip_dialog_open = True

    @rx.event
    def cancel_skip(self) -> None:
        """取消略過，留在分組。"""
        self.skip_dialog_open = False

    @rx.event
    def confirm_skip(self) -> None:
        """確認略過分組，直接到暗電流圖。"""
        self.skip_dialog_open = False
        self.tab = DarkTab.PLOT.value

    @rx.event
    def reset_plot_range(self) -> None:
        """X、Y 範圍回到自動（輸入框重新掛載以清空）。"""
        self.x_min = self.x_max = self.y_min = self.y_max = ""
        self.range_key += 1

    def _ranges(self) -> tuple[list[float] | None, list[float] | None]:
        """檢查並取出 (X 範圍, Y 範圍)；留空為自動；格式錯誤拋出 ValueError。"""
        x_lo = parse_float(self.x_min, "X 軸下限")
        x_hi = parse_float(self.x_max, "X 軸上限")
        y_lo = parse_float(self.y_min, "Y 軸下限")
        y_hi = parse_float(self.y_max, "Y 軸上限")
        if (x_lo is None) != (x_hi is None):
            raise ValueError("X 軸範圍請同時填上下限，或兩個都留空（自動）")
        if (y_lo is None) != (y_hi is None):
            raise ValueError("Y 軸範圍請同時填上下限，或兩個都留空（自動）")
        if x_lo is not None and x_lo >= x_hi:
            raise ValueError("X 軸下限必須小於上限")
        if y_lo is not None:
            if y_lo <= 0:
                raise ValueError("Y 軸為對數座標，下限必須大於 0（例如 1e-10）")
            if y_lo >= y_hi:
                raise ValueError("Y 軸下限必須小於上限")
        x_range = [x_lo, x_hi] if x_lo is not None else None
        y_range = [y_lo, y_hi] if y_lo is not None else None
        return x_range, y_range

    @rx.event
    async def plot_dark(self):
        """畫暗電流疊圖（|J| 對數 Y 軸；有偏移時右上角註記 shift）。"""
        if not self.plot_selected:
            self._show_message("請至少勾選一個 pixel")
            return
        # 依目前的顯示順序排列（分組可能在勾選後才改），並排除暫時隱藏的區塊
        names = self._visible_selected()
        if not names:
            self._show_message("勾選的 pixel 都在暫時隱藏的區塊內，請先取消隱藏")
            return
        try:
            x_range, y_range = self._ranges()
        except ValueError as exc:
            self._show_message(str(exc))
            return
        body = {"names": names, "x_range": x_range, "y_range": y_range}
        self.loading = True
        yield
        try:
            png = await api.post_bytes(f"/dark/jobs/{self.job_id}/plots/dark", body)
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self.plot_png = png_data_url(png)

"""C 區 EQE 的狀態：c-1 上傳（含舊型命名、Excel）→ c-2 分組 → c-3 EQE 與積分電流 → c-4 R-plot。

- 舊型儀器的樣品會自動編號 S1、S2…；API 回傳的 unnamed 不為空時，必須先命名才能分組
- 分組單位與 B 區相同（樣品：G1-1、G1-2 → G1，GroupingMixin）；勾選清單與 B 區共用（CurvePickerMixin），
  c-3、c-4 共用同一份勾選
- 工作放在目前專案底下（G-4）：上傳時帶 user、project；頁面載入時帶出專案已有的 C 區結果
所有 API 呼叫都是 async，失敗時開啟 ErrorState 的警告視窗。
"""
from dataclasses import dataclass

import reflex as rx

from front import api_client as api
from front.api_client import ApiError
from front.enums import EqeTab, ErrorKind, Section
from front.states.common import fmt, parse_range, png_data_url
from front.states.grouping import GroupingMixin
from front.states.picker import CurvePickerMixin, PickCurve
from front.states.session import SessionState

SECTION = Section.EQE
UPLOAD_ID = "eqe_upload"
UPLOAD_TYPE = "application/octet-stream"  # txt、xls、xlsx 統一用二進位上傳
ACCEPT = {"application/octet-stream": [".txt", ".xls", ".xlsx"]}  # 與 api/jobs.py 的 Section.EQE 相同
EXCEL_FALLBACK_NAME = "EQE.zip"
EQE_PLOT_NAME = "EQE.png"
RPLOT_NAME = "R-plot.png"
OLD_INSTRUMENT = "舊型（五樓）"  # core.eqe.types.EqeInstrument.OLD 的 value
DEFAULT_EQE_RANGE = ("0", "100")  # EQE 軸預設 0–100（與 core.plotting.DEFAULT_EQE_RANGE 相同）


@dataclass
class EqeCurveRow:
    """一個 pixel 的摘要（數值已轉成顯示用文字）。"""

    name: str = ""
    original_name: str = ""
    device: str = ""
    instrument: str = ""
    source: str = ""
    points: int = 0
    jsc: str = ""
    timestamp: str = ""
    bias: str = ""


@dataclass
class NameEdit:
    """舊型樣品命名的一列：原始編號、目前名稱、輸入框內容。"""

    original: str = ""
    current: str = ""
    value: str = ""
    unnamed: bool = True


class EqeState(CurvePickerMixin, GroupingMixin, SessionState):
    """EQE 頁面的狀態（SessionState 的子狀態）。"""

    tab: str = EqeTab.UPLOAD.value
    loading: bool = False
    loaded_project: str = ""

    # 上傳與工作
    job_id: str = ""
    skipped: list[str] = []
    curves: list[EqeCurveRow] = []
    unnamed: list[str] = []  # 尚未命名的舊型樣品

    # 舊型命名：原始編號 → 輸入框內容
    name_edits: dict[str, str] = {}
    name_key: int = 0  # 輸入框為非受控，重新載入命名時遞增 key

    # c-3 EQE 與積分電流
    eqe_x_min: str = ""
    eqe_x_max: str = ""
    eqe_y_min: str = DEFAULT_EQE_RANGE[0]
    eqe_y_max: str = DEFAULT_EQE_RANGE[1]
    jsc_min: str = ""
    jsc_max: str = ""
    show_jsc: bool = True
    eqe_png: str = ""

    # c-4 R-plot
    r_x_min: str = ""
    r_x_max: str = ""
    r_y_min: str = ""
    r_y_max: str = ""
    rplot_png: str = ""

    range_key: int = 0  # 「範圍改回預設」時遞增，讓非受控輸入框重新掛載

    # ---------- 計算屬性 ----------
    @rx.var
    def has_job(self) -> bool:
        """已成功上傳並建立工作。"""
        return self.job_id != ""

    @rx.var
    def needs_naming(self) -> bool:
        """還有舊型樣品沒命名（不能分組）。"""
        return len(self.unnamed) > 0

    @rx.var
    def name_rows(self) -> list[NameEdit]:
        """舊型樣品命名表（依讀檔順序）。"""
        return [
            NameEdit(c.original_name, c.name, self.name_edits.get(c.original_name, c.name), c.name in self.unnamed)
            for c in self.curves if c.instrument == OLD_INSTRUMENT
        ]

    @rx.var
    def plot_locked(self) -> bool:
        """在 c-3、c-4：整頁不捲動，只有勾選清單捲動。"""
        return self.tab in (EqeTab.EQE.value, EqeTab.RPLOT.value)

    # ---------- 分頁與輸入框 ----------
    @rx.event
    def set_tab(self, value: str) -> None:
        """切換分頁。"""
        self.tab = value

    @rx.event
    def go_to(self, tab: str) -> None:
        """「下一步」按鈕。"""
        self.tab = tab

    @rx.event
    def set_name_edit(self, original: str, value: str) -> None:
        """舊型樣品的新名稱。"""
        self.name_edits = {**self.name_edits, original: value}

    @rx.event
    def set_eqe_x_min(self, value: str) -> None:
        """EQE 圖 X 軸下限。"""
        self.eqe_x_min = value

    @rx.event
    def set_eqe_x_max(self, value: str) -> None:
        """EQE 圖 X 軸上限。"""
        self.eqe_x_max = value

    @rx.event
    def set_eqe_y_min(self, value: str) -> None:
        """EQE 軸下限。"""
        self.eqe_y_min = value

    @rx.event
    def set_eqe_y_max(self, value: str) -> None:
        """EQE 軸上限。"""
        self.eqe_y_max = value

    @rx.event
    def set_jsc_min(self, value: str) -> None:
        """積分電流軸下限。"""
        self.jsc_min = value

    @rx.event
    def set_jsc_max(self, value: str) -> None:
        """積分電流軸上限。"""
        self.jsc_max = value

    @rx.event
    def set_show_jsc(self, value: bool) -> None:
        """是否顯示右軸（積分電流）。"""
        self.show_jsc = value

    @rx.event
    def set_r_x_min(self, value: str) -> None:
        """R-plot X 軸下限。"""
        self.r_x_min = value

    @rx.event
    def set_r_x_max(self, value: str) -> None:
        """R-plot X 軸上限。"""
        self.r_x_max = value

    @rx.event
    def set_r_y_min(self, value: str) -> None:
        """R-plot Y 軸下限。"""
        self.r_y_min = value

    @rx.event
    def set_r_y_max(self, value: str) -> None:
        """R-plot Y 軸上限。"""
        self.r_y_max = value

    @rx.event
    def reset_eqe_range(self) -> None:
        """EQE 圖範圍回到預設（X、積分電流自動；EQE 0–100）。"""
        self.eqe_x_min = self.eqe_x_max = self.jsc_min = self.jsc_max = ""
        self.eqe_y_min, self.eqe_y_max = DEFAULT_EQE_RANGE
        self.range_key += 1

    @rx.event
    def reset_r_range(self) -> None:
        """R-plot 範圍回到自動。"""
        self.r_x_min = self.r_x_max = self.r_y_min = self.r_y_max = ""
        self.range_key += 1

    # ---------- 工作內容 ----------
    def _apply_job(self, data: dict) -> None:
        """把 API 回傳的工作內容（EqeJobOut）填入狀態。"""
        self.job_id = data["job_id"]
        self.skipped = data.get("skipped", [])
        self.curves = [
            EqeCurveRow(
                name=c["name"], original_name=c["original_name"], device=c.get("device") or "",
                instrument=c["instrument"], source=c["source"], points=int(c["points"]), jsc=fmt(float(c["jsc"])),
                timestamp=c.get("timestamp") or "", bias=fmt(c.get("bias")),
            )
            for c in data["curves"]
        ]
        self.unnamed = list(data["unnamed"])
        # 命名輸入框：以目前名稱為初始值
        self.name_edits = {c.original_name: c.name for c in self.curves if c.instrument == OLD_INSTRUMENT}
        self.name_key += 1

        self.samples = data["devices"]  # GroupingMixin 的分組單位：樣品
        self._load_choices(data["project_conditions"])
        self._load_conditions(data["settings"].get("conditions"))
        self.pick_curves = [PickCurve(c.name, c.device) for c in self.curves]
        self._init_selection()

    def _job_path(self) -> str:
        """工作的 API 路徑（GroupingMixin 使用）。"""
        return f"/eqe/jobs/{self.job_id}"

    def _handle_error(self, err: ApiError) -> None:
        """顯示錯誤；檔案錯誤停止作業（清除工作）。"""
        if err.kind is ErrorKind.FILE:
            self.reset()
        self._show_error(err)

    def _on_groups_changed(self) -> None:
        """分組改變：舊的圖失效（圖例順序會變）。"""
        self.eqe_png = self.rplot_png = ""

    def _on_hidden_changed(self):
        """暫時隱藏改變：目前分頁已有預覽圖時自動重畫（CurvePickerMixin 的掛鉤）。"""
        if self.tab == EqeTab.EQE.value and self.eqe_png:
            return EqeState.plot_eqe
        if self.tab == EqeTab.RPLOT.value and self.rplot_png:
            return EqeState.plot_rplot
        return None

    # ---------- 專案（G-4） ----------
    def _project_key(self) -> str:
        """目前的「使用者/專案」。"""
        return f"{self.user}/{self.project}"

    @rx.event
    async def sync_project(self):
        """頁面載入：帶出目前專案的 C 區結果（換專案或其他分頁重新上傳時，先清除畫面）。"""
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
            data = await api.get_json(f"/eqe/jobs/{job_id}")
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self._apply_job(data)

    # ---------- 上傳 ----------
    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        """上傳 EQE 檔（新型 PD-QE TXT、舊型 xls）到目前專案。"""
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
            data = await api.upload("/eqe/jobs", uploads, UPLOAD_TYPE, params)
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self.project_jobs = {**self.project_jobs, SECTION.value: data["job_id"]}
        self._apply_job(data)
        yield rx.clear_selected_files(UPLOAD_ID)

    # ---------- 舊型命名 ----------
    @rx.event
    async def save_names(self):
        """儲存舊型樣品的名稱（送出完整對照）；空白、重複由 API 檢查；樣品組成改變時分組會被清除。"""
        names = {orig: value.strip() for orig, value in self.name_edits.items() if value.strip() != orig}
        empty = [orig for orig, value in self.name_edits.items() if not value.strip()]
        if empty:
            self._show_message("名稱不可空白：" + "、".join(empty))
            return
        try:
            data = await api.put_json(f"/eqe/jobs/{self.job_id}/names", {"names": names})
        except ApiError as err:
            self._handle_error(err)
            return
        self._apply_job(data)
        self.eqe_png = self.rplot_png = ""
        yield rx.toast.success("名稱已儲存")

    # ---------- Excel ----------
    @rx.event
    async def download_excel(self):
        """下載整合 Excel：依儀器各一份，兩份時為 zip（檔名由伺服器決定）。"""
        self.loading = True
        yield
        try:
            name, content = await api.get_file(f"/eqe/jobs/{self.job_id}/excel", EXCEL_FALLBACK_NAME)
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        yield rx.download(data=content, filename=name)

    # ---------- 畫圖 ----------
    def _plot_names(self) -> list[str] | None:
        """要畫的 pixel（排除暫時隱藏）；沒有可畫的時顯示訊息並回傳 None。"""
        if not self.plot_selected:
            self._show_message("請至少勾選一個 pixel")
            return None
        names = self._visible_selected()
        if not names:
            self._show_message("勾選的 pixel 都在暫時隱藏的區塊內，請先取消隱藏")
            return None
        return names

    async def _post_png(self, path: str, body: dict) -> str:
        """送出畫圖請求並回傳 data URL；失敗時已顯示錯誤並回傳空字串。"""
        try:
            return png_data_url(await api.post_bytes(path, body))
        except ApiError as err:
            self._handle_error(err)
            return ""

    @rx.event
    async def plot_eqe(self):
        """c-3：EQE（左軸）加積分電流（右軸）；X 軸由使用者輸入（留空為自動）。"""
        names = self._plot_names()
        if names is None:
            return
        try:
            body = {
                "names": names,
                "x_range": parse_range(self.eqe_x_min, self.eqe_x_max, "X 軸"),
                "eqe_range": parse_range(self.eqe_y_min, self.eqe_y_max, "EQE 軸"),
                "jsc_range": parse_range(self.jsc_min, self.jsc_max, "積分電流軸"),
                "show_jsc": self.show_jsc,
            }
        except ValueError as exc:
            self._show_message(str(exc))
            return
        self.loading = True
        yield
        png = await self._post_png(f"/eqe/jobs/{self.job_id}/plots/eqe", body)
        self.loading = False
        if png:
            self.eqe_png = png

    @rx.event
    async def plot_rplot(self):
        """c-4：R-plot（SR，A/W）。"""
        names = self._plot_names()
        if names is None:
            return
        try:
            body = {
                "names": names,
                "x_range": parse_range(self.r_x_min, self.r_x_max, "X 軸"),
                "y_range": parse_range(self.r_y_min, self.r_y_max, "Y 軸"),
            }
        except ValueError as exc:
            self._show_message(str(exc))
            return
        self.loading = True
        yield
        png = await self._post_png(f"/eqe/jobs/{self.job_id}/plots/rplot", body)
        self.loading = False
        if png:
            self.rplot_png = png

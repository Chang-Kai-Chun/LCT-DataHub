"""A 區 JV 的狀態：上傳 → 面積確認 → 分組 → Excel → Box 圖 → JV 曲線。

伺服器（FastAPI）保存工作資料夾與已確認的設定；這裡只保存畫面需要的內容。
工作放在目前專案底下（G-4）：上傳時帶 user、project；頁面載入時帶出專案已有的 A 區結果。
Box 表狀態不存在伺服器（11/06 決定），每次由這裡送出方向、範圍、手動保留。
所有 API 呼叫都是 async，失敗時開啟 ErrorState 的警告視窗。
"""
from dataclasses import dataclass

import reflex as rx

from front import api_client as api
from front.api_client import ApiError
from front.enums import BOX_FILTER_PARAMS, BoxColumn, Direction, DirectionMode, ErrorKind, JVParam, JVTab, Section
from front.states.common import AreaRow, fmt, parse_float, png_data_url
from front.states.grouping import GroupingMixin
from front.states.session import SessionState

SECTION = Section.JV

UPLOAD_ID = "jv_upload"
CSV_TYPE = "text/csv"
EXCEL_NAME = "ALL_Data.xlsx"
DEFAULT_Y_RANGE = ("-40", "10")  # JV 曲線 Y 軸預設（mA/cm²），與 core.jv.curve.DEFAULT_Y_RANGE 相同


# ---------- 給 rx.foreach 使用的資料列 ----------
@dataclass
class FileRow:
    """上傳檔案摘要的一列。"""

    filename: str = ""
    sample: str = ""
    direction: str = ""
    pixels: str = ""


@dataclass
class MissingRow:
    """條件中列出、但找不到檔案的樣品與方向。"""

    condition: str = ""
    sample: str = ""
    direction: str = ""


@dataclass
class BoxRow:
    """Box 表的一列（數值已轉成顯示用文字）。"""

    row: int = 0
    condition: str = ""
    sample: str = ""
    direction: str = ""
    pixel: str = ""
    pce: str = ""
    voc: str = ""
    jsc: str = ""
    ff: str = ""
    rsh: str = ""
    keep: bool = True


class JVState(GroupingMixin, SessionState):
    """JV 頁面的狀態（SessionState 的子狀態：讀得到使用者與專案，共用警告視窗；分組狀態來自 GroupingMixin）。"""

    # 共用
    tab: str = JVTab.UPLOAD.value
    loading: bool = False
    loaded_project: str = ""  # 目前畫面內容屬於哪個「使用者/專案」（換專案時清除）

    # 上傳與工作
    job_id: str = ""
    skipped: list[str] = []
    files: list[FileRow] = []
    # samples（依數字排序，API 已排序）與分組欄位定義在 GroupingMixin

    # 面積
    area_uniform: bool = True
    area_uniform_value: str = ""
    area_values: list[str] = []
    area_rows: list[AreaRow] = []
    area_notice: str = ""
    recomputed_params: list[str] = []
    area_override: str = ""  # 已套用的指定面積；空白表示沿用檔內面積
    area_confirmed: bool = False
    area_dialog_open: bool = False
    area_notice_open: bool = False
    area_input: str = ""

    # 分組檢查：條件中列出、但找不到檔案的樣品
    missing: list[MissingRow] = []

    # Excel
    excel_fw: bool = True
    excel_rv: bool = False

    # Box 圖
    box_mode: str = DirectionMode.FW.value
    sample_dirs: dict[str, str] = {}  # 逐樣品選擇時：樣品 → FW／RV
    range_min: dict[str, str] = {p.value: "" for p in BOX_FILTER_PARAMS}
    range_max: dict[str, str] = {p.value: "" for p in BOX_FILTER_PARAMS}
    keep_overrides: dict[str, bool] = {}  # 列號（字串）→ 手動保留
    box_rows: list[BoxRow] = []
    box_param: str = JVParam.PCE.value
    box_ymin: str = ""
    box_ymax: str = ""
    box_png: str = ""

    # JV 曲線
    curve_selected: list[str] = []
    curve_fw: bool = True
    curve_rv: bool = False
    curve_ymin: str = DEFAULT_Y_RANGE[0]
    curve_ymax: str = DEFAULT_Y_RANGE[1]
    curve_png: str = ""

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
    def kept_count(self) -> int:
        """Box 表中保留的筆數。"""
        return sum(1 for r in self.box_rows if r.keep)

    # ---------- 分頁與輸入框 ----------
    @rx.event
    def set_tab(self, value: str) -> None:
        """切換分頁。"""
        self.tab = value

    @rx.event
    def go_to(self, tab: str) -> None:
        """「下一步」按鈕：切到指定分頁。"""
        self.tab = tab

    @rx.event
    def set_area_input(self, value: str) -> None:
        """面積輸入框。"""
        self.area_input = value

    @rx.event
    def set_area_dialog_open(self, value: bool) -> None:
        """面積視窗開關。"""
        self.area_dialog_open = value

    @rx.event
    def set_excel_fw(self, value: bool) -> None:
        """Excel 參數 sheet 是否含 FW。"""
        self.excel_fw = value

    @rx.event
    def set_excel_rv(self, value: bool) -> None:
        """Excel 參數 sheet 是否含 RV。"""
        self.excel_rv = value

    @rx.event
    def set_box_mode(self, value: str) -> None:
        """Box 取用方向；換方向後列號會改變，手動保留一併清除。"""
        self.box_mode = value
        self.keep_overrides = {}
        self.box_rows = []
        self.box_png = ""

    @rx.event
    def set_sample_dir(self, sample: str, value: str) -> None:
        """逐樣品選擇：指定某樣品的方向。"""
        self.sample_dirs = {**self.sample_dirs, sample: value}
        self.keep_overrides = {}

    @rx.event
    def set_range_min(self, param: str, value: str) -> None:
        """篩選下限。"""
        self.range_min = {**self.range_min, param: value}

    @rx.event
    def set_range_max(self, param: str, value: str) -> None:
        """篩選上限。"""
        self.range_max = {**self.range_max, param: value}

    @rx.event
    def set_box_param(self, value: str) -> None:
        """Box 圖的參數。"""
        self.box_param = value
        self.box_png = ""

    @rx.event
    def set_box_ymin(self, value: str) -> None:
        """Box 圖 Y 軸下限。"""
        self.box_ymin = value

    @rx.event
    def set_box_ymax(self, value: str) -> None:
        """Box 圖 Y 軸上限。"""
        self.box_ymax = value

    @rx.event
    def set_curve_fw(self, value: bool) -> None:
        """JV 曲線是否畫 FW。"""
        self.curve_fw = value

    @rx.event
    def set_curve_rv(self, value: bool) -> None:
        """JV 曲線是否畫 RV。"""
        self.curve_rv = value

    @rx.event
    def set_curve_ymin(self, value: str) -> None:
        """JV 曲線 Y 軸下限。"""
        self.curve_ymin = value

    @rx.event
    def set_curve_ymax(self, value: str) -> None:
        """JV 曲線 Y 軸上限。"""
        self.curve_ymax = value

    # ---------- 工作內容 ----------
    def _reset_job(self) -> None:
        """清除目前工作（重新上傳或檔案錯誤停止作業時）。"""
        self.reset()

    def _apply_job(self, data: dict) -> None:
        """把 API 回傳的工作內容（JVJobOut）填入狀態。"""
        self.job_id = data["job_id"]
        self.skipped = data.get("skipped", [])
        self.samples = data["samples"]
        self.files = [
            FileRow(f["filename"], f["sample"], f["direction"], "".join(str(p) for p in f["pixels"]))
            for f in data["files"]
        ]

        report = data["area_report"]
        self.area_uniform = report["is_uniform"]
        self.area_uniform_value = fmt(report["uniform_value"])
        self.area_values = [fmt(v) for v in report["values"]]
        self.area_rows = [
            AreaRow(name, ", ".join(fmt(v) for v in values)) for name, values in report["by_file"].items()
        ]
        self.area_notice = data["area_notice"]
        self.recomputed_params = data["recomputed_params"]

        settings = data["settings"]
        self.area_override = fmt(settings.get("area"))
        self._load_choices(data["project_conditions"])  # GroupingMixin：專案統一的條件名稱
        self._load_conditions(settings.get("conditions"))  # GroupingMixin：已確認的分組
        self.missing = [MissingRow(m["condition"], m["sample"], m["direction"]) for m in data.get("missing", [])]

        # 第一次載入時，JV 曲線預設全選、逐樣品方向預設 FW
        if not self.curve_selected:
            self.curve_selected = list(self.samples)
        self.sample_dirs = {s: self.sample_dirs.get(s, Direction.FW.value) for s in self.samples}

    # ---------- GroupingMixin 需要的方法 ----------
    def _job_path(self) -> str:
        """工作的 API 路徑。"""
        return f"/jv/jobs/{self.job_id}"

    def _on_groups_changed(self) -> None:
        """分組被修改：Box 表與 Box 圖失效。"""
        self.box_rows, self.box_png = [], ""

    def _on_groups_confirmed(self) -> None:
        """分組確認後：列號會改變，手動保留清除。"""
        self.keep_overrides = {}

    def _handle_error(self, err: ApiError) -> None:
        """顯示錯誤；檔案錯誤停止作業（清除工作）。"""
        if err.kind is ErrorKind.FILE:
            self._reset_job()
        self._show_error(err)

    # ---------- 專案（G-4） ----------
    def _project_key(self) -> str:
        """目前的「使用者/專案」。"""
        return f"{self.user}/{self.project}"

    @rx.event
    async def sync_project(self):
        """頁面載入：帶出目前專案的 A 區結果（換專案或其他分頁重新上傳時，先清除畫面）。"""
        if not self.user or not self.project:
            return
        project = await self._refresh_project()
        if project is None:
            return
        job_id = project["jobs"].get(SECTION.value, "")
        if self.loaded_project != self._project_key() or job_id != self.job_id:
            self._reset_job()
            self.loaded_project = self._project_key()
        if not job_id:
            return
        self.loading = True
        yield
        try:
            data = await api.get_json(f"/jv/jobs/{job_id}")
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self._apply_job(data)
        # 使用者已在面積視窗選擇過，或面積一致（上傳時自動確認）
        self.area_confirmed = bool(data["settings"].get("area_confirmed")) or self.area_uniform

    # ---------- 上傳 ----------
    @rx.event
    async def handle_upload(self, files: list[rx.UploadFile]):
        """上傳 JV CSV（檔名如 G1 FW 432.csv 或 G1FW432.csv）到目前專案；面積不一致時開啟面積確認視窗。"""
        if not files:
            self._show_message("請先選擇檔案")
            return
        uploads = [(f.filename or f.name or "", await f.read()) for f in files]
        self._reset_job()
        self.loaded_project = self._project_key()
        self.loading = True
        yield
        try:
            params = {"user": self.user, "project": self.project}
            data = await api.upload("/jv/jobs", uploads, CSV_TYPE, params)
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self.project_jobs = {**self.project_jobs, SECTION.value: data["job_id"]}
        self._apply_job(data)
        # 面積一致就直接確認；不一致時讓使用者選擇
        self.area_confirmed = self.area_uniform
        self.area_dialog_open = not self.area_uniform
        yield rx.clear_selected_files(UPLOAD_ID)

    # ---------- 面積確認 ----------
    @rx.event
    def open_area_dialog(self) -> None:
        """重新開啟面積視窗（例如想改用指定面積）。"""
        self.area_input = self.area_override
        self.area_dialog_open = True

    @rx.event
    async def area_ignore(self):
        """忽略並繼續：沿用檔內面積（PUT area = null）。"""
        try:
            data = await api.put_json(f"/jv/jobs/{self.job_id}/area", {"area": None})
        except ApiError as err:
            self._handle_error(err)
            return
        self._apply_job(data)
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
        """使用者確認警告後，套用指定面積（API 重算 J、Jsc、PCE）。"""
        self.area_notice_open = False
        try:
            area = parse_float(self.area_input, "面積")
            data = await api.put_json(f"/jv/jobs/{self.job_id}/area", {"area": area})
        except ValueError as exc:
            self._show_message(str(exc))
            return
        except ApiError as err:
            self._handle_error(err)
            return
        self._apply_job(data)
        self.area_confirmed = True
        self.area_dialog_open = False
        # 面積改變後，舊的圖與 Box 表都失效
        self.box_rows, self.box_png, self.curve_png = [], "", ""

    # ---------- Excel ----------
    @rx.event
    async def download_excel(self):
        """下載 ALL_Data.xlsx（參數 sheet 依勾選的方向）。"""
        directions = [d.value for d, on in ((Direction.FW, self.excel_fw), (Direction.RV, self.excel_rv)) if on]
        if not directions:
            self._show_message("請至少勾選一個方向（FW 或 RV）")
            return
        self.loading = True
        yield
        try:
            content = await api.get_bytes(f"/jv/jobs/{self.job_id}/excel", params={"directions": directions})
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        yield rx.download(data=content, filename=EXCEL_NAME)

    # ---------- Box 圖 ----------
    def _box_body(self) -> dict:
        """組出 Box 表參數（方向、範圍、手動保留）；輸入格式錯誤拋出 ValueError。"""
        ranges = {}
        for param in BOX_FILTER_PARAMS:
            lo = parse_float(self.range_min.get(param.value, ""), f"{param.value} 下限")
            hi = parse_float(self.range_max.get(param.value, ""), f"{param.value} 上限")
            if lo is not None and hi is not None and lo > hi:
                raise ValueError(f"「{param.value}」下限不可大於上限")
            if lo is not None or hi is not None:
                ranges[param.value] = {"minimum": lo, "maximum": hi}
        body: dict = {
            "mode": self.box_mode,
            "ranges": ranges,
            "keep": {int(k): v for k, v in self.keep_overrides.items()},
        }
        if self.box_mode == DirectionMode.PER_SAMPLE.value:
            body["sample_directions"] = dict(self.sample_dirs)
        return body

    async def _load_box_table(self) -> None:
        """向 API 取得 Box 表並轉成顯示用的列；失敗時拋出 ApiError 或 ValueError。"""
        rows = await api.post_json(f"/jv/jobs/{self.job_id}/box/table", self._box_body())
        self.box_rows = [
            BoxRow(
                row=int(r[BoxColumn.ROW.value]),
                condition=str(r[BoxColumn.CONDITION.value]),
                sample=str(r[BoxColumn.SAMPLE.value]),
                direction=str(r[BoxColumn.DIRECTION.value]),
                pixel=fmt(r[BoxColumn.PIXEL.value]),
                pce=fmt(r.get(JVParam.PCE.value)),
                voc=fmt(r.get(JVParam.VOC.value)),
                jsc=fmt(r.get(JVParam.JSC.value)),
                ff=fmt(r.get(JVParam.FF.value)),
                rsh=fmt(r.get(JVParam.RSH.value)),
                keep=bool(r[BoxColumn.KEEP.value]),
            )
            for r in rows
        ]

    @rx.event
    async def refresh_box_table(self):
        """套用方向與範圍篩選，更新 Box 表給使用者確認。"""
        try:
            await self._load_box_table()
        except ValueError as exc:
            self._show_message(str(exc))
        except ApiError as err:
            self._handle_error(err)

    @rx.event
    async def toggle_keep(self, row: int, value: bool):
        """手動勾選是否保留某一列，然後更新表格。"""
        self.keep_overrides = {**self.keep_overrides, str(row): value}
        try:
            await self._load_box_table()
        except (ValueError, ApiError) as err:
            self._show_message(str(err))

    @rx.event
    async def reset_keep(self):
        """清除所有手動保留，回到篩選結果。"""
        self.keep_overrides = {}
        try:
            await self._load_box_table()
        except (ValueError, ApiError) as err:
            self._show_message(str(err))

    @rx.event
    async def plot_box(self):
        """畫目前參數的 Box 圖（只畫保留的值）。"""
        try:
            body = self._box_body()
            lo = parse_float(self.box_ymin, "Y 軸下限")
            hi = parse_float(self.box_ymax, "Y 軸上限")
        except ValueError as exc:
            self._show_message(str(exc))
            return
        if (lo is None) != (hi is None):
            self._show_message("Y 軸範圍請同時填上下限，或兩個都留空（自動）")
            return
        body["param"] = self.box_param
        body["y_range"] = [lo, hi] if lo is not None else None
        self.loading = True
        yield
        try:
            png = await api.post_bytes(f"/jv/jobs/{self.job_id}/box/plot", body)
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self.box_png = png_data_url(png)

    # ---------- JV 曲線 ----------
    @rx.event
    def toggle_curve_sample(self, sample: str, checked: bool) -> None:
        """勾選或取消某樣品。"""
        if checked:
            self.curve_selected = self._sorted(list({*self.curve_selected, sample}))
        else:
            self.curve_selected = [s for s in self.curve_selected if s != sample]

    @rx.event
    def select_all_curves(self) -> None:
        """全選。"""
        self.curve_selected = list(self.samples)

    @rx.event
    def select_no_curves(self) -> None:
        """全消。"""
        self.curve_selected = []

    @rx.event
    def reset_curve_range(self) -> None:
        """Y 軸範圍回到預設 −40 到 10 mA/cm²。"""
        self.curve_ymin, self.curve_ymax = DEFAULT_Y_RANGE

    @rx.event
    async def plot_curves(self):
        """畫 JV 曲線疊圖（FW 實線、RV 虛線）。"""
        directions = [d.value for d, on in ((Direction.FW, self.curve_fw), (Direction.RV, self.curve_rv)) if on]
        if not self.curve_selected:
            self._show_message("請至少勾選一個樣品")
            return
        if not directions:
            self._show_message("請至少勾選一個方向（FW 或 RV）")
            return
        try:
            lo = parse_float(self.curve_ymin, "Y 軸下限")
            hi = parse_float(self.curve_ymax, "Y 軸上限")
        except ValueError as exc:
            self._show_message(str(exc))
            return
        if lo is None or hi is None or lo >= hi:
            self._show_message("Y 軸範圍需要填上下限，且下限小於上限")
            return
        body = {"samples": self.curve_selected, "directions": directions, "y_range": [lo, hi]}
        self.loading = True
        yield
        try:
            png = await api.post_bytes(f"/jv/jobs/{self.job_id}/curves/plot", body)
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.loading = False
        self.curve_png = png_data_url(png)

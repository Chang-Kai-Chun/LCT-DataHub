"""G-5 報告輸出（PD 報告）的狀態：封面資訊、每個條件的代表 pixel、元件結構圖、下載 PPT。

- 條件取自專案總覽的分組；每個條件選一顆代表 pixel（預設 D* 最高；選「不列入」就不放進報告）
- 封面資訊與選擇存在專案（report.json），下次自動帶出
所有 API 呼叫都是 async，失敗時開啟 ErrorState 的警告視窗。
"""
from dataclasses import dataclass, field

import reflex as rx

from front import api_client as api
from front.api_client import ApiError, Method
from front.states.session import SessionState

IMAGE_UPLOAD_ID = "report_image"
IMAGE_ACCEPT = {"image/png": [".png"], "image/jpeg": [".jpg", ".jpeg"]}
PPTX_FALLBACK_NAME = "PD報告.pptx"
NOT_INCLUDED = ""  # 代表 pixel 選單：不列入


@dataclass
class PixelOption:
    """條件底下的一顆 pixel（顯示用文字）。"""

    pixel: str = ""
    label: str = ""  # 「G6-1　D* 2.5e10（實測）」


@dataclass
class ConditionRow:
    """一個條件：代表 pixel 與選項。"""

    name: str = ""
    selected: str = ""
    options: list[PixelOption] = field(default_factory=list)
    empty: bool = False  # 這個條件底下沒有任何 pixel


class ReportState(SessionState):
    """報告輸出頁的狀態（SessionState 的子狀態）。"""

    loading: bool = False
    project_name: str = ""
    has_grouping: bool = False
    has_image: bool = False
    title: str = ""
    recipe: str = ""
    concentration: str = ""
    input_key: int = 0  # 非受控輸入框重新載入時遞增
    conditions: list[ConditionRow] = []

    @rx.var
    def included_count(self) -> int:
        """會放進報告的條件數。"""
        return sum(1 for c in self.conditions if c.selected)

    # ---------- 輸入 ----------
    @rx.event
    def set_title(self, value: str) -> None:
        """報告標題（空白則用專案名稱）。"""
        self.title = value

    @rx.event
    def set_recipe(self, value: str) -> None:
        """配方（化學式的數字在 PPT 中自動變成下標）。"""
        self.recipe = value

    @rx.event
    def set_concentration(self, value: str) -> None:
        """前驅液濃度。"""
        self.concentration = value

    @rx.event
    async def set_selection(self, condition: str, pixel: str):
        """選擇某個條件的代表 pixel（立即儲存）。"""
        self.conditions = [
            ConditionRow(c.name, pixel if c.name == condition else c.selected, c.options, c.empty)
            for c in self.conditions
        ]
        async for event in self._save(toast=False):
            yield event

    # ---------- API ----------
    def _base(self) -> str:
        """報告的 API 路徑（不含 /api）。"""
        return f"{api.project_path(self.user, self.project)}/report"

    def _apply(self, data: dict) -> None:
        """把 API 回傳的 ReportOut 填入狀態。"""
        settings = data["settings"]
        self.project_name = data["project_name"]
        self.has_grouping = bool(data["has_grouping"])
        self.has_image = bool(data["has_image"])
        self.title, self.recipe, self.concentration = settings["title"], settings["recipe"], settings["concentration"]
        self.input_key += 1
        rows = []
        for c in data["conditions"]:
            options = []
            for p in c["pixels"]:
                if p["dstar"] is None:
                    label = f"{p['pixel']}　（沒有 D*）"
                else:
                    label = f"{p['pixel']}　D* {p['dstar']:.2e}（{'實測' if p['measured'] else '理論極限'}）"
                options.append(PixelOption(p["pixel"], label))
            rows.append(ConditionRow(c["name"], c["selected"], options, not options))
        self.conditions = rows

    @rx.event
    async def load(self):
        """頁面載入：讀取報告設定與每個條件的 pixel。"""
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

    async def _save(self, toast: bool = True):
        """儲存封面資訊與代表 pixel。"""
        body = {
            "title": self.title.strip(), "recipe": self.recipe.strip(), "concentration": self.concentration.strip(),
            "selections": {c.name: c.selected for c in self.conditions},
        }
        try:
            data = await api.put_json(f"{self._base()}/settings", body)
        except ApiError as err:
            self._show_error(err)
            return
        self._apply(data)
        if toast:
            yield rx.toast.success("已儲存")

    @rx.event
    async def save(self):
        """「儲存」按鈕。"""
        async for event in self._save():
            yield event

    @rx.event
    async def upload_image(self, files: list[rx.UploadFile]):
        """上傳元件結構圖（png、jpg）。"""
        if not files:
            self._show_message("請先選擇圖片")
            return
        f = files[0]
        name, content = f.filename or f.name or "structure.png", await f.read()
        try:
            resp = await api.request(Method.POST, f"{self._base()}/image",
                                     files=[("file", (name, content, "application/octet-stream"))])
        except ApiError as err:
            self._show_error(err)
            return
        self._apply(resp.json())
        yield rx.clear_selected_files(IMAGE_UPLOAD_ID)
        yield rx.toast.success("元件結構圖已更新")

    @rx.event
    async def clear_image(self):
        """移除元件結構圖。"""
        try:
            data = await api.post_json(f"{self._base()}/image/clear", {})
        except ApiError as err:
            self._show_error(err)
            return
        self._apply(data)

    @rx.event
    async def download(self):
        """先儲存目前輸入，再下載 PD 報告（PowerPoint）。"""
        if self.included_count == 0:
            self._show_message("請至少為一個條件選擇代表 pixel")
            return
        self.loading = True
        yield
        async for event in self._save(toast=False):
            yield event
        try:
            name, content = await api.get_file(f"{self._base()}/pptx", PPTX_FALLBACK_NAME)
        except ApiError as err:
            self._show_error(err)
            return
        finally:
            self.loading = False
        yield rx.download(data=content, filename=name)

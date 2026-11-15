"""登入與專案的狀態（G-4）。

- SessionState：目前的使用者與專案；A、B 等各區的 State 都繼承它，所以能直接讀 self.user、self.project
- LoginState：登入畫面（下拉選單＋新增使用者），瀏覽器記住上次選的使用者
- ProjectsState：專案大廳（列出、排序、新增、開啟專案）與作業區總覽（修改條件）

流程：登入 → 專案大廳（每次都重新選專案）→ 作業區（總覽、a.～e.、g.）。
沒有密碼；每位使用者只看得到自己的專案。
"""
import re
from dataclasses import dataclass, field

import reflex as rx

from front import api_client as api
from front.api_client import ApiError
from front.enums import ProjectSort, Route, Section
from front.states.error_state import ErrorState

_DIGITS = re.compile(r"(\d+)")

LAST_USER_KEY = "lct_last_user"  # 瀏覽器 localStorage 的鍵
# 各區在介面上的字母（專案頁「已上傳」的方塊與清單）
SECTION_LETTERS = {Section.JV.value: "a.", Section.DARK.value: "b.", Section.EQE.value: "c."}
DEFAULT_COND_COUNT = 3  # 新增專案時預設的條件數量
MAX_COND_COUNT = 12


@dataclass
class ProjectGroup:
    """總覽分組的一個條件：條件名稱與樣品代號。"""

    name: str = ""
    samples: list[str] = field(default_factory=list)


class SessionState(ErrorState):
    """目前的使用者與專案（各區 State 的父狀態）。"""

    user: str = ""
    project: str = ""
    project_conditions: list[str] = []  # 專案統一的條件名稱
    project_grouping: list[ProjectGroup] = []  # 總覽分組（各區可「套用總覽的分組」）
    project_jobs: dict[str, str] = {}  # 功能（jv、dark…）→ 目前的工作編號

    @rx.var
    def logged_in(self) -> bool:
        """已登入。"""
        return self.user != ""

    @rx.var
    def has_project(self) -> bool:
        """已開啟專案。"""
        return self.project != ""

    def _set_project(self, data: dict) -> None:
        """把 API 回傳的專案內容（ProjectOut）填入狀態。"""
        self.project = data["name"]
        self.project_conditions = list(data["conditions"])
        # 舊版 API 沒有 grouping（尚未重新啟動時）
        self.project_grouping = [ProjectGroup(g["name"], list(g["samples"])) for g in data.get("grouping", [])]
        self.project_jobs = dict(data["jobs"])

    def _clear_project(self) -> None:
        """關閉專案。"""
        self.project = ""
        self.project_conditions = []
        self.project_grouping = []
        self.project_jobs = {}

    async def _refresh_project(self) -> dict | None:
        """重新向 API 取得目前專案（其他分頁可能已上傳或改條件）；失敗時顯示錯誤並回傳 None。"""
        try:
            data = await api.get_json(api.project_path(self.user, self.project))
        except ApiError as err:
            self._show_error(err)
            return None
        self._set_project(data)
        return data

    @rx.event
    def require_login(self):
        """頁面載入時：還沒登入就轉到登入頁。"""
        if not self.user:
            return rx.redirect(Route.LOGIN.value)

    @rx.event
    def require_project(self):
        """頁面載入時：還沒登入轉到登入頁，還沒開專案轉到專案大廳。"""
        if not self.user:
            return rx.redirect(Route.LOGIN.value)
        if not self.project:
            return rx.redirect(Route.PROJECTS.value)

    @rx.event
    def go_entry(self):
        """網站入口（/）：沒登入到登入頁，已登入到專案頁。"""
        return rx.redirect(Route.PROJECTS.value if self.user else Route.LOGIN.value)

    @rx.event
    def logout(self):
        """登出：清除使用者與專案，回到登入頁（各區的工作內容在下次開專案時重新載入）。"""
        self.user = ""
        self._clear_project()
        return rx.redirect(Route.LOGIN.value)


class LoginState(SessionState):
    """登入畫面：選使用者或新增。"""

    last_user: str = rx.LocalStorage("", name=LAST_USER_KEY)
    users: list[str] = []
    choice: str = ""
    new_user: str = ""
    loading: bool = False

    @rx.event
    def set_choice(self, value: str) -> None:
        """下拉選單。"""
        self.choice = value

    @rx.event
    def set_new_user(self, value: str) -> None:
        """新使用者名稱輸入框。"""
        self.new_user = value

    @rx.event
    async def load_users(self):
        """登入頁載入：取得使用者清單，預設選上次登入的人。"""
        self.loading = True
        yield
        try:
            self.users = await api.get_json("/users")
        except ApiError as err:
            self._show_error(err)
            return
        finally:
            self.loading = False
        if self.choice not in self.users:
            self.choice = self.last_user if self.last_user in self.users else next(iter(self.users), "")

    @rx.event
    def login(self):
        """以選定的使用者登入，前往專案頁。"""
        if not self.choice:
            self._show_message("請先選擇使用者，或新增一位")
            return
        if self.choice != self.user:
            self._clear_project()  # 換人登入時，不沿用上一位的專案
        self.user = self.choice
        self.last_user = self.choice
        return rx.redirect(Route.PROJECTS.value)

    @rx.event
    async def create_user(self):
        """新增使用者（名稱重複或含不允許的字元時由 API 回錯誤），新增後自動選取。"""
        name = self.new_user.strip()
        if not name:
            self._show_message("請輸入使用者名稱")
            return
        try:
            self.users = await api.post_json("/users", {"name": name})
        except ApiError as err:
            self._show_error(err)
            return
        self.choice = name
        self.new_user = ""


@dataclass
class ProjectRow:
    """專案清單的一列。"""

    name: str = ""
    created: str = ""
    updated: str = ""  # 最後修改時間（ISO 去掉 T，字串可直接比較先後）
    conditions: str = ""  # 以「、」串接
    sections: str = ""  # 已上傳資料的區（a. b.…）


def _natural_key(name: str) -> list:
    """名稱自然排序：數字依大小比較，英文不分大小寫。"""
    return [int(p) if p.isdigit() else p.lower() for p in _DIGITS.split(name)]


@dataclass
class ConditionRow:
    """條件編輯的一列：old 為原名稱（新增的列為空字串），new 為輸入框內容。

    uid：每列固定的編號，給輸入框當 key；上下移或刪除時，輸入框才會跟著正確的列（輸入框為非受控）。
    """

    old: str = ""
    new: str = ""
    uid: str = ""


@dataclass
class NameSlot:
    """新增專案時的一個條件名稱格。"""

    no: int = 1
    value: str = ""


class ProjectsState(SessionState):
    """專案大廳（列出、排序、新增、開啟專案）與作業區總覽（修改條件）；新增與修改都在對話框中。"""

    rows: list[ProjectRow] = []
    sort: str = ProjectSort.UPDATED.value
    loading: bool = False

    # 新增專案對話框：步驟 1 名稱與條件數量 → 步驟 2 N 個名稱格
    new_open: bool = False
    new_step: int = 1
    new_name: str = ""
    new_count: int = DEFAULT_COND_COUNT
    new_names: list[str] = [""] * DEFAULT_COND_COUNT

    # 修改條件對話框
    cond_open: bool = False
    cond_rows: list[ConditionRow] = []
    _next_uid: int = 0  # 新增條件列的編號（後端變數，不送到前端）

    # ---------- 計算屬性 ----------
    @rx.var
    def sorted_rows(self) -> list[ProjectRow]:
        """依目前排序方式排列：最新修改（新的在前）或名稱（由大到小：以日期開頭的名稱，新的在上）。"""
        if self.sort == ProjectSort.NAME.value:
            return sorted(self.rows, key=lambda r: _natural_key(r.name), reverse=True)
        return sorted(self.rows, key=lambda r: r.updated, reverse=True)

    @rx.var
    def name_slots(self) -> list[NameSlot]:
        """步驟 2 的 N 個名稱格。"""
        return [NameSlot(i + 1, v) for i, v in enumerate(self.new_names)]

    @rx.var
    def new_step_text(self) -> str:
        """對話框標題旁的步驟說明。"""
        return "1 / 2　名稱與條件數量" if self.new_step == 1 else "2 / 2　條件名稱"

    # ---------- 載入 ----------
    @rx.event
    def set_sort(self, value: str) -> None:
        """排序方式。"""
        self.sort = value

    @rx.event
    async def load_projects(self):
        """專案大廳載入：沒登入轉到登入頁；否則關閉目前專案（每次都重新選）並取得專案清單。"""
        if not self.user:
            yield rx.redirect(Route.LOGIN.value)
            return
        self._clear_project()
        yield ProjectsState.fetch_projects

    @rx.event
    async def fetch_projects(self):
        """取得專案清單。"""
        self.loading = True
        yield
        try:
            projects = await api.get_json(f"/users/{api.seg(self.user)}/projects")
        except ApiError as err:
            self._show_error(err)
            return
        finally:
            self.loading = False
        self.rows = [
            ProjectRow(
                name=p["name"],
                created=p["created"].replace("T", " "),
                # 舊版 API 沒有 updated（尚未重新啟動時），以建立時間代替
                updated=p.get("updated", p["created"]).replace("T", " "),
                conditions="、".join(p["conditions"]) or "（尚未設定）",
                sections=" ".join(SECTION_LETTERS.get(s, s) for s in p["jobs"]) or "—",
            )
            for p in projects
        ]

    @rx.event
    async def load_overview(self):
        """總覽頁載入：重新取得目前專案（條件與各區工作可能在其他分頁改過）。"""
        if self.user and self.project:
            await self._refresh_project()

    @rx.event
    async def open_project(self, name: str):
        """開啟專案，進入作業區總覽；各區頁面載入時會帶出已有的結果。"""
        try:
            data = await api.get_json(api.project_path(self.user, name))
        except ApiError as err:
            self._show_error(err)
            return
        self._set_project(data)
        yield rx.redirect(Route.OVERVIEW.value)

    # ---------- 新增專案對話框 ----------
    @rx.event
    def open_new(self) -> None:
        """開啟新增專案對話框（從步驟 1 開始）。"""
        self.new_open, self.new_step = True, 1

    @rx.event
    def close_new(self) -> None:
        """關閉新增專案對話框（已填的內容保留，下次開啟可繼續）。"""
        self.new_open = False

    @rx.event
    def set_new_name(self, value: str) -> None:
        """專案名稱。"""
        self.new_name = value

    def _resize_names(self, count: int) -> None:
        """條件數量改變：名稱格截短或補齊，已填的保留。"""
        self.new_count = count
        self.new_names = (self.new_names + [""] * count)[:count]

    @rx.event
    def dec_count(self) -> None:
        """條件數量減一（至少 1）。"""
        self._resize_names(max(1, self.new_count - 1))

    @rx.event
    def inc_count(self) -> None:
        """條件數量加一（最多 MAX_COND_COUNT）。"""
        self._resize_names(min(MAX_COND_COUNT, self.new_count + 1))

    @rx.event
    def to_names(self) -> None:
        """下一步：輸入條件名稱（專案名稱必填）。"""
        if not self.new_name.strip():
            self._show_message("請輸入專案名稱")
            return
        self.new_step = 2

    @rx.event
    def to_count(self) -> None:
        """上一步。"""
        self.new_step = 1

    @rx.event
    def set_new_slot(self, index: int, value: str) -> None:
        """第 index 格的條件名稱。"""
        names = list(self.new_names)
        names[index] = value
        self.new_names = names

    @rx.event
    async def create_project(self):
        """建立專案並開啟；名稱重複、條件名稱重複或含不允許的字元時由 API 回錯誤。"""
        names = [n.strip() for n in self.new_names]
        empty = [str(i + 1) for i, n in enumerate(names) if not n]
        if empty:
            self._show_message(f"第 {'、'.join(empty)} 個條件還沒填名稱")
            return
        body = {"name": self.new_name.strip(), "conditions": names}
        try:
            data = await api.post_json(f"/users/{api.seg(self.user)}/projects", body)
        except ApiError as err:
            self._show_error(err)
            return
        self._set_project(data)
        self.new_open, self.new_step, self.new_name = False, 1, ""
        self._resize_names(DEFAULT_COND_COUNT)
        self.new_names = [""] * DEFAULT_COND_COUNT
        yield rx.redirect(Route.OVERVIEW.value)

    # ---------- 修改條件對話框 ----------
    @rx.event
    def open_cond(self) -> None:
        """開啟修改條件對話框，載入目前專案的條件。"""
        self.cond_rows = [ConditionRow(c, c, self._uid()) for c in self.project_conditions]
        self.cond_open = True

    def _uid(self) -> str:
        """產生條件列的編號。"""
        self._next_uid += 1
        return f"c{self._next_uid}"

    @rx.event
    def close_cond(self) -> None:
        """關閉修改條件對話框（未儲存的修改捨棄）。"""
        self.cond_open = False

    @rx.event
    def set_cond_row(self, index: int, value: str) -> None:
        """修改第 index 列的名稱。"""
        rows = list(self.cond_rows)
        rows[index] = ConditionRow(rows[index].old, value, rows[index].uid)
        self.cond_rows = rows

    @rx.event
    def add_cond_row(self) -> None:
        """新增一列空白條件。"""
        self.cond_rows = [*self.cond_rows, ConditionRow("", "", self._uid())]

    @rx.event
    def remove_cond_row(self, index: int) -> None:
        """刪除第 index 列（按「儲存」才會生效）。"""
        self.cond_rows = [r for i, r in enumerate(self.cond_rows) if i != index]

    @rx.event
    def move_cond_row(self, index: int, step: int) -> None:
        """上下移動第 index 列（step 為 -1 或 1）。"""
        target = index + step
        if not 0 <= target < len(self.cond_rows):
            return
        rows = list(self.cond_rows)
        rows[index], rows[target] = rows[target], rows[index]
        self.cond_rows = rows

    @rx.event
    async def save_conditions(self):
        """儲存條件：改名會一併更新各區已確認的分組；被分組使用的條件不能刪（API 回錯誤）。"""
        edits = [{"old": r.old or None, "new": r.new} for r in self.cond_rows]
        try:
            data = await api.put_json(f"{api.project_path(self.user, self.project)}/conditions", {"conditions": edits})
        except ApiError as err:
            self._show_error(err)
            return
        self._set_project(data)
        self.cond_open = False
        yield rx.toast.success("條件已儲存")
        # 條件改名或新增後，總覽分組的條件選單與條件框跟著更新
        from front.states.overview_state import OverviewGroupState  # 避免循環匯入

        yield OverviewGroupState.load

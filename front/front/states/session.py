"""登入與專案的狀態（G-4）。

- SessionState：目前的使用者與專案；A、B 等各區的 State 都繼承它，所以能直接讀 self.user、self.project
- LoginState：登入畫面（下拉選單＋新增使用者），瀏覽器記住上次選的使用者
- ProjectsState：專案頁（列出、新增、開啟專案，修改目前專案的統一條件名稱）

沒有密碼；每位使用者只看得到自己的專案。
"""
from dataclasses import dataclass

import reflex as rx

from front import api_client as api
from front.api_client import ApiError
from front.enums import Route, Section
from front.states.error_state import ErrorState

LAST_USER_KEY = "lct_last_user"  # 瀏覽器 localStorage 的鍵
SECTION_LABELS = {Section.JV.value: "A JV", Section.DARK.value: "B 暗電流", Section.EQE.value: "C EQE"}


class SessionState(ErrorState):
    """目前的使用者與專案（各區 State 的父狀態）。"""

    user: str = ""
    project: str = ""
    project_conditions: list[str] = []  # 專案統一的條件名稱
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
        self.project_jobs = dict(data["jobs"])

    def _clear_project(self) -> None:
        """關閉專案。"""
        self.project = ""
        self.project_conditions = []
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
        """頁面載入時：還沒登入轉到登入頁，還沒開專案轉到專案頁。"""
        if not self.user:
            return rx.redirect(Route.LOGIN.value)
        if not self.project:
            return rx.redirect(Route.PROJECTS.value)

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
    conditions: str = ""  # 以「、」串接
    sections: str = ""  # 已上傳資料的區


@dataclass
class ConditionRow:
    """條件編輯的一列：old 為原名稱（新增的列為空字串），new 為輸入框內容。"""

    old: str = ""
    new: str = ""


def _split_lines(text: str) -> list[str]:
    """把多行文字拆成名稱清單（一行一個，略過空行）。"""
    return [line.strip() for line in text.splitlines() if line.strip()]


class ProjectsState(SessionState):
    """專案頁：列出、新增、開啟專案；修改目前專案的條件名稱。"""

    rows: list[ProjectRow] = []
    new_name: str = ""
    new_conditions: str = ""  # 一行一個條件
    cond_rows: list[ConditionRow] = []
    loading: bool = False

    @rx.event
    def set_new_name(self, value: str) -> None:
        """新專案名稱。"""
        self.new_name = value

    @rx.event
    def set_new_conditions(self, value: str) -> None:
        """新專案的條件（一行一個）。"""
        self.new_conditions = value

    def _load_cond_rows(self) -> None:
        """把目前專案的條件放進編輯列。"""
        self.cond_rows = [ConditionRow(c, c) for c in self.project_conditions]

    @rx.event
    async def load_projects(self):
        """專案頁載入：沒登入轉到登入頁；否則取得專案清單，並更新目前專案。"""
        if not self.user:
            yield rx.redirect(Route.LOGIN.value)
            return
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
                conditions="、".join(p["conditions"]) or "（尚未設定）",
                sections="、".join(SECTION_LABELS.get(s, s) for s in p["jobs"]) or "—",
            )
            for p in projects
        ]
        current = next((p for p in projects if p["name"] == self.project), None)
        if current:
            self._set_project(current)
        elif self.project:
            self._clear_project()  # 專案已不存在（例如在主機上被刪除）
        self._load_cond_rows()

    @rx.event
    async def create_project(self):
        """新增專案（名稱＋條件，一行一個），建立後直接開啟。"""
        name = self.new_name.strip()
        if not name:
            self._show_message("請輸入專案名稱")
            return
        body = {"name": name, "conditions": _split_lines(self.new_conditions)}
        try:
            data = await api.post_json(f"/users/{api.seg(self.user)}/projects", body)
        except ApiError as err:
            self._show_error(err)
            return
        self.new_name = self.new_conditions = ""
        self._set_project(data)
        self._load_cond_rows()
        yield ProjectsState.load_projects

    @rx.event
    async def open_project(self, name: str):
        """開啟專案，回到首頁；各區頁面載入時會帶出已有的結果。"""
        try:
            data = await api.get_json(api.project_path(self.user, name))
        except ApiError as err:
            self._show_error(err)
            return
        self._set_project(data)
        self._load_cond_rows()
        yield rx.redirect(Route.HOME.value)

    # ---------- 修改條件 ----------
    @rx.event
    def set_cond_row(self, index: int, value: str) -> None:
        """修改第 index 列的名稱。"""
        rows = list(self.cond_rows)
        rows[index] = ConditionRow(rows[index].old, value)
        self.cond_rows = rows

    @rx.event
    def add_cond_row(self) -> None:
        """新增一列空白條件。"""
        self.cond_rows = [*self.cond_rows, ConditionRow("", "")]

    @rx.event
    def remove_cond_row(self, index: int) -> None:
        """刪除第 index 列（按「儲存條件」才會生效）。"""
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
    def reset_cond_rows(self) -> None:
        """放棄修改，回到已儲存的條件。"""
        self._load_cond_rows()

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
        self._load_cond_rows()
        yield rx.toast.success("條件已儲存")
        yield ProjectsState.load_projects

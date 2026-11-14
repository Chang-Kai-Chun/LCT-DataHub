"""G-4 使用者與專案：登入（選使用者／新增）、列出與建立專案、修改專案的統一條件名稱。

使用者與專案名稱即資料夾名稱，放在網址中（前端需做 URL 編碼）。
路由為 async def，讀寫資料夾以 asyncio.to_thread() 交給執行緒。
"""
import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lct_datahub.api.common import get_store
from lct_datahub.api.jobs import JobStore
from lct_datahub.api.projects import ConditionEdit, Project

router = APIRouter(prefix="/api/users", tags=["G 使用者與專案"])


# ---------- 資料模型 ----------
class UserIn(BaseModel):
    """新增使用者。"""

    name: str


class ProjectIn(BaseModel):
    """新增專案：名稱與統一的條件名稱（可之後再加）。"""

    name: str
    conditions: list[str] = []


class ConditionsEditIn(BaseModel):
    """修改條件清單：依順序列出全部條件；改名時 old 填原名稱，新增時 old 為 null，沒列出的視為刪除。"""

    conditions: list[ConditionEdit]


class ProjectOut(BaseModel):
    """專案內容：各區目前的工作編號（功能 → 工作編號；沒有上傳過的區不會出現）。"""

    name: str
    created: str
    conditions: list[str]
    jobs: dict[str, str]

    @classmethod
    def from_project(cls, project: Project) -> "ProjectOut":
        """由 Project 轉換。"""
        info = project.info
        return cls(name=info.name, created=info.created, conditions=info.conditions, jobs=info.jobs)


# ---------- 路由：使用者 ----------
@router.get("", response_model=list[str])
async def list_users(store: JobStore = Depends(get_store)) -> list[str]:
    """所有使用者（依名稱排序），給登入畫面的下拉選單。"""
    return await asyncio.to_thread(store.workspace.list_users)


@router.post("", response_model=list[str])
async def create_user(body: UserIn, store: JobStore = Depends(get_store)) -> list[str]:
    """新增使用者，回傳新的使用者清單；名稱重複或含不允許的字元回 400。"""

    def _run() -> list[str]:
        """新增後重新列出。"""
        store.workspace.create_user(body.name)
        return store.workspace.list_users()

    return await asyncio.to_thread(_run)


# ---------- 路由：專案 ----------
@router.get("/{user}/projects", response_model=list[ProjectOut])
async def list_projects(user: str, store: JobStore = Depends(get_store)) -> list[ProjectOut]:
    """使用者的所有專案（新的在前）；找不到使用者回 404。"""
    projects = await asyncio.to_thread(store.workspace.list_projects, user)
    return [ProjectOut.from_project(p) for p in projects]


@router.post("/{user}/projects", response_model=ProjectOut)
async def create_project(user: str, body: ProjectIn, store: JobStore = Depends(get_store)) -> ProjectOut:
    """新增專案；名稱重複、條件名稱重複或含不允許的字元回 400。"""
    project = await asyncio.to_thread(store.workspace.create_project, user, body.name, body.conditions)
    return ProjectOut.from_project(project)


@router.get("/{user}/projects/{project}", response_model=ProjectOut)
async def get_project(user: str, project: str, store: JobStore = Depends(get_store)) -> ProjectOut:
    """專案內容（開啟專案時用來帶出各區已有的工作）。"""
    return ProjectOut.from_project(await asyncio.to_thread(store.workspace.get_project, user, project))


@router.put("/{user}/projects/{project}/conditions", response_model=ProjectOut)
async def edit_conditions(
    user: str, project: str, body: ConditionsEditIn, store: JobStore = Depends(get_store),
) -> ProjectOut:
    """修改專案的條件清單：改名會一併更新各區已確認的分組；刪除已被分組使用的條件回 400。"""
    result = await asyncio.to_thread(store.workspace.edit_conditions, user, project, body.conditions)
    return ProjectOut.from_project(result)

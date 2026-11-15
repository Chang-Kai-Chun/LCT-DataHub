"""G-4 使用者與專案：登入（選使用者／新增）、列出與建立專案、修改專案的統一條件名稱。

使用者與專案名稱即資料夾名稱，放在網址中（前端需做 URL 編碼）。
路由為 async def，讀寫資料夾以 asyncio.to_thread() 交給執行緒。
"""
import asyncio

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from lct_datahub.api.common import get_store
from lct_datahub.api.grouping import GroupingIn, GroupingOut, preview_grouping
from lct_datahub.api.jobs import JobStore, Section
from lct_datahub.api.projects import ConditionEdit, Project, ProjectGroup
from lct_datahub.api.routes import dark, eqe, jv
from lct_datahub.core.sample_id import parse_sample_id

# 各區取得工作樣品的函式（專案總覽分組的樣品清單＝各區樣品的聯集）
SECTION_SAMPLES = {Section.JV: jv.job_samples, Section.DARK: dark.job_samples, Section.EQE: eqe.job_samples}

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


class GroupingEntryIn(BaseModel):
    """總覽分組的一列：條件名稱＋樣品（範圍字串如 'G1-G4, G7'，或樣品代號清單；空白表示這個條件沒有樣品）。"""

    name: str
    samples: str | list[str] = ""

    def text(self) -> str:
        """樣品轉成範圍字串（清單以逗號串接）。"""
        return self.samples if isinstance(self.samples, str) else ", ".join(self.samples)


class GroupingPreviewIn(GroupingIn):
    """總覽分組預填：分組方式（同各區）＋要分組的樣品（前端送出：各區樣品＋手動加入）。"""

    samples: list[str]


class ProjectGroupingIn(BaseModel):
    """設定總覽分組（整份取代）。"""

    conditions: list[GroupingEntryIn]


class ProjectOut(BaseModel):
    """專案內容：各區目前的工作編號（功能 → 工作編號；沒有上傳過的區不會出現）。"""

    name: str
    created: str
    updated: str  # 最後修改時間（上傳、改設定、分組、改條件），給專案大廳排序
    conditions: list[str]
    grouping: list[ProjectGroup]  # 總覽分組（各區可直接套用）
    jobs: dict[str, str]

    @classmethod
    def from_project(cls, project: Project) -> "ProjectOut":
        """由 Project 轉換。"""
        info = project.info
        return cls(
            name=info.name, created=info.created, updated=project.last_modified(),
            conditions=info.conditions, grouping=info.grouping, jobs=info.jobs,
        )


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


@router.put("/{user}/projects/{project}/grouping", response_model=ProjectOut)
async def set_grouping(
    user: str, project: str, body: ProjectGroupingIn, store: JobStore = Depends(get_store),
) -> ProjectOut:
    """設定總覽分組（各區可「套用總覽的分組」再微調）；條件不在專案中、樣品重複歸組或代號格式錯誤回 400。"""
    entries = [(e.name, e.text()) for e in body.conditions]
    result = await asyncio.to_thread(store.workspace.set_grouping, user, project, entries)
    return ProjectOut.from_project(result)


def _project_samples(store: JobStore, user: str, name: str) -> list[str]:
    """專案各區目前工作的樣品聯集，依代號排序。"""
    project = store.workspace.get_project(user, name)
    found: set[str] = set()
    for section, func in SECTION_SAMPLES.items():
        job_id = project.info.jobs.get(section.value)
        if job_id:
            found.update(func(store, store.get(section, job_id)))
    return [str(s) for s in sorted(parse_sample_id(x) for x in found)]


@router.get("/{user}/projects/{project}/samples", response_model=list[str])
async def project_samples(user: str, project: str, store: JobStore = Depends(get_store)) -> list[str]:
    """專案各區已上傳的樣品（聯集），給總覽分組。"""
    return await asyncio.to_thread(_project_samples, store, user, project)


@router.post("/{user}/projects/{project}/grouping/preview", response_model=GroupingOut)
async def preview_project_grouping(
    user: str, project: str, body: GroupingPreviewIn, store: JobStore = Depends(get_store),
) -> GroupingOut:
    """總覽分組預填（平均分配／自訂／自動，同各區；不存檔）；樣品由前端送出。"""

    def _run() -> GroupingOut:
        """依專案條件預填。"""
        conditions = store.workspace.get_project(user, project).info.conditions
        samples = sorted({parse_sample_id(s) for s in body.samples})
        return preview_grouping(samples, body, conditions)

    return await asyncio.to_thread(_run)
"""G-4 使用者與專案：每位使用者一個資料夾，裡面是自己的專案；各區的工作掛在專案底下。

資料夾結構：<data_root>/users/<使用者>/
  user.json                     建立時間
  projects/<專案>/
    project.json                專案名稱、建立時間、統一的條件名稱、各區目前的工作編號
    <功能>/<工作編號>/           各區的工作（見 jobs.py）

- 使用者清單直接掃 users/ 底下的資料夾，不另存名單；在主機上刪掉資料夾即移除使用者
- 登入沒有密碼（實驗室區網內使用）；每位使用者只看得到自己的專案
- 條件名稱由專案統一定義，各區分組時只能選用這些名稱，E 區才能以名稱對應
"""
import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

from lct_datahub.core.jv.types import GroupingError
from lct_datahub.core.sample_id import expand_samples

USERS_DIR = "users"
PROJECTS_DIR = "projects"
USER_FILE = "user.json"
PROJECT_FILE = "project.json"
SETTINGS_FILE = "settings.json"  # 與 jobs.FileName.SETTINGS 相同（避免循環 import，在此另寫）

SECTION_LABELS = {"jv": "A JV", "dark": "B 暗電流", "eqe": "C EQE"}  # 錯誤訊息中顯示的區名
NAME_MAX_LENGTH = 50
_FORBIDDEN = re.compile(r'[\\/:*?"<>|\x00-\x1f]')  # Windows 資料夾名稱不允許的字元
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class WorkspaceNotFoundError(LookupError):
    """找不到使用者或專案時拋出（API 回 404）。"""


class InvalidNameError(ValueError):
    """名稱不合規則或重複時拋出（API 回 400）。"""


def check_name(name: str, label: str) -> str:
    """檢查使用者、專案或條件名稱，回傳去掉前後空白的名稱；不合規則拋出 InvalidNameError。"""
    name = (name or "").strip()
    if not name:
        raise InvalidNameError(f"{label}名稱不可空白")
    if len(name) > NAME_MAX_LENGTH:
        raise InvalidNameError(f"{label}名稱最多 {NAME_MAX_LENGTH} 個字")
    if _FORBIDDEN.search(name):
        raise InvalidNameError(f'{label}名稱不可包含 \\ / : * ? " < > |')
    if name.endswith(".") or name in {".", ".."} or name.upper() in _RESERVED:
        raise InvalidNameError(f"{label}名稱「{name}」無法當作資料夾名稱")
    return name


def check_condition_names(names: list[str]) -> list[str]:
    """檢查條件名稱清單：每個名稱合規則、不可重複（不分大小寫）。"""
    cleaned = [check_name(n, "條件") for n in names]
    lowered = [n.lower() for n in cleaned]
    duplicated = sorted({n for n in cleaned if lowered.count(n.lower()) > 1})
    if duplicated:
        raise InvalidNameError(f"條件名稱重複：{'、'.join(duplicated)}")
    return cleaned


# ---------- 資料模型（存在 json） ----------
class ProjectGroup(BaseModel):
    """總覽分組的一個條件：條件名稱＋樣品代號（正規化後，例如 G1）。"""

    name: str
    samples: list[str]


class ProjectInfo(BaseModel):
    """project.json 的內容。"""

    name: str
    created: str
    conditions: list[str] = []  # 統一的條件名稱（依順序）
    grouping: list[ProjectGroup] = []  # 總覽分組（2026-11-15）：各區可直接套用，再微調確定
    jobs: dict[str, str] = {}  # 功能（jv、dark、eqe）→ 目前的工作編號


class ConditionEdit(BaseModel):
    """修改條件清單的一列：old 為原名稱（新增時為 null），new 為新名稱。"""

    old: str | None = None
    new: str


@dataclass(frozen=True)
class Project:
    """一個專案（資料夾＋內容）。"""

    user: str
    folder: Path
    info: ProjectInfo

    @property
    def name(self) -> str:
        """專案名稱（＝資料夾名稱）。"""
        return self.info.name

    def last_modified(self) -> str:
        """最後修改時間（ISO，到秒）：project.json 與各區目前工作的 meta.json、settings.json 中最新的一個。

        上傳、改設定、分組、改條件都會更新其中一個檔案，因此不另外記錄。
        """
        paths = [self.folder / PROJECT_FILE]
        for section, job_id in self.info.jobs.items():
            job_dir = self.folder / section / job_id
            paths += [job_dir / "meta.json", job_dir / SETTINGS_FILE]
        latest = max(p.stat().st_mtime for p in paths if p.is_file())
        return datetime.fromtimestamp(latest).isoformat(timespec="seconds")


class Workspace:
    """使用者與專案的建立、列出與讀寫。"""

    def __init__(self, data_root: Path):
        """data_root 為資料根目錄（底下的 users/ 不存在會自動建立）。"""
        self.users_dir = Path(data_root) / USERS_DIR
        self._lock = threading.Lock()  # 寫 project.json、settings.json 時避免互相覆蓋

    # ---------- 使用者 ----------
    def list_users(self) -> list[str]:
        """所有使用者（掃 users/ 底下的資料夾），依名稱排序。"""
        if not self.users_dir.is_dir():
            return []
        return sorted((p.name for p in self.users_dir.iterdir() if p.is_dir()), key=str.lower)

    def create_user(self, name: str) -> str:
        """新增使用者；名稱重複（不分大小寫）拋出 InvalidNameError。"""
        name = check_name(name, "使用者")
        if name.lower() in {u.lower() for u in self.list_users()}:
            raise InvalidNameError(f"使用者「{name}」已存在")
        folder = self.users_dir / name
        (folder / PROJECTS_DIR).mkdir(parents=True)
        _write_json(folder / USER_FILE, {"name": name, "created": _now()})
        return name

    def _user_dir(self, user: str) -> Path:
        """使用者資料夾；名稱不合規則或不存在拋出 WorkspaceNotFoundError。"""
        try:
            user = check_name(user, "使用者")
        except InvalidNameError:
            raise WorkspaceNotFoundError(f"找不到使用者：{user}") from None
        folder = self.users_dir / user
        if not folder.is_dir():
            raise WorkspaceNotFoundError(f"找不到使用者：{user}")
        return folder

    # ---------- 專案 ----------
    def list_projects(self, user: str) -> list[Project]:
        """使用者的所有專案，新建立的在前面。"""
        root = self._user_dir(user) / PROJECTS_DIR
        if not root.is_dir():
            return []
        projects = [self._load(user, p) for p in root.iterdir() if (p / PROJECT_FILE).is_file()]
        return sorted(projects, key=lambda p: p.info.created, reverse=True)

    def create_project(self, user: str, name: str, conditions: list[str] | None = None) -> Project:
        """新增專案（可同時給條件名稱）；名稱重複（不分大小寫）拋出 InvalidNameError。"""
        root = self._user_dir(user) / PROJECTS_DIR
        name = check_name(name, "專案")
        cleaned = check_condition_names(conditions or [])
        if root.is_dir() and name.lower() in {p.name.lower() for p in root.iterdir()}:
            raise InvalidNameError(f"專案「{name}」已存在")
        folder = root / name
        folder.mkdir(parents=True)
        info = ProjectInfo(name=name, created=_now(), conditions=cleaned)
        _write_json(folder / PROJECT_FILE, info.model_dump())
        return Project(user, folder, info)

    def get_project(self, user: str, name: str) -> Project:
        """取得專案；不存在拋出 WorkspaceNotFoundError。"""
        root = self._user_dir(user) / PROJECTS_DIR
        try:
            name = check_name(name, "專案")
        except InvalidNameError:
            raise WorkspaceNotFoundError(f"找不到專案：{name}") from None
        folder = root / name
        if not (folder / PROJECT_FILE).is_file():
            raise WorkspaceNotFoundError(f"找不到專案：{name}")
        return self._load(user, folder)

    def project_of(self, job_folder: Path) -> Project:
        """由工作資料夾（<專案>/<功能>/<工作編號>）找出所屬專案。"""
        folder = job_folder.parent.parent
        return self._load(folder.parent.parent.name, folder)

    def set_job(self, project: Project, section: str, job_id: str) -> Project:
        """記錄專案在某一區目前的工作（重新上傳時取代；舊的工作資料夾保留）。"""
        with self._lock:
            info = self._load(project.user, project.folder).info
            info.jobs[section] = job_id
            _write_json(project.folder / PROJECT_FILE, info.model_dump())
        return Project(project.user, project.folder, info)

    def edit_conditions(self, user: str, name: str, edits: list[ConditionEdit]) -> Project:
        """修改專案的條件清單（依 edits 的順序）。

        - 改名：各區已確認的分組一起改名
        - 刪除：若有任何一區的已確認分組用到這個條件，拋出 GroupingError，不做任何修改
        """
        project = self.get_project(user, name)
        new_names = check_condition_names([e.new for e in edits])
        old_names = project.info.conditions
        unknown = [e.old for e in edits if e.old is not None and e.old not in old_names]
        if unknown:
            raise InvalidNameError(f"專案中沒有這些條件：{'、'.join(unknown)}")
        renames = {e.old: n for e, n in zip(edits, new_names) if e.old is not None and e.old != n}
        kept = {e.old for e in edits if e.old is not None}
        removed = [c for c in old_names if c not in kept]

        with self._lock:
            settings_files = self._settings_files(project)
            if removed:
                used = self._sections_using(settings_files, set(removed))
                for group in project.info.grouping:  # 總覽分組也算使用中
                    if group.name in removed:
                        used.setdefault(group.name, []).append("總覽")
                if used:
                    detail = "；".join(f"{c}（{'、'.join(s)}）" for c, s in used.items())
                    raise GroupingError(f"以下條件已用在分組中，請先修改該處的分組再刪除：{detail}")
            for path in settings_files:
                _rename_in_settings(path, renames)
            grouping = [ProjectGroup(name=renames.get(g.name, g.name), samples=g.samples) for g in project.info.grouping]
            info = project.info.model_copy(update={"conditions": new_names, "grouping": grouping})
            _write_json(project.folder / PROJECT_FILE, info.model_dump())
        return Project(project.user, project.folder, info)

    def set_grouping(self, user: str, name: str, entries: list[tuple[str, str]]) -> Project:
        """設定總覽分組：entries 為 (條件名稱, 樣品範圍字串，例如 'G1-G4, G7')；樣品空白的條件略過。

        條件須在專案條件中、不可重複；同一樣品不可屬於兩個條件；樣品代號格式錯誤拋出 InvalidSampleIdError。
        """
        project = self.get_project(user, name)
        allowed = project.info.conditions
        groups: list[ProjectGroup] = []
        owner: dict[str, str] = {}  # 樣品 → 已屬於的條件
        for cond, text in entries:
            if cond not in allowed:
                raise GroupingError(f"條件「{cond}」不在專案的條件清單中（{'、'.join(allowed)}）")
            if any(g.name == cond for g in groups):
                raise GroupingError(f"條件「{cond}」重複")
            samples = [str(s) for s in expand_samples(text)] if text.strip() else []  # 空白＝這個條件沒有樣品
            for s in samples:
                if s in owner:
                    raise GroupingError(f"{s} 同時屬於「{owner[s]}」與「{cond}」")
                owner[s] = cond
            if samples:
                groups.append(ProjectGroup(name=cond, samples=samples))
        with self._lock:
            info = self._load(project.user, project.folder).info.model_copy(update={"grouping": groups})
            _write_json(project.folder / PROJECT_FILE, info.model_dump())
        return Project(project.user, project.folder, info)

    # ---------- 內部 ----------
    def _load(self, user: str, folder: Path) -> Project:
        """讀 project.json。"""
        info = ProjectInfo.model_validate_json((folder / PROJECT_FILE).read_text(encoding="utf-8"))
        return Project(user, folder, info)

    @staticmethod
    def _settings_files(project: Project) -> list[Path]:
        """專案內各區「目前工作」的 settings.json（存在的才列出）。"""
        paths = [project.folder / section / job_id / SETTINGS_FILE for section, job_id in project.info.jobs.items()]
        return [p for p in paths if p.is_file()]

    @staticmethod
    def _sections_using(paths: list[Path], names: set[str]) -> dict[str, list[str]]:
        """哪些條件被哪些區的已確認分組使用：條件 → [功能]。"""
        used: dict[str, list[str]] = {}
        for path in paths:
            data = json.loads(path.read_text(encoding="utf-8"))
            for cond in data.get("conditions") or []:
                if cond.get("name") in names:
                    section = path.parent.parent.name
                    used.setdefault(cond["name"], []).append(SECTION_LABELS.get(section, section))
        return used


def _rename_in_settings(path: Path, renames: dict[str, str]) -> None:
    """把 settings.json 中已確認分組的條件改名（沒有用到就不寫檔）。"""
    if not renames:
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    conditions = data.get("conditions") or []
    if not any(c.get("name") in renames for c in conditions):
        return
    for cond in conditions:
        cond["name"] = renames.get(cond["name"], cond["name"])
    _write_json(path, data)


def _write_json(path: Path, data: dict) -> None:
    """寫 json（先寫暫存檔再取代，避免寫到一半被讀到）。"""
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _now() -> str:
    """目前時間（ISO 格式，到秒）。"""
    return datetime.now().isoformat(timespec="seconds")

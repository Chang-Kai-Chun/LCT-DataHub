"""G-2 工作資料夾：每次上傳建立一個工作（job），原始檔、輸出與設定都放在自己的資料夾。

資料夾結構：<work_root>/<功能>/<工作編號>/
  raw/            上傳的原始檔
  output/         Excel、zip 等輸出
  meta.json       上傳順序（檔名清單）
  settings.json   使用者設定（面積、分組、改名…），各功能自行定義內容

每個請求都從 raw/ 重新讀檔再套用 settings.json，因此不依賴記憶體狀態，服務重啟也不會遺失。
"""
import json
import re
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel


class Section(Enum):
    """API 的功能區；value 同時是網址與資料夾名稱。"""

    JV = "jv"  # A
    DARK = "dark"  # B
    EQE = "eqe"  # C


# 各功能接受的副檔名（其他檔案上傳時略過，並在回應中列出）
ALLOWED_SUFFIXES = {
    Section.JV: frozenset({".csv"}),
    Section.DARK: frozenset({".txt", ".csv", ".dat", ".xlsx", ".xls"}),
    Section.EQE: frozenset({".txt", ".xls", ".xlsx"}),
}

# 工作編號：日期時間＋8 碼亂數，例如 20261106-153000-1a2b3c4d；同時用來防止路徑穿越
_JOB_ID = re.compile(r"^\d{8}-\d{6}-[0-9a-f]{8}$")


class FileName:
    """工作資料夾內的固定檔名。"""

    RAW = "raw"
    OUTPUT = "output"
    META = "meta.json"
    SETTINGS = "settings.json"


class JobNotFoundError(LookupError):
    """工作編號格式不符或資料夾不存在時拋出。"""


class UploadError(ValueError):
    """上傳內容不合理（沒有可處理的檔案、檔名重複）時拋出。"""


@dataclass(frozen=True)
class UploadResult:
    """建立工作的結果。"""

    job: "Job"
    skipped: list[str]  # 副檔名不接受而略過的檔案


@dataclass(frozen=True)
class Job:
    """一個工作（一次上傳）。"""

    id: str
    section: Section
    folder: Path

    @property
    def raw_dir(self) -> Path:
        """原始檔資料夾。"""
        return self.folder / FileName.RAW

    @property
    def output_dir(self) -> Path:
        """輸出資料夾（不存在就建立）。"""
        path = self.folder / FileName.OUTPUT
        path.mkdir(exist_ok=True)
        return path

    def raw_files(self) -> list[Path]:
        """原始檔路徑，依上傳順序。"""
        meta = json.loads((self.folder / FileName.META).read_text(encoding="utf-8"))
        return [self.raw_dir / name for name in meta["files"]]


class JobStore:
    """建立、取得工作，以及讀寫工作設定。"""

    def __init__(self, root: Path):
        """root 為工作資料夾根目錄（不存在會自動建立）。"""
        self.root = Path(root)
        self._lock = threading.Lock()  # 同一個服務內寫 settings.json 時避免互相覆蓋

    def create(self, section: Section, files: list[tuple[str, bytes]]) -> UploadResult:
        """以上傳的 (檔名, 內容) 建立工作；只保留該功能接受的副檔名。

        檔名只取最後一段（去掉路徑）；沒有可處理的檔案或檔名重複時拋出 UploadError。
        """
        allowed = ALLOWED_SUFFIXES[section]
        kept, skipped = [], []
        for raw_name, content in files:
            name = Path(raw_name.replace("\\", "/")).name  # 防止 ../ 之類的路徑
            (kept if Path(name).suffix.lower() in allowed and name else skipped).append((name, content))
        if not kept:
            raise UploadError(f"沒有可處理的檔案（接受：{'、'.join(sorted(allowed))}）")
        names = [n for n, _ in kept]
        duplicated = sorted({n for n in names if names.count(n) > 1})
        if duplicated:
            raise UploadError(f"檔案重複：{'、'.join(duplicated)}")

        job_id = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}"
        job = Job(job_id, section, self.root / section.value / job_id)
        job.raw_dir.mkdir(parents=True)
        for name, content in kept:
            (job.raw_dir / name).write_bytes(content)
        (job.folder / FileName.META).write_text(json.dumps({"files": names}, ensure_ascii=False), encoding="utf-8")
        return UploadResult(job, [n for n, _ in skipped])

    def get(self, section: Section, job_id: str) -> Job:
        """取得既有工作；編號格式不符或不存在時拋出 JobNotFoundError。"""
        if not _JOB_ID.match(job_id):
            raise JobNotFoundError(f"找不到工作：{job_id}")
        folder = self.root / section.value / job_id
        if not (folder / FileName.META).is_file():
            raise JobNotFoundError(f"找不到工作：{job_id}")
        return Job(job_id, section, folder)

    def load_settings[T: BaseModel](self, job: Job, model: type[T]) -> T:
        """讀取工作設定；還沒存過就回傳 model 的預設值。"""
        path = job.folder / FileName.SETTINGS
        if not path.is_file():
            return model()
        return model.model_validate_json(path.read_text(encoding="utf-8"))

    def save_settings(self, job: Job, settings: BaseModel) -> None:
        """寫入工作設定（先寫暫存檔再取代，避免寫到一半被讀到）。"""
        path = job.folder / FileName.SETTINGS
        with self._lock:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(settings.model_dump_json(indent=2), encoding="utf-8")
            tmp.replace(path)

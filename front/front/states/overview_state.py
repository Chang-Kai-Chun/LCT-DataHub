"""總覽分組的狀態：與 A、B、C 區相同的分組畫面（GroupingMixin），預設用格子分，「使用者自訂」才手動輸入範圍。

- 樣品清單：各區已上傳的樣品聯集（API）＋已存的總覽分組中的樣品＋手動加入的樣品
- 預填：POST /users/{u}/projects/{p}/grouping/preview（樣品由這裡送出）
- 確定：PUT /users/{u}/projects/{p}/grouping（存成總覽分組，各區可「套用總覽的分組」）
"""
import re

import reflex as rx

from front import api_client as api
from front.api_client import ApiError
from front.states.grouping import GroupingMixin
from front.states.session import SessionState

# 手動加入樣品：G1、G1-G16、G1-16（逗號分隔，半形或全形）
_SAMPLE_RANGE = re.compile(r"^([A-Za-z]{1,3})(\d+)(?:\s*-\s*(?:[A-Za-z]{1,3})?(\d+))?$")
_SPLIT = re.compile(r"[,，、\s]+")
MAX_RANGE = 200  # 一個範圍最多展開的樣品數


def expand_text(text: str) -> list[str]:
    """把「G1-G4, G7」展開成正規化的樣品代號（大寫、去前導零）；格式錯誤拋出 ValueError。"""
    result: list[str] = []
    for part in _SPLIT.split(text.strip()):
        if not part:
            continue
        match = _SAMPLE_RANGE.match(part.replace(" ", ""))
        if not match:
            raise ValueError(f"樣品代號格式不符：{part}（例如 G1、G1-G16）")
        prefix, start = match.group(1).upper(), int(match.group(2))
        end = int(match.group(3)) if match.group(3) else start
        if end < start or end - start >= MAX_RANGE:
            raise ValueError(f"範圍不合理：{part}")
        result += [f"{prefix}{n}" for n in range(start, end + 1) if f"{prefix}{n}" not in result]
    return result


def _sample_key(sample: str) -> tuple[str, int]:
    """樣品排序：字母、數字大小。"""
    match = re.match(r"^([A-Z]+)(\d+)$", sample)
    return (match.group(1), int(match.group(2))) if match else (sample, 0)


class OverviewGroupState(GroupingMixin, SessionState):
    """總覽分組（SessionState 的子狀態）。"""

    section_samples: list[str] = []  # 各區已上傳的樣品
    extra_samples: list[str] = []  # 手動加入的樣品
    extra_text: str = ""
    extra_key: int = 0

    # ---------- GroupingMixin 的掛鉤 ----------
    def _project_api(self) -> str:
        """專案的 API 路徑。"""
        return api.project_path(self.user, self.project)

    def _preview_path(self) -> str:
        """預填分組的 API。"""
        return f"{self._project_api()}/grouping/preview"

    def _confirm_path(self) -> str:
        """確定分組＝存成總覽分組。"""
        return f"{self._project_api()}/grouping"

    def _preview_extra(self) -> dict:
        """預填時送出樣品清單（總覽沒有檔案，樣品由這裡提供）。"""
        return {"samples": self.samples}

    def _handle_error(self, err: ApiError) -> None:
        """顯示錯誤。"""
        self._show_error(err)

    def _apply_job(self, data: dict) -> None:
        """確定後 API 回傳專案內容（ProjectOut）：更新專案與分組。"""
        self._set_project(data)
        self._refresh_samples()
        self._load_conditions(data.get("grouping") or None)

    # ---------- 樣品 ----------
    def _refresh_samples(self) -> None:
        """樣品＝各區樣品＋總覽分組中的樣品＋手動加入，依代號排序。"""
        saved = {s for g in self.project_grouping for s in g.samples}
        self.samples = sorted(set(self.section_samples) | saved | set(self.extra_samples), key=_sample_key)

    @rx.event
    async def load(self):
        """總覽頁載入：取得各區樣品，載入專案條件與已存的總覽分組。"""
        if not self.user or not self.project:
            return
        try:
            self.section_samples = await api.get_json(f"{self._project_api()}/samples")
        except ApiError as err:
            self._show_error(err)
            return
        self._refresh_samples()
        self._load_choices(self.project_conditions)
        self._load_conditions([{"name": g.name, "samples": g.samples} for g in self.project_grouping] or None)

    @rx.event
    def set_extra_text(self, value: str) -> None:
        """手動加入樣品的輸入框。"""
        self.extra_text = value

    @rx.event
    def add_extra(self) -> None:
        """手動加入樣品（例如還沒上傳任何區時，先用 G1-G16 建立分組）；新樣品放在未分配。"""
        try:
            added = [s for s in expand_text(self.extra_text) if s not in self.samples]
        except ValueError as exc:
            self._show_message(str(exc))
            return
        if not added:
            self._show_message("沒有新的樣品可加入")
            return
        self.extra_samples = [*self.extra_samples, *added]
        self._refresh_samples()
        if self.conditions:
            self.unassigned = self._sorted([*self.unassigned, *added])
            self._unconfirm()
        self.extra_text = ""
        self.extra_key += 1

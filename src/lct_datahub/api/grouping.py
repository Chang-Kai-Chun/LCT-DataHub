"""各功能共用的分組 API 模型與流程（A JV 依樣品、B 暗電流依元件）。

分組邏輯都在 core/jv/grouping.py：預填（平均分配、自訂、自動）→ 前端微調 → 確認（須全部分配）。
條件名稱只能用專案統一定義的名稱（G-4）；自動分組依序取專案的條件名稱（不再是 Group 1、Group 2…）。
這裡只負責 API 資料模型與 core 之間的轉換。
"""
from pydantic import BaseModel

from lct_datahub.core.jv.grouping import group_auto, group_custom, group_even, require_complete, to_grouping
from lct_datahub.core.jv.types import Condition, GroupingError, GroupMode
from lct_datahub.core.sample_id import SampleId, parse_sample_id


class ConditionModel(BaseModel):
    """一個條件：名稱＋樣品代號（正規化後的字串，例如 G1）。"""

    name: str
    samples: list[str]

    @classmethod
    def from_core(cls, cond: Condition) -> "ConditionModel":
        """由 core 的 Condition 轉換。"""
        return cls(name=cond.name, samples=[str(s) for s in cond.samples])


class CustomEntry(BaseModel):
    """使用者自訂分組的一列：條件名稱＋樣品範圍字串（例如 'G1-G4, G7'）。"""

    name: str
    samples: str


class GroupingIn(BaseModel):
    """分組預填：平均分配用 names、自訂用 entries、自動不需要參數。"""

    mode: GroupMode
    names: list[str] = []
    entries: list[CustomEntry] = []


class GroupingOut(BaseModel):
    """分組狀態（給微調畫面）：各條件與未分配的樣品。"""

    conditions: list[ConditionModel]
    unassigned: list[str]


class ConditionsIn(BaseModel):
    """確認分組：所有樣品都要分配，條件名稱不可重複、樣品不可重複歸組。"""

    conditions: list[ConditionModel]


def to_core(models: list[ConditionModel]) -> list[Condition]:
    """把 API 的條件轉成 core 的 Condition（樣品代號會正規化並檢查格式）。"""
    return [Condition(m.name, tuple(parse_sample_id(s) for s in m.samples)) for m in models]


def require_project_names(names: list[str], allowed: list[str]) -> None:
    """條件名稱必須是專案統一定義的名稱（G-4）；專案還沒定義條件、或用了清單外的名稱時拋出 GroupingError。"""
    if not allowed:
        raise GroupingError("專案還沒有定義條件名稱，請先到「專案」頁新增條件")
    outside = [n for n in names if n not in allowed]
    if outside:
        raise GroupingError(f"條件「{'、'.join(outside)}」不在專案的條件清單中（{'、'.join(allowed)}）")


def _auto_with_project_names(samples: list[SampleId], allowed: list[str]) -> list[Condition]:
    """自動：每 4 個一組，條件名稱依序取專案的條件；組數多於條件數時拋出 GroupingError。"""
    groups = group_auto(samples)
    if len(groups) > len(allowed):
        raise GroupingError(
            f"自動分組需要 {len(groups)} 個條件，但專案只有 {len(allowed)} 個；請改用平均分配或自訂，或到「專案」頁新增條件"
        )
    return [Condition(name, g.samples) for name, g in zip(allowed, groups)]


def preview_grouping(samples: list[SampleId], body: GroupingIn, allowed: list[str]) -> GroupingOut:
    """依分組方式預填條件（不存檔）；沒被分到的樣品放在未分配。allowed 為專案的條件名稱。"""
    if body.mode is GroupMode.EVEN:
        require_project_names(body.names, allowed)
        conditions = group_even(samples, body.names)
    elif body.mode is GroupMode.CUSTOM:
        require_project_names([e.name for e in body.entries], allowed)
        conditions = group_custom([(e.name, e.samples) for e in body.entries])
    else:
        require_project_names([], allowed)
        conditions = _auto_with_project_names(samples, allowed)
    grouping = to_grouping(samples, conditions)
    return GroupingOut(
        conditions=[ConditionModel.from_core(c) for c in grouping.conditions],
        unassigned=[str(s) for s in grouping.unassigned],
    )


def confirm_grouping(samples: list[SampleId], body: ConditionsIn, allowed: list[str]) -> list[ConditionModel]:
    """驗證要確認的分組並回傳可存檔的條件。

    名稱須在專案條件清單中；group_custom 檢查名稱與重複歸組；to_grouping 檢查樣品是否存在；
    require_complete 檢查全部分配。
    """
    require_project_names([c.name for c in body.conditions], allowed)
    conditions = group_custom([(c.name, ",".join(c.samples)) for c in body.conditions])
    conditions = require_complete(to_grouping(samples, conditions))
    return [ConditionModel.from_core(c) for c in conditions]

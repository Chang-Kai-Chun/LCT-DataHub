"""分組畫面的共用狀態（mixin）：A JV 依樣品分組、B 暗電流依元件分組，邏輯完全相同。

流程：分組方式（平均分配／使用者自訂／自動）→ API 預填（不存檔）→ 點選微調 → 確定分組（存到伺服器）。
條件名稱只能從專案統一的條件中選（G-4，cond_choices）；自動分組依序取專案的條件名稱。
使用方式：class XxxState(GroupingMixin, SessionState)，並覆寫下方「子類別需提供」的方法；
子類別的 _apply_job 需呼叫 _load_choices(專案條件) 與 _load_conditions(已確認分組)。
"""
import re
from dataclasses import dataclass, field

import reflex as rx

from front import api_client as api
from front.api_client import ApiError
from front.enums import GroupMode

ADJUST_ID = "group-adjust"  # 「微調與確定」區塊的 id（套用分組後捲到這裡）
NEXT_ID = "group-next"  # 「確定分組」那一列的 id（確認後捲到這裡）
DEFAULT_COND_COUNT = 2  # 分組預設條件數
MAX_COND_COUNT = 12  # 條件數選單的上限（另受樣品數限制）
SAMPLE_PATTERN = re.compile(r"^([A-Z]{1,3})(\d+)$")  # API 回傳的樣品代號已正規化（大寫、無前導零）


@dataclass
class GroupCond:
    """分組畫面的一個條件框（給 rx.foreach 使用）。"""

    name: str = ""
    samples: list[str] = field(default_factory=list)


# ---------- 小工具 ----------
def split_sample(sample: str) -> tuple[str, int] | None:
    """把樣品代號拆成 (字母, 編號)，例如 I10 → ('I', 10)；格式不符回傳 None。"""
    match = SAMPLE_PATTERN.match(sample)
    return (match.group(1), int(match.group(2))) if match else None


def sample_prefixes(samples: list[str]) -> list[str]:
    """樣品代號中出現的字母，依出現順序。"""
    found: list[str] = []
    for s in samples:
        parts = split_sample(s)
        if parts and parts[0] not in found:
            found.append(parts[0])
    return found


def samples_in_range(samples: list[str], prefix: str, start: str, end: str) -> list[str]:
    """挑出範圍內「實際存在」的樣品（缺號自動略過）；end 空白表示只取 start 那一個。

    輸入格式錯誤拋出 ValueError；兩格都空白回傳空 list。
    """
    start, end = start.strip(), end.strip()
    if not start and not end:
        return []
    if not start:
        raise ValueError("請填起始編號")
    if not start.isdigit() or (end and not end.isdigit()):
        raise ValueError(f"編號只能填數字：{start} 到 {end}")
    lo = int(start)
    hi = int(end) if end else lo
    if lo > hi:
        raise ValueError(f"起始編號（{lo}）不可大於結束編號（{hi}）")
    result = []
    for s in samples:
        parts = split_sample(s)
        if parts and parts[0] == prefix and lo <= parts[1] <= hi:
            result.append(s)
    return result


class GroupingMixin(rx.State, mixin=True):
    """分組狀態；samples 為要分組的代號清單（JV 為樣品、暗電流為元件），依代號排序。"""

    samples: list[str] = []
    cond_choices: list[str] = []  # 專案統一的條件名稱（只能從這裡選）

    # 分組設定：選條件數 → 出現 N 個名稱框（自訂另有「從 [ ] 到 [ ]」的編號範圍）
    group_mode: str = GroupMode.EVEN.value
    cond_count: int = DEFAULT_COND_COUNT
    cond_names: list[str] = [""] * DEFAULT_COND_COUNT
    range_from: list[str] = [""] * DEFAULT_COND_COUNT  # 自訂：起始編號（只填數字）
    range_to: list[str] = [""] * DEFAULT_COND_COUNT  # 自訂：結束編號（空白表示只有起始那一個）
    range_prefix: list[str] = [""] * DEFAULT_COND_COUNT  # 自訂：樣品字母（只有一種字母時自動帶入）
    new_cond_name: str = ""
    conditions: list[GroupCond] = []
    unassigned: list[str] = []
    selected_sample: str = ""
    groups_confirmed: bool = False
    group_busy: bool = False  # 等待 API（套用、確定）時為 True，按鈕旁顯示八面體動畫

    # ---------- 子類別需提供 ----------
    def _job_path(self) -> str:
        """工作的 API 路徑，例如 /jv/jobs/<工作編號>。"""
        raise NotImplementedError

    def _apply_job(self, data: dict) -> None:
        """把 PUT conditions 回傳的工作內容填入狀態。"""
        raise NotImplementedError

    # 另需 _handle_error(err)（子類別）與 _show_message(text)（ErrorState）；
    # 這裡不定義空殼，否則 mixin 在 MRO 中排在 ErrorState 前面，會蓋掉 ErrorState 的實作

    def _on_groups_changed(self) -> None:
        """分組被修改（需重新確認）時，子類別可清除相關結果。"""

    def _on_groups_confirmed(self) -> None:
        """分組確認後，子類別可做額外處理。"""

    def _preview_path(self) -> str:
        """預填分組的 API 路徑（總覽分組可覆寫）。"""
        return f"{self._job_path()}/grouping/preview"

    def _confirm_path(self) -> str:
        """確定分組的 API 路徑（PUT；總覽分組可覆寫）。"""
        return f"{self._job_path()}/conditions"

    def _preview_extra(self) -> dict:
        """預填分組時額外送出的內容（總覽分組要送樣品清單）。"""
        return {}

    # ---------- 狀態更新（給子類別的 _apply_job 呼叫） ----------
    def _load_choices(self, choices: list[str]) -> None:
        """載入專案的條件名稱；名稱框中不在清單內（被改名或刪除）的清空，空白的依序補上未使用的名稱。"""
        self.cond_choices = list(choices)
        self.cond_count = max(1, min(self.cond_count, len(choices) or 1))
        names = [n if n in choices else "" for n in (self.cond_names + [""] * self.cond_count)[: self.cond_count]]
        self.cond_names = self._fill_names(names)
        if self.new_cond_name not in choices:
            self.new_cond_name = ""

    def _fill_names(self, names: list[str]) -> list[str]:
        """把空白的名稱框依序補上還沒用到的專案條件。"""
        unused = iter(c for c in self.cond_choices if c not in names)
        return [n or next(unused, "") for n in names]

    def _load_conditions(self, conditions: list[dict] | None) -> None:
        """載入伺服器上已確認的分組（None 表示尚未分組）；並帶入自訂範圍的預設字母。"""
        self.groups_confirmed = bool(conditions)
        if conditions:
            self.conditions = [GroupCond(c["name"], list(c["samples"])) for c in conditions]
            self.unassigned = []
        default_prefix = next(iter(sample_prefixes(self.samples)), "")
        self.range_prefix = [p or default_prefix for p in self.range_prefix]

    # ---------- 計算屬性 ----------
    @rx.var
    def can_confirm_groups(self) -> bool:
        """所有樣品都分配完、且至少有一個條件，才能按確定（require_complete）。"""
        return len(self.unassigned) == 0 and len(self.conditions) > 0

    @rx.var
    def count_options(self) -> list[str]:
        """條件數選單：1 到 min(樣品數, 專案條件數, MAX_COND_COUNT)。"""
        top = max(1, min(len(self.samples), len(self.cond_choices), MAX_COND_COUNT))
        return [str(n) for n in range(1, top + 1)]

    @rx.var
    def has_choices(self) -> bool:
        """專案已定義條件名稱（沒有時不能分組）。"""
        return len(self.cond_choices) > 0

    @rx.var
    def unused_choices(self) -> list[str]:
        """微調時可新增的條件：專案條件中還沒出現在條件框的。"""
        used = {c.name for c in self.conditions}
        return [c for c in self.cond_choices if c not in used]

    @rx.var
    def cond_indices(self) -> list[int]:
        """條件輸入框的索引（給 rx.foreach 產生 N 列）。"""
        return list(range(self.cond_count))

    @rx.var
    def prefixes(self) -> list[str]:
        """樣品代號中出現的字母（通常只有一種，例如 I）。"""
        return sample_prefixes(self.samples)

    @rx.var
    def range_previews(self) -> list[str]:
        """自訂：每一列範圍實際會分到的樣品（即時顯示，缺號已略過）。"""
        previews = []
        for i in range(self.cond_count):
            try:
                found = samples_in_range(self.samples, self.range_prefix[i], self.range_from[i], self.range_to[i])
            except ValueError as exc:
                previews.append(f"⚠ {exc}")
                continue
            if found:
                previews.append("→ " + "、".join(found))
            elif self.range_from[i].strip():
                previews.append("⚠ 範圍內沒有樣品")
            else:
                previews.append("")
        return previews

    # ---------- 輸入框 ----------
    @rx.event
    def set_group_mode(self, value: str | list[str]) -> None:
        """分組方式（segmented_control 單選時傳入 str）。"""
        self.group_mode = value if isinstance(value, str) else value[0]

    @rx.event
    def set_cond_count(self, value: str) -> None:
        """選擇條件數：調整輸入框數量，已填的內容保留。"""
        n = int(value)

        def _resize(items: list[str], fill: str = "") -> list[str]:
            """截短或補齊到 n 個。"""
            return (items + [fill] * n)[:n]

        default_prefix = next(iter(sample_prefixes(self.samples)), "")
        self.cond_count = n
        self.cond_names = self._fill_names(_resize(self.cond_names))
        self.range_from = _resize(self.range_from)
        self.range_to = _resize(self.range_to)
        self.range_prefix = [p or default_prefix for p in _resize(self.range_prefix, default_prefix)]

    @staticmethod
    def _replace(items: list[str], index: int, value: str) -> list[str]:
        """回傳把第 index 項換成 value 的新 list（重新指定才會觸發畫面更新）。"""
        items = list(items)
        items[index] = value
        return items

    @rx.event
    def set_cond_name(self, index: int, value: str) -> None:
        """第 index 個條件名稱。"""
        self.cond_names = self._replace(self.cond_names, index, value)

    @rx.event
    def set_range_from(self, index: int, value: str) -> None:
        """第 index 列的起始編號。"""
        self.range_from = self._replace(self.range_from, index, value)

    @rx.event
    def set_range_to(self, index: int, value: str) -> None:
        """第 index 列的結束編號。"""
        self.range_to = self._replace(self.range_to, index, value)

    @rx.event
    def set_range_prefix(self, index: int, value: str) -> None:
        """第 index 列的樣品字母（有多種字母時才需要選）。"""
        self.range_prefix = self._replace(self.range_prefix, index, value)

    @rx.event
    def set_new_cond_name(self, value: str) -> None:
        """新增條件的名稱。"""
        self.new_cond_name = value

    # ---------- 預填 ----------
    def _checked_names(self) -> list[str]:
        """取出 N 個條件名稱；有空白或重複時拋出 ValueError。"""
        names = [n.strip() for n in self.cond_names[: self.cond_count]]
        empty = [str(i + 1) for i, n in enumerate(names) if not n]
        if empty:
            raise ValueError(f"第 {'、'.join(empty)} 個條件還沒填名稱")
        if len(set(names)) != len(names):
            raise ValueError("條件名稱不可重複")
        return names

    def _custom_entries(self, names: list[str]) -> list[dict]:
        """自訂：把每列「從 [ ] 到 [ ]」轉成實際存在的樣品清單（API 的 entries）。"""
        entries = []
        for i, name in enumerate(names):
            try:
                found = samples_in_range(self.samples, self.range_prefix[i], self.range_from[i], self.range_to[i])
            except ValueError as exc:
                raise ValueError(f"條件「{name}」：{exc}") from None
            if not found:
                raise ValueError(f"條件「{name}」的範圍內沒有樣品")
            entries.append({"name": name, "samples": ", ".join(found)})
        return entries

    def _sorted(self, samples: list[str]) -> list[str]:
        """依樣品清單的順序排序。"""
        order = {s: i for i, s in enumerate(self.samples)}
        return sorted(samples, key=lambda s: order.get(s, len(order)))

    def _unconfirm(self) -> None:
        """分組被修改後，需重新確認。"""
        self.groups_confirmed = False
        self._on_groups_changed()

    @rx.event
    async def apply_grouping(self):
        """套用分組：依方式請 API 算出初步分組（不存檔），之後可點選微調，再按「確定分組」。"""
        mode = GroupMode(self.group_mode)
        body: dict = {"mode": mode.value}
        try:
            if mode is GroupMode.EVEN:
                body["names"] = self._checked_names()
            elif mode is GroupMode.CUSTOM:
                body["entries"] = self._custom_entries(self._checked_names())
        except ValueError as exc:
            self._show_message(str(exc))
            return
        self.group_busy = True
        yield
        try:
            data = await api.post_json(self._preview_path(), {**body, **self._preview_extra()})
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.group_busy = False
        self.conditions = [GroupCond(c["name"], list(c["samples"])) for c in data["conditions"]]
        self.unassigned = list(data["unassigned"])
        self.selected_sample = ""
        self._unconfirm()
        yield rx.scroll_to(ADJUST_ID)  # 捲到「微調與確定」，提示下一步

    @rx.event
    def apply_project_grouping(self):
        """套用總覽的分組：取專案分組中本區有的樣品；本區多出來的樣品放在未分配，之後可微調再確定。

        project_grouping 來自 SessionState（各區 State 都是它的子狀態）。
        """
        present = set(self.samples)
        conds = [
            GroupCond(g.name, self._sorted([s for s in g.samples if s in present]))
            for g in self.project_grouping
            if g.name in self.cond_choices
        ]
        conds = [c for c in conds if c.samples]
        if not conds:
            self._show_message("總覽的分組中，沒有本區的樣品")
            return
        assigned = {s for c in conds for s in c.samples}
        self.conditions = conds
        self.unassigned = [s for s in self.samples if s not in assigned]
        self.selected_sample = ""
        self._unconfirm()
        return rx.scroll_to(ADJUST_ID)

    # ---------- 微調 ----------
    @rx.event
    def add_condition(self) -> None:
        """新增一個空白條件框（名稱從專案條件中選）。"""
        name = self.new_cond_name.strip()
        if not name:
            self._show_message("請選擇要新增的條件")
            return
        if any(c.name == name for c in self.conditions):
            self._show_message(f"條件名稱「{name}」已存在")
            return
        if not self.conditions and not self.unassigned:
            self.unassigned = list(self.samples)  # 第一次直接新增條件時，樣品都先放未分配區
        self.conditions = [*self.conditions, GroupCond(name, [])]
        self.new_cond_name = ""
        self._unconfirm()

    @rx.event
    def remove_condition(self, index: int) -> None:
        """刪除條件框，其中的樣品移回未分配區。"""
        removed = self.conditions[index]
        self.conditions = [c for i, c in enumerate(self.conditions) if i != index]
        self.unassigned = self._sorted([*self.unassigned, *removed.samples])
        self._unconfirm()

    @rx.event
    def pick_sample(self, sample: str) -> None:
        """點選樣品卡片（再點一次取消）。"""
        self.selected_sample = "" if self.selected_sample == sample else sample

    def _take_selected(self) -> str:
        """把已選的樣品從所在位置移除並回傳；沒有選擇時回傳空字串。"""
        sample = self.selected_sample
        if not sample:
            return ""
        self.unassigned = [s for s in self.unassigned if s != sample]
        self.conditions = [GroupCond(c.name, [s for s in c.samples if s != sample]) for c in self.conditions]
        self.selected_sample = ""
        return sample

    @rx.event
    def move_to(self, index: int) -> None:
        """把已選的樣品放進第 index 個條件框。"""
        sample = self._take_selected()
        if not sample:
            return
        conds = list(self.conditions)
        conds[index] = GroupCond(conds[index].name, self._sorted([*conds[index].samples, sample]))
        self.conditions = conds
        self._unconfirm()

    @rx.event
    def move_to_unassigned(self) -> None:
        """把已選的樣品移回未分配區。"""
        sample = self._take_selected()
        if not sample:
            return
        self.unassigned = self._sorted([*self.unassigned, sample])
        self._unconfirm()

    # ---------- 確定 ----------
    @rx.event
    async def confirm_grouping(self):
        """確認分組並存到伺服器；所有樣品須分配完。"""
        if self.unassigned:
            self._show_message("尚未分配的樣品：" + "、".join(self.unassigned))
            return
        body = {"conditions": [{"name": c.name, "samples": c.samples} for c in self.conditions]}
        self.group_busy = True
        yield
        try:
            data = await api.put_json(self._confirm_path(), body)
        except ApiError as err:
            self._handle_error(err)
            return
        finally:
            self.group_busy = False
        self._apply_job(data)
        self._on_groups_confirmed()
        yield rx.scroll_to(NEXT_ID)  # 捲到「已確認／下一步」

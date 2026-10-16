"""A-1：樣品分組（平均分配、使用者自訂、自動），結果為 Condition 清單。

UI 先顯示分組結果，使用者可拖拉調整；調整時呼叫 move_sample。
"""
from lct_datahub.core.jv.integrate import make_condition
from lct_datahub.core.jv.types import Condition, Grouping, GroupingError, JVFile
from lct_datahub.core.sample_id import SampleId

AUTO_GROUP_SIZE = 4  # 自動分組：每組樣品數


def sample_list(files: list[JVFile]) -> list[SampleId]:
    """檔案中出現的樣品（不分 FW／RV，不重複），依代號與數字大小排序。"""
    return sorted({jv.name.sample for jv in files})


def _check_names(names: list[str]) -> list[str]:
    """條件名稱不可空白、不可重複；回傳去除前後空白的名稱。"""
    cleaned = [n.strip() for n in names]
    if any(not n for n in cleaned):
        raise GroupingError("條件名稱不可空白")
    if len(set(cleaned)) != len(cleaned):
        raise GroupingError("條件名稱不可重複")
    return cleaned


def group_even(samples: list[SampleId], names: list[str]) -> list[Condition]:
    """平均分配：樣品依序平均分到各條件（16 個樣品、4 個條件 → 每組 4 個）。

    無法整除時，前面的條件各多一個（例如 9 個樣品、4 個條件 → 3、2、2、2）。
    """
    names = _check_names(names)
    if not names:
        raise GroupingError("至少需要 1 個條件")
    if len(names) > len(samples):
        raise GroupingError(f"條件數（{len(names)}）多於樣品數（{len(samples)}）")
    base, extra = divmod(len(samples), len(names))
    groups, start = [], 0
    for i, name in enumerate(names):
        size = base + (1 if i < extra else 0)
        groups.append(Condition(name, tuple(samples[start : start + size])))
        start += size
    return groups


def group_custom(entries: list[tuple[str, str]]) -> list[Condition]:
    """使用者自訂：entries 為 (條件名稱, 樣品範圍字串)，例如 ('Ref', 'G1-G4, G7')。

    同一個樣品不可歸入兩個條件。
    """
    _check_names([name for name, _ in entries])
    conditions = [make_condition(name, text) for name, text in entries]
    seen: dict[SampleId, str] = {}
    for cond in conditions:
        for sample in cond.samples:
            if sample in seen:
                raise GroupingError(f"{sample} 同時屬於「{seen[sample]}」與「{cond.name}」")
            seen[sample] = cond.name
    return conditions


def group_auto(samples: list[SampleId]) -> list[Condition]:
    """自動：每 AUTO_GROUP_SIZE 個樣品一組，餘數放在最後一組；條件名稱為 Group 1、Group 2…。"""
    if not samples:
        raise GroupingError("沒有樣品可分組")
    return [
        Condition(f"Group {i + 1}", tuple(samples[start : start + AUTO_GROUP_SIZE]))
        for i, start in enumerate(range(0, len(samples), AUTO_GROUP_SIZE))
    ]


def start_grouping(samples: list[SampleId], names: list[str]) -> Grouping:
    """開始手動分組：建立空的條件框，所有樣品先放在未分配區。"""
    names = _check_names(names)
    if not names:
        raise GroupingError("至少需要 1 個條件")
    return Grouping(
        conditions=tuple(Condition(n, ()) for n in names),
        unassigned=tuple(sorted(samples)),
    )


def to_grouping(samples: list[SampleId], conditions: list[Condition]) -> Grouping:
    """把預填的分組（平均、自訂、自動的結果）轉成分組狀態；沒被分到的樣品進未分配區。"""
    known = set(samples)
    assigned: set[SampleId] = set()
    for cond in conditions:
        for sample in cond.samples:
            if sample not in known:
                raise GroupingError(f"{sample} 不在檔案的樣品中（條件「{cond.name}」）")
            assigned.add(sample)
    return Grouping(
        conditions=tuple(conditions),
        unassigned=tuple(sorted(known - assigned)),
    )


def move_sample(grouping: Grouping, sample: SampleId, target: str | None) -> Grouping:
    """把樣品移到另一個條件，或移回未分配區（target 為 None）；對應 UI 拖拉。

    回傳新的分組狀態，原本的不變。條件內與未分配區都依數字大小排序。
    """
    names = {c.name for c in grouping.conditions}
    if target is not None and target not in names:
        raise GroupingError(f"找不到條件：{target}")
    in_conditions = any(sample in c.samples for c in grouping.conditions)
    if not in_conditions and sample not in grouping.unassigned:
        raise GroupingError(f"{sample} 不在分組中")

    # 先從原本的位置移除，再放進目標
    conditions = []
    for cond in grouping.conditions:
        members = [s for s in cond.samples if s != sample]
        if cond.name == target:
            members.append(sample)
        conditions.append(Condition(cond.name, tuple(sorted(members))))
    unassigned = [s for s in grouping.unassigned if s != sample]
    if target is None:
        unassigned.append(sample)
    return Grouping(tuple(conditions), tuple(sorted(unassigned)))


def require_complete(grouping: Grouping) -> list[Condition]:
    """確認所有樣品都已分配；否則拋出 GroupingError 並列出未分配的樣品。"""
    if not grouping.is_complete:
        left = "、".join(str(s) for s in grouping.unassigned)
        raise GroupingError(f"還有樣品尚未分配：{left}")
    return list(grouping.conditions)

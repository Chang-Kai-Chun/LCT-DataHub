"""B-3：依名稱挑出要畫的暗電流曲線（供預覽勾選使用），以及曲線所屬的樣品（供分組）。

樣品代號的判斷（device_of）放在共用的 core/sample_id.py（B、C 區共用），這裡再匯出以維持原本的用法。
"""
from lct_datahub.core.dark_current.types import DarkCurve
from lct_datahub.core.sample_id import SampleId, device_of, devices_of

__all__ = ["curve_names", "select_dark_curves", "device_of", "device_list"]


def curve_names(curves: list[DarkCurve]) -> list[str]:
    """全部曲線的名稱（維持讀入順序），供 UI 顯示勾選清單。"""
    return [c.name for c in curves]


def select_dark_curves(curves: list[DarkCurve], names: list[str]) -> list[DarkCurve]:
    """依 names 的順序挑出曲線；有不存在的名稱就拋出 KeyError（列出所有找不到的名稱）。"""
    by_name = {c.name: c for c in curves}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise KeyError(f"找不到曲線：{missing}")
    return [by_name[n] for n in names]


def device_list(curves: list[DarkCurve]) -> list[SampleId]:
    """所有曲線出現的樣品（不重複），依字母、數字大小排序；作為分組的樣品清單。"""
    return devices_of([c.name for c in curves])

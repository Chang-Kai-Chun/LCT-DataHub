"""B-3：依名稱挑出要畫的暗電流曲線（供預覽勾選使用），以及曲線所屬的元件（供分組）。"""
import re

from lct_datahub.core.dark_current.types import DarkCurve
from lct_datahub.core.sample_id import SampleId, parse_sample_id

# 曲線名稱開頭的元件代號：1–3 個字母＋數字，後面不可緊接字母或數字
# 例：G1-3 → G1、G7-1_second → G7、G1 REF-1_330 K（明志）→ G1、G10-4 → G10
_DEVICE_PATTERN = re.compile(r"^([A-Za-z]{1,3}\d+)(?![A-Za-z0-9])")


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


def device_of(name: str) -> SampleId | None:
    """曲線所屬的元件：取名稱開頭的樣品代號（G1-1 → G1）；開頭不是代號時回傳 None。"""
    match = _DEVICE_PATTERN.match(name.strip())
    return parse_sample_id(match.group(1)) if match else None


def device_list(curves: list[DarkCurve]) -> list[SampleId]:
    """所有曲線出現的元件（不重複），依字母、數字大小排序；作為分組的樣品清單。"""
    return sorted({d for c in curves if (d := device_of(c.name)) is not None})

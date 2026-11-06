"""C-2、C-3：依名稱挑出要畫的 EQE 曲線（供預覽勾選使用）。"""
from lct_datahub.core.eqe.types import EqeCurve


def curve_names(curves: list[EqeCurve]) -> list[str]:
    """全部曲線的名稱（維持讀入順序），供 UI 顯示勾選清單。"""
    return [c.name for c in curves]


def select_eqe_curves(curves: list[EqeCurve], names: list[str]) -> list[EqeCurve]:
    """依 names 的順序挑出曲線；有不存在的名稱就拋出 KeyError（列出所有找不到的名稱）。"""
    by_name = {c.name: c for c in curves}
    missing = [n for n in names if n not in by_name]
    if missing:
        raise KeyError(f"找不到曲線：{missing}")
    return [by_name[n] for n in names]

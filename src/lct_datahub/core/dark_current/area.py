"""B-1：以使用者指定的有效面積重算暗電流密度。

面積確認彈窗選「改為 ＿＿ cm²」時使用；**會更動數據**，UI 須先告知（見 AREA_OVERRIDE_NOTICE）。
電流 I 是量測結果不變；J = |I| / 新面積。
"""
import dataclasses
import math

from lct_datahub.core.dark_current.types import DarkColumn, DarkCurve
from lct_datahub.core.jv.types import InvalidAreaError

# 給 UI 顯示的警告文字
AREA_OVERRIDE_NOTICE = "數據將被更動：改用指定的有效面積後，電流密度 J 會以新面積重算（J = |I| ÷ 面積）；電流 I 不變。"


def apply_dark_area(curves: list[DarkCurve], area: float) -> list[DarkCurve]:
    """把全部曲線的有效面積改成 area（cm²）並重算 J；回傳新的清單，原本的不變。"""
    if not math.isfinite(area) or area <= 0:
        raise InvalidAreaError(f"有效面積必須是大於 0 的數值（cm²）：{area}")
    result = []
    for curve in curves:
        data = curve.data.copy()
        data[DarkColumn.J.value] = data[DarkColumn.CURRENT.value].abs() / area
        result.append(dataclasses.replace(curve, area=area, area_from_file=False, data=data))
    return result

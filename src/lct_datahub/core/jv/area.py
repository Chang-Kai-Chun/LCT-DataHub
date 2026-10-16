"""A-1：以使用者指定的有效面積重算 JV 數據。

面積確認彈窗選「改為 ＿＿ cm²」時使用。**這會更動數據**，UI 必須先告知使用者
（見 AREA_OVERRIDE_NOTICE），確認後才呼叫 apply_area。

換面積時，電流 I（mA）、Voc、FF、Rs、Rsh 是量測結果，不變；與面積有關的量按比例重算：
  - J（曲線的 J 欄）= I / 新面積
  - Jsc（彙整表）  = Isc / 新面積，等於 舊 Jsc × 舊面積 / 新面積
  - PCE（Efficiency）= Pmax / (入射功率密度 × 面積)，等於 舊 PCE × 舊面積 / 新面積
"""
import dataclasses
import math

from lct_datahub.core.jv.types import CurveColumn, InvalidAreaError, JVFile, JVParam

# 給 UI 顯示的警告文字
AREA_OVERRIDE_NOTICE = (
    "數據將被更動：改用指定的有效面積後，電流密度 J、Jsc 與效率 PCE 會以新面積重算；"
    "電流 I、Voc、FF、Rsh 不變。"
)

# 會被重算的參數（供 UI 與測試列出）
RECOMPUTED_PARAMS = (JVParam.JSC, JVParam.PCE)


def apply_area(files: list[JVFile], area: float) -> list[JVFile]:
    """把全部檔案的有效面積改成 area（cm²），並重算 J、Jsc、PCE；回傳新的檔案清單，原本的不變。"""
    if not math.isfinite(area) or area <= 0:
        raise InvalidAreaError(f"有效面積必須是大於 0 的數值（cm²）：{area}")

    result = []
    for jv in files:
        params = jv.params.copy()
        curves = []
        # params 的列順序與 curves 相同；各曲線的舊面積可能不同，逐條處理
        for i, curve in enumerate(jv.curves):
            scale = curve.area / area  # 舊面積 / 新面積
            data = curve.data.copy()
            data[CurveColumn.J.value] = data[CurveColumn.CURRENT.value] / area  # J = I / A
            params.iloc[i, params.columns.get_loc(JVParam.JSC.value)] *= scale
            params.iloc[i, params.columns.get_loc(JVParam.PCE.value)] *= scale
            curves.append(dataclasses.replace(curve, area=area, data=data))
        result.append(dataclasses.replace(jv, curves=tuple(curves), params=params))
    return result

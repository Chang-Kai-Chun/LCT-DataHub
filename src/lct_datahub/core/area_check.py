"""有效面積檢查（各功能共用）：找出各檔案的面積是否一致。

只負責「檢查」並回報結果；詢問使用者（忽略並繼續／改用指定面積）屬於 UI。
"""
from dataclasses import dataclass

# 面積比對時四捨五入到小數第幾位（cm²），避免浮點誤差造成誤判
_DECIMALS = 9


@dataclass(frozen=True)
class AreaReport:
    """面積檢查結果。"""

    by_file: dict[str, tuple[float, ...]]  # 檔名 → 該檔出現的面積（不重複，由小到大）
    values: tuple[float, ...]  # 全部檔案出現過的面積（不重複，由小到大）

    @property
    def is_uniform(self) -> bool:
        """所有檔案的面積是否都相同。"""
        return len(self.values) <= 1

    @property
    def uniform_value(self) -> float | None:
        """面積一致時的值；沒有資料或不一致時為 None。"""
        return self.values[0] if len(self.values) == 1 else None

    def files_with(self, area: float) -> list[str]:
        """含有指定面積的檔名（供 UI 顯示「哪些檔案是這個面積」）。"""
        target = round(area, _DECIMALS)
        return [name for name, areas in self.by_file.items() if target in areas]


def check_areas(areas_by_file: dict[str, list[float]]) -> AreaReport:
    """檢查各檔案的面積：輸入為「檔名 → 該檔所有面積」，輸出 AreaReport。

    同一個檔案內不同曲線的面積也會一併比較。
    """
    by_file = {
        name: tuple(sorted({round(a, _DECIMALS) for a in areas}))
        for name, areas in areas_by_file.items()
    }
    values = tuple(sorted({a for areas in by_file.values() for a in areas}))
    return AreaReport(by_file=by_file, values=values)

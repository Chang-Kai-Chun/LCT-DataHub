"""名稱處理（各功能共用）：同名自動編號、Excel sheet 名稱清理。"""
import re

_MAX_SHEET_NAME = 31  # Excel 的 sheet 名稱上限
_BAD_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")


def unique_names(names: list[str]) -> list[str]:
    """同名依出現順序加 _2、_3…（第一個保持原名）；名稱已被占用時繼續遞增。"""
    used: set[str] = set()
    result = []
    for base in names:
        name, n = base, 1
        while name in used:
            n += 1
            name = f"{base}_{n}"
        used.add(name)
        result.append(name)
    return result


def safe_sheet_names(names: list[str], reserved: set[str]) -> list[str]:
    """把名稱轉成合法的 sheet 名稱：不允許的字元換成底線、截到 31 字，並與 reserved 及彼此都不重複（不分大小寫）。"""
    used = {r.lower() for r in reserved}
    result = []
    for raw in names:
        base = _BAD_SHEET_CHARS.sub("_", raw)[:_MAX_SHEET_NAME] or "Sheet"
        name, n = base, 1
        while name.lower() in used:
            n += 1
            suffix = f"_{n}"
            name = base[: _MAX_SHEET_NAME - len(suffix)] + suffix
        used.add(name.lower())
        result.append(name)
    return result

"""A-1：JV 檔名解析（<代號+編號> <FW|RV> <Pixel 數字串>）與重複檔案檢查。

三段之間的空格可有可無（2026-11-13）：G1 FW 432、G1FW432、G1 FW432 都可以。
任何問題都拋出 JVFileError（不略過、不猜測），由呼叫端警告並停止作業。
"""
import re
from collections import defaultdict
from pathlib import PurePath

from lct_datahub.core.jv.types import (
    VALID_PIXELS,
    Direction,
    FailureReason,
    JVFileError,
    JVFileName,
)
from lct_datahub.core.sample_id import InvalidSampleIdError, parse_sample_id

_FORMAT_HINT = "例如 G1 FW 432 或 G1FW432"

# 方向的寫法（FW|RV），由 Direction 產生，避免寫死
_DIRS = "|".join(d.value for d in Direction)
# 第 1 段：樣品代號（1–3 個字母＋數字），後面必須是空白、方向或結尾，避免 G1x 這類被誤切
_SAMPLE_PART = re.compile(rf"^([A-Za-z]{{1,3}}\d+)(?=\s|{_DIRS}|$)\s*(.*)$", re.IGNORECASE)
# 第 2 段：方向，後面必須是空白、數字或結尾，避免 FWD 被當成 FW
_DIRECTION_PART = re.compile(rf"^({_DIRS})(?=\s|\d|$)\s*(.*)$", re.IGNORECASE)


def parse_jv_filename(filename: str) -> JVFileName:
    """解析單一檔名（可含副檔名），例如 'G1 FW 432.csv' 或 'G1FW432.csv'。

    依序從前面切出樣品、方向、Pixel；三段之間的空格可有可無，大小寫不分。
    """
    stem = PurePath(filename).stem.strip()

    # 第 1 段：樣品代號
    if not stem:
        raise JVFileError(filename, FailureReason.BAD_FORMAT, _FORMAT_HINT, "空白檔名")
    match = _SAMPLE_PART.match(stem)
    if match is None:
        raise JVFileError(filename, FailureReason.BAD_FORMAT, _FORMAT_HINT, stem)
    try:
        sample = parse_sample_id(match.group(1))
    except InvalidSampleIdError:
        raise JVFileError(filename, FailureReason.BAD_FORMAT, _FORMAT_HINT, stem) from None
    rest = match.group(2)

    # 第 2 段：方向（不分大小寫）
    match = _DIRECTION_PART.match(rest)
    if match is None:
        actual = rest.split()[0] if rest else "無"
        raise JVFileError(filename, FailureReason.MISSING_DIRECTION, "FW 或 RV", actual)
    direction = Direction(match.group(1).upper())
    digits = match.group(2)

    # 第 3 段：Pixel 數字串（之後不可再有其他內容）
    if not digits:
        raise JVFileError(filename, FailureReason.MISSING_PIXELS, "2–6 的數字串，例如 432", "無")
    if len(digits.split()) > 1:
        raise JVFileError(filename, FailureReason.BAD_FORMAT, _FORMAT_HINT, stem)
    if not digits.isdigit():
        raise JVFileError(filename, FailureReason.INVALID_PIXEL, "只含 2–6 的數字", digits)
    pixels = tuple(int(c) for c in digits)
    # 數字必須在 2–6，且同一個 Pixel 不可出現兩次
    if not set(pixels) <= VALID_PIXELS or len(set(pixels)) != len(pixels):
        raise JVFileError(filename, FailureReason.INVALID_PIXEL, "2–6 的數字且不重複", digits)

    return JVFileName(sample=sample, direction=direction, pixels=pixels, filename=filename)


def check_curve_count(parsed: JVFileName, curve_count: int) -> None:
    """檢查檔名的 Pixel 個數是否等於檔內曲線組數；不符時拋出 JVFileError。"""
    if len(parsed.pixels) != curve_count:
        raise JVFileError(
            parsed.filename,
            FailureReason.COUNT_MISMATCH,
            f"檔名 {len(parsed.pixels)} 個 Pixel",
            f"檔內 {curve_count} 組曲線",
        )


def parse_jv_filenames(filenames: list[str]) -> list[JVFileName]:
    """解析一批檔名並檢查重複；任一檔案有問題就拋出 JVFileError。

    回傳依樣品（數字大小）與方向排序的結果。
    """
    results = [parse_jv_filename(name) for name in filenames]

    # 同一樣品、同一方向出現兩個以上檔案視為重複
    groups: dict[tuple, list[str]] = defaultdict(list)
    for item in results:
        groups[(item.sample, item.direction)].append(item.filename)
    for (sample, direction), names in groups.items():
        if len(names) > 1:
            raise JVFileError(
                "、".join(names),
                FailureReason.DUPLICATE,
                f"{sample} {direction.value} 只有一個檔案",
                f"{len(names)} 個檔案",
            )

    return sorted(results, key=lambda r: (r.sample, r.direction.value))

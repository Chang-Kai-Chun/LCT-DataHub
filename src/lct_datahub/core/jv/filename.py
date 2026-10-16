"""A-1：JV 檔名解析（<代號+編號> <FW|RV> <Pixel 數字串>）與重複檔案檢查。

任何問題都拋出 JVFileError（不略過、不猜測），由呼叫端警告並停止作業。
"""
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

_FORMAT_HINT = "例如 G1 FW 432"


def parse_jv_filename(filename: str) -> JVFileName:
    """解析單一檔名（可含副檔名），例如 'G1 FW 432.csv'。"""
    stem = PurePath(filename).stem
    tokens = stem.split()

    # 第 1 段：樣品代號
    if not tokens:
        raise JVFileError(filename, FailureReason.BAD_FORMAT, _FORMAT_HINT, "空白檔名")
    try:
        sample = parse_sample_id(tokens[0])
    except InvalidSampleIdError:
        raise JVFileError(filename, FailureReason.BAD_FORMAT, _FORMAT_HINT, stem) from None

    # 第 2 段：方向（不分大小寫）
    valid_dirs = {d.value for d in Direction}
    if len(tokens) < 2 or tokens[1].upper() not in valid_dirs:
        actual = tokens[1] if len(tokens) >= 2 else "無"
        raise JVFileError(filename, FailureReason.MISSING_DIRECTION, "FW 或 RV", actual)
    direction = Direction(tokens[1].upper())

    # 第 3 段：Pixel 數字串
    if len(tokens) < 3:
        raise JVFileError(filename, FailureReason.MISSING_PIXELS, "2–6 的數字串，例如 432", "無")
    if len(tokens) > 3:
        raise JVFileError(filename, FailureReason.BAD_FORMAT, _FORMAT_HINT, stem)
    digits = tokens[2]
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

"""樣品代號：正規化、範圍展開、排序（各功能共用）。

格式為 1–3 個字母＋數字，例如 G1、fat7、Qwe13。
字母轉大寫、數字去前導零（G01 與 G1 視為同一個）。
"""
import re
from dataclasses import dataclass

# 1–3 個字母＋至少一位數字
_SAMPLE_PATTERN = re.compile(r"^([A-Za-z]{1,3})(\d+)$")


class InvalidSampleIdError(ValueError):
    """樣品代號格式不符時拋出。"""


@dataclass(frozen=True, order=True)
class SampleId:
    """正規化後的樣品代號。

    排序時先比字母、再比數字大小（G10 排在 G2 之後）。
    """

    prefix: str  # 大寫字母
    number: int  # 已去前導零

    def __str__(self) -> str:
        """回傳正規化字串，例如 G1。"""
        return f"{self.prefix}{self.number}"


def parse_sample_id(text: str) -> SampleId:
    """把字串轉成 SampleId；格式不符時拋出 InvalidSampleIdError。"""
    match = _SAMPLE_PATTERN.match(text.strip())
    if match is None:
        raise InvalidSampleIdError(f"樣品代號格式不符（需 1–3 個字母加數字）：{text!r}")
    # 轉大寫；int() 會自動去掉前導零
    return SampleId(prefix=match.group(1).upper(), number=int(match.group(2)))


def expand_range(text: str) -> list[SampleId]:
    """展開樣品範圍，例如 'G1-G4' 展開成 G1、G2、G3、G4；單一代號回傳只有一個元素的 list。

    範圍兩端的字母必須相同，且起點不可大於終點。
    """
    parts = text.split("-")
    if len(parts) == 1:
        return [parse_sample_id(parts[0])]
    if len(parts) != 2:
        raise InvalidSampleIdError(f"範圍格式不符：{text!r}")
    start, end = parse_sample_id(parts[0]), parse_sample_id(parts[1])
    if start.prefix != end.prefix:
        raise InvalidSampleIdError(f"範圍兩端的字母不同：{text!r}")
    if start.number > end.number:
        raise InvalidSampleIdError(f"範圍起點大於終點：{text!r}")
    return [SampleId(start.prefix, n) for n in range(start.number, end.number + 1)]


def sort_samples(samples: list[SampleId]) -> list[SampleId]:
    """依字母、數字大小排序（不依字串）。"""
    return sorted(samples)


def expand_samples(text: str) -> list[SampleId]:
    """展開以逗號分隔的樣品清單，每一項可是單一代號或範圍，例如 'G1-G4, G7'。

    半形與全形逗號都可使用；重複的代號只保留第一次出現，並依輸入順序回傳。
    """
    result: list[SampleId] = []
    for part in text.replace("，", ",").split(","):
        if not part.strip():
            continue
        for sample in expand_range(part.strip()):
            if sample not in result:
                result.append(sample)
    if not result:
        raise InvalidSampleIdError(f"沒有任何樣品：{text!r}")
    return result

"""D-2：noise 組與 B-4 暗電流擷取值的配對（參考線用，2026-11-19 定案）。

- 名稱：暗電流曲線名稱取第一個底線之前（G1-2_330 K → G1-2；PD-QE 的 G1-3 不變），不分大小寫與 noise 樣品比對
- 同一個 pixel 有兩台儀器的暗電流時，自動選與 noise 相同儀器的那條（明志配明志、PD-QE 配 PD-QE）；
  沒有相同儀器才用另一台，並註明
- 使用者可手動指定配對（或指定不配對），手動優先
- 暗電流取與 noise 相同偏壓（B-4 的 0／−0.1／−0.5 V）；偏壓不在其中時只有 Thermal
"""
from dataclasses import dataclass

from lct_datahub.core.dark_current.extract import DarkExtract
from lct_datahub.core.dark_current.types import ExtractBias
from lct_datahub.core.noise.reference import ROOM_TEMPERATURE, ReferenceLine, reference_lines
from lct_datahub.core.noise.types import NoiseGroup

NO_PAIR = ""  # 手動指定「不配對」


def pixel_key(name: str) -> str:
    """配對鍵：第一個底線之前、去掉前後空白、轉大寫（G1-2_330 K → G1-2）。"""
    return name.split("_", 1)[0].strip().upper()


def extract_bias(bias: float) -> ExtractBias | None:
    """noise 偏壓對應的 B-4 電壓；不在 0／−0.1／−0.5 V 時為 None。"""
    return next((b for b in ExtractBias if abs(b.value - bias) < 1e-9), None)


@dataclass(frozen=True)
class DarkPair:
    """一個 noise 組的配對結果。"""

    dark: DarkExtract | None  # 配對到的暗電流擷取值（None：沒有配對）
    manual: bool  # 使用者手動指定
    note: str  # 說明（不同儀器、偏壓不在 B-4 等）
    dark_current: float | None  # 同偏壓的 Id（A）
    lines: list[ReferenceLine]  # Shot、Thermal、總和

    @property
    def total(self) -> float | None:
        """理論白雜訊（Shot＋Thermal）；只有其中一項時為該項；沒有配對為 None。"""
        return self.lines[-1].value if self.lines else None


def candidates(sample: str, extracts: list[DarkExtract]) -> list[DarkExtract]:
    """名稱相同的暗電流擷取值。"""
    return [e for e in extracts if pixel_key(e.name) == sample.upper()]


def pair_group(group: NoiseGroup, extracts: list[DarkExtract], manual: dict[str, str] | None = None,
               key: str | None = None, temperature: float = ROOM_TEMPERATURE) -> DarkPair:
    """為一個 noise 組找暗電流擷取值並算參考線；manual 為 {組的鍵: 暗電流曲線名稱或 NO_PAIR}，key 預設為 group.label。"""
    key = key or group.label
    manual = manual or {}
    notes: list[str] = []
    if key in manual:
        chosen = next((e for e in extracts if e.name == manual[key]), None)
        if manual[key] != NO_PAIR and chosen is None:
            notes.append(f"手動指定的暗電流「{manual[key]}」不存在")
        is_manual = True
    else:
        found = candidates(group.sample, extracts)
        same = [e for e in found if e.instrument.value == group.instrument.value]
        chosen = (same or found or [None])[0]
        if chosen is not None and not same:
            notes.append(f"沒有{group.instrument.value}的暗電流，改用{chosen.instrument.value}")
        is_manual = False
    if chosen is None:
        return DarkPair(None, is_manual, "；".join(notes) or "找不到對應的暗電流", None, [])
    bias = extract_bias(group.bias)
    dark_current = chosen.id.get(bias) if bias is not None else None
    if bias is None:
        notes.append(f"B-4 沒有 {group.bias:g} V 的暗電流，只畫 Thermal")
    lines = reference_lines(group.sample, dark_current, chosen.rsh, temperature)
    return DarkPair(chosen, is_manual, "；".join(notes), dark_current, lines)

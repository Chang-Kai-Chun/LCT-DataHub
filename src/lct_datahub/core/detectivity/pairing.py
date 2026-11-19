"""E 區：把 B（暗電流 B-4）、C（EQE）、D（noise）依 pixel 名稱配對（2026-11-19 定案）。

- pixel 名稱：第一個底線之前、不分大小寫（G1-2_330 K → G1-2；C、D 區的 G1-2 不變）
- 同一個 pixel 在某一區有多筆（例如 PD-QE 與明志都有 G6-1 的暗電流）時自動判斷儀器：
  暗電流與 noise 優先選兩者共有的儀器（明志配明志）；其餘取第一筆，並列出候選讓使用者選
- 使用者可對每個 pixel、每一區手動指定（名稱）或指定不使用（""），手動優先
- noise 只取與 D* 偏壓相同的組（n = 0 的組不列）
"""
import re
from dataclasses import dataclass, field
from enum import Enum

from lct_datahub.core.dark_current.extract import DarkExtract
from lct_datahub.core.dark_current.types import ExtractBias
from lct_datahub.core.detectivity.compute import PixelInput
from lct_datahub.core.eqe.types import EqeCurve
from lct_datahub.core.noise.pairing import extract_bias, pixel_key
from lct_datahub.core.noise.spectrum import value_at
from lct_datahub.core.noise.types import NoiseGroup

NOT_USED = ""  # 手動指定「不使用」


class SourceKind(Enum):
    """資料來源（value 為 API 與設定的鍵）。"""

    DARK = "dark"  # B 區
    EQE = "eqe"  # C 區
    NOISE = "noise"  # D 區


@dataclass(frozen=True)
class Candidate:
    """某一區的一筆候選：名稱與儀器。"""

    name: str
    instrument: str


@dataclass(frozen=True, eq=False)
class PixelPairing:
    """一個 pixel 的配對結果。"""

    pixel: str
    dark: DarkExtract | None
    eqe: EqeCurve | None
    noise: NoiseGroup | None
    noise_name: str | None  # noise 組的顯示名稱
    candidates: dict[SourceKind, list[Candidate]]
    manual: set[SourceKind] = field(default_factory=set)  # 被手動指定的區

    def chosen(self, kind: SourceKind) -> str | None:
        """某一區選到的名稱（沒有為 None）。"""
        if kind is SourceKind.DARK:
            return self.dark.name if self.dark else None
        if kind is SourceKind.EQE:
            return self.eqe.name if self.eqe else None
        return self.noise_name

    def instrument(self, kind: SourceKind) -> str | None:
        """某一區選到的儀器（沒有為 None）。"""
        if kind is SourceKind.DARK:
            return self.dark.instrument.value if self.dark else None
        if kind is SourceKind.EQE:
            return self.eqe.instrument.value if self.eqe else None
        return self.noise.instrument.value if self.noise else None

    def chosen_text(self, kind: str) -> str:
        """Excel 用的「名稱 (儀器)」；沒有為空白。kind 為 SourceKind 的 value。"""
        source = SourceKind(kind)
        name = self.chosen(source)
        return f"{name} ({self.instrument(source)})" if name else ""


def _natural(text: str) -> list:
    """自然排序鍵。"""
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text)]


def pair_pixels(
    bias: float,
    extracts: list[DarkExtract],
    curves: list[EqeCurve],
    groups: list[tuple[str, NoiseGroup]],
    overrides: dict[str, dict[str, str]] | None = None,
) -> list[PixelPairing]:
    """依 pixel 名稱配對三區；groups 為 (顯示名稱, noise 組)；overrides 為 {pixel: {區: 名稱或 ""}}。"""
    overrides = overrides or {}
    groups = [(n, g) for n, g in groups if g.n > 0 and abs(g.bias - bias) < 1e-9]
    pixels = {pixel_key(e.name) for e in extracts} | {pixel_key(c.name) for c in curves} | {g.sample for _, g in groups}
    result = []
    for pixel in sorted(pixels, key=_natural):
        darks = [e for e in extracts if pixel_key(e.name) == pixel]
        eqes = [c for c in curves if pixel_key(c.name) == pixel]
        noises = [(n, g) for n, g in groups if g.sample == pixel]
        candidates = {
            SourceKind.DARK: [Candidate(e.name, e.instrument.value) for e in darks],
            SourceKind.EQE: [Candidate(c.name, c.instrument.value) for c in eqes],
            SourceKind.NOISE: [Candidate(n, g.instrument.value) for n, g in noises],
        }
        # 自動：暗電流與 noise 優先選兩者共有的儀器
        common = [e.instrument.value for e in darks if e.instrument.value in {g.instrument.value for _, g in noises}]
        dark = next((e for e in darks if common and e.instrument.value == common[0]), darks[0] if darks else None)
        noise = next(((n, g) for n, g in noises if dark and g.instrument.value == dark.instrument.value),
                     noises[0] if noises else None)
        eqe = eqes[0] if eqes else None
        # 手動指定
        manual: set[SourceKind] = set()
        chosen = overrides.get(pixel, {})
        if SourceKind.DARK.value in chosen:
            manual.add(SourceKind.DARK)
            dark = next((e for e in darks if e.name == chosen[SourceKind.DARK.value]), None)
        if SourceKind.EQE.value in chosen:
            manual.add(SourceKind.EQE)
            eqe = next((c for c in eqes if c.name == chosen[SourceKind.EQE.value]), None)
        if SourceKind.NOISE.value in chosen:
            manual.add(SourceKind.NOISE)
            noise = next(((n, g) for n, g in noises if n == chosen[SourceKind.NOISE.value]), None)
        result.append(PixelPairing(
            pixel=pixel, dark=dark, eqe=eqe, noise=noise[1] if noise else None,
            noise_name=noise[0] if noise else None, candidates=candidates, manual=manual,
        ))
    return result


def shot_current(dark: DarkExtract, bias: float) -> float | None:
    """Shot 用的暗電流：0 V 用曲線最低點的 |I|；其他偏壓用 B-4 該偏壓的 Id（不在 B-4 的偏壓為 None）。"""
    if abs(bias) < 1e-9:
        return dark.id_min
    matched = extract_bias(bias)
    return dark.id.get(matched) if matched is not None else None


def to_input(pairing: PixelPairing, bias: float) -> PixelInput:
    """配對結果轉成 D* 的輸入。"""
    dark, group = pairing.dark, pairing.noise
    return PixelInput(
        pixel=pairing.pixel, bias=bias, eqe=pairing.eqe,
        area=dark.area if dark else None,
        noise=value_at(group.freq, group.mean) if group is not None and group.mean is not None else None,
        noise_bias=group.bias if group is not None else None,
        dark_current=shot_current(dark, bias) if dark else None,
        rsh=dark.rsh if dark else None,
    )


SUPPORTED_BIASES = [b.value for b in ExtractBias]  # E 區可選的偏壓（與 B-4 相同）

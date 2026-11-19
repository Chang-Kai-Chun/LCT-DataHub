"""D-1：依樣品＋偏壓分組，做 n 次功率平均（2026-11-19 定案）。

- 分組鍵：樣品（不分大小寫）、偏壓、儀器；同一組內量測設定（點數、取樣間隔）不同就不合併，分成多組並提示
- 組內有幾個檔，n 就是幾；沒有次數標記的檔一樣算一次（例如 PD-QE 只量一次）
- 溢位、削平的檔自動排除並記錄原因，n 跟著減少
- 未穩定的檔預設只警告、仍納入平均（2026-11-19 改：衰減主要影響 0.5 Hz 以下，D* 用的 1 Hz 幾乎不受影響）
"""
import re
from collections import Counter

import numpy as np

from lct_datahub.core.noise.anomaly import detect_anomaly
from lct_datahub.core.noise.spectrum import noise_density
from lct_datahub.core.noise.types import (
    BiasSource, Exclusion, NoiseAnomaly, NoiseDefinition, NoiseGroup, NoiseRecord,
)

_DIGITS = re.compile(r"(\d+)")
_INTERVAL_DECIMALS = 9  # 比較取樣間隔時四捨五入的位數


def _natural_key(text: str) -> list:
    """自然排序用的鍵（G2 排在 G10 前面）。"""
    return [int(part) if part.isdigit() else part for part in _DIGITS.split(text)]


def _settings(record: NoiseRecord) -> tuple[int, float]:
    """量測設定：(點數, 取樣間隔)；兩者都相同才能逐點平均。"""
    return record.points, round(record.interval, _INTERVAL_DECIMALS)


def _run_order(record: NoiseRecord) -> tuple:
    """組內排序：有次數的依次數，沒有的排後面再依檔名。"""
    return (record.run is None, record.run or 0, record.source)


def _notes(records: list[NoiseRecord]) -> list[str]:
    """組內提醒：偏壓為預設、檔名與檔內偏壓不同、次數重複。"""
    notes = []
    if any(r.bias_source is BiasSource.DEFAULT for r in records):
        notes.append("檔名沒有偏壓，預設為 0 V")
    for r in records:
        if r.header_bias is not None and abs(r.header_bias - r.bias) > 1e-9:
            notes.append(f"{r.source}：檔名偏壓 {r.bias:g} V 與檔內 Volt Level {r.header_bias:g} V 不同")
    counts = Counter(r.run for r in records if r.run is not None)
    for run, count in sorted(counts.items()):
        if count > 1:
            notes.append(f"第 {run} 次量測有 {count} 個檔")
    return notes


def _build(records: list[NoiseRecord], definition: NoiseDefinition, exclude_unstable: bool,
           split: bool) -> NoiseGroup:
    """建立一組（同樣品、偏壓、儀器、量測設定）：偵測異常、計算每個檔的雜訊密度。"""
    records = sorted(records, key=_run_order)
    first = records[0]
    members: list[NoiseRecord] = []
    runs: list[np.ndarray] = []
    excluded: list[Exclusion] = []
    notes = _notes(records)
    freq = np.fft.rfftfreq(first.points, first.interval)[1:first.points // 2]
    for record in records:
        problem = detect_anomaly(record)
        if problem is not None:
            if problem.anomaly is not NoiseAnomaly.UNSTABLE or exclude_unstable:
                excluded.append(problem)
                continue
            notes.append(f"{record.source}：{problem.anomaly.value}（{problem.detail}），仍納入平均")
        freq, density = noise_density(record, definition)
        members.append(record)
        runs.append(density)
    if split:
        notes.append(f"同一樣品與偏壓有不同的量測設定，已分開計算（本組每次 {first.duration:g} s）")
    if not members:
        notes.append("全部檔案都被排除，沒有可用的數據")
    return NoiseGroup(
        sample=first.sample, bias=first.bias, bias_source=first.bias_source, instrument=first.instrument,
        definition=definition, points=first.points, interval=first.interval, members=members,
        excluded=excluded, freq=freq, runs=runs, notes=notes, split=split,
    )


def build_groups(records: list[NoiseRecord], definition: NoiseDefinition = NoiseDefinition.STANDARD,
                 exclude_unstable: bool = False) -> list[NoiseGroup]:
    """依樣品＋偏壓＋儀器分組並平均；量測設定不同的分成不同組。

    exclude_unstable：未穩定的檔是否排除（預設 False：只在 notes 警告並納入平均；True 時排除）。
    回傳依樣品自然排序、同樣品偏壓由高到低（0 V 在 −0.1 V 前）。
    """
    buckets: dict[tuple, list[NoiseRecord]] = {}
    for record in records:
        buckets.setdefault((record.sample, record.bias, record.instrument), []).append(record)
    groups = []
    for members in buckets.values():
        by_settings: dict[tuple, list[NoiseRecord]] = {}
        for record in members:
            by_settings.setdefault(_settings(record), []).append(record)
        split = len(by_settings) > 1
        for subset in by_settings.values():
            groups.append(_build(subset, definition, exclude_unstable, split))
    return sorted(groups, key=lambda g: (_natural_key(g.sample), -g.bias, g.instrument.value, g.duration))

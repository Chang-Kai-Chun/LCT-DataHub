"""D-1：讀取 noise 檔的時域電流（明志、PD-QE），儀器算好的頻譜一律不使用。

依內容判斷儀器（第一列第一格）：
- 明志：`[PARM]`；第 A、B 欄為量測參數（含 `Volt Level (V)`），第 C、D 欄為時間與電流
- PD-QE：`Time (s)`；第 A、B 欄為時間與電流
兩者都是逗號分隔、cp950（Big5）編碼；時間欄空白的列（頻譜比時域長或短）略過。
"""
import csv
import io
from pathlib import Path

import numpy as np

from lct_datahub.core.noise.filename import parse_noise_name
from lct_datahub.core.noise.types import NoiseFailure, NoiseFileError, NoiseInstrument, NoiseRecord

MIN_POINTS = 16  # 少於這個點數無法做有意義的 FFT
INTERVAL_TOLERANCE = 1e-3  # 取樣間隔的相對變動容許值（超過視為時間間隔不固定）
NOISE_SUFFIXES = {".csv"}
_ENCODINGS = ("utf-8-sig", "cp950", "latin-1")  # 依序嘗試
_MINGCHI_MARK = "[PARM]"
_PDQE_MARK = "time (s)"
_VOLT_LEVEL = "volt level (v)"
# 各儀器的（時間欄, 電流欄）位置（0 起算）
_COLUMNS = {NoiseInstrument.MINGCHI: (2, 3), NoiseInstrument.PDQE: (0, 1)}


def is_noise_file(name: str) -> bool:
    """可處理的 noise 檔：csv，且不是 Office 暫存檔。"""
    return Path(name).suffix.lower() in NOISE_SUFFIXES and not name.startswith("~$")


def _decode(raw: bytes) -> str:
    """依序嘗試 utf-8、cp950，最後以 latin-1 解碼（latin-1 不會失敗；只影響表頭文字）。"""
    for enc in _ENCODINGS:
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise AssertionError("latin-1 不會解碼失敗")  # pragma: no cover


def _instrument(first_cell: str, filename: str) -> NoiseInstrument:
    """依第一列第一格判斷儀器；都不是就拋出 BAD_FORMAT。"""
    cell = first_cell.strip()
    if cell.upper() == _MINGCHI_MARK:
        return NoiseInstrument.MINGCHI
    if cell.lower() == _PDQE_MARK:
        return NoiseInstrument.PDQE
    raise NoiseFileError(filename, NoiseFailure.BAD_FORMAT, "明志 [PARM] 或 PD-QE Time (s) 表頭", cell or "空白")


def _header_bias(rows: list[list[str]]) -> float | None:
    """明志參數表的 Volt Level (V)；找不到或不是數字為 None。"""
    for row in rows:
        if len(row) >= 2 and row[0].strip().lower() == _VOLT_LEVEL:
            try:
                return float(row[1]) + 0.0
            except ValueError:
                return None
    return None


def _series(rows: list[list[str]], t_col: int, i_col: int) -> tuple[np.ndarray, np.ndarray]:
    """取出時間與電流兩欄（兩欄都是數字的列才算；時間空白的列略過）。"""
    times, currents = [], []
    for row in rows:
        if len(row) <= max(t_col, i_col) or not row[t_col].strip():
            continue
        try:
            t, i = float(row[t_col]), float(row[i_col])
        except ValueError:
            continue
        times.append(t)
        currents.append(i)
    return np.array(times, dtype=float), np.array(currents, dtype=float)


def parse_noise_text(text: str, filename: str) -> NoiseRecord:
    """解析 noise 檔內容（檔名用來讀出樣品、次數與偏壓）。"""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or not rows[0]:
        raise NoiseFileError(filename, NoiseFailure.BAD_FORMAT, "逗號分隔的 noise 檔", "空白檔案")
    instrument = _instrument(rows[0][0], filename)
    t_col, i_col = _COLUMNS[instrument]
    time, current = _series(rows[1:], t_col, i_col)
    if len(time) < MIN_POINTS:
        raise NoiseFileError(filename, NoiseFailure.TOO_FEW_POINTS, f"至少 {MIN_POINTS} 點", f"{len(time)} 點")
    steps = np.diff(time)
    step = float(np.median(steps))
    if step <= 0 or np.max(np.abs(steps - step)) > INTERVAL_TOLERANCE * step:
        raise NoiseFileError(
            filename, NoiseFailure.IRREGULAR_TIME, "固定的取樣間隔", f"{steps.min():.3g}～{steps.max():.3g} s",
        )
    name = parse_noise_name(filename)
    return NoiseRecord(
        source=filename, instrument=instrument, sample=name.sample, bias=name.bias, bias_source=name.bias_source,
        run=name.run, time=time, current=current,
        header_bias=_header_bias(rows) if instrument is NoiseInstrument.MINGCHI else None,
    )


def read_noise_file(path: Path) -> NoiseRecord:
    """讀取單一 noise 檔。"""
    path = Path(path)
    return parse_noise_text(_decode(path.read_bytes()), path.name)


def read_noise_files(paths: list[Path]) -> list[NoiseRecord]:
    """讀取多個 noise 檔（依傳入順序）。"""
    return [read_noise_file(p) for p in paths]


def list_noise_files(folder: Path) -> list[Path]:
    """列出資料夾內可處理的 noise 檔（規則見 is_noise_file），依檔名排序。"""
    return sorted(p for p in Path(folder).iterdir() if p.is_file() and is_noise_file(p.name))

"""D 區 Noise（filename、reader、spectrum、anomaly、group、export、reference、plot）的測試。"""
import csv
import dataclasses
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from lct_datahub.core.noise.anomaly import (
    CLIP_MIN_COUNT, UNSTABLE_RATIO, clipped_count, detect_anomaly, instability, overflow_count,
)
from lct_datahub.core.noise.export import NoiseSheet, column_names, mean_frame, summary_frame, write_noise_excel
from lct_datahub.core.noise.filename import parse_noise_name
from lct_datahub.core.noise.group import build_groups
from lct_datahub.core.noise.reader import (
    is_noise_file, list_noise_files, parse_noise_text, read_noise_file, read_noise_files,
)
from lct_datahub.core.noise.reference import (
    ReferenceKind, reference_lines, shot_noise, thermal_noise,
)
from lct_datahub.core.noise.spectrum import amplitude, noise_density, to_density, value_at
from lct_datahub.core.noise.types import (
    BiasSource, NoiseAnomaly, NoiseDefinition, NoiseFailure, NoiseFileError, NoiseInstrument, NoiseRecord,
)
from lct_datahub.core.plotting import figure_to_png, plot_noise

ROOT = Path(__file__).resolve().parent.parent / "test_for_develop" / "Noise_test_file"
MINGCHI_DIR = ROOT / "mingchi"
needs_pdqe = pytest.mark.skipif(not (ROOT / "G6-1.csv").exists(), reason="沒有 PD-QE noise 測試檔")
needs_mingchi = pytest.mark.skipif(not MINGCHI_DIR.exists(), reason="沒有明志 noise 測試檔")
PNG_MAGIC = b"\x89PNG"


def _record(current: np.ndarray, interval: float = 0.005, source: str = "S 1st 0V.csv", **kwargs) -> NoiseRecord:
    """測試用的合成檔。"""
    values = dict(
        source=source, instrument=NoiseInstrument.MINGCHI, sample="S", bias=0.0, bias_source=BiasSource.FILENAME,
        run=1, time=np.arange(len(current)) * interval, current=np.asarray(current, dtype=float),
    )
    values.update(kwargs)
    return NoiseRecord(**values)


def _white(density: float, n: int = 2000, interval: float = 0.005, seed: int = 0) -> np.ndarray:
    """已知雜訊密度（A/√Hz）的白雜訊：RMS = 密度 × √(取樣率 ÷ 2)。"""
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, density * np.sqrt(0.5 / interval), n)


def _mingchi_files() -> list[Path]:
    """明志測試檔（不含背景檔）。"""
    return [p for p in list_noise_files(MINGCHI_DIR) if "BACKGROUND" not in p.name.upper()]


# ---------- 檔名 ----------
@pytest.mark.parametrize(
    ("name", "sample", "run", "bias", "source"),
    [
        ("G1-2 1st -0.1V.csv", "G1-2", 1, -0.1, BiasSource.FILENAME),
        ("g1-2 3rd 0v.csv", "G1-2", 3, 0.0, BiasSource.FILENAME),
        ("G1-2 3nd -0.1V.csv", "G1-2", 3, -0.1, BiasSource.FILENAME),  # 3nd 只讀數字
        ("G6-1.csv", "G6-1", None, 0.0, BiasSource.DEFAULT),  # PD-QE：沒有偏壓 → 預設 0 V
        ("G6-1_-0.1V.csv", "G6-1", None, -0.1, BiasSource.FILENAME),
        ("EMPTY 1st 0V 1E-9.csv", "EMPTY", 1, 0.0, BiasSource.FILENAME),  # 檔位標記略過
        ("G1 REF-1 2nd -0.2V.csv", "G1 REF-1", 2, -0.2, BiasSource.FILENAME),  # 樣品名可含空白
        ("G11-1 -0.1V 2nd.csv", "G11-1", 2, -0.1, BiasSource.FILENAME),  # 順序不限
    ],
)
def test_parse_noise_name(name, sample, run, bias, source):
    """樣品（大寫）、次數、偏壓與偏壓來源。"""
    parsed = parse_noise_name(name)
    assert (parsed.sample, parsed.run, parsed.bias, parsed.bias_source) == (sample, run, bias, source)


def test_is_noise_file():
    """只接受 csv，略過暫存檔與其他副檔名。"""
    assert is_noise_file("a.csv") and is_noise_file("A.CSV")
    assert not is_noise_file("~$a.csv") and not is_noise_file("a.jpg") and not is_noise_file("a.xlsx")


# ---------- 讀檔 ----------
@needs_mingchi
def test_read_mingchi_file():
    """明志：時間與電流在第 C、D 欄；參數表的 Volt Level 讀成 header_bias。"""
    record = read_noise_file(MINGCHI_DIR / "G1-2 1st -0.1V.csv")
    assert record.instrument is NoiseInstrument.MINGCHI
    assert (record.sample, record.run, record.bias) == ("G1-2", 1, -0.1)
    assert record.header_bias == -0.1
    assert record.points == 2000 and record.interval == pytest.approx(0.005)
    assert record.duration == pytest.approx(10.0) and record.resolution == pytest.approx(0.1)


@needs_pdqe
def test_read_pdqe_file():
    """PD-QE：時間與電流在第 A、B 欄；檔名沒有偏壓預設 0 V；沒有 header_bias。"""
    record = read_noise_file(ROOT / "G6-1.csv")
    assert record.instrument is NoiseInstrument.PDQE
    assert (record.sample, record.run, record.bias, record.bias_source) == ("G6-1", None, 0.0, BiasSource.DEFAULT)
    assert record.header_bias is None and record.points == 2000 and record.interval == pytest.approx(0.005)
    assert read_noise_file(ROOT / "G6-1_-0.1V.csv").bias == -0.1


@needs_mingchi
def test_read_background_file_is_bad_format():
    """只有 FFT 結果的背景檔（Hz - Plot 0）不支援：BAD_FORMAT。"""
    with pytest.raises(NoiseFileError) as e:
        read_noise_file(MINGCHI_DIR / "MINGCHI_BACKGROUND2.csv")
    assert e.value.reason is NoiseFailure.BAD_FORMAT


def test_reader_too_few_points_and_irregular_time():
    """點數太少：TOO_FEW_POINTS；時間間隔不固定：IRREGULAR_TIME。"""
    short = "Time (s),Current\n" + "\n".join(f"{i * 0.005},{1e-9}" for i in range(5))
    with pytest.raises(NoiseFileError) as e:
        parse_noise_text(short, "x.csv")
    assert e.value.reason is NoiseFailure.TOO_FEW_POINTS
    times = np.cumsum(np.r_[0.005, np.full(30, 0.005), 0.02, np.full(30, 0.005)])
    irregular = "Time (s),Current\n" + "\n".join(f"{t},{1e-9}" for t in times)
    with pytest.raises(NoiseFileError) as e:
        parse_noise_text(irregular, "x.csv")
    assert e.value.reason is NoiseFailure.IRREGULAR_TIME


def test_reader_skips_blank_time_rows():
    """時間欄空白的列（頻譜比時域長）略過。"""
    lines = ["Time (s),Current,Frequency (Hz),Noise"] + [f"{i * 0.005},{i * 1e-12},{i * 0.1},1" for i in range(20)]
    lines += [f",,{i * 0.1},1" for i in range(20, 30)]
    record = parse_noise_text("\n".join(lines), "S_-0.1V.csv")
    assert record.points == 20 and record.bias == -0.1


# ---------- 頻譜 ----------
def test_standard_definition_recovers_known_white_noise():
    """已知密度 1E-12 的白雜訊：標準定義（多次平均）還原到 1E-12，與量測時間無關。"""
    for n in (2000, 4000):
        powers = [noise_density(_record(_white(1e-12, n=n, seed=s)))[1] ** 2 for s in range(200)]
        assert np.sqrt(np.mean(powers)) == pytest.approx(1e-12, rel=0.02)


def test_parseval_holds_for_standard_definition():
    """Parseval：標準定義 Σ i_n² × Δf ≈ 時域變異數；儀器定義（÷√f）明顯不符。"""
    record = _record(_white(3e-12, seed=7))
    freq, std = noise_density(record)
    _, inst = noise_density(record, NoiseDefinition.INSTRUMENT)
    variance = np.var(record.current)
    assert np.sum(std ** 2) * record.resolution == pytest.approx(variance, rel=0.03)
    assert np.sum(inst ** 2) * record.resolution < 0.2 * variance


def test_amplitude_of_sine_and_dc_removed():
    """整數格的正弦波：峰值振幅等於正弦振幅；平均電流（直流）不影響 0.1 Hz。"""
    t = np.arange(2000) * 0.005
    freq, amp = amplitude(5e-11 * np.sin(2 * np.pi * 3.0 * t) + 2e-8, 0.005)
    assert freq[0] == pytest.approx(0.1) and freq[-1] == pytest.approx(99.9)
    assert amp[np.argmin(np.abs(freq - 3.0))] == pytest.approx(5e-11, rel=1e-6)
    assert amp[0] < 1e-15  # 2E-8 的直流沒有洩漏到 0.1 Hz


def test_to_density_definitions():
    """標準：a ÷ √(2×1.5×Δf)；儀器：a ÷ √f；1 Hz 時兩者相差 √0.3 倍。"""
    freq, amp = np.array([1.0, 4.0]), np.array([2e-12, 2e-12])
    std = to_density(freq, amp, 0.1, NoiseDefinition.STANDARD)
    inst = to_density(freq, amp, 0.1, NoiseDefinition.INSTRUMENT)
    assert std == pytest.approx(amp / np.sqrt(0.3))
    assert inst == pytest.approx([2e-12, 1e-12])
    assert std[0] / inst[0] == pytest.approx(1 / np.sqrt(0.3))


@needs_mingchi
def test_matches_instrument_columns():
    """明志檔：振幅與儀器 G 欄、儀器定義與 I 欄一致（略過 0.1 Hz）。

    檔案只到 1E-12，容許差取 ±1E-12 與 0.5% 的較大者（20、60 Hz 干擾峰旁的少數點，
    受時域電流捨入影響有 0.2～0.5% 的相對誤差）。
    """
    path = MINGCHI_DIR / "G1-1 1st -0.1V.csv"
    record = read_noise_file(path)
    with open(path, encoding="cp950", errors="replace") as fh:
        rows = [r for r in csv.reader(fh)][1:]
    file_amp = np.array([float(r[6]) for r in rows if len(r) > 8 and r[7]])[1:]  # 去掉 0 Hz
    file_inst = np.array([float(r[8]) for r in rows if len(r) > 8 and r[7]])[1:]
    _, amp = amplitude(record.current, record.interval)
    freq, inst = noise_density(record, NoiseDefinition.INSTRUMENT)
    k = slice(1, len(amp))  # 0.1 Hz 受直流（已扣除）影響，不比較

    def close(ours: np.ndarray, theirs: np.ndarray) -> float:
        """一致的比例。"""
        return float(np.mean(np.abs(ours - theirs) <= np.maximum(1.01e-12, 5e-3 * np.abs(theirs))))

    assert close(amp[k], file_amp[: len(amp)][k]) > 0.99
    assert close(inst[k], file_inst[: len(inst)][k]) > 0.99


def test_value_at():
    """取最接近的頻率點；超出範圍為 None。"""
    freq = np.arange(1, 1000) * 0.1
    assert value_at(freq, freq * 2) == pytest.approx(2.0)
    assert value_at(np.arange(1, 9) * 0.1, np.ones(8)) is None  # 只到 0.8 Hz


# ---------- 異常 ----------
def test_overflow_detected():
    """溢位代碼 9.91E+37：排除。"""
    current = _white(1e-12)
    current[[3, 900]] = 9.91e37
    assert overflow_count(current) == 2
    problem = detect_anomaly(_record(current))
    assert problem is not None and problem.anomaly is NoiseAnomaly.OVERFLOW


def test_clipping_detected():
    """超過量程被削平：排除；正常數據的極值只出現一次。"""
    current = 1e-8 * np.sin(2 * np.pi * 60.3 * np.arange(2000) * 0.005) + _white(1e-12)
    assert clipped_count(current) < CLIP_MIN_COUNT and detect_anomaly(_record(current)) is None
    problem = detect_anomaly(_record(np.clip(current, -8e-9, 8e-9)))
    assert problem is not None and problem.anomaly is NoiseAnomaly.CLIPPED


def test_unstable_detected():
    """開頭衰減（加偏壓後的暫態）：排除；穩定的白雜訊不會。"""
    t = np.arange(2000) * 0.005
    stable = _white(1e-13, seed=3) - 4e-11
    assert instability(stable) < UNSTABLE_RATIO and detect_anomaly(_record(stable)) is None
    problem = detect_anomaly(_record(stable - 2e-10 * np.exp(-t / 0.7)))
    assert problem is not None and problem.anomaly is NoiseAnomaly.UNSTABLE


# ---------- 分組與平均 ----------
@needs_mingchi
def test_groups_from_mingchi_files():
    """明志 36 檔：6 顆 × 2 偏壓，每組 n = 3（3nd 也算第 3 次；大小寫不同的 g1-2 同一組）。"""
    groups = build_groups(read_noise_files(_mingchi_files()))
    assert len(groups) == 12 and all(g.n == 3 for g in groups)
    assert [(g.sample, g.bias) for g in groups[:4]] == [("G1-1", 0.0), ("G1-1", -0.1), ("G1-2", 0.0), ("G1-2", -0.1)]
    g12 = next(g for g in groups if g.sample == "G1-2" and g.bias == -0.1)
    assert [r.run for r in g12.members] == [1, 2, 3]
    assert value_at(g12.freq, g12.mean) == pytest.approx(4.59e-11, rel=0.01)


@needs_pdqe
def test_groups_n1_for_pdqe():
    """PD-QE 每個樣品、偏壓只有一個檔：n = 1，平均就是該次，沒有範圍帶。"""
    groups = build_groups(read_noise_files(list_noise_files(ROOT)))
    assert len(groups) == 12 and all(g.n == 1 for g in groups)
    g = groups[0]
    assert np.array_equal(g.mean, g.runs[0]) and np.array_equal(g.low, g.high)
    assert any("預設為 0 V" in note for note in g.notes)  # G1-2.csv 沒有偏壓


def test_power_average():
    """功率平均：先平方、平均後開根號。"""
    records = [_record(_white(1e-12, seed=s), source=f"S {s}st 0V.csv", run=s) for s in (1, 2)]
    [group] = build_groups(records)
    expected = np.sqrt((group.runs[0] ** 2 + group.runs[1] ** 2) / 2)
    assert group.n == 2 and np.allclose(group.mean, expected)
    assert np.all(group.low <= group.mean) and np.all(group.mean <= group.high)


def test_different_settings_not_merged():
    """同樣品同偏壓、量測時間不同：不合併，分成兩組並提示。"""
    records = [
        _record(_white(1e-12, n=2000, seed=1), source="S 1st 0V.csv"),
        _record(_white(1e-12, n=4000, seed=2), source="S 2nd 0V.csv", run=2),
    ]
    groups = build_groups(records)
    assert len(groups) == 2 and all(g.n == 1 and g.split for g in groups)
    assert sorted(g.duration for g in groups) == pytest.approx([10.0, 20.0])
    assert all("不同的量測設定" in " ".join(g.notes) for g in groups)
    assert groups[0].label != groups[1].label


def test_anomalies_excluded_and_reported():
    """異常檔自動排除並記錄原因；n 跟著減少；全部排除時 n = 0、沒有平均。"""
    bad = _white(1e-12, seed=9)
    bad[10] = 9.91e37
    records = [_record(_white(1e-12, seed=1)), _record(bad, source="S 2nd 0V.csv", run=2)]
    [group] = build_groups(records)
    assert group.n == 1 and [e.source for e in group.excluded] == ["S 2nd 0V.csv"]
    assert group.excluded[0].anomaly is NoiseAnomaly.OVERFLOW
    [empty] = build_groups([records[1]])
    assert empty.n == 0 and empty.mean is None and "全部檔案都被排除" in " ".join(empty.notes)


def test_unstable_kept_with_warning_by_default():
    """預設：未穩定的檔納入平均，只在 notes 警告；exclude_unstable=True 時排除。"""
    t = np.arange(2000) * 0.005
    drifting = _white(1e-13, seed=3) - 2e-10 * np.exp(-t / 0.7)
    [kept] = build_groups([_record(drifting)])
    [excluded] = build_groups([_record(drifting)], exclude_unstable=True)
    assert kept.n == 1 and kept.excluded == [] and "電流未穩定" in " ".join(kept.notes)
    assert excluded.n == 0 and excluded.excluded[0].anomaly is NoiseAnomaly.UNSTABLE


@needs_mingchi
def test_mingchi_unstable_files_kept_by_default():
    """明志 −0.1 V 有 9 個檔開頭仍在衰減：預設全部納入（n = 3）並警告；排除時 G10-1、G11-1 變成 n = 0。"""
    records = read_noise_files(_mingchi_files())
    kept = {(g.sample, g.bias): g for g in build_groups(records)}
    strict = {(g.sample, g.bias): g for g in build_groups(records, exclude_unstable=True)}
    assert all(g.n == 3 and not g.excluded for g in kept.values())
    warned = [key for key, g in kept.items() if "電流未穩定" in " ".join(g.notes)]
    assert sorted(warned) == [("G10-1", -0.1), ("G11-1", -0.1), ("G14-1", -0.1), ("G6-1", -0.1)]
    assert strict[("G10-1", -0.1)].n == 0 and strict[("G11-1", -0.1)].n == 0


def test_notes_for_header_bias_and_duplicate_runs():
    """檔名偏壓與檔內 Volt Level 不同、次數重複：提示。"""
    records = [
        _record(_white(1e-12, seed=1), header_bias=-0.1),
        _record(_white(1e-12, seed=2), source="S 1st 0V (2).csv"),
    ]
    [group] = build_groups(records)
    text = " ".join(group.notes)
    assert "Volt Level -0.1 V" in text and "第 1 次量測有 2 個檔" in text


# ---------- Excel ----------
def test_write_noise_excel(tmp_path):
    """Summary、Mean、Runs；有被排除的檔才有 Excluded；Summary 的 1 Hz 值與平均一致。"""
    bad = _white(1e-12, seed=9)
    bad[0] = 9.91e37
    records = [
        _record(_white(1e-12, seed=1)), _record(_white(1e-12, seed=2), source="S 2nd 0V.csv", run=2),
        _record(bad, source="S 3rd 0V.csv", run=3),
        _record(_white(2e-12, seed=4), source="T 1st -0.1V.csv", sample="T", bias=-0.1),
    ]
    groups = build_groups(records)
    path = tmp_path / "Noise.xlsx"
    write_noise_excel(path, groups)
    book = pd.read_excel(path, sheet_name=None)
    assert list(book) == [s.value for s in NoiseSheet]
    summary = book[NoiseSheet.SUMMARY.value]
    assert list(summary["n"]) == [2, 1] and summary["Excluded files"][0].startswith("S 3rd 0V.csv")
    assert summary["Noise @ 1 Hz (A/Hz^0.5)"][0] == pytest.approx(value_at(groups[0].freq, groups[0].mean))
    assert list(book[NoiseSheet.MEAN.value].columns) == ["Frequency (Hz)", "S 0V (n=2)", "T -0.1V (n=1)"]
    assert len(book[NoiseSheet.RUNS.value].columns) == 1 + 3
    clean = tmp_path / "Clean.xlsx"
    write_noise_excel(clean, build_groups(records[:2]))
    assert NoiseSheet.EXCLUDED.value not in pd.read_excel(clean, sheet_name=None)


def test_column_names_disambiguate_instruments():
    """同樣品同偏壓、不同儀器：欄名加上儀器。"""
    records = [_record(_white(1e-12, seed=1)), _record(_white(1e-12, seed=2), instrument=NoiseInstrument.PDQE)]
    groups = build_groups(records)
    assert sorted(column_names(groups)) == ["S 0V (n=1) [PD-QE]", "S 0V (n=1) [明志]"]
    assert list(mean_frame(groups).columns)[1:] == column_names(groups)
    assert len(summary_frame(groups)) == 2


# ---------- 參考線 ----------
def test_reference_lines():
    """Shot √(2qI)、Thermal √(4kT/Rsh)；兩者都有時加總和；Rsh ≤ 0 不畫。"""
    assert shot_noise(-1e-9) == pytest.approx(1.79e-14, rel=1e-2)
    assert thermal_noise(1e6) == pytest.approx(1.287e-13, rel=1e-3)
    lines = reference_lines("G1-2", 8.2e-10, 2.57e8)
    assert [l.kind for l in lines] == [ReferenceKind.SHOT, ReferenceKind.THERMAL, ReferenceKind.TOTAL]
    assert lines[2].value == pytest.approx(np.hypot(lines[0].value, lines[1].value))
    assert lines[0].label == "G1-2 Shot"
    assert [l.kind for l in reference_lines("A", None, 1e9)] == [ReferenceKind.THERMAL]
    assert reference_lines("A", None, 0.0) == []
    with pytest.raises(ValueError):
        thermal_noise(0.0)


# ---------- 繪圖 ----------
def test_plot_noise():
    """雙對數圖輸出 PNG；n = 0 的組不畫；對數軸下限須大於 0。"""
    records = [_record(_white(1e-12, seed=s), source=f"S {s}st 0V.csv", run=s) for s in (1, 2)]
    bad = _white(1e-12, seed=9)
    bad[0] = 9.91e37
    groups = build_groups(records) + build_groups([_record(bad, sample="Z", source="Z 1st 0V.csv")])
    fig = plot_noise(groups, reference_lines("S", 1e-9, 1e9), y_range=(1e-15, 1e-10))
    assert figure_to_png(fig).startswith(PNG_MAGIC)
    labels = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
    assert labels[0] == "S 0V (n=2)" and "Z" not in " ".join(labels)
    with pytest.raises(ValueError):
        plot_noise(groups, y_range=(0, 1))
    with pytest.raises(ValueError):
        plot_noise(groups, x_range=(10, 1))

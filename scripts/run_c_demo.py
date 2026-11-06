"""C 區實測：讀 EQE_test_file（新型 PD-QE 與舊型五樓），輸出 Excel 到 Result/C。"""
from pathlib import Path

from lct_datahub.core.eqe.export import write_eqe_excels
from lct_datahub.core.eqe.integrate import list_eqe_files, read_eqe_files
from lct_datahub.core.eqe.select import curve_names, select_eqe_curves
from lct_datahub.core.eqe.types import EqeInstrument
from lct_datahub.core.plotting import figure_to_png, plot_eqe, plot_rplot

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "EQE_test_file"  # 原始資料
OUT = ROOT / "Result" / "C"  # 輸出資料夾
OUT.mkdir(parents=True, exist_ok=True)

files = list_eqe_files(RAW)
print("檔案：", [f.name for f in files])
curves = read_eqe_files(files)
for c in curves[:3] + curves[-3:]:
    print(f"{c.name:8s} {c.instrument.value}  {len(c.data)} 點  Jsc = {c.jsc:.3f} mA/cm^2")
print(f"共 {len(curves)} 個樣品")

try:
    for path in write_eqe_excels(OUT, curves):
        print("已輸出：", path.name)
except PermissionError:
    print("Excel 無法覆寫（可能在 Excel 開著），請關閉後重跑")

# C-2、C-3 繪圖：單一樣品、PD-QE 前 5 個樣品疊圖、兩台儀器各取一個
names = curve_names(curves)
by_inst = {inst: [c.name for c in curves if c.instrument is inst] for inst in EqeInstrument}
pdqe_names = by_inst[EqeInstrument.PDQE] or names
groups = {
    "single": pdqe_names[:1],
    "pdqe_5": pdqe_names[:5],
    "mixed": [names[0] for names in by_inst.values() if names],
}
for tag, picked in groups.items():
    chosen = select_eqe_curves(curves, picked)
    (OUT / f"EQE_{tag}.png").write_bytes(figure_to_png(plot_eqe(chosen, x_range=(300, 1100))))
    (OUT / f"Rplot_{tag}.png").write_bytes(figure_to_png(plot_rplot(chosen, x_range=(300, 1100))))
    print(f"已輸出：EQE_{tag}.png、Rplot_{tag}.png（{picked}）")

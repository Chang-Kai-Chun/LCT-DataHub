"""B 區實測：讀 JD_test_file（PD-QE 與明志），輸出 Combined Excel 到 Result/B。"""
from pathlib import Path

from lct_datahub.core.area_check import check_areas
from lct_datahub.core.dark_current.export import write_dark_excels
from lct_datahub.core.dark_current.integrate import dark_areas, list_dark_files, read_dark_files
from lct_datahub.core.dark_current.shift import shift_curves
from lct_datahub.core.dark_current.select import select_dark_curves
from lct_datahub.core.dark_current.types import ShiftMode
from lct_datahub.core.plotting import figure_to_png, plot_dark_current

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "JD_test_file"  # 原始資料
OUT = ROOT / "Result" / "B"  # 輸出資料夾
OUT.mkdir(parents=True, exist_ok=True)

files = list_dark_files(RAW)
print("檔案：", [f.name for f in files])
curves = read_dark_files(files)
print(f"共 {len(curves)} 條曲線，被智慧截取的點數：{sum(c.removed_points for c in curves)}")

# 面積檢查：不一致時 UI 會請使用者確認
report = check_areas(dark_areas(curves))
print("面積 (cm^2)：", report.values, "一致" if report.is_uniform else "不一致")

# B-2：最低點偏移到 0 V（整條曲線平移，記錄偏移量）
original = curves
curves = shift_curves(curves, ShiftMode.SHIFT)
shifts = [c.shift for c in curves]
print(f"偏移量 (V)：最小 {min(shifts):+.3f}、最大 {max(shifts):+.3f}，被偏移 {sum(c.is_shifted for c in curves)} 條")

try:
    for path in write_dark_excels(OUT, curves):
        print("已輸出：", path.name)
except PermissionError:
    print("Excel 無法覆寫（可能在 Excel 開著），請關閉後重跑")

# B-3：暗電流圖。明志那條與 PD-QE 前幾條各畫一張偏移後、一張保持原始
names = [c.name for c in curves]
pick = [names[0], names[1], names[2], names[3], names[-1]]
for tag, source in (("shift", curves), ("original", original)):
    png = figure_to_png(plot_dark_current(select_dark_curves(source, pick)))
    (OUT / f"Dark_{tag}.png").write_bytes(png)
# 全部 PD-QE 曲線疊在一起（偏移後）
(OUT / "Dark_all.png").write_bytes(figure_to_png(plot_dark_current(curves)))

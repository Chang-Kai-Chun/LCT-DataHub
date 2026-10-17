"""A 區實測：讀 JV_test_file，輸出 ALL_Data.xlsx、Box 圖、JV 曲線圖到 Result/A。"""
from pathlib import Path

from lct_datahub.core.jv.box import box_data, build_box_table
from lct_datahub.core.jv.curve import select_curves
from lct_datahub.core.jv.export import write_excel
from lct_datahub.core.jv.grouping import group_auto, sample_list
from lct_datahub.core.jv.reader import list_jv_csv, read_jv_files
from lct_datahub.core.jv.types import Direction, DirectionMode, JVParam
from lct_datahub.core.plotting import figure_to_png, plot_box, plot_jv_curves

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "JV_test_file"  # 原始資料
OUT = ROOT / "Result" / "A"  # 輸出資料夾
OUT.mkdir(parents=True, exist_ok=True)

files = read_jv_files(list_jv_csv(RAW))
conditions = group_auto(sample_list(files))  # 自動分組：每 4 個樣品一組
for c in conditions:
    print(c.name, [str(s) for s in c.samples])

# 1. ALL_Data（參數 sheet 取 FW＋RV）
try:
    write_excel(OUT / "ALL_Data.xlsx", files, conditions, (Direction.FW, Direction.RV))
except PermissionError:
    print("ALL_Data.xlsx 無法覆寫（可能在 Excel 開著），請關閉後重跑；圖照常輸出")

# 2. Box 圖：每個參數一張，FW 與 FW＋RV 各一組
for mode in (DirectionMode.FW, DirectionMode.BOTH):
    table = build_box_table(files, conditions, mode)
    for param in JVParam:
        png = figure_to_png(plot_box(box_data(table, param), param))
        (OUT / f"Box_{param.name}_{mode.name}.png").write_bytes(png)

# 3. JV 曲線：全部樣品一張，再每個條件各一張（FW 實線、RV 虛線）
both = (Direction.FW, Direction.RV)
everyone = [s for c in conditions for s in c.samples]
(OUT / "JV_all.png").write_bytes(figure_to_png(plot_jv_curves(select_curves(files, everyone, both))))
for c in conditions:
    lines = select_curves(files, c.samples, both)
    (OUT / f"JV_{c.name.replace(' ', '_')}.png").write_bytes(figure_to_png(plot_jv_curves(lines)))

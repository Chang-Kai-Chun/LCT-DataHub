"""A-1：把整合結果寫成 Excel（sheet 順序：ALL_Data、各參數 sheet、每檔一個 sheet）。

ALL_Data 版面（沿用 V5，2026-10-16 確認）：
  - 第 1 列表頭，每個樣品區塊重複；每個區塊 5 列（Pixel 6、5、4、3、2）× 7 欄，外圍粗框
  - 每個樣品先 FW 區塊、再 RV 區塊；區塊之間空一欄
  - **每個條件佔一列帶（橫向放該條件全部樣品，不限 4 個）**，條件之間空一列
  - 各區塊效率最高的那一格以紅色粗體標示
"""
from enum import Enum
from pathlib import Path

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from lct_datahub.core.jv.integrate import curves_frame, file_params_frame, param_sheet
from lct_datahub.core.jv.types import (
    ALL_DATA_PARAMS,
    VALID_PIXELS,
    Condition,
    Direction,
    JVFile,
    JVParam,
)
from lct_datahub.core.sample_id import SampleId


class SheetName(Enum):
    """固定的 sheet 名稱。"""

    ALL_DATA = "ALL_Data"


# 各參數 sheet 的名稱（與 V5 相同）
PARAM_SHEET_NAMES = {
    JVParam.VOC: "Voc",
    JVParam.JSC: "Jsc",
    JVParam.PCE: "PCE",
    JVParam.FF: "FF",
    JVParam.RSH: "Rsh",
}

# ALL_Data 版面常數
_PIXEL_ORDER = sorted(VALID_PIXELS, reverse=True)  # 6、5、4、3、2
_BLOCK_HEIGHT = len(_PIXEL_ORDER)  # 每個區塊 5 列
_BLOCK_WIDTH = 2 + len(ALL_DATA_PARAMS)  # Sample Name、Pixel、五個參數
_BLOCK_STRIDE = _BLOCK_WIDTH + 1  # 區塊之間空一欄
_ALL_DATA_COL_WIDTH = 12
_PARAM_COL_WIDTH = 14
_THICK = Side(style="thick")
_RED_BOLD = Font(name="標楷體", bold=True, color="FF0000")
_MAX_SHEET_NAME = 31  # Excel 的 sheet 名稱上限


def _clean(value):
    """空值（NaN）轉成 None，其餘轉成 Python 原生型別，供 openpyxl 寫入。"""
    if pd.isna(value):
        return None
    return value.item() if hasattr(value, "item") else value


def _write_frame(ws: Worksheet, frame: pd.DataFrame, start_row: int = 1) -> int:
    """把 DataFrame（含欄名）寫到 start_row 起的位置，回傳最後一列的列號。"""
    ws.cell(start_row, 1)  # 確保 sheet 有資料區
    for c, name in enumerate(frame.columns, start=1):
        ws.cell(start_row, c, str(name))
    for r, row in enumerate(frame.itertuples(index=False), start=start_row + 1):
        for c, value in enumerate(row, start=1):
            ws.cell(r, c, _clean(value))
    return start_row + len(frame)


def _write_block(ws: Worksheet, top: int, left: int, sample: SampleId, direction: Direction, jv: JVFile | None):
    """寫一個樣品區塊（單一方向）：5 列 × 7 欄；jv 為 None 時只畫空白區塊。"""
    # 效率最高的 Pixel（只在有資料時才找）
    best_pixel = None
    if jv is not None:
        pce = jv.params[JVParam.PCE.value].dropna()
        if not pce.empty:
            best_pixel = pce.idxmax()

    for i, pixel in enumerate(_PIXEL_ORDER):
        row = top + i
        ws.cell(row, left + 1, str(pixel))
        if jv is not None and pixel in jv.params.index:
            for k, param in enumerate(ALL_DATA_PARAMS):
                value = _clean(jv.params.loc[pixel, param.value])
                cell = ws.cell(row, left + 2 + k, value)
                # 最高效率的那一格：紅色粗體
                if param is JVParam.PCE and pixel == best_pixel:
                    cell.font = _RED_BOLD

        # 外圍粗框：區塊內不畫格線
        for c in range(left, left + _BLOCK_WIDTH):
            ws.cell(row, c).border = Border(
                left=_THICK if c == left else None,
                right=_THICK if c == left + _BLOCK_WIDTH - 1 else None,
                top=_THICK if i == 0 else None,
                bottom=_THICK if i == _BLOCK_HEIGHT - 1 else None,
            )

    # 樣品名稱：5 列合併、置中
    ws.cell(top, left, f"{sample} {direction.value}")
    ws.merge_cells(start_row=top, start_column=left, end_row=top + _BLOCK_HEIGHT - 1, end_column=left)
    ws.cell(top, left).alignment = Alignment(horizontal="center", vertical="center")


def _write_all_data(ws: Worksheet, files: list[JVFile], conditions: list[Condition]) -> None:
    """寫 ALL_Data：每個條件一列帶，橫向排該條件所有（有檔案的）樣品。"""
    by_key = {(jv.name.sample, jv.name.direction): jv for jv in files}
    # 每個條件只放有檔案的樣品（FW 或 RV 任一有即可）；沒有任何檔案的條件整個略過
    groups = [
        [s for s in cond.samples if any((s, d) in by_key for d in Direction)]
        for cond in conditions
    ]
    groups = [g for g in groups if g]
    width = max((len(g) for g in groups), default=0)

    # 第 1 列：表頭，每個區塊重複
    headers = ["Sample Name", "Pixel"] + [p.value for p in ALL_DATA_PARAMS]
    for k in range(width):
        for j, text in enumerate(headers):
            ws.cell(1, 1 + k * _BLOCK_STRIDE + j, text)

    # 之後每個條件：FW 區塊、RV 區塊，再空一列
    top = 2
    for group in groups:
        for k, sample in enumerate(group):
            left = 1 + k * _BLOCK_STRIDE
            for n, direction in enumerate(Direction):
                _write_block(ws, top + n * _BLOCK_HEIGHT, left, sample, direction, by_key.get((sample, direction)))
        top += len(Direction) * _BLOCK_HEIGHT + 1

    for c in range(1, max(width * _BLOCK_STRIDE - 1, 1) + 1):
        ws.column_dimensions[get_column_letter(c)].width = _ALL_DATA_COL_WIDTH


def write_excel(
    path: Path,
    files: list[JVFile],
    conditions: list[Condition] | None = None,
    directions: tuple[Direction, ...] = (Direction.FW,),
) -> None:
    """寫出整合 Excel。

    - ALL_Data：依條件排版（沒有提供條件時，全部樣品視為一個條件）
    - 五張參數 sheet：只有提供 conditions 時才產生
    - 每檔一個 sheet（以原檔名命名）：上方為電壓與各 Pixel 的 J，下方為 Sample ID 參數表
    """
    if conditions is None:
        all_samples = tuple(sorted({jv.name.sample for jv in files}))
        layout_conditions = [Condition("All", all_samples)]
    else:
        layout_conditions = conditions

    wb = Workbook()
    ws = wb.active
    ws.title = SheetName.ALL_DATA.value
    _write_all_data(ws, files, layout_conditions)

    # 依條件分組的參數 sheet
    if conditions:
        for param, sheet in PARAM_SHEET_NAMES.items():
            sheet_ws = wb.create_sheet(sheet)
            _write_frame(sheet_ws, param_sheet(files, conditions, param, directions))
            for c in range(1, len(conditions) + 1):
                sheet_ws.column_dimensions[get_column_letter(c)].width = _PARAM_COL_WIDTH

    # 每檔一個 sheet，以原檔名（不含副檔名）命名，例如 'I5 FW 236'
    for jv in files:
        name = Path(jv.name.filename).stem[:_MAX_SHEET_NAME]
        sheet_ws = wb.create_sheet(name)
        last = _write_frame(sheet_ws, curves_frame(jv))
        _write_frame(sheet_ws, file_params_frame(jv), start_row=last + 3)  # 空兩列

    wb.save(path)

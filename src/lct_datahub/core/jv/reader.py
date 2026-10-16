"""A-1：JV CSV 讀取（依標題辨識欄位，讀取檔底彙整表與有效面積）。

檔案結構：
  - 每條曲線一個區塊，區塊並排；第 0 列以 'No.' 標示區塊起點
  - 第 1 列為表頭；之後是資訊欄（左）與曲線資料（右）
  - 以 '==========' 列結束曲線資料，其後為彙整表（每條曲線一列）
只讀 CSV；任何問題都拋出 JVFileError，由呼叫端警告並停止作業。
"""
import csv
from datetime import datetime
from pathlib import Path

import pandas as pd

from lct_datahub.core.jv.filename import (
    check_curve_count,
    parse_jv_filename,
    parse_jv_filenames,
)
from lct_datahub.core.jv.types import (
    CurveColumn,
    FailureReason,
    InfoField,
    JVCurve,
    JVFile,
    JVFileError,
    JVParam,
)

_BLOCK_MARK = "No."  # 第 0 列的區塊起點標記
_SEPARATOR = "=========="  # 曲線資料與彙整表之間的分隔列
_TIME_FORMAT = "%Y/%m/%d %H:%M:%S"


def list_jv_csv(folder: Path) -> list[Path]:
    """列出資料夾內的 CSV（忽略 txt、jpg 等其他副檔名），依檔名排序。"""
    return sorted(p for p in Path(folder).iterdir() if p.suffix.lower() == ".csv")


def _bad(path: Path, expected: str, actual: str) -> JVFileError:
    """建立「內容無法辨識」例外。"""
    return JVFileError(path.name, FailureReason.BAD_CONTENT, expected, actual)


def _cell(row: list[str], col: int) -> str:
    """取得儲存格；超出列長度視為空字串。"""
    return row[col].strip() if col < len(row) else ""


def read_jv_csv(path: Path) -> JVFile:
    """讀取單一 JV CSV：解析檔名、曲線、有效面積、時間與彙整表參數。"""
    path = Path(path)
    parsed = parse_jv_filename(path.name)
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))

    # 區塊起點：第 0 列中值為 'No.' 的欄位
    if len(rows) < 3:
        raise _bad(path, "至少 3 列", f"{len(rows)} 列")
    starts = [i for i, v in enumerate(rows[0]) if v.strip() == _BLOCK_MARK]
    if not starts:
        raise _bad(path, "第一列含 'No.' 區塊標記", "找不到")
    check_curve_count(parsed, len(starts))  # 檔名 Pixel 數 = 曲線組數

    # 分隔列：曲線資料到此為止
    sep = next((i for i, r in enumerate(rows) if r and r[0].strip().startswith(_SEPARATOR)), None)
    if sep is None:
        raise _bad(path, f"含 {_SEPARATOR} 分隔列", "找不到")

    # 依表頭文字辨識每個區塊的 V、I、J 欄位，不寫死欄位位置
    ends = starts[1:] + [len(rows[1])]
    curves = []
    for pixel, start, end in zip(parsed.pixels, starts, ends):
        header = {_cell(rows[1], c): c for c in range(start, end)}
        missing = [c.value for c in CurveColumn if c.value not in header]
        if missing:
            raise _bad(path, "、".join(c.value for c in CurveColumn), f"缺少 {'、'.join(missing)}")

        # 資訊欄：左欄為項目名稱、右欄為內容（取第一次出現，Statistic 內的 Area 與其相同）
        info: dict[str, str] = {}
        for r in rows[2:sep]:
            label = _cell(r, start)
            if label and label not in info:
                info[label] = _cell(r, start + 1)
        try:
            area = float(info[InfoField.AREA.value])
            stamp = datetime.strptime(info[InfoField.TIMESTAMP.value], _TIME_FORMAT)
        except (KeyError, ValueError):
            raise _bad(path, "有效且可讀的 Area 與 Time stamp", f"Pixel {pixel} 的資訊欄有誤") from None

        # 曲線資料：到分隔列為止，遇到空白儲存格即停止
        points = []
        for r in rows[2:sep]:
            cells = [_cell(r, header[c.value]) for c in CurveColumn]
            if not all(cells):
                continue
            try:
                points.append([float(x) for x in cells])
            except ValueError:
                raise _bad(path, "數值", f"Pixel {pixel} 的曲線含非數值：{cells}") from None
        data = pd.DataFrame(points, columns=[c.value for c in CurveColumn])
        curves.append(JVCurve(pixel=pixel, area=area, timestamp=stamp, data=data))

    params = _read_summary(path, rows, sep, parsed.pixels)
    return JVFile(name=parsed, curves=tuple(curves), params=params)


def _read_summary(path: Path, rows: list[list[str]], sep: int, pixels: tuple[int, ...]) -> pd.DataFrame:
    """讀取檔底彙整表中的 Voc、Jsc、PCE、FF、Rsh；每條曲線一列。"""
    if sep + 1 >= len(rows):
        raise _bad(path, "分隔列之後有彙整表", "沒有資料")
    header = {_cell(rows[sep + 1], c): c for c in range(len(rows[sep + 1]))}
    missing = [p.value for p in JVParam if p.value not in header]
    if missing:
        raise _bad(path, "彙整表含 " + "、".join(p.value for p in JVParam), f"缺少 {'、'.join(missing)}")

    # 彙整表的列：第一欄（Name）有值者
    body = [r for r in rows[sep + 2 :] if _cell(r, 0)]
    if len(body) != len(pixels):
        raise _bad(path, f"彙整表 {len(pixels)} 列", f"{len(body)} 列")
    try:
        table = [[float(_cell(r, header[p.value])) for p in JVParam] for r in body]
    except ValueError:
        raise _bad(path, "彙整表為數值", "含非數值") from None
    return pd.DataFrame(table, columns=[p.value for p in JVParam], index=pd.Index(pixels, name="Pixel"))


def read_jv_files(paths: list[Path]) -> list[JVFile]:
    """讀取一批 JV CSV：先檢查檔名與重複，再逐一讀取；任何問題就拋出 JVFileError 並停止。

    回傳順序依樣品（數字大小）與方向。
    """
    by_name = {Path(p).name: Path(p) for p in paths}
    ordered = parse_jv_filenames(list(by_name))  # 檔名解析與重複檢查
    return [read_jv_csv(by_name[item.filename]) for item in ordered]

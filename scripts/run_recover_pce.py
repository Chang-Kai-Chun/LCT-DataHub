"""Recover 專案：掃描 Recover/ 內所有 JV CSV，挑出 PCE 達門檻以上的曲線並輸出 Excel。

與 A 區的差異：Recover 的檔名不符合 A 區規則，所以這裡不解析檔名，
直接讀每個 CSV 的檔底彙整表（沿用 A 區的 JVParam、InfoField、JVFileError）。
讀不動的檔案不會中止作業，會記錄在 Excel 的「無法讀取」sheet。
"""
import asyncio
import csv
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from lct_datahub.core.jv.types import FailureReason, InfoField, JVFileError, JVParam

ROOT = Path(__file__).resolve().parent.parent
RECOVER_DIR = ROOT / "Recover"
PCE_THRESHOLD = 22.0  # PCE（%）大於等於此值才列出
JSC_LIMIT = 24.8  # Jsc（mA/cm²）的剔除界線
OUT_DIR = ROOT / "Result" / "Recover"

_BLOCK_MARK = "No."  # 第 0 列的曲線區塊標記
_SEPARATOR = "=========="  # 曲線資料與彙整表之間的分隔列
_CHANNEL_LABEL = "Channel"  # 資訊欄中記錄通道與掃描方向的項目
_AREA_HEADER = "Area (cm^2)"  # 彙整表的面積欄
_HIGHLIGHT = PatternFill("solid", start_color="FFFF00")  # 螢光筆黃


class JscRule(Enum):
    """Jsc 剔除規則：value 為檔名後綴；界線 24.5 本身是否保留由規則決定。"""

    BELOW = "Jsc_below"  # 保留 Jsc < 界線（界線本身剔除）
    UP_TO = "Jsc_upto"  # 保留 Jsc <= 界線（界線本身保留）

    def keep(self, jsc: float) -> bool:
        """此 Jsc 是否保留。"""
        return jsc < JSC_LIMIT if self is JscRule.BELOW else jsc <= JSC_LIMIT

    @property
    def text(self) -> str:
        """寫入「說明」sheet 的文字。"""
        return f"保留 Jsc {'<' if self is JscRule.BELOW else '<='} {JSC_LIMIT} mA/cm²（其餘剔除）"


ACTIVE_RULES = (JscRule.UP_TO,)  # 本次要輸出的規則


class OutCol(Enum):
    """輸出 Excel 的欄位名稱與順序。"""

    RANK = "Rank"
    PCE = JVParam.PCE.value
    VOC = JVParam.VOC.value
    JSC = JVParam.JSC.value
    FF = JVParam.FF.value
    RSH = JVParam.RSH.value
    AREA = _AREA_HEADER
    TIMESTAMP = InfoField.TIMESTAMP.value
    CHANNEL = "Channel"
    CURVE = "曲線（檔內第幾組）"
    FOLDER = "資料夾"
    FILE = "檔名"


@dataclass(frozen=True)
class Hit:
    """一條 PCE 達標的曲線。"""

    pce: float
    voc: float
    jsc: float
    ff: float
    rsh: float
    area: float
    timestamp: str
    channel: str
    curve_no: int
    folder: str
    filename: str

    def signature(self) -> tuple:
        """數值指紋：Voc、PCE、FF、Jsc、Rsh、面積完全相同視為同一份數據的副本。"""
        return (self.voc, self.pce, self.ff, self.jsc, self.rsh, self.area)


def _cell(row: list[str], col: int) -> str:
    """取得儲存格；超出列長度視為空字串。"""
    return row[col].strip() if col < len(row) else ""


def scan_file(path: Path) -> list[Hit]:
    """讀一個 CSV 的彙整表，回傳 PCE 達標的曲線；檔案無法辨識時拋出 JVFileError。"""
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        rows = list(csv.reader(f))
    if len(rows) < 3:
        raise JVFileError(str(path.relative_to(RECOVER_DIR)), FailureReason.BAD_CONTENT, "至少 3 列", f"{len(rows)} 列")

    # 區塊起點與分隔列
    starts = [i for i, v in enumerate(rows[0]) if v.strip() == _BLOCK_MARK]
    sep = next((i for i, r in enumerate(rows) if r and r[0].strip().startswith(_SEPARATOR)), None)
    if not starts or sep is None or sep + 1 >= len(rows):
        raise JVFileError(str(path.relative_to(RECOVER_DIR)), FailureReason.BAD_CONTENT, f"'No.' 區塊與 {_SEPARATOR} 彙整表", "找不到")

    # 彙整表表頭與資料列（每條曲線一列）
    header = {_cell(rows[sep + 1], c): c for c in range(len(rows[sep + 1]))}
    need = [p.value for p in JVParam] + [_AREA_HEADER]
    missing = [n for n in need if n not in header]
    if missing:
        raise JVFileError(str(path.relative_to(RECOVER_DIR)), FailureReason.BAD_CONTENT, "彙整表含 " + "、".join(need), f"缺少 {'、'.join(missing)}")
    body = [r for r in rows[sep + 2 :] if _cell(r, 0)]

    hits = []
    for idx, row in enumerate(body):
        if _cell(row, header[JVParam.PCE.value]) == "---":  # 儀器的空白佔位列（沒有量測）
            continue
        try:
            vals = {n: float(_cell(row, header[n])) for n in need}
        except ValueError:
            raise JVFileError(str(path.relative_to(RECOVER_DIR)), FailureReason.BAD_CONTENT, "彙整表為數值", f"第 {idx + 1} 列含非數值") from None
        if vals[JVParam.PCE.value] < PCE_THRESHOLD:
            continue
        # 資訊欄（Time stamp、Channel）：該曲線區塊左欄為項目名稱、右欄為內容
        start = starts[idx] if idx < len(starts) else starts[-1]
        info: dict[str, str] = {}
        for r in rows[2:sep]:
            label = _cell(r, start)
            if label and label not in info:
                info[label] = _cell(r, start + 1)
        hits.append(
            Hit(
                pce=vals[JVParam.PCE.value],
                voc=vals[JVParam.VOC.value],
                jsc=vals[JVParam.JSC.value],
                ff=vals[JVParam.FF.value],
                rsh=vals[JVParam.RSH.value],
                area=vals[_AREA_HEADER],
                timestamp=info.get(InfoField.TIMESTAMP.value, ""),
                channel=info.get(_CHANNEL_LABEL, ""),
                curve_no=idx + 1,
                folder=str(path.parent.relative_to(RECOVER_DIR)),
                filename=path.name,
            )
        )
    return hits


async def scan_all(paths: list[Path]) -> tuple[list[Hit], list[JVFileError]]:
    """以 asyncio 並行掃描全部檔案（每檔交給執行緒），回傳達標曲線與讀取失敗清單。"""

    async def one(p: Path):
        try:
            return await asyncio.to_thread(scan_file, p)
        except JVFileError as e:
            return e

    results = await asyncio.gather(*(one(p) for p in paths))
    hits = [h for r in results if isinstance(r, list) for h in r]
    errors = [r for r in results if isinstance(r, JVFileError)]
    return hits, errors


def write_excel(hits: list[Hit], errors: list[JVFileError], total_files: int, output: Path, rule: JscRule) -> None:
    """輸出 Excel：PCE 由高到低；數值完全相同的副本以螢光筆標示（全部保留）。"""
    # 數值指紋出現兩次以上者視為副本
    counts: dict[tuple, int] = {}
    for h in hits:
        counts[h.signature()] = counts.get(h.signature(), 0) + 1

    wb = Workbook()
    ws = wb.active
    ws.title = "PCE達標"
    cols = [c.value for c in OutCol]
    ws.append(cols)
    for c in ws[1]:
        c.font = Font(name="Arial", bold=True)
        c.alignment = Alignment(horizontal="center")

    for rank, h in enumerate(sorted(hits, key=lambda x: x.pce, reverse=True), start=1):
        ws.append([rank, h.pce, h.voc, h.jsc, h.ff, h.rsh, h.area, h.timestamp, h.channel, h.curve_no, h.folder, h.filename])
        if counts[h.signature()] > 1:  # 副本：整列塗黃
            for c in ws[ws.max_row]:
                c.fill = _HIGHLIGHT
    ws.freeze_panes = "A2"
    for i, col in enumerate(cols, start=1):
        width = max(len(str(col)), *(len(str(c.value or "")) for c in ws[get_column_letter(i)][:200]))
        ws.column_dimensions[get_column_letter(i)].width = min(width + 2, 60)

    # 說明與統計
    info = wb.create_sheet("說明")
    dup_rows = sum(1 for h in hits if counts[h.signature()] > 1)
    for line in [
        ("掃描時間", datetime.now().strftime("%Y/%m/%d %H:%M:%S")),
        ("PCE 門檻", f"≥ {PCE_THRESHOLD}%（取檔底彙整表的 Efficiency，面積為儀器當時設定）"),
        ("Jsc 規則", rule.text),
        ("掃描 CSV 數", total_files),
        ("PCE 達標曲線數", len(hits)),
        ("涉及檔案數", len({(h.folder, h.filename) for h in hits})),
        ("螢光筆（黃）列數", f"{dup_rows}（Voc、PCE、FF、Jsc、Rsh、面積完全相同，疑似副本；全部保留）"),
        ("無法讀取的檔案數", len(errors)),
    ]:
        info.append(line)
    info.column_dimensions["A"].width = 22
    info.column_dimensions["B"].width = 80

    # 讀不動的檔案（不中止作業）
    bad = wb.create_sheet("無法讀取")
    bad.append(["資料夾 / 檔名", "原因", "期望", "實際"])
    for e in errors:
        bad.append([e.filename, e.reason.value, e.expected, e.actual])

    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(output)
    except PermissionError:
        print(f"警告：{output} 被 Excel 開著，無法覆寫，請關閉後重跑")


def main() -> None:
    """掃描 Recover/，依 ACTIVE_RULES 的 Jsc 規則各輸出一份 Excel 並印出摘要。"""
    paths = sorted(RECOVER_DIR.rglob("*.csv"))
    all_hits, errors = asyncio.run(scan_all(paths))
    for rule in ACTIVE_RULES:
        hits = [h for h in all_hits if rule.keep(h.jsc)]
        output = OUT_DIR / f"PCE_over_{PCE_THRESHOLD:g}_{rule.value}_{JSC_LIMIT:g}.xlsx"
        write_excel(hits, errors, len(paths), output, rule)
        print(f"{rule.text}：{len(hits)} 條 -> {output.name}")


if __name__ == "__main__":
    main()

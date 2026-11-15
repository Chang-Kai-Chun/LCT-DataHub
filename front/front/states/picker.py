"""畫圖勾選清單的共用狀態（mixin）：B 暗電流圖、C EQE 圖與 R-plot 共用。

排法：已確認分組時每個條件一個區塊，否則全部樣品一個區塊；區塊內每個樣品一直行，直行內是它的 pixel
（曲線），依自然排序；名稱無法辨識樣品的放在最後的「其他」區塊。
「暫時隱藏」：勾選保留，但該區塊不畫進圖。

使用方式：class XxxState(CurvePickerMixin, GroupingMixin, SessionState)
- 子類別在 _apply_job 中設定 pick_curves（每條曲線的名稱與所屬樣品），並呼叫 _init_selection()
- 需要 GroupingMixin 的 samples、conditions、groups_confirmed
- 可覆寫 _on_hidden_changed()：隱藏狀態改變時要觸發的事件（例如已有預覽圖就重畫）
"""
import re
from dataclasses import dataclass, field

import reflex as rx

ALL_SAMPLES_TITLE = "全部樣品（尚未分組）"
OTHERS_TITLE = "其他（名稱無法辨識樣品）"
OTHERS_COLUMN = "—"
_DIGITS = re.compile(r"(\d+)")


@dataclass
class PickCurve:
    """一條可勾選的曲線：名稱與所屬樣品（空白表示名稱無法辨識樣品）。"""

    name: str = ""
    device: str = ""


@dataclass
class DeviceColumn:
    """勾選清單的一個直行：一個樣品與它的 pixel。"""

    device: str = ""
    curves: list[str] = field(default_factory=list)


@dataclass
class PlotBlock:
    """勾選清單的一個區塊：一個條件（或尚未分組時的全部樣品）。"""

    title: str = ""
    curves: list[str] = field(default_factory=list)  # 區塊內全部 pixel（給「整組勾選」）
    columns: list[DeviceColumn] = field(default_factory=list)
    summary: str = ""  # 「n 個樣品 · m 個 pixel」


def natural_key(name: str) -> list:
    """自然排序：數字依大小比較（G1-2 排在 G1-10 前面）。"""
    return [int(p) if p.isdigit() else p.lower() for p in _DIGITS.split(name)]


def _block(title: str, devices: list[str], by_device: dict[str, list[str]]) -> PlotBlock:
    """組出一個區塊：每個樣品一個直行（沒有曲線的樣品略過）。"""
    columns = [DeviceColumn(d, by_device[d]) for d in devices if by_device.get(d)]
    curves = [n for c in columns for n in c.curves]
    return PlotBlock(title, curves, columns, f"{len(columns)} 個樣品 · {len(curves)} 個 pixel")


class CurvePickerMixin(rx.State, mixin=True):
    """畫圖勾選清單：勾選、整行／整組勾選、全選、全消、暫時隱藏。"""

    pick_curves: list[PickCurve] = []
    plot_selected: list[str] = []
    hidden_blocks: list[str] = []  # 暫時隱藏的區塊標題

    # ---------- 子類別可覆寫 ----------
    def _on_hidden_changed(self):
        """隱藏狀態改變時要觸發的事件（預設沒有）。"""
        return None

    # ---------- 計算屬性 ----------
    @rx.var
    def plot_blocks(self) -> list[PlotBlock]:
        """勾選清單（區塊 → 樣品直行 → pixel）。"""
        return self._build_blocks()

    @rx.var
    def hidden_selected_count(self) -> int:
        """已勾選但因區塊暫時隱藏而不畫的 pixel 數。"""
        return len(self.plot_selected) - len(self._visible_selected())

    @rx.var
    def pick_sample_count(self) -> int:
        """樣品數（G1、G2…，名稱無法辨識的不算）。"""
        return len({c.device for c in self.pick_curves if c.device})

    @rx.var
    def pick_pixel_count(self) -> int:
        """pixel（曲線）數。"""
        return len(self.pick_curves)

    # ---------- 排列 ----------
    def _build_blocks(self) -> list[PlotBlock]:
        """依分組排出區塊；每個樣品一直行。"""
        by_device: dict[str, list[str]] = {}
        others: list[str] = []
        for c in self.pick_curves:
            if c.device:
                by_device.setdefault(c.device, []).append(c.name)
            else:
                others.append(c.name)
        by_device = {d: sorted(names, key=natural_key) for d, names in by_device.items()}

        if self.groups_confirmed:
            blocks = [_block(c.name, c.samples, by_device) for c in self.conditions]
        else:
            blocks = [_block(ALL_SAMPLES_TITLE, self.samples, by_device)]
        if others:
            blocks.append(PlotBlock(OTHERS_TITLE, others, [DeviceColumn(OTHERS_COLUMN, others)],
                                    f"{len(others)} 個 pixel"))
        return [b for b in blocks if b.curves]

    def _in_display_order(self, names: set[str]) -> list[str]:
        """依勾選清單的顯示順序（條件 → 樣品 → pixel）排列；圖例也依此順序。"""
        return [n for b in self._build_blocks() for n in b.curves if n in names]

    def _visible_selected(self) -> list[str]:
        """依顯示順序取出已勾選、且不在隱藏區塊內的 pixel（送去畫圖的清單）。"""
        hidden, chosen = set(self.hidden_blocks), set(self.plot_selected)
        return [n for b in self._build_blocks() if b.title not in hidden for n in b.curves if n in chosen]

    def _init_selection(self) -> None:
        """第一次載入時預設全選；之後保留勾選（只留下仍存在的曲線）。"""
        names = {c.name for c in self.pick_curves}
        kept = set(self.plot_selected) & names
        self.plot_selected = self._in_display_order(kept or names)

    # ---------- 事件 ----------
    @rx.event
    def toggle_plot_curve(self, name: str, checked: bool) -> None:
        """勾選或取消某個 pixel。"""
        chosen = set(self.plot_selected)
        if checked:
            chosen.add(name)
        else:
            chosen.discard(name)
        self.plot_selected = self._in_display_order(chosen)

    @rx.event
    def toggle_plot_many(self, names: list[str]) -> None:
        """整行（樣品）或整組（條件）：全部已勾選就全部取消，否則全部勾選。"""
        chosen = set(self.plot_selected)
        chosen = chosen - set(names) if set(names) <= chosen else chosen | set(names)
        self.plot_selected = self._in_display_order(chosen)

    @rx.event
    def select_all_plot(self) -> None:
        """全選。"""
        self.plot_selected = self._in_display_order({c.name for c in self.pick_curves})

    @rx.event
    def select_no_plot(self) -> None:
        """全消。"""
        self.plot_selected = []

    @rx.event
    def toggle_hide_block(self, title: str):
        """暫時隱藏／取消隱藏一個區塊（勾選保留，只是不畫進圖）。"""
        hidden = set(self.hidden_blocks)
        hidden.symmetric_difference_update({title})
        self.hidden_blocks = sorted(hidden)
        return self._on_hidden_changed()

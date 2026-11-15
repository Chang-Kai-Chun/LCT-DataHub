"""畫圖勾選清單與繪圖版面的共用元件（B 暗電流圖、C EQE 圖與 R-plot）。

state 參數為繼承 CurvePickerMixin 的 State 類別。
版面：左邊勾選清單（整頁鎖定時只有它捲動），右邊圖與參數（固定）；樣式在 lct.css 的
.plot-layout、.blocks、.block、.device、.plot-side。
"""
import reflex as rx

from front.components.ui import BtnVariant, btn, octa_loader
from front.states.picker import DeviceColumn, PlotBlock


def _check(state, name: rx.Var) -> rx.Component:
    """一個 pixel 的勾選框（點選時送出「目前狀態的相反」）。"""
    checked = state.plot_selected.contains(name)
    return rx.el.label(
        rx.el.input(type="checkbox", checked=checked, on_change=state.toggle_plot_curve(name, ~checked)),
        rx.el.span(name),
        class_name="check",
    )


def _column(state, col: DeviceColumn) -> rx.Component:
    """一個樣品一直行：上方樣品名稱（點選整行勾選／取消），下方是它的 pixel。"""
    return rx.el.div(
        rx.el.button(col.device, type="button", class_name="device-btn", title="整行勾選／取消",
                     on_click=state.toggle_plot_many(col.curves)),
        rx.foreach(col.curves, lambda n: _check(state, n)),
        class_name="device",
    )


def _block(state, block: PlotBlock) -> rx.Component:
    """一個條件區塊：標題、整組勾選、暫時隱藏（固定寬度、固定在最右邊）、數量、樣品直行。"""
    hidden = state.hidden_blocks.contains(block.title)
    return rx.el.div(
        rx.el.div(
            rx.el.h3(block.title),
            btn("整組勾選／取消", variant=BtnVariant.GHOST, small=True, on_click=state.toggle_plot_many(block.curves)),
            rx.el.button(
                rx.cond(hidden, "取消隱藏", "暫時隱藏"),
                type="button",
                class_name=rx.cond(hidden, "btn sm hide-btn warn", "btn sm hide-btn"),
                aria_pressed=rx.cond(hidden, "true", "false"),
                on_click=state.toggle_hide_block(block.title),
            ),
            class_name="block-head",
        ),
        rx.el.span(block.summary, rx.cond(hidden, " · 已隱藏，不畫進圖", ""), class_name="block-sum"),
        rx.el.div(rx.foreach(block.columns, lambda c: _column(state, c)), class_name="columns"),
        class_name=rx.cond(hidden, "block is-hidden", "block"),
    )


def curve_picker(state, *extra_head: rx.Component) -> rx.Component:
    """勾選清單：已選數量、暫時隱藏數量、全選、全消，以及各條件區塊；extra_head 放在標題列（例如「前往分組」）。"""
    return rx.el.section(
        rx.el.div(
            rx.el.h2("曲線選擇"),
            rx.el.span("已選 ", state.plot_selected.length(), " 個 pixel", class_name="mono"),
            rx.cond(
                state.hidden_selected_count > 0,
                rx.el.span("其中 ", state.hidden_selected_count, " 個 pixel 暫時隱藏", class_name="flag"),
            ),
            rx.el.div(
                *extra_head,
                btn("全選", small=True, on_click=state.select_all_plot),
                btn("全消", small=True, on_click=state.select_no_plot, style={"border_color": "var(--line)"}),
                class_name="end",
            ),
            class_name="section-head",
        ),
        rx.el.div(rx.foreach(state.plot_blocks, lambda b: _block(state, b)), class_name="blocks"),
        class_name="section",
    )


def plot_figure(png: rx.Var, alt: str, loading=False) -> rx.Component:
    """右側的圖：還沒預覽時顯示提示；畫圖中在圖的中央顯示八面體讀取動畫（圖一律白底，與介面配色分開）。"""
    return rx.el.figure(
        rx.el.div(
            rx.cond(
                png != "",
                rx.el.img(src=png, alt=alt, style={"width": "100%", "display": "block"}),
                rx.el.p("勾選左側的 pixel，設定範圍後按「預覽」。", class_name="small",
                        style={"margin": "0", "padding": "120px 0", "text_align": "center", "color": "#555555"}),
            ),
            rx.cond(
                loading,
                rx.el.div(octa_loader(64, "畫圖中"), rx.el.span("畫圖中…", class_name="small"),
                          class_name="plot-busy", role="status"),
            ),
            class_name="frame",
        ),
        class_name="figure",
    )


def plot_layout(picker: rx.Component, *side: rx.Component) -> rx.Component:
    """繪圖版面：左邊勾選清單、右邊（圖與參數）。"""
    return rx.el.div(picker, rx.el.aside(*side, class_name="plot-side", aria_label="繪圖"), class_name="plot-layout")

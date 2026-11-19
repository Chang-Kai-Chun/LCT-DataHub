"""E 區 PD 數據整合頁面（lct. 設計）：e-1 設定 → e-2 配對 → e-3 D* 表 → e-4 D*(λ) 圖。

- e-1 設定：B、C、D 三區是否有資料、D* 偏壓（0／−0.1／−0.5 V）、指定波長（最多 3 個）、下載 Excel
- e-2 配對：每個 pixel 的暗電流、EQE、noise；有兩台儀器時可選擇，也可不使用
- e-3 D* 表：切換 D* 種類（實測／Shot+Thermal／Thermal／Shot），最大值與所在波長、指定波長的 D* 與 R；點一下即複製
- e-4 D*(λ) 圖：左邊勾選清單（依專案總覽分組），右邊圖與參數
"""
import reflex as rx

from front.components.layout import layout, page_head, page_top
from front.components.picker import curve_picker, plot_figure, plot_layout
from front.components.ui import (
    BtnVariant, btn, busy, chevron, copy_cell, note, panel, step_tabs, tag, text_input,
)
from front.enums import IntegrationTab, Route, SourceKind
from front.states.integration_state import (
    AUTO_PAIR, MAX_WAVELENGTHS, NOT_USED, PLOT_NAME, IntegrationState, PairRow, ResultRow, SourceCell,
)

TABS = [
    (IntegrationTab.SETTINGS.value, "e-1", "設定", True),
    (IntegrationTab.PAIRING.value, "e-2", "配對", True),
    (IntegrationTab.TABLE.value, "e-3", "D* 表", True),
    (IntegrationTab.PLOT.value, "e-4", "D*(λ) 圖", True),
]
SOURCE_LABELS = {SourceKind.DARK: "暗電流（B）", SourceKind.EQE: "EQE（C）", SourceKind.NOISE: "Noise（D）"}


def _next(label: str, tab: IntegrationTab) -> rx.Component:
    """「下一步」按鈕。"""
    return btn(label, " →", variant=BtnVariant.PRIMARY, on_click=IntegrationState.go_to(tab.value))


# ---------- e-1 設定 ----------
def _status(label: str, ok) -> rx.Component:
    """一區有無上傳：打勾或空格（唯讀）。"""
    return rx.el.label(
        rx.el.input(type="checkbox", checked=ok, read_only=True, disabled=True),
        rx.el.span(label, style={"font_family": "var(--body)"}),
        class_name="check",
    )


def _settings_tab() -> rx.Component:
    """e-1：各區有無上傳、偏壓、指定波長、Excel。"""
    return rx.el.div(
        rx.el.div(
            _status("b. 暗電流", IntegrationState.has_dark),
            _status("c. EQE", IntegrationState.has_eqe),
            _status("d. Noise", IntegrationState.has_noise),
            class_name="row", style={"gap": "28px"},
        ),
        panel(
            "計算設定",
            rx.el.div(
                rx.el.span("D* 偏壓", class_name="label"),
                rx.el.div(
                    rx.foreach(IntegrationState.bias_options, lambda b: rx.el.button(
                        b, " V", type="button", aria_pressed=rx.cond(IntegrationState.bias == b, "true", "false"),
                        on_click=IntegrationState.set_bias(b),
                    )),
                    class_name="segmented", role="group", aria_label="D* 偏壓",
                ),
                rx.el.span("EQE、暗電流、noise 必須同一偏壓；對不上的項目不算。0 V 的 Shot 用暗電流曲線最低點的 |I|。",
                           class_name="small muted"),
                class_name="field",
            ),
            rx.el.div(
                rx.el.span("指定波長（nm，最多 3 個，可留空）", class_name="label"),
                rx.el.div(
                    *[text_input(IntegrationState.wl_inputs[i], lambda v, i=i: IntegrationState.set_wl(i, v),
                                 placeholder=f"波長 {i + 1}", class_name="mono", aria_label=f"波長 {i + 1}",
                                 key=f"wl-{i}-{IntegrationState.wl_key}", style={"width": "8em"})
                      for i in range(MAX_WAVELENGTHS)],
                    btn("儲存設定", variant=BtnVariant.PRIMARY, on_click=IntegrationState.save_settings,
                        disabled=IntegrationState.loading),
                    class_name="row",
                ),
                rx.el.span("每種 D* 都會輸出最大值與所在波長，另外列出這些波長的值。", class_name="small muted"),
                class_name="field",
            ),
        ),
        panel(
            "結果",
            rx.el.div(
                rx.el.span(IntegrationState.pixel_count, " 個 pixel · ", IntegrationState.computable_count,
                           " 個算得出 D*", class_name="mono small"),
                btn("下載 Excel", on_click=IntegrationState.download_excel, disabled=IntegrationState.loading),
                _next("下一步：配對", IntegrationTab.PAIRING),
                class_name="row",
            ),
            rx.el.p("Excel：Summary（每個 pixel 一列）＋ D Measured／D Shot+Thermal／D Thermal／D Shot"
                    "（波長＋每個 pixel 一欄，第一列 Max，可直接貼到 Origin）。",
                    class_name="small muted", style={"margin": "0"}),
        ),
        class_name="section", style={"gap": "40px"},
    )


# ---------- e-2 配對 ----------
def _source_select(pixel, kind: SourceKind, cell: SourceCell) -> rx.Component:
    """某一區的選單：自動、不使用、各候選；右邊顯示目前選到的儀器。"""
    return rx.el.div(
        rx.el.div(
            rx.el.select(
                rx.el.option("自動", value=AUTO_PAIR),
                rx.el.option("不使用", value=NOT_USED),
                rx.foreach(cell.options, lambda n: rx.el.option(n, value=n)),
                value=cell.choice, on_change=lambda v: IntegrationState.set_choice(pixel, kind.value, v),
                class_name="select", aria_label=f"{SOURCE_LABELS[kind]}",
            ),
            chevron(),
            class_name="select-wrap", style={"min_width": "10em"},
        ),
        rx.cond(cell.name != "", rx.el.span(cell.name, " ", tag(cell.instrument), class_name="small"),
                rx.el.span("—", class_name="muted")),
        class_name="stack", style={"gap": "4px"},
    )


def _pair_row(r: PairRow) -> rx.Component:
    """配對表的一列。"""
    return rx.el.tr(
        rx.el.td(r.pixel, rx.cond(r.multi, tag("兩台儀器", "warn")), class_name="mono"),
        rx.el.td(_source_select(r.pixel, SourceKind.DARK, r.dark)),
        rx.el.td(_source_select(r.pixel, SourceKind.EQE, r.eqe)),
        rx.el.td(_source_select(r.pixel, SourceKind.NOISE, r.noise)),
    )


def _pairing_tab() -> rx.Component:
    """e-2：每個 pixel 三區的配對。"""
    return panel(
        "配對",
        rx.el.p("依 pixel 名稱自動配對（暗電流取底線前的名稱，例如 G1-2_330 K → G1-2）。同一 pixel 有 PD-QE 與明志兩台的"
                "暗電流或 noise 時，自動選兩者共有的儀器（橘色標籤）；可在選單改選或「不使用」。noise 只列與 D* 偏壓相同的組。",
                class_name="small muted", style={"margin": "0"}),
        rx.el.div(
            rx.el.table(
                rx.el.thead(rx.el.tr(*[rx.el.th(h) for h in ("Pixel", *SOURCE_LABELS.values())])),
                rx.el.tbody(rx.foreach(IntegrationState.pair_rows, _pair_row)),
                class_name="table compact",
            ),
            class_name="table-scroll", style={"max_height": "62vh"},
        ),
        end=[_next("下一步：D* 表", IntegrationTab.TABLE)],
    )


# ---------- e-3 D* 表 ----------
def _result_row(r: ResultRow) -> rx.Component:
    """D* 表的一列；數值點一下就複製。"""
    return rx.el.tr(
        copy_cell(r.pixel, class_name="mono pixel-col"),
        copy_cell(r.peak, style={"font_weight": "700"}),
        copy_cell(r.peak_at),
        rx.foreach(r.at, lambda v: copy_cell(v)),
        copy_cell(r.noise),
        copy_cell(r.rsh),
        copy_cell(r.dark_current),
        rx.foreach(r.r_at, lambda v: copy_cell(v)),
        rx.el.td("", class_name="small muted"),  # 備註（目前不顯示自動提醒，2026-11-19）
    )


def _table_tab() -> rx.Component:
    """e-3：依選擇的 D* 種類顯示最大值與指定波長的值。"""
    return panel(
        "D* 表",
        rx.el.div(
            rx.el.span("D* 種類", class_name="label"),
            rx.el.div(
                rx.foreach(IntegrationState.kind_options, lambda k: rx.el.button(
                    k, type="button", aria_pressed=rx.cond(IntegrationState.table_kind == k, "true", "false"),
                    on_click=IntegrationState.set_table_kind(k),
                )),
                class_name="segmented", role="group", aria_label="D* 種類",
            ),
            class_name="field",
        ),
        rx.el.div(
            rx.el.table(
                rx.el.thead(rx.el.tr(
                    rx.el.th("Pixel", class_name="pixel-col"), rx.el.th("最大 D* (Jones)"), rx.el.th("最大值波長 (nm)"),
                    rx.foreach(IntegrationState.wavelength_labels, lambda l: rx.el.th("D* @ ", l, " (Jones)")),
                    rx.el.th("i_n (A/Hz^0.5)"), rx.el.th("Rsh (Ω)"), rx.el.th("Id (A)"),
                    rx.foreach(IntegrationState.wavelength_labels, lambda l: rx.el.th("R @ ", l, " (A/W)")),
                    rx.el.th("備註", style={"min_width": "4em"}),
                )),
                rx.el.tbody(rx.foreach(IntegrationState.result_rows, _result_row)),
                class_name="table compact sticky-head",
            ),
            class_name="table-scroll", style={"max_height": "60vh"},
        ),
        end=[btn("下載 Excel", small=True, on_click=IntegrationState.download_excel, disabled=IntegrationState.loading)],
    )


# ---------- e-4 D*(λ) 圖 ----------
def _range(label: str, unit: str, lo, hi, on_lo, on_hi, key: str) -> rx.Component:
    """一組「下限～上限」輸入框（留空為自動）。"""
    return rx.el.div(
        rx.el.span(label, " ", rx.el.span(unit, class_name="mono", style={"font_weight": "400"}),
                   class_name="label", style={"color": "var(--ink)", "font_weight": "700"}),
        rx.el.div(
            text_input(lo, on_lo, placeholder="自動", class_name="mono", aria_label=f"{label}下限",
                       key=f"{key}-lo-{IntegrationState.range_key}"),
            rx.el.span("～", class_name="muted"),
            text_input(hi, on_hi, placeholder="自動", class_name="mono", aria_label=f"{label}上限",
                       key=f"{key}-hi-{IntegrationState.range_key}"),
            class_name="range",
        ),
        class_name="field",
    )


def _plot_params() -> rx.Component:
    """e-4 參數：D* 種類、X／Y 範圍、對數、按鈕。"""
    return rx.el.div(
        rx.el.div(
            rx.el.span("D* 種類", class_name="label"),
            rx.el.div(
                rx.foreach(IntegrationState.kind_options, lambda k: rx.el.button(
                    k, type="button", aria_pressed=rx.cond(IntegrationState.plot_kind == k, "true", "false"),
                    on_click=IntegrationState.set_plot_kind(k),
                )),
                class_name="segmented", role="group", aria_label="D* 種類",
            ),
            class_name="field full",
        ),
        _range("X 軸", "(nm)", IntegrationState.x_min, IntegrationState.x_max, IntegrationState.set_x_min,
               IntegrationState.set_x_max, "dx"),
        _range("Y 軸", "(Jones)", IntegrationState.y_min, IntegrationState.y_max, IntegrationState.set_y_min,
               IntegrationState.set_y_max, "dy"),
        rx.el.label(
            rx.el.input(type="checkbox", checked=IntegrationState.log_y,
                        on_change=IntegrationState.set_log_y(~IntegrationState.log_y)),
            rx.el.span("Y 軸對數", style={"font_family": "var(--body)"}),
            class_name="check full",
        ),
        rx.el.div(
            btn("預覽", variant=BtnVariant.PRIMARY, class_name="grow", on_click=IntegrationState.plot,
                disabled=IntegrationState.loading),
            btn("下載 PNG", disabled=IntegrationState.plot_png == "",
                on_click=rx.download(url=IntegrationState.plot_png, filename=PLOT_NAME)),
            btn("範圍改回自動", variant=BtnVariant.GHOST, on_click=IntegrationState.reset_range),
            class_name="row nowrap full",
        ),
        class_name="params params-grid",
    )


def _plot_tab() -> rx.Component:
    """e-4：左邊勾選清單、右邊圖與參數（指定波長畫灰色虛線）。"""
    return rx.cond(
        IntegrationState.pick_curves.length() > 0,
        plot_layout(
            curve_picker(IntegrationState, rx.fragment()),
            plot_figure(IntegrationState.plot_png, "D*(λ)", IntegrationState.loading),
            _plot_params(),
        ),
        note("還沒有算得出 D* 的 pixel：需要同一 pixel 有 EQE（c.）與暗電流（b.）。"),
    )


# ---------- 頁面 ----------
def _tab_content() -> rx.Component:
    """依目前的步驟顯示內容。"""
    return rx.match(
        IntegrationState.tab,
        (IntegrationTab.PAIRING.value, _pairing_tab()),
        (IntegrationTab.TABLE.value, _table_tab()),
        (IntegrationTab.PLOT.value, _plot_tab()),
        _settings_tab(),
    )


@rx.page(route=Route.INTEGRATION.value, title="e. PD 數據整合｜lct.",
         on_load=[IntegrationState.require_project, IntegrationState.load])
def integration_page() -> rx.Component:
    """PD 數據整合頁面。"""
    return layout(
        page_top(
            page_head(
                "PD 數據整合", letter="e.",
                meta=rx.el.span(IntegrationState.pixel_count, " 個 pixel · 偏壓 ", IntegrationState.bias, " V"),
            ),
            step_tabs(IntegrationState.tab, TABS, IntegrationState.set_tab),
        ),
        rx.el.div(_tab_content(), class_name="tab-panel plot-host"),
        busy(IntegrationState.loading),
        wide=True,
        lock=IntegrationState.plot_locked,
    )

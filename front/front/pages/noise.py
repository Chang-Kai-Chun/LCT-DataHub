"""D 區 Noise 頁面（lct. 設計）：d-1 上傳 → d-2 分組 → d-3 雜訊圖 → d-4 數值與參考線。

- d-1 上傳：上傳 csv（明志、PD-QE），每組的 n、排除的檔、提醒（未穩定、底線不一致、偏壓為預設）、下載 Excel
- d-2 分組：依專案條件分組（樣品代號，同 B、C 區），只影響勾選清單的排列
- d-3 雜訊圖：左邊勾選清單（可依偏壓一鍵勾選），右邊圖與參數（定義、範圍帶、參考線、範圍）
- d-4 數值：每組 1 Hz 雜訊、配對的暗電流（可手動指定）、Shot／Thermal 理論值；點一下即複製
"""
import reflex as rx

from front.components.grouping import grouping_adjust, grouping_settings
from front.components.layout import layout, page_head, page_top
from front.components.picker import curve_picker, plot_figure, plot_layout
from front.components.ui import (
    BtnVariant, btn, busy, chevron, copy_cell, note, panel, segmented, step_tabs, tag, text_input, upload_box,
)
from front.enums import NoiseDefinition, NoiseTab, Route
from front.states.noise_state import (
    ACCEPT, AUTO_PAIR, NO_PAIR, PLOT_NAME, UPLOAD_ID, NoiseGroupRow, NoiseState, ReferenceRow,
)

TABS = [
    (NoiseTab.UPLOAD.value, "d-1", "上傳", True),
    (NoiseTab.GROUPING.value, "d-2", "分組", True),
    (NoiseTab.PLOT.value, "d-3", "雜訊圖", True),
    (NoiseTab.VALUES.value, "d-4", "數值與參考線", True),
]
DEFINITIONS = [d.value for d in NoiseDefinition]


# ---------- 共用小元件 ----------
def _need_job() -> rx.Component:
    """尚未上傳時的提示。"""
    return note("請先在「d-1 上傳」上傳 noise 檔。")


def _next(label: str, tab: NoiseTab) -> rx.Component:
    """「下一步」按鈕。"""
    return btn(label, " →", variant=BtnVariant.PRIMARY, on_click=NoiseState.go_to(tab.value))


def _multiline(text) -> rx.Component:
    """多行文字（以換行分隔）。"""
    return rx.el.span(text, style={"white_space": "pre-line"})


# ---------- d-1 上傳 ----------
def _group_row(g: NoiseGroupRow) -> rx.Component:
    """分組結果的一列。"""
    return rx.el.tr(
        rx.el.td(g.name, class_name="mono"),
        rx.el.td(g.instrument),
        rx.el.td(g.bias, rx.cond(g.bias_default, tag("預設", "warn")), class_name="num"),
        rx.el.td(rx.cond(g.n > 0, g.n, tag("0", "warn")), class_name="num"),
        rx.el.td(g.noise_1hz, class_name="num", style={"font_weight": "700"}),
        rx.el.td(g.peak, class_name="num"),
        rx.el.td(g.floor_ratio, class_name="num"),
        rx.el.td(
            rx.cond(g.excluded != "", rx.el.div(tag("排除", "warn"), _multiline(g.excluded), class_name="small")),
            rx.cond(g.notes != "", rx.el.div(_multiline(g.notes), class_name="small muted")),
            rx.cond(~g.has_warning, rx.el.span("—", class_name="muted")),
        ),
    )


def _result() -> rx.Component:
    """分組平均的結果：每組的 n、1 Hz 值、峰值、底線一致性、排除與提醒。"""
    return panel(
        "分組結果",
        rx.el.div(
            rx.el.strong("讀取完成"),
            rx.el.span(NoiseState.groups.length(), " 組 · ", NoiseState.pick_sample_count, " 個樣品",
                       class_name="mono small muted"),
            rx.cond(NoiseState.warning_count > 0, tag(NoiseState.warning_count.to_string() + " 組有提醒", "warn")),
            class_name="row",
        ),
        rx.cond(
            NoiseState.skipped.length() > 0,
            note("以下檔案已略過（只接受 .csv）：", NoiseState.skipped.join("、"), kind="warn"),
        ),
        rx.el.p(
            "同一樣品、偏壓的檔自動平均（n 次，功率平均）。溢位、削平的檔自動排除；電流未穩定、"
            "n 次底線相差超過 5 倍只提醒、仍納入。峰值為電流絕對值的最大值（主要是 60 Hz 干擾）。",
            class_name="small muted", style={"margin": "0"},
        ),
        rx.el.div(
            rx.el.table(
                rx.el.thead(rx.el.tr(*[rx.el.th(h) for h in (
                    "組", "儀器", "偏壓", "n", "1 Hz (A/Hz^0.5)", "峰值 |I| (A)", "底線比", "排除與提醒")])),
                rx.el.tbody(rx.foreach(NoiseState.groups, _group_row)),
                class_name="table compact",
            ),
            class_name="table-scroll", style={"max_height": "55vh"},
        ),
    )


def _excel() -> rx.Component:
    """下載 Excel 與下一步。"""
    return panel(
        "下載 Excel",
        rx.el.p("Summary（每組一列：n、1 Hz、峰值、底線比、量測參數、使用與排除的檔、提醒）、Mean（每組平均）、"
                "Runs（每個檔）、Excluded（被排除的檔）。數值依目前的定義（d-3 可切換）。",
                class_name="small muted", style={"margin": "0"}),
        rx.el.div(
            btn("下載 Excel", on_click=NoiseState.download_excel, disabled=NoiseState.loading),
            _next("下一步：分組", NoiseTab.GROUPING),
            class_name="row",
        ),
    )


def _upload_tab() -> rx.Component:
    """d-1：上傳 → 分組結果 → Excel。"""
    return rx.el.div(
        panel(
            "上傳",
            upload_box(
                UPLOAD_ID, ACCEPT,
                "接受 .csv（明志、PD-QE）；檔名如 G1-2 1st -0.1V（次數、偏壓由檔名讀出，沒有偏壓預設 0 V）",
                NoiseState.handle_upload(rx.upload_files(upload_id=UPLOAD_ID)),
                NoiseState.loading,
            ),
        ),
        rx.cond(NoiseState.has_job, _result()),
        rx.cond(NoiseState.has_job, _excel()),
        class_name="section", style={"gap": "40px"},
    )


# ---------- d-2 分組 ----------
def _grouping_tab() -> rx.Component:
    """依樣品代號分組（同 B、C 區）。"""
    unit = "樣品"
    return rx.cond(
        NoiseState.has_job,
        rx.el.div(
            grouping_settings(NoiseState, unit=unit),
            rx.cond(
                NoiseState.conditions.length() > 0,
                grouping_adjust(NoiseState, _next("下一步：雜訊圖", NoiseTab.PLOT), unit=unit),
            ),
            class_name="section", style={"gap": "32px"},
        ),
        _need_job(),
    )


# ---------- d-3 雜訊圖 ----------
def _goto_grouping() -> rx.Component:
    """尚未分組時，勾選清單標題列的「前往分組」。"""
    return rx.cond(
        ~NoiseState.groups_confirmed,
        btn("前往分組", variant=BtnVariant.GHOST, small=True, on_click=NoiseState.go_to(NoiseTab.GROUPING.value)),
    )


def _range(label: str, unit: str, lo, hi, on_lo, on_hi, key: str) -> rx.Component:
    """一組「下限～上限」輸入框（留空為自動；對數座標下限需大於 0）。"""
    return rx.el.div(
        rx.el.span(label, " ", rx.el.span(unit, class_name="mono", style={"font_weight": "400"}),
                   class_name="label", style={"color": "var(--ink)", "font_weight": "700"}),
        rx.el.div(
            text_input(lo, on_lo, placeholder="自動", class_name="mono", aria_label=f"{label}下限",
                       key=f"{key}-lo-{NoiseState.range_key}"),
            rx.el.span("～", class_name="muted"),
            text_input(hi, on_hi, placeholder="自動", class_name="mono", aria_label=f"{label}上限",
                       key=f"{key}-hi-{NoiseState.range_key}"),
            class_name="range",
        ),
        class_name="field",
    )


def _check(label: str, checked, on_change) -> rx.Component:
    """勾選框＋說明。"""
    return rx.el.label(
        rx.el.input(type="checkbox", checked=checked, on_change=on_change),
        rx.el.span(label, style={"font_family": "var(--body)"}),
        class_name="check full",
    )


def _plot_params() -> rx.Component:
    """d-3 參數：定義、依偏壓勾選、範圍帶、參考線、X／Y 範圍、按鈕。"""
    return rx.el.div(
        rx.el.div(
            rx.el.span("換算定義", class_name="label"),
            segmented(DEFINITIONS, NoiseState.definition, NoiseState.set_definition, label="換算定義"),
            rx.el.span("標準：a ÷ √(2×1.5×Δf)；儀器：a ÷ √f（光焱軟體，只供對照）", class_name="small muted"),
            class_name="field",
        ),
        rx.el.div(
            rx.el.span("依偏壓勾選", class_name="label"),
            rx.el.div(
                rx.foreach(NoiseState.bias_options,
                           lambda b: btn(b, small=True, variant=BtnVariant.GHOST, on_click=NoiseState.select_bias(b))),
                class_name="row", style={"gap": "6px"},
            ),
            class_name="field",
        ),
        _range("X 軸", "(Hz)", NoiseState.x_min, NoiseState.x_max, NoiseState.set_x_min, NoiseState.set_x_max, "nx"),
        _range("Y 軸", "(A/Hz^0.5)", NoiseState.y_min, NoiseState.y_max, NoiseState.set_y_min, NoiseState.set_y_max,
               "ny"),
        _check("顯示 n 次的範圍帶（n ≥ 2）", NoiseState.show_band, NoiseState.set_show_band(~NoiseState.show_band)),
        _check("顯示 Shot＋Thermal 參考線（取自 B 區 B-4，配對見 d-4）", NoiseState.show_refs,
               NoiseState.set_show_refs(~NoiseState.show_refs)),
        rx.el.div(
            btn("預覽", variant=BtnVariant.PRIMARY, class_name="grow", on_click=NoiseState.plot_noise,
                disabled=NoiseState.loading),
            btn("下載 PNG", disabled=NoiseState.plot_png == "",
                on_click=rx.download(url=NoiseState.plot_png, filename=PLOT_NAME)),
            btn("範圍改回自動", variant=BtnVariant.GHOST, on_click=NoiseState.reset_range),
            class_name="row nowrap full",
        ),
        class_name="params params-grid",
    )


def _plot_tab() -> rx.Component:
    """d-3：左邊勾選清單、右邊圖與參數。"""
    return rx.cond(
        NoiseState.has_job,
        plot_layout(
            curve_picker(NoiseState, _goto_grouping()),
            plot_figure(NoiseState.plot_png, "雜訊圖", NoiseState.loading),
            _plot_params(),
        ),
        _need_job(),
    )


# ---------- d-4 數值與參考線 ----------
def _pair_select(r: ReferenceRow) -> rx.Component:
    """手動配對選單：自動、不配對、B 區的每條暗電流。"""
    return rx.el.div(
        rx.el.select(
            rx.el.option("自動配對", value=AUTO_PAIR),
            rx.el.option("不配對", value=NO_PAIR),
            rx.foreach(NoiseState.pair_options, lambda n: rx.el.option(n, value=n)),
            value=r.choice, on_change=lambda v: NoiseState.set_pair(r.name, v), class_name="select",
            aria_label=f"{r.name} 的暗電流",
        ),
        chevron(),
        class_name="select-wrap", style={"min_width": "11em"},
    )


def _ref_row(r: ReferenceRow) -> rx.Component:
    """d-4 的一列；數值點一下就複製。"""
    return rx.el.tr(
        copy_cell(r.name, class_name="mono"),
        copy_cell(r.noise_1hz, style={"font_weight": "700"}),
        rx.el.td(_pair_select(r)),
        rx.el.td(
            rx.cond(r.dark_name != "", rx.el.span(r.dark_name, " ", tag(r.dark_instrument)), rx.el.span("—", class_name="muted")),
            rx.cond(r.note != "", rx.el.div(r.note, class_name="small muted")),
            class_name="small",
        ),
        copy_cell(r.rsh),
        copy_cell(r.dark_current),
        copy_cell(r.shot),
        copy_cell(r.thermal),
        copy_cell(r.total),
    )


def _values_tab() -> rx.Component:
    """d-4：每組 1 Hz 雜訊與理論白雜訊（Shot＋Thermal）。"""
    return rx.cond(
        NoiseState.has_job,
        rx.el.div(
            panel(
                "數值與參考線",
                rx.cond(
                    ~NoiseState.has_dark,
                    note("這個專案還沒有 B 區（暗電流）資料，所以沒有參考線。到「b. 暗電流」上傳後再回來。", kind="warn"),
                ),
                rx.el.div(
                    rx.el.table(
                        rx.el.thead(rx.el.tr(*[rx.el.th(h) for h in (
                            "組", "1 Hz 實測 (A/Hz^0.5)", "配對", "暗電流曲線", "Rsh (Ω)", "Id (A)", "Shot (A/Hz^0.5)",
                            "Thermal (A/Hz^0.5)", "Shot+Thermal (A/Hz^0.5)")])),
                        rx.el.tbody(rx.foreach(NoiseState.ref_rows, _ref_row)),
                        class_name="table compact",
                    ),
                    class_name="table-scroll", style={"max_height": "60vh"},
                ),
                end=[btn("重新整理", small=True, on_click=NoiseState.load_references, disabled=NoiseState.loading)],
            ),
            class_name="section",
        ),
        _need_job(),
    )


# ---------- 頁面 ----------
def _tab_content() -> rx.Component:
    """依目前的步驟顯示內容。"""
    return rx.match(
        NoiseState.tab,
        (NoiseTab.GROUPING.value, _grouping_tab()),
        (NoiseTab.PLOT.value, _plot_tab()),
        (NoiseTab.VALUES.value, _values_tab()),
        _upload_tab(),
    )


@rx.page(route=Route.NOISE.value, title="d. Noise｜lct.", on_load=[NoiseState.require_project, NoiseState.sync_project])
def noise_page() -> rx.Component:
    """Noise 頁面。"""
    return layout(
        page_top(
            page_head(
                "Noise", letter="d.",
                meta=rx.cond(
                    NoiseState.has_job,
                    rx.el.span(NoiseState.groups.length(), " 組 · ", NoiseState.pick_sample_count, " 個樣品 · ",
                               NoiseState.definition, "定義"),
                ),
            ),
            step_tabs(NoiseState.tab, TABS, NoiseState.set_tab),
        ),
        rx.el.div(_tab_content(), class_name="tab-panel plot-host"),
        busy(NoiseState.loading),
        wide=True,
        lock=NoiseState.plot_locked,
    )

"""C 區 EQE 頁面（lct. 設計）：c-1 上傳 → c-2 分組 → c-3 EQE 與積分電流 → c-4 R-plot。

- c-1 上傳：上傳、樣品清單、舊型命名（有舊型樣品時必須先命名才能分組）、下載 Excel
- c-2 分組：依專案條件分組，單位與 B 區相同（樣品）
- c-3、c-4：左邊勾選清單（與 B 區共用元件，兩頁共用同一份勾選），右邊圖與參數固定
"""
import reflex as rx

from front.components.grouping import grouping_adjust, grouping_settings
from front.components.layout import layout, page_head, page_top
from front.components.picker import curve_picker, plot_figure, plot_layout
from front.components.ui import BtnVariant, btn, busy, note, panel, step_tabs, tag, text_input, upload_box
from front.enums import EqeTab, Route
from front.states.eqe_state import ACCEPT, EQE_PLOT_NAME, RPLOT_NAME, UPLOAD_ID, EqeCurveRow, EqeState, NameEdit

TABS = [
    (EqeTab.UPLOAD.value, "c-1", "上傳", True),
    (EqeTab.GROUPING.value, "c-2", "分組", True),
    (EqeTab.EQE.value, "c-3", "EQE 與積分電流", True),
    (EqeTab.RPLOT.value, "c-4", "R-plot", True),
]


# ---------- 共用小元件 ----------
def _need_job() -> rx.Component:
    """尚未上傳時的提示。"""
    return note("請先在「c-1 上傳」上傳 EQE 檔。")


def _next(label: str, tab: EqeTab) -> rx.Component:
    """「下一步」按鈕。"""
    return btn(label, " →", variant=BtnVariant.PRIMARY, on_click=EqeState.go_to(tab.value))


def _table(headers: list[str], rows: rx.Component) -> rx.Component:
    """可捲動的小表格。"""
    return rx.el.div(
        rx.el.table(rx.el.thead(rx.el.tr(*[rx.el.th(h) for h in headers])), rx.el.tbody(rows),
                    class_name="table compact"),
        class_name="table-scroll",
    )


def _range(label: str, unit: str, lo, hi, on_lo, on_hi, key: str, hint: str = "") -> rx.Component:
    """一組「下限～上限」輸入框（留空為自動）；key 隨「範圍改回預設」改變，讓輸入框重新掛載。"""
    return rx.el.div(
        rx.el.span(label, " ", rx.el.span(unit, class_name="mono", style={"font_weight": "400"}),
                   class_name="label", style={"color": "var(--ink)", "font_weight": "700"}),
        rx.el.div(
            text_input(lo, on_lo, placeholder="自動", class_name="mono", aria_label=f"{label}下限",
                       key=f"{key}-lo-{EqeState.range_key}"),
            rx.el.span("～", class_name="muted"),
            text_input(hi, on_hi, placeholder="自動", class_name="mono", aria_label=f"{label}上限",
                       key=f"{key}-hi-{EqeState.range_key}"),
            class_name="range",
        ),
        rx.el.span(hint, class_name="small muted") if hint else rx.fragment(),
        class_name="field",
    )


# ---------- c-1 上傳 ----------
def _curve_row(c: EqeCurveRow) -> rx.Component:
    """樣品清單的一列。"""
    return rx.el.tr(
        rx.el.td(c.name, class_name="mono"),
        rx.el.td(c.instrument),
        rx.el.td(c.source, class_name="small"),
        rx.el.td(c.jsc, class_name="num"),
        rx.el.td(c.points, class_name="num"),
        rx.el.td(c.timestamp, class_name="small"),
        rx.el.td(c.bias, class_name="num"),
    )


def _name_row(row: NameEdit) -> rx.Component:
    """舊型命名的一列：原始編號、新名稱輸入框、狀態。"""
    return rx.el.tr(
        rx.el.td(row.original, class_name="mono"),
        rx.el.td(
            text_input(row.value, lambda v: EqeState.set_name_edit(row.original, v), class_name="mono",
                       aria_label=f"{row.original} 的名稱", key=f"name-{row.original}-{EqeState.name_key}",
                       style={"width": "14em", "height": "36px"}),
        ),
        rx.el.td(rx.cond(row.unnamed, tag("尚未命名", "warn"), tag(row.current, "ok"))),
    )


def _naming() -> rx.Component:
    """舊型樣品命名：自動偵測，有未命名的樣品時必須先命名才能分組。"""
    return panel(
        "舊型樣品命名",
        rx.cond(
            EqeState.needs_naming,
            note("偵測到舊型儀器（五樓）的樣品，名稱是自動編號，請先命名（例如 G3-1）才能分組。"
                 "名稱開頭的代號（G3）就是分組用的樣品。", kind="warn"),
            rx.el.p("舊型樣品都已命名。", class_name="small muted", style={"margin": "0"}),
        ),
        _table(["原始編號", "名稱", "狀態"], rx.foreach(EqeState.name_rows, _name_row)),
        rx.el.div(btn("儲存名稱", variant=BtnVariant.PRIMARY, on_click=EqeState.save_names,
                      disabled=EqeState.loading), class_name="row"),
        end=[],
    )


def _result() -> rx.Component:
    """讀取結果：數量、略過的檔案、樣品清單。"""
    return panel(
        "讀取結果",
        rx.el.div(
            rx.el.strong("讀取完成"),
            rx.el.span(EqeState.pick_sample_count, " 個樣品 · ", EqeState.pick_pixel_count, " 個 pixel",
                       class_name="mono small muted"),
            class_name="row",
        ),
        rx.cond(
            EqeState.skipped.length() > 0,
            note("以下檔案已略過（副檔名不支援）：", EqeState.skipped.join("、"), kind="warn"),
        ),
        _table(["名稱", "儀器", "來源檔", "Jsc (mA/cm²)", "點數", "量測時間", "偏壓 (V)"],
               rx.foreach(EqeState.curves, _curve_row)),
    )


def _excel() -> rx.Component:
    """下載整合 Excel 與下一步。"""
    return panel(
        "下載 Excel",
        rx.el.p("依儀器各輸出一份（Eqe_PD-QE.xlsx、Eqe_Old.xlsx），各含 Combined、Jsc 與每個樣品一個 sheet；"
                "兩種儀器都有時打包成 EQE.zip。舊型樣品以目前的名稱輸出。",
                class_name="small muted", style={"margin": "0"}),
        rx.el.div(
            btn("下載 Excel", on_click=EqeState.download_excel, disabled=EqeState.loading),
            rx.cond(
                EqeState.needs_naming,
                rx.el.span("命名完成後才能分組", class_name="small muted"),
                _next("下一步：分組", EqeTab.GROUPING),
            ),
            class_name="row",
        ),
    )


def _upload_tab() -> rx.Component:
    """c-1：上傳 → 讀取結果 →（有舊型時）命名 → Excel。"""
    return rx.el.div(
        panel(
            "上傳",
            upload_box(
                UPLOAD_ID, ACCEPT,
                "接受 .txt（新型 PD-QE）、.xls、.xlsx（舊型五樓）；儀器依內容自動判斷，舊型會自動跳過校正檔",
                EqeState.handle_upload(rx.upload_files(upload_id=UPLOAD_ID)),
                EqeState.loading,
            ),
        ),
        rx.cond(EqeState.has_job, _result()),
        rx.cond(EqeState.name_rows.length() > 0, _naming()),
        rx.cond(EqeState.has_job, _excel()),
        class_name="section", style={"gap": "40px"},
    )


# ---------- c-2 分組 ----------
def _grouping_tab() -> rx.Component:
    """依樣品分組（同 B 區）；舊型樣品未命名時不能分組。"""
    unit = "樣品"
    return rx.cond(
        EqeState.has_job,
        rx.cond(
            EqeState.needs_naming,
            note(
                rx.el.span("還有舊型樣品沒有命名：", EqeState.unnamed.join("、")),
                btn("前往 c-1 命名", small=True, on_click=EqeState.go_to(EqeTab.UPLOAD.value),
                    style={"align_self": "flex-start"}),
                kind="warn",
            ),
            rx.el.div(
                grouping_settings(EqeState, unit=unit),
                rx.cond(
                    EqeState.conditions.length() > 0,
                    grouping_adjust(EqeState, _next("下一步：EQE 與積分電流", EqeTab.EQE), unit=unit),
                ),
                class_name="section", style={"gap": "32px"},
            ),
        ),
        _need_job(),
    )


# ---------- c-3、c-4 畫圖 ----------
def _goto_grouping() -> rx.Component:
    """尚未分組時，勾選清單標題列的「前往分組」。"""
    return rx.cond(
        ~EqeState.groups_confirmed,
        btn("前往分組", variant=BtnVariant.GHOST, small=True, on_click=EqeState.go_to(EqeTab.GROUPING.value)),
    )


def _eqe_params() -> rx.Component:
    """c-3 參數：X 軸（使用者輸入，無預設）、EQE 軸（預設 0–100）、積分電流軸、右軸開關。"""
    # 兩欄：左 X 軸；右 EQE 軸與積分電流軸上下排；下方右軸開關與按鈕
    return rx.el.div(
        _range("X 軸", "(nm)", EqeState.eqe_x_min, EqeState.eqe_x_max, EqeState.set_eqe_x_min,
               EqeState.set_eqe_x_max, "ex", hint="留空為依數據自動"),
        rx.el.div(
            _range("EQE 軸", "(%)", EqeState.eqe_y_min, EqeState.eqe_y_max, EqeState.set_eqe_y_min,
                   EqeState.set_eqe_y_max, "ey"),
            _range("積分電流軸", "(mA/cm²)", EqeState.jsc_min, EqeState.jsc_max, EqeState.set_jsc_min,
                   EqeState.set_jsc_max, "ej", hint="預設 0–32.5，留空為自動"),
            class_name="stack",
        ),
        rx.el.label(
            rx.el.input(type="checkbox", checked=EqeState.show_jsc,
                        on_change=EqeState.set_show_jsc(~EqeState.show_jsc)),
            rx.el.span("顯示右軸（積分電流）", style={"font_family": "var(--body)"}),
            class_name="check full",
        ),
        _buttons(EqeState.plot_eqe, EqeState.eqe_png, EQE_PLOT_NAME, "範圍改回預設", EqeState.reset_eqe_range),
        class_name="params params-grid",
    )


def _buttons(on_plot, png, filename: str, reset_label: str, on_reset) -> rx.Component:
    """參數區底部按鈕：預覽、下載 PNG、範圍重設（佔滿兩欄）。"""
    return rx.el.div(
        btn("預覽", variant=BtnVariant.PRIMARY, class_name="grow", on_click=on_plot, disabled=EqeState.loading),
        btn("下載 PNG", disabled=png == "", on_click=rx.download(url=png, filename=filename)),
        btn(reset_label, variant=BtnVariant.GHOST, on_click=on_reset),
        class_name="row nowrap full",
    )


def _rplot_params() -> rx.Component:
    """c-4 參數：X、Y 範圍（留空為自動，Y 從 0 起）。"""
    return rx.el.div(
        _range("X 軸", "(nm)", EqeState.r_x_min, EqeState.r_x_max, EqeState.set_r_x_min,
               EqeState.set_r_x_max, "rx"),
        _range("Y 軸 SR", "(A/W)", EqeState.r_y_min, EqeState.r_y_max, EqeState.set_r_y_min,
               EqeState.set_r_y_max, "ry", hint="預設 0–0.6，留空為自動"),
        _buttons(EqeState.plot_rplot, EqeState.rplot_png, RPLOT_NAME, "範圍改回預設", EqeState.reset_r_range),
        class_name="params params-grid",
    )


def _plot_tab(figure: rx.Component, params: rx.Component) -> rx.Component:
    """c-3、c-4 共用版面：左邊勾選清單、右邊圖與參數。"""
    return rx.cond(
        EqeState.has_job,
        plot_layout(curve_picker(EqeState, _goto_grouping()), figure, params),
        _need_job(),
    )


# ---------- 頁面 ----------
def _tab_content() -> rx.Component:
    """依目前的步驟顯示內容。"""
    return rx.match(
        EqeState.tab,
        (EqeTab.GROUPING.value, _grouping_tab()),
        (EqeTab.EQE.value, _plot_tab(plot_figure(EqeState.eqe_png, "EQE 與積分電流", EqeState.loading), _eqe_params())),
        (EqeTab.RPLOT.value, _plot_tab(plot_figure(EqeState.rplot_png, "R-plot", EqeState.loading), _rplot_params())),
        _upload_tab(),
    )


@rx.page(route=Route.EQE.value, title="c. EQE｜lct.", on_load=[EqeState.require_project, EqeState.sync_project])
def eqe_page() -> rx.Component:
    """EQE 頁面。"""
    return layout(
        page_top(
            page_head(
                "EQE", letter="c.",
                meta=rx.cond(
                    EqeState.has_job,
                    rx.el.span(EqeState.pick_sample_count, " 個樣品 · ", EqeState.pick_pixel_count, " 個 pixel"),
                ),
            ),
            step_tabs(EqeState.tab, TABS, EqeState.set_tab),
        ),
        rx.el.div(_tab_content(), class_name="tab-panel plot-host"),
        busy(EqeState.loading),
        wide=True,
        lock=EqeState.plot_locked,
    )

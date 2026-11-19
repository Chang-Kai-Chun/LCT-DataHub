"""B 區暗電流頁面（lct. 設計）：b-1 整合 → b-2 分組 → b-3 暗電流圖（b-4 擷取值規劃中）。

- b-1 整合：上傳、有效面積確認、最低點偏移、下載 Excel
- b-2 分組：依專案條件分組（只影響暗電流圖勾選清單的排列，可略過）
- b-3 暗電流圖：左邊勾選清單（只有它捲動），右邊圖與參數固定
"""
import reflex as rx

from front.components.grouping import grouping_adjust, grouping_settings
from front.components.layout import layout, page_head, page_top
from front.components.picker import curve_picker, plot_figure, plot_layout
from front.components.ui import (
    BtnVariant, btn, busy, copy_cell, dialog, dialog_actions, note, panel, segmented, step_tabs, tag, text_input,
    upload_box,
)
from front.enums import DarkTab, Route, ShiftMode
from front.states.dark_state import ACCEPT, PLOT_NAME, UPLOAD_ID, DarkCurveRow, DarkState, ExtractRow

# 步驟標籤：(value, 代號, 名稱, 是否可點)
TABS = [
    (DarkTab.INTEGRATE.value, "b-1", "整合", True),
    (DarkTab.GROUPING.value, "b-2", "分組", True),
    (DarkTab.PLOT.value, "b-3", "暗電流圖", True),
    (DarkTab.EXTRACT.value, "b-4", "擷取值", True),
]


# ---------- 共用小元件 ----------
def _need_ready() -> rx.Component:
    """尚未上傳或面積未確認時的提示。"""
    return note("請先在「b-1 整合」完成上傳並確認有效面積。")


def _next(label: str, tab: DarkTab) -> rx.Component:
    """「下一步」按鈕。"""
    return btn(label, " →", variant=BtnVariant.PRIMARY, on_click=DarkState.go_to(tab.value))


def _table(headers: list[str], rows: rx.Component) -> rx.Component:
    """可捲動的小表格。"""
    return rx.el.div(
        rx.el.table(
            rx.el.thead(rx.el.tr(*[rx.el.th(h) for h in headers])),
            rx.el.tbody(rows),
            class_name="table compact",
        ),
        class_name="table-scroll",
    )


# ---------- b-1 整合 ----------
def _curve_row(c: DarkCurveRow) -> rx.Component:
    """曲線表的一列；面積是反推的加註。"""
    return rx.el.tr(
        rx.el.td(c.name, class_name="mono"),
        rx.el.td(c.instrument),
        rx.el.td(c.source, class_name="small"),
        rx.el.td(c.area, rx.cond(~c.area_from_file, rx.el.span(" 非檔內", class_name="small muted")), class_name="num"),
        rx.el.td(c.points, class_name="num"),
        rx.el.td(rx.cond(c.removed_points > 0, c.removed_points.to_string(), "—"), class_name="num"),
        rx.el.td(c.timestamp, class_name="small"),
    )


def _area_status() -> rx.Component:
    """有效面積狀態與「設定面積」按鈕。"""
    return rx.el.div(
        rx.el.span("有效面積", class_name="label"),
        rx.cond(
            DarkState.area_override != "",
            tag(f"已改為 {DarkState.area_override} cm²（J 已重算）", "warn"),
            rx.cond(
                DarkState.area_confirmed,
                rx.cond(
                    DarkState.area_uniform,
                    tag(f"{DarkState.area_uniform_value} cm²（全部一致）", "ok"),
                    tag("各檔不同，已選擇沿用檔內面積", "warn"),
                ),
                tag("尚未確認", "warn"),
            ),
        ),
        btn("設定面積", small=True, on_click=DarkState.open_area_dialog),
        class_name="row",
    )


def _result() -> rx.Component:
    """讀取結果：數量、略過的檔案、面積狀態、曲線表。"""
    return panel(
        "讀取結果",
        rx.el.div(
            rx.el.strong(rx.cond(DarkState.area_confirmed, "讀取完成", "讀取完成，請確認有效面積")),
            rx.el.span(DarkState.pick_sample_count, " 個樣品 · ", DarkState.pick_pixel_count, " 個 pixel",
                       class_name="mono small muted"),
            rx.cond(
                ~DarkState.area_confirmed,
                btn("確認有效面積", variant=BtnVariant.WARN, small=True, on_click=DarkState.open_area_dialog),
            ),
            class_name="row",
        ),
        rx.cond(
            DarkState.skipped.length() > 0,
            note("以下檔案已略過（副檔名不支援，或 Excel 檔名沒有 _abs）：", DarkState.skipped.join("、"), kind="warn"),
        ),
        _area_status(),
        _table(["名稱", "儀器", "來源檔", "面積 (cm²)", "點數", "截取點數", "測量時間"],
               rx.foreach(DarkState.curves, _curve_row)),
    )


def _shift_row(c: DarkCurveRow) -> rx.Component:
    """偏移表的一列：被偏移的曲線以橘色標示（需要使用者留意）。"""
    return rx.el.tr(
        rx.el.td(c.name, class_name="mono"),
        rx.el.td(c.instrument),
        rx.el.td(c.shift, class_name="num", style={"font_weight": rx.cond(c.is_shifted, "700", "400")}),
        rx.el.td(rx.cond(c.is_shifted, tag("已偏移", "warn"), rx.el.span("—", class_name="muted"))),
    )


def _shift() -> rx.Component:
    """最低點位置二選一；偏移時列出各曲線的偏移量。"""
    return panel(
        "最低點位置",
        segmented([m.value for m in ShiftMode], DarkState.shift_mode, DarkState.set_shift_mode, label="最低點位置"),
        rx.cond(
            DarkState.is_shift_mode,
            rx.el.p("整條曲線找 |J| 最低點，只平移電壓軸（V' = V − V_min），I、J 不動、不內插；原始電壓保留在 Excel。"
                    "圖的右上角會註記 shift。", class_name="small muted", style={"margin": "0"}),
            rx.el.p("保持儀器量到的原始電壓，不做任何平移。", class_name="small muted", style={"margin": "0"}),
        ),
        rx.cond(
            DarkState.is_shift_mode,
            rx.fragment(
                rx.el.span(DarkState.shifted_count, " ／ ", DarkState.curves.length(), " 個 pixel 被偏移（偏移量 0 的不算）",
                           class_name="mono small"),
                _table(["名稱", "儀器", "偏移量 (V)", "狀態"], rx.foreach(DarkState.curves, _shift_row)),
            ),
        ),
    )


def _excel() -> rx.Component:
    """下載整合 Excel（依儀器各一份，兩份時為 zip），以及下一步。"""
    return panel(
        "下載 Excel",
        rx.el.p("依儀器各輸出一份（Dark_PD-QE.xlsx、Dark_明志.xlsx），各含 Combined 加每條曲線一個 sheet；"
                "兩種儀器都有時打包成 Dark.zip。偏移時另含原始電壓與 Shift sheet。",
                class_name="small muted", style={"margin": "0"}),
        rx.el.div(
            btn("下載 Excel", on_click=DarkState.download_excel, disabled=DarkState.loading),
            _next("下一步：分組", DarkTab.GROUPING),
            class_name="row",
        ),
    )


def _integrate_tab() -> rx.Component:
    """b-1 整合：上傳 → 讀取結果 → 最低點位置 → Excel。"""
    return rx.el.div(
        panel(
            "上傳",
            upload_box(
                UPLOAD_ID, ACCEPT,
                "接受 .txt、.csv、.dat、.xlsx、.xls（Excel 檔名須含 _abs）；儀器（PD-QE／明志）依內容自動判斷",
                DarkState.handle_upload(rx.upload_files(upload_id=UPLOAD_ID)),
                DarkState.loading,
            ),
        ),
        rx.cond(DarkState.has_job, _result()),
        rx.cond(DarkState.ready, rx.fragment(_shift(), _excel())),
        class_name="section", style={"gap": "40px"},
    )


# ---------- 面積對話框 ----------
def _area_row(row) -> rx.Component:
    """面積表的一列。"""
    return rx.el.tr(rx.el.td(row.filename, class_name="small"), rx.el.td(row.areas, class_name="num"))


def _area_dialog() -> rx.Component:
    """有效面積確認：忽略並繼續，或改為指定面積（先顯示數據將被更動的警告）。"""
    return dialog(
        DarkState.area_dialog_open,
        rx.cond(DarkState.area_uniform, "確認有效面積", "有效面積不一致"),
        rx.cond(
            DarkState.area_uniform,
            rx.el.p("所有檔案的面積都是 ", DarkState.area_uniform_value, " cm²。", style={"margin": "0"}),
            rx.el.p("檔案中出現的面積值：", DarkState.area_values.join("、"), " cm²", style={"margin": "0"}),
        ),
        rx.cond(
            DarkState.derived_sources.length() > 0,
            note(
                rx.el.span("以下檔案（明志）沒有記錄面積，表中的面積是由 |I| ÷ J 反推的，請確認是否正確："),
                rx.el.strong(DarkState.derived_sources.join("、")),
                kind="warn",
            ),
        ),
        _table(["檔名", "面積 (cm²)"], rx.foreach(DarkState.area_rows, _area_row)),
        btn("忽略並繼續（沿用目前面積）", on_click=DarkState.area_ignore),
        rx.el.div(
            rx.el.span("改為", class_name="small"),
            text_input(DarkState.area_input, DarkState.set_area_input, class_name="mono", style={"width": "8em"},
                       aria_label="指定面積"),
            rx.el.span("cm²（套用到本次所有曲線）", class_name="small"),
            btn("套用", variant=BtnVariant.PRIMARY, small=True, on_click=DarkState.area_request_override),
            class_name="row",
        ),
        dialog_actions(btn("稍後再說", variant=BtnVariant.GHOST, on_click=DarkState.set_area_dialog_open(False))),
        on_close=DarkState.set_area_dialog_open(False),
    )


def _area_notice_dialog() -> rx.Component:
    """改面積前的警告：數據將被更動。"""
    return dialog(
        DarkState.area_notice_open,
        "數據將被更動",
        rx.el.p(DarkState.area_notice, style={"margin": "0", "white_space": "pre-wrap"}),
        rx.el.strong("新面積：", DarkState.area_input, " cm²"),
        dialog_actions(
            btn("取消", variant=BtnVariant.GHOST, on_click=DarkState.area_cancel_notice),
            btn("確認更動", variant=BtnVariant.PRIMARY, on_click=DarkState.area_confirm_override),
        ),
        on_close=DarkState.area_cancel_notice,
    )


# ---------- b-2 分組 ----------
def _grouping_tab() -> rx.Component:
    """依樣品分組（G1-1、G1-2 → G1）；只影響暗電流圖勾選清單的排列，不影響 Excel，可略過。"""
    unit = "樣品"
    return rx.cond(
        DarkState.ready,
        rx.cond(
            DarkState.samples.length() > 0,
            rx.el.div(
                note("分組只用來排列「b-3 暗電流圖」的勾選清單（同一條件的樣品放在一起），不影響 Excel；可以略過。"),
                grouping_settings(DarkState, unit=unit),
                rx.cond(
                    DarkState.conditions.length() > 0,
                    grouping_adjust(DarkState, _next("下一步：暗電流圖", DarkTab.PLOT), unit=unit),
                ),
                rx.el.div(btn("略過分組，直接畫圖 →", on_click=DarkState.open_skip_dialog), class_name="row"),
                class_name="section", style={"gap": "32px"},
            ),
            note("曲線名稱都無法辨識樣品（需以 G1、I10 這類代號開頭），無法分組。", kind="warn"),
        ),
        _need_ready(),
    )


def _skip_dialog() -> rx.Component:
    """「略過分組」的二次確認。"""
    return dialog(
        DarkState.skip_dialog_open,
        "確定略過分組？",
        rx.el.p(
            rx.cond(
                DarkState.groups_confirmed,
                "已確認的分組會保留，暗電流圖的勾選清單仍依分組排列。之後可隨時回來修改分組。",
                "暗電流圖的勾選清單會把全部樣品排在同一個區塊。之後可隨時回來分組。",
            ),
            style={"margin": "0"},
        ),
        dialog_actions(
            btn("返回分組", variant=BtnVariant.GHOST, on_click=DarkState.cancel_skip),
            btn("確定略過", variant=BtnVariant.PRIMARY, on_click=DarkState.confirm_skip),
        ),
        on_close=DarkState.cancel_skip,
    )


# ---------- b-3 暗電流圖 ----------
def _range(label: str, unit: str, lo, hi, on_lo, on_hi, key: str, hint: str = "") -> rx.Component:
    """一組「下限～上限」輸入框（留空為自動）；key 隨「範圍改回自動」改變，讓輸入框清空。"""
    return rx.el.div(
        rx.el.span(label, " ", rx.el.span(unit, class_name="mono", style={"font_weight": "400"}),
                   class_name="label", style={"color": "var(--ink)", "font_weight": "700"}),
        rx.el.div(
            text_input(lo, on_lo, placeholder="自動", class_name="mono", aria_label=f"{label}下限",
                       key=f"{key}-lo-{DarkState.range_key}"),
            rx.el.span("～", class_name="muted"),
            text_input(hi, on_hi, placeholder="自動", class_name="mono", aria_label=f"{label}上限",
                       key=f"{key}-hi-{DarkState.range_key}"),
            class_name="range",
        ),
        rx.el.span(hint, class_name="small muted") if hint else rx.fragment(),
        class_name="field",
    )


def _plot_params() -> rx.Component:
    """圖下方的參數：X、Y 範圍與按鈕。"""
    return rx.el.div(
        _range("X 軸", "(V)", DarkState.x_min, DarkState.x_max, DarkState.set_x_min, DarkState.set_x_max, "x"),
        _range("Y 軸 |J|", "(A/cm²)", DarkState.y_min, DarkState.y_max, DarkState.set_y_min, DarkState.set_y_max,
               "y", hint="對數座標，下限須大於 0，例如 1e-10"),
        rx.el.div(
            btn("預覽", variant=BtnVariant.PRIMARY, class_name="grow", on_click=DarkState.plot_dark,
                disabled=DarkState.loading),
            btn("下載 PNG", disabled=DarkState.plot_png == "",
                on_click=rx.download(url=DarkState.plot_png, filename=PLOT_NAME)),
            btn("範圍改回自動", variant=BtnVariant.GHOST, on_click=DarkState.reset_plot_range),
            class_name="row nowrap full",
        ),
        class_name="params params-grid",
    )


def _plot_tab() -> rx.Component:
    """b-3：左邊勾選清單、右邊圖與參數。"""
    goto_grouping = rx.cond(
        ~DarkState.groups_confirmed,
        btn("前往分組", variant=BtnVariant.GHOST, small=True, on_click=DarkState.go_to(DarkTab.GROUPING.value)),
    )
    return rx.cond(
        DarkState.ready,
        plot_layout(
            curve_picker(DarkState, goto_grouping),
            plot_figure(DarkState.plot_png, "暗電流疊圖", DarkState.loading),
            _plot_params(),
        ),
        _need_ready(),
    )


# ---------- b-4 擷取值 ----------
def _extract_row(r: ExtractRow) -> rx.Component:
    """擷取值的一列；數值點一下就複製。"""
    return rx.el.tr(
        copy_cell(r.name, class_name="mono"),
        rx.el.td(rx.cond(r.shifted, tag(r.shift, "warn"), rx.el.span("—", class_name="muted")), class_name="num"),
        copy_cell(r.rsh, style={"font_weight": "700"}),
        rx.cond(
            r.reference_rsh != "",
            copy_cell(r.reference_rsh, class_name="num muted"),
            rx.el.td(rx.el.span("—", class_name="muted"), class_name="num"),
        ),
        copy_cell(r.rsh_area),
        copy_cell(r.jd_0),
        copy_cell(r.jd_01),
        copy_cell(r.jd_05),
        rx.el.td(rx.cond(r.restored, tag(r.current_source, "warn"), r.current_source), class_name="small"),
    )


def _extract_tab() -> rx.Component:
    """b-4：每條曲線的 Rsh 與 0／−0.1／−0.5 V 的暗電流（E 區使用哪個電壓由 E 區選擇）。"""
    return rx.cond(
        DarkState.ready,
        rx.el.div(
            panel(
                "擷取值",
                rx.el.p(
                    "Rsh 取 −0.03～0.03 V 的 I-V 最小平方擬合（與 PD-QE 軟體相同）。曲線有偏移時一律用偏移後的電壓"
                    "（0 V＝|J| 最低點）。PD-QE 另列儀器值對照（未偏移＝表上 Rsh、偏移後＝表上 Rs）；明志沒有儀器值。"
                    "點一下數值即可複製。",
                    class_name="small muted", style={"margin": "0"},
                ),
                rx.el.div(
                    rx.el.table(
                        rx.el.thead(rx.el.tr(
                            *[rx.el.th(h) for h in ("名稱", "偏移量 (V)", "Rsh (Ω)", "儀器 Rsh (Ω)", "A·Rsh (Ω·cm²)",
                                                     "Jd 0 V", "Jd −0.1 V", "Jd −0.5 V", "電流來源")],
                        )),
                        rx.el.tbody(rx.foreach(DarkState.extract_rows, _extract_row)),
                        class_name="table compact",
                    ),
                    class_name="table-scroll", style={"max_height": "60vh"},
                ),
                rx.el.p("Jd 單位 A/cm²；Excel 的 Rsh_Jd sheet 另含 Id (A)。量測範圍不含該電壓時顯示 —。"
                        "明志 _abs 檔的電流是絕對值：有同名未取絕對值的檔就用它，沒有則以 |I| 最低點還原正負號（橘色）。",
                        class_name="small muted", style={"margin": "0"}),
                end=[btn("下載 Excel", small=True, on_click=DarkState.download_excel, disabled=DarkState.loading)],
            ),
            class_name="section",
        ),
        _need_ready(),
    )


# ---------- 頁面 ----------
def _tab_content() -> rx.Component:
    """依目前的步驟顯示內容。"""
    return rx.match(
        DarkState.tab,
        (DarkTab.GROUPING.value, _grouping_tab()),
        (DarkTab.PLOT.value, _plot_tab()),
        (DarkTab.EXTRACT.value, _extract_tab()),
        _integrate_tab(),
    )


@rx.page(
    route=Route.DARK.value, title="b. 暗電流｜lct.",
    on_load=[DarkState.require_project, DarkState.sync_project],
)
def dark_page() -> rx.Component:
    """暗電流頁面。"""
    return layout(
        page_top(
            page_head(
                "暗電流", letter="b.",
                meta=rx.cond(
                    DarkState.has_job,
                    rx.el.span(DarkState.pick_sample_count, " 個樣品 · ", DarkState.pick_pixel_count, " 個 pixel"),
                ),
            ),
            step_tabs(DarkState.tab, TABS, DarkState.set_tab),
        ),
        rx.el.div(_tab_content(), class_name="tab-panel plot-host"),
        _area_dialog(),
        _area_notice_dialog(),
        _skip_dialog(),
        busy(DarkState.loading),
        wide=True,
        lock=DarkState.plot_locked,
    )

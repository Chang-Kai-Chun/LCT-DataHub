"""B 區暗電流頁面：五個分頁依序操作（上傳與面積 → 最低點偏移 → Excel → 分組 → 暗電流圖）。"""
import reflex as rx

from front.components.grouping import grouping_adjust, grouping_settings
from front.components.layout import layout
from front.enums import DarkTab, Route, ShiftMode
from front.states.dark_state import ACCEPT, PLOT_NAME, UPLOAD_ID, DarkCurveRow, DarkState, DeviceColumn, PlotBlock


# ---------- 共用小元件 ----------
def _section(title: str, *children: rx.Component) -> rx.Component:
    """有標題的區塊。"""
    return rx.card(rx.vstack(rx.heading(title, size="3"), *children, spacing="3", width="100%"), width="100%")


def _need_ready() -> rx.Component:
    """尚未上傳或面積未確認時的提示。"""
    return rx.callout("請先在「上傳與面積」完成上傳並確認面積。", icon="info")


def _next_button(label: str, tab: DarkTab) -> rx.Component:
    """「下一步」按鈕：切到下一個分頁。"""
    return rx.button(label, rx.icon("arrow-right", size=18), size="3", on_click=DarkState.go_to(tab.value))


def _table(headers: list[str], body: rx.Component, max_height: str = "320px") -> rx.Component:
    """可捲動的小表格。"""
    return rx.scroll_area(
        rx.table.root(
            rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for h in headers])),
            rx.table.body(body),
            size="1",
        ),
        max_height=max_height,
        type="auto",
    )


# ---------- 1. 上傳與面積 ----------
def _curve_row(c: DarkCurveRow) -> rx.Component:
    """曲線表的一列；面積為反推時加註。"""
    return rx.table.row(
        rx.table.cell(c.name),
        rx.table.cell(rx.badge(c.instrument, variant="soft")),
        rx.table.cell(c.source),
        rx.table.cell(
            rx.hstack(
                rx.text(c.area),
                rx.cond(~c.area_from_file, rx.badge("非檔內", color_scheme="amber", size="1")),
                spacing="1",
                align="center",
            )
        ),
        rx.table.cell(c.points),
        rx.table.cell(rx.cond(c.removed_points > 0, c.removed_points.to_string(), "—")),
        rx.table.cell(c.timestamp),
    )


def _area_status() -> rx.Component:
    """有效面積狀態徽章與「設定面積」按鈕。"""
    return rx.hstack(
        rx.text("有效面積：", weight="bold", size="2"),
        rx.cond(
            DarkState.area_override != "",
            rx.badge(f"已改為 {DarkState.area_override} cm²（J 已重算）", color_scheme="amber"),
            rx.cond(
                DarkState.area_confirmed,
                rx.cond(
                    DarkState.area_uniform,
                    rx.badge(f"{DarkState.area_uniform_value} cm²（全部一致）", color_scheme="green"),
                    rx.badge("各檔不同，已選擇沿用檔內面積", color_scheme="amber"),
                ),
                rx.badge("尚未確認", color_scheme="red"),
            ),
        ),
        rx.button("設定面積", size="1", variant="soft", on_click=DarkState.open_area_dialog),
        align="center",
    )


def _result_card() -> rx.Component:
    """讀取結果（加粗框線與大標題），並提供「下一步：最低點偏移」。"""
    ok = DarkState.area_confirmed
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.cond(
                    ok,
                    rx.icon("circle-check", size=32, color=rx.color("green", 9)),
                    rx.icon("circle-alert", size=32, color=rx.color("amber", 9)),
                ),
                rx.vstack(
                    rx.heading(rx.cond(ok, "讀取完成", "讀取完成，請確認有效面積"), size="6"),
                    rx.text(f"{DarkState.curves.length()} 條曲線", size="3"),
                    spacing="0",
                ),
                rx.spacer(),
                rx.cond(
                    ok,
                    _next_button("下一步：最低點偏移", DarkTab.SHIFT),
                    rx.button("確認有效面積", size="3", color_scheme="amber", on_click=DarkState.open_area_dialog),
                ),
                align="center",
                width="100%",
            ),
            rx.divider(),
            rx.text(f"工作編號 {DarkState.job_id}", size="1", color=rx.color("gray", 10)),
            rx.cond(
                DarkState.skipped.length() > 0,
                rx.callout(
                    "以下檔案已略過（副檔名不支援，或 Excel 檔名沒有 _abs）：" + DarkState.skipped.join("、"),
                    icon="info", color_scheme="amber",
                ),
            ),
            _area_status(),
            _table(["名稱", "儀器", "來源檔", "面積 (cm²)", "點數", "截取點數", "測量時間"], rx.foreach(DarkState.curves, _curve_row)),
            spacing="3",
            width="100%",
        ),
        width="100%",
        border=rx.cond(ok, f"2px solid {rx.color('green', 8)}", f"2px solid {rx.color('amber', 8)}"),
        background=rx.cond(ok, rx.color("green", 2), rx.color("amber", 2)),
    )


def _upload_tab() -> rx.Component:
    """上傳暗電流檔（PD-QE TXT、明志 txt／csv／dat／xlsx／xls）。"""
    return rx.vstack(
        _section(
            "上傳暗電流檔",
            rx.upload(
                rx.vstack(
                    rx.icon("upload", size=28, color=rx.color("gray", 10)),
                    rx.text("拖曳檔案到這裡，或點選選擇檔案", size="2"),
                    rx.text(
                        "接受 .txt、.csv、.dat、.xlsx、.xls（Excel 檔名須含 _abs）；儀器（PD-QE／明志）依內容自動判斷",
                        size="1", color=rx.color("gray", 10),
                    ),
                    align="center",
                    spacing="1",
                    width="100%",
                ),
                id=UPLOAD_ID,
                multiple=True,
                accept=ACCEPT,
                border=f"2px dashed {rx.color('gray', 7)}",
                border_radius="8px",
                padding="1.5em",
                width="100%",
                cursor="pointer",
            ),
            rx.flex(
                rx.foreach(rx.selected_files(UPLOAD_ID), lambda name: rx.badge(name, variant="soft")),
                wrap="wrap",
                gap="1",
            ),
            rx.hstack(
                rx.button(
                    rx.icon("file-up", size=16), "上傳並讀取",
                    on_click=DarkState.handle_upload(rx.upload_files(upload_id=UPLOAD_ID)),
                    loading=DarkState.loading,
                ),
                rx.button("清除選擇", variant="soft", color_scheme="gray", on_click=rx.clear_selected_files(UPLOAD_ID)),
            ),
            rx.text("重新上傳會開始新的工作，目前的設定會清除。", size="1", color=rx.color("gray", 10)),
        ),
        rx.cond(DarkState.has_job, _result_card()),
        spacing="3",
        width="100%",
    )


def _area_row(row) -> rx.Component:
    """面積表的一列。"""
    return rx.table.row(rx.table.cell(row.filename), rx.table.cell(row.areas))


def _area_dialog() -> rx.Component:
    """有效面積確認視窗：忽略並繼續，或改為指定面積（先顯示數據將被更動的警告）。"""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.cond(DarkState.area_uniform, "確認有效面積", "有效面積不一致")),
            rx.vstack(
                rx.cond(
                    DarkState.area_uniform,
                    rx.text(f"所有檔案的面積都是 {DarkState.area_uniform_value} cm²。", size="2"),
                    rx.text("檔案中出現的面積值：" + DarkState.area_values.join("、") + " cm²", size="2"),
                ),
                # 明志檔內沒有面積：提示使用者這是反推值
                rx.cond(
                    DarkState.derived_sources.length() > 0,
                    rx.callout(
                        rx.vstack(
                            rx.text("以下檔案（明志）沒有記錄面積，表中的面積是由 |I| ÷ J 反推的，請確認是否正確："),
                            rx.text(DarkState.derived_sources.join("、"), weight="bold"),
                            spacing="1",
                        ),
                        icon="triangle-alert",
                        color_scheme="amber",
                    ),
                ),
                _table(["檔名", "面積 (cm²)"], rx.foreach(DarkState.area_rows, _area_row), max_height="240px"),
                rx.divider(),
                rx.button("忽略並繼續（沿用目前面積）", variant="soft", on_click=DarkState.area_ignore, width="100%"),
                rx.hstack(
                    rx.text("改為", size="2"),
                    rx.input(value=DarkState.area_input, on_change=DarkState.set_area_input, placeholder="例如 0.045", width="8em"),
                    rx.text("cm²（套用到本次所有曲線）", size="2"),
                    rx.button("套用", on_click=DarkState.area_request_override),
                    align="center",
                ),
                spacing="3",
                width="100%",
            ),
            rx.flex(rx.dialog.close(rx.button("稍後再說", variant="ghost", color_scheme="gray")), justify="end", margin_top="1em"),
            max_width="640px",
        ),
        open=DarkState.area_dialog_open,
        on_open_change=DarkState.set_area_dialog_open,
    )


def _area_notice_dialog() -> rx.Component:
    """改面積前的警告：數據將被更動（AREA_OVERRIDE_NOTICE）。"""
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("數據將被更動"),
            rx.alert_dialog.description(
                rx.vstack(
                    rx.text(DarkState.area_notice, white_space="pre-wrap"),
                    rx.text(f"新面積：{DarkState.area_input} cm²", weight="bold"),
                    spacing="2",
                ),
                as_child=True,
            ),
            rx.flex(
                rx.alert_dialog.cancel(rx.button("取消", variant="soft", color_scheme="gray", on_click=DarkState.area_cancel_notice)),
                rx.alert_dialog.action(rx.button("確認更動", color_scheme="red", on_click=DarkState.area_confirm_override)),
                spacing="3",
                justify="end",
                margin_top="1em",
            ),
        ),
        open=DarkState.area_notice_open,
    )


# ---------- 2. 最低點偏移 ----------
def _shift_row(c: DarkCurveRow) -> rx.Component:
    """偏移表的一列：被偏移的曲線以粗體標示。"""
    return rx.table.row(
        rx.table.cell(c.name),
        rx.table.cell(c.instrument),
        rx.table.cell(rx.text(c.shift, weight=rx.cond(c.is_shifted, "bold", "regular"))),
        rx.table.cell(rx.cond(c.is_shifted, rx.badge("已偏移", color_scheme="red", size="1"), rx.text("—"))),
    )


def _shift_tab() -> rx.Component:
    """B-2：最低點位置二選一，偏移時顯示各曲線的偏移量。"""
    return rx.cond(
        DarkState.ready,
        _section(
            "最低點位置處理",
            rx.segmented_control.root(
                *[rx.segmented_control.item(m.value, value=m.value) for m in ShiftMode],
                value=DarkState.shift_mode,
                on_change=DarkState.set_shift_mode,
            ),
            rx.cond(
                DarkState.is_shift_mode,
                rx.text(
                    "整條曲線找 |J| 最低點，只平移電壓軸（V' = V − V_min），I、J 不動、不內插；"
                    "原始電壓保留在 Excel。圖的右上角會註記 shift。",
                    size="2",
                ),
                rx.text("保持儀器量到的原始電壓，不做任何平移。", size="2"),
            ),
            rx.cond(
                DarkState.is_shift_mode,
                rx.vstack(
                    rx.text(
                        f"{DarkState.shifted_count} ／ {DarkState.curves.length()} 條曲線被偏移（偏移量 0 的不算）",
                        size="2", weight="bold",
                    ),
                    _table(["名稱", "儀器", "偏移量 (V)", "狀態"], rx.foreach(DarkState.curves, _shift_row), max_height="360px"),
                    spacing="2",
                    width="100%",
                ),
            ),
            rx.hstack(rx.spacer(), _next_button("下一步：下載 Excel", DarkTab.EXCEL), width="100%"),
        ),
        _need_ready(),
    )


# ---------- 3. Excel ----------
def _excel_tab() -> rx.Component:
    """下載整合 Excel：依儀器各一份（兩份時打包為 zip）。"""
    return rx.cond(
        DarkState.ready,
        _section(
            "下載整合 Excel",
            rx.text(
                "依儀器各輸出一份（Dark_PD-QE.xlsx、Dark_明志.xlsx），各含 Combined 加每條曲線一個 sheet；"
                "兩種儀器都有時打包成 Dark.zip。",
                size="2",
            ),
            rx.hstack(
                rx.text("目前設定：", size="2"),
                rx.badge(DarkState.shift_mode, variant="soft"),
                rx.cond(
                    DarkState.area_override != "",
                    rx.badge(f"面積 {DarkState.area_override} cm²", color_scheme="amber", variant="soft"),
                ),
                rx.cond(
                    DarkState.is_shift_mode,
                    rx.text("（Excel 會同時放原始與偏移後電壓，並加 Shift sheet）", size="1", color=rx.color("gray", 10)),
                ),
                align="center",
                spacing="2",
            ),
            rx.hstack(
                rx.button(
                    rx.icon("download", size=16), "下載 Excel", size="3",
                    on_click=DarkState.download_excel, loading=DarkState.loading,
                ),
                _next_button("下一步：分組", DarkTab.GROUPING),
                spacing="3",
            ),
        ),
        _need_ready(),
    )


# ---------- 4. 分組（畫面元件與 A 區共用：components/grouping.py） ----------
def _grouping_tab() -> rx.Component:
    """依元件分組（G1-1、G1-2 → G1）；只影響暗電流圖勾選清單的排列，可略過。"""
    unit = "元件"
    return rx.cond(
        DarkState.ready,
        rx.cond(
            DarkState.samples.length() > 0,
            rx.vstack(
                rx.callout(
                    "分組只用來排列「暗電流圖」的勾選清單（同一條件的元件放在一起），不影響 Excel；可以略過。",
                    icon="info",
                ),
                grouping_settings(DarkState, unit=unit),
                rx.cond(
                    DarkState.conditions.length() > 0,
                    grouping_adjust(DarkState, _next_button("下一步：暗電流圖", DarkTab.PLOT), unit=unit),
                ),
                rx.hstack(
                    rx.spacer(),
                    rx.button(
                        "略過分組，直接畫圖", rx.icon("arrow-right", size=16), variant="soft",
                        on_click=DarkState.open_skip_dialog,
                    ),
                    width="100%",
                ),
                spacing="3",
                width="100%",
            ),
            rx.callout("曲線名稱都無法辨識元件（需以 G1、I10 這類代號開頭），無法分組。", icon="info", color_scheme="amber"),
        ),
        _need_ready(),
    )


def _skip_dialog() -> rx.Component:
    """「略過分組」的二次確認視窗。"""
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("確定略過分組？"),
            rx.alert_dialog.description(
                rx.cond(
                    DarkState.groups_confirmed,
                    "已確認的分組會保留，暗電流圖的勾選清單仍依分組排列。之後可隨時回來修改分組。",
                    "暗電流圖的勾選清單會把全部元件排在同一個區塊。之後可隨時回來分組。",
                ),
            ),
            rx.flex(
                rx.alert_dialog.cancel(rx.button("返回分組", variant="soft", color_scheme="gray", on_click=DarkState.cancel_skip)),
                rx.alert_dialog.action(rx.button("確定略過", on_click=DarkState.confirm_skip)),
                spacing="3",
                justify="end",
                margin_top="1em",
            ),
        ),
        open=DarkState.skip_dialog_open,
    )


# ---------- 5. 暗電流圖 ----------
def _curve_check(name: rx.Var) -> rx.Component:
    """一條曲線的勾選框。"""
    return rx.checkbox(
        name, size="1", checked=DarkState.plot_selected.contains(name),
        on_change=lambda v: DarkState.toggle_plot_curve(name, v),
    )


def _device_column(col: DeviceColumn) -> rx.Component:
    """一個元件一直行：上方元件名稱（點選整行勾選／取消），下方是它的曲線。"""
    return rx.vstack(
        rx.button(col.device, size="1", variant="soft", width="100%", on_click=DarkState.toggle_plot_many(col.curves)),
        rx.foreach(col.curves, _curve_check),
        spacing="1",
        min_width="7.5em",
        padding_right="0.5em",
        border_right=f"1px solid {rx.color('gray', 4)}",
    )


def _plot_block(block: PlotBlock) -> rx.Component:
    """一個條件（或全部元件）的區塊：標題列＋元件直行（橫向排列，放不下時換列）。

    「暫時隱藏」：勾選保留，但這一區的曲線不畫進圖；區塊變淡並加上「已隱藏」標記。
    """
    hidden = DarkState.hidden_blocks.contains(block.title)
    return rx.box(
        rx.hstack(
            rx.text(block.title, weight="bold", size="2"),
            rx.badge(f"{block.columns.length()} 個元件、{block.curves.length()} 條", variant="soft", size="1"),
            rx.button("整組勾選／取消", size="1", variant="ghost", on_click=DarkState.toggle_plot_many(block.curves)),
            rx.spacer(),
            rx.cond(hidden, rx.badge("已隱藏（不畫進圖）", color_scheme="amber", size="1")),
            rx.button(
                rx.cond(hidden, rx.icon("eye", size=14), rx.icon("eye-off", size=14)),
                rx.cond(hidden, "取消隱藏", "暫時隱藏"),
                size="1",
                variant=rx.cond(hidden, "solid", "soft"),
                color_scheme=rx.cond(hidden, "amber", "gray"),
                on_click=DarkState.toggle_hide_block(block.title),
            ),
            align="center",
            width="100%",
            margin_bottom="0.5em",
        ),
        rx.flex(
            rx.foreach(block.columns, _device_column),
            wrap="wrap", gap="3", align="start",
            opacity=rx.cond(hidden, "0.4", "1"),
        ),
        padding="0.75em",
        border=rx.cond(hidden, f"1px dashed {rx.color('amber', 7)}", f"1px solid {rx.color('gray', 5)}"),
        border_radius="8px",
        width="100%",
    )



def _range_input(label: str, lo: rx.Var, hi: rx.Var, on_lo, on_hi, hint: str) -> rx.Component:
    """一組「下限～上限」輸入框（留空為自動）。"""
    return rx.hstack(
        rx.text(label, size="2", width="8em"),
        rx.input(value=lo, on_change=on_lo, placeholder="自動", width="7em"),
        rx.text("～"),
        rx.input(value=hi, on_change=on_hi, placeholder="自動", width="7em"),
        rx.text(hint, size="1", color=rx.color("gray", 10)),
        align="center",
    )


def _plot_tab() -> rx.Component:
    """B-3：勾選曲線、X／Y 範圍 → |J| 對數疊圖。"""
    return rx.cond(
        DarkState.ready,
        _section(
            "暗電流疊圖",
            rx.hstack(
                rx.button("全選", size="1", variant="soft", on_click=DarkState.select_all_plot),
                rx.button("全消", size="1", variant="soft", color_scheme="gray", on_click=DarkState.select_no_plot),
                rx.text(f"已選 {DarkState.plot_selected.length()} 條", size="2", color=rx.color("gray", 11)),
                rx.cond(
                    DarkState.hidden_selected_count > 0,
                    rx.text(f"（其中 {DarkState.hidden_selected_count} 條暫時隱藏）", size="2", color=rx.color("amber", 11)),
                ),
                rx.spacer(),
                rx.text("點元件名稱可整行勾選／取消", size="1", color=rx.color("gray", 10)),
                rx.cond(
                    ~DarkState.groups_confirmed,
                    rx.button(
                        "前往分組", size="1", variant="ghost",
                        on_click=DarkState.go_to(DarkTab.GROUPING.value),
                    ),
                ),
                align="center",
                width="100%",
            ),
            rx.scroll_area(
                rx.vstack(rx.foreach(DarkState.plot_blocks, _plot_block), spacing="2", width="100%"),
                max_height="420px",
                type="auto",
            ),
            _range_input("X 軸 (V)", DarkState.x_min, DarkState.x_max, DarkState.set_x_min, DarkState.set_x_max, ""),
            _range_input(
                "Y 軸 |J| (A/cm²)", DarkState.y_min, DarkState.y_max, DarkState.set_y_min, DarkState.set_y_max,
                "對數座標，下限須大於 0，例如 1e-10",
            ),
            rx.hstack(
                rx.button(rx.icon("chart-line", size=16), "預覽", on_click=DarkState.plot_dark, loading=DarkState.loading),
                rx.button("範圍改回自動", variant="ghost", on_click=DarkState.reset_plot_range),
                rx.cond(
                    DarkState.plot_png != "",
                    rx.button(
                        rx.icon("download", size=16), "下載 PNG", variant="soft",
                        on_click=rx.download(url=DarkState.plot_png, filename=PLOT_NAME),
                    ),
                ),
                align="center",
            ),
            rx.cond(DarkState.plot_png != "", rx.image(src=DarkState.plot_png, max_width="720px", width="100%")),
        ),
        _need_ready(),
    )


# ---------- 頁面 ----------
TABS = (
    (DarkTab.UPLOAD, "1 上傳與面積", _upload_tab),
    (DarkTab.SHIFT, "2 最低點偏移", _shift_tab),
    (DarkTab.EXCEL, "3 Excel", _excel_tab),
    (DarkTab.GROUPING, "4 分組", _grouping_tab),
    (DarkTab.PLOT, "5 暗電流圖", _plot_tab),
)


@rx.page(route=Route.DARK.value, title="B 暗電流｜LCT DataHub")
def dark_page() -> rx.Component:
    """暗電流頁面。"""
    return layout(
        rx.vstack(
            rx.hstack(
                rx.heading("B　暗電流", size="6"),
                rx.cond(DarkState.loading, rx.spinner()),
                align="center",
            ),
            rx.tabs.root(
                rx.tabs.list(*[rx.tabs.trigger(label, value=tab.value) for tab, label, _ in TABS]),
                *[rx.tabs.content(build(), value=tab.value, padding_top="1em") for tab, _, build in TABS],
                value=DarkState.tab,
                on_change=DarkState.set_tab,
                width="100%",
            ),
            _area_dialog(),
            _area_notice_dialog(),
            _skip_dialog(),
            spacing="3",
            width="100%",
            max_width="1100px",
        )
    )

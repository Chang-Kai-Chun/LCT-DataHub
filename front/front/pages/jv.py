"""A 區 JV 頁面：五個分頁依序操作（上傳與面積 → 分組 → Excel → Box 圖 → JV 曲線）。"""
import reflex as rx

from front.components.grouping import grouping_adjust, grouping_settings
from front.components.layout import layout, page_head
from front.components.ui import busy, upload_box
from front.enums import BOX_FILTER_PARAMS, Direction, DirectionMode, JVParam, JVTab, Route
from front.states.jv_state import UPLOAD_ID, BoxRow, FileRow, JVState


# ---------- 共用小元件 ----------
def _section(title: str, *children: rx.Component) -> rx.Component:
    """有標題的區塊。"""
    return rx.card(rx.vstack(rx.heading(title, size="3"), *children, spacing="3", width="100%"), width="100%")


def _labeled(label: str, control: rx.Component) -> rx.Component:
    """左標籤、右輸入框。"""
    return rx.hstack(rx.text(label, size="2", width="9em", flex_shrink="0"), control, align="center")


def _need_ready() -> rx.Component:
    """尚未上傳或面積未確認時的提示。"""
    return rx.callout("請先在「上傳與面積」完成上傳並確認面積。", icon="info")


# ---------- 1. 上傳與面積 ----------
def _file_row(f: FileRow) -> rx.Component:
    """檔案表的一列。"""
    return rx.table.row(
        rx.table.cell(f.filename), rx.table.cell(f.sample), rx.table.cell(f.direction), rx.table.cell(f.pixels),
    )


def _job_summary() -> rx.Component:
    """上傳結果：樣品、略過的檔案、面積狀態、檔案清單。"""
    return rx.vstack(
        rx.text(f"工作編號 {JVState.job_id}", size="1", color=rx.color("gray", 10)),
        rx.flex(rx.foreach(JVState.samples, lambda s: rx.badge(s, variant="outline")), wrap="wrap", gap="1"),
        rx.cond(
            JVState.skipped.length() > 0,
            rx.callout(
                "以下檔案不是 .csv，已略過：" + JVState.skipped.join("、"), icon="info", color_scheme="amber",
            ),
        ),
        # 面積狀態
        rx.hstack(
            rx.text("有效面積：", weight="bold", size="2"),
            rx.cond(
                JVState.area_override != "",
                rx.badge(f"已改為 {JVState.area_override} cm²（J、Jsc、PCE 已重算）", color_scheme="amber"),
                rx.cond(
                    JVState.area_uniform,
                    rx.badge(f"{JVState.area_uniform_value} cm²（全部一致）", color_scheme="green"),
                    rx.cond(
                        JVState.area_confirmed,
                        rx.badge("各檔不同，已選擇沿用檔內面積", color_scheme="amber"),
                        rx.badge("各檔不同，尚未確認", color_scheme="red"),
                    ),
                ),
            ),
            rx.button("設定面積", size="1", variant="soft", on_click=JVState.open_area_dialog),
            align="center",
        ),
        rx.scroll_area(
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("檔名"),
                        rx.table.column_header_cell("樣品"),
                        rx.table.column_header_cell("方向"),
                        rx.table.column_header_cell("Pixel"),
                    )
                ),
                rx.table.body(rx.foreach(JVState.files, _file_row)),
                size="1",
            ),
            max_height="320px",
            type="auto",
        ),
        spacing="3",
        width="100%",
    )


def _upload_tab() -> rx.Component:
    """上傳 JV CSV（檔名如 G1 FW 432.csv）。"""
    return rx.vstack(
        _section(
            "上傳 JV CSV",
            upload_box(
                UPLOAD_ID,
                {"text/csv": [".csv"]},
                "只接受 .csv，檔名格式如 G1 FW 432.csv 或 G1FW432.csv（空格可有可無）",
                JVState.handle_upload(rx.upload_files(upload_id=UPLOAD_ID)),
                JVState.loading,
            ),
        ),
        rx.cond(JVState.has_job, _result_card()),
        spacing="3",
        width="100%",
    )


def _next_button(label: str, tab: JVTab, disabled: rx.Var | bool = False) -> rx.Component:
    """「下一步」按鈕：切到下一個分頁。"""
    return rx.button(
        label, rx.icon("arrow-right", size=18), size="3", disabled=disabled, on_click=JVState.go_to(tab.value),
    )


def _result_card() -> rx.Component:
    """讀取結果（加粗框線與大標題），並提供「下一步：前往分組」。"""
    ok = JVState.area_confirmed
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.cond(
                    ok,
                    rx.icon("circle-check", size=32, color=rx.color("green", 9)),
                    rx.icon("circle-alert", size=32, color=rx.color("amber", 9)),
                ),
                rx.vstack(
                    rx.heading(
                        rx.cond(ok, "讀取完成", "讀取完成，請確認有效面積"),
                        size="6",
                    ),
                    rx.text(f"{JVState.files.length()} 個檔案、{JVState.samples.length()} 個樣品", size="3"),
                    spacing="0",
                ),
                rx.spacer(),
                rx.cond(
                    ok,
                    _next_button("下一步：前往分組", JVTab.GROUPING),
                    rx.button("確認有效面積", size="3", color_scheme="amber", on_click=JVState.open_area_dialog),
                ),
                align="center",
                width="100%",
            ),
            rx.divider(),
            _job_summary(),
            spacing="3",
            width="100%",
        ),
        width="100%",
        border=rx.cond(ok, f"2px solid {rx.color('green', 8)}", f"2px solid {rx.color('amber', 8)}"),
        background=rx.cond(ok, rx.color("green", 2), rx.color("amber", 2)),
    )


def _area_row(row) -> rx.Component:
    """面積表的一列。"""
    return rx.table.row(rx.table.cell(row.filename), rx.table.cell(row.areas))


def _area_dialog() -> rx.Component:
    """有效面積確認視窗：忽略並繼續，或改為指定面積（先顯示數據將被更動的警告）。"""
    return rx.dialog.root(
        rx.dialog.content(
            rx.dialog.title(rx.cond(JVState.area_uniform, "設定有效面積", "有效面積不一致")),
            rx.vstack(
                rx.cond(
                    JVState.area_uniform,
                    rx.text(f"所有檔案的面積都是 {JVState.area_uniform_value} cm²。", size="2"),
                    rx.text("檔案中出現的面積值：" + JVState.area_values.join("、") + " cm²", size="2"),
                ),
                rx.scroll_area(
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("檔名"), rx.table.column_header_cell("面積 (cm²)"),
                            )
                        ),
                        rx.table.body(rx.foreach(JVState.area_rows, _area_row)),
                        size="1",
                    ),
                    max_height="240px",
                    type="auto",
                ),
                rx.divider(),
                rx.button("忽略並繼續（沿用檔內面積）", variant="soft", on_click=JVState.area_ignore, width="100%"),
                rx.hstack(
                    rx.text("改為", size="2"),
                    rx.input(value=JVState.area_input, on_change=JVState.set_area_input, placeholder="例如 0.045", width="8em"),
                    rx.text("cm²（套用到本次所有檔案）", size="2"),
                    rx.button("套用", on_click=JVState.area_request_override),
                    align="center",
                ),
                spacing="3",
                width="100%",
            ),
            rx.flex(rx.dialog.close(rx.button("稍後再說", variant="ghost", color_scheme="gray")), justify="end", margin_top="1em"),
            max_width="640px",
        ),
        open=JVState.area_dialog_open,
        on_open_change=JVState.set_area_dialog_open,
    )


def _area_notice_dialog() -> rx.Component:
    """改面積前的警告：數據將被更動（AREA_OVERRIDE_NOTICE）。"""
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title("數據將被更動"),
            rx.alert_dialog.description(
                rx.vstack(
                    rx.text(JVState.area_notice, white_space="pre-wrap"),
                    rx.text("會重算的參數：" + JVState.recomputed_params.join("、"), size="2"),
                    rx.text(f"新面積：{JVState.area_input} cm²", weight="bold"),
                    spacing="2",
                ),
                as_child=True,
            ),
            rx.flex(
                rx.alert_dialog.cancel(rx.button("取消", variant="soft", color_scheme="gray", on_click=JVState.area_cancel_notice)),
                rx.alert_dialog.action(rx.button("確認更動", color_scheme="red", on_click=JVState.area_confirm_override)),
                spacing="3",
                justify="end",
                margin_top="1em",
            ),
        ),
        open=JVState.area_notice_open,
    )


# ---------- 2. 分組（畫面元件與 B 區共用：components/grouping.py） ----------
def _missing_callout() -> rx.Component:
    """條件中列出、但找不到該方向檔案的樣品。"""
    return rx.cond(
        JVState.missing.length() > 0,
        rx.callout(
            rx.vstack(
                rx.text("以下樣品列在條件中，但找不到該方向的檔案："),
                rx.foreach(
                    JVState.missing,
                    lambda m: rx.text(f"{m.condition}：{m.sample} {m.direction}", size="2"),
                ),
                spacing="1",
            ),
            icon="info",
            color_scheme="amber",
        ),
    )


def _grouping_tab() -> rx.Component:
    """分組：設定（平均分配／使用者自訂／自動）→ 點選微調 → 確定。"""
    return rx.cond(
        JVState.ready,
        rx.vstack(
            grouping_settings(JVState),
            rx.cond(
                JVState.conditions.length() > 0,
                grouping_adjust(JVState, _next_button("下一步：下載 Excel", JVTab.EXCEL), _missing_callout()),
            ),
            spacing="3",
            width="100%",
        ),
        _need_ready(),
    )


# ---------- 3. Excel ----------
def _excel_tab() -> rx.Component:
    """下載 ALL_Data.xlsx。"""
    return rx.cond(
        JVState.ready,
        _section(
            "下載整合 Excel（ALL_Data.xlsx）",
            rx.hstack(
                rx.text("參數 sheet 方向：", size="2"),
                rx.checkbox("FW", checked=JVState.excel_fw, on_change=JVState.set_excel_fw),
                rx.checkbox("RV", checked=JVState.excel_rv, on_change=JVState.set_excel_rv),
                spacing="3",
                align="center",
            ),
            rx.cond(
                ~JVState.groups_confirmed,
                rx.callout("尚未確認分組：全部樣品會視為同一個條件。", icon="info", color_scheme="amber"),
            ),
            rx.hstack(
                rx.button(
                    rx.icon("download", size=16), "下載 Excel", size="3",
                    on_click=JVState.download_excel, loading=JVState.loading,
                ),
                rx.cond(JVState.groups_confirmed, _next_button("下一步：Box 圖", JVTab.BOX)),
                spacing="3",
            ),
        ),
        _need_ready(),
    )


# ---------- 4. Box 圖 ----------
def _box_row(r: BoxRow) -> rx.Component:
    """Box 表的一列；Keep 可手動勾選。"""
    return rx.table.row(
        rx.table.cell(rx.checkbox(checked=r.keep, on_change=lambda v: JVState.toggle_keep(r.row, v))),
        rx.table.cell(r.condition),
        rx.table.cell(r.sample),
        rx.table.cell(r.direction),
        rx.table.cell(r.pixel),
        rx.table.cell(r.pce),
        rx.table.cell(r.voc),
        rx.table.cell(r.jsc),
        rx.table.cell(r.ff),
        rx.table.cell(r.rsh),
        color=rx.cond(r.keep, rx.color("gray", 12), rx.color("gray", 8)),
    )


def _range_inputs() -> rx.Component:
    """PCE、Voc、Jsc、FF 的篩選範圍（留空表示不限制）。"""
    return rx.grid(
        *[
            rx.hstack(
                rx.text(p.value, size="2", width="9em"),
                rx.input(
                    value=JVState.range_min[p.value], on_change=lambda v, k=p.value: JVState.set_range_min(k, v),
                    placeholder="下限", width="6em",
                ),
                rx.text("～"),
                rx.input(
                    value=JVState.range_max[p.value], on_change=lambda v, k=p.value: JVState.set_range_max(k, v),
                    placeholder="上限", width="6em",
                ),
                align="center",
            )
            for p in BOX_FILTER_PARAMS
        ],
        columns="2",
        spacing="2",
    )


def _per_sample_dirs() -> rx.Component:
    """逐樣品選擇 FW／RV。"""
    return rx.flex(
        rx.foreach(
            JVState.samples,
            lambda s: rx.hstack(
                rx.text(s, size="2", width="3em"),
                rx.select(
                    [d.value for d in Direction], value=JVState.sample_dirs[s],
                    on_change=lambda v: JVState.set_sample_dir(s, v), size="1",
                ),
                align="center",
            ),
        ),
        wrap="wrap",
        gap="3",
    )


def _box_tab() -> rx.Component:
    """Box 圖：方向 → 範圍篩選 → 確認表格（可手動保留）→ 畫圖。"""
    headers = ["Keep", "Condition", "Sample", "Dir", "Pixel", "PCE (%)", "Voc (V)", "Jsc", "FF (%)", "Rsh"]
    return rx.cond(
        JVState.groups_confirmed,
        rx.vstack(
            _section(
                "取用與篩選",
                _labeled(
                    "取用方向",
                    rx.select([m.value for m in DirectionMode], value=JVState.box_mode, on_change=JVState.set_box_mode),
                ),
                rx.cond(JVState.box_mode == DirectionMode.PER_SAMPLE.value, _per_sample_dirs()),
                rx.text("數值範圍篩選（留空表示不限制；全部留空等於略過）", size="2"),
                _range_inputs(),
                rx.hstack(
                    rx.button("套用篩選並顯示表格", on_click=JVState.refresh_box_table),
                    rx.button("清除手動保留", variant="soft", color_scheme="gray", on_click=JVState.reset_keep),
                ),
            ),
            rx.cond(
                JVState.box_rows.length() > 0,
                _section(
                    "篩選結果（取消勾選 Keep 可手動排除）",
                    rx.text(f"保留 {JVState.kept_count} ／ 共 {JVState.box_rows.length()} 筆", size="2"),
                    rx.scroll_area(
                        rx.table.root(
                            rx.table.header(rx.table.row(*[rx.table.column_header_cell(h) for h in headers])),
                            rx.table.body(rx.foreach(JVState.box_rows, _box_row)),
                            size="1",
                        ),
                        max_height="360px",
                        type="auto",
                    ),
                ),
            ),
            _section(
                "Box 圖",
                rx.hstack(
                    _labeled(
                        "參數",
                        rx.select([p.value for p in JVParam], value=JVState.box_param, on_change=JVState.set_box_param),
                    ),
                    rx.text("Y 軸", size="2"),
                    rx.input(value=JVState.box_ymin, on_change=JVState.set_box_ymin, placeholder="自動", width="6em"),
                    rx.text("～"),
                    rx.input(value=JVState.box_ymax, on_change=JVState.set_box_ymax, placeholder="自動", width="6em"),
                    align="center",
                    wrap="wrap",
                ),
                rx.hstack(
                    rx.button(rx.icon("chart-candlestick", size=16), "預覽", on_click=JVState.plot_box, loading=JVState.loading),
                    rx.cond(
                        JVState.box_png != "",
                        rx.button(
                            rx.icon("download", size=16), "下載 PNG", variant="soft",
                            on_click=rx.download(url=JVState.box_png, filename="Box.png"),
                        ),
                    ),
                ),
                rx.cond(JVState.box_png != "", rx.image(src=JVState.box_png, max_width="720px", width="100%")),
            ),
            rx.hstack(rx.spacer(), _next_button("下一步：JV 曲線", JVTab.CURVES), width="100%"),
            spacing="3",
            width="100%",
        ),
        rx.callout("請先在「分組」確定分組。", icon="info"),
    )


# ---------- 5. JV 曲線 ----------
def _curves_tab() -> rx.Component:
    """JV 曲線：勾選樣品、方向、Y 軸範圍 → 疊圖。"""
    return rx.cond(
        JVState.ready,
        _section(
            "JV 曲線疊圖",
            rx.hstack(
                rx.button("全選", size="1", variant="soft", on_click=JVState.select_all_curves),
                rx.button("全消", size="1", variant="soft", color_scheme="gray", on_click=JVState.select_no_curves),
            ),
            rx.flex(
                rx.foreach(
                    JVState.samples,
                    lambda s: rx.checkbox(
                        s, checked=JVState.curve_selected.contains(s),
                        on_change=lambda v: JVState.toggle_curve_sample(s, v),
                    ),
                ),
                wrap="wrap",
                gap="3",
            ),
            rx.hstack(
                rx.text("方向：", size="2"),
                rx.checkbox("FW（實線）", checked=JVState.curve_fw, on_change=JVState.set_curve_fw),
                rx.checkbox("RV（虛線）", checked=JVState.curve_rv, on_change=JVState.set_curve_rv),
                spacing="3",
                align="center",
            ),
            rx.hstack(
                rx.text("Y 軸 (mA/cm²)", size="2"),
                rx.input(value=JVState.curve_ymin, on_change=JVState.set_curve_ymin, width="6em"),
                rx.text("～"),
                rx.input(value=JVState.curve_ymax, on_change=JVState.set_curve_ymax, width="6em"),
                rx.button("預設", size="1", variant="ghost", on_click=JVState.reset_curve_range),
                align="center",
            ),
            rx.hstack(
                rx.button(rx.icon("chart-line", size=16), "預覽", on_click=JVState.plot_curves, loading=JVState.loading),
                rx.cond(
                    JVState.curve_png != "",
                    rx.button(
                        rx.icon("download", size=16), "下載 PNG", variant="soft",
                        on_click=rx.download(url=JVState.curve_png, filename="JV_curves.png"),
                    ),
                ),
            ),
            rx.cond(JVState.curve_png != "", rx.image(src=JVState.curve_png, max_width="720px", width="100%")),
        ),
        _need_ready(),
    )


# ---------- 頁面 ----------
TABS = (
    (JVTab.UPLOAD, "1 上傳與面積", _upload_tab),
    (JVTab.GROUPING, "2 分組", _grouping_tab),
    (JVTab.EXCEL, "3 Excel", _excel_tab),
    (JVTab.BOX, "4 Box 圖", _box_tab),
    (JVTab.CURVES, "5 JV 曲線", _curves_tab),
)


@rx.page(route=Route.JV.value, title="A JV｜LCT DataHub", on_load=[JVState.require_project, JVState.sync_project])
def jv_page() -> rx.Component:
    """JV 頁面。"""
    return layout(
        rx.vstack(
            page_head("JV", letter="a."),
            busy(JVState.loading),
            rx.tabs.root(
                rx.tabs.list(*[rx.tabs.trigger(label, value=tab.value) for tab, label, _ in TABS]),
                *[rx.tabs.content(build(), value=tab.value, padding_top="1em") for tab, _, build in TABS],
                value=JVState.tab,
                on_change=JVState.set_tab,
                width="100%",
            ),
            _area_dialog(),
            _area_notice_dialog(),
            spacing="3",
            width="100%",
            max_width="1100px",
        )
    )

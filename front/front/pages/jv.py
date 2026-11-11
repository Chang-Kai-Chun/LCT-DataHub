"""A 區 JV 頁面：五個分頁依序操作（上傳與面積 → 分組 → Excel → Box 圖 → JV 曲線）。"""
import reflex as rx

from front.components.layout import layout
from front.enums import BOX_FILTER_PARAMS, Direction, DirectionMode, GroupMode, JVParam, JVTab, Route
from front.states.jv_state import UPLOAD_ID, BoxRow, FileRow, GroupCond, JVState


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
        rx.hstack(
            rx.badge(f"工作 {JVState.job_id}", variant="soft"),
            rx.text(f"{JVState.files.length()} 個檔案、{JVState.samples.length()} 個樣品", size="2"),
            align="center",
        ),
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
            rx.upload(
                rx.vstack(
                    rx.icon("upload", size=28, color=rx.color("gray", 10)),
                    rx.text("拖曳檔案到這裡，或點選選擇檔案", size="2"),
                    rx.text("只接受 .csv，檔名格式如 G1 FW 432.csv", size="1", color=rx.color("gray", 10)),
                    align="center",
                    spacing="1",
                ),
                id=UPLOAD_ID,
                multiple=True,
                accept={"text/csv": [".csv"]},
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
                    on_click=JVState.handle_upload(rx.upload_files(upload_id=UPLOAD_ID)),
                    loading=JVState.loading,
                ),
                rx.button("清除選擇", variant="soft", color_scheme="gray", on_click=rx.clear_selected_files(UPLOAD_ID)),
            ),
            rx.text("重新上傳會開始新的工作，目前的分組與設定會清除。", size="1", color=rx.color("gray", 10)),
        ),
        rx.cond(JVState.has_job, _section("讀取結果", _job_summary())),
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


# ---------- 2. 分組 ----------
def _sample_chip(sample: rx.Var) -> rx.Component:
    """樣品卡片：點選後再按條件框的「放到這裡」。"""
    return rx.button(
        sample,
        size="1",
        variant=rx.cond(JVState.selected_sample == sample, "solid", "outline"),
        on_click=JVState.pick_sample(sample),
    )


def _cond_box(cond: GroupCond, index: rx.Var) -> rx.Component:
    """條件框。"""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.text(cond.name, weight="bold"),
                rx.badge(cond.samples.length(), variant="soft"),
                rx.spacer(),
                rx.icon_button(
                    rx.icon("trash-2", size=14), size="1", variant="ghost", color_scheme="red",
                    on_click=JVState.remove_condition(index),
                ),
                width="100%",
                align="center",
            ),
            rx.flex(rx.foreach(cond.samples, _sample_chip), wrap="wrap", gap="1", min_height="2em"),
            rx.button(
                "放到這裡", size="1", variant="soft", width="100%",
                disabled=JVState.selected_sample == "",
                on_click=JVState.move_to(index),
            ),
            spacing="2",
            width="100%",
        ),
    )


def _grouping_tab() -> rx.Component:
    """分組：預填（平均分配／自訂／自動）→ 點選調整 → 確定。"""
    return rx.cond(
        JVState.ready,
        rx.vstack(
            _section(
                "預填",
                _labeled(
                    "分組方式",
                    rx.select([m.value for m in GroupMode], value=JVState.group_mode, on_change=JVState.set_group_mode),
                ),
                _labeled(
                    "條件名稱",
                    rx.input(
                        value=JVState.group_names, on_change=JVState.set_group_names,
                        placeholder="以逗號分隔，例如 Ref, A, B", width="24em",
                    ),
                ),
                rx.cond(
                    JVState.group_mode == GroupMode.CUSTOM.value,
                    _labeled(
                        "自訂",
                        rx.text_area(
                            value=JVState.custom_text, on_change=JVState.set_custom_text,
                            placeholder="每行一個條件，例如\nRef: G1-G4\nA: G5-G8, G10",
                            width="24em", rows="5",
                        ),
                    ),
                ),
                rx.text(
                    "平均分配需要條件名稱；自訂用上方文字框（條件名稱欄不使用）；自動為每 4 個樣品一組。",
                    size="1", color=rx.color("gray", 10),
                ),
                rx.hstack(
                    rx.button("預填", on_click=JVState.preview_grouping),
                    rx.button("只建立空白條件", variant="soft", on_click=JVState.blank_grouping),
                ),
            ),
            _section(
                "調整分組",
                rx.text("點選樣品卡片（變成實心），再按條件框的「放到這裡」；按「移回這裡」放回未分配區。", size="2"),
                rx.hstack(
                    rx.input(value=JVState.new_cond_name, on_change=JVState.set_new_cond_name, placeholder="新條件名稱"),
                    rx.button(rx.icon("plus", size=14), "新增條件", variant="soft", on_click=JVState.add_condition),
                ),
                # 未分配區
                rx.card(
                    rx.vstack(
                        rx.hstack(
                            rx.text("未分配", weight="bold"),
                            rx.badge(JVState.unassigned.length(), color_scheme=rx.cond(JVState.unassigned.length() > 0, "red", "green")),
                            align="center",
                        ),
                        rx.flex(rx.foreach(JVState.unassigned, _sample_chip), wrap="wrap", gap="1", min_height="2em"),
                        rx.button(
                            "移回這裡", size="1", variant="soft", color_scheme="gray",
                            disabled=JVState.selected_sample == "", on_click=JVState.move_to_unassigned,
                        ),
                        spacing="2",
                        width="100%",
                    ),
                    background=rx.color("gray", 2),
                    width="100%",
                ),
                rx.grid(rx.foreach(JVState.conditions, _cond_box), columns="3", spacing="3", width="100%"),
                rx.hstack(
                    rx.button(rx.icon("check", size=16), "確定分組", on_click=JVState.confirm_grouping, disabled=~JVState.can_confirm_groups),
                    rx.cond(
                        JVState.groups_confirmed,
                        rx.badge("已確認", color_scheme="green"),
                        rx.cond(
                            JVState.unassigned.length() > 0,
                            rx.text("尚未分配：" + JVState.unassigned.join("、"), size="2", color=rx.color("red", 10)),
                        ),
                    ),
                    align="center",
                ),
                rx.cond(
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
                ),
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
            rx.button(rx.icon("download", size=16), "下載 Excel", on_click=JVState.download_excel, loading=JVState.loading),
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


@rx.page(route=Route.JV.value, title="A JV｜LCT DataHub")
def jv_page() -> rx.Component:
    """JV 頁面。"""
    return layout(
        rx.vstack(
            rx.hstack(
                rx.heading("A　JV", size="6"),
                rx.cond(JVState.loading, rx.spinner()),
                align="center",
            ),
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

"""G-5 報告輸出頁面（lct. 設計）：PD 報告（PowerPoint）。

- 封面資訊：標題（空白用專案名稱）、配方、前驅液濃度、元件結構圖（選用）
- 代表 pixel：依專案總覽的分組，每個條件選一顆（預設 D* 最高）；「不列入」不放進報告
- 下載：封面 → 暗電流 → EQE／R／D*(λ) → D* 表（0 V、−0.1 V）→ Noise；沒有資料的頁不產生
"""
import reflex as rx

from front.components.layout import layout, page_head
from front.components.ui import BtnVariant, btn, busy, chevron, note, panel, tag, text_input, upload_box
from front.enums import Route
from front.states.report_state import IMAGE_ACCEPT, IMAGE_UPLOAD_ID, NOT_INCLUDED, ConditionRow, ReportState


def _field(label: str, value, on_change, key: str, placeholder: str = "", hint: str = "") -> rx.Component:
    """標籤＋輸入框（非受控）。"""
    return rx.el.div(
        rx.el.span(label, class_name="label"),
        text_input(value, on_change, placeholder=placeholder, key=f"{key}-{ReportState.input_key}",
                   aria_label=label),
        rx.el.span(hint, class_name="small muted") if hint else rx.fragment(),
        class_name="field",
    )


def _cover() -> rx.Component:
    """封面資訊。"""
    return panel(
        "封面",
        rx.el.div(
            _field("標題", ReportState.title, ReportState.set_title, "title", placeholder=ReportState.project_name,
                   hint="空白則使用專案名稱"),
            _field("配方", ReportState.recipe, ReportState.set_recipe, "recipe",
                   placeholder="例：Cs0.025FA0.475MA0.5Sn0.5Pb0.5I2.925Br0.075", hint="元素後的數字在 PPT 中自動變成下標"),
            _field("前驅液濃度", ReportState.concentration, ReportState.set_concentration, "conc", placeholder="例：1.8M"),
            class_name="stack", style={"gap": "16px", "max_width": "640px"},
        ),
        rx.el.div(btn("儲存", variant=BtnVariant.PRIMARY, on_click=ReportState.save, disabled=ReportState.loading),
                  class_name="row"),
        rx.el.div(
            rx.el.span("元件結構圖（選用）", class_name="label"),
            rx.cond(
                ReportState.has_image,
                rx.el.div(tag("已上傳", "ok"), btn("移除", small=True, variant=BtnVariant.GHOST,
                                                 on_click=ReportState.clear_image), class_name="row"),
            ),
            upload_box(IMAGE_UPLOAD_ID, IMAGE_ACCEPT, "png、jpg；放在封面右側",
                       ReportState.upload_image(rx.upload_files(upload_id=IMAGE_UPLOAD_ID)), ReportState.loading),
            class_name="field",
        ),
    )


def _condition_row(c: ConditionRow) -> rx.Component:
    """一個條件的代表 pixel 選單。"""
    return rx.el.tr(
        rx.el.td(c.name, style={"font_weight": "700", "white_space": "nowrap"}),
        rx.el.td(
            rx.cond(
                c.empty,
                rx.el.span("這個條件沒有任何 pixel 的資料", class_name="small muted"),
                rx.el.div(
                    rx.el.select(
                        rx.el.option("不列入", value=NOT_INCLUDED),
                        rx.foreach(c.options, lambda o: rx.el.option(o.label, value=o.pixel)),
                        value=c.selected, on_change=lambda v: ReportState.set_selection(c.name, v),
                        class_name="select", aria_label=f"{c.name} 的代表 pixel",
                    ),
                    chevron(),
                    class_name="select-wrap", style={"max_width": "28em"},
                ),
            ),
        ),
    )


def _pixels() -> rx.Component:
    """每個條件的代表 pixel。"""
    return panel(
        "代表 pixel",
        rx.cond(
            ReportState.has_grouping,
            rx.el.div(
                rx.el.table(
                    rx.el.thead(rx.el.tr(rx.el.th("條件"), rx.el.th("代表 pixel"))),
                    rx.el.tbody(rx.foreach(ReportState.conditions, _condition_row)),
                    class_name="table compact",
                ),
                class_name="table-scroll", style={"max_height": "50vh"},
            ),
            note("專案還沒有總覽分組，無法依條件選擇 pixel。請先到「總覽」設定分組。", kind="warn"),
        ),
    )


def _download() -> rx.Component:
    """下載 PPT。"""
    return panel(
        "下載",
        rx.el.div(
            btn("下載 PD 報告（PPT）", variant=BtnVariant.PRIMARY, on_click=ReportState.download,
                disabled=ReportState.loading | (ReportState.included_count == 0)),
            rx.el.span(ReportState.included_count, " 個條件", class_name="mono small muted"),
            class_name="row",
        ),
    )


@rx.page(route=Route.REPORT.value, title="g. 報告輸出｜lct.", on_load=[ReportState.require_project, ReportState.load])
def report_page() -> rx.Component:
    """報告輸出頁面。"""
    return layout(
        page_head("報告輸出", letter="g.", meta=rx.el.span("PD 報告")),
        rx.el.div(_cover(), _pixels(), _download(), class_name="section", style={"gap": "40px"}),
        busy(ReportState.loading),
    )

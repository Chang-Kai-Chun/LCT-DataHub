"""專案大廳（G-4）：登入後、進入作業區之前的一頁，只做「選專案」。

- 不顯示 a.～g. 的側欄（還沒開專案，不能進作業區）
- 每次都重新選專案；清單可依「最新修改」或「名稱」排序
- f. 色票跟著使用者，不需要專案，入口放在右上角使用者旁邊
- 開啟或新增專案後進入作業區總覽（pages/overview.py）
"""
import reflex as rx

from front.components.error_dialog import error_dialog
from front.components.layout import theme_toggle
from front.components.ui import BtnVariant, btn, dialog, dialog_actions, mark, text_input, wordmark
from front.enums import ProjectSort, Route
from front.states.session import NameSlot, ProjectRow, ProjectsState


# ---------- 頂列 ----------
def _topbar() -> rx.Component:
    """字標；右上：f. 色票（跟著使用者，不需要專案）、使用者、深淺色、登出。"""
    return rx.el.header(
        rx.el.span(mark(), wordmark(), class_name="brand"),
        rx.el.div(
            rx.el.span(
                rx.el.span("f.", style={"font_family": "var(--head)", "font_weight": "800"}),
                "色票",
                rx.el.span("未開放", class_name="small"),
                class_name="muted", style={"display": "inline-flex", "gap": "6px", "align_items": "baseline"},
            ),
            rx.el.span(ProjectsState.user, style={"font_weight": "700"}),
            theme_toggle(),
            rx.el.a("登出", href="#", on_click=ProjectsState.logout),
            class_name="who",
        ),
        class_name="topbar",
    )


# ---------- 專案清單 ----------
def _sort_control() -> rx.Component:
    """排序：最新修改／名稱排序。"""
    return rx.el.div(
        *[
            rx.el.button(
                s.value, type="button",
                aria_pressed=rx.cond(ProjectsState.sort == s.value, "true", "false"),
                on_click=ProjectsState.set_sort(s.value),
            )
            for s in ProjectSort
        ],
        class_name="segmented", role="group", aria_label="排序",
    )


def _project_row(row: ProjectRow) -> rx.Component:
    """專案清單的一列；整列的「開啟」進入作業區。"""
    return rx.el.tr(
        rx.el.td(row.name, style={"font_weight": "700"}),
        rx.el.td(row.conditions),
        rx.el.td(row.sections, style={"font_family": "var(--head)", "font_weight": "800"}),
        rx.el.td(row.updated, class_name="mono small"),
        rx.el.td(
            btn("開啟 →", variant=BtnVariant.PRIMARY, small=True, on_click=ProjectsState.open_project(row.name)),
            style={"text_align": "right"},
        ),
    )


def _list_section() -> rx.Component:
    """我的專案：排序、新增、清單。"""
    return rx.el.section(
        rx.el.div(
            rx.el.h2("選擇專案", style={"font_family": "var(--head)", "font_weight": "600", "font_size": "24px"}),
            _sort_control(),
            rx.el.div(btn("＋ 新增專案", on_click=ProjectsState.open_new), class_name="end"),
            class_name="section-head",
        ),
        rx.cond(
            ProjectsState.rows.length() > 0,
            rx.el.div(
                rx.el.table(
                    rx.el.thead(rx.el.tr(*[rx.el.th(h) for h in ("專案", "條件", "已上傳", "最後修改", "")])),
                    rx.el.tbody(rx.foreach(ProjectsState.sorted_rows, _project_row)),
                    class_name="table",
                ),
                class_name="table-wrap",
            ),
            rx.el.p("還沒有專案，請按「新增專案」。", class_name="muted"),
        ),
        class_name="section",
    )


# ---------- 新增專案對話框：先問條件數量，再出現 N 個格子 ----------
def _name_slot(slot: NameSlot, index: rx.Var) -> rx.Component:
    """步驟 2 的一個條件名稱格。"""
    return rx.el.div(
        rx.el.label(f"條件 {slot.no}", html_for=f"cond-{index}", class_name="mono small muted",
                    style={"width": "4.5em", "flex": "none"}),
        text_input(slot.value, lambda v: ProjectsState.set_new_slot(index, v),
                   class_name="grow", id=f"cond-{index}"),
        class_name="row nowrap",
    )


def _new_dialog() -> rx.Component:
    """新增專案對話框；建立後直接進入作業區總覽。"""
    step1 = rx.el.div(
        rx.el.div(
            rx.el.label("專案名稱", html_for="proj-name"),
            text_input(ProjectsState.new_name, ProjectsState.set_new_name, id="proj-name", auto_focus=True),
            class_name="field",
        ),
        rx.el.div(
            rx.el.span("條件數量", class_name="label", id="count-label"),
            rx.el.div(
                rx.el.button("−", type="button", aria_label="減少", on_click=ProjectsState.dec_count),
                rx.el.output(ProjectsState.new_count, aria_live="polite"),
                rx.el.button("＋", type="button", aria_label="增加", on_click=ProjectsState.inc_count),
                class_name="stepper", role="group", aria_labelledby="count-label",
            ),
            class_name="field",
        ),
        dialog_actions(
            btn("取消", variant=BtnVariant.GHOST, on_click=ProjectsState.close_new),
            btn("下一步：輸入名稱", variant=BtnVariant.PRIMARY, on_click=ProjectsState.to_names),
        ),
        class_name="section", style={"gap": "20px"},
    )
    step2 = rx.el.div(
        rx.el.div(rx.foreach(ProjectsState.name_slots, _name_slot), class_name="section", style={"gap": "12px"}),
        rx.el.p("各區分組只能選用這些條件，之後可在總覽修改。", class_name="small muted", style={"margin": "0"}),
        dialog_actions(
            btn("← 上一步", variant=BtnVariant.GHOST, on_click=ProjectsState.to_count),
            btn("建立並開啟", variant=BtnVariant.PRIMARY, on_click=ProjectsState.create_project),
        ),
        class_name="section",
    )
    return dialog(
        ProjectsState.new_open, "新增專案",
        rx.cond(ProjectsState.new_step == 1, step1, step2),
        on_close=ProjectsState.close_new,
        step_text=ProjectsState.new_step_text,
    )


@rx.page(route=Route.PROJECTS.value, title="專案｜lct.", on_load=ProjectsState.load_projects)
def projects_page() -> rx.Component:
    """專案大廳（不顯示側欄）。"""
    return rx.el.div(
        rx.el.div(
            _topbar(),
            rx.el.header(rx.el.h1("專案", class_name="big-title"), class_name="page-head"),
            _list_section(),
            class_name="lobby",
        ),
        _new_dialog(),
        error_dialog(),
        class_name="lct-root",
    )

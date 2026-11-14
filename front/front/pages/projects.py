"""專案頁（G-4）：列出自己的專案、新增與開啟專案、修改目前專案的統一條件名稱。"""
import reflex as rx

from front.components.layout import layout
from front.enums import Route
from front.states.session import ConditionRow, ProjectRow, ProjectsState


def _section(title: str, *children: rx.Component) -> rx.Component:
    """有標題的區塊。"""
    return rx.card(rx.vstack(rx.heading(title, size="3"), *children, spacing="3", width="100%"), width="100%")


# ---------- 新增專案 ----------
def _create_card() -> rx.Component:
    """新增專案：名稱＋條件（一行一個，之後可修改）。"""
    return _section(
        "新增專案",
        rx.hstack(
            rx.text("專案名稱", size="2", width="6em", flex_shrink="0"),
            rx.input(
                value=ProjectsState.new_name, on_change=ProjectsState.set_new_name,
                placeholder="例如 2026-11 鈍化層比較", width="24em",
            ),
            align="center",
        ),
        rx.hstack(
            rx.text("條件名稱", size="2", width="6em", flex_shrink="0"),
            rx.text_area(
                value=ProjectsState.new_conditions, on_change=ProjectsState.set_new_conditions,
                placeholder="一行一個，例如：\nRef\n1 mol%\n2 mol%", rows="4", width="24em",
            ),
            align="start",
        ),
        rx.text(
            "各區分組時只能選用這些條件名稱，E 區與報告才能自動對應；之後可在下方修改。",
            size="1", color=rx.color("gray", 10),
        ),
        rx.button(rx.icon("folder-plus", size=16), "建立並開啟", on_click=ProjectsState.create_project),
    )


# ---------- 專案清單 ----------
def _project_row(row: ProjectRow) -> rx.Component:
    """專案清單的一列；目前開啟的專案以徽章標示。"""
    is_current = row.name == ProjectsState.project
    return rx.table.row(
        rx.table.cell(
            rx.hstack(
                rx.text(row.name, weight="bold"),
                rx.cond(is_current, rx.badge("目前專案", color_scheme="green", size="1")),
                spacing="2",
                align="center",
            )
        ),
        rx.table.cell(row.conditions),
        rx.table.cell(row.sections),
        rx.table.cell(row.created),
        rx.table.cell(
            rx.button("開啟", size="1", variant=rx.cond(is_current, "soft", "solid"),
                      on_click=ProjectsState.open_project(row.name)),
        ),
    )


def _list_card() -> rx.Component:
    """我的專案（新的在前）。"""
    return _section(
        "我的專案",
        rx.cond(
            ProjectsState.rows.length() > 0,
            rx.scroll_area(
                rx.table.root(
                    rx.table.header(rx.table.row(
                        *[rx.table.column_header_cell(h) for h in ("專案", "條件", "已上傳", "建立時間", "")]
                    )),
                    rx.table.body(rx.foreach(ProjectsState.rows, _project_row)),
                    size="1",
                    width="100%",
                ),
                max_height="360px",
                type="auto",
            ),
            rx.text("還沒有專案，請先在上方新增。", size="2", color=rx.color("gray", 10)),
        ),
    )


# ---------- 修改條件 ----------
def _cond_row(row: ConditionRow, index: rx.Var) -> rx.Component:
    """條件編輯的一列：名稱框、上下移、刪除；改過名稱或新增的列加註。"""
    return rx.hstack(
        rx.text(index + 1, size="2", width="1.5em"),
        rx.input(value=row.new, on_change=lambda v: ProjectsState.set_cond_row(index, v), width="16em"),
        rx.icon_button(rx.icon("arrow-up", size=14), size="1", variant="ghost",
                       on_click=ProjectsState.move_cond_row(index, -1)),
        rx.icon_button(rx.icon("arrow-down", size=14), size="1", variant="ghost",
                       on_click=ProjectsState.move_cond_row(index, 1)),
        rx.icon_button(rx.icon("trash-2", size=14), size="1", variant="ghost", color_scheme="red",
                       on_click=ProjectsState.remove_cond_row(index)),
        rx.cond(row.old == "", rx.badge("新增", color_scheme="green", size="1"),
                rx.cond(row.old != row.new, rx.badge(f"原名 {row.old}", color_scheme="amber", size="1"))),
        align="center",
    )


def _conditions_card() -> rx.Component:
    """目前專案的條件名稱：改名會一併更新各區已確認的分組；已被分組使用的條件不能刪。"""
    return _section(
        f"目前專案的條件：{ProjectsState.project}",
        rx.text(
            "改名會一併更新 A、B 等各區已確認的分組；已被分組使用的條件不能刪除（請先到該區修改分組）。按「儲存條件」才會生效。",
            size="2", color=rx.color("gray", 11),
        ),
        rx.foreach(ProjectsState.cond_rows, _cond_row),
        rx.hstack(
            rx.button(rx.icon("plus", size=14), "新增條件", variant="soft", on_click=ProjectsState.add_cond_row),
            rx.button(rx.icon("save", size=14), "儲存條件", on_click=ProjectsState.save_conditions),
            rx.button("放棄修改", variant="ghost", color_scheme="gray", on_click=ProjectsState.reset_cond_rows),
            spacing="2",
        ),
    )


@rx.page(route=Route.PROJECTS.value, title="專案｜LCT DataHub", on_load=ProjectsState.load_projects)
def projects_page() -> rx.Component:
    """專案頁。"""
    return layout(
        rx.vstack(
            rx.hstack(
                rx.heading("專案", size="6"),
                rx.cond(ProjectsState.loading, rx.spinner()),
                align="center",
            ),
            rx.text(
                "一次數據處理建立一個專案；A、B 等各區上傳的資料都放在目前開啟的專案中，下次開啟會帶出已有的結果。",
                size="2", color=rx.color("gray", 11),
            ),
            rx.cond(ProjectsState.has_project, _conditions_card()),
            _list_card(),
            _create_card(),
            spacing="3",
            width="100%",
            max_width="1000px",
        )
    )

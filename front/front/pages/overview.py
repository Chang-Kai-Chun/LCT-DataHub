"""作業區總覽：開啟專案後的第一頁。

顯示專案的統一條件（可修改）、總覽分組（各區可直接套用）與各區是否已上傳，每一區都可以直接點進去。
"""
from dataclasses import dataclass

import reflex as rx

from front.components.grouping import grouping_adjust, grouping_settings
from front.components.layout import layout, page_head
from front.components.ui import BtnVariant, btn, dialog, dialog_actions, text_input
from front.enums import Route, Section
from front.states.overview_state import OverviewGroupState
from front.states.session import ConditionRow, ProjectsState, SessionState


@dataclass(frozen=True)
class SectionCard:
    """總覽的一區入口；section 為 None 表示還沒有對應的資料（例如 d. Noise）。"""

    letter: str
    label: str
    route: Route | None
    section: Section | None


SECTION_CARDS = (
    SectionCard("a.", "JV", Route.JV, Section.JV),
    SectionCard("b.", "暗電流", Route.DARK, Section.DARK),
    SectionCard("c.", "EQE", Route.EQE, Section.EQE),
    SectionCard("d.", "Noise", None, None),
)


# ---------- 條件 ----------
def _conditions() -> rx.Component:
    """專案統一的條件（各區分組只能選用這些）。"""
    return rx.el.section(
        rx.el.div(
            rx.el.h2("條件"),
            rx.el.span("各區分組只能選用這些條件", class_name="small muted"),
            rx.el.div(btn("修改條件", small=True, on_click=ProjectsState.open_cond), class_name="end"),
            class_name="section-head",
        ),
        rx.cond(
            SessionState.project_conditions.length() > 0,
            rx.el.div(
                rx.foreach(SessionState.project_conditions, lambda c: rx.el.span(c, class_name="chip")),
                class_name="row", style={"gap": "8px"},
            ),
            rx.el.p("還沒有設定條件，分組前請先按「修改條件」新增。", class_name="muted", style={"margin": "0"}),
        ),
        class_name="section rule",
    )


# ---------- 總覽分組（與各區相同的分組畫面） ----------
def _sample_source() -> rx.Component:
    """樣品來源：各區已上傳的樣品＋手動加入（還沒上傳時可先加 G1-G16 建立分組）。"""
    return rx.el.div(
        rx.el.p(
            "樣品來自各區已上傳的資料",
            rx.cond(OverviewGroupState.section_samples.length() == 0, "（目前還沒有上傳任何區）", ""),
            "；也可以手動加入樣品。各區按「套用總覽的分組」時，只取該區有的樣品。",
            class_name="small muted", style={"margin": "0"},
        ),
        rx.el.div(
            text_input(OverviewGroupState.extra_text, OverviewGroupState.set_extra_text, class_name="mono",
                       placeholder="G1-G16", aria_label="手動加入樣品", key=OverviewGroupState.extra_key,
                       style={"width": "14em"}),
            btn("＋ 加入樣品", small=True, on_click=OverviewGroupState.add_extra),
            class_name="row",
        ),
        class_name="section", style={"gap": "8px"},
    )


def _grouping() -> rx.Component:
    """總覽分組：分組方式（預設平均分配，用格子微調）→ 確定後存成總覽分組，各區可直接套用。"""
    saved = rx.el.span("已存成總覽分組，各區可在分組步驟按「套用總覽的分組」", class_name="small muted")
    return rx.el.div(
        rx.el.section(rx.el.div(rx.el.h2("分組"), class_name="section-head"), _sample_source(),
                      class_name="section rule"),
        grouping_settings(OverviewGroupState, unit="樣品", show_project=False),
        rx.cond(OverviewGroupState.conditions.length() > 0, grouping_adjust(OverviewGroupState, saved)),
        class_name="section", style={"gap": "32px"},
    )


# ---------- 各區 ----------
def _section_card(card: SectionCard) -> rx.Component:
    """一區的入口：已上傳／尚未上傳；未開放的區顯示灰色。"""
    if card.route is None:
        return rx.el.div(
            rx.el.span(card.letter, class_name="letter"),
            rx.el.span(card.label),
            rx.el.span("未開放", class_name="small"),
            class_name="sec-card off",
        )
    uploaded = SessionState.project_jobs.contains(card.section.value)
    return rx.el.a(
        rx.el.span(card.letter, class_name="letter"),
        rx.el.span(card.label, style={"font_weight": "700"}),
        rx.cond(uploaded, rx.el.span("已上傳", class_name="tag ok"), rx.el.span("尚未上傳", class_name="small muted")),
        href=card.route.value,
        class_name="sec-card",
    )


def _sections() -> rx.Component:
    """各區入口。"""
    return rx.el.section(
        rx.el.div(rx.el.h2("各區資料"), class_name="section-head"),
        rx.el.div(*[_section_card(c) for c in SECTION_CARDS], class_name="sec-grid"),
        class_name="section rule",
    )


# ---------- 修改條件對話框 ----------
def _cond_row(row: ConditionRow, index: rx.Var) -> rx.Component:
    """條件編輯的一列：名稱框、上下移、刪除；新增或改名的列加註。"""
    return rx.el.div(
        rx.el.span(index + 1, class_name="mono small muted", style={"width": "1.5em"}),
        text_input(row.new, lambda v: ProjectsState.set_cond_row(index, v), class_name="grow",
                   aria_label=f"條件 {index + 1}", key=row.uid),
        btn("↑", variant=BtnVariant.GHOST, small=True, aria_label="上移", on_click=ProjectsState.move_cond_row(index, -1)),
        btn("↓", variant=BtnVariant.GHOST, small=True, aria_label="下移", on_click=ProjectsState.move_cond_row(index, 1)),
        btn("刪除", variant=BtnVariant.GHOST, small=True, on_click=ProjectsState.remove_cond_row(index)),
        rx.cond(
            row.old == "",
            rx.el.span("新增", class_name="tag ok"),
            rx.cond(row.old != row.new, rx.el.span(f"原名 {row.old}", class_name="tag warn")),
        ),
        class_name="row nowrap",
    )


def _cond_dialog() -> rx.Component:
    """修改專案的條件：改名同步各區分組；已被分組使用的條件不能刪。"""
    return dialog(
        ProjectsState.cond_open, "修改條件",
        rx.el.p(
            "改名會一併更新各區已確認的分組；已被分組使用的條件不能刪除（請先到該區修改分組）。",
            class_name="small muted", style={"margin": "0"},
        ),
        rx.el.div(rx.foreach(ProjectsState.cond_rows, _cond_row), class_name="section", style={"gap": "10px"}),
        btn("＋ 新增條件", small=True, on_click=ProjectsState.add_cond_row, style={"align_self": "flex-start"}),
        dialog_actions(
            btn("取消", variant=BtnVariant.GHOST, on_click=ProjectsState.close_cond),
            btn("儲存", variant=BtnVariant.PRIMARY, on_click=ProjectsState.save_conditions),
        ),
        on_close=ProjectsState.close_cond,
    )


@rx.page(
    route=Route.OVERVIEW.value, title="總覽｜lct.",
    on_load=[SessionState.require_project, ProjectsState.load_overview, OverviewGroupState.load],
)
def overview_page() -> rx.Component:
    """作業區總覽。"""
    return layout(
        page_head("總覽"),
        rx.el.p(SessionState.project, class_name="muted",
                style={"margin": "-16px 0 0", "font_family": "var(--head)", "font_size": "20px"}),
        _conditions(),
        rx.cond(SessionState.project_conditions.length() > 0, _grouping()),
        _sections(),
        _cond_dialog(),
    )

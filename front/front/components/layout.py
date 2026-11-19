"""作業區版面：左側導覽列（字標、目前專案、總覽與 a.～g.）＋右側內容，最外層放錯誤警告視窗。

作業區的頁面都需要先開啟專案（專案大廳在 pages/projects.py，不使用這個版面）。
f. 色票跟著使用者，不屬於專案，單獨一組並標示「個人」。
樣式在 assets/lct.css（.app、.sidebar、.nav、.content、.page-head）。
"""
from dataclasses import dataclass

import reflex as rx

from front.components.error_dialog import error_dialog
from front.components.ui import mark, wordmark
from front.enums import Route
from front.states.session import SessionState


@dataclass(frozen=True)
class NavItem:
    """導覽列的一個項目；letter 為空字串表示平台頁（專案）。"""

    label: str
    route: Route | None  # None：尚未開放
    letter: str = ""
    note: str = ""  # 右側小字（例如「個人」）


# 四組：總覽／量測資料 a.～d.／整合與輸出 e.、g.（屬於專案）／f. 色票（屬於使用者）
NAV_GROUPS: tuple[tuple[NavItem, ...], ...] = (
    (NavItem("總覽", Route.OVERVIEW),),
    (
        NavItem("JV", Route.JV, "a."),
        NavItem("暗電流", Route.DARK, "b."),
        NavItem("EQE", Route.EQE, "c."),
        NavItem("Noise", Route.NOISE, "d."),
    ),
    (
        NavItem("PD 數據整合", Route.INTEGRATION, "e."),
        NavItem("報告輸出", Route.REPORT, "g."),
    ),
    (NavItem("色票", None, "f.", note="個人"),),
)


def _nav_item(item: NavItem) -> rx.Component:
    """導覽列項目：目前頁面左側顯示橘色小色塊；未開放的顯示灰色。"""
    content = [rx.el.span(class_name="bar")]
    if item.letter:
        content.append(rx.el.span(item.letter, class_name="letter"))
    content.append(rx.el.span(item.label))  # 包成元素，懸浮時才能跟著位移
    if item.route is None:
        status = f"{item.note} · 未開放" if item.note else "未開放"
        return rx.el.li(rx.el.span(*content, rx.el.span(status, class_name="tag"), class_name="disabled"))
    if item.note:
        content.append(rx.el.span(item.note, class_name="tag"))
    active = rx.State.router.page.path == item.route.value
    return rx.el.li(
        rx.el.a(*content, href=item.route.value, class_name=rx.cond(active, "active", "")),
    )


def _session_box() -> rx.Component:
    """目前專案（大字）與切換專案；下方小字為使用者與登出。"""
    return rx.el.div(
        rx.el.span("目前專案", class_name="label"),
        rx.el.span(SessionState.project, class_name="project-name"),
        rx.el.a("← 切換專案", href=Route.PROJECTS.value, class_name="btn switch-btn"),
        rx.el.span(
            rx.el.span(SessionState.user),
            rx.el.a("登出", href="#", on_click=SessionState.logout),
            class_name="links muted",
        ),
        class_name="session",
    )


def theme_toggle() -> rx.Component:
    """深淺色切換鈕（Reflex 內建 color mode，會記住選擇）。"""
    return rx.el.button(
        rx.color_mode_cond(light="深色模式", dark="淺色模式"),
        type="button", class_name="theme-toggle", on_click=rx.toggle_color_mode,
    )


def sidebar() -> rx.Component:
    """左側導覽列。"""
    return rx.el.nav(
        rx.el.a(mark(), wordmark(), href=Route.OVERVIEW.value, class_name="brand"),
        _session_box(),
        *[rx.el.ul(*[_nav_item(i) for i in group], class_name="nav") for group in NAV_GROUPS],
        rx.el.div(class_name="spacer"),
        rx.el.div(theme_toggle(), class_name="row"),
        class_name="sidebar",
        aria_label="主選單",
    )


def page_head(title: str, letter: str = "", meta: rx.Component | None = None) -> rx.Component:
    """頁首：大字母（例如 b.）＋頁名；沒有字母時頁名本身放大（例如「專案」）。"""
    if letter:
        parts = [rx.el.span(letter, class_name="letter", aria_hidden="true"), rx.el.h1(title)]
    else:
        parts = [rx.el.h1(title, class_name="big-title")]
    if meta is not None:
        parts.append(rx.el.span(meta, class_name="meta"))
    return rx.el.header(*parts, class_name="page-head")


def page_top(*children: rx.Component) -> rx.Component:
    """頁首區塊（大標＋步驟標籤）：所有分頁大小、位置相同，捲動時固定在上方（2026-11-19）。"""
    return rx.el.div(*children, class_name="page-top")


def layout(*children: rx.Component, wide: bool = False, lock=False) -> rx.Component:
    """頁面外框：側欄＋內容＋警告視窗。

    wide：內容區放寬（繪圖頁）；lock：整頁不捲動、只有內部清單捲動（可傳 Var，例如目前在繪圖分頁時）。
    """
    root = rx.cond(lock, "lct-root app lock-scroll", "lct-root app") if not isinstance(lock, bool) else (
        "lct-root app lock-scroll" if lock else "lct-root app"
    )
    return rx.el.div(
        sidebar(),
        rx.el.main(*children, class_name="content wide" if wide else "content"),
        error_dialog(),
        class_name=root,
    )

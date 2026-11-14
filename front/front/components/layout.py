"""全站版面：左側導覽列＋右側內容，最外層放錯誤警告視窗。"""
from dataclasses import dataclass

import reflex as rx

from front.components.error_dialog import error_dialog
from front.enums import Route


@dataclass(frozen=True)
class NavItem:
    """導覽列的一個項目。"""

    label: str
    route: Route
    icon: str
    enabled: bool = True  # 尚未完成的功能先顯示為灰色


NAV_ITEMS = (
    NavItem("首頁", Route.HOME, "house"),
    NavItem("A　JV", Route.JV, "zap"),
    NavItem("B　暗電流", Route.DARK, "moon"),
    NavItem("C　EQE", Route.EQE, "sun", enabled=False),
)


def _nav_link(item: NavItem) -> rx.Component:
    """導覽列項目；目前頁面以底色標示。"""
    content = rx.hstack(rx.icon(item.icon, size=18), rx.text(item.label), spacing="2", align="center")
    if not item.enabled:
        return rx.box(
            rx.hstack(content, rx.badge("未開放", size="1", variant="soft"), justify="between"),
            padding="0.5em 0.75em",
            color=rx.color("gray", 8),
            width="100%",
        )
    active = rx.State.router.page.path == item.route.value
    return rx.link(
        rx.box(
            content,
            padding="0.5em 0.75em",
            border_radius="6px",
            background=rx.cond(active, rx.color("accent", 4), "transparent"),
            _hover={"background": rx.color("accent", 3)},
            width="100%",
        ),
        href=item.route.value,
        underline="none",
        color=rx.color("gray", 12),
        width="100%",
    )


def sidebar() -> rx.Component:
    """左側導覽列。"""
    return rx.vstack(
        rx.heading("LCT DataHub", size="5", padding="0.5em 0.75em"),
        rx.text("V6", size="1", color=rx.color("gray", 10), padding_left="0.75em", margin_top="-0.75em"),
        rx.divider(),
        *[_nav_link(item) for item in NAV_ITEMS],
        rx.spacer(),
        rx.color_mode.button(),
        width="220px",
        min_width="220px",
        height="100vh",
        position="sticky",
        top="0",
        padding="1em 0.5em",
        border_right=f"1px solid {rx.color('gray', 5)}",
        background=rx.color("gray", 2),
        spacing="1",
    )


def layout(*children: rx.Component) -> rx.Component:
    """頁面外框：側欄＋內容＋警告視窗。"""
    return rx.hstack(
        sidebar(),
        rx.box(*children, padding="1.5em 2em", width="100%", min_width="0"),
        error_dialog(),
        spacing="0",
        align="start",
        width="100%",
    )

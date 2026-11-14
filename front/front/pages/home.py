"""首頁：功能入口與 API 連線狀態。"""
import reflex as rx

from front import api_client as api
from front.components.layout import layout
from front.enums import Route
from front.settings import SETTINGS
from front.states.session import SECTION_LABELS, SessionState


class HomeState(rx.State):
    """首頁狀態：API 是否在線。"""

    api_checked: bool = False
    api_online: bool = False

    @rx.event
    async def check_api(self) -> None:
        """呼叫 /api/health 確認 FastAPI 在線。"""
        self.api_online = await api.health()
        self.api_checked = True


def _api_status() -> rx.Component:
    """API 連線狀態卡片。"""
    return rx.card(
        rx.hstack(
            rx.cond(
                HomeState.api_checked,
                rx.cond(
                    HomeState.api_online,
                    rx.badge("API 在線", color_scheme="green", size="2"),
                    rx.badge("API 未連線", color_scheme="red", size="2"),
                ),
                rx.badge("檢查中…", color_scheme="gray", size="2"),
            ),
            rx.text(SETTINGS.api_url, size="2", color=rx.color("gray", 10)),
            rx.spacer(),
            rx.button(rx.icon("refresh-cw", size=14), "重新檢查", size="1", variant="soft", on_click=HomeState.check_api),
            align="center",
            width="100%",
        ),
        rx.cond(
            HomeState.api_checked & ~HomeState.api_online,
            rx.text("請在專案根目錄執行 uv run lct-api 啟動 FastAPI。", size="2", margin_top="0.5em"),
        ),
        width="100%",
        max_width="640px",
    )


def _feature(title: str, desc: str, route: Route | None) -> rx.Component:
    """功能卡片；route 為 None 表示尚未開放。"""
    card = rx.card(
        rx.heading(title, size="4"),
        rx.text(desc, size="2", color=rx.color("gray", 11)),
        rx.badge("未開放", variant="soft") if route is None else rx.fragment(),
        width="100%",
    )
    return rx.link(card, href=route.value, underline="none") if route else card


def _project_card() -> rx.Component:
    """目前專案：條件與已上傳資料的區。"""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.icon("folder-open", size=20),
                rx.heading(SessionState.project, size="4"),
                rx.spacer(),
                rx.link(rx.button("切換專案", size="1", variant="soft"), href=Route.PROJECTS.value),
                align="center",
                width="100%",
            ),
            rx.text(
                "條件：" + rx.cond(
                    SessionState.project_conditions.length() > 0,
                    SessionState.project_conditions.join("、"),
                    "（尚未設定，分組前請先到專案頁新增）",
                ),
                size="2",
            ),
            rx.hstack(
                rx.text("已上傳：", size="2"),
                *[
                    rx.cond(
                        SessionState.project_jobs.contains(key),
                        rx.badge(label, color_scheme="green", variant="soft"),
                        rx.badge(label, color_scheme="gray", variant="outline"),
                    )
                    for key, label in SECTION_LABELS.items()
                ],
                spacing="2",
                align="center",
            ),
            spacing="2",
            width="100%",
        ),
        width="100%",
        max_width="640px",
    )


@rx.page(route=Route.HOME.value, title="LCT DataHub", on_load=[SessionState.require_project, HomeState.check_api])
def home() -> rx.Component:
    """首頁。"""
    return layout(
        rx.vstack(
            rx.heading("LCT DataHub", size="7"),
            rx.text("上傳量測檔案，整合成 Excel 並繪圖。", color=rx.color("gray", 11)),
            _project_card(),
            _api_status(),
            rx.grid(
                _feature("A　JV", "JV 整合、分組、ALL_Data、Box 圖、JV 曲線", Route.JV),
                _feature("B　暗電流", "暗電流整合、最低點偏移、暗電流圖", Route.DARK),
                _feature("C　EQE", "EQE 整合、EQE 加積分電流圖、R-plot", None),
                columns="3",
                spacing="3",
                width="100%",
                max_width="900px",
            ),
            spacing="4",
        )
    )

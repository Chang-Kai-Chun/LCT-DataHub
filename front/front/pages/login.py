"""登入頁（G-4）：選擇使用者或新增，沒有密碼；瀏覽器記住上次選的使用者。"""
import reflex as rx

from front.components.error_dialog import error_dialog
from front.enums import Route
from front.states.session import LoginState


def _login_card() -> rx.Component:
    """登入卡片：下拉選單＋登入；下方新增使用者。"""
    return rx.card(
        rx.vstack(
            rx.heading("LCT DataHub", size="7"),
            rx.text("請選擇使用者", size="2", color=rx.color("gray", 11)),
            rx.cond(
                LoginState.users.length() > 0,
                rx.hstack(
                    rx.select(
                        LoginState.users, value=LoginState.choice, on_change=LoginState.set_choice,
                        placeholder="選擇使用者", size="3", width="100%",
                    ),
                    rx.button(rx.icon("log-in", size=16), "登入", size="3", on_click=LoginState.login),
                    width="100%",
                ),
                rx.callout("還沒有任何使用者，請先在下方新增。", icon="info"),
            ),
            rx.divider(),
            rx.text("新增使用者", weight="bold", size="2"),
            rx.hstack(
                rx.input(
                    value=LoginState.new_user, on_change=LoginState.set_new_user,
                    placeholder="例如 Gino", width="100%",
                ),
                rx.button(rx.icon("user-plus", size=16), "新增", variant="soft", on_click=LoginState.create_user),
                width="100%",
            ),
            rx.text(
                "名稱會成為資料夾名稱，不可包含 \\ / : * ? \" < > |。移除使用者請在主機上刪除 data/users 中的資料夾。",
                size="1", color=rx.color("gray", 10),
            ),
            spacing="3",
            width="100%",
        ),
        width="100%",
        max_width="420px",
        size="4",
    )


@rx.page(route=Route.LOGIN.value, title="登入｜LCT DataHub", on_load=LoginState.load_users)
def login_page() -> rx.Component:
    """登入頁（不顯示側欄）。"""
    return rx.center(
        rx.cond(LoginState.loading, rx.spinner(size="3"), _login_card()),
        error_dialog(),
        min_height="100vh",
        padding="1em",
    )

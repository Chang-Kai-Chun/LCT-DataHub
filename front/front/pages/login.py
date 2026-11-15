"""登入頁（G-4）與網站入口（/）。

左：字標 lct.；右：深藍登入區（選擇使用者或新增）。沒有密碼；瀏覽器記住上次選的使用者。
"""
import reflex as rx

from front.components.error_dialog import error_dialog
from front.components.layout import theme_toggle
from front.components.ui import BtnVariant, btn, mark, select, text_input
from front.enums import Route
from front.states.session import LoginState, SessionState


def _hero() -> rx.Component:
    """左側：小記號、版本與大字標。"""
    return rx.el.section(
        rx.el.div(
            rx.el.div(
                mark(),
                rx.el.span("LCT DATAHUB · V6", class_name="mono small muted", style={"letter_spacing": ".08em"}),
                class_name="row",
            ),
            theme_toggle(),
            class_name="row",
            style={"justify_content": "space-between"},
        ),
        rx.el.div(
            rx.el.p("lct", rx.el.span(".", class_name="dot"), class_name="wordmark"),
            rx.el.p(
                "實驗室量測資料整合與繪圖：JV、暗電流、EQE、Noise。",
                class_name="muted", style={"margin": "0", "font_size": "18px", "max_width": "30em"},
            ),
            style={"display": "flex", "flex_direction": "column", "gap": "20px"},
        ),
        class_name="hero",
    )


def _panel() -> rx.Component:
    """右側：深藍登入區。選單佔剩下的寬度、按鈕固定寬度，不會被擠出去。"""
    return rx.el.section(
        rx.el.h1("登入", id="login-title"),
        rx.el.div(
            rx.el.label("使用者", html_for="user-select"),
            rx.cond(
                LoginState.users.length() > 0,
                rx.el.div(
                    select(
                        LoginState.users, LoginState.choice, LoginState.set_choice,
                        class_name="grow", id="user-select", style={"font_size": "18px"},
                    ),
                    btn("LOGIN", variant=BtnVariant.PRIMARY, on_click=LoginState.login),
                    class_name="row nowrap",
                ),
                rx.el.p("還沒有任何使用者，請先在下方新增。", class_name="small muted", style={"margin": "0"}),
            ),
            class_name="field",
        ),
        rx.el.hr(),
        rx.el.div(
            rx.el.label("新增使用者", html_for="new-user"),
            rx.el.div(
                # key 隨使用者數量改變：新增成功後輸入框重新掛載並清空（輸入框為非受控）
                text_input(LoginState.new_user, LoginState.set_new_user, placeholder="名稱",
                           class_name="grow", id="new-user", key=LoginState.users.length()),
                btn("新增", on_click=LoginState.create_user),
                class_name="row nowrap",
            ),
            rx.el.p(
                '名稱會成為資料夾名稱，不可包含 \\ / : * ? " < > |。移除使用者請在主機上刪除 data/users 中的資料夾。',
                class_name="small muted", style={"margin": "0"},
            ),
            class_name="field",
        ),
        class_name="panel",
        aria_labelledby="login-title",
    )


@rx.page(route=Route.LOGIN.value, title="登入｜lct.", on_load=LoginState.load_users)
def login_page() -> rx.Component:
    """登入頁（不顯示側欄）。"""
    return rx.el.div(
        rx.el.div(_hero(), _panel(), class_name="login"),
        error_dialog(),
        class_name="lct-root",
    )


@rx.page(route=Route.HOME.value, title="lct.", on_load=SessionState.go_entry)
def entry_page() -> rx.Component:
    """網站入口：依登入狀態轉到登入頁或專案頁。"""
    return rx.el.div(class_name="lct-root")

"""錯誤警告視窗：檔案錯誤完整顯示檔名、原因、期望、實際四項（3-5 共通）。"""
import reflex as rx

from front.states.error_state import ErrorState


def _field(label: str, value: rx.Var) -> rx.Component:
    """一列「標題：內容」。"""
    return rx.hstack(
        rx.text(label, weight="bold", width="4em", flex_shrink="0"),
        rx.text(value, white_space="pre-wrap", word_break="break-all"),
        align="start",
        width="100%",
    )


def error_dialog() -> rx.Component:
    """全站共用的警告視窗（放在版面最外層）。"""
    return rx.alert_dialog.root(
        rx.alert_dialog.content(
            rx.alert_dialog.title(
                rx.hstack(rx.icon("triangle-alert", color=rx.color("red", 9)), rx.text(ErrorState.error_title)),
            ),
            rx.alert_dialog.description(
                rx.cond(
                    ErrorState.error_is_file,
                    # 檔案錯誤：四欄完整顯示
                    rx.vstack(
                        _field("檔名", ErrorState.error_filename),
                        _field("原因", ErrorState.error_reason),
                        _field("期望", ErrorState.error_expected),
                        _field("實際", ErrorState.error_actual),
                        rx.callout("請修正檔案後重新上傳。", icon="info", color_scheme="red", width="100%"),
                        spacing="2",
                        width="100%",
                    ),
                    rx.text(ErrorState.error_message, white_space="pre-wrap"),
                ),
                as_child=True,
            ),
            rx.flex(
                rx.alert_dialog.action(rx.button("確定", on_click=ErrorState.close_error)),
                justify="end",
                margin_top="1em",
            ),
            max_width="560px",
        ),
        open=ErrorState.error_open,
        on_open_change=ErrorState.set_error_open,
    )

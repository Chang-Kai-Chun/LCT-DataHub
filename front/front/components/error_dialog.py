"""錯誤警告視窗：檔案錯誤完整顯示檔名、原因、期望、實際四項（3-5 共通）。

外觀使用 lct.css 的 .dialog.error（上緣為錯誤色）；不使用 Radix。
"""
import reflex as rx

from front.components.ui import BtnVariant, btn, dialog, dialog_actions
from front.states.error_state import ErrorState


def _kv(label: str, value: rx.Var) -> list[rx.Component]:
    """一列「標題：內容」。"""
    return [rx.el.dt(label), rx.el.dd(value)]


def error_dialog() -> rx.Component:
    """全站共用的警告視窗（放在版面最外層）。"""
    return dialog(
        ErrorState.error_open,
        ErrorState.error_title,
        rx.cond(
            ErrorState.error_is_file,
            # 檔案錯誤：四欄完整顯示，並提示修正後重新上傳
            rx.el.div(
                rx.el.dl(
                    *_kv("檔名", ErrorState.error_filename),
                    *_kv("原因", ErrorState.error_reason),
                    *_kv("期望", ErrorState.error_expected),
                    *_kv("實際", ErrorState.error_actual),
                    class_name="kv",
                ),
                rx.el.p("請修正檔案後重新上傳。", class_name="small muted", style={"margin": "12px 0 0"}),
            ),
            rx.el.p(ErrorState.error_message, style={"margin": "0", "white_space": "pre-wrap"}),
        ),
        dialog_actions(btn("確定", variant=BtnVariant.PRIMARY, on_click=ErrorState.close_error, auto_focus=True)),
        on_close=ErrorState.close_error,
        error=True,
    )

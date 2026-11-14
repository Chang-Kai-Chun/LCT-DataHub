"""錯誤警告視窗的共用狀態。

各功能的 State 繼承 ErrorState（成為子狀態），呼叫 self._show_error() 就能開啟同一個警告視窗。
檔案錯誤（kind = file）完整顯示檔名、原因、期望、實際，並由呼叫端停止作業（3-5 共通）。
"""
import reflex as rx

from front.api_client import ApiError
from front.enums import ErrorKind

# 各類錯誤的視窗標題
ERROR_TITLES = {
    ErrorKind.FILE: "檔案有問題，作業已停止",
    ErrorKind.INPUT: "輸入有誤",
    ErrorKind.NOT_FOUND: "找不到資料",  # 工作、使用者或專案
    ErrorKind.CONNECTION: "無法連線到 API",
    ErrorKind.UNKNOWN: "發生錯誤",
}


class ErrorState(rx.State):
    """警告視窗內容。"""

    error_open: bool = False
    error_title: str = ""
    error_message: str = ""
    error_is_file: bool = False  # True 時顯示檔名、原因、期望、實際四欄
    error_filename: str = ""
    error_reason: str = ""
    error_expected: str = ""
    error_actual: str = ""

    def _show_error(self, err: ApiError) -> None:
        """依 ApiError 填入視窗內容並開啟（一般方法，不是事件）。"""
        self.error_title = ERROR_TITLES.get(err.kind, ERROR_TITLES[ErrorKind.UNKNOWN])
        self.error_message = err.message
        self.error_is_file = err.kind is ErrorKind.FILE
        self.error_filename = err.filename
        self.error_reason = err.reason
        self.error_expected = err.expected
        self.error_actual = err.actual
        self.error_open = True

    def _show_message(self, message: str) -> None:
        """顯示前端自己檢查到的輸入錯誤。"""
        self._show_error(ApiError(ErrorKind.INPUT, message))

    @rx.event
    def close_error(self) -> None:
        """關閉警告視窗。"""
        self.error_open = False

    @rx.event
    def set_error_open(self, value: bool) -> None:
        """視窗開關（按 Esc 或點外面關閉時觸發）。"""
        self.error_open = value

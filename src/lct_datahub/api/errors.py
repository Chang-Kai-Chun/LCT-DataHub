"""把 core 的例外轉成 HTTP 回應，讓前端可以顯示警告視窗。

- 檔案問題（JV、暗電流、EQE）：422，附檔名、原因、期望、實際
- 使用者輸入不合理（分組、面積、樣品代號、改名、範圍…）：400，附訊息
- 找不到工作、使用者或專案：404
"""
from enum import Enum

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from lct_datahub.api.jobs import JobNotFoundError, UploadError
from lct_datahub.api.projects import InvalidNameError, WorkspaceNotFoundError
from lct_datahub.core.dark_current.types import DarkFileError
from lct_datahub.core.eqe.types import EqeFileError, EqeNameError
from lct_datahub.core.jv.types import GroupingError, InvalidAreaError, JVFileError
from lct_datahub.core.noise.types import NoiseFileError
from lct_datahub.core.sample_id import InvalidSampleIdError


class ErrorKind(Enum):
    """錯誤回應的 kind 欄位，前端依此決定顯示方式。"""

    FILE = "file"  # 檔案問題：顯示檔名、原因、期望、實際並停止作業
    INPUT = "input"  # 輸入問題：顯示訊息，讓使用者修正
    NOT_FOUND = "not_found"


# 檔案錯誤都有 filename、reason（Enum）、expected、actual 四個屬性
FILE_ERRORS = (JVFileError, DarkFileError, EqeFileError, NoiseFileError)
INPUT_ERRORS = (
    GroupingError, InvalidAreaError, InvalidSampleIdError, EqeNameError, UploadError, InvalidNameError,
    KeyError, ValueError,
)
NOT_FOUND_ERRORS = (JobNotFoundError, WorkspaceNotFoundError)


def _message(exc: Exception) -> str:
    """取出例外訊息；KeyError 的 str() 會多一層引號，改用第一個參數。"""
    if isinstance(exc, KeyError) and exc.args:
        return str(exc.args[0])
    return str(exc)


async def _file_error(_: Request, exc: Exception) -> JSONResponse:
    """檔案問題 → 422。"""
    return JSONResponse(
        status_code=422,
        content={
            "kind": ErrorKind.FILE.value,
            "message": str(exc),
            "filename": exc.filename,
            "reason": exc.reason.value,
            "expected": exc.expected,
            "actual": exc.actual,
        },
    )


async def _input_error(_: Request, exc: Exception) -> JSONResponse:
    """輸入問題 → 400。"""
    return JSONResponse(status_code=400, content={"kind": ErrorKind.INPUT.value, "message": _message(exc)})


async def _not_found(_: Request, exc: Exception) -> JSONResponse:
    """找不到工作 → 404。"""
    return JSONResponse(status_code=404, content={"kind": ErrorKind.NOT_FOUND.value, "message": str(exc)})


def register_error_handlers(app: FastAPI) -> None:
    """註冊上述例外處理。"""
    for exc_type in FILE_ERRORS:
        app.add_exception_handler(exc_type, _file_error)
    for exc_type in INPUT_ERRORS:
        app.add_exception_handler(exc_type, _input_error)
    for exc_type in NOT_FOUND_ERRORS:
        app.add_exception_handler(exc_type, _not_found)

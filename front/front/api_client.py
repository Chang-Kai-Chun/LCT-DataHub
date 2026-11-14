"""呼叫 FastAPI 的共用函式（asyncio ＋ httpx）。

Reflex 後端（Python）呼叫 FastAPI，瀏覽器不直接連 FastAPI，因此不需要 CORS。
所有失敗都轉成 ApiError，由 ErrorState 顯示警告視窗。
"""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any
from urllib.parse import unquote

import httpx

from front.enums import ErrorKind
from front.settings import SETTINGS

API_PREFIX = "/api"


class Method(Enum):
    """HTTP 方法。"""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"


@dataclass
class ApiError(Exception):
    """API 失敗：kind 決定顯示方式；檔案錯誤另附 filename、reason、expected、actual。"""

    kind: ErrorKind
    message: str
    status: int | None = None
    filename: str = ""
    reason: str = ""
    expected: str = ""
    actual: str = ""

    def __str__(self) -> str:
        """回傳訊息文字。"""
        return self.message


def _error_from_response(resp: httpx.Response) -> ApiError:
    """把 API 的錯誤回應（errors.py 的格式或 FastAPI 驗證錯誤）轉成 ApiError。"""
    try:
        body = resp.json()
    except ValueError:
        return ApiError(ErrorKind.UNKNOWN, f"API 錯誤（{resp.status_code}）：{resp.text[:300]}", resp.status_code)

    # FastAPI 自己的參數驗證錯誤：{"detail": [...]}
    if "kind" not in body:
        detail = body.get("detail", body)
        return ApiError(ErrorKind.INPUT, f"輸入格式不符：{detail}", resp.status_code)

    try:
        kind = ErrorKind(body["kind"])
    except ValueError:
        kind = ErrorKind.UNKNOWN
    return ApiError(
        kind=kind,
        message=str(body.get("message", "")),
        status=resp.status_code,
        filename=str(body.get("filename") or ""),
        reason=str(body.get("reason") or ""),
        expected=str(body.get("expected") or ""),
        actual=str(body.get("actual") or ""),
    )


async def request(
    method: Method,
    path: str,
    *,
    json: Any = None,
    params: Any = None,
    files: list[tuple[str, tuple[str, bytes, str]]] | None = None,
) -> httpx.Response:
    """送出請求（path 不含 /api 前綴）；非 2xx 或連線失敗時拋出 ApiError。"""
    url = f"{SETTINGS.api_url}{API_PREFIX}{path}"
    try:
        async with httpx.AsyncClient(timeout=SETTINGS.api_timeout) as client:
            resp = await client.request(method.value, url, json=json, params=params, files=files)
    except httpx.HTTPError as exc:
        raise ApiError(
            ErrorKind.CONNECTION,
            f"無法連線到 API（{SETTINGS.api_url}）。請確認已執行 uv run lct-api。\n{type(exc).__name__}: {exc}",
        ) from exc
    if resp.is_success:
        return resp
    raise _error_from_response(resp)


async def get_json(path: str, params: Any = None) -> Any:
    """GET 並回傳 JSON。"""
    return (await request(Method.GET, path, params=params)).json()


async def post_json(path: str, body: Any) -> Any:
    """POST JSON 並回傳 JSON。"""
    return (await request(Method.POST, path, json=body)).json()


async def put_json(path: str, body: Any) -> Any:
    """PUT JSON 並回傳 JSON。"""
    return (await request(Method.PUT, path, json=body)).json()


async def post_bytes(path: str, body: Any) -> bytes:
    """POST JSON 並回傳二進位內容（PNG）。"""
    return (await request(Method.POST, path, json=body)).content


async def get_bytes(path: str, params: Any = None) -> bytes:
    """GET 並回傳二進位內容（Excel、zip）。"""
    return (await request(Method.GET, path, params=params)).content


def _filename_from_header(resp: httpx.Response, fallback: str) -> str:
    """從 Content-Disposition 取出檔名（支援 filename*=utf-8''… 的中文檔名）；取不到時用 fallback。"""
    header = resp.headers.get("content-disposition", "")
    encoded = re.search(r"filename\*=(?:utf-8|UTF-8)''([^;]+)", header)
    if encoded:
        return unquote(encoded.group(1).strip())
    plain = re.search(r'filename="?([^";]+)"?', header)
    return plain.group(1).strip() if plain else fallback


async def get_file(path: str, fallback_name: str, params: Any = None) -> tuple[str, bytes]:
    """GET 下載檔案，回傳 (伺服器給的檔名, 內容)；檔名依回應而定（例如單一 xlsx 或 zip）。"""
    resp = await request(Method.GET, path, params=params)
    return _filename_from_header(resp, fallback_name), resp.content


async def upload(path: str, uploads: list[tuple[str, bytes]], content_type: str) -> Any:
    """以 multipart 上傳多個檔案（欄位名稱 files），回傳 JSON。"""
    files = [("files", (name, data, content_type)) for name, data in uploads]
    return (await request(Method.POST, path, files=files)).json()


async def health() -> bool:
    """確認 API 在線。"""
    try:
        await get_json("/health")
    except ApiError:
        return False
    return True

"""各路由共用：依賴注入、上傳讀取、PNG 與檔案下載回應、共用的資料模型。"""
import math
import zipfile
from enum import Enum
from pathlib import Path

from fastapi import Request, UploadFile
from fastapi.responses import FileResponse, Response
from matplotlib.figure import Figure
from pydantic import BaseModel

from lct_datahub.api.jobs import JobStore
from lct_datahub.core.area_check import AreaReport
from lct_datahub.core.plotting import figure_to_png

# 座標範圍：[下限, 上限]；null 表示自動
AxisRange = tuple[float, float] | None


class MediaType:
    """回應的檔案類型。"""

    PNG = "image/png"
    XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    ZIP = "application/zip"


def get_store(request: Request) -> JobStore:
    """取得 app 上的 JobStore（create_app 時建立）。"""
    return request.app.state.store


async def read_uploads(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    """把上傳檔轉成 (檔名, 內容)；以非同步方式讀取，不擋住事件迴圈。"""
    return [(f.filename or "", await f.read()) for f in files]


def png_response(fig: Figure) -> Response:
    """把 Figure 轉成 PNG 回應。"""
    return Response(content=figure_to_png(fig), media_type=MediaType.PNG)


def download_response(paths: list[Path], zip_path: Path) -> FileResponse:
    """只有一個檔案就直接下載；多個檔案（例如依儀器各一份 Excel）打包成 zip_path 再下載。"""
    if len(paths) == 1:
        return FileResponse(paths[0], media_type=MediaType.XLSX, filename=paths[0].name)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=p.name)
    return FileResponse(zip_path, media_type=MediaType.ZIP, filename=zip_path.name)


class AreaReportOut(BaseModel):
    """有效面積檢查結果（給面積確認視窗）。"""

    is_uniform: bool  # 所有檔案面積是否相同
    uniform_value: float | None  # 相同時的值
    values: list[float]  # 出現過的所有面積
    by_file: dict[str, list[float]]  # 檔名 → 該檔的面積

    @classmethod
    def from_report(cls, report: AreaReport) -> "AreaReportOut":
        """由 core 的 AreaReport 轉換。"""
        return cls(
            is_uniform=report.is_uniform,
            uniform_value=report.uniform_value,
            values=list(report.values),
            by_file={k: list(v) for k, v in report.by_file.items()},
        )


class AreaIn(BaseModel):
    """面積確認的結果：null 表示「忽略並繼續」（沿用檔內面積），數值表示改用此面積（cm²）。"""

    area: float | None = None


def json_value(value):
    """把 DataFrame 內的值轉成 JSON 可用的型別：Enum 取 value、NaN 轉 null、時間轉字串。"""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):  # numpy 純量
        return json_value(value.item())
    return value

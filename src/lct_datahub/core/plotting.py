"""matplotlib 繪圖：只使用 Figure() 與 Agg 後端，不使用 pyplot；只負責把 DataFrame 變成圖。"""
from collections.abc import Callable
from functools import wraps
from io import BytesIO

import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib import rc_context
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.colors import to_rgb
from matplotlib.figure import Figure
from matplotlib.transforms import ScaledTranslation

from lct_datahub.core.jv.curve import DEFAULT_Y_RANGE, CurveLine
from lct_datahub.core.jv.types import JVParam

# 預設色盤（F 區色票庫完成前暫用）；matplotlib 的 tab10
DEFAULT_COLORS = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
)

# 全部圖的字體（Arial）；標題與 X、Y 軸標籤粗體
FONT_FAMILY = ["Arial", "DejaVu Sans"]  # 找不到 Arial 時退回 DejaVu Sans
FIGURE_STYLE = {
    "font.family": FONT_FAMILY,
    "axes.labelweight": "bold",
    "axes.titleweight": "bold",
}

# 球體符號的疊層：(大小比例, 往左上偏移的比例, 顏色與白色的混合比例或底色變暗比例, 不透明度)
# 第一層為變暗的底色，其後依序是原色、淺色、白色高光
SPHERE_LAYERS = (
    (1.00, 0.00, ("dark", 0.35), 1.0),
    (0.62, 0.16, ("mix", 0.00), 1.0),
    (0.30, 0.30, ("mix", 0.75), 0.95),
    (0.12, 0.38, ("mix", 1.00), 0.95),
)

# 圖例每欄最多幾列，超過就分成多欄
LEGEND_ROWS = 20

# Box 圖樣式：條件色（洋紅、紅、綠、藍，之後依序為橘、青、紫、黑）、box 寬度、線寬、點大小
BOX_COLORS = (
    "#FF00FF", "#FF0000", "#00C800", "#0000FF", "#FF8000", "#00B4B4", "#8000C0", "#000000",
)
BOX_WIDTH = 0.55
BOX_LINE_WIDTH = 1.8
BOX_POINT_SIZE = 32

# Box 圖數據點的左右抖動幅度與亂數種子
BOX_JITTER = 0.15
BOX_JITTER_SEED = 0

# 各參數的 Y 軸標籤
PARAM_LABELS = {
    JVParam.VOC: "Voc (V)",
    JVParam.JSC: "Jsc (mA/cm²)",
    JVParam.PCE: "PCE (%)",
    JVParam.FF: "FF (%)",
    JVParam.RSH: "Rsh (Ω)",
}


def _styled(func: Callable[..., Figure]) -> Callable[..., Figure]:
    """讓繪圖函式在 FIGURE_STYLE（Arial、粗體標籤）下建立圖。"""

    @wraps(func)
    def wrapper(*args, **kwargs) -> Figure:
        with rc_context(FIGURE_STYLE):
            return func(*args, **kwargs)

    return wrapper


def _blend(color: str, target: tuple[float, float, float], ratio: float) -> tuple[float, ...]:
    """color 與 target 以 ratio 混合（0 為原色，1 為 target）。"""
    return tuple((1 - ratio) * a + ratio * b for a, b in zip(to_rgb(color), target))


def scatter_spheres(ax: Axes, xs, ys, color: str, size: float = BOX_POINT_SIZE) -> None:
    """畫有高光的球體符號（向量疊層）：變暗的底、原色、淺色與白色高光往左上偏移。

    size 為符號面積（points²），與 ax.scatter 的 s 相同。
    """
    radius_in = np.sqrt(size) / 2 / 72  # 符號半徑（英吋），偏移量以此換算
    for scale, offset, (kind, ratio), alpha in SPHERE_LAYERS:
        layer_color = (
            _blend(color, (0, 0, 0), ratio) if kind == "dark" else _blend(color, (1, 1, 1), ratio)
        )
        shift = ScaledTranslation(-offset * radius_in, offset * radius_in, ax.figure.dpi_scale_trans)
        ax.scatter(
            xs, ys, s=size * scale, color=layer_color, alpha=alpha, linewidths=0, zorder=3,
            transform=ax.transData + shift,
        )


def _new_figure(size: tuple[float, float]) -> tuple[Figure, Axes]:
    """建立不經 pyplot 的 Figure 與單一 Axes。"""
    fig = Figure(figsize=size)
    FigureCanvasAgg(fig)  # 掛上 Agg 後端才能輸出 PNG
    return fig, fig.add_subplot(111)


@_styled
def plot_jv_curves(
    lines: list[CurveLine],
    y_range: tuple[float, float] = DEFAULT_Y_RANGE,
    colors: tuple[str, ...] = DEFAULT_COLORS,
) -> Figure:
    """畫 JV 曲線疊圖：FW 實線、RV 虛線；同一樣品同一 Pixel 的 FW 與 RV 同色。

    y_range 為 (下限, 上限)，下限需小於上限，否則拋出 ValueError。
    """
    low, high = y_range
    if not low < high:
        raise ValueError("Y 軸下限必須小於上限")

    fig, ax = _new_figure((6, 4.5))
    color_of: dict[tuple, str] = {}
    for line in lines:
        key = (line.sample, line.pixel)
        if key not in color_of:
            color_of[key] = colors[len(color_of) % len(colors)]
        ax.plot(
            line.voltage, line.current_density,
            color=color_of[key], linestyle=line.style.value, linewidth=1.5, label=line.label,
        )
    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("Current density (mA/cm²)")
    ax.set_ylim(low, high)
    ax.axhline(0, color="black", linewidth=0.6)
    ax.axvline(0, color="black", linewidth=0.6)
    if lines:
        # 圖例放在圖外右側，曲線多時自動分欄；輸出 PNG 時由 bbox_inches="tight" 保留完整圖例
        ax.legend(
            fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(1.02, 1.0),
            ncol=-(-len(lines) // LEGEND_ROWS),
        )
    return fig


@_styled
def plot_box(
    data: pd.DataFrame,
    param: JVParam,
    colors: tuple[str, ...] = BOX_COLORS,
    y_range: tuple[float, float] | None = None,
) -> Figure:
    """畫單一參數的 Box 圖（Origin 風格）：data 每欄一個條件（box_data 的輸出），空值自動略過。

    每個條件一種顏色：空心 box 與中位線、鬚線、數據點同色；粗體座標軸、粗框線、刻度朝內。
    y_range 為 (下限, 上限)，None 表示自動；下限需小於上限，否則拋出 ValueError。
    """
    if y_range is not None and not y_range[0] < y_range[1]:
        raise ValueError("Y 軸下限必須小於上限")
    fig, ax = _new_figure((max(4.0, 0.9 * len(data.columns) + 2.5), 4.0))
    values = [data[name].dropna().to_numpy() for name in data.columns]
    if values:
        # 離群值改由散點一併顯示，所以關掉 box 預設的離群點
        parts = ax.boxplot(
            values, widths=BOX_WIDTH, tick_labels=list(data.columns), showfliers=False,
        )
        rng = np.random.default_rng(BOX_JITTER_SEED)  # 固定種子：同一份資料每次輸出一致
        for i, ys in enumerate(values):
            color = colors[i % len(colors)]
            # box 本體、中位線各一個；鬚線與端點每個 box 兩個
            for key in ("boxes", "medians"):
                parts[key][i].set(color=color, linewidth=BOX_LINE_WIDTH)
            for key in ("whiskers", "caps"):
                for artist in parts[key][2 * i : 2 * i + 2]:
                    artist.set(color=color, linewidth=BOX_LINE_WIDTH)
            # 每個數據點（球體符號）畫在 box 上，x 方向小幅抖動避免重疊
            xs = i + 1 + rng.uniform(-BOX_JITTER, BOX_JITTER, size=len(ys))
            scatter_spheres(ax, xs, ys, color)

    if y_range is not None:
        ax.set_ylim(*y_range)
    ax.set_ylabel(PARAM_LABELS[param], fontsize=13, fontweight="bold")
    ax.tick_params(direction="in", width=1.5, labelsize=11)
    for label in ax.get_xticklabels():
        label.set_fontweight("bold")
    for spine in ax.spines.values():
        spine.set_linewidth(1.5)
    fig.tight_layout()
    return fig


def figure_to_png(fig: Figure, dpi: int = 200) -> bytes:
    """把 Figure 輸出成 PNG 位元組（預覽與下載共用）。"""
    buffer = BytesIO()
    with rc_context(FIGURE_STYLE):  # 刻度文字在輸出時才建立，也要套同樣字體
        fig.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight")
    return buffer.getvalue()

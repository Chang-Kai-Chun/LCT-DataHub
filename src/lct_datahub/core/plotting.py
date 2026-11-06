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

from lct_datahub.core.dark_current.types import DarkColumn, DarkCurve
from lct_datahub.core.eqe.types import EqeColumn, EqeCurve
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


# 暗電流圖：偏移註記（紅框、黑字、斜體、粗體）放在右上角
SHIFT_NOTE_TEXT = "shift"


def _add_shift_note(ax: Axes) -> None:
    """在座標軸右上角加上 shift 註記：紅框、黑字、斜體、粗體。"""
    ax.text(
        0.97, 0.96, SHIFT_NOTE_TEXT, transform=ax.transAxes, ha="right", va="top",
        color="black", fontstyle="italic", fontweight="bold", fontsize=12, zorder=5,
        bbox={"boxstyle": "square,pad=0.35", "facecolor": "white", "edgecolor": "red", "linewidth": 1.8},
    )


@_styled
def plot_dark_current(
    curves: list[DarkCurve],
    y_range: tuple[float, float] | None = None,
    x_range: tuple[float, float] | None = None,
    colors: tuple[str, ...] = DEFAULT_COLORS,
) -> Figure:
    """畫暗電流疊圖：X 為電壓 (V)，Y 為 |J| (A/cm²)，對數座標。

    只要有一條曲線被偏移過（B-2），右上角就加 shift 註記。
    y_range、x_range 為 (下限, 上限)，None 表示自動；下限需小於上限，Y 軸（對數）下限需大於 0，否則拋出 ValueError。
    J 為 0 的點無法在對數座標顯示，會略過。
    """
    for name, rng in (("X", x_range), ("Y", y_range)):
        if rng is not None and not rng[0] < rng[1]:
            raise ValueError(f"{name} 軸下限必須小於上限")
    if y_range is not None and y_range[0] <= 0:
        raise ValueError("Y 軸為對數座標，下限必須大於 0")

    fig, ax = _new_figure((6, 4.5))
    for i, curve in enumerate(curves):
        dens = curve.data[DarkColumn.J.value].abs().where(lambda s: s > 0)  # 0 無法取對數
        ax.plot(
            curve.data[DarkColumn.VOLTAGE.value], dens,
            color=colors[i % len(colors)], linewidth=1.5, label=curve.name,
        )
    ax.set_yscale("log")
    ax.set_xlabel("Voltage (V)")
    ax.set_ylabel("|J| (A/cm²)")
    if x_range is not None:
        ax.set_xlim(*x_range)
    if y_range is not None:
        ax.set_ylim(*y_range)
    ax.axvline(0, color="black", linewidth=0.6)
    if curves:
        # 圖例放在圖外右側，曲線多時自動分欄（與 JV 曲線圖相同）
        ax.legend(
            fontsize=7, frameon=False, loc="upper left", bbox_to_anchor=(1.02, 1.0),
            ncol=-(-len(curves) // LEGEND_ROWS),
        )
    if any(c.is_shifted for c in curves):
        _add_shift_note(ax)
    return fig


def _check_range(name: str, rng: tuple[float, float] | None) -> None:
    """檢查座標範圍：None 表示自動；否則下限需小於上限，否則拋出 ValueError。"""
    if rng is not None and not rng[0] < rng[1]:
        raise ValueError(f"{name} 軸下限必須小於上限")


# EQE 圖：單一樣品時沿用 V5 配色（EQE 藍、積分電流紅），座標軸同色
EQE_SINGLE_COLOR = "#0000FF"
JSC_SINGLE_COLOR = "#FF0000"
DEFAULT_EQE_RANGE = (0.0, 100.0)  # EQE 軸預設範圍（%）
JSC_LINE_STYLE = "--"  # 多樣品時積分電流用虛線（EQE 用實線）


def _legend_outside(ax: Axes, handles: list, labels: list[str], x_offset: float) -> None:
    """把圖例放在圖外右側，曲線多時自動分欄；x_offset 為圖例左緣相對座標軸寬度的位置。"""
    ax.legend(
        handles, labels, fontsize=7, frameon=False, loc="upper left",
        bbox_to_anchor=(x_offset, 1.0), ncol=-(-len(labels) // LEGEND_ROWS),
    )


def _color_axis(ax: Axes, side: str, color: str) -> None:
    """把一側 Y 軸（座標線、刻度、標籤）設成指定顏色，用於單一樣品的雙軸圖。"""
    ax.spines[side].set_color(color)
    ax.tick_params(axis="y", colors=color)
    ax.yaxis.label.set_color(color)


@_styled
def plot_eqe(
    curves: list[EqeCurve],
    x_range: tuple[float, float] | None = None,
    eqe_range: tuple[float, float] | None = DEFAULT_EQE_RANGE,
    jsc_range: tuple[float, float] | None = None,
    show_jsc: bool = True,
    colors: tuple[str, ...] = DEFAULT_COLORS,
) -> Figure:
    """C-2：畫 EQE 疊圖，EQE 用左 Y 軸、積分電流用右 Y 軸。

    - 單一樣品：EQE 藍、積分電流紅（V5 配色），兩側座標軸與曲線同色
    - 多個樣品：同一樣品同色，EQE 實線、積分電流虛線；圖例只列樣品名稱與線型說明
    - show_jsc=False 時不畫右軸與積分電流
    x_range 由使用者輸入，None 表示依數據自動；eqe_range 預設 0–100；jsc_range None 表示自動。
    任何範圍的下限需小於上限，否則拋出 ValueError。
    """
    for name, rng in (("X", x_range), ("EQE", eqe_range), ("積分電流", jsc_range)):
        _check_range(name, rng)

    fig, ax = _new_figure((6, 4.5))
    ax_jsc = ax.twinx() if show_jsc else None
    single = len(curves) == 1
    handles, labels = [], []
    for i, curve in enumerate(curves):
        wl = curve.data[EqeColumn.WAVELENGTH.value]
        eqe_color = EQE_SINGLE_COLOR if single else colors[i % len(colors)]
        (line,) = ax.plot(wl, curve.data[EqeColumn.EQE.value], color=eqe_color, linewidth=1.5)
        handles.append(line)
        labels.append(curve.name)
        if ax_jsc is not None:
            jsc_color = JSC_SINGLE_COLOR if single else eqe_color
            jsc_style = "-" if single else JSC_LINE_STYLE  # 單一樣品已用顏色區分，不必虛線
            ax_jsc.plot(wl, curve.data[EqeColumn.JSC.value], color=jsc_color, linestyle=jsc_style, linewidth=1.5)

    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("EQE (%)")
    if x_range is not None:
        ax.set_xlim(*x_range)
    if eqe_range is not None:
        ax.set_ylim(*eqe_range)
    if ax_jsc is not None:
        ax_jsc.set_ylabel("Integrated Jsc (mA/cm²)", fontweight="bold")
        if jsc_range is not None:
            ax_jsc.set_ylim(*jsc_range)
        else:
            ax_jsc.set_ylim(bottom=0)  # 積分電流從 0 起算
        if single:
            _color_axis(ax, "left", EQE_SINGLE_COLOR)
            _color_axis(ax_jsc, "right", JSC_SINGLE_COLOR)
            ax_jsc.spines["left"].set_visible(False)  # 避免右軸圖層的左框線蓋掉藍色左軸
        elif curves:
            # 多樣品時另加兩個灰色項目說明線型
            handles += [
                ax.plot([], [], color="gray", linestyle="-")[0],
                ax.plot([], [], color="gray", linestyle=JSC_LINE_STYLE)[0],
            ]
            labels += ["EQE", "Integrated Jsc"]
    if curves:
        # 有右軸時圖例要再往右，避開右軸刻度與標籤
        _legend_outside(ax, handles, labels, 1.18 if ax_jsc is not None else 1.02)
    return fig


@_styled
def plot_rplot(
    curves: list[EqeCurve],
    x_range: tuple[float, float] | None = None,
    y_range: tuple[float, float] | None = None,
    colors: tuple[str, ...] = DEFAULT_COLORS,
) -> Figure:
    """C-3：畫 R-plot 疊圖，X 為波長 (nm)、Y 為 SR (A/W)；每個樣品一色。

    x_range、y_range 由使用者輸入，None 表示依數據自動（Y 軸自動時從 0 起算）；下限需小於上限，否則拋出 ValueError。
    """
    for name, rng in (("X", x_range), ("Y", y_range)):
        _check_range(name, rng)

    fig, ax = _new_figure((6, 4.5))
    for i, curve in enumerate(curves):
        ax.plot(
            curve.data[EqeColumn.WAVELENGTH.value], curve.data[EqeColumn.SR.value],
            color=colors[i % len(colors)], linewidth=1.5, label=curve.name,
        )
    ax.set_xlabel("Wavelength (nm)")
    ax.set_ylabel("Responsivity (A/W)")
    if x_range is not None:
        ax.set_xlim(*x_range)
    if y_range is not None:
        ax.set_ylim(*y_range)
    else:
        ax.set_ylim(bottom=0)
    if curves:
        h, l = ax.get_legend_handles_labels()
        _legend_outside(ax, h, l, 1.02)
    return fig


def figure_to_png(fig: Figure, dpi: int = 200) -> bytes:
    """把 Figure 輸出成 PNG 位元組（預覽與下載共用）。"""
    buffer = BytesIO()
    with rc_context(FIGURE_STYLE):  # 刻度文字在輸出時才建立，也要套同樣字體
        fig.savefig(buffer, format="png", dpi=dpi, bbox_inches="tight")
    return buffer.getvalue()

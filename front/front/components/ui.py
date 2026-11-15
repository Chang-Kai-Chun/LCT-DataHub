"""lct. 設計的共用小元件（樣式在 assets/lct.css，這裡只組 HTML 結構與 class）。

全部用 rx.el.*（原生 HTML 元素），不使用 Radix 的外觀，避免與 lct.css 互相覆蓋。
"""
from enum import Enum

import reflex as rx

# 八面體（BX6）：前方八條邊＋一個橘色面；字標旁的小記號與載入動畫共用同一組座標
_OCTA_FACE = "50,6 42,64 86,48"
_OCTA_OUTLINE = "M50 6 L14 52 L50 94 L86 48 Z M14 52 L42 64 L86 48 M50 6 L42 64 L50 94"
_OCTA_EDGES = (
    "M50 6 L14 52", "M50 6 L42 64", "M50 6 L86 48", "M14 52 L42 64",
    "M42 64 L86 48", "M14 52 L50 94", "M42 64 L50 94", "M86 48 L50 94",
)
EDGE_DELAY_S = 0.08  # 每條邊描邊的間隔（秒）


class BtnVariant(Enum):
    """按鈕樣式（對應 lct.css 的 class）。"""

    DEFAULT = ""
    PRIMARY = "primary"
    GHOST = "ghost"
    WARN = "warn"


# ---------- 圖形 ----------
def mark(size: int = 26) -> rx.Component:
    """字標旁的八面體小記號（一面填橘色）。"""
    return rx.html(
        f'<svg class="mark" width="{size}" height="{size}" viewBox="0 0 100 100" aria-hidden="true" fill="none" '
        f'stroke="currentColor" stroke-width="6" stroke-linejoin="round">'
        f'<polygon class="face" points="{_OCTA_FACE}" stroke="none"></polygon>'
        f'<path d="{_OCTA_OUTLINE}"></path></svg>',
        style={"display": "flex"},
    )


def octa_loader(size: int = 40, label: str = "載入中") -> rx.Component:
    """八面體載入動畫：八條邊依序描邊、背面虛線淡入、一面填橘色（減少動態時直接顯示完成圖）。"""
    edges = "".join(
        f'<path class="edge" pathLength="1" d="{d}" style="animation-delay: {i * EDGE_DELAY_S:.2f}s"></path>'
        for i, d in enumerate(_OCTA_EDGES)
    )
    return rx.html(
        f'<svg class="octa" width="{size}" height="{size}" viewBox="0 0 100 100" role="img" aria-label="{label}" '
        f'fill="none" stroke="currentColor" stroke-linejoin="round" stroke-linecap="round">'
        f'<polygon class="face" points="{_OCTA_FACE}" stroke="none"></polygon>'
        f'<g class="back" stroke-width="2" stroke-dasharray="4 4"><path d="M50 6 L58 38 L50 94"></path>'
        f'<path d="M14 52 L58 38 L86 48"></path></g>'
        f'<g stroke-width="3">{edges}</g></svg>',
        style={"display": "flex"},
    )


def wordmark(size: str = "34px") -> rx.Component:
    """字標 lct.（句點橘色）。"""
    return rx.el.span(
        "lct", rx.el.span(".", class_name="dot"),
        class_name="wordmark", style={"font_size": size, "letter_spacing": "-0.05em", "line_height": "1"},
    )


def chevron() -> rx.Component:
    """下拉選單右側的箭頭。"""
    return rx.html(
        '<svg width="16" height="16" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
        'stroke-width="2"><path d="M6 9l6 6 6-6"></path></svg>',
        style={"position": "absolute", "right": "14px", "top": "50%", "transform": "translateY(-50%)",
               "pointer_events": "none", "display": "flex"},
    )


# ---------- 按鈕與輸入 ----------
def btn(*children, variant: BtnVariant = BtnVariant.DEFAULT, small: bool = False, class_name: str = "",
        **props) -> rx.Component:
    """按鈕（type=button）；variant 決定樣式，small 為小尺寸。"""
    classes = " ".join(c for c in ("btn", variant.value, "sm" if small else "", class_name) if c)
    return rx.el.button(*children, type="button", class_name=classes, **props)


def text_input(value, on_change, placeholder: str = "", class_name: str = "", **props) -> rx.Component:
    """文字輸入框（非受控）：value 只當初始值，打字時只把內容回報給 State，不再寫回輸入框。

    受控寫法（value=）每打一個字就從後端寫回一次，會打斷注音、倉頡等輸入法的選字。
    要清空或換內容時，請改變 key（或讓輸入框重新掛載，例如對話框重新開啟）。
    """
    return rx.el.input(
        default_value=value, on_change=on_change, placeholder=placeholder, type="text",
        class_name=f"input {class_name}".strip(), **props,
    )


def select(options, value, on_change, placeholder: str = "", class_name: str = "", **props) -> rx.Component:
    """原生下拉選單；options 為字串清單（Var 或 list），placeholder 為未選擇時的第一項。"""
    items = rx.foreach(options, lambda o: rx.el.option(o, value=o))
    first = [rx.el.option(placeholder, value="", disabled=True)] if placeholder else []
    return rx.el.div(
        rx.el.select(*first, items, value=value, on_change=on_change, class_name="select", **props),
        chevron(),
        class_name=f"select-wrap {class_name}".strip(),
    )


def field(label: str, control: rx.Component, html_for: str = "") -> rx.Component:
    """標籤（上）＋輸入（下）。"""
    return rx.el.div(rx.el.label(label, html_for=html_for), control, class_name="field")


# ---------- 文字與區塊 ----------
def section_head(title: str, *extra: rx.Component, end: list[rx.Component] | None = None) -> rx.Component:
    """區段標題列：標題、附加資訊，最右邊放 end 的按鈕。"""
    return rx.el.div(
        rx.el.h2(title), *extra,
        rx.el.div(*(end or []), class_name="end") if end else rx.fragment(),
        class_name="section-head",
    )


def note(*children, kind: str = "") -> rx.Component:
    """提示框；kind 為 ''、'warn'、'error'。"""
    return rx.el.div(*children, class_name=f"note {kind}".strip())


def copy_cell(value, class_name: str = "num", **props) -> rx.Component:
    """表格的數值格：點一下就複製文字（不用選取），並跳出提示。"""
    return rx.el.td(
        value,
        class_name=f"{class_name} copyable".strip(),
        title="點一下複製",
        on_click=[rx.set_clipboard(value), rx.toast(f"已複製：{value}", duration=1500)],
        **props,
    )


def tag(text, kind: str = "") -> rx.Component:
    """小標籤；kind 為 ''、'ok'、'warn'。"""
    return rx.el.span(text, class_name=f"tag {kind}".strip())


# ---------- 步驟標籤 ----------
def step_tabs(current, items: list[tuple[str, str, str, bool]], on_change) -> rx.Component:
    """步驟標籤列（b-1 整合、b-2 分組…）；items 為 (value, 代號, 名稱, 是否可點)。

    on_change 接收被點的 value；選中的標籤底線由左展開（lct.css 的 .tab::after）。
    """
    tabs = [
        rx.el.button(
            rx.el.span(code, class_name="mono"), label,
            type="button", role="tab", class_name="tab", disabled=not enabled,
            aria_selected=rx.cond(current == value, "true", "false"),
            on_click=on_change(value),
        )
        for value, code, label, enabled in items
    ]
    return rx.el.div(*tabs, class_name="tabs", role="tablist", aria_label="步驟")


def segmented(options: list[str], value, on_change, label: str = "") -> rx.Component:
    """分段按鈕（單選）：選中的反白；on_change 接收被點的選項。"""
    return rx.el.div(
        *[
            rx.el.button(o, type="button", aria_pressed=rx.cond(value == o, "true", "false"), on_click=on_change(o))
            for o in options
        ],
        class_name="segmented", role="group", aria_label=label,
    )


def panel(title: str, *children: rx.Component, end: list[rx.Component] | None = None) -> rx.Component:
    """一個區段：上緣粗線＋標題列（右側可放按鈕）＋內容。"""
    return rx.el.section(section_head(title, end=end), *children, class_name="section rule")


# ---------- 對話框 ----------
def dialog(open_var, title, *children, on_close=None, step_text=None, error: bool = False) -> rx.Component:
    """對話框（自製，不用 Radix），開啟時以 rx.cond 掛上；on_close：點背景時觸發。"""
    head = [rx.el.h2(title, id="dlg-title")]
    if step_text is not None:
        head.append(rx.el.span(step_text, class_name="mono small muted"))
    box = rx.el.div(
        rx.el.div(*head, class_name="row", style={"align_items": "baseline"}),
        *children,
        class_name="dialog error" if error else "dialog",
        role="dialog",
        aria_modal="true",
        aria_labelledby="dlg-title",
    )
    # 背景是獨立的一層（.backdrop），與對話框並列：
    # 在輸入框按下、拖曳選字到框外才放開時，click 會落在兩者共同的外層（沒有事件），不會誤關對話框；
    # 只有在背景上按下並放開，才會觸發 on_close。
    backdrop = rx.el.div(class_name="backdrop", on_click=on_close) if on_close is not None else rx.el.div(
        class_name="backdrop")
    return rx.cond(open_var, rx.el.div(backdrop, box, class_name="overlay"))


def dialog_actions(*buttons: rx.Component) -> rx.Component:
    """對話框底部按鈕列（靠右）。"""
    return rx.el.div(*buttons, class_name="actions")


def upload_box(upload_id: str, accept: dict, hint: str, on_confirm, loading) -> rx.Component:
    """上傳區：點選或拖曳檔案到中間的框（唯一的選檔方式）→ 列出已選檔案 →「確認」上傳讀取。

    沒有選檔案時「確認」反灰不能按；處理中（loading）也不能按。
    """
    selected = rx.selected_files(upload_id)
    icon = rx.html(
        '<svg width="28" height="28" viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
        'stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">'
        '<path d="M12 16V4M7 9l5-5 5 5M4 16v4h16v-4"></path></svg>',
        style={"display": "flex"},
    )
    return rx.el.div(
        rx.upload(
            icon,
            rx.el.strong("拖曳檔案到這裡，或點選選擇檔案"),
            rx.el.span(hint, class_name="small muted"),
            id=upload_id,
            multiple=True,
            accept=accept,
            class_name="dropzone",
            # 蓋過 rx.upload 內建的框線與留白，外觀由 .dropzone 決定
            border="1px dashed var(--ink)",
            padding="32px",
            border_radius="0",
        ),
        rx.cond(
            selected.length() > 0,
            rx.el.div(
                rx.foreach(selected, lambda name: rx.el.span(name, class_name="tag ok")),
                btn("清除", variant=BtnVariant.GHOST, small=True, on_click=rx.clear_selected_files(upload_id)),
                class_name="row", style={"gap": "6px"},
            ),
        ),
        rx.el.div(
            btn("確認", variant=BtnVariant.PRIMARY, on_click=on_confirm,
                disabled=(selected.length() == 0) | loading),
            rx.cond(selected.length() == 0, rx.el.span("請先選擇檔案", class_name="small muted")),
            class_name="row",
        ),
        class_name="section",
    )


def busy(loading, text: str = "處理中…") -> rx.Component:
    """右下角的處理中提示（八面體動畫）。"""
    return rx.cond(loading, rx.el.div(octa_loader(28), rx.el.span(text), class_name="busy", role="status"))

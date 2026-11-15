"""分組畫面的共用元件（A JV、B 暗電流、之後 C EQE；分組單位都是「樣品」）。

state 參數為繼承 GroupingMixin 的 State 類別；unit 為畫面上的單位名稱。
外觀使用 lct.css（不用 Radix）；條件名稱只能從專案統一的條件中選。
"""
import reflex as rx

from front.components.ui import BtnVariant, btn, note, octa_loader, panel, segmented, select, text_input
from front.enums import GroupMode, Route
from front.states.grouping import ADJUST_ID, NEXT_ID, GroupCond


def _sample_chip(state, sample: rx.Var) -> rx.Component:
    """樣品卡片：點選（反白）後再按條件框的「放到這裡」。"""
    return rx.el.button(
        sample, type="button", class_name="chip-btn",
        aria_pressed=rx.cond(state.selected_sample == sample, "true", "false"),
        on_click=state.pick_sample(sample),
    )


def _cond_box(state, cond: GroupCond, index: rx.Var) -> rx.Component:
    """條件框：名稱、樣品數、刪除；樣品卡片；「放到這裡」。"""
    return rx.el.div(
        rx.el.div(
            rx.el.strong(cond.name),
            rx.el.span(cond.samples.length(), class_name="tag"),
            btn("刪除", variant=BtnVariant.GHOST, small=True, on_click=state.remove_condition(index),
                style={"margin_left": "auto"}),
            class_name="row nowrap",
        ),
        rx.el.div(rx.foreach(cond.samples, lambda s: _sample_chip(state, s)), class_name="row",
                  style={"gap": "6px", "min_height": "32px"}),
        btn("放到這裡", small=True, disabled=state.selected_sample == "", on_click=state.move_to(index)),
        class_name="cond-box",
    )


def _cond_input_row(state, i: rx.Var) -> rx.Component:
    """第 i 個條件：從專案條件中選名稱；自訂時後方加「[字母] [起] 到 [迄]」與即時結果。"""
    is_custom = state.group_mode == GroupMode.CUSTOM.value
    # 樣品字母：只有一種時直接顯示，多種時給選單
    prefix = rx.cond(
        state.prefixes.length() > 1,
        select(state.prefixes, state.range_prefix[i], lambda v: state.set_range_prefix(i, v),
               style={"width": "5em"}),
        rx.el.strong(state.range_prefix[i]),
    )
    return rx.el.div(
        rx.el.span(f"條件 {i + 1}", class_name="mono small muted", style={"width": "4.5em", "flex": "none"}),
        select(state.cond_choices, state.cond_names[i], lambda v: state.set_cond_name(i, v),
               placeholder="選擇條件", style={"width": "14em"}),
        rx.cond(
            is_custom,
            rx.el.div(
                prefix,
                text_input(state.range_from[i], lambda v: state.set_range_from(i, v), placeholder="起",
                           class_name="mono", style={"width": "5em"}),
                rx.el.span("到", class_name="muted"),
                prefix,
                text_input(state.range_to[i], lambda v: state.set_range_to(i, v), placeholder="迄",
                           class_name="mono", style={"width": "5em"}),
                rx.el.span(state.range_previews[i], class_name="small muted"),
                class_name="row",
            ),
        ),
        class_name="row",
    )


def _no_choices_note() -> rx.Component:
    """專案還沒定義條件名稱時的提示（分組只能用專案的條件）。"""
    return note(
        rx.el.span("這個專案還沒有定義條件名稱，分組只能使用專案統一的條件。"),
        rx.el.a("前往總覽新增條件 →", href=Route.OVERVIEW.value),
        kind="warn",
    )


def _project_group_line(group) -> rx.Component:
    """總覽分組的一列：條件：樣品。"""
    return rx.el.span(rx.el.strong(group.name), "：", group.samples.join("、"), class_name="small")


def _project_grouping(state) -> rx.Component:
    """總覽已設定分組時：列出並提供「套用總覽的分組」（套用後可微調再確定）。"""
    return rx.cond(
        state.project_grouping.length() > 0,
        panel(
            "總覽的分組",
            rx.el.div(rx.foreach(state.project_grouping, _project_group_line), class_name="section",
                      style={"gap": "4px"}),
            rx.el.div(
                btn("套用總覽的分組", variant=BtnVariant.PRIMARY, on_click=state.apply_project_grouping),
                rx.el.span("本區沒有的樣品略過；本區多出來的樣品放在未分配", class_name="small muted"),
                class_name="row",
            ),
        ),
    )


def grouping_settings(state, unit: str = "樣品", show_project: bool = True) -> rx.Component:
    """（總覽的分組）＋分組方式 → 條件數 → N 個條件（從專案條件中選）→ 套用分組；專案沒有條件時只顯示提示。

    show_project：顯示「總覽的分組」與套用按鈕（總覽頁自己不顯示）。
    """
    parts = [_project_grouping(state)] if show_project else []
    return rx.cond(
        state.has_choices,
        rx.el.div(*parts, _grouping_settings(state, unit), class_name="section", style={"gap": "32px"}),
        _no_choices_note(),
    )


def _grouping_settings(state, unit: str) -> rx.Component:
    """分組設定本體。"""
    return panel(
        "分組設定",
        rx.el.div(
            rx.el.span("專案條件：", state.cond_choices.join("、"), class_name="small muted"),
            rx.el.a("修改", href=Route.OVERVIEW.value, class_name="small"),
            class_name="row",
        ),
        rx.el.div(
            rx.el.span("分組方式", class_name="label"),
            segmented([m.value for m in GroupMode], state.group_mode, state.set_group_mode, label="分組方式"),
            class_name="field",
        ),
        rx.el.p(f"本次{unit}：", state.samples.join("、"), class_name="small muted", style={"margin": "0"}),
        rx.cond(
            state.group_mode == GroupMode.AUTO.value,
            rx.el.p(f"每 4 個{unit}一組，餘數放在最後一組；條件名稱依序取專案的條件。", style={"margin": "0"}),
            rx.el.div(
                rx.el.div(
                    rx.el.span("條件數", class_name="label"),
                    select(state.count_options, state.cond_count.to_string(), state.set_cond_count,
                           style={"width": "6em"}),
                    class_name="field",
                ),
                rx.foreach(state.cond_indices, lambda i: _cond_input_row(state, i)),
                rx.cond(
                    state.group_mode == GroupMode.EVEN.value,
                    rx.el.p(f"{unit}依序平均分到各條件；無法整除時，前面的條件各多一個。", class_name="small muted",
                            style={"margin": "0"}),
                    rx.el.p(f"編號只填數字；範圍內沒有檔案的編號會自動略過。沒被分到的{unit}會放在「未分配」。",
                            class_name="small muted", style={"margin": "0"}),
                ),
                class_name="section", style={"gap": "10px"},
            ),
        ),
        rx.el.div(
            btn("套用分組", variant=BtnVariant.PRIMARY, on_click=state.apply_grouping, disabled=state.group_busy),
            _busy_mark(state),
            class_name="row",
        ),
    )


def _busy_mark(state) -> rx.Component:
    """等待 API 時，按鈕旁的八面體讀取動畫。"""
    return rx.cond(state.group_busy, rx.el.span(octa_loader(28), rx.el.span("處理中…", class_name="small muted"),
                                                class_name="row", style={"gap": "8px"}))


def grouping_adjust(state, after_confirmed: rx.Component, *extra: rx.Component, unit: str = "樣品") -> rx.Component:
    """套用後：點選微調 → 確定分組；確認後顯示 after_confirmed（通常是「下一步」），extra 放在最後。

    區塊 id 為 ADJUST_ID、確定那一列為 NEXT_ID：套用分組與確定分組後，頁面會自動捲到這裡。
    """
    return rx.el.div(_adjust_panel(state, after_confirmed, *extra, unit=unit), id=ADJUST_ID)


def _adjust_panel(state, after_confirmed: rx.Component, *extra: rx.Component, unit: str) -> rx.Component:
    """微調與確定的內容。"""
    return panel(
        "微調與確定",
        rx.el.p(f"點選{unit}卡片（反白）後，按條件框的「放到這裡」；按「移回這裡」放回未分配。",
                class_name="small muted", style={"margin": "0"}),
        rx.cond(
            state.unused_choices.length() > 0,
            rx.el.div(
                select(state.unused_choices, state.new_cond_name, state.set_new_cond_name,
                       placeholder="選擇要新增的條件", style={"width": "14em"}),
                btn("＋ 新增條件", small=True, on_click=state.add_condition),
                class_name="row",
            ),
        ),
        # 未分配區
        rx.el.div(
            rx.el.div(
                rx.el.strong("未分配"),
                rx.el.span(state.unassigned.length(),
                           class_name=rx.cond(state.unassigned.length() > 0, "tag warn", "tag ok")),
                class_name="row nowrap",
            ),
            rx.el.div(rx.foreach(state.unassigned, lambda s: _sample_chip(state, s)), class_name="row",
                      style={"gap": "6px", "min_height": "32px"}),
            btn("移回這裡", small=True, disabled=state.selected_sample == "", on_click=state.move_to_unassigned),
            class_name="cond-box", style={"background": "var(--surface)"},
        ),
        rx.el.div(rx.foreach(state.conditions, lambda c, i: _cond_box(state, c, i)), class_name="cond-grid"),
        rx.el.div(
            btn("確定分組", variant=BtnVariant.PRIMARY, on_click=state.confirm_grouping,
                disabled=~state.can_confirm_groups | state.group_busy),
            _busy_mark(state),
            rx.cond(
                state.groups_confirmed,
                rx.el.div(rx.el.span("已確認", class_name="tag ok"), after_confirmed, class_name="row"),
                rx.cond(
                    state.unassigned.length() > 0,
                    rx.el.span("尚未分配：", state.unassigned.join("、"), class_name="small",
                               style={"color": "var(--error)"}),
                ),
            ),
            class_name="row",
            id=NEXT_ID,
            style={"scroll_margin_bottom": "40vh"},  # 捲過來時不要貼在畫面最底
        ),
        *extra,
    )

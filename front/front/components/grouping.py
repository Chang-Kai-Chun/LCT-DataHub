"""分組畫面的共用元件（A JV 依樣品、B 暗電流依元件）。

state 參數為繼承 GroupingMixin 的 State 類別；unit 為畫面上的單位名稱（「樣品」或「元件」）。
"""
import reflex as rx

from front.enums import GroupMode, Route
from front.states.grouping import GroupCond


def _section(title: str, *children: rx.Component) -> rx.Component:
    """有標題的區塊。"""
    return rx.card(rx.vstack(rx.heading(title, size="3"), *children, spacing="3", width="100%"), width="100%")


def _labeled(label: str, control: rx.Component) -> rx.Component:
    """左標籤、右輸入框。"""
    return rx.hstack(rx.text(label, size="2", width="9em", flex_shrink="0"), control, align="center")


def _sample_chip(state, sample: rx.Var) -> rx.Component:
    """樣品卡片：點選後再按條件框的「放到這裡」。"""
    return rx.button(
        sample,
        size="1",
        variant=rx.cond(state.selected_sample == sample, "solid", "outline"),
        on_click=state.pick_sample(sample),
    )


def _cond_box(state, cond: GroupCond, index: rx.Var) -> rx.Component:
    """條件框。"""
    return rx.card(
        rx.vstack(
            rx.hstack(
                rx.text(cond.name, weight="bold"),
                rx.badge(cond.samples.length(), variant="soft"),
                rx.spacer(),
                rx.icon_button(
                    rx.icon("trash-2", size=14), size="1", variant="ghost", color_scheme="red",
                    on_click=state.remove_condition(index),
                ),
                width="100%",
                align="center",
            ),
            rx.flex(rx.foreach(cond.samples, lambda s: _sample_chip(state, s)), wrap="wrap", gap="1", min_height="2em"),
            rx.button(
                "放到這裡", size="1", variant="soft", width="100%",
                disabled=state.selected_sample == "",
                on_click=state.move_to(index),
            ),
            spacing="2",
            width="100%",
        ),
    )


def _cond_input_row(state, i: rx.Var) -> rx.Component:
    """第 i 個條件：名稱框；自訂時後方加「[字母] [起] 到 [迄]」與即時結果。"""
    is_custom = state.group_mode == GroupMode.CUSTOM.value
    # 樣品字母：只有一種時直接顯示，多種時給選單
    prefix = rx.cond(
        state.prefixes.length() > 1,
        rx.select(
            state.prefixes, value=state.range_prefix[i],
            on_change=lambda v: state.set_range_prefix(i, v), size="2",
        ),
        rx.text(state.range_prefix[i], weight="bold"),
    )
    return rx.hstack(
        rx.text(f"條件 {i + 1}", size="2", width="4em", flex_shrink="0"),
        rx.select(
            state.cond_choices, value=state.cond_names[i], on_change=lambda v: state.set_cond_name(i, v),
            placeholder="選擇條件", width="14em",
        ),
        rx.cond(
            is_custom,
            rx.hstack(
                prefix,
                rx.input(
                    value=state.range_from[i], on_change=lambda v: state.set_range_from(i, v),
                    placeholder="起", width="5em",
                ),
                rx.text("到"),
                prefix,
                rx.input(
                    value=state.range_to[i], on_change=lambda v: state.set_range_to(i, v),
                    placeholder="迄", width="5em",
                ),
                rx.text(state.range_previews[i], size="2", color=rx.color("gray", 11)),
                align="center",
            ),
        ),
        align="center",
        wrap="wrap",
    )


def _no_choices_callout() -> rx.Component:
    """專案還沒定義條件名稱時的提示（分組只能用專案的條件）。"""
    return rx.callout(
        rx.hstack(
            rx.text("這個專案還沒有定義條件名稱，分組只能使用專案統一的條件。"),
            rx.link("前往專案頁新增條件", href=Route.PROJECTS.value),
            spacing="2",
            wrap="wrap",
        ),
        icon="triangle-alert",
        color_scheme="amber",
    )


def grouping_settings(state, unit: str = "樣品") -> rx.Component:
    """分組方式 → 條件數 → N 個條件（從專案條件中選）→ 套用分組；專案沒有條件時只顯示提示。"""
    return rx.cond(state.has_choices, _grouping_settings(state, unit), _no_choices_callout())


def _grouping_settings(state, unit: str) -> rx.Component:
    """分組設定本體。"""
    is_auto = state.group_mode == GroupMode.AUTO.value
    return _section(
        "分組設定",
        rx.hstack(
            rx.text("專案條件：" + state.cond_choices.join("、"), size="2", color=rx.color("gray", 11)),
            rx.link("修改", href=Route.PROJECTS.value, size="2"),
            spacing="2",
        ),
        _labeled(
            "分組方式",
            rx.segmented_control.root(
                *[rx.segmented_control.item(m.value, value=m.value) for m in GroupMode],
                value=state.group_mode,
                on_change=state.set_group_mode,
            ),
        ),
        rx.text(f"本次{unit}：" + state.samples.join("、"), size="2", color=rx.color("gray", 11)),
        rx.cond(
            is_auto,
            rx.text(f"每 4 個{unit}一組，餘數放在最後一組；條件名稱依序取專案的條件。", size="2"),
            rx.vstack(
                _labeled(
                    "條件數",
                    rx.select(
                        state.count_options, value=state.cond_count.to_string(),
                        on_change=state.set_cond_count, width="6em",
                    ),
                ),
                rx.foreach(state.cond_indices, lambda i: _cond_input_row(state, i)),
                rx.cond(
                    state.group_mode == GroupMode.EVEN.value,
                    rx.text(f"{unit}依序平均分到各條件；無法整除時，前面的條件各多一個。", size="1", color=rx.color("gray", 10)),
                    rx.text(
                        f"編號只填數字；範圍內沒有檔案的編號會自動略過。沒被分到的{unit}會放在「未分配」。",
                        size="1", color=rx.color("gray", 10),
                    ),
                ),
                spacing="2",
                width="100%",
            ),
        ),
        rx.button(rx.icon("wand-sparkles", size=16), "套用分組", size="3", on_click=state.apply_grouping),
    )


def grouping_adjust(state, after_confirmed: rx.Component, *extra: rx.Component, unit: str = "樣品") -> rx.Component:
    """套用後：點選微調 → 確定分組；確認後顯示 after_confirmed（通常是「下一步」），extra 放在最後。"""
    return _section(
        "微調與確定",
        rx.text(f"需要調整時：點選{unit}卡片（變成實心），再按條件框的「放到這裡」；按「移回這裡」放回未分配區。", size="2"),
        rx.cond(
            state.unused_choices.length() > 0,
            rx.hstack(
                rx.select(
                    state.unused_choices, value=state.new_cond_name, on_change=state.set_new_cond_name,
                    placeholder="選擇要新增的條件",
                ),
                rx.button(rx.icon("plus", size=14), "新增條件", variant="soft", on_click=state.add_condition),
            ),
        ),
        # 未分配區
        rx.card(
            rx.vstack(
                rx.hstack(
                    rx.text("未分配", weight="bold"),
                    rx.badge(
                        state.unassigned.length(),
                        color_scheme=rx.cond(state.unassigned.length() > 0, "red", "green"),
                    ),
                    align="center",
                ),
                rx.flex(rx.foreach(state.unassigned, lambda s: _sample_chip(state, s)), wrap="wrap", gap="1", min_height="2em"),
                rx.button(
                    "移回這裡", size="1", variant="soft", color_scheme="gray",
                    disabled=state.selected_sample == "", on_click=state.move_to_unassigned,
                ),
                spacing="2",
                width="100%",
            ),
            background=rx.color("gray", 2),
            width="100%",
        ),
        rx.grid(
            rx.foreach(state.conditions, lambda c, i: _cond_box(state, c, i)),
            columns="3", spacing="3", width="100%",
        ),
        rx.hstack(
            rx.button(
                rx.icon("check", size=16), "確定分組", size="3",
                on_click=state.confirm_grouping, disabled=~state.can_confirm_groups,
            ),
            rx.cond(
                state.groups_confirmed,
                rx.hstack(rx.badge("已確認", color_scheme="green", size="2"), after_confirmed, align="center"),
                rx.cond(
                    state.unassigned.length() > 0,
                    rx.text("尚未分配：" + state.unassigned.join("、"), size="2", color=rx.color("red", 10)),
                ),
            ),
            align="center",
        ),
        *extra,
    )

import streamlit as st

from components.money import format_money


def show_close_month_dialog(
    month_name,
    pending_items,
    on_confirm=None
):

    @st.dialog("Close Cycle", width="large")
    def dialog():

        if not pending_items:

            st.success(
                "🎉 Everything has been completed."
            )

            if st.button(
                "Close Cycle",
                type="primary",
                use_container_width=True
            ):

                if on_confirm:
                    on_confirm([])

                st.rerun()

            return

        updated_items = []

        def clear_dialog_state():
            for item in pending_items:
                item_key = f"{item['type']}_{item['id']}"

                st.session_state.pop(
                    f"close_action_{item_key}",
                    None
                )

                st.session_state.pop(
                    f"close_amount_{item_key}",
                    None
                )

        st.markdown(f"""
        <div class="close-header">
            <div class="close-subtitle">Review the remaining obligations before closing {month_name}.</div>
        </div>
        """, unsafe_allow_html=True)

        paid_count = 0
        cancelled_count = 0
        carry_count = 0

        def set_close_action(key, value):
            st.session_state[key] = value

        for item in pending_items:

            item_key = f"{item['type']}_{item['id']}"
            action_key = f"close_action_{item_key}"

            if action_key not in st.session_state:
                st.session_state[action_key] = item["default_action"]

            amount_key = f"close_amount_{item_key}"

            if amount_key not in st.session_state:
                st.session_state[amount_key] = float(
                    item["expected"]
                )

            with st.container(border=True):

                top_left, top_right = st.columns([3,1])

                with top_left:
                    status = st.session_state[action_key]

                    colour = {
                        None: "#94A3B8",
                        "Paid": "#4ADE80",
                        "Cancelled": "#F87171",
                        "Carry Forward": "#FBBF24"
                    }[status]

                    label = status if status else "Choose an action"
                    st.markdown(
                        f"""
                        <div class="close-item">
                            <div class="close-icon">{item['icon']}</div>
                            <div>
                                <div class="close-name">{item['name']}</div>
                                <div class="close-expected">Expected {format_money(item['expected'])}</div>
                                <div
                                    style="
                                        display:inline-block;
                                        margin-top:10px;
                                        padding:6px 14px;
                                        border-radius:999px;
                                        background:{colour}20;
                                        color:{colour};
                                        font-size:13px;
                                        font-weight:700;
                                    "
                                >
                                    ● {label}
                                </div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

                with top_right:

                    st.number_input(
                        "Actual",
                        min_value=0.0,
                        step=0.01,
                        placeholder="Enter Amount",
                        format="%.2f",
                        key=amount_key,
                        label_visibility="visible"
                    )

                b1, b2, b3 = st.columns(3)

                with b1:

                    if st.button(
                        "✅ Paid",
                        key=f"paid_{item_key}",
                        use_container_width=True,
                        on_click=set_close_action,
                        args=(
                            action_key,
                            "Paid"
                        )
                    ):
                        st.session_state[action_key] = "Paid"

                with b2:

                    if st.button(
                        "❌ Cancel",
                        key=f"cancel_{item_key}",
                        use_container_width=True,
                        on_click=set_close_action,
                        args=(
                            action_key,
                            "Cancelled"
                        )
                    ):
                        st.session_state[action_key] = "Cancelled"

                with b3:
                    if st.button(
                        "↩ Carry",
                        key=f"carry_{item_key}",
                        use_container_width=True,
                        on_click=set_close_action,
                        args=(
                            action_key,
                            "Carry Forward"
                        )
                    ):
                        st.session_state[action_key] = "Carry Forward"

                action = st.session_state[action_key]
                amount = st.session_state[amount_key]

                if action == "Paid":
                    paid_count += 1

                elif action == "Cancelled":
                    cancelled_count += 1

                elif action == "Carry Forward":
                    carry_count += 1

                updated_items.append({
                    "id": item["id"],
                    "type": item["type"],
                    "action": action,
                    "amount": amount
                })

                st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

        with st.container(border=True):

            st.markdown(
                "<div class='close-summary-title'>CYCLE SUMMARY</div>",
                unsafe_allow_html=True
            )

            c1, c2, c3 = st.columns(3)

            with c1:
                st.metric("🟢 Paid", paid_count)

            with c2:
                st.metric("🔴 Cancelled", cancelled_count)

            with c3:
                st.metric("🟡 Carry", carry_count)

            st.markdown("<div style='height:10px'></div>", unsafe_allow_html=True)

            st.caption(
                "Closing this financial cycle marks it completed "
                "and starts the next cycle."
            )

            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)

            left, right = st.columns([1,1])

            with left:

                if st.button(
                    "Cancel",
                    use_container_width=True,
                    key="cancel_close_month"
                ):

                    clear_dialog_state()

                    st.rerun()

            with right:

                if st.button(
                    "Close Cycle",
                    type="primary",
                    use_container_width=True
                ):

                    unresolved = [
                        item
                        for item in updated_items
                        if item["action"] is None
                    ]

                    if unresolved:

                        st.error(
                            "Please choose an action for every pending item."
                        )

                        st.stop()

                    invalid_amounts = [
                        item
                        for item in updated_items
                        if (
                            item["action"] in [
                                "Paid",
                                "Carry Forward"
                            ]
                            and item["amount"] <= 0
                        )
                    ]

                    if invalid_amounts:

                        st.error(
                            "Paid and carried items must have an amount greater than zero."
                        )

                        st.stop()

                    if on_confirm:
                        on_confirm(updated_items)

                    for item in pending_items:
                        item_key = f"{item['type']}_{item['id']}"

                        st.session_state.pop(
                            f"close_action_{item_key}",
                            None
                        )

                        st.session_state.pop(
                            f"close_amount_{item_key}",
                            None
                        )

                    st.rerun()

    dialog()

import streamlit as st

from components.money import format_money
from components.responsive import mobile_label


def render_activity_row(
    *,
    item_id,
    icon,
    name,
    expected,
    actual,
    due_day,
    month_name,
    status,
    complete_text,
    complete_status,
    complete_callback,
    cancel_callback,
    input_prefix, read_only=False
):

    cols = st.columns(
    [2.1, 1.3, 1.35, 0.9, 0.9, 1.1],
    vertical_alignment="center"
)

    # --------------------------------------------------
    # NAME
    # --------------------------------------------------

    with cols[0]:

        st.markdown(
            f"""
            <div class="mv-mobile-labeled" {mobile_label("Obligation")} style="
                display:flex;
                align-items:center;
                height:42px;
                font-size:18px;
                font-weight:600;
            ">
                {icon}&nbsp;&nbsp;{name}
            </div>
            """,
            unsafe_allow_html=True
        )

    # --------------------------------------------------
    # EXPECTED
    # --------------------------------------------------

    with cols[1]:

        st.markdown(
            f"""
            <div class="mv-mobile-labeled" {mobile_label("Expected")} style="
                display:flex;
                align-items:center;
                height:42px;
                font-size:18px;
            ">
                {format_money(expected)}
            </div>
            """,
            unsafe_allow_html=True
        )

    # --------------------------------------------------
    # ACTUAL
    # --------------------------------------------------

    with cols[2]:
        left, middle, right = st.columns([4, 1, 1])
        with left:
            actual_input = st.text_input(
                "Actual",
                value=str(
                    int(actual)
                    if actual is not None
                    else int(expected)
                ),
                key=f"{input_prefix}_{item_id}",
                label_visibility="collapsed", disabled=read_only
            )
        
        try:
            actual_amount = float(
                actual_input.replace(",", "")
            )

        except ValueError:

            st.error(
                "Please enter a valid amount."
            )

            st.stop()

    # --------------------------------------------------
    # DUE DAY
    # --------------------------------------------------

    with cols[3]:

        st.markdown(
            f"""
            <div class="mv-mobile-labeled" {mobile_label("Due")} style="
                display:flex;
                align-items:center;
                height:42px;
                font-size:18px;
            ">
                {due_day} {month_name}
            </div>
            """,
            unsafe_allow_html=True
        )

    # --------------------------------------------------
    # STATUS
    # --------------------------------------------------

    with cols[4]:

        if status == complete_status:

            css = "status-success"
            text = complete_text

        elif status == "CANCELLED":

            css = "status-cancelled"
            text = "Cancelled"

        elif status == "CARRIED_FORWARD":

            css = "status-pending"
            text = "Carried"

        else:

            css = "status-pending"
            text = "Pending"

        st.markdown(
            f"""
            <div class="mv-mobile-labeled" {mobile_label("Status")} style="
                display:flex;
                align-items:center;
                height:42px;
            ">
                <span class="{css}">
                    {text}
                </span>
            </div>
            """,
            unsafe_allow_html=True
        )

    # --------------------------------------------------
    # ACTIONS
    # --------------------------------------------------

    with cols[5]:

        if status == "PENDING":

            left, right = st.columns(2)

            with left:

                if st.button(
                    "✓",
                    key=f"{input_prefix}_complete_{item_id}",
                    use_container_width=True, disabled=read_only
                ):

                    complete_callback(actual_amount)
                    st.rerun()

            with right:

                if st.button(
                    "✕",
                    key=f"{input_prefix}_cancel_{item_id}",
                    use_container_width=True, disabled=read_only
                ):

                    cancel_callback()
                    st.rerun()

        else:

            # Keep the column width identical even when
            # buttons are hidden.
            st.write("")

    return actual_amount

import streamlit as st

from components.money import format_money


def render_template_table(
    rows,
    icon_function,
    action_prefix, read_only=False
):
    """
    Generic renderer for Income / Commitment tables.
    """

    st.markdown("""
    <div class="table-header">
        <div>Name</div>
        <div>Amount</div>
        <div>Due Day</div>
        <div>Account</div>
        <div>Action</div>
    </div>
    """,
    unsafe_allow_html=True)

    for row in rows:

        item_id = row[0]
        name = row[1]
        amount = row[2]
        due_day = row[3]
        account_name = row[4]

        icon = icon_function(name)

        row_col1, row_col2 = st.columns(
            [20,1]
        )

        with row_col1:

            st.markdown(
            f"""
            <div class="commitment-row">
                <div class="commitment-cell commitment-name">{icon} {name}</div>
                <div class="commitment-cell">{format_money(amount)}</div>
                <div class="commitment-cell">{due_day}</div>
                <div class="commitment-cell">🏦 {account_name}</div>
            </div>
            """,
            unsafe_allow_html=True
            )

        with row_col2:

            if st.button(
                "→",
                key=f"{action_prefix}_edit_{item_id}", disabled= read_only
            ):

                st.session_state[
                    f"edit_{action_prefix}_id"
                ] = item_id

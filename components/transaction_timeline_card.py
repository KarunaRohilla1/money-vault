import streamlit as st


def transaction_timeline_card(transaction_id,
    icon,
    category,
    account,
    amount,
    notes="",
    transaction_type="Expense"
):

    if transaction_type == "Income":
        amount_class = "transaction-income"
    elif transaction_type == "Transfer":
        amount_class = "transaction-transfer"
    else:
        amount_class = "transaction-expense"

    notes_html = ""

    if notes:
        notes_html = f"""<div class="transaction-notes">{notes}</div>"""

    left, right = st.columns([12, 2])
    with left:
        st.markdown(
        f"""<div class="transaction-card">
            <div class="transaction-header">
                <div class="transaction-left">
                    <div class="transaction-icon">{icon}</div>
                    <div>
                        <div class="transaction-title">{category}</div>
                        <div class="transaction-account">{account}</div>
                        {notes_html} </div>
                    </div>
                <div class="transaction-right">
                    <div class="{amount_class}">₹{amount:,.0f}</div>
                </div>
            </div>
        </div>""",
        unsafe_allow_html=True
    )

    with right:

        col1, col2 = st.columns(2)

        with col1:

            if st.button(
                "✏️",
                key=f"edit_{transaction_id}",
                disabled=transaction_type == "Transfer"
            ):
                st.session_state.delete_transaction_id = None
                st.session_state.edit_transaction_id = transaction_id

                st.rerun()

        with col2:

            if st.button(
                "🗑️",
                key=f"delete_{transaction_id}"
            ):
                st.session_state.edit_transaction_id = None
                st.session_state.delete_transaction_id = transaction_id

                st.rerun()

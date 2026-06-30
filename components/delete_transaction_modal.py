import streamlit as st

from db.transactions import delete_transaction


@st.dialog("🗑 Delete Transaction")
def delete_transaction_dialog(
    transaction_id
):

    st.warning(
        "Are you sure you want to delete this transaction?"
    )

    col1, col2 = st.columns(2)

    with col1:

        if st.button(
            "Cancel",
            use_container_width=True
        ):

            st.session_state.delete_transaction_id = None

            st.rerun()

    with col2:

        if st.button(
            "Delete",
            use_container_width=True
        ):

            delete_transaction(
                transaction_id
            )

            st.session_state.delete_transaction_id = None

            st.rerun()

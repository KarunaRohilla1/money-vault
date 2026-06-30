import streamlit as st

from components.transaction_form import (
    transaction_form
)

@st.dialog("✏️ Edit Transaction")
def edit_transaction_dialog(
    vault_id,
    transaction_id
):

    transaction_form(
        vault_id,
        form_key=f"edit_{transaction_id}",
        transaction_id=transaction_id
    )
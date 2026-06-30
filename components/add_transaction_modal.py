import streamlit as st

from components.transaction_form import (
    transaction_form
)


@st.dialog("🧾 Record Transaction")
def add_transaction_dialog(
    vault_id
):

    transaction_form(
        vault_id,
        "dashboard_transaction_form", allow_add_another=True
    )
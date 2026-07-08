import streamlit as st

from components.transaction_form import transaction_form
from db.vaults import get_shared_vault_participants


@st.dialog("Add Shared Expense")
def add_shared_expense_dialog(shared_vault_id):
    participants = get_shared_vault_participants(
        shared_vault_id
    )

    if not participants:
        st.warning(
            "Add individual participants to this shared vault before recording shared expenses."
        )
        return

    payer_map = {
        participant[1]: participant[0]
        for participant in participants
    }
    payer_name = st.selectbox(
        "Paid By",
        list(payer_map.keys()),
        key="shared_expense_payer"
    )

    transaction_form(
        payer_map[payer_name],
        "shared_dashboard_transaction_form",
        allow_add_another=True,
        forced_beneficiary_vault_id=shared_vault_id,
        dialog_state_key="show_shared_expense_dialog"
    )

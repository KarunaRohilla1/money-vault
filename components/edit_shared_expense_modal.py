import streamlit as st

from components.transaction_form import transaction_form
from db.vaults import get_shared_vault_participants


def show_edit_shared_expense_dialog(
    shared_vault_id,
    expense
):
    @st.dialog("Edit Shared Expense")
    def dialog():
        participants = get_shared_vault_participants(
            shared_vault_id
        )

        if not participants:
            st.warning(
                "Add individual participants to this shared vault before editing shared expenses."
            )
            return

        payer_map = {
            participant[1]: participant[0]
            for participant in participants
        }
        payer_names = list(
            payer_map.keys()
        )
        current_payer_name = expense["paid_by"]
        default_index = (
            payer_names.index(current_payer_name)
            if current_payer_name in payer_names
            else 0
        )

        payer_name = st.selectbox(
            "Paid By",
            payer_names,
            index=default_index,
            key=f"edit_shared_expense_payer_{expense['id']}"
        )

        transaction_form(
            payer_map[payer_name],
            form_key=f"edit_shared_expense_{expense['id']}",
            transaction_id=expense["id"],
            forced_beneficiary_vault_id=shared_vault_id,
            allow_delete=True,
            edit_session_key="edit_shared_expense_id"
        )

    dialog()

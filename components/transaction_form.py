import streamlit as st
from datetime import date

from db.accounts import get_accounts
from db.categories import get_category_dropdown
from db.transactions import (
    add_transaction,
    get_transaction_by_id,
    update_transaction
)


def transaction_form(
    vault_id,
    form_key="transaction_form",
    allow_add_another=False,
    transaction_id=None
):

    accounts = get_accounts(vault_id)
    categories = get_category_dropdown(vault_id)
    existing_transaction = None

    if transaction_id:

        existing_transaction = (
            get_transaction_by_id(
                transaction_id
            )
        )

        if not existing_transaction:
            st.error(
                "Transaction not found. It may have been deleted."
            )
            return

    if not accounts:
        st.warning(
            "Create an account first."
        )
        return

    if not categories:
        st.warning(
            "Create a category first."
        )
        return

    account_map = {
        account[1]: account[0]
        for account in accounts
    }

    category_map = {
        f"{cat[1]} {cat[2]}": (
            cat[0],
            cat[3]
        )
        for cat in categories
    }

    default_amount = ""
    default_notes = ""
    default_date = date.today()

    default_account_index = 0
    default_category_index = 0

    if existing_transaction:

        existing_account_id = existing_transaction[1]

        existing_category_id = existing_transaction[2]

        default_date = date.fromisoformat(
            existing_transaction[3]
        )

        default_amount = str(
            existing_transaction[4]
        )

        default_notes = (
            existing_transaction[6] or ""
        )

        account_ids = [
            account[0]
            for account in accounts
        ]

        category_ids = [
            cat[0]
            for cat in categories
        ]

        if existing_account_id not in account_ids:
            st.error(
                "This transaction uses an archived or missing account. Restore the account or delete the transaction."
            )
            return

        default_account_index = account_ids.index(
            existing_account_id
        )

        if existing_category_id in category_ids:

            default_category_index = (
                category_ids.index(
                    existing_category_id
                )
            )

    with st.form(form_key):

        amount_text = st.text_input(
    "Amount",
    value=default_amount,
    placeholder="₹ Enter amount"
)

        txn_date = st.date_input(
            "Date",
            value=default_date,
            key=f"{form_key}_date"
        )

        account_name = st.selectbox(
            "Account",
            list(account_map.keys()),
            key=f"{form_key}_account", index=default_account_index
        )

        category_name = st.selectbox(
            "Category",
            list(category_map.keys()),
            key=f"{form_key}_category", index=default_category_index
        )

        notes = st.text_area(
    "Notes",
    value=default_notes,
    key=f"{form_key}_notes"
)

        category_id = category_map[
            category_name
        ][0]

        transaction_type = category_map[
            category_name
        ][1]

        save_clicked = False
        save_another_clicked = False
        cancel_clicked = False

        if allow_add_another:

            col1, col2, col3 = st.columns(3)

            with col1:

                save_clicked = (
                    st.form_submit_button(
    "💾 Save",
    use_container_width=True)
                )

            with col2:

                save_another_clicked = (
                    st.form_submit_button(
    "Save Another",
    use_container_width=True
)
                )

            with col3:

                cancel_clicked = (
                    st.form_submit_button(
                        "Cancel",
                        use_container_width=True
                    )
                )

        else:

            col1, col2 = st.columns(2)

            with col1:

                save_clicked = (
                    st.form_submit_button(
                        "Save Transaction",
                        use_container_width=True
                    )
                )

            with col2:

                cancel_clicked = (
                    st.form_submit_button(
                        "Cancel",
                        use_container_width=True
                    )
                )

        if cancel_clicked:
            if transaction_id:
                st.session_state.edit_transaction_id = None
            else:
                st.session_state.show_transaction_dialog = False

            st.rerun()

        if save_clicked or save_another_clicked:

            try:
                cleaned_amount = (
                    amount_text
                    .replace(",", "")
                    .replace("₹", "")
                    .strip()
                )
                amount = float(cleaned_amount)
            except ValueError:
                st.error(
                    "Please enter a valid amount."
                )
                st.stop()

            if amount <= 0:

                st.error(
                    "Amount must be greater than zero."
                )

            else:
                if transaction_id:

                    update_transaction(
                        transaction_id,
                        account_map[account_name],
                        category_id,
                        str(txn_date),
                        amount,
                        notes.strip(),
                        transaction_type
                    )
                    st.session_state.edit_transaction_id = None
                    st.rerun()

                else:

                    add_transaction(
                        vault_id,
                        account_map[account_name],
                        str(txn_date),
                        amount,
                        category_id,
                        transaction_type,
                        notes.strip()
                    )

                # SAVE
                if save_clicked:

                    st.session_state.show_transaction_dialog = False

                    st.rerun()

                # SAVE & ADD ANOTHER
                elif save_another_clicked:

                    st.rerun()

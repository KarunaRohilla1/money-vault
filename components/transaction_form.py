from datetime import date

import streamlit as st

from db.accounts import get_accounts
from db.categories import get_category_dropdown
from db.transaction_shares import (
    ALLOCATION_EQUAL,
    ALLOCATION_FIXED,
    ALLOCATION_METHODS,
    ALLOCATION_PERCENTAGE,
    calculate_transaction_shares,
    cents,
    get_transaction_shares
)
from db.transactions import (
    add_transaction,
    get_transaction_by_id,
    update_transaction
)
from db.vaults import (
    get_connected_shared_vaults,
    get_shared_vault_participants,
    get_vault_by_id
)


def parse_amount_text(amount_text):
    cleaned_amount = (
        amount_text
        .replace(",", "")
        .replace("Rs.", "")
        .replace("₹", "")
        .replace("â‚¹", "")
        .replace("Ã¢â€šÂ¹", "")
        .strip()
    )
    return float(cleaned_amount)


def amount_preview(amount_text):
    try:
        amount = parse_amount_text(
            amount_text
        )
    except ValueError:
        return 0

    return max(
        amount,
        0
    )


def allocation_remaining_label(allocation_method, amount, participant_values):
    if allocation_method == ALLOCATION_PERCENTAGE:
        remaining = round(
            100 - sum(participant_values.values()),
            2
        )
        return f"Remaining percentage: {remaining:.2f}%"

    if allocation_method == ALLOCATION_FIXED:
        remaining_cents = (
            cents(amount)
            - sum(
                cents(value)
                for value in participant_values.values()
            )
        )
        return f"Remaining amount: Rs. {remaining_cents / 100:,.2f}"

    return ""


def render_equal_preview(amount, participant_vaults):
    if not participant_vaults:
        return

    try:
        shares = calculate_transaction_shares(
            amount,
            ALLOCATION_EQUAL,
            participant_vaults
        )
    except ValueError:
        shares = []

    share_map = {
        share["participant_vault_id"]: share
        for share in shares
    }

    st.caption(
        f"Participants ({len(participant_vaults)})"
    )

    for participant in participant_vaults:
        share = share_map.get(
            participant[0],
            {}
        )
        percentage = share.get(
            "share_percentage",
            0
        )
        share_amount = share.get(
            "share_amount",
            0
        )

        left, right = st.columns(
            [2, 1],
            vertical_alignment="center"
        )

        with left:
            st.write(
                participant[1]
            )

        with right:
            st.write(
                f"{percentage:.0f}% - Rs. {share_amount:,.2f}"
            )


def transaction_form(
    vault_id,
    form_key="transaction_form",
    allow_add_another=False,
    transaction_id=None,
    forced_beneficiary_vault_id=None,
    dialog_state_key="show_transaction_dialog"
):

    reset_token_key = f"{form_key}_reset_token"
    if reset_token_key not in st.session_state:
        st.session_state[reset_token_key] = 0

    field_key_prefix = form_key
    if not transaction_id:
        field_key_prefix = (
            f"{form_key}_{st.session_state[reset_token_key]}"
        )

    accounts = get_accounts(vault_id)
    categories = get_category_dropdown(vault_id)
    current_vault = get_vault_by_id(vault_id)
    shared_vaults = get_connected_shared_vaults(vault_id)
    if forced_beneficiary_vault_id:
        forced_shared_vault = get_vault_by_id(
            forced_beneficiary_vault_id
        )
        if forced_shared_vault:
            shared_vaults = [
                forced_shared_vault
            ]
    existing_transaction = None
    existing_shares = []

    if transaction_id:
        existing_transaction = get_transaction_by_id(
            transaction_id
        )

        if not existing_transaction:
            st.error(
                "Transaction not found. It may have been deleted."
            )
            return

        existing_shares = get_transaction_shares(
            transaction_id
        )

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
    default_amount = ""
    default_notes = ""
    default_date = date.today()
    default_account_index = 0
    default_category_index = 0
    default_beneficiary_id = vault_id
    default_allocation_method = ALLOCATION_EQUAL

    if existing_transaction:
        existing_account_id = existing_transaction[1]
        existing_category_id = existing_transaction[2]
        default_date = date.fromisoformat(
            existing_transaction[3]
        )
        default_amount = str(
            existing_transaction[4]
        )
        default_notes = existing_transaction[6] or ""
        default_beneficiary_id = (
            existing_transaction[7]
            if len(existing_transaction) > 7 and existing_transaction[7]
            else vault_id
        )
        default_allocation_method = (
            existing_transaction[8]
            if len(existing_transaction) > 8 and existing_transaction[8]
            else ALLOCATION_EQUAL
        )

        account_ids = [
            account[0]
            for account in accounts
        ]
        if existing_account_id not in account_ids:
            st.error(
                "This transaction uses an archived or missing account. Restore the account or delete the transaction."
            )
            return

        default_account_index = account_ids.index(
            existing_account_id
        )

    amount_text = st.text_input(
        "Amount",
        value=default_amount,
        placeholder="Rs. Enter amount",
        key=f"{field_key_prefix}_amount"
    )

    txn_date = st.date_input(
        "Date",
        value=default_date,
        key=f"{field_key_prefix}_date"
    )

    has_shared_vaults = bool(
        shared_vaults
    )

    if has_shared_vaults:
        account_name = st.selectbox(
            "Account (Paid From)",
            list(account_map.keys()),
            key=f"{field_key_prefix}_account",
            index=default_account_index
        )

    else:
        account_name = st.selectbox(
            "Account",
            list(account_map.keys()),
            key=f"{field_key_prefix}_account",
            index=default_account_index
        )

    beneficiary_vault_id = vault_id
    allocation_method = None
    participant_vaults = []
    percentage_allocations = {}
    amount_allocations = {}

    if has_shared_vaults:
        default_scope = (
            "Shared"
            if (
                forced_beneficiary_vault_id
                or int(default_beneficiary_id) != int(vault_id)
            )
            else "Personal"
        )
        if forced_beneficiary_vault_id:
            expense_scope = "Shared"
        else:
            expense_scope = st.radio(
                "Expense Type",
                ["Personal", "Shared"],
                index=0 if default_scope == "Personal" else 1,
                horizontal=True,
                key=f"{field_key_prefix}_expense_scope"
            )

        if expense_scope == "Shared":
            shared_map = {
                vault[1]: vault[0]
                for vault in shared_vaults
            }
            shared_names = list(
                shared_map.keys()
            )
            default_shared_index = 0

            if default_beneficiary_id in shared_map.values():
                default_shared_index = list(
                    shared_map.values()
                ).index(
                    default_beneficiary_id
                )

            if forced_beneficiary_vault_id:
                shared_name = shared_names[default_shared_index]
            else:
                shared_name = st.selectbox(
                    "Select Shared Vault",
                    shared_names,
                    index=default_shared_index,
                    key=f"{field_key_prefix}_shared_vault"
                )
            beneficiary_vault_id = shared_map[
                shared_name
            ]
            st.caption(
                "All participants in this shared vault will be shown for allocation."
            )

            participant_vaults = get_shared_vault_participants(
                beneficiary_vault_id
            )

            if not participant_vaults:
                st.warning(
                    "This shared vault has no participants."
                )

            allocation_method = st.radio(
                "Split Type",
                ALLOCATION_METHODS,
                index=(
                    ALLOCATION_METHODS.index(default_allocation_method)
                    if default_allocation_method in ALLOCATION_METHODS
                    else 0
                ),
                horizontal=True,
                key=f"{field_key_prefix}_allocation_method"
            )

            preview_amount = amount_preview(
                amount_text
            )
            existing_share_map = {
                share[2]: share
                for share in existing_shares
            }

            if allocation_method == ALLOCATION_EQUAL:
                st.info(
                    "This amount will be split equally among all participants in the selected shared vault."
                )
                render_equal_preview(
                    preview_amount,
                    participant_vaults
                )
                st.caption(
                    "Split preview is based on amount entered."
                )

            elif allocation_method == ALLOCATION_PERCENTAGE:
                allocation_values = {}

                for participant in participant_vaults:
                    participant_id = participant[0]
                    existing_share = existing_share_map.get(
                        participant_id
                    )
                    default_percentage = (
                        float(existing_share[5] or 0)
                        if existing_share
                        else round(
                            100 / max(len(participant_vaults), 1),
                            2
                        )
                    )

                    allocation_values[participant_id] = st.number_input(
                        participant[1],
                        min_value=0.0,
                        max_value=100.0,
                        value=default_percentage,
                        step=1.0,
                        key=f"{field_key_prefix}_share_percentage_{participant_id}"
                    )

                percentage_allocations = allocation_values
                st.caption(
                    allocation_remaining_label(
                        allocation_method,
                        preview_amount,
                        allocation_values
                    )
                )

            elif allocation_method == ALLOCATION_FIXED:
                allocation_values = {}

                for participant in participant_vaults:
                    participant_id = participant[0]
                    existing_share = existing_share_map.get(
                        participant_id
                    )
                    default_amount_value = (
                        float(existing_share[4] or 0)
                        if existing_share
                        else round(
                            preview_amount / max(len(participant_vaults), 1),
                            2
                        )
                    )

                    allocation_values[participant_id] = st.number_input(
                        participant[1],
                        min_value=0.0,
                        value=default_amount_value,
                        step=0.01,
                        format="%.2f",
                        key=f"{field_key_prefix}_share_amount_{participant_id}"
                    )

                amount_allocations = allocation_values
                st.caption(
                    allocation_remaining_label(
                        allocation_method,
                        preview_amount,
                        allocation_values
                    )
                )

    visible_categories = categories

    if has_shared_vaults and expense_scope == "Shared":
        visible_categories = [
            category
            for category in categories
            if len(category) > 5 and category[5]
        ]

    if not visible_categories:
        st.warning(
            "System categories are not configured."
        )
        return

    category_map = {
        f"{cat[1]} {cat[2]}": (
            cat[0],
            cat[3]
        )
        for cat in visible_categories
    }

    category_ids = [
        cat[0]
        for cat in visible_categories
    ]

    if existing_transaction:
        existing_category_id = existing_transaction[2]
        if existing_category_id in category_ids:
            default_category_index = category_ids.index(
                existing_category_id
            )
        elif has_shared_vaults and expense_scope == "Shared":
            default_category_index = 0

    category_name = st.selectbox(
        "Category",
        list(category_map.keys()),
        key=f"{field_key_prefix}_category",
        index=default_category_index
    )

    notes = st.text_area(
        "Notes",
        value=default_notes,
        key=f"{field_key_prefix}_notes"
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
            save_clicked = st.button(
                "Save",
                use_container_width=True,
                key=f"{form_key}_save"
            )

        with col2:
            save_another_clicked = st.button(
                "Save Another",
                use_container_width=True,
                key=f"{form_key}_save_another"
            )

        with col3:
            cancel_clicked = st.button(
                "Cancel",
                use_container_width=True,
                key=f"{form_key}_cancel"
            )

    else:
        col1, col2 = st.columns(2)

        with col1:
            save_clicked = st.button(
                "Save Transaction",
                use_container_width=True,
                key=f"{form_key}_save"
            )

        with col2:
            cancel_clicked = st.button(
                "Cancel",
                use_container_width=True,
                key=f"{form_key}_cancel"
            )

    if cancel_clicked:
        if transaction_id:
            st.session_state.edit_transaction_id = None
        else:
            st.session_state[dialog_state_key] = False

        st.rerun()

    if save_clicked or save_another_clicked:
        try:
            amount = parse_amount_text(
                amount_text
            )
        except ValueError:
            st.error(
                "Please enter a valid amount."
            )
            st.stop()

        if amount <= 0:
            st.error(
                "Amount must be greater than zero."
            )
            st.stop()

        try:
            if transaction_id:
                update_transaction(
                    transaction_id,
                    account_map[account_name],
                    category_id,
                    str(txn_date),
                    amount,
                    notes.strip(),
                    transaction_type,
                    vault_id=vault_id,
                    beneficiary_vault_id=beneficiary_vault_id,
                    allocation_method=allocation_method,
                    participant_vaults=participant_vaults,
                    percentage_allocations=percentage_allocations,
                    amount_allocations=amount_allocations
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
                    notes.strip(),
                    beneficiary_vault_id=beneficiary_vault_id,
                    allocation_method=allocation_method,
                    participant_vaults=participant_vaults,
                    percentage_allocations=percentage_allocations,
                    amount_allocations=amount_allocations
                )

        except ValueError as error:
            st.error(
                str(error)
            )
            st.stop()

        if save_clicked:
            st.session_state[dialog_state_key] = False
            st.rerun()

        elif save_another_clicked:
            if not transaction_id:
                st.session_state[reset_token_key] += 1
                st.session_state[dialog_state_key] = True
            st.rerun()

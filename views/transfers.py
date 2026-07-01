from datetime import date

import pandas as pd
import streamlit as st

from db.accounts import (
    get_account_balances,
    get_accounts
)
from db.transfers import (
    add_transfer,
    delete_transfer,
    get_transfer_by_group,
    get_transfers,
    update_transfer
)


INITIAL_TRANSFER_LIMIT = 5


def format_money(amount):

    return f"₹{amount:,.0f}"


def account_badge(name):

    return "".join(
        word[0]
        for word in name.split()[:2]
    ).upper()


def validate_transfer(
    from_account_id,
    to_account_id,
    amount
):

    if from_account_id == to_account_id:

        st.error(
            "Accounts must be different."
        )

        return False

    if amount <= 0:

        st.error(
            "Amount must be greater than zero."
        )

        return False

    return True


@st.dialog("Edit Transfer")
def edit_transfer_dialog(
    transfer_group_id,
    accounts
):

    transfer = get_transfer_by_group(
        transfer_group_id
    )

    if not transfer:

        st.error(
            "Transfer not found."
        )

        if st.button("Close"):
            st.session_state.edit_transfer_group_id = None
            st.rerun()

        return

    account_map = {
        account[1]: account[0]
        for account in accounts
    }

    account_names = list(
        account_map.keys()
    )

    account_ids = [
        account[0]
        for account in accounts
    ]

    if (
        transfer[3] not in account_ids
        or transfer[4] not in account_ids
    ):
        st.error(
            "This transfer uses an archived or missing account and cannot be edited."
        )
        if st.button("Close"):
            st.session_state.edit_transfer_group_id = None
            st.rerun()
        return

    from_index = account_ids.index(
        transfer[3]
    )

    to_index = account_ids.index(
        transfer[4]
    )

    transfer_date = date.fromisoformat(
        transfer[2]
    )

    from_account = st.selectbox(
        "From Account",
        account_names,
        index=from_index,
        key=f"edit_from_{transfer_group_id}"
    )

    to_account = st.selectbox(
        "To Account",
        account_names,
        index=to_index,
        key=f"edit_to_{transfer_group_id}"
    )

    amount = st.number_input(
        "Amount",
        min_value=0.0,
        value=float(transfer[5]),
        step=100.0,
        key=f"edit_amount_{transfer_group_id}"
    )

    edited_date = st.date_input(
        "Date",
        value=transfer_date,
        key=f"edit_date_{transfer_group_id}"
    )

    notes = st.text_input(
        "Note",
        value=transfer[6] or "",
        key=f"edit_note_{transfer_group_id}"
    )

    c1, c2 = st.columns(2)

    with c1:

        if st.button(
            "Save",
            use_container_width=True
        ):

            from_account_id = account_map[from_account]
            to_account_id = account_map[to_account]

            if not validate_transfer(
                from_account_id,
                to_account_id,
                amount
            ):

                st.stop()

            update_transfer(
                transfer_group_id,
                from_account_id,
                to_account_id,
                str(edited_date),
                amount,
                notes.strip()
            )

            st.session_state.edit_transfer_group_id = None

            st.rerun()

    with c2:

        if st.button(
            "Cancel",
            use_container_width=True
        ):

            st.session_state.edit_transfer_group_id = None

            st.rerun()


@st.dialog("Delete Transfer")
def delete_transfer_dialog(
    transfer_group_id
):

    st.warning(
        "Delete this transfer? Both sides of the money movement will be removed."
    )

    c1, c2 = st.columns(2)

    with c1:

        if st.button(
            "Cancel",
            use_container_width=True
        ):

            st.session_state.delete_transfer_group_id = None

            st.rerun()

    with c2:

        if st.button(
            "Delete",
            use_container_width=True
        ):

            delete_transfer(
                transfer_group_id
            )

            st.session_state.delete_transfer_group_id = None

            st.rerun()


def render_transfer_form(
    vault_id,
    accounts
):
    account_balances = get_account_balances(
        vault_id
    )

    account_map = {
        account[1]: account[0]
        for account in accounts
    }

    account_names = list(
        account_map.keys()
    )

    st.markdown(
        """
        <div class="mv-transfer-card">
            <div class="mv-transfer-card-title">
                <span class="mv-transfer-title-icon material-symbols-outlined">sync_alt</span>
                <span>New Transfer</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

    top = st.columns(
        [2.1, 0.32, 2.1, 2.2],
        vertical_alignment="top"
    )

    with top[0]:

        from_account = st.selectbox(
            "From Account",
            account_names,
            key="transfer_from_account"
        )

        from_balance = account_balances.get(
            account_map[from_account],
            0
        )

        st.markdown(
            f'<div class="mv-transfer-balance">Available Balance: <span>{format_money(from_balance)}</span></div>',
            unsafe_allow_html=True
        )

    with top[1]:

        st.markdown(
            '<div class="mv-transfer-arrow material-symbols-outlined">arrow_forward</div>',
            unsafe_allow_html=True
        )

    with top[2]:

        default_to_index = 1 if len(account_names) > 1 else 0

        to_account = st.selectbox(
            "To Account",
            account_names,
            index=default_to_index,
            key="transfer_to_account"
        )

        to_balance = account_balances.get(
            account_map[to_account],
            0
        )

        st.markdown(
            f'<div class="mv-transfer-balance">Available Balance: <span>{format_money(to_balance)}</span></div>',
            unsafe_allow_html=True
        )

    with top[3]:

        amount = st.number_input(
            "Amount",
            min_value=0.0,
            step=100.0,
            key="transfer_amount"
        )

    bottom = st.columns(
        [2.1, 2.65, 1.6],
        vertical_alignment="bottom"
    )

    with bottom[0]:

        transfer_date = st.date_input(
            "Date",
            value=date.today(),
            key="transfer_date"
        )

    with bottom[1]:

        notes = st.text_input(
            "Note (Optional)",
            placeholder="e.g., Emergency fund transfer",
            key="transfer_notes"
        )

    with bottom[2]:

        if st.button(
            "Transfer",
            use_container_width=True,
            key="submit_transfer"
        ):

            from_account_id = account_map[from_account]
            to_account_id = account_map[to_account]

            if not validate_transfer(
                from_account_id,
                to_account_id,
                amount
            ):

                st.stop()

            add_transfer(
                vault_id,
                from_account_id,
                to_account_id,
                str(transfer_date),
                amount,
                notes.strip()
            )

            st.success(
                "Transfer recorded."
            )

            st.rerun()


def render_transfer_table(
    vault_id,
    accounts
):

    account_map = {
        account[1]: account[0]
        for account in accounts
    }

    if "transfer_limit" not in st.session_state:
        st.session_state.transfer_limit = INITIAL_TRANSFER_LIMIT

    today = date.today()
    month_start = today.replace(day=1)

    header_col, export_col = st.columns(
        [5, 1],
        vertical_alignment="center"
    )

    with header_col:

        st.markdown(
            """
            <div class="mv-transfer-section-title">
                <span class="mv-transfer-title-icon material-symbols-outlined">history</span>
                <span>Recent Transfers</span>
            </div>
            """,
            unsafe_allow_html=True
        )

    filters = st.columns(
        [1.2, 1.2, 1.55, 0.8],
        vertical_alignment="bottom"
    )

    with filters[0]:

        date_from = st.date_input(
            "From Date",
            value=month_start,
            key="transfer_filter_from"
        )

    with filters[1]:

        date_to = st.date_input(
            "To Date",
            value=today,
            key="transfer_filter_to"
        )

    if date_from > date_to:
        st.warning(
            "From Date cannot be after To Date."
        )
        return

    with filters[2]:

        account_filter = st.selectbox(
            "Account",
            ["All Accounts"] + list(account_map.keys()),
            key="transfer_filter_account"
        )

    with filters[3]:

        if st.button(
            "Reset",
            key="transfer_filter_reset"
        ):

            st.session_state.transfer_limit = INITIAL_TRANSFER_LIMIT
            st.rerun()

    selected_account_id = (
        None
        if account_filter == "All Accounts"
        else account_map[account_filter]
    )

    transfers = get_transfers(
        vault_id,
        str(date_from),
        str(date_to),
        selected_account_id
    )

    with export_col:

        csv = b""

        if transfers:

            export_df = pd.DataFrame(
                transfers,
                columns=[
                    "Transfer ID",
                    "Date",
                    "From Account ID",
                    "From",
                    "To Account ID",
                    "To",
                    "Amount",
                    "Note"
                ]
            )

            csv = export_df[
                [
                    "Date",
                    "From",
                    "To",
                    "Amount",
                    "Note"
                ]
            ].to_csv(
                index=False
            ).encode("utf-8-sig")

            st.download_button(
                "Export",
                csv,
                "transfers.csv",
                "text/csv",
                use_container_width=True
            )

        else:

            st.download_button(
                "Export",
                csv,
                "transfers.csv",
                "text/csv",
                use_container_width=True,
                disabled=True
            )

    st.markdown(
        """
        <div class="mv-transfer-table-head">
            <div>Date</div>
            <div>From</div>
            <div></div>
            <div>To</div>
            <div>Amount</div>
            <div>Note</div>
            <div></div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if not transfers:

        st.info(
            "No transfers found."
        )

        return

    visible_transfers = transfers[
        :st.session_state.transfer_limit
    ]

    for transfer in visible_transfers:

        group_id = transfer[0]
        transfer_date = date.fromisoformat(
            transfer[1]
        ).strftime("%d %b %Y")
        from_name = transfer[3]
        to_name = transfer[5]
        amount = transfer[6]
        note = transfer[7] or ""

        row = st.columns(
            [1.05, 2.25, 0.4, 2.25, 1.2, 1.55, 0.35],
            vertical_alignment="center"
        )

        with row[0]:
            st.markdown(
                f'<div class="mv-transfer-date">{transfer_date}</div>',
                unsafe_allow_html=True
            )

        with row[1]:
            st.markdown(
                f"""
                <div class="mv-transfer-account">
                    <span class="mv-transfer-mini-badge">{account_badge(from_name)}</span>
                    <span>{from_name}</span>
                </div>
                """,
                unsafe_allow_html=True
            )

        with row[2]:
            st.markdown(
                '<div class="mv-transfer-row-arrow material-symbols-outlined">arrow_forward</div>',
                unsafe_allow_html=True
            )

        with row[3]:
            st.markdown(
                f"""
                <div class="mv-transfer-account">
                    <span class="mv-transfer-mini-badge">{account_badge(to_name)}</span>
                    <span>{to_name}</span>
                </div>
                """,
                unsafe_allow_html=True
            )

        with row[4]:
            st.markdown(
                f'<div class="mv-transfer-amount">{format_money(amount)}</div>',
                unsafe_allow_html=True
            )

        with row[5]:
            st.markdown(
                f'<div class="mv-transfer-note">{note}</div>',
                unsafe_allow_html=True
            )

        with row[6]:

            if hasattr(st, "popover"):

                with st.popover(
                    "⋮"
                ):

                    if st.button(
                        "Edit",
                        key=f"edit_transfer_{group_id}",
                        use_container_width=True
                    ):

                        st.session_state.edit_transfer_group_id = group_id
                        st.rerun()

                    if st.button(
                        "Delete",
                        key=f"delete_transfer_{group_id}",
                        use_container_width=True
                    ):

                        st.session_state.delete_transfer_group_id = group_id
                        st.rerun()

            elif st.button(
                "⋮",
                key=f"transfer_actions_{group_id}"
            ):

                st.session_state.edit_transfer_group_id = group_id
                st.rerun()

        st.markdown(
            '<div class="mv-transfer-row-divider"></div>',
            unsafe_allow_html=True
        )

    if len(transfers) > st.session_state.transfer_limit:

        if st.button(
            "Load more",
            key="load_more_transfers",
            use_container_width=True
        ):

            st.session_state.transfer_limit += 5
            st.rerun()


def show_transfers(vault_id):

    if "edit_transfer_group_id" not in st.session_state:
        st.session_state.edit_transfer_group_id = None

    if "delete_transfer_group_id" not in st.session_state:
        st.session_state.delete_transfer_group_id = None

    accounts = get_accounts(
        vault_id
    )

    if st.session_state.edit_transfer_group_id:
        edit_transfer_group_id = st.session_state.pop(
            "edit_transfer_group_id"
        )

        edit_transfer_dialog(
            edit_transfer_group_id,
            accounts
        )

    if st.session_state.delete_transfer_group_id:
        delete_transfer_group_id = st.session_state.pop(
            "delete_transfer_group_id"
        )

        delete_transfer_dialog(
            delete_transfer_group_id
        )

    title_col, button_col = st.columns(
        [5, 1],
        vertical_alignment="center"
    )

    with title_col:

        st.markdown(
            """
            <div class="mv-transfer-page-title">
                <h2>Transfers</h2>
                <p>Move money between your accounts</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with button_col:

        st.button(
            "+ New Transfer",
            use_container_width=True,
            disabled=True
        )

    if len(accounts) < 2:

        st.warning(
            "At least two accounts are required to transfer money."
        )

        return

    with st.container(border=True):

        render_transfer_form(
            vault_id,
            accounts
        )

    with st.container(border=True):

        render_transfer_table(
            vault_id,
            accounts
        )

    st.markdown(
        """
        <div class="mv-transfer-info">
            <span class="material-symbols-outlined">info</span>
            <div>
                <strong>Transfers between your accounts are not counted as expenses.</strong>
                <p>They only move money and don't affect your spending.</p>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )

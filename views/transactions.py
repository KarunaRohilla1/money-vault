import streamlit as st
import pandas as pd
from datetime import datetime

from db.accounts import get_accounts
from db.categories import get_category_dropdown
from db.transactions import (
    get_filtered_transactions
)

from components.transaction_timeline_card import (
    transaction_timeline_card
)

from components.add_transaction_modal import (
    add_transaction_dialog
)

from components.edit_transaction_modal import (
    edit_transaction_dialog
)

from components.delete_transaction_modal import (
    delete_transaction_dialog
)

from dateutil.relativedelta import relativedelta

INITIAL_LIMIT = 3


def collapse_transfer_rows(transactions):
    collapsed = []
    pending_transfers = {}

    for tx in transactions:
        tx_type = tx[5]
        transfer_group_id = (
            tx[7]
            if len(tx) > 7
            else None
        )

        if (
            tx_type not in ("Transfer In", "Transfer Out")
            or not transfer_group_id
        ):
            collapsed.append(tx)
            continue

        group = pending_transfers.setdefault(
            transfer_group_id,
            []
        )
        group.append(tx)

        if len(group) < 2:
            continue

        out_tx = next(
            (
                item for item in group
                if item[5] == "Transfer Out"
            ),
            None
        )
        in_tx = next(
            (
                item for item in group
                if item[5] == "Transfer In"
            ),
            None
        )

        if not out_tx or not in_tx:
            continue

        collapsed.append(
            (
                out_tx[0],
                out_tx[1],
                f"{out_tx[2]} \u2192 {in_tx[2]}",
                "\U0001f501 Transfer",
                out_tx[4],
                "Transfer",
                out_tx[6] or in_tx[6],
                transfer_group_id
            )
        )

        pending_transfers.pop(
            transfer_group_id,
            None
        )

    for group in pending_transfers.values():
        collapsed.extend(group)

    return collapsed

def show_transactions(vault_id):

    if "edit_transaction_id" not in st.session_state:
        st.session_state.edit_transaction_id = None
    
    if st.session_state.edit_transaction_id:
        edit_transaction_id = st.session_state.pop(
            "edit_transaction_id"
        )
        edit_transaction_dialog(
                vault_id,
                edit_transaction_id
            )
    
    if "delete_transaction_id" not in st.session_state:
        st.session_state.delete_transaction_id = None

    if st.session_state.delete_transaction_id:
        delete_transaction_id = st.session_state.pop(
            "delete_transaction_id"
        )
        delete_transaction_dialog(
        delete_transaction_id
    )
    

    # ==================================
    # Header
    # ==================================

    col1, col2 = st.columns([8, 2])

    with col1:

        st.markdown(
            """
            <div class="dashboard-header">
                <h2>💸 Transactions</h2>
                <p>Track every rupee</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with col2:

        if st.button(
            "Add Transaction",
            use_container_width=True
        ):
            st.session_state.show_transaction_dialog = True

    if st.session_state.get(
        "show_transaction_dialog",
        False
    ):
        st.session_state.show_transaction_dialog = False
        add_transaction_dialog(
            vault_id
        )

    # ==================================
    # Data
    # ==================================

    accounts = get_accounts(
        vault_id
    )

    categories = get_category_dropdown(
        vault_id
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

    # ==================================
    # Filters
    # ==================================

    search_text = st.text_input(
        "",
        placeholder="🔍 Search transactions..."
    )

    col1, col2, col3, col4 = st.columns(4)

    with col1:

        date_range_filter = st.selectbox(
        "Date Range",
        [
            "This Month",
            "Last Month",
            "Last 3 Months",
            "This Year",
            "All Time",
            "Custom"
        ]
    )
        custom_start = None
        custom_end = None

    with col2:

        account_filter = st.selectbox(
            "Account",
            ["All"]
            + [
                account[1]
                for account in accounts
            ]
        )

    with col3:

        category_filter = st.selectbox(
            "Category",
            ["All"]
            + [
                cat[2]
                for cat in categories
            ]
        )

    with col4:

        sort_option = st.selectbox(
            "Sort",
            [
                "Newest",
                "Oldest",
                "Amount High",
                "Amount Low"
            ]
        )
    
    current_filter_state = (
        date_range_filter,
        account_filter,
        category_filter,
        search_text
    )

    if "last_filter_state" not in st.session_state:
        st.session_state.last_filter_state = current_filter_state

    if st.session_state.last_filter_state != current_filter_state:
        st.session_state.transaction_limit = INITIAL_LIMIT
        st.session_state.last_filter_state = current_filter_state

    # ==================================
    # Date Range Logic
    # ==================================

    today = datetime.today()

    month_filter = None

    if date_range_filter == "This Month":

        month_filter = today.strftime(
            "%Y-%m"
        )

    elif date_range_filter == "Last Month":

        month_filter = (
            today - relativedelta(months=1)
        ).strftime(
            "%Y-%m"
        )

    elif date_range_filter == "Last 3 Months":

        month_filter = "LAST_3_MONTHS"
    elif date_range_filter == "This Year":
        month_filter = "THIS_YEAR"
    if date_range_filter == "Custom":

        c1, c2 = st.columns(2)

        with c1:
            custom_start = st.date_input(
                "From", value=today.date()
            )

        with c2:
            custom_end = st.date_input(
                "To", value=today.date()
            )

    # ==================================
    # Transactions
    # ==================================

    transactions = get_filtered_transactions(
        vault_id=vault_id,
        month=(
            None
            if month_filter == "All"
            else month_filter
        ),
        category=(
            None
            if category_filter == "All"
            else category_filter
        ),
        account=(
            None
            if account_filter == "All"
            else account_filter
        ),
        search=search_text,
        sort_by=sort_option
    )

    if not transactions:

        st.info(
            "No transactions found."
        )

        return

    if (
            date_range_filter == "Custom"
            and custom_start
            and custom_end
        ):

            transactions = [
                tx
                for tx in transactions
                if (
                    custom_start
                    <= datetime.strptime(
                        tx[1],
                        "%Y-%m-%d"
                    ).date()
                    <= custom_end
                )
            ]

#############################################################################################3

    transactions = collapse_transfer_rows(
        transactions
    )

    if not transactions:
        st.info(
            "No transactions found."
        )
        return

    summary_col1, summary_col2 = st.columns([8,2])

    with summary_col1:

        st.caption(
            f"{len(transactions)} transaction(s) found"
        )

    with summary_col2:

        if transactions:

            export_df = pd.DataFrame(
                [
                    tx[:7]
                    for tx in transactions
                ],
                columns=[
                    "ID",
                    "Date",
                    "Account",
                    "Category",
                    "Amount",
                    "Type",
                    "Notes"
                ]
            )

            csv = export_df.to_csv(
                index=False
            ).encode("utf-8-sig")

            st.download_button(
                "⬇ Export CSV",
                csv,
                "transactions.csv",
                "text/csv",
                use_container_width=True
            )
    # ==================================
    # Timeline
    # ==================================

    grouped_transactions = {}

    if "transaction_limit" not in st.session_state:
        st.session_state.transaction_limit = INITIAL_LIMIT

    all_transactions = transactions

    visible_transactions = all_transactions[
        :st.session_state.transaction_limit
    ]

    for tx in visible_transactions:

        tx_date = tx[1]

        if tx_date not in grouped_transactions:
            grouped_transactions[tx_date] = []

        grouped_transactions[tx_date].append(tx)

    for tx_date, date_transactions in grouped_transactions.items():
        line_height = max(
    120,
    len(date_transactions) * 85
)
        display_date = datetime.strptime(
            tx_date,
            "%Y-%m-%d"
        ).strftime(
            "%d %b %Y"
        )

        left_col, right_col = st.columns(
            [1.4, 8]
        )
        
        with left_col:

            st.markdown(
                f"""
                <div class="timeline-column">
                    <div class="timeline-dot"></div>
                    <div class="timeline-date-column">{display_date}</div>
                    <div class="timeline-line" style="height:{line_height}px;"></div>
                </div>""",
                unsafe_allow_html=True
            )

        with right_col:

            for tx in date_transactions:
                tx_id = tx[0]
                account = tx[2]
                category = tx[3]
                amount = tx[4]
                tx_type = tx[5]
                notes = tx[6]

                icon = "💰"
                category_name = category

                if category:

                    parts = category.split(
                        " ",
                        1
                    )

                    if len(parts) == 2:

                        icon = parts[0]
                        category_name = parts[1]

                transaction_timeline_card(
                    transaction_id=tx_id,
                    icon=icon,
                    category=category_name,
                    account=account,
                    amount=amount,
                    notes=notes or "",
                    transaction_type=tx_type
                )

        st.markdown("<br>", unsafe_allow_html=True)

    if len(all_transactions) > st.session_state.transaction_limit:
        if st.button(
            "Load More",
            use_container_width=True,
            key="load_more_transactions"
        ):

            st.session_state.transaction_limit += 10

            st.rerun()



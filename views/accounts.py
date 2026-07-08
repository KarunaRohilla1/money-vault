import streamlit as st

from db.accounts import (
    ACCOUNT_TYPES,
    account_exists,
    account_has_transactions,
    add_account,
    archive_account,
    get_account_by_id,
    get_accounts_with_balances,
    set_primary_account,
    update_account
)

@st.dialog("Add Account")
def add_account_dialog(vault_id):

    with st.form("add_account_form"):

        name = st.text_input(
            "Account Name"
        )

        account_type = st.selectbox(
            "Account Type",
            ACCOUNT_TYPES
        )

        opening_balance = st.number_input(
            "Opening Balance",
            step=0.01,
            value=None,
            placeholder="Enter Amount",
            format="%.2f"
        )

        is_primary = st.checkbox(
            "Set as primary account"
        )

        left, right = st.columns(2)

        with left:
            submitted = st.form_submit_button(
                "Add Account",
                use_container_width=True
            )

        with right:
            cancelled = st.form_submit_button(
                "Cancel",
                use_container_width=True
            )

        if cancelled:
            st.rerun()

        if submitted:
            name = name.strip()
            if not name:
                st.error(
                    "Account name is required."
                )
            elif opening_balance is None:
                st.error("Opening balance cannot be empty.")
            elif account_type != "Credit Card" and opening_balance < 0:
                st.error(
                    "Opening balance cannot be negative."
                )
            elif account_exists(
                vault_id,
                name
            ):
                st.error(
                    "An account with this name already exists."
                )
            else:
                add_account(
                    vault_id,
                    name,
                    account_type,
                    opening_balance,
                    is_primary
                )
                st.success(
                    "Account created"
                )

                st.rerun()

@st.dialog("Edit Account")
def edit_account_dialog(account, vault_id):

    with st.form(
        f"edit_account_{account[0]}"
    ):

        name = st.text_input(
            "Account Name",
            value=account[1]
        )

        account_type = st.selectbox(
            "Account Type",
            ACCOUNT_TYPES,
            index=ACCOUNT_TYPES.index(
                account[2]
            )
        )

        opening_balance = st.number_input(
            "Opening Balance",
            value=float(account[3]),
            step=0.01,
            placeholder="Enter Amount",
            format="%.2f"
        )

        is_primary = st.checkbox(
            "Set as primary account",
            value=bool(account[4])
        )

        left, right = st.columns(2)

        with left:
            submitted = st.form_submit_button(
                "Save Changes",
                use_container_width=True
            )

        with right:
            cancelled = st.form_submit_button(
                "Cancel",
                use_container_width=True
            )

        if cancelled:
            st.rerun()

        if submitted:
            name = name.strip()
            if not name:
                st.error(
                    "Account name is required."
                )
            elif opening_balance is None:
                st.error("Opening balance cannot be empty.")
            elif account_type != "Credit Card" and opening_balance < 0:
                st.error(
                    "Opening balance cannot be negative."
                )
            elif account_exists(
                vault_id,
                name,
                account[0]
            ):
                st.error("Account already exists.")
            else:
                update_account(
                    account[0],
                    name,
                    account_type,
                    opening_balance,
                    is_primary
                )

                st.success(
                    "Account updated"
                )

                st.rerun()

@st.dialog("Delete Account")
def delete_account_dialog(account_id):

    if account_has_transactions(
        account_id
    ):
        st.warning(
            "This account has financial history. It will be marked inactive and kept in reports and existing transactions."
        )
    else:
        st.warning(
            "Are you sure you want to archive this account?"
        )

    col1, col2 = st.columns(2)

    with col1:

        if st.button(
            "Archive Account",
            use_container_width=True
        ):

            archive_account(
                account_id
            )

            st.success(
                "Account archived"
            )

            st.rerun()

    with col2:

        if st.button(
            "Cancel",
            use_container_width=True
        ):
            st.rerun()

def show_accounts(vault_id):

    # ==================================
    # Header
    # ==================================

    accounts = get_accounts_with_balances(vault_id)

    header_col, button_col = st.columns([8, 2])

    with header_col:

        st.markdown(
            """
            <div class="dashboard-header">
                <h2>🏦 Accounts</h2>
                <p>Manage all your financial accounts</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with button_col:

        st.write("")  # small vertical spacing

        if st.button(
            "Add Account",
            use_container_width=True
        ):
            add_account_dialog(vault_id)

    # ==================================
    # Summary
    # ==================================

    total_accounts = 0
    credit_cards = 0

    assets = 0
    liabilities = 0

    for account in accounts:

        balance = account[5]
        account_type = account[2]

        if account_type == "Credit Card":

            credit_cards += 1

            if balance < 0:

                liabilities += abs(balance)

        else:

            total_accounts += 1

            assets += balance

    net_worth = assets - liabilities

    st.markdown(f"""
        <div class="mv-assets-hero">
            <div class="mv-assets-left">
                <div class="mv-assets-label">NET WORTH</div>
                <div class="mv-assets-value">₹{net_worth:,.0f}</div>
                <div class="mv-networth-breakdown">Assets: ₹{assets:,.0f} • Liabilities: ₹{liabilities:,.0f}</div>
            </div>
            <div class="mv-assets-divider"></div>
            <div class="mv-assets-stat">
                <div class="mv-assets-stat-top">
                    <span class="mv-assets-icon">wallet</span>
                    <span class="mv-assets-stat-number">{total_accounts}</span>
                </div>
                <div class="mv-assets-stat-label">Accounts</div>
            </div>
            <div class="mv-assets-divider"></div>
                <div class="mv-assets-stat">
                    <div class="mv-assets-stat-top">
                    <span class="mv-assets-icon">credit_card</span>
                    <span class="mv-assets-stat-number">{credit_cards}</span>
                    </div>
                <div class="mv-assets-stat-label">Credit Cards</div>
            </div>
        </div>""",
unsafe_allow_html=True
)

    # ==================================
    # Accounts List
    # ==================================

    st.divider()
    if not accounts:

        st.info(
            "No accounts yet."
        )

    else:
        for account in accounts:

            account_id = account[0]
            name = account[1]
            account_type = account[2]
            is_primary = bool(account[4])

            balance = account[5]

            initials = "".join(
                [w[0] for w in name.split()[:2]]
            ).upper()

            if account_type == "Credit Card":
                balance_label = "Due Amount"
                balance_color = "#F87171"
            else:
                balance_label = "Available Balance"
                balance_color = "#4ADE80"


            c1, c2, c3, c4 = st.columns([0.75, 5.25, 3, 1.5], vertical_alignment="center")
            with c1:
                st.markdown(
                        f"""
                        <div class="mv-account-avatar">{initials}</div>""",
                        unsafe_allow_html=True
                    )

            with c2:

                st.markdown(
                        f"""
                        <div class="mv-account-name">{name}</div>
                        <div class="mv-account-type">{account_type}{' • Primary' if is_primary else ''}</div>
                        """,
                        unsafe_allow_html=True
                    )

            with c3:

                st.markdown(
                        f"""
                        <div style="text-align:right;">
                            <div class="mv-account-amount">₹{abs(balance):,.0f}</div>
                            <div
                                class="mv-account-label"
                                style="color:{balance_color};"
                            >{balance_label}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )

            with c4:

                b1, b2, b3 = st.columns(3)
                with b1:

                    if st.button(
                            "★" if is_primary else "☆",
                            key=f"primary_{account_id}",
                            use_container_width=True,
                            disabled=is_primary
                        ):
                            set_primary_account(account_id)
                            st.rerun()

                with b2:

                    if st.button(
                            "✎",
                            key=f"edit_{account_id}",
                            use_container_width=True
                        ):
                            account = get_account_by_id(account_id)
                            edit_account_dialog(account, vault_id)
                            

                with b3:
                    if st.button(
                            "🗑",
                            key=f"archive_{account_id}",
                            use_container_width=True
                        ):
                            delete_account_dialog(account_id)
                            

from datetime import datetime

import streamlit as st

from db.transactions import get_transactions


def show_recent_transactions(vault_id, limit=5):
    transactions = get_transactions(vault_id)

    st.markdown(
        """
        <div class="section-title">
            Recent Activity
        </div>
        """,
        unsafe_allow_html=True
    )

    rows_html = ""
    visible_count = 0

    for tx in transactions:
        transaction_type = tx[5]

        if transaction_type in (
            "Transfer In",
            "Transfer Out"
        ):
            continue

        amount = tx[4]

        if amount == 0:
            continue

        date = datetime.strptime(
            tx[1],
            "%Y-%m-%d"
        ).strftime("%d %b")

        category = tx[3]
        parts = category.split(" ", 1)

        if len(parts) > 1:
            icon = parts[0]
            category_name = parts[1]
        else:
            icon = "\U0001f4b0"
            category_name = category

        amount_class = (
            "transaction-income"
            if transaction_type == "Income"
            else "transaction-expense"
        )

        rows_html += f"""
        <div class="activity-row">
            <div class="activity-left">
                <div class="activity-icon">{icon}</div>
                <div>
                    <div class="activity-category">{category_name}</div>
                    <div class="activity-date">{date}</div>
                </div>
            </div>
            <div class="{amount_class}">\u20b9{amount:,.0f}</div>
        </div>
        """

        visible_count += 1

        if visible_count >= limit:
            break

    if not rows_html:
        rows_html = """
        <div class="empty-state">
            No transactions yet.
        </div>
        """

    st.markdown(
        f"""
        <div class="widget-card">
            {rows_html}
        </div>
        """,
        unsafe_allow_html=True
    )

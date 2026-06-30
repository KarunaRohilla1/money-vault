import streamlit as st

from components.cards import (
    get_spending_message,
    hero_card,
    metric_card
)
from components.header import dashboard_header
from components.spending_insights import show_spending_insights
from components.transaction_cards import show_recent_transactions
from db.dashboard import (
    get_dashboard_summary,
    get_onboarding_status
)


def show_onboarding(status):

    progress = 0

    if status["has_accounts"]:
        progress += 1

    if status["has_income_templates"]:
        progress += 1

    if status["has_commitments"]:
        progress += 1

    percent = int(
        progress / 3 * 100
    )

    progress_width = max(
        percent,
        3
    )

    def checklist_item(
        *,
        complete,
        tone,
        icon,
        title,
        body
    ):

        check_class = (
            "is-complete"
            if complete
            else ""
        )

        check_icon = (
            "check"
            if complete
            else ""
        )

        return (
            f'<div class="mv-onboarding-item {tone}">'
            f'<div class="mv-onboarding-icon material-symbols-outlined">{icon}</div>'
            f'<div class="mv-onboarding-check {check_class}">'
            f'<span class="material-symbols-outlined">{check_icon}</span>'
            f'</div>'
            f'<div class="mv-onboarding-copy">'
            f'<div class="mv-onboarding-item-title">{title}</div>'
            f'<div class="mv-onboarding-item-body">{body}</div>'
            f'</div>'
            f'</div>'
        )

    items_html = "".join([
        checklist_item(
            complete=status["has_accounts"],
            tone="purple",
            icon="account_balance",
            title="Add your first Account",
            body="Go to Accounts and create at least one account."
        ),
        checklist_item(
            complete=status["has_income_templates"],
            tone="green",
            icon="account_balance_wallet",
            title="Add Recurring Income",
            body=(
                "Go to Planning -> Recurring Income "
                "and add your income sources."
            )
        ),
        checklist_item(
            complete=status["has_commitments"],
            tone="amber",
            icon="calendar_month",
            title="Add Recurring Commitment",
            body=(
                "Go to Planning -> Recurring Commitments "
                "and add your monthly commitments."
            )
        )
    ])

    markup = (
        '<div class="mv-onboarding-shell">'
        '<div class="mv-onboarding-welcome">'
        '<span class="mv-onboarding-wave">👋</span>'
        '<span class="mv-onboarding-welcome-title">Welcome to Money Vault!</span>'
        '<span class="mv-onboarding-welcome-copy">'
        "Let's complete your initial setup to get the most out of your financial management."
        '</span>'
        '</div>'
        '<div class="mv-onboarding-head">'
        '<div>'
        '<div class="mv-onboarding-title">Getting Started</div>'
        '<div class="mv-onboarding-subtitle">'
        'Complete the steps below to unlock the full experience.'
        '</div>'
        '</div>'
        f'<div class="mv-onboarding-pill">{percent}% Complete</div>'
        '</div>'
        '<div class="mv-onboarding-progress">'
        f'<div style="width:{progress_width}%"></div>'
        '</div>'
        '<div class="mv-onboarding-section-title">Setup Checklist</div>'
        f'<div class="mv-onboarding-list">{items_html}</div>'
        '<div class="mv-onboarding-complete">'
        '<div class="mv-onboarding-trophy material-symbols-outlined">emoji_events</div>'
        '<div>'
        f'<div class="mv-onboarding-complete-title">{progress}/3 Completed</div>'
        '<div class="mv-onboarding-complete-copy">'
        'Complete these steps to unlock all features of Money Vault.'
        '</div>'
        '</div>'
        '<div class="mv-onboarding-confetti material-symbols-outlined">celebration</div>'
        '</div>'
        '</div>'
    )

    st.markdown(
        markup,
        unsafe_allow_html=True
    )


def show_dashboard(vault_id):

    dashboard_header()

    status = get_onboarding_status(
        vault_id
    )

    if not status["is_complete"]:

        show_onboarding(
            status
        )

        return

    dashboard = get_dashboard_summary(
        vault_id
    )
    dashboard["income"] = dashboard[
        "primary_account_balance"
    ]

    left_col, right_col = st.columns(
        [1.7, 1.5],
        gap="medium"
    )

    with left_col:

        hero_card(
            "SAFE TO SPEND",
            f"₹{dashboard['safe_to_spend']:,.0f}",
            message=get_spending_message(
                dashboard["safe_to_spend"]
            )
        )

    with right_col:

        row1_col1, row1_col2 = st.columns(2)

        with row1_col1:

            metric_card(
                dashboard["primary_account_name"],
                f"₹{dashboard['income']:,.0f}",
                "salary"
            )

        with row1_col2:

            metric_card(
                "Remaining Commitments",
                f"₹{dashboard['remaining_commitments']:,.0f}",
                "expense"
            )

        row2_col1, row2_col2 = st.columns(2)

        with row2_col1:

            metric_card(
                "Credit Card Due",
                f"₹{dashboard['credit_card_due']:,.0f}",
                "credit"
            )

        with row2_col2:

            metric_card(
                "Expenses This Month",
                f"₹{dashboard['expenses']:,.0f}",
                "expense"
            )

    st.markdown(
        "<br>",
        unsafe_allow_html=True
    )

    activity_col, insights_col = st.columns(
        2,
        gap="large"
    )

    with activity_col:

        show_recent_transactions(
            vault_id
        )

    with insights_col:

        show_spending_insights(
            vault_id
        )

    st.markdown(
        "<br>",
        unsafe_allow_html=True
    )

    with st.expander(
        "How is Safe To Spend calculated?"
    ):
        st.markdown(
            f"""
            ### Available Cash

            ₹{dashboard['available_cash']:,.0f}

            ### Remaining Commitments

            ₹{dashboard['remaining_commitments']:,.0f}

            ### Expenses This Month

            ₹{dashboard['expenses']:,.0f}

            Expenses are already reflected in available cash.

            ### Credit Card Due

            ₹{dashboard['credit_card_due']:,.0f}

            ---

            ## Safe To Spend

            ₹{dashboard['safe_to_spend']:,.0f}
            """
        )

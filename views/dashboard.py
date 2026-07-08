from datetime import date
from html import escape

import streamlit as st

from components.cards import (
    get_spending_message,
    hero_card,
    metric_card
)
from components.add_shared_expense_modal import add_shared_expense_dialog
from components.header import dashboard_header
from components.spending_insights import show_spending_insights
from components.transaction_cards import show_recent_transactions
from db.dashboard import (
    get_dashboard_page_data,
)
from db.accounts import get_accounts_with_balances
from db.financial_cycles import get_current_cycle
from db.shared_bills import get_shared_bills_summary
from db.shared_expenses import (
    get_shared_category_spending,
    get_shared_recent_activity,
    get_shared_vault_summary,
    settle_outstanding_settlement
)
from db.vaults import get_vault_by_id


def format_money(amount):
    return f"₹{amount:,.0f}"


def account_option_label(account):
    return (
        f"{account[1]} · {account[2]} · "
        f"{format_money(account[5])}"
    )


@st.dialog("Mark Settlement")
def mark_settlement_dialog(settlement_items):
    if not settlement_items:
        st.info("No outstanding settlement to mark.")
        if st.button("Close", use_container_width=True):
            st.rerun()
        return

    settlement_labels = [
        (
            f"{item['from_name']} pays {item['to_name']} "
            f"{format_money(item['amount'])} · {item['shared_vault_name']}"
        )
        for item in settlement_items
    ]
    selected_label = st.selectbox(
        "Settlement",
        settlement_labels
    )
    settlement = settlement_items[
        settlement_labels.index(selected_label)
    ]

    from_accounts = get_accounts_with_balances(
        settlement["from_vault_id"]
    )
    to_accounts = get_accounts_with_balances(
        settlement["to_vault_id"]
    )

    if not from_accounts:
        st.error(
            f"{settlement['from_name']} has no active account to pay from."
        )
        return

    if not to_accounts:
        st.error(
            f"{settlement['to_name']} has no active account to receive into."
        )
        return

    from_account_labels = [
        account_option_label(account)
        for account in from_accounts
    ]
    to_account_labels = [
        account_option_label(account)
        for account in to_accounts
    ]

    from_account_label = st.selectbox(
        "Paying Account",
        from_account_labels
    )
    to_account_label = st.selectbox(
        "Receiving Account",
        to_account_labels
    )
    amount = st.number_input(
        "Amount",
        min_value=0.01,
        max_value=float(settlement["amount"]),
        value=float(settlement["amount"]),
        step=0.01,
        format="%.2f"
    )
    settlement_date = st.date_input(
        "Date",
        value=date.today()
    )

    left, right = st.columns(2)
    with left:
        if st.button(
            "Mark Settled",
            type="primary",
            use_container_width=True
        ):
            from_account = from_accounts[
                from_account_labels.index(from_account_label)
            ]
            to_account = to_accounts[
                to_account_labels.index(to_account_label)
            ]

            try:
                settle_outstanding_settlement(
                    settlement["shared_vault_id"],
                    settlement["from_vault_id"],
                    from_account[0],
                    settlement["to_vault_id"],
                    to_account[0],
                    amount,
                    settlement_date.isoformat()
                )
                st.success("Settlement recorded.")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with right:
        if st.button(
            "Cancel",
            use_container_width=True
        ):
            st.rerun()


def settlement_card(settlement_summary):
    direction = settlement_summary["direction"]
    amount = settlement_summary["amount"]
    tone = "neutral"

    if direction == "receivable":
        tone = "positive"
    elif direction == "payable":
        tone = "negative"

    if direction == "settled":
        label = "No pending shared settlement."
        amount_text = "All Settled"
    else:
        label = settlement_summary["label"]
        amount_text = format_money(amount)

    st.markdown(
        f"""
        <div class="mv-settlement-card {tone}">
            <div class="mv-settlement-icon">🤝</div>
            <div>
                <div class="mv-settlement-title">Outstanding Settlements</div>
                <div class="mv-settlement-label">{label}</div>
            </div>
            <div class="mv-settlement-amount">{amount_text}</div>
        </div>
        """,
        unsafe_allow_html=True
    )

    if direction != "settled":
        if st.button(
            "Mark Settled",
            use_container_width=True,
            key="mark_dashboard_settlement"
        ):
            mark_settlement_dialog(
                settlement_summary["items"]
            )

def material_icon(name):
    return (
        '<span class="material-symbols-outlined">'
        f'{escape(name)}'
        '</span>'
    )


def shared_stat_card(icon, title, value, subtitle="", tone="purple"):
    return (
        f'<div class="mv-shared-stat {tone}">'
        f'<div class="mv-shared-stat-icon material-symbols-outlined">{icon}</div>'
        '<div class="mv-shared-stat-copy">'
        f'<div class="mv-shared-stat-title">{escape(title)}</div>'
        f'<div class="mv-shared-stat-value">{escape(str(value))}</div>'
        f'<div class="mv-shared-stat-subtitle">{escape(subtitle)}</div>'
        '</div>'
        '</div>'
    )


def shared_spending_panel(participants, total_spending):
    colors = [
        "#7c3aed",
        "#38bdf8",
        "#60a5fa",
        "#fbbf24",
        "#f472b6",
        "#8b5cf6"
    ]
    segments = []
    cursor = 0

    if total_spending:
        for index, participant in enumerate(participants[:6]):
            amount = float(participant["paid"] or 0)
            percent = amount / total_spending * 100
            next_cursor = cursor + percent
            color = colors[index % len(colors)]
            segments.append(
                f"{color} {cursor:.2f}% {next_cursor:.2f}%"
            )
            cursor = next_cursor

    gradient = (
        ", ".join(segments)
        if segments
        else "#263044 0% 100%"
    )

    if participants:
        participant_html = "".join(
            (
                '<div class="mv-shared-category-row">'
                '<div class="mv-shared-category-name">'
                f'<span style="background:{colors[index % len(colors)]}"></span>'
                f'{escape(str(participant["name"]))}'
                '</div>'
                f'<div>{format_money(participant["paid"] or 0)}</div>'
                f'<div>{((float(participant["paid"] or 0) / total_spending * 100) if total_spending else 0):.0f}%</div>'
                '</div>'
            )
            for index, participant in enumerate(participants[:6])
        )
    else:
        participant_html = (
            '<div class="mv-shared-empty">No shared expenses yet.</div>'
        )

    return (
        '<section class="mv-shared-panel mv-shared-spend-panel">'
        '<div class="mv-shared-panel-head">'
        '<div class="mv-shared-panel-title">Shared Spending This Cycle</div>'
        '</div>'
        '<div class="mv-shared-spend-body">'
        '<div class="mv-shared-donut" '
        f'style="background: conic-gradient({gradient});">'
        '<div class="mv-shared-donut-center">'
        f'<strong>{format_money(total_spending)}</strong>'
        '<span>Total</span>'
        '</div>'
        '</div>'
        f'<div class="mv-shared-category-list">{participant_html}</div>'
        '</div>'
        '</section>'
    )


def render_shared_spending_panel(participants, total_spending):
    try:
        import plotly.graph_objects as go
    except ImportError:
        st.markdown(
            shared_spending_panel(
                participants,
                total_spending
            ),
            unsafe_allow_html=True
        )
        return

    colors = [
        "#7c3aed",
        "#38bdf8",
        "#60a5fa",
        "#fbbf24",
        "#f472b6",
        "#8b5cf6"
    ]

    with st.container():
        st.markdown(
            """
            <section class="mv-shared-panel mv-shared-spend-panel mv-shared-streamlit-panel">
                <div class="mv-shared-panel-head">
                    <div class="mv-shared-panel-title">Shared Spending This Cycle</div>
                </div>
            """,
            unsafe_allow_html=True
        )

        if not participants or not total_spending:
            st.markdown(
                '<div class="mv-shared-empty tall">No shared expenses yet.</div></section>',
                unsafe_allow_html=True
            )
            return

        chart_col, list_col = st.columns(
            [0.85, 1.15],
            gap="large"
        )

        labels = [
            participant["name"]
            for participant in participants[:6]
        ]
        values = [
            float(participant["paid"] or 0)
            for participant in participants[:6]
        ]
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=labels,
                    values=values,
                    hole=0.58,
                    marker=dict(
                        colors=colors[:len(labels)],
                        line=dict(
                            color="#111827",
                            width=1
                        )
                    ),
                    hovertemplate="%{label}<br>%{value:,.0f}<br>%{percent}<extra></extra>",
                    textinfo="none"
                )
            ]
        )
        fig.update_layout(
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font_color="#f8fafc",
            margin=dict(l=0, r=0, t=0, b=0),
            showlegend=False,
            height=250,
            annotations=[
                dict(
                    text=f"{format_money(total_spending)}<br><span style='font-size:13px'>Total</span>",
                    x=0.5,
                    y=0.5,
                    font=dict(
                        size=20,
                        color="#f8fafc"
                    ),
                    showarrow=False
                )
            ]
        )

        with chart_col:
            st.plotly_chart(
                fig,
                use_container_width=True,
                config={"displayModeBar": False}
            )

        with list_col:
            category_html = "".join(
                (
                    '<div class="mv-shared-category-row">'
                    '<div class="mv-shared-category-name">'
                    f'<span style="background:{colors[index % len(colors)]}"></span>'
                    f'{escape(str(participant["name"]))}'
                    '</div>'
                    f'<div>{format_money(participant["paid"] or 0)}</div>'
                    f'<div>{((float(participant["paid"] or 0) / total_spending * 100) if total_spending else 0):.0f}%</div>'
                    '</div>'
                )
                for index, participant in enumerate(participants[:6])
            )
            st.markdown(
                f'<div class="mv-shared-category-list">{category_html}</div>',
                unsafe_allow_html=True
            )

        st.markdown(
            '</section>',
            unsafe_allow_html=True
        )


def shared_bills_panel(bills_summary):
    if bills_summary["upcoming_bills"]:
        rows = "".join(
            (
                '<div class="mv-shared-bill-row purple">'
                f'<div class="mv-shared-bill-icon material-symbols-outlined">{escape(str(bill["icon"]))}</div>'
                '<div class="mv-shared-bill-main">'
                f'<strong>{escape(bill["name"])}</strong>'
                f'<span>Due in {bill["days_until_due"]} days</span>'
                '</div>'
                f'<div class="mv-shared-bill-amount">{format_money(bill["amount"])}</div>'
                '<div class="mv-shared-bill-badge">Due Soon</div>'
                '</div>'
            )
            for bill in bills_summary["upcoming_bills"]
        )
    else:
        rows = (
            '<div class="mv-shared-empty tall">'
            'No shared bills due soon.'
            '</div>'
        )

    return (
        '<section class="mv-shared-panel">'
        '<div class="mv-shared-panel-head">'
        '<div class="mv-shared-panel-title">Upcoming Bills</div>'
        '</div>'
        f'<div class="mv-shared-bill-list">{rows}</div>'
        '</section>'
    )


def shared_activity_panel(activity_rows):
    if activity_rows:
        cards = "".join(
            (
                '<div class="mv-shared-activity-card mv-shared-activity-list-item">'
                f'<div class="mv-shared-activity-icon">{escape(str(row[5]))}</div>'
                '<div>'
                f'<div class="mv-shared-activity-title">{escape(str(row[3]))} paid</div>'
                f'<div class="mv-shared-activity-subtitle">{escape(str(row[4]))}</div>'
                f'<div class="mv-shared-activity-amount">{format_money(row[2] or 0)}</div>'
                '</div>'
                '<span class="mv-shared-chip">Shared</span>'
                '</div>'
            )
            for row in activity_rows[:4]
        )
    else:
        cards = (
            '<div class="mv-shared-empty">'
            'No shared activity yet.'
            '</div>'
        )

    return (
        '<section class="mv-shared-panel mv-shared-recent">'
        '<div class="mv-shared-panel-head">'
        '<div class="mv-shared-panel-title">Recent Activity</div>'
        '</div>'
        f'<div class="mv-shared-activity-list">{cards}</div>'
        '</section>'
    )


def shared_participant_panel(summary):
    rows = "".join(
        (
            '<div class="mv-shared-settlement-row">'
            '<div>'
            f'<strong>{escape(participant["name"])}</strong>'
            f'<span>Paid {format_money(participant["paid"])} &bull; Share {format_money(participant["share"])}</span>'
            '</div>'
            f'<strong>{format_money(abs(participant["balance"]))}</strong>'
            '</div>'
        )
        for participant in summary["participants"]
    )
    return (
        '<section class="mv-shared-panel">'
        '<div class="mv-shared-panel-head">'
        '<div class="mv-shared-panel-title">Participants</div>'
        '</div>'
        f'{rows or "<div class=\"mv-shared-empty\">No participants yet.</div>"}'
        '</section>'
    )


def show_shared_dashboard(vault_id, vault_name):
    cycle = get_current_cycle(
        vault_id
    )
    start_date, end_date = cycle.start_iso, cycle.end_iso
    summary = get_shared_vault_summary(
        vault_id,
        start_date,
        end_date
    )
    category_rows = get_shared_category_spending(
        vault_id,
        start_date,
        end_date
    )
    activity_rows = get_shared_recent_activity(
        vault_id,
        start_date,
        end_date
    )
    bills_summary = get_shared_bills_summary(
        vault_id
    )

    if st.session_state.get("show_shared_expense_dialog"):
        st.session_state.show_shared_expense_dialog = False
        add_shared_expense_dialog(
            vault_id
        )

    settlement_subtitle = "All settled"
    if summary["settlements"]:
        first_settlement = summary["settlements"][0]
        settlement_subtitle = (
            f'{first_settlement["from"]} owes '
            f'{first_settlement["to"]}'
        )

    top_category_name = "No expenses yet"
    top_category_value = format_money(0)
    if category_rows:
        top_category_name = category_rows[0][1]
        top_category_value = format_money(category_rows[0][2] or 0)
    due_soon_text = (
        f'{bills_summary["due_soon_count"]} bills due soon'
    )

    header_col, action_col = st.columns(
        [1, 0.34],
        vertical_alignment="center"
    )
    with header_col:
        st.markdown(
            (
                '<div class="mv-shared-topbar">'
                '<div>'
                '<h1>Shared Vault</h1>'
                "<p>Here's how your household is doing</p>"
                '</div>'
                '</div>'
            ),
            unsafe_allow_html=True
        )

    with action_col:
        if st.button(
            "+ Add Shared Expense",
            use_container_width=True,
            key="shared_dashboard_add_expense"
        ):
            st.session_state.show_shared_expense_dialog = True
            st.rerun()

    top_html = (
        '<div class="mv-shared-stats">'
        f'{shared_stat_card("business_center", "Shared Spend", format_money(summary["total_shared_spending"]), "This Cycle", "purple")}'
        f'{shared_stat_card("sync_alt", "Outstanding Balance", format_money(summary["outstanding_settlement"]), settlement_subtitle, "blue")}'
        f'{shared_stat_card("calendar_month", "Upcoming Bills", format_money(bills_summary["total_due_soon"]), due_soon_text, "orange")}'
        f'{shared_stat_card("donut_large", "Top Category", top_category_value, top_category_name, "green")}'
        '</div>'
    )

    st.markdown(
        top_html,
        unsafe_allow_html=True
    )

    spend_col, bills_col = st.columns(
        [1.02, 1],
        gap="large"
    )
    with spend_col:
        render_shared_spending_panel(
            summary["participants"],
            summary["total_shared_spending"]
        )
    with bills_col:
        st.markdown(
            shared_bills_panel(bills_summary),
            unsafe_allow_html=True
        )

    activity_col, participant_col = st.columns(
        [1.2, 0.8],
        gap="large"
    )
    with activity_col:
        st.markdown(
            shared_activity_panel(activity_rows),
            unsafe_allow_html=True
        )
    with participant_col:
        st.markdown(
            shared_participant_panel(summary),
            unsafe_allow_html=True
        )


def show_onboarding(status):

    progress = 0

    if status.get("has_vault_login"):
        progress += 1

    if status.get("has_cycle_setting"):
        progress += 1

    if status.get("has_savings_goal"):
        progress += 1

    if status["has_accounts"]:
        progress += 1

    percent = int(
        progress / 4 * 100
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
            complete=status.get("has_vault_login", False),
            tone="green",
            icon="password",
            title="Set Vault PIN",
            body="Your vault should have login credentials configured."
        ),
        checklist_item(
            complete=status.get("has_cycle_setting", False),
            tone="amber",
            icon="event_repeat",
            title="Set Financial Cycle",
            body="Go to Settings and choose your financial cycle start day."
        ),
        checklist_item(
            complete=status.get("has_savings_goal", False),
            tone="green",
            icon="savings",
            title="Set Monthly Savings Goal",
            body="Go to Settings and add the amount you want to save each cycle."
        ),
        checklist_item(
            complete=status["has_accounts"],
            tone="purple",
            icon="account_balance",
            title="Add your first Account",
            body="Go to Accounts and create at least one account."
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
        f'<div class="mv-onboarding-complete-title">{progress}/4 Completed</div>'
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

    vault = get_vault_by_id(
        vault_id
    )

    if vault and len(vault) > 4 and vault[4] == "Shared":
        show_shared_dashboard(
            vault_id,
            vault[1]
        )
        return

    dashboard_header()

    page_data = get_dashboard_page_data(
        vault_id
    )
    status = page_data["status"]

    if not status["is_complete"]:

        show_onboarding(
            status
        )

        return

    dashboard = page_data["summary"]

    if not status.get("has_income_templates"):
        st.info("Recurring income not configured.")

    if not status.get("has_commitments"):
        st.info("No commitments configured. Commitments are treated as zero.")

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
            ),
            variant="hero-card-horizontal"
        )
        settlement_card(
            dashboard["settlement_summary"]
        )

    with right_col:

        row1_col1, row1_col2 = st.columns(2)

        with row1_col1:

            metric_card(
                dashboard["primary_account_name"],
                f"₹{dashboard['primary_account_balance']:,.0f}",
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
                "Expenses This Cycle",
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
            vault_id,
            transactions=page_data["recent_activity"]
        )

    with insights_col:

        show_spending_insights(
            vault_id,
            category_data=page_data["category_spending"]
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
            Safe To Spend is the cash you can use after reserving money for
            known obligations and your savings target.

            **Formula**

            `Available Cash - You Owe - Remaining Commitments - Credit Card Due - Savings Goal`

            | Component | Amount | Meaning |
            |---|---:|---|
            | Available Cash | ₹{dashboard['available_cash']:,.0f} | Current spendable cash. Expenses already reduce this balance when recorded. |
            | You Owe | -₹{dashboard['settlement_summary']['payable']:,.0f} | Shared settlement money you still need to pay. |
            | Remaining Commitments | -₹{dashboard['remaining_commitments']:,.0f} | Bills/commitments still pending this cycle. |
            | Credit Card Due | -₹{dashboard['credit_card_due']:,.0f} | Current unpaid credit card balance. |
            | Savings Goal | -₹{dashboard['monthly_savings_goal']:,.0f} | Money reserved for savings. |

            **Safe To Spend = ₹{dashboard['safe_to_spend']:,.0f}**

            Outstanding settlements are tracked separately as
            ₹{dashboard['settlement_summary']['amount']:,.0f}.
            Money owed to you is not counted as spendable cash until it is
            actually settled into an account.

            Expenses this cycle are shown separately as ₹{dashboard['expenses']:,.0f}.
            They are not subtracted again here because they have already reduced
            your account balances.

            **Net Worth**
            
            Assets: ₹{dashboard['total_assets']:,.0f}  
            Liabilities: ₹{dashboard['total_liabilities']:,.0f}  
            Net Worth: ₹{dashboard['net_worth']:,.0f}
            """
        )

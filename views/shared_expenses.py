from datetime import date, datetime, timedelta
from html import escape

import pandas as pd
import streamlit as st
from dateutil.relativedelta import relativedelta

from components.add_shared_expense_modal import add_shared_expense_dialog
from components.edit_shared_expense_modal import show_edit_shared_expense_dialog
from components.responsive import mobile_label
from db.shared_expenses import get_shared_expenses_page_data
from db.financial_cycles import get_current_cycle
from views.dashboard import format_money

INITIAL_LIMIT = 6


def format_date(value):
    try:
        return date.fromisoformat(value).strftime("%d %b %Y")
    except ValueError:
        return value


def selected_dates(shared_vault_id, selected_range):
    today = datetime.today().date()

    if selected_range == "This Cycle":
        cycle = get_current_cycle(shared_vault_id)
        return cycle.start_date, cycle.end_date

    if selected_range == "Last Month":
        last_month = today - relativedelta(months=1)
        start = last_month.replace(day=1)
        if start.month == 12:
            end = date(start.year + 1, 1, 1) - timedelta(days=1)
        else:
            end = date(start.year, start.month + 1, 1) - timedelta(days=1)
        return start, end

    if selected_range == "Last 3 Months":
        return today - relativedelta(months=3), today

    if selected_range == "This Year":
        return date(today.year, 1, 1), date(today.year, 12, 31)

    if selected_range == "All Time":
        return date(1970, 1, 1), date(2999, 12, 31)

    cycle = get_current_cycle(shared_vault_id)
    return cycle.start_date, cycle.end_date


def summary_card(icon, title, value, subtitle, tone):
    return (
        f'<div class="mv-shared-expense-summary-item {tone}">'
        f'<div class="mv-shared-expense-summary-icon material-symbols-outlined">{icon}</div>'
        '<div>'
        f'<div class="mv-shared-expense-summary-title">{escape(title)}</div>'
        f'<div class="mv-shared-expense-summary-value">{escape(str(value))}</div>'
        f'<div class="mv-shared-expense-summary-subtitle">{escape(subtitle)}</div>'
        '</div>'
        '</div>'
    )


def expense_row(expense, current_name, other_label):
    merchant = expense["merchant"] or expense["category"]

    return (
        '<div class="mv-shared-expense-row">'
        '<div class="mv-shared-expense-main">'
        f'<div class="mv-shared-expense-icon">{escape(str(expense["category_icon"]))}</div>'
        '<div>'
        f'<div class="mv-shared-expense-title">{escape(expense["category"])}</div>'
        f'<div class="mv-shared-expense-meta">{format_date(expense["date"])} &bull; {escape(merchant)}</div>'
        '</div>'
        '</div>'
        f'<div class="mv-shared-expense-paidby mv-mobile-labeled" {mobile_label("Paid By")}>'
        '<div class="mv-shared-avatar">'
        f'{escape(expense["paid_by"][:1].upper())}'
        '</div>'
        f'<span>{escape(expense["paid_by"])}</span>'
        '</div>'
        f'<div class="mv-shared-expense-split mv-mobile-labeled" {mobile_label("Split")}>'
        f'<strong>{escape(expense["split_label"])}</strong>'
        f'<span>{escape(expense["allocation_method"])}</span>'
        '</div>'
        f'<div class="mv-shared-expense-share mv-mobile-labeled" {mobile_label(f"{current_name} Share")}>'
        f'<strong>{format_money(expense["my_share"])}</strong>'
        f'<span>{escape(current_name)} Share</span>'
        '</div>'
        f'<div class="mv-shared-expense-share mv-mobile-labeled" {mobile_label(f"{other_label} Share")}>'
        f'<strong>{format_money(expense["other_share"])}</strong>'
        f'<span>{escape(other_label)} Share</span>'
        '</div>'
        '</div>'
    )


def show_shared_expenses(shared_vault_id, vault_name):
    default_cycle = get_current_cycle(shared_vault_id)
    default_start, default_end = default_cycle.start_date, default_cycle.end_date
    limit_key = "shared_expenses_limit"
    filter_state_key = "shared_expenses_last_filter_state"

    if limit_key not in st.session_state:
        st.session_state[limit_key] = INITIAL_LIMIT

    header_col, action_col = st.columns(
        [8, 2],
        vertical_alignment="center"
    )

    with header_col:
        st.markdown(
            """
            <div class="mv-shared-expense-header">
                <h1>Shared Expenses</h1>
                <p>All expenses that belong to our household.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with action_col:
        if st.button(
            "Add Shared Expense",
            use_container_width=True,
            key="shared_expenses_add_button"
        ):
            st.session_state.show_shared_expense_dialog = True

    if st.session_state.get("show_shared_expense_dialog"):
        st.session_state.show_shared_expense_dialog = False
        add_shared_expense_dialog(
            shared_vault_id
        )

    initial_data = get_shared_expenses_page_data(
        shared_vault_id,
        default_start.isoformat(),
        default_end.isoformat()
    )
    category_options = {"All Categories": None}
    category_options.update({
        f"{row[2]} {row[1]}": row[0]
        for row in initial_data["categories"]
    })
    paid_by_options = {"All": None}
    paid_by_options.update({
        row[1]: row[0]
        for row in initial_data["participants"]
    })

    date_col, category_col, paid_col, clear_col = st.columns(
        [1.15, 1.15, 1.05, 1],
        vertical_alignment="bottom"
    )

    with date_col:
        selected_range = st.selectbox(
            "Date Range",
            [
                "This Cycle",
                "Last Month",
                "Last 3 Months",
                "This Year",
                "All Time",
                "Custom"
            ],
            key="shared_expenses_date_range"
        )

    with category_col:
        selected_category = st.selectbox(
            "Category",
            list(category_options.keys()),
            key="shared_expenses_category"
        )

    with paid_col:
        selected_paid_by = st.selectbox(
            "Paid By",
            list(paid_by_options.keys()),
            key="shared_expenses_paid_by"
        )

    with clear_col:
        if st.button(
            "Clear Filters",
            use_container_width=True,
            key="shared_expenses_clear_filters"
        ):
            st.session_state.shared_expenses_date_range = "This Cycle"
            st.session_state.shared_expenses_category = "All Categories"
            st.session_state.shared_expenses_paid_by = "All"
            st.session_state[limit_key] = INITIAL_LIMIT
            st.rerun()

    if selected_range == "Custom":
        custom_cols = st.columns(2)
        with custom_cols[0]:
            start_date = st.date_input(
                "From",
                value=date.today(),
                key="shared_expenses_custom_start"
            )
        with custom_cols[1]:
            end_date = st.date_input(
                "To",
                value=date.today(),
                key="shared_expenses_custom_end"
            )
    else:
        start_date, end_date = selected_dates(
            shared_vault_id,
            selected_range
        )

    current_filter_state = (
        selected_range,
        selected_category,
        selected_paid_by,
        start_date,
        end_date
    )
    if filter_state_key not in st.session_state:
        st.session_state[filter_state_key] = current_filter_state
    if st.session_state[filter_state_key] != current_filter_state:
        st.session_state[limit_key] = INITIAL_LIMIT
        st.session_state[filter_state_key] = current_filter_state

    selected_category_id = category_options[selected_category]
    selected_paid_by_id = paid_by_options[selected_paid_by]
    uses_default_data = (
        selected_range == "This Cycle"
        and selected_category_id is None
        and selected_paid_by_id is None
        and start_date == default_start
        and end_date == default_end
    )

    if uses_default_data:
        data = initial_data
    else:
        data = get_shared_expenses_page_data(
            shared_vault_id,
            start_date.isoformat(),
            end_date.isoformat(),
            category_id=selected_category_id,
            paid_by_vault_id=selected_paid_by_id
        )

    current_participant = data["current_participant"]
    current_name = (
        current_participant[1]
        if current_participant
        else "Member"
    )
    other_label = (
        data["other_participants"][0][1]
        if len(data["other_participants"]) == 1
        else "Other Members"
    )
    current_share_header = f"{current_name} Share"
    other_share_header = f"{other_label} Share"

    summary = data["summary"]
    total = summary["total_shared_spend"] or 1
    current_pct = summary["paid_by_current"] / total * 100
    other_pct = summary["paid_by_other"] / total * 100

    st.markdown(
        (
            '<div class="mv-shared-expense-summary">'
            f'{summary_card("business_center", "Total Shared Spend", format_money(summary["total_shared_spend"]), selected_range, "purple")}'
            f'{summary_card("group", "Total Transactions", summary["total_transactions"], selected_range, "blue")}'
            f'{summary_card("sync_alt", f"{current_name} Paid", format_money(summary["paid_by_current"]), f"{current_pct:.0f}% of total", "green")}'
            f'{summary_card("receipt_long", f"{other_label} Paid", format_money(summary["paid_by_other"]), f"{other_pct:.0f}% of total", "orange")}'
            '</div>'
        ),
        unsafe_allow_html=True
    )

    all_expenses = data["expenses"]
    visible_expenses = all_expenses[
        :st.session_state[limit_key]
    ]

    result_col, export_col = st.columns(
        [8, 2],
        vertical_alignment="center"
    )

    with result_col:
        st.caption(
            f"{len(all_expenses)} shared expense(s) found"
        )

    with export_col:
        if all_expenses:
            export_df = pd.DataFrame([
                {
                    "Date": expense["date"],
                    "Category": expense["category"],
                    "Merchant": expense["merchant"],
                    "Amount": expense["amount"],
                    "Paid By": expense["paid_by"],
                    "Split": expense["split_label"],
                    current_share_header: expense["my_share"],
                    other_share_header: expense["other_share"]
                }
                for expense in all_expenses
            ])
            csv = export_df.to_csv(
                index=False
            ).encode("utf-8-sig")

            st.download_button(
                "⬇ Export CSV",
                csv,
                "shared_expenses.csv",
                "text/csv",
                use_container_width=True
            )

    headers = (
        '<div class="mv-shared-expense-table-head">'
        '<div>Expense</div>'
        '<div>Paid By</div>'
        '<div>Split</div>'
        f'<div>{escape(current_share_header)}</div>'
        f'<div>{escape(other_share_header)}</div>'
        '</div>'
    )

    st.markdown(
        headers,
        unsafe_allow_html=True
    )

    if not visible_expenses:
        st.markdown(
            (
                '<div class="mv-shared-expense-list">'
                '<div class="mv-shared-empty tall">'
                'No shared expenses match these filters.'
                '</div>'
                '</div>'
            ),
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            '<div class="mv-shared-expense-list">',
            unsafe_allow_html=True
        )

        for expense in visible_expenses:
            row_col, action_col = st.columns(
                [20, 1],
                vertical_alignment="center"
            )

            with row_col:
                st.markdown(
                    expense_row(
                        expense,
                        current_name,
                        other_label
                    ),
                    unsafe_allow_html=True
                )

            with action_col:
                if st.button(
                    "→",
                    key=f"edit_shared_expense_{expense['id']}",
                    use_container_width=True
                ):
                    st.session_state.edit_shared_expense_id = expense["id"]

        st.markdown(
            '</div>',
            unsafe_allow_html=True
        )

    selected_expense_id = st.session_state.get(
        "edit_shared_expense_id"
    )

    if selected_expense_id:
        st.session_state.edit_shared_expense_id = None

        selected_expense = next(
            (
                expense
                for expense in all_expenses
                if expense["id"] == selected_expense_id
            ),
            None
        )

        if selected_expense:
            show_edit_shared_expense_dialog(
                shared_vault_id,
                selected_expense
            )

    st.markdown(
        f"""
        <div class="mv-shared-expense-footer">
            Showing {len(visible_expenses)} of {len(all_expenses)} shared expenses
        </div>
        """,
        unsafe_allow_html=True
    )

    if len(all_expenses) > st.session_state[limit_key]:
        if st.button(
            "Load More",
            use_container_width=True,
            key="load_more_shared_expenses"
        ):
            st.session_state[limit_key] += 10
            st.rerun()

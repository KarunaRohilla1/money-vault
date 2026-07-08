from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from db.cache import cache_data
from db.core import EXPENSE, INCOME, TRANSFER_OUT, get_connection
from db.financial_cycles import (
    add_months,
    build_cycle_navigation_options,
    get_current_cycle,
    format_cycle_range,
    get_cycle_for_date
)
from db.shared_expenses import (
    get_actual_category_spending,
    get_personal_spend_summary,
    get_settlement_summary,
    get_shared_vault_summary
)
from db.vaults import get_vault_by_id


REPORT_COLORS = [
    "#8B5CF6",
    "#7C3AED",
    "#2563EB",
    "#22C1C3",
    "#F59E0B",
    "#EC4899",
    "#60A5FA"
]

MATERIAL_REPORT_ICONS = {
    "calendar_month",
    "label"
}


def format_money(amount):
    return f"₹{float(amount or 0):,.0f}"


def is_shared_vault(vault_id):
    vault = get_vault_by_id(vault_id)
    return bool(vault and len(vault) > 4 and vault[4] == "Shared")


def get_selected_report_cycle(vault_id):
    current_cycle = get_current_cycle(vault_id)
    cycle_options = build_cycle_navigation_options(vault_id)

    if "reports_selected_cycle_start" not in st.session_state:
        st.session_state.reports_selected_cycle_start = (
            current_cycle.start_iso
        )

    cycle_keys = [
        option["key"]
        for option in cycle_options
    ]

    if st.session_state.reports_selected_cycle_start not in cycle_keys:
        st.session_state.reports_selected_cycle_start = (
            current_cycle.start_iso
        )

    selected_index = cycle_keys.index(
        st.session_state.reports_selected_cycle_start
    )
    selected_cycle = get_cycle_for_date(
        vault_id,
        st.session_state.reports_selected_cycle_start
    )

    return selected_cycle, cycle_options, cycle_keys, selected_index


def build_cycle_windows(vault_id, start_date, end_date):
    cycle = get_cycle_for_date(
        vault_id,
        start_date.isoformat()
    )
    windows = []

    while cycle.start_date <= end_date:
        windows.append((
            cycle.start_iso,
            cycle.end_iso,
            cycle.start_month,
            cycle.start_year
        ))
        cycle = get_cycle_for_date(
            vault_id,
            add_months(cycle.start_date, 1).isoformat()
        )

    return tuple(windows)


def report_period_context(vault_id, selected_cycle):
    return {
        "selected_cycle": selected_cycle,
        "start_date": selected_cycle.start_date,
        "end_date": selected_cycle.end_date,
        "cycle_windows": build_cycle_windows(
            vault_id,
            selected_cycle.start_date,
            selected_cycle.end_date
        )
    }


def cycle_status_filter(alias, cycle_windows):
    if not cycle_windows:
        return "1 = 0", ()

    conditions = []
    params = []
    for _start_iso, _end_iso, month, year in cycle_windows:
        conditions.append(f"({alias}.month = ? AND {alias}.year = ?)")
        params.extend([month, year])

    return " OR ".join(conditions), tuple(params)


@cache_data(ttl=60)
def get_actual_income_total(vault_id, start_date, end_date, cycle_windows):
    status_filter, status_params = cycle_status_filter("s", cycle_windows)
    conn = get_connection()
    try:
        row = conn.execute(
            f"""
            WITH manual_income AS (
                SELECT COALESCE(SUM(t.amount), 0) AS amount
                FROM transactions t
                WHERE t.vault_id = ?
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                AND NOT EXISTS (
                    SELECT 1
                    FROM income_status s
                    WHERE s.transaction_id = t.id
                )
            ),
            received_recurring_income AS (
                SELECT COALESCE(
                    SUM(COALESCE(s.actual_amount, i.amount)),
                    0
                ) AS amount
                FROM income_status s
                JOIN income_templates i
                    ON i.id = s.income_template_id
                WHERE i.vault_id = ?
                AND s.status = 'RECEIVED'
                AND ({status_filter})
            )
            SELECT manual_income.amount + received_recurring_income.amount
            FROM manual_income
            CROSS JOIN received_recurring_income
            """,
            (
                vault_id,
                INCOME,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                *status_params
            )
        ).fetchone()
        return float(row[0] or 0)
    finally:
        conn.close()


@cache_data(ttl=60)
def get_unlinked_paid_commitments_total(vault_id, cycle_windows):
    status_filter, status_params = cycle_status_filter("s", cycle_windows)
    conn = get_connection()
    try:
        row = conn.execute(
            f"""
            SELECT COALESCE(SUM(COALESCE(s.actual_amount, c.amount)), 0)
            FROM obligation_status s
            JOIN commitments c
                ON c.id = s.commitment_id
            LEFT JOIN transactions t
                ON t.id = s.transaction_id
                AND t.is_deleted = 0
            WHERE c.vault_id = ?
            AND s.status = 'PAID'
            AND t.id IS NULL
            AND ({status_filter})
            """,
            (
                vault_id,
                *status_params
            )
        ).fetchone()
        return float(row[0] or 0)
    finally:
        conn.close()


@cache_data(ttl=60)
def get_investment_total(vault_id, start_date, end_date):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(t.amount), 0)
            FROM transactions t
            LEFT JOIN categories c
                ON c.id = t.category_id
            WHERE t.vault_id = ?
            AND t.is_deleted = 0
            AND t.transaction_type = ?
            AND t.date::date BETWEEN ?::date AND ?::date
            AND (
                LOWER(COALESCE(c.name, '')) IN ('investment', 'savings')
                OR LOWER(COALESCE(c.parent_category, '')) = 'financial'
            )
            """,
            (
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat()
            )
        ).fetchone()
        return float(row[0] or 0)
    finally:
        conn.close()


@cache_data(ttl=60)
def get_shared_expenses_received_total(vault_id, start_date, end_date):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(ts.share_amount), 0)
            FROM transaction_shares ts
            JOIN transactions t
                ON t.id = ts.transaction_id
            WHERE ts.participant_vault_id = ?
            AND t.vault_id != ?
            AND COALESCE(t.beneficiary_vault_id, t.vault_id) != t.vault_id
            AND t.is_deleted = 0
            AND t.transaction_type = ?
            AND t.date::date BETWEEN ?::date AND ?::date
            """,
            (
                vault_id,
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat()
            )
        ).fetchone()
        return float(row[0] or 0)
    finally:
        conn.close()


def get_personal_report_money(vault_id, start_date, end_date, cycle_windows):
    income = get_actual_income_total(
        vault_id,
        start_date,
        end_date,
        cycle_windows
    )
    spend_summary = get_personal_spend_summary(
        vault_id,
        start_date.isoformat(),
        end_date.isoformat()
    )
    unlinked_commitments = get_unlinked_paid_commitments_total(
        vault_id,
        cycle_windows
    )
    cash_outflow = (
        spend_summary["personal_spending"]
        + spend_summary["shared_paid"]
        + unlinked_commitments
    )
    net_personal_cost = (
        spend_summary["personal_spending"]
        + spend_summary["own_shared_share"]
        + unlinked_commitments
    )
    settlement_summary = get_settlement_summary(
        vault_id,
        start_date.isoformat(),
        end_date.isoformat()
    )

    return {
        "income": income,
        "cash_outflow": cash_outflow,
        "net_personal_cost": net_personal_cost,
        "spent": net_personal_cost,
        "saved": max(income - net_personal_cost, 0),
        "investments": get_investment_total(
            vault_id,
            start_date,
            end_date
        ),
        "settlements": settlement_summary["net"],
        "outstanding_receivables": settlement_summary["receivable"],
        "outstanding_payables": settlement_summary["payable"],
        "net_outstanding": settlement_summary["net"],
        "settlements_completed": (
            spend_summary.get("settlement_received", 0)
            + spend_summary.get("settlement_paid", 0)
        ),
        "settlements_pending": settlement_summary["amount"],
        "shared_expenses_paid": spend_summary["shared_paid"],
        "shared_expenses_received": get_shared_expenses_received_total(
            vault_id,
            start_date,
            end_date
        ),
        "net_cash_flow": income - cash_outflow
    }


@cache_data(ttl=60)
def get_report_summary(vault_id, start_date, end_date, cycle_windows):
    if is_shared_vault(vault_id):
        shared_summary = get_shared_vault_summary(
            vault_id,
            start_date.isoformat(),
            end_date.isoformat()
        )
        conn = get_connection()
        try:
            summary_row = conn.execute(
                """
                WITH shared_expenses AS (
                    SELECT
                        t.id,
                        t.amount,
                        COALESCE(NULLIF(t.notes, ''), c.name, 'Expense') AS name,
                        COALESCE(c.emoji || ' ' || c.name, 'Uncategorized') AS category_name,
                        c.id AS category_id,
                        t.vault_id AS payer_vault_id
                    FROM transactions t
                    LEFT JOIN categories c
                        ON t.category_id = c.id
                    WHERE t.beneficiary_vault_id = ?
                    AND t.is_deleted = 0
                    AND t.transaction_type = ?
                    AND t.date::date BETWEEN ?::date AND ?::date
                ),
                largest_expense AS (
                    SELECT name, amount
                    FROM shared_expenses
                    ORDER BY amount DESC
                    LIMIT 1
                ),
                most_used_category AS (
                    SELECT category_name, COUNT(*) AS count
                    FROM shared_expenses
                    GROUP BY category_id, category_name
                    ORDER BY COUNT(*) DESC, COALESCE(SUM(amount), 0) DESC
                    LIMIT 1
                ),
                most_used_account AS (
                    SELECT v.name, COUNT(*) AS count
                    FROM shared_expenses se
                    JOIN vaults v
                        ON v.id = se.payer_vault_id
                    GROUP BY v.id, v.name
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                )
                SELECT
                    (SELECT COUNT(*) FROM shared_expenses),
                    largest_expense.name,
                    largest_expense.amount,
                    most_used_category.category_name,
                    most_used_category.count,
                    most_used_account.name,
                    most_used_account.count
                FROM largest_expense
                FULL JOIN most_used_category
                    ON TRUE
                FULL JOIN most_used_account
                    ON TRUE
                """,
                (
                    vault_id,
                    EXPENSE,
                    start_date.isoformat(),
                    end_date.isoformat()
                )
            ).fetchone()
        finally:
            conn.close()

        spent = shared_summary["total_shared_spending"]
        return {
            "income": 0,
            "cash_outflow": spent,
            "net_personal_cost": 0,
            "household_spending": spent,
            "spent": spent,
            "saved": 0,
            "investments": 0,
            "settlements": shared_summary["outstanding_settlement"],
            "outstanding_receivables": 0,
            "outstanding_payables": 0,
            "net_outstanding": 0,
            "settlements_completed": 0,
            "settlements_pending": shared_summary["outstanding_settlement"],
            "shared_expenses_paid": spent,
            "shared_expenses_received": 0,
            "net_cash_flow": -spent,
            "transactions": summary_row[0] if summary_row else 0,
            "transfers": 0,
            "largest_expense": (
                (summary_row[1], summary_row[2])
                if summary_row and summary_row[1] is not None
                else None
            ),
            "most_used_category": (
                (summary_row[3], summary_row[4])
                if summary_row and summary_row[3] is not None
                else None
            ),
            "most_used_account": (
                (summary_row[5], summary_row[6])
                if summary_row and summary_row[5] is not None
                else None
            )
        }

    conn = get_connection()
    try:
        summary_row = conn.execute(
            """
            WITH transaction_count AS (
                SELECT COUNT(*) AS count
                FROM transactions
                WHERE vault_id = ?
                AND is_deleted = 0
                AND date::date BETWEEN ?::date AND ?::date
            ),
            transfers AS (
                SELECT COUNT(DISTINCT transfer_group_id) AS count
                FROM transactions
                WHERE vault_id = ?
                AND is_deleted = 0
                AND transfer_group_id IS NOT NULL
                AND transaction_type = ?
                AND date::date BETWEEN ?::date AND ?::date
            ),
            largest_expense AS (
                SELECT
                    COALESCE(NULLIF(t.notes, ''), c.name, 'Expense') AS name,
                    t.amount
                FROM transactions t
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE t.vault_id = ?
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                ORDER BY t.amount DESC
                LIMIT 1
            ),
            most_used_category AS (
                SELECT
                    COALESCE(c.emoji || ' ' || c.name, 'Uncategorized') AS name,
                    COUNT(*) AS count
                FROM transactions t
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE t.vault_id = ?
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                GROUP BY c.id, c.name, c.emoji
                ORDER BY COUNT(*) DESC, COALESCE(SUM(t.amount), 0) DESC
                LIMIT 1
            ),
            most_used_account AS (
                SELECT
                    a.name,
                    COUNT(*) AS count
                FROM transactions t
                JOIN accounts a
                    ON t.account_id = a.id
                WHERE t.vault_id = ?
                AND t.is_deleted = 0
                AND t.transaction_type IN (?, ?)
                AND t.date::date BETWEEN ?::date AND ?::date
                GROUP BY a.id, a.name
                ORDER BY COUNT(*) DESC
                LIMIT 1
            )
            SELECT
                transaction_count.count,
                transfers.count,
                largest_expense.name,
                largest_expense.amount,
                most_used_category.name,
                most_used_category.count,
                most_used_account.name,
                most_used_account.count
            FROM transaction_count
            CROSS JOIN transfers
            LEFT JOIN largest_expense
                ON TRUE
            LEFT JOIN most_used_category
                ON TRUE
            LEFT JOIN most_used_account
                ON TRUE
            """,
            (
                vault_id,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                TRANSFER_OUT,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                INCOME,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat()
            )
        ).fetchone()
    finally:
        conn.close()

    money = get_personal_report_money(
        vault_id,
        start_date,
        end_date,
        cycle_windows
    )

    return {
        **money,
        "transactions": summary_row[0] if summary_row else 0,
        "transfers": summary_row[1] if summary_row else 0,
        "largest_expense": (
            (summary_row[2], summary_row[3])
            if summary_row and summary_row[2] is not None
            else None
        ),
        "most_used_category": (
            (summary_row[4], summary_row[5])
            if summary_row and summary_row[4] is not None
            else None
        ),
        "most_used_account": (
            (summary_row[6], summary_row[7])
            if summary_row and summary_row[6] is not None
            else None
        )
    }


@cache_data(ttl=60)
def get_category_breakdown(vault_id, start_date, end_date):
    conn = get_connection()
    try:
        vault = conn.execute(
            """
            SELECT vault_type
            FROM vaults
            WHERE id = ?
            """,
            (vault_id,)
        ).fetchone()

        if vault and vault[0] == "Shared":
            return conn.execute(
                """
                SELECT
                    COALESCE(MIN(c.emoji), 'label'),
                    COALESCE(c.parent_category, c.name, 'Uncategorized'),
                    COALESCE(SUM(t.amount), 0)
                FROM transactions t
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE t.beneficiary_vault_id = ?
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                GROUP BY COALESCE(c.parent_category, c.name, 'Uncategorized')
                ORDER BY SUM(t.amount) DESC
                """,
                (
                    vault_id,
                    EXPENSE,
                    start_date.isoformat(),
                    end_date.isoformat()
                )
            ).fetchall()
    finally:
        conn.close()

    return get_actual_category_spending(
        vault_id,
        start_date.isoformat(),
        end_date.isoformat()
    )


@cache_data(ttl=60)
def get_cash_outflow_category_breakdown(vault_id, start_date, end_date):
    if is_shared_vault(vault_id):
        return get_category_breakdown(
            vault_id,
            start_date,
            end_date
        )

    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT
                COALESCE(c.emoji, 'label') AS icon,
                COALESCE(c.name, 'Uncategorized') AS name,
                COALESCE(SUM(t.amount), 0) AS amount
            FROM transactions t
            LEFT JOIN categories c
                ON t.category_id = c.id
            WHERE t.vault_id = ?
            AND t.is_deleted = 0
            AND t.transaction_type = ?
            AND t.date::date BETWEEN ?::date AND ?::date
            AND COALESCE(t.notes, '') NOT LIKE 'Shared settlement:%'
            GROUP BY c.id, c.name, c.emoji
            HAVING COALESCE(SUM(t.amount), 0) > 0
            ORDER BY SUM(t.amount) DESC
            """,
            (
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat()
            )
        ).fetchall()
    finally:
        conn.close()


@cache_data(ttl=60)
def get_net_personal_category_breakdown(vault_id, start_date, end_date):
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            WITH personal_categories AS (
                SELECT
                    COALESCE(c.emoji, 'label') AS icon,
                    COALESCE(c.name, 'Uncategorized') AS name,
                    COALESCE(SUM(t.amount), 0) AS amount
                FROM transactions t
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE t.vault_id = ?
                AND COALESCE(t.beneficiary_vault_id, t.vault_id) = t.vault_id
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                GROUP BY c.id, c.name, c.emoji
            ),
            shared_categories AS (
                SELECT
                    COALESCE(c.emoji, 'label') AS icon,
                    COALESCE(c.name, 'Uncategorized') AS name,
                    COALESCE(SUM(ts.share_amount), 0) AS amount
                FROM transaction_shares ts
                JOIN transactions t
                    ON t.id = ts.transaction_id
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE ts.participant_vault_id = ?
                AND COALESCE(t.beneficiary_vault_id, t.vault_id) != t.vault_id
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                GROUP BY c.id, c.name, c.emoji
            )
            SELECT icon, name, SUM(amount) AS amount
            FROM (
                SELECT * FROM personal_categories
                UNION ALL
                SELECT * FROM shared_categories
            ) rows
            GROUP BY icon, name
            HAVING SUM(amount) > 0
            ORDER BY SUM(amount) DESC
            """,
            (
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat()
            )
        ).fetchall()

        return rows
    finally:
        conn.close()


@cache_data(ttl=60)
def get_monthly_trend(vault_id, end_date):
    data = []
    anchor_cycle = get_cycle_for_date(
        vault_id,
        end_date.isoformat()
    )
    shared = is_shared_vault(vault_id)

    for offset in range(5, -1, -1):
        cycle_start = add_months(
            anchor_cycle.start_date,
            -offset
        )
        cycle = get_cycle_for_date(
            vault_id,
            cycle_start.isoformat()
        )
        if shared:
            shared_summary = get_shared_vault_summary(
                vault_id,
                cycle.start_iso,
                cycle.end_iso
            )
            income = 0
            cash_outflow = shared_summary["total_shared_spending"]
            net_personal_cost = 0
            household_spending = shared_summary["total_shared_spending"]
            savings = 0
        else:
            money = get_personal_report_money(
                vault_id,
                cycle.start_date,
                cycle.end_date,
                (
                    (
                        cycle.start_iso,
                        cycle.end_iso,
                        cycle.start_month,
                        cycle.start_year
                    ),
                )
            )
            income = money["income"]
            cash_outflow = money["cash_outflow"]
            net_personal_cost = money["net_personal_cost"]
            household_spending = 0
            savings = money["saved"]
        data.append({
            "Cycle": format_cycle_range(
                cycle.start_date,
                cycle.end_date
            ),
            "Cash Outflow": cash_outflow,
            "Net Personal Cost": net_personal_cost,
            "Household Spending": household_spending,
            "Income": income,
            "Savings": savings
        })

    return data


def render_report_card(icon, title, value, caption, tone, key=None):
    key_attr = f" data-report-card='{key}'" if key else ""
    st.markdown(
        f"""
        <div class="mv-report-card"{key_attr}>
            <div class="mv-report-card-icon {tone} material-symbols-outlined">{icon}</div>
            <div>
                <div class="mv-report-card-title">{title}</div>
                <div class="mv-report-card-value">{value}</div>
                <div class="mv-report-card-caption">{caption}</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True
    )


def render_overview(summary, shared=False):
    if shared:
        cards = [
            (
                "home",
                "Household Spending",
                summary["household_spending"],
                "Total shared vault spend",
                "purple",
                "household"
            ),
            (
                "receipt_long",
                "Transactions",
                summary["transactions"],
                "Shared expenses this cycle",
                "green",
                "transactions"
            ),
            (
                "category",
                "Top Category",
                summary["most_used_category"][0]
                if summary["most_used_category"]
                else "None",
                "Highest activity category",
                "purple",
                "top-category"
            )
        ]
    else:
        outstanding_label = (
            "Owed to you"
            if summary["net_outstanding"] > 0
            else "You owe"
            if summary["net_outstanding"] < 0
            else "All settled"
        )
        cards = [
            (
                "business_center",
                "Income",
                summary["income"],
                "Money received this cycle",
                "purple",
                "income"
            ),
            (
                "arrow_outward",
                "Cash Outflow",
                summary["cash_outflow"],
                "Cash that left accounts",
                "red",
                "cash-outflow"
            ),
            (
                "receipt_long",
                "Net Personal Cost",
                summary["net_personal_cost"],
                "Your true expense burden",
                "purple",
                "net-cost"
            ),
            (
                "handshake",
                "Outstanding Settlements",
                abs(summary["net_outstanding"]),
                outstanding_label,
                "red"
                if summary["net_outstanding"] < 0
                else "green",
                "settlements"
            ),
            (
                "savings",
                "Savings",
                summary["saved"],
                "Income - net cost",
                "green",
                "savings"
            )
        ]

    columns = st.columns(len(cards))
    for column, (icon, title, value, caption, tone, key) in zip(
        columns,
        cards
    ):
        with column:
            display_value = (
                format_money(value)
                if isinstance(value, (int, float))
                else value
            )
            render_report_card(
                icon,
                title,
                display_value,
                caption,
                tone,
                key=key
            )


def render_shared_insights(summary, shared=False):
    if shared:
        return

    st.markdown(
        """
        <div class="mv-report-section">
            <h3>Shared Insights</h3>
            <p>Shared expense ownership and settlement status</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    insight_rows = [
        ("Total Shared Expenses Paid", summary["shared_expenses_paid"]),
        ("Total Shared Expenses Received", summary["shared_expenses_received"]),
        ("Outstanding Receivables", summary["outstanding_receivables"]),
        ("Outstanding Payables", summary["outstanding_payables"]),
        ("Settlements Completed", summary["settlements_completed"]),
        ("Settlements Pending", summary["settlements_pending"])
    ]
    columns = st.columns(3)
    for index, (label, value) in enumerate(insight_rows):
        with columns[index % 3]:
            st.markdown(
                f"""
                <div class="mv-report-insight">
                    <span>{label}</span>
                    <strong>{format_money(value)}</strong>
                </div>
                """,
                unsafe_allow_html=True
            )


def render_monthly_review(period_label, summary):
    largest = summary["largest_expense"]
    category = summary["most_used_category"]
    account = summary["most_used_account"]
    largest_text = (
        f"{largest[0]}<br>{format_money(largest[1])}"
        if largest
        else "None"
    )
    rows = [
        ("calendar_month", "Period", period_label),
        ("receipt_long", "Total Transactions", summary["transactions"]),
        ("sync_alt", "Transfers", summary["transfers"]),
        ("shopping_bag", "Largest Expense", largest_text),
        ("restaurant", "Most Used Category", category[0] if category else "None"),
        ("credit_card", "Most Used Account", account[0] if account else "None")
    ]
    left, right = st.columns([1.1, 1], gap="medium")
    with left:
        st.markdown(
            "".join(
                f"""
                <div class="mv-report-review-row">
                    <span class="material-symbols-outlined">{icon}</span>
                    <div>{label}</div>
                    <strong>{value}</strong>
                </div>
                """
                for icon, label, value in rows
            ),
            unsafe_allow_html=True
        )
    with right:
        st.markdown(
            f"""
            <div class="mv-report-review-summary">
                <div class="mv-report-review-title">Summary</div>
                <div><span>Income</span><strong>{format_money(summary['income'])}</strong></div>
                <div><span>Spent</span><strong>{format_money(summary['spent'])}</strong></div>
                <div><span>Saved</span><strong>{format_money(summary['saved'])}</strong></div>
                <div><span>Investments</span><strong>{format_money(summary['investments'])}</strong></div>
                <div><span>Settlements</span><strong>{format_money(summary['settlements'])}</strong></div>
                <div><span>Net Cash Flow</span><strong>{format_money(summary['net_cash_flow'])}</strong></div>
            </div>
            """,
            unsafe_allow_html=True
        )


def render_category_breakdown(rows):
    if not rows:
        st.info("No category spending for this period.")
        return
    total = sum(row[2] for row in rows)
    chart_df = pd.DataFrame(
        [
            {
                "Category": row[1],
                "Amount": row[2]
            }
            for row in rows
        ]
    )
    chart_col, legend_col = st.columns([1.05, 1.25], gap="large")
    with chart_col:
        fig = px.pie(
            chart_df,
            names="Category",
            values="Amount",
            hole=0.58,
            color_discrete_sequence=REPORT_COLORS
        )
        fig.update_traces(
            textinfo="percent",
            marker=dict(
                line=dict(color="rgba(255,255,255,0.08)", width=2)
            )
        )
        fig.update_layout(
            height=360,
            showlegend=False,
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            margin=dict(l=0, r=0, t=0, b=0),
            annotations=[
                dict(
                    text=f"<b>{format_money(total)}</b><br>Total Spent",
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(size=22, color="#F8FAFC")
                )
            ]
        )
        st.plotly_chart(
            fig,
            use_container_width=True,
            config={"displayModeBar": False}
        )
    with legend_col:
        for index, row in enumerate(rows):
            percent = round(row[2] / total * 100) if total else 0
            color = REPORT_COLORS[index % len(REPORT_COLORS)]
            icon_class = (
                "material-symbols-outlined"
                if row[0] in MATERIAL_REPORT_ICONS
                else ""
            )
            st.markdown(
                f"""
                <div class="mv-report-category-row">
                    <i style="background:{color}"></i>
                    <div>
                        <span class="mv-report-category-icon {icon_class}">{row[0]}</span>
                        {row[1]}
                    </div>
                    <strong>{format_money(row[2])}</strong>
                    <em>{percent}%</em>
                </div>
                """,
                unsafe_allow_html=True
            )


def render_category_chart_panel(title, subtitle, rows):
    st.markdown(
        f"""
        <div class="mv-report-chart-title">{title}</div>
        <div class="mv-report-chart-subtitle">{subtitle}</div>
        """,
        unsafe_allow_html=True
    )
    if not rows:
        st.info("No category spending for this cycle.")
        return

    total = sum(float(row[2] or 0) for row in rows)
    chart_df = pd.DataFrame(
        [
            {
                "Category": row[1],
                "Amount": float(row[2] or 0)
            }
            for row in rows
        ]
    )
    fig = px.pie(
        chart_df,
        names="Category",
        values="Amount",
        hole=0.58,
        color_discrete_sequence=REPORT_COLORS
    )
    fig.update_traces(
        textinfo="percent",
        hovertemplate=(
            "%{label}<br>"
            "Amount: ₹%{value:,.0f}<br>"
            "%{percent}<extra></extra>"
        ),
        marker=dict(
            line=dict(color="rgba(255,255,255,0.08)", width=2)
        )
    )
    fig.update_layout(
        height=300,
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=0, r=0, t=0, b=0),
        annotations=[
            dict(
                text=f"<b>{format_money(total)}</b><br>Total",
                x=0.5,
                y=0.5,
                showarrow=False,
                font=dict(size=18, color="#F8FAFC")
            )
        ]
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False}
    )

    for index, row in enumerate(rows[:5]):
        percent = round(float(row[2] or 0) / total * 100) if total else 0
        color = REPORT_COLORS[index % len(REPORT_COLORS)]
        icon_class = (
            "material-symbols-outlined"
            if row[0] in MATERIAL_REPORT_ICONS
            else ""
        )
        st.markdown(
            f"""
            <div class="mv-report-category-row compact">
                <i style="background:{color}"></i>
                <div>
                    <span class="mv-report-category-icon {icon_class}">{row[0]}</span>
                    {row[1]}
                </div>
                <strong>{format_money(row[2])}</strong>
                <em>{percent}%</em>
            </div>
            """,
            unsafe_allow_html=True
        )


def render_category_analysis(
    cash_rows,
    net_rows,
    shared=False
):
    if shared:
        render_category_chart_panel(
            "Household Spending by Category",
            "Where household money went this cycle.",
            cash_rows
        )
        return

    cash_col, net_col = st.columns(2, gap="large")
    with cash_col:
        render_category_chart_panel(
            "Cash Outflow by Category",
            "Where cash actually left your accounts.",
            cash_rows
        )
    with net_col:
        render_category_chart_panel(
            "Net Personal Cost by Category",
            "Your true cost after shared ownership.",
            net_rows
        )


def render_trend(data, shared=False):
    if not data:
        return
    selector_left, selector_right = st.columns(
        [1.7, 1],
        vertical_alignment="center"
    )
    with selector_left:
        st.write("")
    with selector_right:
        metrics = (
            ["Household Spending"]
            if shared
            else [
                "Cash Outflow",
                "Net Personal Cost",
                "Income",
                "Savings"
            ]
        )
        metric = st.radio(
            "Trend Metric",
            metrics,
            horizontal=True,
            key="report_trend_metric",
            label_visibility="collapsed"
        )
    chart_df = pd.DataFrame(data)
    line_color = {
        "Cash Outflow": "#EF4444",
        "Net Personal Cost": "#8B5CF6",
        "Household Spending": "#8B5CF6",
        "Income": "#4ADE80",
        "Savings": "#60A5FA"
    }[metric]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=chart_df["Cycle"],
            y=chart_df[metric],
            mode="lines+markers",
            line=dict(color=line_color, width=3),
            marker=dict(
                size=9,
                color=line_color,
                line=dict(color="#C4B5FD", width=2)
            ),
            fill="tozeroy",
            fillcolor="rgba(139, 92, 246, 0.18)",
            hovertemplate=(
                "%{x}<br>"
                f"{metric}: ₹%{{y:,.0f}}"
                "<extra></extra>"
            )
        )
    )
    fig.update_layout(
        height=360,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color="#CBD5E1"),
        margin=dict(l=0, r=0, t=10, b=0),
        showlegend=False,
        yaxis=dict(
            gridcolor="rgba(148,163,184,0.12)",
            tickprefix="₹",
            zerolinecolor="rgba(148,163,184,0.20)"
        ),
        xaxis=dict(gridcolor="rgba(148,163,184,0.06)")
    )
    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False}
    )


def show_reports(vault_id):
    header_left, nav_col = st.columns(
        [3.2, 2.4],
        vertical_alignment="center"
    )
    selected_cycle, cycle_options, cycle_keys, selected_index = (
        get_selected_report_cycle(vault_id)
    )
    shared = is_shared_vault(vault_id)

    with header_left:
        st.markdown(
            """
            <div class="mv-report-title">
                <h2>Reports</h2>
                <p>Financial summary for the selected cycle.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with nav_col:
        nav_left, nav_mid, nav_right = st.columns(
            [1.1, 2.3, 1.1],
            gap="small",
            vertical_alignment="center"
        )
        with nav_left:
            if st.button(
                "Previous Cycle",
                key="report_cycle_prev",
                use_container_width=True,
                disabled=selected_index == 0
            ):
                st.session_state.reports_selected_cycle_start = (
                    cycle_options[selected_index - 1]["key"]
                )
                st.rerun()

        with nav_mid:
            selected_cycle_key = st.selectbox(
                "Current Cycle",
                options=cycle_keys,
                index=selected_index,
                format_func=lambda key: next(
                    option["label"]
                    for option in cycle_options
                    if option["key"] == key
                ),
                key="reports_cycle_dropdown",
                label_visibility="collapsed"
            )
            if selected_cycle_key != (
                st.session_state.reports_selected_cycle_start
            ):
                st.session_state.reports_selected_cycle_start = (
                    selected_cycle_key
                )
                st.rerun()

        with nav_right:
            if st.button(
                "Next Cycle",
                key="report_cycle_next",
                use_container_width=True,
                disabled=selected_index == len(cycle_options) - 1
            ):
                st.session_state.reports_selected_cycle_start = (
                    cycle_options[selected_index + 1]["key"]
                )
                st.rerun()

    report_context = report_period_context(vault_id, selected_cycle)
    start_date = report_context["start_date"]
    end_date = report_context["end_date"]
    cycle_windows = report_context["cycle_windows"]

    summary = get_report_summary(
        vault_id,
        start_date,
        end_date,
        cycle_windows
    )
    cash_categories = get_cash_outflow_category_breakdown(
        vault_id,
        start_date,
        end_date
    )
    net_categories = (
        []
        if shared
        else get_net_personal_category_breakdown(
            vault_id,
            start_date,
            end_date
        )
    )

    period_label = format_cycle_range(
        start_date,
        end_date,
        include_year=True
    )

    st.markdown(
        f"""
        <div class="glass-month mv-report-cycle-label">
            {period_label}
        </div>
        """,
        unsafe_allow_html=True
    )

    st.markdown(
        """
        <div class="mv-report-section">
            <h3>Overview</h3>
            <p>Income, cash movement, cost ownership and savings</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    render_overview(summary, shared=shared)

    st.markdown(
        """
        <div class="mv-report-section">
            <h3>Financial Cycle Review</h3>
            <p>A quick summary of the selected financial cycle</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    render_monthly_review(period_label, summary)

    st.markdown(
        """
        <div class="mv-report-section">
            <h3>Category Analysis</h3>
            <p>Compare cash outflow against your true personal cost</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    render_category_analysis(
        cash_categories,
        net_categories,
        shared=shared
    )

    render_shared_insights(summary, shared=shared)

    st.markdown(
        """
        <div class="mv-report-section">
            <h3>Financial Cycle Trends</h3>
            <p>Compare money movement across financial cycles</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    render_trend(
        get_monthly_trend(vault_id, end_date),
        shared=shared
    )

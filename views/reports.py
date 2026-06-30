from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from db.core import (
    EXPENSE,
    INCOME,
    TRANSFER_OUT,
    get_connection
)
from db.dashboard import get_dashboard_cycle
from db.planning import get_monthly_planning_totals


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
    "calendar_month"
}


def format_money(amount):
    return f"\u20b9{amount:,.0f}"


def month_bounds(year, month):
    if month == 12:
        return (
            date(year, month, 1),
            date(year, month, 31)
        )

    next_month = date(year, month + 1, 1)
    return (
        date(year, month, 1),
        date.fromordinal(next_month.toordinal() - 1)
    )


def previous_month(year, month):
    if month == 1:
        return 12, year - 1

    return month - 1, year


def iter_months(start_date, end_date):
    month = start_date.month
    year = start_date.year

    while (year, month) <= (
        end_date.year,
        end_date.month
    ):
        yield month, year

        if month == 12:
            month = 1
            year += 1
        else:
            month += 1


def period_bounds(vault_id, label):
    active_month, active_year = get_dashboard_cycle(vault_id)

    if label == "Last Month":
        month, year = previous_month(
            active_year,
            active_month
        )
        return month_bounds(year, month)

    if label == "This Year":
        _, active_end = month_bounds(
            active_year,
            active_month
        )

        return (
            date(active_year, 1, 1),
            active_end
        )

    return month_bounds(
        active_year,
        active_month
    )


def get_planning_report_totals(vault_id, start_date, end_date):
    income = 0
    commitments = 0

    for month, year in iter_months(
        start_date,
        end_date
    ):
        totals = get_monthly_planning_totals(
            vault_id,
            month,
            year
        )
        income += totals["income"]
        commitments += totals["planned_commitments"]

    return income, commitments


def get_standalone_transaction_totals(vault_id, start_date, end_date):
    conn = get_connection()

    row = conn.execute(
        """
        SELECT
            COALESCE(SUM(
                CASE
                    WHEN transaction_type = ? THEN amount
                    ELSE 0
                END
            ), 0),
            COALESCE(SUM(
                CASE
                    WHEN transaction_type = ? THEN amount
                    ELSE 0
                END
            ), 0)
        FROM transactions t
        WHERE t.vault_id = ?
        AND t.is_deleted = 0
        AND t.date BETWEEN ? AND ?
        AND (
            (
                t.transaction_type = ?
                AND t.id NOT IN (
                    SELECT transaction_id
                    FROM income_status
                    WHERE transaction_id IS NOT NULL
                )
            )
            OR
            (
                t.transaction_type = ?
                AND t.id NOT IN (
                    SELECT transaction_id
                    FROM obligation_status
                    WHERE transaction_id IS NOT NULL
                )
            )
        )
        """,
        (
            INCOME,
            EXPENSE,
            vault_id,
            start_date.isoformat(),
            end_date.isoformat(),
            INCOME,
            EXPENSE
        )
    ).fetchone()

    conn.close()

    return row[0], row[1]


def get_report_summary(vault_id, start_date, end_date):
    conn = get_connection()

    transaction_count = conn.execute(
        """
        SELECT COUNT(*)
        FROM transactions
        WHERE vault_id = ?
        AND is_deleted = 0
        AND date BETWEEN ? AND ?
        """,
        (
            vault_id,
            start_date.isoformat(),
            end_date.isoformat()
        )
    ).fetchone()[0]

    transfers = conn.execute(
        """
        SELECT COUNT(DISTINCT transfer_group_id)
        FROM transactions
        WHERE vault_id = ?
        AND is_deleted = 0
        AND transfer_group_id IS NOT NULL
        AND transaction_type = ?
        AND date BETWEEN ? AND ?
        """,
        (
            vault_id,
            TRANSFER_OUT,
            start_date.isoformat(),
            end_date.isoformat()
        )
    ).fetchone()[0]

    largest_expense = conn.execute(
        """
        SELECT
            COALESCE(NULLIF(notes, ''), c.name, 'Expense'),
            amount
        FROM transactions t
        LEFT JOIN categories c
            ON t.category_id = c.id
        WHERE t.vault_id = ?
        AND t.is_deleted = 0
        AND t.transaction_type = ?
        AND t.date BETWEEN ? AND ?
        ORDER BY t.amount DESC
        LIMIT 1
        """,
        (
            vault_id,
            EXPENSE,
            start_date.isoformat(),
            end_date.isoformat()
        )
    ).fetchone()

    most_used_category = conn.execute(
        """
        SELECT
            COALESCE(c.emoji || ' ' || c.name, 'Uncategorized'),
            COUNT(*)
        FROM transactions t
        LEFT JOIN categories c
            ON t.category_id = c.id
        WHERE t.vault_id = ?
        AND t.is_deleted = 0
        AND t.transaction_type = ?
        AND t.date BETWEEN ? AND ?
        GROUP BY c.id, c.name, c.emoji
        ORDER BY COUNT(*) DESC, COALESCE(SUM(t.amount), 0) DESC
        LIMIT 1
        """,
        (
            vault_id,
            EXPENSE,
            start_date.isoformat(),
            end_date.isoformat()
        )
    ).fetchone()

    most_used_account = conn.execute(
        """
        SELECT
            a.name,
            COUNT(*)
        FROM transactions t
        JOIN accounts a
            ON t.account_id = a.id
        WHERE t.vault_id = ?
        AND t.is_deleted = 0
        AND t.transaction_type IN (?, ?)
        AND t.date BETWEEN ? AND ?
        GROUP BY a.id, a.name
        ORDER BY COUNT(*) DESC
        LIMIT 1
        """,
        (
            vault_id,
            INCOME,
            EXPENSE,
            start_date.isoformat(),
            end_date.isoformat()
        )
    ).fetchone()

    conn.close()

    planning_income, planning_spent = get_planning_report_totals(
        vault_id,
        start_date,
        end_date
    )
    transaction_income, transaction_spent = get_standalone_transaction_totals(
        vault_id,
        start_date,
        end_date
    )

    income = planning_income + transaction_income
    spent = planning_spent + transaction_spent
    saved = max(
        income - spent,
        0
    )

    return {
        "income": income,
        "spent": spent,
        "saved": saved,
        "transactions": transaction_count,
        "transfers": transfers,
        "largest_expense": largest_expense,
        "most_used_category": most_used_category,
        "most_used_account": most_used_account
    }


def get_category_breakdown(vault_id, start_date, end_date):
    conn = get_connection()

    rows = conn.execute(
        """
        SELECT
            COALESCE(c.emoji, '•'),
            COALESCE(c.name, 'Uncategorized'),
            COALESCE(SUM(t.amount), 0)
        FROM transactions t
        LEFT JOIN categories c
            ON t.category_id = c.id
        WHERE t.vault_id = ?
        AND t.is_deleted = 0
        AND t.transaction_type = ?
        AND t.id NOT IN (
            SELECT transaction_id
            FROM obligation_status
            WHERE transaction_id IS NOT NULL
        )
        AND t.date BETWEEN ? AND ?
        GROUP BY c.id, c.name, c.emoji
        ORDER BY SUM(t.amount) DESC
        """,
        (
            vault_id,
            EXPENSE,
            start_date.isoformat(),
            end_date.isoformat()
        )
    ).fetchall()

    conn.close()

    _, planning_spent = get_planning_report_totals(
        vault_id,
        start_date,
        end_date
    )

    report_rows = list(rows)

    if planning_spent:
        report_rows.append(
            (
                "calendar_month",
                "Recurring Commitments",
                planning_spent
            )
        )

    report_rows.sort(
        key=lambda row: row[2],
        reverse=True
    )

    return report_rows


def get_monthly_trend(vault_id, end_date):
    months = []
    month = end_date.month
    year = end_date.year

    for _ in range(6):
        months.append(
            (month, year)
        )
        month, year = previous_month(
            year,
            month
        )

    months.reverse()

    data = []

    for month, year in months:
        start_date, finish_date = month_bounds(
            year,
            month
        )

        planning_income, planning_spent = get_planning_report_totals(
            vault_id,
            start_date,
            finish_date
        )
        transaction_income, transaction_spent = get_standalone_transaction_totals(
            vault_id,
            start_date,
            finish_date
        )

        spent = planning_spent + transaction_spent
        income = planning_income + transaction_income

        data.append({
            "Month": start_date.strftime("%b"),
            "Spending": spent,
            "Income": income,
            "Savings": max(
                income - spent,
                0
            )
        })

    return data


def render_report_card(icon, title, value, caption, tone):
    st.markdown(
        f"""
        <div class="mv-report-card">
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
        ("calendar_month", "Month", period_label),
        ("receipt_long", "Total Transactions", summary["transactions"]),
        ("sync_alt", "Transfers", summary["transfers"]),
        ("shopping_bag", "Largest Expense", largest_text),
        (
            "restaurant",
            "Most Used Category",
            category[0] if category else "None"
        ),
        (
            "credit_card",
            "Most Used Account",
            account[0] if account else "None"
        )
    ]

    left, right = st.columns(
        [1.1, 1],
        gap="medium"
    )

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
            </div>
            """,
            unsafe_allow_html=True
        )


def render_category_breakdown(rows):
    if not rows:
        st.info("No category spending for this period.")
        return

    total = sum(
        row[2]
        for row in rows
    )

    chart_df = pd.DataFrame(
        [
            {
                "Category": row[1],
                "Amount": row[2]
            }
            for row in rows
        ]
    )

    chart_col, legend_col = st.columns(
        [1.05, 1.25],
        gap="large"
    )

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
                line=dict(
                    color="rgba(255,255,255,0.08)",
                    width=2
                )
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
                    text=(
                        f"<b>{format_money(total)}</b>"
                        "<br>Total Spent"
                    ),
                    x=0.5,
                    y=0.5,
                    showarrow=False,
                    font=dict(
                        size=22,
                        color="#F8FAFC"
                    )
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
            percent = (
                round(row[2] / total * 100)
                if total
                else 0
            )
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


def render_trend(data):
    if not data:
        return

    selector_left, selector_right = st.columns(
        [1.7, 1],
        vertical_alignment="center"
    )

    with selector_left:
        st.write("")

    with selector_right:
        metric = st.radio(
            "Trend Metric",
            [
                "Spending",
                "Income",
                "Savings"
            ],
            horizontal=True,
            key="report_trend_metric",
            label_visibility="collapsed"
        )

    chart_df = pd.DataFrame(data)
    line_color = {
        "Spending": "#8B5CF6",
        "Income": "#4ADE80",
        "Savings": "#60A5FA"
    }[metric]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=chart_df["Month"],
            y=chart_df[metric],
            mode="lines+markers",
            line=dict(
                color=line_color,
                width=3
            ),
            marker=dict(
                size=9,
                color=line_color,
                line=dict(
                    color="#C4B5FD",
                    width=2
                )
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
        xaxis=dict(
            gridcolor="rgba(148,163,184,0.06)"
        )
    )

    st.plotly_chart(
        fig,
        use_container_width=True,
        config={"displayModeBar": False}
    )


def show_reports(vault_id):
    header_left, header_right = st.columns(
        [3.5, 1],
        vertical_alignment="center"
    )

    with header_left:
        st.markdown(
            """
            <div class="mv-report-title">
                <h2>Reports</h2>
                <p>Understand your money better.</p>
            </div>
            """,
            unsafe_allow_html=True
        )

    with header_right:
        period = st.selectbox(
            "Report Period",
            [
                "This Month",
                "Last Month",
                "This Year"
            ],
            label_visibility="collapsed"
        )

    start_date, end_date = period_bounds(
        vault_id,
        period
    )
    summary = get_report_summary(
        vault_id,
        start_date,
        end_date
    )
    categories = get_category_breakdown(
        vault_id,
        start_date,
        end_date
    )

    card_cols = st.columns(3)
    with card_cols[0]:
        render_report_card(
            "business_center",
            "Income",
            format_money(summary["income"]),
            "Total Income",
            "purple"
        )
    with card_cols[1]:
        render_report_card(
            "arrow_outward",
            "Total Spent",
            format_money(summary["spent"]),
            "Across all categories",
            "red"
        )
    with card_cols[2]:
        render_report_card(
            "savings",
            "Total Saved",
            format_money(summary["saved"]),
            "Income - Spent",
            "green"
        )

    st.markdown(
        """
        <div class="mv-report-section">
            <h3>Monthly Review</h3>
            <p>A quick summary of your month</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    render_monthly_review(
        start_date.strftime("%B %Y")
        if period != "This Year"
        else str(start_date.year),
        summary
    )

    st.markdown(
        """
        <div class="mv-report-section">
            <h3>Category Breakdown</h3>
            <p>Where your money went</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    render_category_breakdown(categories)

    st.markdown(
        """
        <div class="mv-report-section">
            <h3>Monthly Trend</h3>
            <p>Total money movement over recent months</p>
        </div>
        """,
        unsafe_allow_html=True
    )
    render_trend(
        get_monthly_trend(
            vault_id,
            end_date
        )
    )

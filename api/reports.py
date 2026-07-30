from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from api.dashboard import to_json_safe
from api.dependencies import get_authenticated_vault
from api.resources import bad_request, int_vault_id
from api.schemas import (
    ReportBiggestPurchase,
    ReportCategoryItem,
    ReportCycleOption,
    ReportCycleProgress,
    ReportFilters,
    ReportFinancialReview,
    ReportMoneyCard,
    ReportReviewItem,
    ReportSpendingComparison,
    ReportSpendingData,
    ReportSpendingBreakdown,
    ReportSpendingBreakdownRow,
    ReportSpendingFilterOptions,
    ReportSpendingMetadata,
    ReportSpendingResponse,
    ReportSpendingSummaryMetric,
    ReportSpendingTrend,
    ReportSpendingTrendPoint,
    ReportSpendingVisualization,
    ReportSpendingVisualizationItem,
    ReportTrendItem,
    ReportsData,
    ReportsResponse,
    VaultContext,
)
from db.core import EXPENSE, get_connection
from db.financial_cycles import (
    add_months,
    build_cycle_navigation_options,
    format_cycle_range,
    get_current_cycle,
    get_cycle_for_date,
)
from views.reports import (
    get_cash_outflow_category_breakdown,
    get_monthly_trend,
    get_net_personal_category_breakdown,
    get_report_summary,
    is_shared_vault,
    report_period_context,
)


router = APIRouter(prefix="/api/reports", tags=["reports"])


def number(value):
    return float(value or 0)


def count(value):
    return int(value or 0)


def tuple_name(value):
    if not value:
        return "None"
    return str(value[0])


def tuple_amount(value):
    if not value or len(value) < 2:
        return 0
    return number(value[1])


def tuple_date(value):
    if not value or len(value) < 3 or not value[2]:
        return None
    return str(value[2])


def cycle_option(option):
    cycle = option["cycle"]
    return ReportCycleOption(
        key=option["key"],
        label=option["label"],
        startDate=cycle.start_iso,
        endDate=cycle.end_iso,
        status=cycle.status,
    )


def category_key(name, index):
    normalized = str(name or "Uncategorized").strip().lower().replace(" ", "-")
    return f"{normalized or 'uncategorized'}:{index}"


def category_rows(rows):
    total = sum(number(row[2]) for row in rows)
    items = []
    for index, row in enumerate(rows):
        amount = number(row[2])
        percent = round(amount / total * 100) if total else 0
        name = str(row[1] or "Uncategorized")
        items.append(
            ReportCategoryItem(
                key=category_key(name, index),
                icon=str(row[0] or "label"),
                name=name,
                amount=amount,
                percent=percent,
            )
        )
    return items


def overview_cards(summary, shared):
    if shared:
        return [
            ReportMoneyCard(
                key="household",
                title="Household Spending",
                value=number(summary["household_spending"]),
                caption="Total shared vault spend",
                tone="purple",
            ),
            ReportMoneyCard(
                key="transactions",
                title="Transactions",
                value=count(summary["transactions"]),
                caption="Shared expenses this cycle",
                tone="green",
                format="count",
            ),
            ReportMoneyCard(
                key="top-category",
                title="Top Category",
                value=tuple_name(summary["most_used_category"]),
                caption="Highest activity category",
                tone="purple",
                format="text",
            ),
        ]

    return [
        ReportMoneyCard(
            key="income",
            title="Income",
            value=number(summary["income"]),
            caption="Money received",
            tone="purple",
        ),
        ReportMoneyCard(
            key="cash-outflow",
            title="Cash Outflow",
            value=number(summary["cash_outflow"]),
            caption="Cash left accounts",
            tone="red",
        ),
        ReportMoneyCard(
            key="net-cost",
            title="Net Personal Cost",
            value=number(summary["net_personal_cost"]),
            caption="Your true expense burden",
            tone="purple",
        ),
        ReportMoneyCard(
            key="savings",
            title="Savings",
            value=number(summary["saved"]),
            caption="Income - net cost",
            tone="green",
        ),
    ]


def cycle_progress(summary):
    total = count(summary["transactions"])
    percent = 100 if total > 0 else 0
    return ReportCycleProgress(
        completedTransactions=total,
        totalTransactions=total,
        percent=percent,
    )


def financial_review(period_label, summary):
    largest = summary["largest_expense"]
    return ReportFinancialReview(
        period=period_label,
        totalTransactions=count(summary["transactions"]),
        transfers=count(summary["transfers"]),
        largestExpense=ReportReviewItem(
            key="largest-expense",
            label="Largest Expense",
            value=tuple_name(largest),
        ),
        mostUsedCategory=ReportReviewItem(
            key="most-used-category",
            label="Most Used Category",
            value=tuple_name(summary["most_used_category"]),
        ),
        mostUsedAccount=ReportReviewItem(
            key="most-used-account",
            label="Most Used Account",
            value=tuple_name(summary["most_used_account"]),
        ),
        biggestPurchase=ReportBiggestPurchase(
            title=tuple_name(largest),
            amount=tuple_amount(largest),
            date=tuple_date(largest),
        ),
        cycleProgress=cycle_progress(summary),
    )


def monthly_review(period_label, summary):
    largest = summary["largest_expense"]
    largest_value = (
        f"{largest[0]} - {number(largest[1]):.2f}"
        if largest
        else "None"
    )
    return [
        ReportReviewItem(key="period", label="Period", value=period_label),
        ReportReviewItem(key="transactions", label="Total Transactions", value=count(summary["transactions"]), format="count"),
        ReportReviewItem(key="transfers", label="Transfers", value=count(summary["transfers"]), format="count"),
        ReportReviewItem(key="largest-expense", label="Largest Expense", value=largest_value),
        ReportReviewItem(key="most-used-category", label="Most Used Category", value=tuple_name(summary["most_used_category"])),
        ReportReviewItem(key="most-used-account", label="Most Used Account", value=tuple_name(summary["most_used_account"])),
    ]


def monthly_summary(summary):
    return [
        ReportReviewItem(key="income", label="Income", value=number(summary["income"]), format="money"),
        ReportReviewItem(key="spent", label="Spent", value=number(summary["spent"]), format="money"),
        ReportReviewItem(key="saved", label="Saved", value=number(summary["saved"]), format="money"),
        ReportReviewItem(key="investments", label="Investments", value=number(summary["investments"]), format="money"),
        ReportReviewItem(key="settlements", label="Settlements", value=number(summary["settlements"]), format="money"),
        ReportReviewItem(key="net-cash-flow", label="Net Cash Flow", value=number(summary["net_cash_flow"]), format="money"),
    ]


def shared_insights(summary, shared):
    if shared:
        return []
    return [
        ReportReviewItem(key="paid-by-you", label="Paid by you", value=number(summary["shared_expenses_paid"]), format="money"),
        ReportReviewItem(key="received-by-you", label="Received by you", value=number(summary["shared_expenses_received"]), format="money"),
        ReportReviewItem(key="you-owe", label="You owe", value=number(summary["outstanding_payables"]), format="money"),
        ReportReviewItem(key="you-are-owed", label="You are owed", value=number(summary["outstanding_receivables"]), format="money"),
        ReportReviewItem(key="settlements-completed", label="Settlements completed", value=number(summary["settlements_completed"]), format="money"),
        ReportReviewItem(key="settlements-pending", label="Settlements pending", value=number(summary["settlements_pending"]), format="money"),
    ]


def trend_rows(rows):
    return [
        ReportTrendItem(
            cycle=str(row["Cycle"]),
            cashOutflow=number(row["Cash Outflow"]),
            netPersonalCost=number(row["Net Personal Cost"]),
            householdSpending=number(row["Household Spending"]),
            income=number(row["Income"]),
            savings=number(row["Savings"]),
        )
        for row in rows
    ]


def select_cycle(vault_id, cycle_start):
    if not cycle_start:
        return get_current_cycle(vault_id)

    valid_keys = {
        option["key"]
        for option in build_cycle_navigation_options(vault_id)
    }
    if cycle_start not in valid_keys:
        raise bad_request("Choose a valid financial cycle.")

    return get_cycle_for_date(vault_id, cycle_start)


SPENDING_COLORS = [
    "#8B5CF6",
    "#2563EB",
    "#22C1C3",
    "#F59E0B",
    "#EC4899",
    "#64748B",
]


def percent_of(amount, total):
    return round(number(amount) / number(total) * 100) if number(total) else 0


def comparison(current, previous, label):
    current_value = number(current)
    previous_value = number(previous)
    if previous_value <= 0 or current_value == previous_value:
        return ReportSpendingComparison(label=label, direction="flat", percent=0)
    delta = round(abs(current_value - previous_value) / previous_value * 100)
    direction = "up" if current_value > previous_value else "down"
    return ReportSpendingComparison(label=label, direction=direction, percent=delta)


def spending_scope_where(shared):
    if shared:
        return "COALESCE(t.beneficiary_vault_id, t.vault_id) = ?"
    return "t.vault_id = ?"


def spending_filter_sql(filters):
    clauses = []
    params = []
    if filters.get("account"):
        clauses.append("a.name = ?")
        params.append(filters["account"])
    if filters.get("category"):
        clauses.append("COALESCE(c.name, 'Uncategorized') = ?")
        params.append(filters["category"])
    if filters.get("merchant"):
        clauses.append("COALESCE(NULLIF(t.notes, ''), c.name, 'Expense') = ?")
        params.append(filters["merchant"])
    if filters.get("payment_mode"):
        clauses.append("COALESCE(a.type, 'Unknown') = ?")
        params.append(filters["payment_mode"])
    if filters.get("amount_min") is not None:
        clauses.append("t.amount >= ?")
        params.append(filters["amount_min"])
    if filters.get("amount_max") is not None:
        clauses.append("t.amount <= ?")
        params.append(filters["amount_max"])
    if filters.get("transaction_type") and filters["transaction_type"] != "Expense":
        clauses.append("t.transaction_type = ?")
        params.append(filters["transaction_type"])
    return clauses, params


def spending_base_query(shared, filters):
    scope_clause = spending_scope_where(shared)
    filter_clauses, filter_params = spending_filter_sql(filters)
    extra = "" if not filter_clauses else "AND " + " AND ".join(filter_clauses)
    return f"""
        FROM transactions t
        LEFT JOIN accounts a ON t.account_id = a.id
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE {scope_clause}
        AND t.is_deleted = 0
        AND t.transaction_type = ?
        AND t.date::date BETWEEN ?::date AND ?::date
        AND COALESCE(t.notes, '') NOT LIKE 'Shared settlement:%'
        {extra}
    """, filter_params


def grouped_spending(conn, base, params, key_expr, name_expr, icon_expr):
    return conn.execute(
        f"""
        SELECT
            {key_expr} AS id,
            {name_expr} AS name,
            {icon_expr} AS icon,
            COALESCE(SUM(t.amount), 0) AS amount,
            COUNT(t.id) AS transaction_count
        {base}
        GROUP BY {key_expr}, {name_expr}
        HAVING COALESCE(SUM(t.amount), 0) > 0
        ORDER BY COALESCE(SUM(t.amount), 0) DESC, {name_expr} ASC
        """,
        tuple(params)
    ).fetchall()


def filter_options(conn, vault_id, start_date, end_date, shared):
    scope_clause = spending_scope_where(shared)
    params = (vault_id, EXPENSE, start_date.isoformat(), end_date.isoformat())
    base = f"""
        FROM transactions t
        LEFT JOIN accounts a ON t.account_id = a.id
        LEFT JOIN categories c ON t.category_id = c.id
        WHERE {scope_clause}
        AND t.is_deleted = 0
        AND t.transaction_type = ?
        AND t.date::date BETWEEN ?::date AND ?::date
        AND COALESCE(t.notes, '') NOT LIKE 'Shared settlement:%'
    """

    def values(expr):
        return [str(row[0]) for row in conn.execute(f"SELECT DISTINCT {expr} {base} ORDER BY {expr}", params).fetchall() if row[0]]

    return ReportSpendingFilterOptions(
        accounts=values("a.name"),
        categories=values("COALESCE(c.name, 'Uncategorized')"),
        merchants=values("COALESCE(NULLIF(t.notes, ''), c.name, 'Expense')"),
        paymentModes=values("COALESCE(a.type, 'Unknown')"),
    )


def spending_rows(vault_id, start_date, end_date, shared, filters):
    base, filter_params = spending_base_query(shared, filters)
    params = [vault_id, EXPENSE, start_date.isoformat(), end_date.isoformat(), *filter_params]
    conn = get_connection()
    try:
        summary = conn.execute(f"SELECT COALESCE(SUM(t.amount), 0), COUNT(t.id) {base}", tuple(params)).fetchone()
        daily = conn.execute(
            f"""
            SELECT t.date::date::text, COALESCE(SUM(t.amount), 0)
            {base}
            GROUP BY t.date::date
            ORDER BY t.date::date
            """,
            tuple(params)
        ).fetchall()
        categories = grouped_spending(conn, base, params, "COALESCE(c.id::text, 'uncategorized')", "COALESCE(c.name, 'Uncategorized')", "COALESCE(MIN(c.emoji), 'label')")
        merchants = grouped_spending(conn, base, params, "LOWER(COALESCE(NULLIF(t.notes, ''), c.name, 'Expense'))", "COALESCE(NULLIF(t.notes, ''), c.name, 'Expense')", "'storefront'")
        accounts = grouped_spending(conn, base, params, "COALESCE(a.id::text, 'unknown')", "COALESCE(a.name, 'Unknown Account')", "'credit-card-outline'")
        payment_modes = grouped_spending(conn, base, params, "COALESCE(a.type, 'Unknown')", "COALESCE(a.type, 'Unknown')", "'wallet-outline'")
        options = filter_options(conn, vault_id, start_date, end_date, shared)
    finally:
        conn.close()
    return {
        "total": number(summary[0] if summary else 0),
        "count": count(summary[1] if summary else 0),
        "daily": daily,
        "categories": categories,
        "merchants": merchants,
        "accounts": accounts,
        "payment_modes": payment_modes,
        "options": options,
    }


def analytics_items(rows):
    total = sum(number(row[3]) for row in rows)
    items = []
    for index, row in enumerate(rows):
        amount = number(row[3])
        label = str(row[1] or "Uncategorized")
        items.append(ReportSpendingVisualizationItem(
            id=str(row[0] or label.lower()),
            key=f"spending:{index}:{str(row[0] or label).lower().replace(' ', '-')}",
            label=label,
            icon=str(row[2] or "label"),
            color=SPENDING_COLORS[index % len(SPENDING_COLORS)],
            amount=amount,
            percent=percent_of(amount, total),
            transactionCount=count(row[4] if len(row) > 4 else 0),
        ))
    return items


def trend_points(rows):
    return [ReportSpendingTrendPoint(date=str(row[0]), label=str(row[0])[8:10], amount=number(row[1])) for row in rows]


def analytics_breakdown(title, items, sub_label_for=None):
    rows = []
    for item in items:
        rows.append(ReportSpendingBreakdownRow(
            id=item.id,
            key=item.key,
            label=item.label,
            subLabel=sub_label_for(item) if sub_label_for else "",
            icon=item.icon,
            amount=item.amount,
            percent=item.percent,
            transactionCount=item.transaction_count,
        ))
    return ReportSpendingBreakdown(title=title, rows=rows)


def largest_transaction(vault_id, start_date, end_date, shared, filters):
    base, filter_params = spending_base_query(shared, filters)
    params = [vault_id, EXPENSE, start_date.isoformat(), end_date.isoformat(), *filter_params]
    conn = get_connection()
    try:
        row = conn.execute(
            f"""
            SELECT COALESCE(NULLIF(t.notes, ''), c.name, 'Expense'), t.amount
            {base}
            ORDER BY t.amount DESC, t.date::date DESC, t.id DESC
            LIMIT 1
            """,
            tuple(params)
        ).fetchone()
    finally:
        conn.close()
    return row


def metric(key, title, value, fmt="money", caption="", tone="purple", comp=None):
    return ReportSpendingSummaryMetric(key=key, title=title, value=value, format=fmt, caption=caption, tone=tone, comparison=comp)


def dimension_config(dimension):
    configs = {
        "categories": {
            "question": "Where is my money going?",
            "title": "Spending by Category",
            "breakdown": "Category Breakdown",
            "chart": "donut",
            "empty_title": "No categories",
            "empty_message": "No category spending for this cycle.",
            "rows_key": "categories",
        },
        "merchants": {
            "question": "Who am I spending with?",
            "title": "Spending by Merchant",
            "breakdown": "Merchant Breakdown",
            "chart": "horizontalBar",
            "empty_title": "No merchants",
            "empty_message": "No merchant spending for this cycle.",
            "rows_key": "merchants",
        },
        "accounts": {
            "question": "Which account funds spending?",
            "title": "Spending by Account",
            "breakdown": "Account Breakdown",
            "chart": "verticalBar",
            "empty_title": "No accounts",
            "empty_message": "No account spending for this cycle.",
            "rows_key": "accounts",
        },
        "paymentModes": {
            "question": "How do I pay?",
            "title": "Spending by Payment Mode",
            "breakdown": "Payment Mode Breakdown",
            "chart": "percentageBar",
            "empty_title": "No payment modes",
            "empty_message": "No payment mode spending for this cycle.",
            "rows_key": "payment_modes",
        },
    }
    return configs.get(dimension, configs["categories"])


def spending_summary_for_dimension(dimension, current, previous, selected_cycle, previous_label, vault_id, shared, filters):
    days = max((selected_cycle.end_date - selected_cycle.start_date).days + 1, 1)
    total = current["total"]
    daily_average = round(total / days, 2)
    highest = max(current["daily"], key=lambda row: number(row[1]), default=None)
    highest_amount = number(highest[1]) if highest else 0
    highest_date = str(highest[0]) if highest else "No spending"
    if dimension == "merchants":
        merchants = analytics_items(current["merchants"])
        top = merchants[0] if merchants else None
        largest = largest_transaction(vault_id, selected_cycle.start_date, selected_cycle.end_date, shared, filters)
        average = round(total / len(merchants), 2) if merchants else 0
        return [
            metric("unique-merchants", "Unique Merchants", len(merchants), "count", "This cycle", "purple"),
            metric("top-merchant", "Top Merchant", top.label if top else "None", "text", "Highest total spend", "purple"),
            metric("largest-transaction", "Largest Transaction", number(largest[1]) if largest else 0, "money", str(largest[0]) if largest else "None", "red"),
            metric("average-merchant", "Avg / Merchant", average, "money", "Across merchants", "blue"),
        ]
    if dimension == "accounts":
        accounts = analytics_items(current["accounts"])
        most_used = max(accounts, key=lambda item: item.transaction_count, default=None)
        highest_spend = accounts[0] if accounts else None
        return [
            metric("cash-outflow", "Cash Outflow", total, "money", f"vs {previous_label}", "red", comparison(total, previous["total"], f"vs {previous_label}")),
            metric("most-used-account", "Most Used Account", most_used.label if most_used else "None", "text", "By transaction count", "purple"),
            metric("highest-spend-account", "Highest Spend Account", highest_spend.label if highest_spend else "None", "text", "By amount", "blue"),
            metric("transactions", "Transactions", current["count"], "count", f"vs {previous_label}", "green", comparison(current["count"], previous["count"], f"vs {previous_label}")),
        ]
    if dimension == "paymentModes":
        modes = analytics_items(current["payment_modes"])
        most_used = max(modes, key=lambda item: item.transaction_count, default=None)
        highest = modes[0] if modes else None
        credit_card = sum(item.amount for item in modes if "credit" in item.label.lower())
        other = max(total - credit_card, 0)
        return [
            metric("most-used-mode", "Most Used Mode", most_used.label if most_used else "None", "text", "By transaction count", "purple"),
            metric("highest-spend-mode", "Highest Spend Mode", highest.label if highest else "None", "text", "By amount", "blue"),
            metric("credit-card-spend", "Credit Card Spend", credit_card, "money", "Credit card accounts", "red"),
            metric("other-spend", "Other Spend", other, "money", "All other modes", "green"),
        ]
    previous_daily_average = round(previous["total"] / days, 2)
    return [
        metric("total-spent", "Total Spent", total, "money", f"vs {previous_label}", "red", comparison(total, previous["total"], f"vs {previous_label}")),
        metric("daily-average", "Daily Average", daily_average, "money", f"vs {previous_label}", "purple", comparison(daily_average, previous_daily_average, f"vs {previous_label}")),
        metric("highest-day", "Highest Day", highest_amount, "money", highest_date, "orange"),
        metric("transactions", "Transactions", current["count"], "count", f"vs {previous_label}", "blue", comparison(current["count"], previous["count"], f"vs {previous_label}")),
    ]


def spending_analytics_data(dimension, current, previous, selected_cycle, previous_label, vault_id, shared, filters):
    config = dimension_config(dimension)
    items = analytics_items(current[config["rows_key"]])
    total = sum(item.amount for item in items)
    return ReportSpendingData(
        summary=spending_summary_for_dimension(dimension, current, previous, selected_cycle, previous_label, vault_id, shared, filters),
        visualization=ReportSpendingVisualization(type=config["chart"], title=config["title"], total=total, items=items),
        trend=ReportSpendingTrend(title=f"{config['title']} Trend", points=trend_points(current["daily"])),
        breakdown=analytics_breakdown(config["breakdown"], items, lambda item: f"{item.transaction_count} transactions"),
        metadata=ReportSpendingMetadata(
            dimension=dimension,
            question=config["question"],
            emptyTitle=config["empty_title"],
            emptyMessage=config["empty_message"],
            filterOptions=current["options"],
        ),
    )

@router.get("", response_model=ReportsResponse, response_model_by_alias=True)
def reports(
    cycle_start: str | None = Query(default=None, alias="cycleStart"),
    detail_level: str = Query(default="full", alias="detailLevel"),
    vault: VaultContext = Depends(get_authenticated_vault),
):
    if detail_level not in {"overview", "full"}:
        raise bad_request("Choose a valid reports detail level.")

    vault_id = int_vault_id(vault)
    selected_cycle = select_cycle(vault_id, cycle_start)
    context = report_period_context(vault_id, selected_cycle)
    start_date = context["start_date"]
    end_date = context["end_date"]
    cycle_windows = context["cycle_windows"]
    shared = is_shared_vault(vault_id)
    summary = to_json_safe(
        get_report_summary(vault_id, start_date, end_date, cycle_windows)
    )
    include_breakdowns = detail_level == "full"
    cash_categories = get_cash_outflow_category_breakdown(vault_id, start_date, end_date) if include_breakdowns else []
    net_categories = [] if shared or not include_breakdowns else get_net_personal_category_breakdown(vault_id, start_date, end_date)
    trend = get_monthly_trend(vault_id, end_date) if include_breakdowns else []
    period_label = format_cycle_range(start_date, end_date, include_year=True)

    return ReportsResponse(
        generatedAt=datetime.now(timezone.utc),
        vault=vault,
        filters=ReportFilters(
            period="cycle",
            cycleStart=selected_cycle.start_iso,
            startDate=selected_cycle.start_iso,
            endDate=selected_cycle.end_iso,
        ),
        cycleOptions=[
            cycle_option(option)
            for option in build_cycle_navigation_options(vault_id)
        ],
        data=ReportsData(
            summary=summary,
            overview=overview_cards(summary, shared),
            financialReview=financial_review(period_label, summary),
            monthlyReview=monthly_review(period_label, summary),
            monthlySummary=monthly_summary(summary),
            sharedInsights=shared_insights(summary, shared),
            cashOutflowByCategory=category_rows(to_json_safe(cash_categories)),
            netPersonalCostByCategory=category_rows(to_json_safe(net_categories)),
            trend=trend_rows(to_json_safe(trend)),
            naturalLanguageResult=None,
        ),
    )



@router.get("/spending", response_model=ReportSpendingResponse, response_model_by_alias=True)
def reports_spending(
    cycle_start: str | None = Query(default=None, alias="cycleStart"),
    dimension: str = Query(default="categories"),
    account: str | None = Query(default=None),
    category: str | None = Query(default=None),
    merchant: str | None = Query(default=None),
    payment_mode: str | None = Query(default=None, alias="paymentMode"),
    transaction_type: str | None = Query(default=None, alias="transactionType"),
    amount_min: float | None = Query(default=None, alias="amountMin"),
    amount_max: float | None = Query(default=None, alias="amountMax"),
    vault: VaultContext = Depends(get_authenticated_vault),
):
    if dimension not in {"categories", "merchants", "accounts", "paymentModes"}:
        raise bad_request("Choose a valid reports analysis dimension.")

    vault_id = int_vault_id(vault)
    selected_cycle = select_cycle(vault_id, cycle_start)
    previous_cycle = get_cycle_for_date(vault_id, add_months(selected_cycle.start_date, -1).isoformat())
    shared = is_shared_vault(vault_id)
    filters = {
        "account": account,
        "category": category,
        "merchant": merchant,
        "payment_mode": payment_mode,
        "transaction_type": transaction_type,
        "amount_min": amount_min,
        "amount_max": amount_max,
    }
    current = spending_rows(vault_id, selected_cycle.start_date, selected_cycle.end_date, shared, filters)
    previous = spending_rows(vault_id, previous_cycle.start_date, previous_cycle.end_date, shared, filters)
    previous_label = previous_cycle.start_date.strftime("%b %Y")

    return ReportSpendingResponse(
        generatedAt=datetime.now(timezone.utc),
        vault=vault,
        filters=ReportFilters(
            period="cycle",
            cycleStart=selected_cycle.start_iso,
            startDate=selected_cycle.start_iso,
            endDate=selected_cycle.end_iso,
        ),
        data=spending_analytics_data(dimension, current, previous, selected_cycle, previous_label, vault_id, shared, filters),
    )

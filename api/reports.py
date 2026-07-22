from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from api.dashboard import to_json_safe
from api.dependencies import get_authenticated_vault
from api.resources import bad_request, int_vault_id
from api.schemas import (
    ReportCategoryItem,
    ReportCycleOption,
    ReportFilters,
    ReportMoneyCard,
    ReportReviewItem,
    ReportTrendItem,
    ReportsData,
    ReportsResponse,
    VaultContext,
)
from db.financial_cycles import (
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

    outstanding_label = (
        "Owed to you"
        if number(summary["net_outstanding"]) > 0
        else "You owe"
        if number(summary["net_outstanding"]) < 0
        else "All settled"
    )
    return [
        ReportMoneyCard(
            key="income",
            title="Income",
            value=number(summary["income"]),
            caption="Money received this cycle",
            tone="purple",
        ),
        ReportMoneyCard(
            key="cash-outflow",
            title="Cash Outflow",
            value=number(summary["cash_outflow"]),
            caption="Cash that left accounts",
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
            key="settlements",
            title="Outstanding Settlements",
            value=abs(number(summary["net_outstanding"])),
            caption=outstanding_label,
            tone="red" if number(summary["net_outstanding"]) < 0 else "green",
        ),
        ReportMoneyCard(
            key="savings",
            title="Savings",
            value=number(summary["saved"]),
            caption="Income - net cost",
            tone="green",
        ),
    ]


def monthly_review(period_label, summary):
    largest = summary["largest_expense"]
    largest_value = (
        f"{largest[0]} · {number(largest[1]):.2f}"
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
        ReportReviewItem(key="shared-paid", label="Total Shared Expenses Paid", value=number(summary["shared_expenses_paid"]), format="money"),
        ReportReviewItem(key="shared-received", label="Total Shared Expenses Received", value=number(summary["shared_expenses_received"]), format="money"),
        ReportReviewItem(key="receivables", label="Outstanding Receivables", value=number(summary["outstanding_receivables"]), format="money"),
        ReportReviewItem(key="payables", label="Outstanding Payables", value=number(summary["outstanding_payables"]), format="money"),
        ReportReviewItem(key="settlements-completed", label="Settlements Completed", value=number(summary["settlements_completed"]), format="money"),
        ReportReviewItem(key="settlements-pending", label="Settlements Pending", value=number(summary["settlements_pending"]), format="money"),
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


@router.get("", response_model=ReportsResponse, response_model_by_alias=True)
def reports(
    cycle_start: str | None = Query(default=None, alias="cycleStart"),
    vault: VaultContext = Depends(get_authenticated_vault),
):
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
    cash_categories = get_cash_outflow_category_breakdown(vault_id, start_date, end_date)
    net_categories = [] if shared else get_net_personal_category_breakdown(vault_id, start_date, end_date)
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
            monthlyReview=monthly_review(period_label, summary),
            monthlySummary=monthly_summary(summary),
            sharedInsights=shared_insights(summary, shared),
            cashOutflowByCategory=category_rows(to_json_safe(cash_categories)),
            netPersonalCostByCategory=category_rows(to_json_safe(net_categories)),
            trend=trend_rows(to_json_safe(get_monthly_trend(vault_id, end_date))),
            naturalLanguageResult=None,
        ),
    )

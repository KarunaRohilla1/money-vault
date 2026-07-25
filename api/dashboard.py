from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_authenticated_vault
from api.schemas import (
    CategorySpendItem,
    DashboardDataResponse,
    DashboardResponse,
    FinancialCycleResponse,
    PrimaryAccountResponse,
    RecentActivityItem,
    SafeToSpendBreakdownItem,
    SafeToSpendBreakdownResponse,
    SetupStatusResponse,
    SettlementResponse,
    VaultContext,
)
from db.dashboard import get_dashboard_page_data
from db.financial_cycles import get_current_cycle


router = APIRouter(prefix="/api", tags=["dashboard"])


def to_json_safe(value: Any):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): to_json_safe(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [
            to_json_safe(item)
            for item in value
        ]
    return value


def number(value):
    return float(value or 0)


def cash_flow_direction(transaction_type):
    normalized = str(transaction_type or "").strip().lower()
    if normalized in ("income", "transfer in"):
        return "credit"
    if normalized in ("expense", "transfer out"):
        return "debit"
    return "neutral"


def signed_amount(amount, direction):
    value = number(amount)
    if direction == "credit":
        return abs(value)
    if direction == "debit":
        return -abs(value)
    return 0


def category_key(category_id, name):
    if category_id is not None:
        return f"category:{category_id}"

    normalized_name = str(name or "").strip().lower()
    if normalized_name in ("", "uncategorized"):
        return "uncategorized"

    return f"legacy-category:{normalized_name}"


def adapt_recent_activity(rows):
    items = []
    for row in rows[:5]:
        direction = cash_flow_direction(row[5])
        items.append(
            RecentActivityItem(
                id=int(row[0]),
                date=str(to_json_safe(row[1])),
                accountName=row[2],
                categoryName=str(row[3]),
                amount=number(row[4]),
                signedAmount=signed_amount(row[4], direction),
                direction=direction,
                transactionType=str(row[5]),
                notes=row[6]
            )
        )
    return items


def build_safe_to_spend_breakdown(summary):
    settlement = summary["settlement_summary"]
    items = [
        SafeToSpendBreakdownItem(
            key="available_cash",
            label="Available Cash",
            amount=number(summary["available_cash"]),
            operation="add"
        ),
        SafeToSpendBreakdownItem(
            key="you_owe",
            label="You Owe",
            amount=number(settlement["payable"]),
            operation="subtract"
        ),
        SafeToSpendBreakdownItem(
            key="remaining_commitments",
            label="Remaining Commitments",
            amount=number(summary["remaining_commitments"]),
            operation="subtract"
        ),
        SafeToSpendBreakdownItem(
            key="credit_card_due",
            label="Credit Card Due",
            amount=number(summary["credit_card_due"]),
            operation="subtract"
        ),
        SafeToSpendBreakdownItem(
            key="savings_goal",
            label="Savings Goal",
            amount=number(summary["monthly_savings_goal"]),
            operation="subtract"
        )
    ]
    raw_total = (
        items[0].amount
        - items[1].amount
        - items[2].amount
        - items[3].amount
        - items[4].amount
    )
    total = number(summary["safe_to_spend"])

    if raw_total < 0 and total == 0:
        items.append(
            SafeToSpendBreakdownItem(
                key="minimum_safe_to_spend_floor",
                label="Minimum Safe to Spend",
                amount=abs(raw_total),
                operation="add"
            )
        )

    return SafeToSpendBreakdownResponse(
        items=items,
        total=total
    )

def adapt_dashboard_response(vault: VaultContext, payload, cycle):
    safe_payload = to_json_safe(payload)
    summary = safe_payload["summary"]
    status_payload = safe_payload["status"]
    settlement = summary["settlement_summary"]
    response_vault = VaultContext(
        id=vault.id,
        name=vault.name,
        isAdmin=vault.is_admin,
        vaultType=vault.vault_type
    )

    return DashboardResponse(
        generatedAt=datetime.now(timezone.utc),
        vault=response_vault,
        data=DashboardDataResponse(
            cycle=FinancialCycleResponse(
                id=cycle.id,
                startDate=cycle.start_iso,
                endDate=cycle.end_iso,
                displayName=cycle.display_name,
                status=cycle.status,
                daysCompleted=cycle.days_completed,
                daysRemaining=cycle.days_remaining,
                totalDays=cycle.total_days,
                progressPercent=cycle.progress_percent
            ),
            safeToSpend=number(summary["safe_to_spend"]),
            safeToSpendBreakdown=build_safe_to_spend_breakdown(summary),
            primaryAccount=PrimaryAccountResponse(
                name=str(summary["primary_account_name"]),
                balance=number(summary["primary_account_balance"])
            ),
            expensesThisCycle=number(summary["expenses"]),
            remainingCommitments=number(summary["remaining_commitments"]),
            creditCardDue=number(summary["credit_card_due"]),
            settlement=SettlementResponse(
                label=str(settlement["label"]),
                amount=number(settlement["amount"]),
                direction=str(settlement["direction"]),
                receivable=number(settlement["receivable"]),
                payable=number(settlement["payable"]),
                net=number(settlement["net"]),
                items=to_json_safe(settlement.get("items", []))
            ),
            recentActivity=adapt_recent_activity(safe_payload.get("recent_activity", [])),
            spendingByCategory=[
                CategorySpendItem(
                    categoryId=int(item[0]) if len(item) > 2 and item[0] is not None else None,
                    key=category_key(item[0] if len(item) > 2 else None, item[1] if len(item) > 2 else item[0]),
                    name=str(item[1] if len(item) > 2 else item[0]),
                    amount=number(item[2] if len(item) > 2 else item[1])
                )
                for item in safe_payload.get("category_spending", [])
            ],
            setup=SetupStatusResponse(
                accounts=int(status_payload["accounts"]),
                incomeTemplates=int(status_payload["income_templates"]),
                commitments=int(status_payload["commitments"]),
                hasVaultLogin=bool(status_payload["has_vault_login"]),
                hasCycleSetting=bool(status_payload["has_cycle_setting"]),
                hasSavingsGoal=bool(status_payload["has_savings_goal"]),
                hasAccounts=bool(status_payload["has_accounts"]),
                hasIncomeTemplates=bool(status_payload["has_income_templates"]),
                hasCommitments=bool(status_payload["has_commitments"]),
                isComplete=bool(status_payload["is_complete"])
            ),
            summary=summary
        )
    )


@router.get("/dashboard", response_model=DashboardResponse, response_model_by_alias=True, response_model_exclude_none=True)
def dashboard(vault: VaultContext = Depends(get_authenticated_vault)):
    try:
        vault_id = int(vault.id)
        payload = get_dashboard_page_data(vault_id)
        cycle = get_current_cycle(vault_id)
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "code": "DASHBOARD_UNAVAILABLE",
                "message": "Dashboard is unavailable."
            }
        ) from error

    if not cycle:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "NO_ACTIVE_CYCLE",
                "message": "No active financial cycle is available."
            }
        )

    return adapt_dashboard_response(vault, payload, cycle)

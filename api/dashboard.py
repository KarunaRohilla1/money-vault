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


def adapt_recent_activity(rows):
    items = []
    for row in rows[:5]:
        items.append(
            RecentActivityItem(
                id=int(row[0]),
                date=str(to_json_safe(row[1])),
                accountName=row[2],
                categoryName=str(row[3]),
                amount=number(row[4]),
                transactionType=str(row[5]),
                notes=row[6]
            )
        )
    return items


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
                CategorySpendItem(name=str(item[0]), amount=number(item[1]))
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

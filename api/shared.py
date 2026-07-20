from datetime import UTC, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_authenticated_vault
from api.resources import (
    bad_request,
    int_vault_id,
    require_category,
    require_shared_bill,
    require_shared_bill_cycle,
    require_shared_bill_instance,
    require_shared_participant,
    require_shared_vault
)
from api.schemas import (
    SharedBillPaymentRequest,
    SharedBillRequest,
    SharedPageResponse,
    SharedSettlementRequest,
    SuccessResponse,
    VaultContext
)
from db.financial_cycles import get_current_cycle
from db.accounts import get_accounts_with_balances
from db.core import get_connection
from db.shared_bills import (
    add_shared_bill,
    cancel_shared_bill,
    close_cycle,
    duplicate_shared_bill,
    get_shared_bills_page_data,
    get_shared_bills_summary,
    mark_bill_paid,
    skip_bill_instance,
    update_shared_bill
)
from db.shared_expenses import (
    get_settlement_summary,
    get_shared_category_spending,
    get_shared_expenses_page_data,
    get_shared_vault_summary,
    settle_outstanding_settlement
)
from db.vaults import get_connected_shared_vaults, get_vault_by_id


router = APIRouter(prefix="/api/shared", tags=["shared"])


def default_shared_vault_id(vault_id):
    vault = get_vault_by_id(vault_id)
    if vault and vault[4] == "Shared":
        return int(vault_id)

    shared_vaults = get_connected_shared_vaults(vault_id)
    if not shared_vaults:
        raise bad_request("No shared vault is connected to this vault.")

    return int(shared_vaults[0][0])


def resolve_shared_vault_id(vault_id, shared_vault_id=None):
    selected_id = int(shared_vault_id) if shared_vault_id else default_shared_vault_id(vault_id)
    require_shared_vault(
        selected_id,
        vault_id
    )
    return selected_id


def cycle_bounds(shared_vault_id):
    cycle = get_current_cycle(shared_vault_id)
    return cycle.start_iso, cycle.end_iso


def shared_vault_id_for_instance(instance_id):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT c.shared_vault_id
            FROM shared_bill_instances i
            JOIN shared_bill_cycles c
                ON i.cycle_id = c.id
            WHERE i.id = ?
            """,
            (instance_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise bad_request("Bill instance not found.")

    return int(row[0])


def shared_vault_id_for_bill(bill_id):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT shared_vault_id
            FROM shared_bills
            WHERE id = ?
            """,
            (bill_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        raise bad_request("Bill not found.")

    return int(row[0])



def current_personal_vault_id(vault):
    if vault.vault_type == "Shared" and vault.authenticated_vault_id:
        return int(vault.authenticated_vault_id)
    return int_vault_id(vault)


def safe_percent(amount, total):
    total = float(total or 0)
    if total <= 0:
        return 0
    return round(float(amount or 0) / total * 100)


def stable_key(value):
    key = "".join(
        char.lower() if char.isalnum() else "-"
        for char in str(value or "uncategorized")
    ).strip("-")
    return key or "uncategorized"


def participant_initial(name):
    return (name or "?").strip()[:1].upper() or "?"


def adapt_shared_dashboard_cycle(cycle):
    return {
        "id": cycle.id,
        "startDate": cycle.start_iso,
        "endDate": cycle.end_iso,
        "displayName": cycle.display_name,
        "status": cycle.status,
        "daysCompleted": cycle.days_completed,
        "daysRemaining": cycle.days_remaining,
        "totalDays": cycle.total_days,
        "progressPercent": cycle.progress_percent
    }


def adapt_shared_dashboard_vault(shared_vault_id):
    row = get_vault_by_id(shared_vault_id)
    if not row:
        raise bad_request("Shared vault not found.")
    return {
        "id": str(row[0]),
        "name": row[1],
        "isAdmin": bool(row[3]),
        "vaultType": row[4]
    }


def build_shared_dashboard_payload(vault, shared_vault_id):
    personal_vault_id = current_personal_vault_id(vault)
    cycle = get_current_cycle(shared_vault_id)
    start_date = cycle.start_iso
    end_date = cycle.end_iso
    expenses = get_shared_expenses_page_data(
        shared_vault_id,
        start_date,
        end_date
    )
    shared_summary = get_shared_vault_summary(
        shared_vault_id,
        start_date,
        end_date
    )
    bill_summary = get_shared_bills_summary(shared_vault_id)
    category_rows = get_shared_category_spending(
        shared_vault_id,
        start_date,
        end_date
    )
    settlement = settlement_summary_with_accounts(
        personal_vault_id
    )
    participants = shared_summary["participants"]
    current_participant = next(
        (
            item
            for item in participants
            if int(item["vault_id"]) == personal_vault_id
        ),
        None
    )
    total_spend = float(shared_summary["total_shared_spending"] or 0)
    top_category_row = category_rows[0] if category_rows else None
    top_category_amount = float(top_category_row[2]) if top_category_row else 0
    daily_average = round(
        total_spend / max(cycle.days_completed, 1),
        2
    )
    projection = round(
        daily_average * cycle.total_days,
        2
    )
    current_paid = float(current_participant["paid"] if current_participant else 0)
    current_share = float(current_participant["share"] if current_participant else 0)
    current_balance = float(current_participant["balance"] if current_participant else 0)

    spending_chart = []
    for row in category_rows:
        amount = float(row[2] or 0)
        name = row[1] or "Uncategorized"
        spending_chart.append({
            "key": f"category:{stable_key(name)}",
            "category": name,
            "amount": amount,
            "percentage": safe_percent(amount, total_spend),
            "icon": row[0]
        })

    recent_activity = []
    for expense in expenses["expenses"][:5]:
        paid_by_current = int(expense["paid_by_id"]) == personal_vault_id
        recent_activity.append({
            "id": expense["id"],
            "participant": expense["paid_by"],
            "category": expense["category"],
            "amount": expense["amount"],
            "date": expense["date"],
            "time": None,
            "direction": "paid" if paid_by_current else "owed",
            "sharedTag": expense["split_label"],
            "icon": expense["category_icon"]
        })

    participant_summaries = [
        {
            "vaultId": item["vault_id"],
            "name": item["name"],
            "avatarInitial": participant_initial(item["name"]),
            "paid": item["paid"],
            "share": item["share"],
            "balance": item["balance"],
            "positiveBalance": max(float(item["balance"]), 0),
            "negativeBalance": max(-float(item["balance"]), 0),
            "isCurrentUser": int(item["vault_id"]) == personal_vault_id
        }
        for item in participants
    ]

    settlement_amount = abs(current_balance)
    return {
        "generatedAt": datetime.now(UTC).isoformat(),
        "vault": adapt_shared_dashboard_vault(shared_vault_id),
        "data": {
            "cycle": adapt_shared_dashboard_cycle(cycle),
            "settlement": {
                "currentUserOwes": max(-current_balance, 0),
                "currentUserIsOwed": max(current_balance, 0),
                "currentUserPaid": current_paid,
                "currentUserShare": current_share,
                "settlementPercentage": safe_percent(current_paid, current_share) if current_share > 0 else 100,
                "amount": settlement_amount,
                "label": "All settled" if settlement_amount == 0 else ("You owe" if current_balance < 0 else "You are owed"),
                "direction": "settled" if settlement_amount == 0 else ("payable" if current_balance < 0 else "receivable"),
                "items": [
                    item
                    for item in settlement["items"]
                    if int(item["shared_vault_id"]) == int(shared_vault_id)
                ]
            },
            "householdSnapshot": {
                "householdSpendThisMonth": total_spend,
                "upcomingBillsCount": bill_summary["due_soon_count"],
                "participantCount": len(participants),
                "topCategory": top_category_row[1] if top_category_row else None,
                "topCategoryPercentage": safe_percent(top_category_amount, total_spend),
                "topCategoryAmount": top_category_amount
            },
            "recentActivity": recent_activity,
            "participants": participant_summaries,
            "spendingChart": spending_chart,
            "monthlySummary": {
                "monthlySpend": total_spend,
                "dailyAverage": daily_average,
                "projection": projection
            },
            "quickActions": {
                "canAddExpense": True,
                "canSplit": True,
                "canAddBill": True,
                "markSettledVisible": settlement_amount > 0,
                "markSettledEnabled": settlement_amount > 0
            },
            "emptyStates": {
                "noSharedTransactions": len(expenses["expenses"]) == 0,
                "noParticipants": len(participants) == 0,
                "noSpending": total_spend == 0,
                "noCategories": len(spending_chart) == 0,
                "noBills": bill_summary["due_soon_count"] == 0
            }
        }
    }

def adapt_settlement_account(row):
    return {
        "balance": float(row[5]) if len(row) > 5 and row[5] is not None else None,
        "id": int(row[0]),
        "is_primary": bool(row[4]),
        "name": row[1],
        "type": row[2]
    }


def settlement_summary_with_accounts(vault_id):
    cycle = get_current_cycle(vault_id)
    summary = get_settlement_summary(
        vault_id,
        cycle.start_iso,
        cycle.end_iso
    )

    items = []
    for item in summary["items"]:
        items.append({
            **item,
            "from_accounts": [
                adapt_settlement_account(row)
                for row in get_accounts_with_balances(item["from_vault_id"])
            ],
            "to_accounts": [
                adapt_settlement_account(row)
                for row in get_accounts_with_balances(item["to_vault_id"])
            ]
        })

    return {
        **summary,
        "items": items
    }


@router.get("/dashboard", response_model=SharedPageResponse, response_model_by_alias=True)
def shared_dashboard(
    shared_vault_id: Optional[int] = Query(default=None, alias="sharedVaultId"),
    vault: VaultContext = Depends(get_authenticated_vault)
):
    selected_id = resolve_shared_vault_id(
        int_vault_id(vault),
        shared_vault_id
    )
    return SharedPageResponse(
        data=build_shared_dashboard_payload(
            vault,
            selected_id
        )
    )

@router.get("/expenses", response_model=SharedPageResponse, response_model_by_alias=True)
def shared_expenses(
    shared_vault_id: Optional[int] = Query(default=None, alias="sharedVaultId"),
    date_from: Optional[str] = Query(default=None, alias="dateFrom"),
    date_to: Optional[str] = Query(default=None, alias="dateTo"),
    category_id: Optional[int] = Query(default=None, alias="categoryId"),
    paid_by_vault_id: Optional[int] = Query(default=None, alias="paidByVaultId"),
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    selected_id = resolve_shared_vault_id(
        vault_id,
        shared_vault_id
    )
    start_date, end_date = cycle_bounds(selected_id)

    if paid_by_vault_id is not None:
        require_shared_participant(
            paid_by_vault_id,
            selected_id
        )

    return SharedPageResponse(
        data=get_shared_expenses_page_data(
            selected_id,
            date_from or start_date,
            date_to or end_date,
            category_id=category_id,
            paid_by_vault_id=paid_by_vault_id
        )
    )


@router.get("/settlements", response_model=SharedPageResponse, response_model_by_alias=True)
def shared_settlements(vault: VaultContext = Depends(get_authenticated_vault)):
    return SharedPageResponse(
        data=settlement_summary_with_accounts(
            int_vault_id(vault)
        )
    )


@router.get("/bills", response_model=SharedPageResponse, response_model_by_alias=True)
def shared_bills(
    shared_vault_id: Optional[int] = Query(default=None, alias="sharedVaultId"),
    year: Optional[int] = None,
    month: Optional[int] = None,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    selected_id = resolve_shared_vault_id(
        int_vault_id(vault),
        shared_vault_id
    )
    return SharedPageResponse(
        data=get_shared_bills_page_data(
            selected_id,
            year=year,
            month=month
        )
    )


@router.post("/bills", response_model=SuccessResponse, response_model_by_alias=True)
def create_shared_bill(request: SharedBillRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = int_vault_id(vault)
    require_shared_vault(
        request.shared_vault_id,
        vault_id
    )
    if request.category_id is not None:
        require_category(
            request.category_id,
            request.shared_vault_id
        )
    try:
        add_shared_bill(
            request.shared_vault_id,
            request.name,
            request.amount,
            request.due_day,
            category_id=request.category_id,
            notes=request.notes,
            frequency=request.frequency,
            start_date=request.start_date,
            end_date=request.end_date,
            is_active=request.is_active
        )
    except ValueError as error:
        raise bad_request(str(error)) from error
    return SuccessResponse()


@router.put("/bills/{bill_id}", response_model=SuccessResponse, response_model_by_alias=True)
def update_shared_bill_route(
    bill_id: int,
    request: SharedBillRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    require_shared_bill(
        bill_id,
        vault_id
    )
    existing_shared_vault_id = shared_vault_id_for_bill(bill_id)
    if existing_shared_vault_id != request.shared_vault_id:
        raise bad_request("Bill shared vault cannot be changed.")
    require_shared_vault(
        request.shared_vault_id,
        vault_id
    )
    if request.category_id is not None:
        require_category(
            request.category_id,
            request.shared_vault_id
        )
    try:
        update_shared_bill(
            bill_id,
            request.name,
            request.amount,
            request.due_day,
            category_id=request.category_id,
            notes=request.notes,
            frequency=request.frequency,
            start_date=request.start_date,
            end_date=request.end_date,
            is_active=request.is_active
        )
    except ValueError as error:
        raise bad_request(str(error)) from error
    return SuccessResponse()


@router.post("/bills/{bill_id}/cancel", response_model=SuccessResponse, response_model_by_alias=True)
def cancel_shared_bill_route(bill_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    require_shared_bill(
        bill_id,
        int_vault_id(vault)
    )
    cancel_shared_bill(bill_id)
    return SuccessResponse()


@router.post("/bills/{bill_id}/duplicate", response_model=SuccessResponse, response_model_by_alias=True)
def duplicate_shared_bill_route(bill_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    require_shared_bill(
        bill_id,
        int_vault_id(vault)
    )
    duplicate_shared_bill(bill_id)
    return SuccessResponse()


@router.post("/bills/instances/{instance_id}/skip", response_model=SuccessResponse, response_model_by_alias=True)
def skip_shared_bill_instance_route(instance_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    require_shared_bill_instance(
        instance_id,
        int_vault_id(vault)
    )
    skip_bill_instance(instance_id)
    return SuccessResponse()


@router.post("/bills/instances/{instance_id}/paid", response_model=SuccessResponse, response_model_by_alias=True)
def mark_shared_bill_paid_route(
    instance_id: int,
    request: SharedBillPaymentRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    require_shared_bill_instance(
        instance_id,
        vault_id
    )
    if vault.vault_type == "Individual" and request.payer_vault_id != vault_id:
        raise bad_request("Payer must match the authenticated vault.")
    selected_id = shared_vault_id_for_instance(instance_id)
    require_shared_participant(
        request.payer_vault_id,
        selected_id
    )
    try:
        mark_bill_paid(
            instance_id,
            request.payer_vault_id,
            request.payment_date,
            notes=request.notes
        )
    except ValueError as error:
        raise bad_request(str(error)) from error
    return SuccessResponse()


@router.post("/settlements", response_model=SuccessResponse, response_model_by_alias=True)
def mark_shared_settlement_route(
    request: SharedSettlementRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    require_shared_vault(
        request.shared_vault_id,
        vault_id
    )
    require_shared_participant(
        request.from_vault_id,
        request.shared_vault_id
    )
    require_shared_participant(
        request.to_vault_id,
        request.shared_vault_id
    )
    try:
        settle_outstanding_settlement(
            request.shared_vault_id,
            request.from_vault_id,
            request.from_account_id,
            request.to_vault_id,
            request.to_account_id,
            request.amount,
            request.settlement_date
        )
    except ValueError as error:
        raise bad_request(str(error)) from error
    return SuccessResponse()


@router.post("/bills/cycles/{cycle_id}/close", response_model=SuccessResponse, response_model_by_alias=True)
def close_shared_bill_cycle_route(cycle_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    require_shared_bill_cycle(
        cycle_id,
        int_vault_id(vault)
    )
    try:
        close_cycle(cycle_id)
    except ValueError as error:
        raise bad_request(str(error)) from error
    return SuccessResponse()

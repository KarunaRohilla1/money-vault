from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_authenticated_vault
from api.resources import (
    bad_request,
    int_vault_id,
    require_account,
    require_category,
    require_shared_participant,
    require_shared_vault,
    require_transaction
)
from api.schemas import (
    SuccessResponse,
    TransactionCreateRequest,
    TransactionDetailResponse,
    TransactionHistoryItemResponse,
    TransactionHistoryResponse,
    TransactionHistorySectionResponse,
    TransactionMonthRangeResponse,
    TransactionResponse,
    TransactionUpdateRequest,
    VaultContext
)
from db.transactions import (
    add_transaction,
    delete_transaction,
    get_filtered_transactions,
    get_transaction_history,
    get_transaction_month_range,
    get_transaction_by_id,
    update_transaction
)
from db.vaults import get_shared_vault_participants


router = APIRouter(prefix="/api/transactions", tags=["transactions"])


def transaction_origin_vault_id(vault):
    if vault.vault_type == "Shared" and vault.authenticated_vault_id:
        return int(vault.authenticated_vault_id)
    return int_vault_id(vault)


def normalize_allocation_keys(allocations):
    if not allocations:
        return allocations

    return {
        int(participant_vault_id): value
        for participant_vault_id, value in allocations.items()
    }


def participant_rows_for_request(participant_vault_ids, beneficiary_vault_id):
    if not participant_vault_ids:
        return []

    participant_map = {
        int(participant[0]): participant
        for participant in get_shared_vault_participants(beneficiary_vault_id)
    }

    return [
        participant_map.get(int(participant_vault_id), (int(participant_vault_id), ""))
        for participant_vault_id in participant_vault_ids
    ]


def validate_shared_transaction_request(request, vault, origin_vault_id):
    active_vault_id = int_vault_id(vault)
    beneficiary_vault_id = request.beneficiary_vault_id or active_vault_id

    if vault.vault_type == "Shared":
        if int(beneficiary_vault_id) != active_vault_id:
            raise bad_request("Shared vault transactions must use the active shared vault.")
    elif int(beneficiary_vault_id) == origin_vault_id:
        return beneficiary_vault_id

    require_shared_vault(
        beneficiary_vault_id,
        origin_vault_id
    )

    for participant_vault_id in request.participant_vaults or []:
        require_shared_participant(
            participant_vault_id,
            beneficiary_vault_id
        )

    if origin_vault_id not in (request.participant_vaults or []):
        raise bad_request("Shared transactions must include the authenticated vault as a participant.")

    return beneficiary_vault_id




def parse_history_date(value):
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def history_label(value):
    transaction_date = parse_history_date(value)
    today = date.today()
    if transaction_date == today:
        return f"Today, {transaction_date.day} {transaction_date.strftime('%b')}"
    if transaction_date == today - timedelta(days=1):
        return f"Yesterday, {transaction_date.day} {transaction_date.strftime('%b')}"
    return f"{transaction_date.day} {transaction_date.strftime('%b')}"


def money_summary(prefix, amount):
    if amount <= 0:
        return ""
    return f"{prefix} {amount:,.0f}"


def row_value(row, index, default=None):
    try:
        return row[index]
    except IndexError:
        return default


def transaction_kind(transaction_type):
    normalized = str(transaction_type or "").strip().lower()
    if normalized == "income":
        return "income"
    if normalized in ("transfer in", "transfer out"):
        return "transfer"
    return "expense"


def transaction_direction(transaction_type):
    kind = transaction_kind(transaction_type)
    if kind == "income":
        return "credit"
    if kind == "expense":
        return "debit"
    return "neutral"


def transaction_title(row):
    notes = str(row_value(row, 7, "") or "").strip()
    category = str(row_value(row, 3, "") or "").strip()
    transaction_type = str(row_value(row, 6, "") or "").strip()
    return notes or category or transaction_type or "Transaction"


def adapt_history_regular_item(row):
    transaction_type = str(row_value(row, 6, "Expense") or "Expense")
    kind = transaction_kind(transaction_type)
    return TransactionHistoryItemResponse(
        id=str(row_value(row, 0)),
        transactionId=int(row_value(row, 0)),
        type=kind,
        transactionType=transaction_type,
        title=transaction_title(row),
        merchant=str(row_value(row, 7, "") or "") or None,
        category=str(row_value(row, 3, transaction_type) or transaction_type),
        categoryIcon=str(row_value(row, 4, "") or ""),
        account=row_value(row, 2),
        amount=float(row_value(row, 5, 0) or 0),
        direction=transaction_direction(transaction_type),
        date=str(row_value(row, 1)),
        time=None,
        runningBalance=float(row_value(row, 9, 0)) if row_value(row, 9) is not None else None,
        shared=bool(row_value(row, 10)),
        sharedVaultName=row_value(row, 10),
        transferGroupId=row_value(row, 8),
        transferMetadata=None
    )


def adapt_history_transfer_item(rows):
    transfer_out = next((row for row in rows if row_value(row, 6) == "Transfer Out"), rows[0])
    transfer_in = next((row for row in rows if row_value(row, 6) == "Transfer In"), rows[-1])
    group_id = row_value(transfer_out, 8) or row_value(transfer_in, 8)
    amount = float(row_value(transfer_out, 5, row_value(transfer_in, 5, 0)) or 0)
    from_account = row_value(transfer_out, 2)
    to_account = row_value(transfer_in, 2)
    title = f"From {from_account}" if from_account else "Transfer"
    return TransactionHistoryItemResponse(
        id=str(group_id),
        transactionId=int(row_value(transfer_out, 0)),
        type="transfer",
        transactionType="Transfer",
        title=title,
        merchant=None,
        category="Transfer",
        categoryIcon="",
        account=to_account or from_account,
        amount=amount,
        direction="neutral",
        date=str(row_value(transfer_out, 1, row_value(transfer_in, 1))),
        time=None,
        runningBalance=float(row_value(transfer_in, 9, 0)) if row_value(transfer_in, 9) is not None else None,
        shared=False,
        sharedVaultName=None,
        transferGroupId=str(group_id),
        transferMetadata={
            "fromAccount": from_account,
            "toAccount": to_account,
            "fromRunningBalance": float(row_value(transfer_out, 9, 0)) if row_value(transfer_out, 9) is not None else None,
            "toRunningBalance": float(row_value(transfer_in, 9, 0)) if row_value(transfer_in, 9) is not None else None
        }
    )


def adapt_history_items(rows):
    items = []
    transfer_groups = OrderedDict()
    for row in rows:
        transfer_group_id = row_value(row, 8)
        if transfer_group_id and row_value(row, 6) in ("Transfer In", "Transfer Out"):
            transfer_groups.setdefault(transfer_group_id, []).append(row)
            continue
        items.append(adapt_history_regular_item(row))

    for group_rows in transfer_groups.values():
        items.append(adapt_history_transfer_item(group_rows))

    return sorted(items, key=lambda item: (item.date, item.transaction_id or 0), reverse=True)


def group_history_sections(items):
    grouped = OrderedDict()
    for item in items:
        grouped.setdefault(item.date, []).append(item)

    sections = []
    for section_date, section_items in grouped.items():
        spent = sum(item.amount for item in section_items if item.direction == "debit")
        received = sum(item.amount for item in section_items if item.direction == "credit")
        summary = money_summary("Received", received) or money_summary("Spent", spent)
        if spent > 0 and received > 0:
            summary = f"{money_summary('Spent', spent)} / {money_summary('Received', received)}"
        sections.append(
            TransactionHistorySectionResponse(
                date=section_date,
                label=history_label(section_date),
                summary=summary,
                spent=spent,
                received=received,
                transactions=section_items
            )
        )
    return sections


def build_transaction_history_response(rows, month):
    items = adapt_history_items(rows)
    return TransactionHistoryResponse(
        month=month,
        transactionCount=len(items),
        sections=group_history_sections(items)
    )

def adapt_transaction(row):
    return TransactionResponse(
        id=int(row[0]),
        date=str(row[1]),
        accountName=row[2],
        categoryName=row[3],
        amount=float(row[4] or 0),
        transactionType=row[5],
        notes=row[6],
        transferGroupId=row[7]
    )


def adapt_transaction_detail(row):
    return TransactionDetailResponse(
        id=int(row[0]),
        accountId=int(row[1]),
        categoryId=int(row[2]),
        date=str(row[3]),
        amount=float(row[4] or 0),
        transactionType=row[5],
        notes=row[6],
        beneficiaryVaultId=int(row[7]) if row[7] is not None else None,
        allocationMethod=row[8],
        accountName=row_value(row, 9),
        categoryName=row_value(row, 10),
        categoryIcon=row_value(row, 11),
        shared=bool(row_value(row, 12)),
        sharedVaultName=row_value(row, 12),
        transferGroupId=row_value(row, 13),
        createdAt=None,
        updatedAt=None
    )


@router.get("", response_model=TransactionHistoryResponse, response_model_by_alias=True)
def list_transactions(
    account: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = Query(default=None, alias="dateFrom"),
    date_to: Optional[str] = Query(default=None, alias="dateTo"),
    month: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = Query(default="Newest", alias="sortBy"),
    transaction_type: str = Query(default="All", alias="transactionType"),
    shared_only: bool = Query(default=False, alias="sharedOnly"),
    amount_min: Optional[float] = Query(default=None, alias="amountMin"),
    amount_max: Optional[float] = Query(default=None, alias="amountMax"),
    vault: VaultContext = Depends(get_authenticated_vault)
):
    rows = get_transaction_history(
        int_vault_id(vault),
        month=month,
        category=category,
        account=account,
        search=search,
        transaction_type=transaction_type,
        sort_by=sort_by,
        date_from=date_from,
        date_to=date_to,
        shared_only=shared_only,
        amount_min=amount_min,
        amount_max=amount_max
    )
    return build_transaction_history_response(rows, month)


@router.get("/month-range", response_model=TransactionMonthRangeResponse, response_model_by_alias=True)
def transaction_month_range(vault: VaultContext = Depends(get_authenticated_vault)):
    row = get_transaction_month_range(int_vault_id(vault))
    return TransactionMonthRangeResponse(
        oldestMonth=str(row[0]),
        latestMonth=str(row[1])
    )


@router.get("/{transaction_id}", response_model=TransactionDetailResponse, response_model_by_alias=True)
def transaction_detail(transaction_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    require_transaction(
        transaction_id,
        int_vault_id(vault)
    )
    return adapt_transaction_detail(get_transaction_by_id(transaction_id))


@router.post("", response_model=TransactionDetailResponse, response_model_by_alias=True)
def create_transaction(
    request: TransactionCreateRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = transaction_origin_vault_id(vault)
    beneficiary_vault_id = validate_shared_transaction_request(
        request,
        vault,
        vault_id
    )
    require_account(
        request.account_id,
        vault_id
    )
    require_category(
        request.category_id,
        vault_id
    )

    participant_vaults = participant_rows_for_request(
        request.participant_vaults,
        beneficiary_vault_id
    )

    try:
        transaction_id = add_transaction(
            vault_id,
            request.account_id,
            request.date,
            request.amount,
            request.category_id,
            request.transaction_type,
            request.notes,
            beneficiary_vault_id=beneficiary_vault_id,
            allocation_method=request.allocation_method,
            participant_vaults=participant_vaults,
            percentage_allocations=normalize_allocation_keys(request.percentage_allocations),
            amount_allocations=normalize_allocation_keys(request.amount_allocations)
        )
    except ValueError as error:
        raise bad_request(str(error)) from error

    return adapt_transaction_detail(get_transaction_by_id(transaction_id))


@router.put("/{transaction_id}", response_model=TransactionDetailResponse, response_model_by_alias=True)
def update_transaction_route(
    transaction_id: int,
    request: TransactionUpdateRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = transaction_origin_vault_id(vault)
    require_transaction(
        transaction_id,
        vault_id
    )
    require_account(
        request.account_id,
        vault_id
    )
    require_category(
        request.category_id,
        vault_id
    )
    beneficiary_vault_id = validate_shared_transaction_request(
        request,
        vault,
        vault_id
    )

    participant_vaults = participant_rows_for_request(
        request.participant_vaults,
        beneficiary_vault_id
    )

    try:
        update_transaction(
            transaction_id,
            request.account_id,
            request.category_id,
            request.date,
            request.amount,
            request.notes,
            transaction_type=request.transaction_type,
            vault_id=vault_id,
            beneficiary_vault_id=beneficiary_vault_id,
            allocation_method=request.allocation_method,
            participant_vaults=participant_vaults,
            percentage_allocations=normalize_allocation_keys(request.percentage_allocations),
            amount_allocations=normalize_allocation_keys(request.amount_allocations)
        )
    except ValueError as error:
        raise bad_request(str(error)) from error

    return adapt_transaction_detail(get_transaction_by_id(transaction_id))


@router.delete("/{transaction_id}", response_model=SuccessResponse, response_model_by_alias=True)
def delete_transaction_route(transaction_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    require_transaction(
        transaction_id,
        int_vault_id(vault)
    )
    delete_transaction(transaction_id)
    return SuccessResponse()

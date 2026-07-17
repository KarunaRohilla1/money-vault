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
    TransactionResponse,
    TransactionUpdateRequest,
    VaultContext
)
from db.transactions import (
    add_transaction,
    delete_transaction,
    get_filtered_transactions,
    get_transaction_by_id,
    update_transaction
)


router = APIRouter(prefix="/api/transactions", tags=["transactions"])


def validate_shared_transaction_request(request, vault_id):
    beneficiary_vault_id = request.beneficiary_vault_id or vault_id
    if int(beneficiary_vault_id) == int(vault_id):
        return beneficiary_vault_id

    require_shared_vault(
        beneficiary_vault_id,
        vault_id
    )

    for participant_vault_id in request.participant_vaults or []:
        require_shared_participant(
            participant_vault_id,
            beneficiary_vault_id
        )

    if vault_id not in (request.participant_vaults or []):
        raise bad_request("Shared transactions must include the authenticated vault as a participant.")

    return beneficiary_vault_id


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
        allocationMethod=row[8]
    )


@router.get("", response_model=list[TransactionResponse], response_model_by_alias=True)
def list_transactions(
    account: Optional[str] = None,
    category: Optional[str] = None,
    date_from: Optional[str] = Query(default=None, alias="dateFrom"),
    date_to: Optional[str] = Query(default=None, alias="dateTo"),
    month: Optional[str] = None,
    search: Optional[str] = None,
    sort_by: str = Query(default="Newest", alias="sortBy"),
    vault: VaultContext = Depends(get_authenticated_vault)
):
    return [
        adapt_transaction(row)
        for row in get_filtered_transactions(
            int_vault_id(vault),
            month=month,
            category=category,
            account=account,
            search=search,
            sort_by=sort_by,
            date_from=date_from,
            date_to=date_to
        )
    ]


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
    vault_id = int_vault_id(vault)
    beneficiary_vault_id = validate_shared_transaction_request(
        request,
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
            participant_vaults=request.participant_vaults,
            percentage_allocations=request.percentage_allocations,
            amount_allocations=request.amount_allocations
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
    vault_id = int_vault_id(vault)
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
        vault_id
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
            participant_vaults=request.participant_vaults,
            percentage_allocations=request.percentage_allocations,
            amount_allocations=request.amount_allocations
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

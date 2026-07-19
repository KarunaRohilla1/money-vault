from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_authenticated_vault
from api.resources import bad_request, int_vault_id, require_account, require_transfer
from api.schemas import (
    SuccessResponse,
    TransferCreateRequest,
    TransferDetailResponse,
    TransferResponse,
    TransferUpdateRequest,
    VaultContext
)
from db.transfers import (
    add_transfer,
    delete_transfer,
    get_transfer_by_group,
    get_transfers,
    TransferPairIntegrityError,
    update_transfer
)


router = APIRouter(prefix="/api/transfers", tags=["transfers"])


def adapt_transfer(row):
    return TransferResponse(
        transferGroupId=row[0],
        date=str(row[1]),
        fromAccountId=int(row[2]),
        fromAccountName=row[3],
        toAccountId=int(row[4]),
        toAccountName=row[5],
        amount=float(row[6] or 0),
        notes=row[7]
    )


def adapt_transfer_detail(row):
    return TransferDetailResponse(
        transferGroupId=row[0],
        vaultId=int(row[1]),
        date=str(row[2]),
        fromAccountId=int(row[3]),
        toAccountId=int(row[4]),
        amount=float(row[5] or 0),
        notes=row[6]
    )


def validate_transfer_request(request, vault_id):
    if request.from_account_id == request.to_account_id:
        raise bad_request("Transfer accounts must be different.")

    require_account(
        request.from_account_id,
        vault_id
    )
    require_account(
        request.to_account_id,
        vault_id
    )


def transfer_pair_conflict():
    from fastapi import HTTPException, status

    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "TRANSFER_PAIR_CORRUPTED",
            "message": "Transfer could not be changed because its paired records are inconsistent."
        }
    )


@router.get("", response_model=list[TransferResponse], response_model_by_alias=True)
def list_transfers(
    account_id: Optional[int] = Query(default=None, alias="accountId"),
    source_account_id: Optional[int] = Query(default=None, alias="sourceAccountId"),
    destination_account_id: Optional[int] = Query(default=None, alias="destinationAccountId"),
    date_from: Optional[date] = Query(default=None, alias="dateFrom"),
    date_to: Optional[date] = Query(default=None, alias="dateTo"),
    limit: Optional[int] = None,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)

    if account_id is not None:
        require_account(account_id, vault_id)

    if source_account_id is not None:
        require_account(source_account_id, vault_id)

    if destination_account_id is not None:
        require_account(destination_account_id, vault_id)

    return [
        adapt_transfer(row)
        for row in get_transfers(
            vault_id,
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
            account_id=account_id,
            source_account_id=source_account_id,
            destination_account_id=destination_account_id,
            limit=limit
        )
    ]


@router.get("/{transfer_group_id}", response_model=TransferDetailResponse, response_model_by_alias=True)
def transfer_detail(transfer_group_id: str, vault: VaultContext = Depends(get_authenticated_vault)):
    require_transfer(
        transfer_group_id,
        int_vault_id(vault)
    )
    return adapt_transfer_detail(get_transfer_by_group(transfer_group_id))


@router.post("", response_model=TransferDetailResponse, response_model_by_alias=True)
def create_transfer(request: TransferCreateRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = int_vault_id(vault)
    validate_transfer_request(
        request,
        vault_id
    )
    try:
        transfer_group_id = add_transfer(
            vault_id,
            request.from_account_id,
            request.to_account_id,
            request.date.isoformat(),
            request.amount,
            request.notes
        )
    except TransferPairIntegrityError as error:
        raise transfer_pair_conflict() from error
    return adapt_transfer_detail(get_transfer_by_group(transfer_group_id))


@router.put("/{transfer_group_id}", response_model=TransferDetailResponse, response_model_by_alias=True)
def update_transfer_route(
    transfer_group_id: str,
    request: TransferUpdateRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    require_transfer(
        transfer_group_id,
        vault_id
    )
    validate_transfer_request(
        request,
        vault_id
    )
    try:
        update_transfer(
            transfer_group_id,
            request.from_account_id,
            request.to_account_id,
            request.date.isoformat(),
            request.amount,
            request.notes
        )
    except TransferPairIntegrityError as error:
        raise transfer_pair_conflict() from error
    return adapt_transfer_detail(get_transfer_by_group(transfer_group_id))


@router.delete("/{transfer_group_id}", response_model=SuccessResponse, response_model_by_alias=True)
def delete_transfer_route(transfer_group_id: str, vault: VaultContext = Depends(get_authenticated_vault)):
    require_transfer(
        transfer_group_id,
        int_vault_id(vault)
    )
    try:
        delete_transfer(transfer_group_id)
    except TransferPairIntegrityError as error:
        raise transfer_pair_conflict() from error
    return SuccessResponse()

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


@router.get("", response_model=list[TransferResponse], response_model_by_alias=True)
def list_transfers(
    account_id: Optional[int] = Query(default=None, alias="accountId"),
    date_from: Optional[date] = Query(default=None, alias="dateFrom"),
    date_to: Optional[date] = Query(default=None, alias="dateTo"),
    limit: Optional[int] = None,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    return [
        adapt_transfer(row)
        for row in get_transfers(
            int_vault_id(vault),
            date_from=date_from.isoformat() if date_from else None,
            date_to=date_to.isoformat() if date_to else None,
            account_id=account_id,
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
    transfer_group_id = add_transfer(
        vault_id,
        request.from_account_id,
        request.to_account_id,
        request.date.isoformat(),
        request.amount,
        request.notes
    )
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
    update_transfer(
        transfer_group_id,
        request.from_account_id,
        request.to_account_id,
        request.date.isoformat(),
        request.amount,
        request.notes
    )
    return adapt_transfer_detail(get_transfer_by_group(transfer_group_id))


@router.delete("/{transfer_group_id}", response_model=SuccessResponse, response_model_by_alias=True)
def delete_transfer_route(transfer_group_id: str, vault: VaultContext = Depends(get_authenticated_vault)):
    require_transfer(
        transfer_group_id,
        int_vault_id(vault)
    )
    delete_transfer(transfer_group_id)
    return SuccessResponse()

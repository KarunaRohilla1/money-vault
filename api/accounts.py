import math

from fastapi import APIRouter, Depends

from api.dependencies import get_authenticated_vault
from api.resources import bad_request, int_vault_id, require_account
from api.schemas import (
    AccountCreateRequest,
    AccountResponse,
    AccountUpdateRequest,
    SuccessResponse,
    VaultContext
)
from db.core import ACCOUNT_TYPES
from db.accounts import (
    account_exists,
    add_account,
    archive_account,
    get_account_by_id,
    get_accounts_with_balances,
    set_primary_account,
    update_account
)


router = APIRouter(prefix="/api/accounts", tags=["accounts"])


def validate_account_payload(request):
    account_type = request.type.strip() if isinstance(request.type, str) else ""

    if not account_type:
        raise bad_request("Account type is required.")

    if account_type not in ACCOUNT_TYPES:
        raise bad_request("Choose a valid account type.")

    if request.opening_balance is None:
        raise bad_request("Opening balance cannot be empty.")

    if not math.isfinite(request.opening_balance):
        raise bad_request("Opening balance must be a number.")

    if request.opening_balance == 0:
        raise bad_request("Opening balance must be greater than zero.")

    if account_type != "Credit Card" and request.opening_balance < 0:
        raise bad_request("Opening balance cannot be negative.")


def effective_account_vault_id(vault):
    if vault.vault_type == "Shared" and vault.authenticated_vault_id:
        return int(vault.authenticated_vault_id)
    return int_vault_id(vault)


def account_exists_for_vault(account_id, vault_id):
    row = get_account_by_id(account_id)
    return bool(row and int(row[5]) == int(vault_id))


def adapt_account(row):
    return AccountResponse(
        id=int(row[0]),
        name=row[1],
        type=row[2],
        openingBalance=float(row[3] or 0),
        isPrimary=bool(row[4]),
        balance=float(row[5]) if len(row) > 5 and row[5] is not None else None
    )


@router.get("", response_model=list[AccountResponse], response_model_by_alias=True)
def list_accounts(vault: VaultContext = Depends(get_authenticated_vault)):
    return [
        adapt_account(row)
        for row in get_accounts_with_balances(effective_account_vault_id(vault))
    ]


@router.get("/{account_id}", response_model=AccountResponse, response_model_by_alias=True)
def account_detail(account_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = effective_account_vault_id(vault)
    require_account(
        account_id,
        vault_id
    )
    row = get_account_by_id(account_id)
    return adapt_account((*row[:5], None))


@router.post("", response_model=SuccessResponse, response_model_by_alias=True)
def create_account(request: AccountCreateRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = int_vault_id(vault)
    validate_account_payload(request)
    if account_exists(
        vault_id,
        request.name
    ):
        raise bad_request("Account already exists.")

    add_account(
        vault_id,
        request.name.strip(),
        request.type.strip(),
        request.opening_balance,
        request.is_primary
    )
    return SuccessResponse()


@router.put("/{account_id}", response_model=AccountResponse, response_model_by_alias=True)
def update_account_route(
    account_id: int,
    request: AccountUpdateRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = effective_account_vault_id(vault)
    require_account(
        account_id,
        vault_id
    )
    validate_account_payload(request)
    if account_exists(
        vault_id,
        request.name,
        exclude_account_id=account_id
    ):
        raise bad_request("Account already exists.")

    update_account(
        account_id,
        request.name.strip(),
        request.type.strip(),
        request.opening_balance,
        request.is_primary
    )
    row = get_account_by_id(account_id)
    return adapt_account((*row[:5], None))


@router.delete("/{account_id}", response_model=SuccessResponse, response_model_by_alias=True)
def delete_account(account_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = int_vault_id(vault)
    if not account_exists_for_vault(
        account_id,
        vault_id
    ):
        require_account(
            account_id,
            vault_id
        )

    archive_account(account_id)
    return SuccessResponse()


@router.post("/{account_id}/primary", response_model=SuccessResponse, response_model_by_alias=True)
def make_primary(account_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    require_account(
        account_id,
        int_vault_id(vault)
    )
    set_primary_account(account_id)
    return SuccessResponse()

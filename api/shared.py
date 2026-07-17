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
    SuccessResponse,
    VaultContext
)
from db.financial_cycles import get_current_cycle
from db.core import get_connection
from db.shared_bills import (
    add_shared_bill,
    cancel_shared_bill,
    close_cycle,
    duplicate_shared_bill,
    get_shared_bills_page_data,
    mark_bill_paid,
    skip_bill_instance,
    update_shared_bill
)
from db.shared_expenses import get_shared_expenses_page_data
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

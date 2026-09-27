from fastapi import APIRouter, Depends

from api.dependencies import get_authenticated_vault
from api.resources import bad_request, int_vault_id
from api.schemas import SettingsResponse, SettingsUpdateRequest, VaultContext, VaultSummaryResponse
from db.identity import MEMBER_ROLE, OWNER_ROLE, get_membership
from db.vaults import (
    get_all_vaults,
    get_connected_shared_vaults,
    get_shared_vault_participants,
    get_vault_by_id,
    get_vault_financial_settings,
    update_vault
)


router = APIRouter(prefix="/api/settings", tags=["settings"])


def adapt_vault(row, user_id=None):
    vault_id = int(row[0])
    vault_type = row[4] if len(row) > 4 else "Individual"
    role = None
    if user_id:
        role = get_membership(user_id, vault_id)
    if not role:
        role = OWNER_ROLE if vault_type == "Individual" else (OWNER_ROLE if bool(row[2]) else MEMBER_ROLE)
    is_admin = (role == OWNER_ROLE)

    return VaultSummaryResponse(
        id=vault_id,
        name=row[1],
        isAdmin=is_admin,
        vaultType=vault_type,
        role=role
    )


def accessible_vaults_for(current_vault):
    vault_id = int(current_vault[0])
    vault_type = current_vault[4]

    if vault_type == "Shared":
        rows = get_shared_vault_participants(vault_id)
        return [
            VaultSummaryResponse(
                id=int(row[0]),
                name=row[1],
                isAdmin=True,
                vaultType="Individual",
                role=OWNER_ROLE
            )
            for row in rows
        ]

    shared_rows = get_connected_shared_vaults(vault_id)
    shared = [
        VaultSummaryResponse(
            id=int(row[0]),
            name=row[1],
            isAdmin=False,
            vaultType="Shared",
            role=MEMBER_ROLE
        )
        for row in shared_rows
    ]
    current = adapt_vault(current_vault)
    return [current, *shared]


@router.get("", response_model=SettingsResponse, response_model_by_alias=True)
def settings(vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = int_vault_id(vault)
    current = get_vault_by_id(vault_id)
    accessible_source = current
    if vault.authenticated_vault_id:
        authenticated = get_vault_by_id(vault.authenticated_vault_id)
        if authenticated:
            accessible_source = authenticated
    financial = get_vault_financial_settings(vault_id)
    return SettingsResponse(
        currentVault=adapt_vault(current, user_id=vault.user_id),
        accessibleVaults=accessible_vaults_for(accessible_source),
        cycleStartDay=int(financial[0] or 1),
        monthlySavingsGoal=float(financial[1] or 0)
    )


@router.patch("", response_model=SettingsResponse, response_model_by_alias=True)
def update_settings(request: SettingsUpdateRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = int_vault_id(vault)
    current = get_vault_by_id(vault_id)
    current_name = current[1]
    next_name = current_name if request.vault_name is None else request.vault_name.strip()

    try:
        vault_type = current[4] if len(current) > 4 else "Individual"
        if vault_type == "Individual":
            next_name = "Personal"

        update_vault(
            vault_id,
            next_name,
            month_start_day=request.cycle_start_day,
            monthly_savings_goal=request.monthly_savings_goal
        )
    except ValueError as exc:
        raise bad_request(str(exc)) from exc

    return settings(vault)


@router.get("/vaults", response_model=list[VaultSummaryResponse], response_model_by_alias=True)
def all_vaults(_vault: VaultContext = Depends(get_authenticated_vault)):
    return [
        adapt_vault(row)
        for row in get_all_vaults()
    ]

from fastapi import APIRouter, Depends

from api.dependencies import get_authenticated_vault
from api.resources import bad_request, int_vault_id
from api.schemas import SettingsResponse, SettingsUpdateRequest, VaultContext, VaultSummaryResponse
from db.vaults import (
    get_all_vaults,
    get_connected_shared_vaults,
    get_shared_vault_participants,
    get_vault_by_id,
    get_vault_financial_settings,
    update_vault
)


router = APIRouter(prefix="/api/settings", tags=["settings"])


def adapt_vault(row):
    return VaultSummaryResponse(
        id=int(row[0]),
        name=row[1],
        isAdmin=bool(row[2]) if len(row) > 2 else False,
        vaultType=row[4] if len(row) > 4 else "Individual"
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
                isAdmin=False,
                vaultType="Individual"
            )
            for row in rows
        ]

    shared_rows = get_connected_shared_vaults(vault_id)
    shared = [
        VaultSummaryResponse(
            id=int(row[0]),
            name=row[1],
            isAdmin=False,
            vaultType="Shared"
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
        currentVault=adapt_vault(current),
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

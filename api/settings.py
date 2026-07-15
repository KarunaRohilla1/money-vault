from fastapi import APIRouter, Depends

from api.dependencies import get_authenticated_vault
from api.resources import int_vault_id
from api.schemas import SettingsResponse, VaultContext, VaultSummaryResponse
from db.vaults import (
    get_all_vaults,
    get_connected_shared_vaults,
    get_shared_vault_participants,
    get_vault_by_id,
    get_vault_financial_settings
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
    financial = get_vault_financial_settings(vault_id)
    return SettingsResponse(
        currentVault=adapt_vault(current),
        accessibleVaults=accessible_vaults_for(current),
        cycleStartDay=int(financial[0] or 1),
        monthlySavingsGoal=float(financial[1] or 0)
    )


@router.get("/vaults", response_model=list[VaultSummaryResponse], response_model_by_alias=True)
def all_vaults(_vault: VaultContext = Depends(get_authenticated_vault)):
    return [
        adapt_vault(row)
        for row in get_all_vaults()
    ]

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_authenticated_vault
from api.schemas import (
    LoginRequest,
    LoginResponse,
    SessionResponse,
    SharedVaultActivationRequest,
    VaultContext,
    VaultSummaryResponse
)
from api.security import create_access_token
from db.vaults import get_connected_shared_vaults, get_vault_by_id, verify_pin


INVALID_CREDENTIALS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail={
        "code": "INVALID_CREDENTIALS",
        "message": "Invalid vault credentials."
    }
)

router = APIRouter(prefix="/api", tags=["auth"])


@dataclass(frozen=True)
class AuthenticatedVault:
    id: str
    name: str
    is_admin: bool
    vault_type: str


def authenticate_vault(vault_name, pin):
    verified = verify_pin(vault_name, pin)
    if not verified:
        raise INVALID_CREDENTIALS

    vault_id = verified[0]
    vault_details = get_vault_by_id(vault_id)
    if not vault_details:
        raise INVALID_CREDENTIALS

    return AuthenticatedVault(
        id=str(vault_details[0]),
        name=str(vault_details[1]),
        is_admin=bool(vault_details[2]),
        vault_type=str(vault_details[4] if len(vault_details) > 4 else "Individual")
    )


def vault_from_row(row):
    if not row:
        return None

    return AuthenticatedVault(
        id=str(row[0]),
        name=str(row[1]),
        is_admin=bool(row[2]),
        vault_type=str(row[4] if len(row) > 4 else "Individual")
    )


def vault_context(vault, authenticated_vault=None, include_authenticated=False):
    authenticated = authenticated_vault or vault
    payload = {
        "id": vault.id,
        "name": vault.name,
        "isAdmin": vault.is_admin,
        "vaultType": vault.vault_type
    }

    if include_authenticated:
        payload.update({
            "authenticatedVaultId": authenticated.id,
            "authenticatedVaultName": authenticated.name,
            "authenticatedVaultType": authenticated.vault_type
        })

    return VaultContext(**payload)


def vault_summary(vault):
    return VaultSummaryResponse(
        id=int(vault.id),
        name=vault.name,
        isAdmin=vault.is_admin,
        vaultType=vault.vault_type
    )


def authenticated_personal_vault(active_context):
    authenticated_id = active_context.authenticated_vault_id or active_context.id
    row = get_vault_by_id(authenticated_id)
    authenticated = vault_from_row(row)

    if not authenticated or authenticated.vault_type != "Individual":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "PERSONAL_VAULT_REQUIRED",
                "message": "A personal vault session is required."
            }
        )

    return authenticated


def active_vault_from_context(active_context):
    row = get_vault_by_id(active_context.id)
    active = vault_from_row(row)

    if not active:
        raise INVALID_CREDENTIALS

    return active


def connected_shared_vaults_for(personal_vault):
    rows = get_connected_shared_vaults(personal_vault.id)
    return [
        vault_from_row(get_vault_by_id(row[0]))
        for row in rows
    ]


def visible_connected_shared_vaults(personal_vault):
    return [
        vault
        for vault in connected_shared_vaults_for(personal_vault)
        if vault is not None and vault.vault_type == "Shared"
    ]


def session_response(active, authenticated):
    shared_vaults = visible_connected_shared_vaults(authenticated)
    return SessionResponse(
        vault=vault_context(active, authenticated),
        authenticatedVault=vault_context(authenticated, authenticated),
        accessibleVaults=[
            vault_summary(authenticated),
            *[
                vault_summary(vault)
                for vault in shared_vaults
            ]
        ]
    )


def forbidden_shared_vault():
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "SHARED_VAULT_FORBIDDEN",
            "message": "Shared vault is not connected to this personal vault."
        }
    )


@router.post("/login", response_model=LoginResponse, response_model_by_alias=True, response_model_exclude_none=True)
def login(request: LoginRequest):
    vault = authenticate_vault(
        request.vault_name,
        request.pin
    )
    authenticated = vault if vault.vault_type == "Individual" else vault
    token, expires_at = create_access_token(vault, authenticated)

    return LoginResponse(
        token=token,
        expiresAt=expires_at.isoformat(),
        vault=vault_context(vault, authenticated),
        authenticatedVault=vault_context(authenticated, authenticated)
    )


@router.get("/session", response_model=SessionResponse, response_model_by_alias=True, response_model_exclude_none=True)
def session(vault: VaultContext = Depends(get_authenticated_vault)):
    active = active_vault_from_context(vault)
    authenticated = authenticated_personal_vault(vault)

    if active.id != authenticated.id:
        allowed_ids = {
            connected.id
            for connected in visible_connected_shared_vaults(authenticated)
        }
        if active.id not in allowed_ids:
            raise forbidden_shared_vault()

    return session_response(active, authenticated)


@router.get("/vaults/shared", response_model=list[VaultSummaryResponse], response_model_by_alias=True)
def shared_vaults(vault: VaultContext = Depends(get_authenticated_vault)):
    authenticated = authenticated_personal_vault(vault)
    return [
        vault_summary(shared_vault)
        for shared_vault in visible_connected_shared_vaults(authenticated)
    ]


@router.post("/vaults/shared/activate", response_model=LoginResponse, response_model_by_alias=True, response_model_exclude_none=True)
def activate_shared_vault(
    request: SharedVaultActivationRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    authenticated = authenticated_personal_vault(vault)
    connected = {
        shared_vault.id: shared_vault
        for shared_vault in visible_connected_shared_vaults(authenticated)
    }
    target = connected.get(str(request.shared_vault_id))

    if not target:
        raise forbidden_shared_vault()

    if request.pin:
        verified = verify_pin(
            target.name,
            request.pin
        )

        if not verified or int(verified[0]) != int(target.id):
            raise INVALID_CREDENTIALS

    token, expires_at = create_access_token(target, authenticated)
    return LoginResponse(
        token=token,
        expiresAt=expires_at.isoformat(),
        vault=vault_context(target, authenticated),
        authenticatedVault=vault_context(authenticated, authenticated)
    )


@router.post("/vaults/personal/activate", response_model=LoginResponse, response_model_by_alias=True, response_model_exclude_none=True)
def activate_personal_vault(vault: VaultContext = Depends(get_authenticated_vault)):
    authenticated = authenticated_personal_vault(vault)
    token, expires_at = create_access_token(authenticated, authenticated)
    return LoginResponse(
        token=token,
        expiresAt=expires_at.isoformat(),
        vault=vault_context(authenticated, authenticated),
        authenticatedVault=vault_context(authenticated, authenticated)
    )

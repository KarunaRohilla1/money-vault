from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, status

from api.schemas import LoginRequest, LoginResponse, VaultContext
from api.security import create_access_token
from db.vaults import get_vault_by_id, verify_pin


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


@router.post("/login", response_model=LoginResponse, response_model_by_alias=True)
def login(request: LoginRequest):
    vault = authenticate_vault(
        request.vault_name,
        request.pin
    )
    token, expires_at = create_access_token(vault)

    return LoginResponse(
        token=token,
        expiresAt=expires_at.isoformat(),
        vault=VaultContext(
            id=vault.id,
            name=vault.name,
            isAdmin=vault.is_admin,
            vaultType=vault.vault_type
        )
    )

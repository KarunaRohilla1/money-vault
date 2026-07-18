from datetime import datetime, timedelta, timezone

import jwt

from api.config import get_config
from api.schemas import VaultContext


JWT_ALGORITHM = "HS256"


class AuthError(Exception):
    pass


class ExpiredAuthError(AuthError):
    pass


def create_access_token(vault, authenticated_vault=None):
    config = get_config()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=config.jwt_expiry_days)
    authenticated = authenticated_vault or vault

    payload = {
        "sub": str(authenticated.id),
        "authenticated_vault_name": authenticated.name,
        "authenticated_vault_type": authenticated.vault_type,
        "authenticated_is_admin": authenticated.is_admin,
        "active_vault_id": str(vault.id),
        "active_vault_name": vault.name,
        "active_vault_type": vault.vault_type,
        "active_is_admin": vault.is_admin,
        "vault_name": vault.name,
        "vault_type": vault.vault_type,
        "is_admin": vault.is_admin,
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }

    token = jwt.encode(
        payload,
        config.jwt_secret,
        algorithm=JWT_ALGORITHM
    )

    return token, expires_at


def verify_access_token(token):
    config = get_config()

    try:
        payload = jwt.decode(
            token,
            config.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            options={"require": ["sub", "exp", "iat"]}
        )
    except jwt.ExpiredSignatureError as error:
        raise ExpiredAuthError() from error
    except jwt.InvalidTokenError as error:
        raise AuthError() from error

    try:
        authenticated_vault_id = str(payload["sub"])
        return VaultContext(
            id=str(payload.get("active_vault_id", payload["sub"])),
            name=str(payload.get("active_vault_name", payload["vault_name"])),
            isAdmin=bool(payload.get("active_is_admin", payload["is_admin"])),
            vaultType=str(payload.get("active_vault_type", payload["vault_type"])),
            authenticatedVaultId=authenticated_vault_id,
            authenticatedVaultName=str(payload.get("authenticated_vault_name", payload["vault_name"])),
            authenticatedVaultType=str(payload.get("authenticated_vault_type", payload["vault_type"]))
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AuthError() from error

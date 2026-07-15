from datetime import datetime, timedelta, timezone

import jwt

from api.config import get_config
from api.schemas import VaultContext


JWT_ALGORITHM = "HS256"


class AuthError(Exception):
    pass


class ExpiredAuthError(AuthError):
    pass


def create_access_token(vault):
    config = get_config()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=config.jwt_expiry_days)

    payload = {
        "sub": str(vault.id),
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
        return VaultContext(
            id=str(payload["sub"]),
            name=str(payload["vault_name"]),
            isAdmin=bool(payload["is_admin"]),
            vaultType=str(payload["vault_type"])
        )
    except (KeyError, TypeError, ValueError) as error:
        raise AuthError() from error

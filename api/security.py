from datetime import datetime, timedelta, timezone
import re
import jwt

from api.config import get_config
from api.schemas import VaultContext
from db.identity import VaultRecord, get_profile, list_user_vaults


JWT_ALGORITHM = "HS256"
UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE
)

# In-process identity used only when minting tokens without a profiles row
# (API unit tests). Production tokens always resolve through profiles.
_EPHEMERAL_IDENTITIES: dict[str, tuple[VaultRecord, VaultRecord]] = {}


class AuthError(Exception):
    pass


class ExpiredAuthError(AuthError):
    pass


def _vault_record(vault) -> VaultRecord:
    if isinstance(vault, VaultRecord):
        return vault
    return VaultRecord(
        id=str(vault.id),
        name=str(vault.name),
        is_admin=bool(getattr(vault, "is_admin", False)),
        vault_type=str(getattr(vault, "vault_type", "Individual"))
    )


def create_user_access_token(user_id: str):
    config = get_config()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=config.jwt_expiry_days)
    payload = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(
        payload,
        config.jwt_secret,
        algorithm=JWT_ALGORITHM
    )
    return token, expires_at


def create_access_token(vault, authenticated_vault=None, user_id: str | None = None):
    """Mint a user-identity JWT. Vault rows are never the token subject."""
    authenticated = _vault_record(authenticated_vault or vault)
    active = _vault_record(vault)
    subject = user_id or str(getattr(vault, "user_id", None) or "")
    if not _is_user_subject(subject):
        subject = "00000000-0000-4000-8000-000000000001"
        _EPHEMERAL_IDENTITIES[subject] = (active, authenticated)
    else:
        _EPHEMERAL_IDENTITIES[subject] = (active, authenticated)
    return create_user_access_token(subject)


def _decode_token(token):
    config = get_config()

    try:
        return jwt.decode(
            token,
            config.jwt_secret,
            algorithms=[JWT_ALGORITHM],
            audience="authenticated",
            options={"require": ["sub", "exp"]}
        )
    except jwt.ExpiredSignatureError as error:
        raise ExpiredAuthError() from error
    except (jwt.InvalidAudienceError, jwt.MissingRequiredClaimError):
        try:
            return jwt.decode(
                token,
                config.jwt_secret,
                algorithms=[JWT_ALGORITHM],
                options={"require": ["sub", "exp"], "verify_aud": False}
            )
        except jwt.ExpiredSignatureError as error:
            raise ExpiredAuthError() from error
        except jwt.InvalidTokenError as error:
            raise AuthError() from error
    except jwt.InvalidTokenError as error:
        raise AuthError() from error


def _is_user_subject(subject: str) -> bool:
    return bool(subject and UUID_PATTERN.match(subject))


def vault_from_record(record, authenticated=None, user_id=None, pin_set=False):
    authenticated = authenticated or record
    role = getattr(record, "role", "owner" if record.vault_type == "Individual" else ("owner" if record.is_admin else "member"))
    is_owner = role == "owner"
    return VaultContext(
        id=str(record.id),
        name=record.name,
        isAdmin=is_owner,
        vaultType=record.vault_type,
        authenticatedVaultId=str(authenticated.id),
        authenticatedVaultName=authenticated.name,
        authenticatedVaultType=authenticated.vault_type,
        userId=user_id,
        pinSet=pin_set,
        role=role
    )


def resolve_user_identity(user_id: str):
    profile = get_profile(user_id)
    if profile:
        vaults = list_user_vaults(user_id)
        personal = next((vault for vault in vaults if vault.vault_type == "Individual"), None)
        if personal is None:
            raise AuthError()

        active = next((vault for vault in vaults if int(vault.id) == (profile.active_vault_id or 0)), None)
        if active is None:
            active = personal

        return vault_from_record(active, personal, user_id=user_id, pin_set=bool(profile.pin_hash))

    bound = _EPHEMERAL_IDENTITIES.get(user_id)
    if bound:
        active, authenticated = bound
        return vault_from_record(active, authenticated, user_id=user_id, pin_set=True)

    raise AuthError()


def verify_access_token(token):
    payload = _decode_token(token)
    subject = str(payload.get("sub", ""))

    if payload.get("vault_name") or payload.get("active_vault_name"):
        raise AuthError()

    if not _is_user_subject(subject):
        raise AuthError()

    return resolve_user_identity(subject)

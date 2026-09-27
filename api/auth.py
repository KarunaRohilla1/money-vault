from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.dependencies import get_authenticated_vault
from api.resources import bad_request
from api.schemas import (
    CreateSharedVaultRequest,
    JoinSharedVaultRequest,
    LoginRequest,
    LoginResponse,
    PinChangeRequest,
    PinSetRequest,
    ProfileUpdateRequest,
    RecoverPinRequest,
    RecoveryCodeResponse,
    RegisterRequest,
    SessionResponse,
    SharedVaultActivationRequest,
    SharedVaultDetailResponse,
    SharedVaultMemberResponse,
    SharedVaultRenameRequest,
    SharedVaultSummaryResponse,
    VaultContext,
    VaultSummaryResponse
)
from api.security import create_access_token, create_user_access_token
from db.identity import (
    MEMBER_ROLE,
    OWNER_ROLE,
    IdentityError,
    add_vault_member,
    authenticate_user,
    change_profile_pin,
    create_shared_vault_for_user,
    delete_shared_vault_for_user,
    get_membership,
    get_personal_vault,
    get_profile,
    invite_code_for_shared_vault,
    issue_recovery_code,
    join_shared_vault_for_user,
    leave_shared_vault_for_user,
    list_shared_memberships_for_user,
    list_shared_vault_members,
    recover_pin_with_recovery_code,
    register_user,
    remove_shared_vault_member,
    rename_shared_vault_for_user,
    require_shared_membership,
    set_active_vault,
    set_profile_pin,
    update_display_name
)
from db.vaults import get_connected_shared_vaults, get_vault_by_id


bearer_scheme = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/api", tags=["auth"])


@dataclass(frozen=True)
class AuthenticatedVault:
    id: str
    name: str
    is_admin: bool
    vault_type: str
    role: str = "member"


def vault_from_row(row, user_id=None):
    if not row:
        return None

    role = str(row[5]) if len(row) > 5 and row[5] is not None else None
    if not role and user_id:
        role = get_membership(user_id, int(row[0]))
    if not role:
        role = OWNER_ROLE if (len(row) > 4 and row[4] == "Individual") else (OWNER_ROLE if bool(row[2]) else MEMBER_ROLE)

    return AuthenticatedVault(
        id=str(row[0]),
        name=str(row[1]),
        is_admin=role == OWNER_ROLE,
        vault_type=str(row[4] if len(row) > 4 else "Individual"),
        role=role
    )


def vault_context(vault, authenticated_vault=None, include_authenticated=False, user_id=None, pin_set=None, role=None):
    authenticated = authenticated_vault or vault
    vault_role = role or getattr(vault, "role", OWNER_ROLE if getattr(vault, "vault_type", "Individual") == "Individual" else MEMBER_ROLE)
    payload = {
        "id": vault.id,
        "name": vault.name,
        "isAdmin": vault_role == OWNER_ROLE,
        "vaultType": vault.vault_type,
        "role": vault_role
    }

    if include_authenticated:
        payload.update({
            "authenticatedVaultId": authenticated.id,
            "authenticatedVaultName": authenticated.name,
            "authenticatedVaultType": authenticated.vault_type
        })

    if user_id:
        payload["userId"] = user_id
    if pin_set is not None:
        payload["pinSet"] = pin_set

    return VaultContext(**payload)


def vault_summary(vault):
    role = getattr(vault, "role", OWNER_ROLE if getattr(vault, "vault_type", "Individual") == "Individual" else MEMBER_ROLE)
    return VaultSummaryResponse(
        id=int(vault.id),
        name=vault.name,
        isAdmin=role == OWNER_ROLE,
        vaultType=vault.vault_type,
        role=role
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Invalid vault credentials."
            }
        )

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


def identity_fields(vault: VaultContext):
    if not vault.user_id:
        return {}

    profile = get_profile(vault.user_id)
    return {
        "displayName": profile.display_name if profile else None,
        "pinSet": bool(profile.pin_hash) if profile else bool(vault.pin_set),
        "userId": vault.user_id
    }


def session_response(active, authenticated, extra=None):
    shared_vaults = visible_connected_shared_vaults(authenticated)
    payload = {
        "vault": vault_context(active, authenticated),
        "authenticatedVault": vault_context(authenticated, authenticated),
        "accessibleVaults": [
            vault_summary(authenticated),
            *[
                vault_summary(vault)
                for vault in shared_vaults
            ]
        ]
    }
    if extra:
        payload.update({key: value for key, value in extra.items() if value is not None})
    return SessionResponse(**payload)


def forbidden_shared_vault():
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail={
            "code": "SHARED_VAULT_FORBIDDEN",
            "message": "Shared vault is not connected to this personal vault."
        }
    )


def require_user_id(vault: VaultContext):
    if not vault.user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "AUTHENTICATION_REQUIRED",
                "message": "A signed-in user is required."
            }
        )
    return vault.user_id


def echo_token(credentials: HTTPAuthorizationCredentials | None, vault, authenticated):
    if credentials and credentials.credentials:
        return credentials.credentials

    if vault.user_id:
        token, _expires = create_user_access_token(vault.user_id)
        return token
    token, _expires = create_access_token(vault, authenticated)
    return token


def credential_login_response(profile, personal, recovery_code=None):
    # Login/register always establish Personal Vault as the active vault so
    # session, dashboard, and setup checks agree with the auth response.
    set_active_vault(profile.id, int(personal.id))
    token, expires_at = create_user_access_token(profile.id)
    personal_context = vault_context(personal, personal, user_id=profile.id, pin_set=True)
    return LoginResponse(
        token=token,
        vault=personal_context,
        authenticated_vault=personal_context,
        expires_at=expires_at.isoformat(),
        pin_set=True,
        display_name=profile.display_name,
        user_id=profile.id,
        recovery_code=recovery_code
    )


@router.post("/register", response_model=LoginResponse, response_model_by_alias=True, response_model_exclude_none=True)
def register(request: RegisterRequest):
    if request.pin != request.confirm_pin:
        raise bad_request("PIN and confirmation do not match.")

    try:
        profile, personal = register_user(request.username, request.display_name, request.pin)
        recovery_code = issue_recovery_code(profile.id)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    except IdentityError as exc:
        raise bad_request(str(exc)) from exc

    return credential_login_response(profile, personal, recovery_code=recovery_code)


@router.post("/login", response_model=LoginResponse, response_model_by_alias=True, response_model_exclude_none=True)
def login(request: LoginRequest):
    try:
        profile, personal = authenticate_user(request.username, request.pin)
    except IdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_CREDENTIALS",
                "message": "Username or PIN is incorrect."
            }
        ) from exc

    return credential_login_response(profile, personal)


@router.post("/recover-pin", response_model=LoginResponse, response_model_by_alias=True, response_model_exclude_none=True)
def recover_pin(request: RecoverPinRequest):
    if request.new_pin != request.confirm_pin:
        raise bad_request("New PIN and confirmation do not match.")

    try:
        profile, personal = recover_pin_with_recovery_code(
            request.username,
            request.recovery_code,
            request.new_pin,
        )
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    except IdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_RECOVERY_CODE",
                "message": "Recovery code is invalid."
            }
        ) from exc

    return credential_login_response(profile, personal)


@router.post("/me/recovery-code", response_model=RecoveryCodeResponse, response_model_by_alias=True)
def create_recovery_code(vault: VaultContext = Depends(get_authenticated_vault)):
    user_id = require_user_id(vault)
    try:
        recovery_code = issue_recovery_code(user_id)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    return RecoveryCodeResponse(recoveryCode=recovery_code)


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

    return session_response(active, authenticated, identity_fields(vault))


@router.patch("/me", response_model=SessionResponse, response_model_by_alias=True, response_model_exclude_none=True)
def update_profile(request: ProfileUpdateRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    user_id = require_user_id(vault)
    try:
        update_display_name(user_id, request.display_name)
    except IdentityError as exc:
        if str(exc) == "Profile not found.":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={
                    "code": "AUTHENTICATION_REQUIRED",
                    "message": "A signed-in user is required."
                }
            ) from exc
        raise bad_request(str(exc)) from exc

    return session(vault)


@router.post("/me/pin", response_model=SessionResponse, response_model_by_alias=True, response_model_exclude_none=True)
def set_pin(request: PinSetRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    user_id = require_user_id(vault)
    if request.pin != request.confirm_pin:
        raise bad_request("New PIN and confirmation do not match.")

    profile = get_profile(user_id)
    if profile and profile.pin_hash:
        raise bad_request("A PIN is already set. Use change PIN instead.")

    try:
        set_profile_pin(user_id, request.pin)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc

    return session(vault)


@router.patch("/me/pin", response_model=SessionResponse, response_model_by_alias=True, response_model_exclude_none=True)
def change_pin(request: PinChangeRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    user_id = require_user_id(vault)
    if request.new_pin != request.confirm_pin:
        raise bad_request("New PIN and confirmation do not match.")

    try:
        change_profile_pin(user_id, request.current_pin, request.new_pin)
    except IdentityError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INVALID_PIN",
                "message": "Current PIN is incorrect."
            }
        ) from exc
    except ValueError as exc:
        raise bad_request(str(exc)) from exc

    return session(vault)


@router.get("/vaults/shared", response_model=list[SharedVaultSummaryResponse], response_model_by_alias=True)
def shared_vaults(vault: VaultContext = Depends(get_authenticated_vault)):
    if vault.user_id:
        user_memberships = list_shared_memberships_for_user(vault.user_id)
        if user_memberships:
            return [
                SharedVaultSummaryResponse(
                    id=int(item.id),
                    name=item.name,
                    isAdmin=item.role == OWNER_ROLE,
                    vaultType="Shared",
                    role=item.role,
                    memberCount=item.member_count,
                )
                for item in user_memberships
            ]

    authenticated = authenticated_personal_vault(vault)
    return [
        SharedVaultSummaryResponse(
            id=int(shared_vault.id),
            name=shared_vault.name,
            isAdmin=False,
            vaultType="Shared",
            role=MEMBER_ROLE,
            memberCount=0,
        )
        for shared_vault in visible_connected_shared_vaults(authenticated)
    ]


@router.get("/vaults/shared/{shared_vault_id}", response_model=SharedVaultDetailResponse, response_model_by_alias=True)
def shared_vault_detail(shared_vault_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    user_id = require_user_id(vault)
    try:
        role = require_shared_membership(user_id, shared_vault_id)
    except IdentityError as exc:
        raise forbidden_shared_vault() from exc

    members = list_shared_vault_members(shared_vault_id)
    row = get_vault_by_id(shared_vault_id)
    name = str(row[1]) if row else "Shared Vault"

    return SharedVaultDetailResponse(
        id=shared_vault_id,
        name=name,
        isAdmin=role == OWNER_ROLE,
        vaultType="Shared",
        role=role,
        memberCount=len(members),
        inviteCode=invite_code_for_shared_vault(shared_vault_id) if role == OWNER_ROLE else None,
        members=[
            SharedVaultMemberResponse(
                userId=member.user_id,
                displayName=member.display_name,
                role=member.role,
                isCurrentUser=member.user_id == user_id,
            )
            for member in members
        ],
    )


@router.patch("/vaults/shared/{shared_vault_id}", response_model=SharedVaultDetailResponse, response_model_by_alias=True)
def rename_shared_vault(
    shared_vault_id: int,
    request: SharedVaultRenameRequest,
    vault: VaultContext = Depends(get_authenticated_vault),
):
    user_id = require_user_id(vault)
    try:
        rename_shared_vault_for_user(user_id, shared_vault_id, request.vault_name)
    except IdentityError as exc:
        raise bad_request(str(exc)) from exc
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    return shared_vault_detail(shared_vault_id, vault)


@router.post("/vaults/shared/{shared_vault_id}/leave", response_model_by_alias=True)
def leave_shared_vault(shared_vault_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    user_id = require_user_id(vault)
    try:
        leave_shared_vault_for_user(user_id, shared_vault_id)
    except IdentityError as exc:
        raise bad_request(str(exc)) from exc
    return {"ok": True}


@router.delete("/vaults/shared/{shared_vault_id}/members/{member_user_id}", response_model_by_alias=True)
def remove_shared_member(
    shared_vault_id: int,
    member_user_id: str,
    vault: VaultContext = Depends(get_authenticated_vault),
):
    user_id = require_user_id(vault)
    try:
        remove_shared_vault_member(user_id, shared_vault_id, member_user_id)
    except IdentityError as exc:
        raise bad_request(str(exc)) from exc
    return {"ok": True}


@router.delete("/vaults/shared/{shared_vault_id}", response_model_by_alias=True)
def delete_shared_vault(shared_vault_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    user_id = require_user_id(vault)
    try:
        delete_shared_vault_for_user(user_id, shared_vault_id)
    except IdentityError as exc:
        raise bad_request(str(exc)) from exc
    return {"ok": True}


@router.post("/vaults/shared/activate", response_model=LoginResponse, response_model_by_alias=True, response_model_exclude_none=True)
def activate_shared_vault(
    request: SharedVaultActivationRequest,
    vault: VaultContext = Depends(get_authenticated_vault),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)
):
    authenticated = authenticated_personal_vault(vault)
    connected = {
        shared_vault.id: shared_vault
        for shared_vault in visible_connected_shared_vaults(authenticated)
    }
    target = connected.get(str(request.shared_vault_id))

    # Membership via vault_members is the source of truth for multi-vault access.
    if not target and vault.user_id:
        memberships = {
            item.id: item
            for item in list_shared_memberships_for_user(vault.user_id)
        }
        membership = memberships.get(str(request.shared_vault_id))
        if membership:
            row = get_vault_by_id(request.shared_vault_id)
            target = vault_from_row(row)

    if not target:
        raise forbidden_shared_vault()

    if vault.user_id:
        try:
            set_active_vault(vault.user_id, int(target.id))
        except IdentityError:
            try:
                add_vault_member(int(target.id), vault.user_id, MEMBER_ROLE)
                set_active_vault(vault.user_id, int(target.id))
            except Exception:
                pass

    token = echo_token(credentials, target, authenticated)
    extra = identity_fields(vault)
    return LoginResponse(
        token=token,
        vault=vault_context(target, authenticated),
        authenticatedVault=vault_context(authenticated, authenticated),
        pinSet=extra.get("pinSet"),
        displayName=extra.get("displayName"),
        userId=extra.get("userId")
    )


@router.post("/vaults/shared/create", response_model=LoginResponse, response_model_by_alias=True, response_model_exclude_none=True)
def create_shared_vault(
    request: CreateSharedVaultRequest,
    vault: VaultContext = Depends(get_authenticated_vault),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)
):
    user_id = require_user_id(vault)
    authenticated = authenticated_personal_vault(vault)
    try:
        shared = create_shared_vault_for_user(user_id, request.vault_name)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc
    except IdentityError as exc:
        raise bad_request(str(exc)) from exc

    token = echo_token(credentials, shared, authenticated)
    extra = identity_fields(vault)
    return LoginResponse(
        token=token,
        vault=vault_context(shared, authenticated),
        authenticatedVault=vault_context(authenticated, authenticated),
        pinSet=extra.get("pinSet"),
        displayName=extra.get("displayName"),
        userId=extra.get("userId"),
        inviteCode=invite_code_for_shared_vault(shared.id)
    )


@router.post("/vaults/shared/join", response_model=LoginResponse, response_model_by_alias=True, response_model_exclude_none=True)
def join_shared_vault(
    request: JoinSharedVaultRequest,
    vault: VaultContext = Depends(get_authenticated_vault),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)
):
    user_id = require_user_id(vault)
    authenticated = authenticated_personal_vault(vault)
    try:
        shared = join_shared_vault_for_user(user_id, request.invite_code)
    except IdentityError as exc:
        raise bad_request(str(exc)) from exc

    token = echo_token(credentials, shared, authenticated)
    extra = identity_fields(vault)
    return LoginResponse(
        token=token,
        vault=vault_context(shared, authenticated),
        authenticatedVault=vault_context(authenticated, authenticated),
        pinSet=extra.get("pinSet"),
        displayName=extra.get("displayName"),
        userId=extra.get("userId")
    )


@router.post("/vaults/personal/activate", response_model=LoginResponse, response_model_by_alias=True, response_model_exclude_none=True)
def activate_personal_vault(
    vault: VaultContext = Depends(get_authenticated_vault),
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme)
):
    authenticated = authenticated_personal_vault(vault)
    if vault.user_id:
        try:
            set_active_vault(vault.user_id, int(authenticated.id))
        except IdentityError:
            pass

    token = echo_token(credentials, authenticated, authenticated)
    extra = identity_fields(vault)
    return LoginResponse(
        token=token,
        vault=vault_context(authenticated, authenticated),
        authenticatedVault=vault_context(authenticated, authenticated),
        pinSet=extra.get("pinSet"),
        displayName=extra.get("displayName"),
        userId=extra.get("userId")
    )

from dataclasses import dataclass
import re
import secrets
import string
from uuid import uuid4

import bcrypt

from db.cache import clear_data_cache
from db.core import ensure_default_category_with_cursor, get_connection


PERSONAL_VAULT_NAME = "Personal"
OWNER_ROLE = "owner"
MEMBER_ROLE = "member"
USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,32}$")
PROFILE_COLUMNS = "id, username, display_name, pin_hash, active_vault_id"
INVITE_CODE_PREFIX = "MV"
RECOVERY_CODE_ALPHABET = "".join(ch for ch in string.ascii_uppercase + string.digits if ch not in "O01IL")



class IdentityError(Exception):
    pass


@dataclass(frozen=True)
class ProfileRecord:
    id: str
    username: str | None
    display_name: str | None
    pin_hash: str | None
    active_vault_id: int | None


@dataclass(frozen=True)
class VaultRecord:
    id: str
    name: str
    is_admin: bool
    vault_type: str
    role: str = "member"


def hash_app_pin(pin: str) -> str:
    return bcrypt.hashpw(pin.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def verify_app_pin(pin: str, pin_hash: str | None) -> bool:
    if not pin_hash:
        return False

    try:
        return bcrypt.checkpw(pin.encode("utf-8"), pin_hash.encode("utf-8"))
    except ValueError:
        return False


def normalize_recovery_code(recovery_code: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", recovery_code).upper()


def generate_recovery_code() -> str:
    raw = "".join(secrets.choice(RECOVERY_CODE_ALPHABET) for _ in range(12))
    return f"{raw[0:4]}-{raw[4:8]}-{raw[8:12]}"


def hash_recovery_code(recovery_code: str) -> str:
    normalized = normalize_recovery_code(recovery_code)
    if len(normalized) < 12:
        raise ValueError("Recovery code is invalid.")
    return hash_app_pin(normalized)


def verify_recovery_code(recovery_code: str, recovery_code_hash: str | None) -> bool:
    if not recovery_code_hash:
        return False
    try:
        normalized = normalize_recovery_code(recovery_code)
        if len(normalized) < 12:
            return False
        return bcrypt.checkpw(normalized.encode("utf-8"), recovery_code_hash.encode("utf-8"))
    except ValueError:
        return False


def get_recovery_code_hash(user_id: str) -> str | None:
    ensure_identity_schema()
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT recovery_code_hash
            FROM profiles
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()
        if not row:
            return None
        value = row[0]
        return str(value) if value else None
    finally:
        conn.close()


def store_recovery_code_hash(user_id: str, recovery_code_hash: str) -> None:
    ensure_identity_schema()
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE profiles
            SET recovery_code_hash = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (recovery_code_hash, user_id),
            capture_lastrowid=False,
        )
        conn.commit()
    finally:
        conn.close()


def clear_recovery_code_hash(user_id: str) -> None:
    ensure_identity_schema()
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE profiles
            SET recovery_code_hash = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (user_id,),
            capture_lastrowid=False,
        )
        conn.commit()
    finally:
        conn.close()


def issue_recovery_code(user_id: str) -> str:
    code = generate_recovery_code()
    store_recovery_code_hash(user_id, hash_recovery_code(code))
    return code


def recover_pin_with_recovery_code(username: str, recovery_code: str, new_pin: str) -> tuple[ProfileRecord, VaultRecord]:
    """Verify recovery code, set a new account PIN, and invalidate the recovery code."""
    ensure_identity_schema()
    validate_app_pin(new_pin)
    profile = get_profile_by_username(username)
    if not profile:
        raise IdentityError("Recovery code is invalid.")

    stored_hash = get_recovery_code_hash(profile.id)
    if not verify_recovery_code(recovery_code, stored_hash):
        raise IdentityError("Recovery code is invalid.")

    personal = get_personal_vault(profile.id)
    if not personal:
        raise IdentityError("Your personal vault could not be found.")

    set_profile_pin(profile.id, new_pin)
    clear_recovery_code_hash(profile.id)
    set_active_vault(profile.id, int(personal.id))
    clear_data_cache()
    refreshed = get_profile(profile.id)
    if not refreshed:
        raise IdentityError("Profile not found.")
    return refreshed, personal


def validate_app_pin(pin: str) -> None:
    if pin is None or len(pin) < 4 or len(pin) > 6:
        raise ValueError("PIN must be between 4 and 6 characters.")


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not USERNAME_PATTERN.match(normalized):
        raise ValueError("Username must be 3 to 32 letters, numbers, or underscores.")
    return normalized


def validate_display_name(display_name: str, username: str) -> str:
    name = display_name.strip()
    if not name:
        raise ValueError("Display name is required.")
    if name.casefold() == username.casefold():
        raise ValueError("Display name must be different from your username.")
    return name


def validate_vault_name(name: str) -> str:
    vault_name = name.strip()
    if not vault_name:
        raise ValueError("Vault name is required.")
    return vault_name


def person_display_name_sql(vault_id_expr: str, fallback_expr: str) -> str:
    """SQL expression: profile display name, then username, then vault name."""
    return f"""COALESCE(
        (
            SELECT COALESCE(NULLIF(TRIM(p.display_name), ''), NULLIF(TRIM(p.username), ''))
            FROM vault_members vm
            JOIN profiles p ON p.id = vm.user_id
            WHERE vm.vault_id = {vault_id_expr}
            ORDER BY CASE WHEN vm.role = 'owner' THEN 0 ELSE 1 END
            LIMIT 1
        ),
        {fallback_expr}
    )"""


def invite_code_for_shared_vault(vault_id: int | str) -> str:
    return f"{INVITE_CODE_PREFIX}-{int(vault_id):06d}"


def shared_vault_id_from_invite_code(invite_code: str) -> int:
    cleaned = invite_code.strip().upper().replace(" ", "")
    if cleaned.startswith(f"{INVITE_CODE_PREFIX}-"):
        cleaned = cleaned[len(INVITE_CODE_PREFIX) + 1:]

    if not cleaned.isdigit():
        raise IdentityError("Invite code is invalid.")

    return int(cleaned)


def ensure_identity_schema_with_cursor(cursor) -> None:
    try:
        cursor.execute(
            """
            ALTER TABLE vaults
            ALTER COLUMN pin_hash DROP NOT NULL
            """,
            capture_lastrowid=False
        )
    except Exception:
        pass

    try:
        cursor.execute("ALTER TABLE vaults DROP CONSTRAINT IF EXISTS vaults_name_key", capture_lastrowid=False)
    except Exception:
        pass
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
            id UUID PRIMARY KEY,
            username TEXT UNIQUE,
            display_name TEXT,
            pin_hash TEXT,
            active_vault_id BIGINT REFERENCES vaults(id),
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
        )
        """,
        capture_lastrowid=False
    )
    try:
        cursor.execute(
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS username TEXT",
            capture_lastrowid=False
        )
    except Exception:
        pass
    try:
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_username ON profiles (username)",
            capture_lastrowid=False
        )
    except Exception:
        pass
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS vault_members (
            id BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
            vault_id BIGINT NOT NULL REFERENCES vaults(id) ON DELETE CASCADE,
            user_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
            role TEXT NOT NULL DEFAULT 'member',
            created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(vault_id, user_id)
        )
        """,
        capture_lastrowid=False
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_vault_members_user ON vault_members(user_id)",
        capture_lastrowid=False
    )
    try:
        cursor.execute(
            "ALTER TABLE profiles ADD COLUMN IF NOT EXISTS recovery_code_hash TEXT",
            capture_lastrowid=False
        )
    except Exception:
        pass

    try:
        cursor.execute(
            "ALTER TABLE vaults DROP CONSTRAINT IF EXISTS chk_vault_type",
            capture_lastrowid=False
        )
        cursor.execute(
            """
            ALTER TABLE vaults
            ADD CONSTRAINT chk_vault_type
            CHECK (vault_type IN ('Individual', 'Shared'))
            """,
            capture_lastrowid=False
        )
    except Exception:
        pass

    try:
        cursor.execute(
            "ALTER TABLE vault_members DROP CONSTRAINT IF EXISTS chk_vault_member_role",
            capture_lastrowid=False
        )
        cursor.execute(
            """
            ALTER TABLE vault_members
            ADD CONSTRAINT chk_vault_member_role
            CHECK (role IN ('owner', 'member'))
            """,
            capture_lastrowid=False
        )
    except Exception:
        pass

    try:
        cursor.execute(
            """
            CREATE OR REPLACE FUNCTION prevent_duplicate_personal_vault_owner()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $fn$
            BEGIN
              IF NEW.role = 'owner' AND EXISTS (
                SELECT 1 FROM vaults v
                WHERE v.id = NEW.vault_id AND v.vault_type = 'Individual'
              ) THEN
                IF EXISTS (
                  SELECT 1
                  FROM vault_members vm
                  JOIN vaults v ON v.id = vm.vault_id
                  WHERE vm.user_id = NEW.user_id
                    AND vm.role = 'owner'
                    AND v.vault_type = 'Individual'
                    AND (NEW.id IS NULL OR vm.id <> NEW.id)
                ) THEN
                  RAISE EXCEPTION 'A user can own only one Personal Vault';
                END IF;
              END IF;
              RETURN NEW;
            END;
            $fn$;
            """,
            capture_lastrowid=False
        )
        cursor.execute(
            "DROP TRIGGER IF EXISTS trg_one_personal_vault_owner ON vault_members",
            capture_lastrowid=False
        )
        cursor.execute(
            """
            CREATE TRIGGER trg_one_personal_vault_owner
            BEFORE INSERT OR UPDATE ON vault_members
            FOR EACH ROW
            EXECUTE PROCEDURE prevent_duplicate_personal_vault_owner()
            """,
            capture_lastrowid=False
        )
    except Exception:
        pass


def ensure_identity_schema() -> None:
    conn = get_connection()
    try:
        ensure_identity_schema_with_cursor(conn.cursor())
        conn.commit()
    finally:
        conn.close()


def _row_to_profile(row) -> ProfileRecord | None:
    if not row:
        return None

    return ProfileRecord(
        id=str(row[0]),
        username=row[1],
        display_name=row[2],
        pin_hash=row[3],
        active_vault_id=int(row[4]) if row[4] is not None else None
    )


def _row_to_vault(row) -> VaultRecord | None:
    if not row:
        return None

    role = str(row[5]) if len(row) > 5 and row[5] is not None else (
        OWNER_ROLE if len(row) > 4 and row[4] == "Individual" else (
            OWNER_ROLE if len(row) > 2 and bool(row[2]) else MEMBER_ROLE
        )
    )

    return VaultRecord(
        id=str(row[0]),
        name=str(row[1]),
        is_admin=role == OWNER_ROLE,
        vault_type=str(row[4] if len(row) > 4 else "Individual"),
        role=role
    )


def get_profile(user_id: str) -> ProfileRecord | None:
    conn = get_connection()
    try:
        row = conn.execute(
            f"""
            SELECT {PROFILE_COLUMNS}
            FROM profiles
            WHERE id = ?
            """,
            (user_id,)
        ).fetchone()
        return _row_to_profile(row)
    finally:
        conn.close()


def get_profile_by_username(username: str) -> ProfileRecord | None:
    conn = get_connection()
    try:
        row = conn.execute(
            f"""
            SELECT {PROFILE_COLUMNS}
            FROM profiles
            WHERE username = ?
            """,
            (normalize_username(username),)
        ).fetchone()
        return _row_to_profile(row)
    finally:
        conn.close()


def list_user_vaults(user_id: str) -> list[VaultRecord]:
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT v.id, v.name, v.is_admin, v.financial_cycle_start_day, v.vault_type, vm.role
            FROM vault_members vm
            JOIN vaults v ON v.id = vm.vault_id
            WHERE vm.user_id = ?
            ORDER BY CASE WHEN v.vault_type = 'Individual' THEN 0 ELSE 1 END, v.name
            """,
            (user_id,)
        ).fetchall()
        return [vault for vault in (_row_to_vault(row) for row in rows) if vault]
    finally:
        conn.close()


def get_membership(user_id: str, vault_id: int) -> str | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT role
            FROM vault_members
            WHERE user_id = ?
            AND vault_id = ?
            """,
            (user_id, vault_id)
        ).fetchone()
        return str(row[0]) if row else None
    finally:
        conn.close()


def get_personal_vault(user_id: str) -> VaultRecord | None:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT v.id, v.name, v.is_admin, v.financial_cycle_start_day, v.vault_type, vm.role
            FROM vault_members vm
            JOIN vaults v ON v.id = vm.vault_id
            WHERE vm.user_id = ?
            AND vm.role = ?
            AND v.vault_type = 'Individual'
            ORDER BY v.id
            LIMIT 1
            """,
            (user_id, OWNER_ROLE)
        ).fetchone()
        return _row_to_vault(row)
    finally:
        conn.close()


def register_user(username: str, display_name: str, pin: str) -> tuple[ProfileRecord, VaultRecord]:
    normalized_username = validate_username(username)
    name = validate_display_name(display_name, normalized_username)
    validate_app_pin(pin)
    ensure_identity_schema()

    if get_profile_by_username(normalized_username):
        raise IdentityError("That username is already taken.")

    user_id = str(uuid4())
    pin_hash = hash_app_pin(pin)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO profiles (id, username, display_name, pin_hash)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, normalized_username, name, pin_hash),
            capture_lastrowid=False
        )
        cursor.execute(
            """
            INSERT INTO vaults (
                name,
                month_start_day,
                financial_cycle_start_day,
                monthly_savings_goal,
                vault_type,
                is_admin
            )
            VALUES (?, 1, 1, 0, 'Individual', 0)
            """,
            (PERSONAL_VAULT_NAME,)
        )
        vault_id = cursor.lastrowid
        ensure_default_category_with_cursor(cursor, vault_id)
        cursor.execute(
            """
            INSERT INTO vault_members (vault_id, user_id, role)
            VALUES (?, ?, ?)
            """,
            (vault_id, user_id, OWNER_ROLE),
            capture_lastrowid=False
        )
        cursor.execute(
            """
            UPDATE profiles
            SET active_vault_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (vault_id, user_id),
            capture_lastrowid=False
        )
        profile_row = cursor.execute(
            f"""
            SELECT {PROFILE_COLUMNS}
            FROM profiles
            WHERE id = ?
            """,
            (user_id,)
        ).fetchone()
        personal_row = cursor.execute(
            """
            SELECT id, name, is_admin, financial_cycle_start_day, vault_type
            FROM vaults
            WHERE id = ?
            """,
            (vault_id,)
        ).fetchone()
        conn.commit()
        profile = _row_to_profile(profile_row)
        personal = _row_to_vault(personal_row)
        if not profile or not personal:
            raise IdentityError("Unable to create your Money Vault.")
        return profile, personal
    except IdentityError:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        if get_profile_by_username(normalized_username):
            raise IdentityError("That username is already taken.")
        raise
    finally:
        conn.close()


def authenticate_user(username: str, pin: str) -> tuple[ProfileRecord, VaultRecord]:
    ensure_identity_schema()
    profile = get_profile_by_username(username)
    if not profile or not verify_app_pin(pin, profile.pin_hash):
        raise IdentityError("Username or PIN is incorrect.")

    personal = get_personal_vault(profile.id)
    if not personal:
        raise IdentityError("Your personal vault could not be found.")
    return profile, personal


def set_active_vault(user_id: str, vault_id: int) -> None:
    if not get_membership(user_id, vault_id):
        raise IdentityError("You do not have access to that vault.")

    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE profiles
            SET active_vault_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (vault_id, user_id),
            capture_lastrowid=False
        )
        conn.commit()
    finally:
        conn.close()


def update_display_name(user_id: str, display_name: str) -> ProfileRecord:
    profile = get_profile(user_id)
    if not profile:
        raise IdentityError("Profile not found.")

    name = validate_display_name(display_name, profile.username or "")
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE profiles
            SET display_name = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (name, user_id),
            capture_lastrowid=False
        )
        conn.commit()
    finally:
        conn.close()

    updated = get_profile(user_id)
    if not updated:
        raise IdentityError("Profile not found.")
    return updated


def set_profile_pin(user_id: str, pin: str) -> None:
    validate_app_pin(pin)
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE profiles
            SET pin_hash = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (hash_app_pin(pin), user_id),
            capture_lastrowid=False
        )
        conn.commit()
    finally:
        conn.close()


def change_profile_pin(user_id: str, current_pin: str, new_pin: str) -> None:
    profile = get_profile(user_id)
    if not profile or not verify_app_pin(current_pin, profile.pin_hash):
        raise IdentityError("Current PIN is incorrect.")
    if current_pin == new_pin:
        raise ValueError("New PIN must differ from current PIN.")
    set_profile_pin(user_id, new_pin)


def add_vault_member(vault_id: int, user_id: str, role: str = MEMBER_ROLE) -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO vault_members (vault_id, user_id, role)
            VALUES (?, ?, ?)
            ON CONFLICT (vault_id, user_id) DO UPDATE SET role = EXCLUDED.role
            """,
            (vault_id, user_id, role),
            capture_lastrowid=False
        )
        conn.commit()
    finally:
        conn.close()


def create_shared_vault_for_user(user_id: str, name: str) -> VaultRecord:
    vault_name = validate_vault_name(name)
    profile = get_profile(user_id)
    if not profile:
        raise IdentityError("Profile not found.")

    personal = get_personal_vault(user_id)
    if not personal:
        raise IdentityError("Your personal vault could not be found.")

    ensure_identity_schema()
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO vaults (
                name,
                month_start_day,
                financial_cycle_start_day,
                monthly_savings_goal,
                vault_type,
                is_admin
            )
            VALUES (?, 1, 1, 0, 'Shared', 0)
            """,
            (vault_name,)
        )
        vault_id = cursor.lastrowid
        ensure_default_category_with_cursor(cursor, vault_id)
        cursor.execute(
            """
            INSERT INTO vault_shares (vault_id, shared_vault_id)
            VALUES (?, ?)
            ON CONFLICT (vault_id, shared_vault_id) DO NOTHING
            """,
            (vault_id, int(personal.id)),
            capture_lastrowid=False
        )
        cursor.execute(
            """
            INSERT INTO vault_members (vault_id, user_id, role)
            VALUES (?, ?, ?)
            ON CONFLICT (vault_id, user_id) DO UPDATE SET role = EXCLUDED.role
            """,
            (vault_id, user_id, OWNER_ROLE),
            capture_lastrowid=False
        )
        cursor.execute(
            """
            UPDATE profiles
            SET active_vault_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (vault_id, user_id),
            capture_lastrowid=False
        )
        row = cursor.execute(
            """
            SELECT id, name, is_admin, financial_cycle_start_day, vault_type
            FROM vaults
            WHERE id = ?
            """,
            (vault_id,)
        ).fetchone()
        conn.commit()
        shared = _row_to_vault(row)
        if not shared:
            raise IdentityError("Shared vault could not be created.")
        clear_data_cache(("vaults", "dashboard", "reports", "shared_expenses", "shared_bills"))
        return shared
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@dataclass(frozen=True)
class SharedVaultMembership:
    id: str
    name: str
    role: str
    member_count: int


@dataclass(frozen=True)
class SharedVaultMemberRecord:
    user_id: str
    display_name: str
    role: str


def list_shared_memberships_for_user(user_id: str) -> list[SharedVaultMembership]:
    ensure_identity_schema()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                v.id,
                v.name,
                vm.role,
                (
                    SELECT COUNT(*)
                    FROM vault_members members
                    WHERE members.vault_id = v.id
                ) AS member_count
            FROM vault_members vm
            JOIN vaults v ON v.id = vm.vault_id
            WHERE vm.user_id = ?
            AND v.vault_type = 'Shared'
            ORDER BY v.name
            """,
            (user_id,)
        ).fetchall()
        return [
            SharedVaultMembership(
                id=str(row[0]),
                name=str(row[1]),
                role=str(row[2]),
                member_count=int(row[3] or 0),
            )
            for row in rows
        ]
    finally:
        conn.close()


def require_shared_membership(user_id: str, vault_id: int) -> str:
    role = get_membership(user_id, vault_id)
    vault = None
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT id, name, is_admin, financial_cycle_start_day, vault_type
            FROM vaults
            WHERE id = ?
            """,
            (vault_id,)
        ).fetchone()
        vault = _row_to_vault(row)
    finally:
        conn.close()

    if not vault or vault.vault_type != "Shared" or not role:
        raise IdentityError("Shared vault was not found.")
    return role


def list_shared_vault_members(vault_id: int) -> list[SharedVaultMemberRecord]:
    ensure_identity_schema()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT p.id, COALESCE(p.display_name, p.username, 'Member'), vm.role
            FROM vault_members vm
            JOIN profiles p ON p.id = vm.user_id
            WHERE vm.vault_id = ?
            ORDER BY CASE WHEN vm.role = ? THEN 0 ELSE 1 END, COALESCE(p.display_name, p.username)
            """,
            (vault_id, OWNER_ROLE)
        ).fetchall()
        return [
            SharedVaultMemberRecord(
                user_id=str(row[0]),
                display_name=str(row[1]),
                role=str(row[2]),
            )
            for row in rows
        ]
    finally:
        conn.close()


def _owner_count(vault_id: int) -> int:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COUNT(*)
            FROM vault_members
            WHERE vault_id = ?
            AND role = ?
            """,
            (vault_id, OWNER_ROLE)
        ).fetchone()
        return int(row[0] or 0) if row else 0
    finally:
        conn.close()


def _detach_personal_share(cursor, shared_vault_id: int, personal_vault_id: int) -> None:
    cursor.execute(
        """
        DELETE FROM vault_shares
        WHERE vault_id = ?
        AND shared_vault_id = ?
        """,
        (shared_vault_id, personal_vault_id),
        capture_lastrowid=False
    )


def _reset_active_vault_if_needed(cursor, user_id: str, shared_vault_id: int, personal_vault_id: int | None) -> None:
    if personal_vault_id is None:
        return
    cursor.execute(
        """
        UPDATE profiles
        SET active_vault_id = ?, updated_at = CURRENT_TIMESTAMP
        WHERE id = ?
        AND active_vault_id = ?
        """,
        (personal_vault_id, user_id, shared_vault_id),
        capture_lastrowid=False
    )


def rename_shared_vault_for_user(user_id: str, vault_id: int, name: str) -> VaultRecord:
    role = require_shared_membership(user_id, vault_id)
    if role != OWNER_ROLE:
        raise IdentityError("Only the vault owner can rename this shared vault.")

    vault_name = validate_vault_name(name)
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE vaults
            SET name = ?
            WHERE id = ?
            AND vault_type = 'Shared'
            """,
            (vault_name, vault_id),
            capture_lastrowid=False
        )
        row = conn.execute(
            """
            SELECT id, name, is_admin, financial_cycle_start_day, vault_type
            FROM vaults
            WHERE id = ?
            """,
            (vault_id,)
        ).fetchone()
        conn.commit()
        clear_data_cache(("vaults", "dashboard", "reports", "shared_expenses", "shared_bills"))
        vault = _row_to_vault(row)
        if not vault:
            raise IdentityError("Shared vault was not found.")
        return vault
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def leave_shared_vault_for_user(user_id: str, vault_id: int) -> None:
    role = require_shared_membership(user_id, vault_id)
    if role == OWNER_ROLE and _owner_count(vault_id) <= 1:
        raise IdentityError("Owners must delete the shared vault instead of leaving as the only owner.")

    personal = get_personal_vault(user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM vault_members
            WHERE vault_id = ?
            AND user_id = ?
            """,
            (vault_id, user_id),
            capture_lastrowid=False
        )
        if personal:
            _detach_personal_share(cursor, vault_id, int(personal.id))
            _reset_active_vault_if_needed(cursor, user_id, vault_id, int(personal.id))
        conn.commit()
        clear_data_cache(("vaults", "dashboard", "reports", "shared_expenses", "shared_bills"))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def remove_shared_vault_member(actor_user_id: str, vault_id: int, target_user_id: str) -> None:
    role = require_shared_membership(actor_user_id, vault_id)
    if role != OWNER_ROLE:
        raise IdentityError("Only the vault owner can remove members.")
    if actor_user_id == target_user_id:
        raise IdentityError("Use leave vault to remove yourself.")

    target_role = get_membership(target_user_id, vault_id)
    if not target_role:
        raise IdentityError("That member was not found in this shared vault.")
    if target_role == OWNER_ROLE and _owner_count(vault_id) <= 1:
        raise IdentityError("Cannot remove the only owner.")

    target_personal = get_personal_vault(target_user_id)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            DELETE FROM vault_members
            WHERE vault_id = ?
            AND user_id = ?
            """,
            (vault_id, target_user_id),
            capture_lastrowid=False
        )
        if target_personal:
            _detach_personal_share(cursor, vault_id, int(target_personal.id))
            _reset_active_vault_if_needed(cursor, target_user_id, vault_id, int(target_personal.id))
        conn.commit()
        clear_data_cache(("vaults", "dashboard", "reports", "shared_expenses", "shared_bills"))
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_shared_vault_for_user(user_id: str, vault_id: int) -> None:
    role = require_shared_membership(user_id, vault_id)
    if role != OWNER_ROLE:
        raise IdentityError("Only the vault owner can delete this shared vault.")

    members = list_shared_vault_members(vault_id)
    personal_by_user = {
        member.user_id: get_personal_vault(member.user_id)
        for member in members
    }

    conn = get_connection()
    try:
        cursor = conn.cursor()
        for member in members:
            personal = personal_by_user.get(member.user_id)
            if personal:
                _reset_active_vault_if_needed(cursor, member.user_id, vault_id, int(personal.id))
        cursor.execute(
            """
            DELETE FROM vault_members
            WHERE vault_id = ?
            """,
            (vault_id,),
            capture_lastrowid=False
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    from db.vaults import delete_vault

    delete_vault(vault_id)


def join_shared_vault_for_user(user_id: str, invite_code: str) -> VaultRecord:
    profile = get_profile(user_id)
    if not profile:
        raise IdentityError("Profile not found.")

    personal = get_personal_vault(user_id)
    if not personal:
        raise IdentityError("Your personal vault could not be found.")

    shared_vault_id = shared_vault_id_from_invite_code(invite_code)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        row = cursor.execute(
            """
            SELECT id, name, is_admin, financial_cycle_start_day, vault_type
            FROM vaults
            WHERE id = ?
            AND vault_type = 'Shared'
            """,
            (shared_vault_id,)
        ).fetchone()
        shared = _row_to_vault(row)
        if not shared:
            raise IdentityError("Invite code is invalid.")

        cursor.execute(
            """
            INSERT INTO vault_shares (vault_id, shared_vault_id)
            VALUES (?, ?)
            ON CONFLICT (vault_id, shared_vault_id) DO NOTHING
            """,
            (shared_vault_id, int(personal.id)),
            capture_lastrowid=False
        )
        cursor.execute(
            """
            INSERT INTO vault_members (vault_id, user_id, role)
            VALUES (?, ?, ?)
            ON CONFLICT (vault_id, user_id) DO UPDATE SET role = EXCLUDED.role
            """,
            (shared_vault_id, user_id, MEMBER_ROLE),
            capture_lastrowid=False
        )
        cursor.execute(
            """
            UPDATE profiles
            SET active_vault_id = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (shared_vault_id, user_id),
            capture_lastrowid=False
        )
        conn.commit()
        clear_data_cache(("vaults", "dashboard", "reports", "shared_expenses", "shared_bills"))
        return shared
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

from db.core import (
    ensure_default_category_with_cursor,
    get_connection,
    hash_pin
)
from db.cache import cache_data, clear_data_cache


def validate_pin(pin):
    if pin is None:
        return

    if len(pin) < 4 or len(pin) > 6:
        raise ValueError("PIN must be between 4 and 6 characters.")


@cache_data(ttl=60)
def vault_exists():

    conn = get_connection()
    try:

        count = conn.execute(
            "SELECT COUNT(*) FROM vaults"
        ).fetchone()[0]


        return count > 0

    finally:
        conn.close()
def verify_pin(vault_name, pin):

    conn = get_connection()
    try:
        pin_hash = hash_pin(pin)

        vault = conn.execute(
            """
            SELECT
                id,
                name,
                pin_hash,
                is_admin,
                created_at
            FROM vaults
            WHERE name = ?
            AND pin_hash = ?
            """,
            (
                vault_name,
                pin_hash
            )
        ).fetchone()


        return vault

    finally:
        conn.close()
@cache_data(ttl=60)
def get_vaults():

    conn = get_connection()
    try:

        vaults = conn.execute(
            """
            SELECT id, name
            FROM vaults
            ORDER BY name
            """
        ).fetchall()


        return vaults


    finally:
        conn.close()
def create_vault(
    name,
    pin,
    is_admin=False,
    vault_type="Individual",
    shared_vault_ids=None
):

    validate_pin(pin)

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO vaults
            (
                name,
                pin_hash,
                month_start_day,
                financial_cycle_start_day,
                monthly_savings_goal,
                vault_type,
                is_admin
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                hash_pin(pin),
                1,
                1,
                0,
                vault_type,
                int(is_admin)
            )
        )

        vault_id = cursor.lastrowid

        ensure_default_category_with_cursor(
            cursor,
            vault_id
        )

        update_vault_shares_with_cursor(
            cursor,
            vault_id,
            shared_vault_ids or []
        )

        conn.commit()
        clear_data_cache((
            "vaults",
            "accounts",
            "categories",
            "cycles",
            "dashboard",
            "planning",
            "reports",
            "shared_expenses",
            "shared_bills",
            "wishlist"
        ))


    finally:
        conn.close()
def update_vault(
    vault_id,
    name,
    pin=None,
    is_admin=None,
    month_start_day=None,
    monthly_savings_goal=None,
    vault_type=None,
    shared_vault_ids=None
):

    vault_name = name.strip()

    if not vault_name:
        raise ValueError("Vault name is required.")

    conn = get_connection()
    try:

        existing = conn.execute(
            """
            SELECT id
            FROM vaults
            WHERE LOWER(name) = LOWER(?)
            AND id != ?
            """,
            (
                vault_name,
                vault_id
            )
        ).fetchone()

        if existing:
            raise ValueError("A vault with this name already exists.")

        updates = [
            "name = ?"
        ]
        params = [
            vault_name
        ]

        if pin:
            validate_pin(pin)
            updates.append(
                "pin_hash = ?"
            )
            params.append(
                hash_pin(pin)
            )

        if is_admin is not None:
            updates.append(
                "is_admin = ?"
            )
            params.append(
                int(is_admin)
            )

        if month_start_day is not None:
            month_start_day = int(month_start_day)
            if month_start_day < 1 or month_start_day > 31:
                raise ValueError("Financial cycle start day must be between 1 and 31.")
            updates.append(
                "month_start_day = ?"
            )
            params.append(
                month_start_day
            )
            updates.append(
                "financial_cycle_start_day = ?"
            )
            params.append(
                month_start_day
            )

        if monthly_savings_goal is not None:
            monthly_savings_goal = float(monthly_savings_goal)
            if monthly_savings_goal < 0:
                raise ValueError("Monthly savings goal cannot be negative.")
            updates.append(
                "monthly_savings_goal = ?"
            )
            params.append(
                monthly_savings_goal
            )

        if vault_type is not None:
            updates.append(
                "vault_type = ?"
            )
            params.append(
                vault_type
            )

        params.append(
            vault_id
        )

        conn.execute(
            f"""
            UPDATE vaults
            SET {", ".join(updates)}
            WHERE id = ?
            """,
            params
        )

        if shared_vault_ids is not None:
            update_vault_shares_with_cursor(
                conn,
                vault_id,
                shared_vault_ids
            )

        conn.commit()
        clear_data_cache((
            "vaults",
            "accounts",
            "categories",
            "cycles",
            "dashboard",
            "planning",
            "reports",
            "shared_expenses",
            "shared_bills",
            "wishlist"
        ))


    finally:
        conn.close()
def update_vault_shares_with_cursor(cursor, vault_id, shared_vault_ids):
    cursor.execute(
        """
        DELETE FROM vault_shares
        WHERE vault_id = ?
        """,
        (vault_id,)
    )

    for shared_vault_id in shared_vault_ids:
        if int(shared_vault_id) == int(vault_id):
            continue

        cursor.execute(
            """
            INSERT INTO vault_shares (
                vault_id,
                shared_vault_id
            )
            VALUES (?, ?)
            ON CONFLICT (vault_id, shared_vault_id) DO NOTHING
            """,
            (
                vault_id,
                int(shared_vault_id)
            )
            ,
            capture_lastrowid=False
        )

@cache_data(ttl=60)
def get_vault_share_ids(vault_id):

    conn = get_connection()
    try:

        rows = conn.execute(
            """
            SELECT shared_vault_id
            FROM vault_shares
            WHERE vault_id = ?
            ORDER BY shared_vault_id
            """,
            (vault_id,)
        ).fetchall()


        return [
            row[0]
            for row in rows
        ]

    finally:
        conn.close()
@cache_data(ttl=60)
def get_connected_shared_vaults(vault_id):

    conn = get_connection()
    try:

        vaults = conn.execute(
            """
            SELECT
                shared.id,
                shared.name
            FROM vault_shares vs
            JOIN vaults shared
                ON vs.vault_id = shared.id
            WHERE vs.shared_vault_id = ?
            AND shared.vault_type = 'Shared'
            ORDER BY shared.name
            """,
            (vault_id,)
        ).fetchall()


        return vaults

    finally:
        conn.close()
@cache_data(ttl=60)
def get_shared_vault_participants(shared_vault_id):

    conn = get_connection()
    try:

        participants = conn.execute(
            """
            SELECT
                participant.id,
                participant.name
            FROM vault_shares vs
            JOIN vaults participant
                ON vs.shared_vault_id = participant.id
            WHERE vs.vault_id = ?
            AND participant.vault_type = 'Individual'
            ORDER BY participant.name
            """,
            (shared_vault_id,)
        ).fetchall()


        return participants

    finally:
        conn.close()
@cache_data(ttl=60)
def get_vault_by_id(vault_id):

    conn = get_connection()
    try:

        vault = conn.execute(
            """
            SELECT
                id,
                name,
                is_admin,
                COALESCE(financial_cycle_start_day, month_start_day, 1),
                vault_type
            FROM vaults
            WHERE id = ?
            """,
            (vault_id,)
        ).fetchone()


        return vault

    finally:
        conn.close()
@cache_data(ttl=60)
def get_vault_financial_settings(vault_id):

    conn = get_connection()
    try:

        return conn.execute(
            """
            SELECT
                COALESCE(financial_cycle_start_day, month_start_day, 1),
                COALESCE(monthly_savings_goal, 0)
            FROM vaults
            WHERE id = ?
            """,
            (vault_id,)
        ).fetchone()

    finally:
        conn.close()


@cache_data(ttl=60)
def get_all_vaults():

    conn = get_connection()
    try:

        vaults = conn.execute(
            """
            SELECT
                id,
                name,
                is_admin,
                COALESCE(financial_cycle_start_day, month_start_day, 1),
                vault_type
            FROM vaults
            ORDER BY name
            """
        ).fetchall()


        return vaults


    finally:
        conn.close()
def promote_to_admin(vault_name):

    conn = get_connection()
    try:

        conn.execute(
            """
            UPDATE vaults
            SET is_admin = 1
            WHERE name = ?
            """,
            (vault_name,)
        )

        affected_rows = conn.total_changes

        conn.commit()
        clear_data_cache((
            "vaults",
            "dashboard",
            "reports"
        ))

        return affected_rows


    finally:
        conn.close()
def demote_admin(vault_name):

    conn = get_connection()
    try:

        conn.execute(
            """
            UPDATE vaults
            SET is_admin = 0
            WHERE name = ?
            """,
            (vault_name,)
        )

        conn.commit()
        clear_data_cache((
            "vaults",
            "dashboard",
            "reports"
        ))

    finally:
        conn.close()
@cache_data(ttl=60)
def get_admin_count():

    conn = get_connection()
    try:

        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM vaults
            WHERE is_admin = 1
            """
        ).fetchone()[0]


        return count


    finally:
        conn.close()
def delete_vault(vault_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM income_status
            WHERE income_template_id IN (
                SELECT id
                FROM income_templates
                WHERE vault_id = ?
            )
            """,
            (vault_id,)
        )

        cursor.execute(
            """
            DELETE FROM obligation_status
            WHERE commitment_id IN (
                SELECT id
                FROM commitments
                WHERE vault_id = ?
            )
            """,
            (vault_id,)
        )

        cursor.execute(
            """
            DELETE FROM transaction_shares
            WHERE participant_vault_id = ?
            OR transaction_id IN (
                SELECT id
                FROM transactions
                WHERE vault_id = ?
                OR beneficiary_vault_id = ?
            )
            """,
            (
                vault_id,
                vault_id,
                vault_id
            )
        )

        cursor.execute(
            """
            DELETE FROM transactions
            WHERE vault_id = ?
            OR beneficiary_vault_id = ?
            """,
            (
                vault_id,
                vault_id
            )
        )

        cursor.execute(
            """
            DELETE FROM income_templates
            WHERE vault_id = ?
            """,
            (vault_id,)
        )

        cursor.execute(
            """
            DELETE FROM commitments
            WHERE vault_id = ?
            """,
            (vault_id,)
        )

        cursor.execute(
            """
            DELETE FROM shared_bill_instance_shares
            WHERE participant_vault_id = ?
            OR bill_instance_id IN (
                SELECT i.id
                FROM shared_bill_instances i
                LEFT JOIN shared_bill_cycles c
                    ON c.id = i.cycle_id
                LEFT JOIN shared_bills b
                    ON b.id = i.bill_id
                WHERE c.shared_vault_id = ?
                OR b.shared_vault_id = ?
                OR b.category_id IN (
                    SELECT id
                    FROM categories
                    WHERE vault_id = ?
                )
            )
            """,
            (
                vault_id,
                vault_id,
                vault_id,
                vault_id
            )
        )

        cursor.execute(
            """
            DELETE FROM shared_bill_instances
            WHERE cycle_id IN (
                SELECT id
                FROM shared_bill_cycles
                WHERE shared_vault_id = ?
            )
            OR bill_id IN (
                SELECT id
                FROM shared_bills
                WHERE shared_vault_id = ?
                OR category_id IN (
                    SELECT id
                    FROM categories
                    WHERE vault_id = ?
                )
            )
            """,
            (
                vault_id,
                vault_id,
                vault_id
            )
        )

        cursor.execute(
            """
            DELETE FROM shared_bill_cycles
            WHERE shared_vault_id = ?
            """,
            (vault_id,)
        )

        cursor.execute(
            """
            DELETE FROM shared_bills
            WHERE shared_vault_id = ?
            OR category_id IN (
                SELECT id
                FROM categories
                WHERE vault_id = ?
            )
            """,
            (
                vault_id,
                vault_id
            )
        )

        cursor.execute(
            """
            DELETE FROM categories
            WHERE vault_id = ?
            """,
            (vault_id,)
        )

        cursor.execute(
            """
            DELETE FROM wishlist_items
            WHERE vault_id = ?
            """,
            (vault_id,)
        )

        cursor.execute(
            """
            DELETE FROM wishlist_categories
            WHERE vault_id = ?
            """,
            (vault_id,)
        )

        cursor.execute(
            """
            DELETE FROM monthly_cycles
            WHERE vault_id = ?
            """,
            (vault_id,)
        )

        cursor.execute(
            """
            DELETE FROM accounts
            WHERE vault_id = ?
            """,
            (vault_id,)
        )

        cursor.execute(
            """
            DELETE FROM vault_shares
            WHERE vault_id = ?
            OR shared_vault_id = ?
            """,
            (
                vault_id,
                vault_id
            )
        )

        cursor.execute(
            """
            DELETE FROM vaults
            WHERE id = ?
            """,
            (vault_id,)
        )

        conn.commit()
        clear_data_cache((
            "vaults",
            "accounts",
            "categories",
            "cycles",
            "dashboard",
            "planning",
            "reports",
            "shared_expenses",
            "shared_bills",
            "wishlist"
        ))

    finally:
        conn.close()

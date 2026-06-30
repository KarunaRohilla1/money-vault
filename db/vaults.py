from db.core import (
    ensure_default_category_with_cursor,
    get_connection,
    hash_pin
)


def vault_exists():

    conn = get_connection()

    count = conn.execute(
        "SELECT COUNT(*) FROM vaults"
    ).fetchone()[0]

    conn.close()

    return count > 0


def verify_pin(vault_name, pin):

    conn = get_connection()
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

    if vault:
        conn.execute(
            """
            UPDATE vaults
            SET pin_plain = ?
            WHERE id = ?
            AND (
                pin_plain IS NULL
                OR pin_plain = ''
            )
            """,
            (
                pin,
                vault[0]
            )
        )
        conn.commit()

    conn.close()

    return vault


def get_vaults():

    conn = get_connection()

    vaults = conn.execute(
        """
        SELECT id, name
        FROM vaults
        ORDER BY name
        """
    ).fetchall()

    conn.close()

    return vaults


def create_vault(
    name,
    pin,
    is_admin=False,
    vault_type="Individual",
    shared_vault_ids=None
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO vaults
        (
            name,
            pin_hash,
            pin_plain,
            month_start_day,
            vault_type,
            is_admin
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            hash_pin(pin),
            pin,
            1,
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
    conn.close()


def update_vault(
    vault_id,
    name,
    pin=None,
    is_admin=None,
    month_start_day=None,
    vault_type=None,
    shared_vault_ids=None
):

    vault_name = name.strip()

    if not vault_name:
        raise ValueError("Vault name is required.")

    conn = get_connection()

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
        conn.close()
        raise ValueError("A vault with this name already exists.")

    updates = [
        "name = ?"
    ]
    params = [
        vault_name
    ]

    if pin:
        updates.append(
            "pin_hash = ?"
        )
        params.append(
            hash_pin(pin)
        )
        updates.append(
            "pin_plain = ?"
        )
        params.append(
            pin
        )

    if is_admin is not None:
        updates.append(
            "is_admin = ?"
        )
        params.append(
            int(is_admin)
        )

    if month_start_day is not None:
        updates.append(
            "month_start_day = ?"
        )
        params.append(
            int(month_start_day)
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
            INSERT OR IGNORE INTO vault_shares (
                vault_id,
                shared_vault_id
            )
            VALUES (?, ?)
            """,
            (
                vault_id,
                int(shared_vault_id)
            )
        )


def get_vault_share_ids(vault_id):

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT shared_vault_id
        FROM vault_shares
        WHERE vault_id = ?
        ORDER BY shared_vault_id
        """,
        (vault_id,)
    ).fetchall()

    conn.close()

    return [
        row[0]
        for row in rows
    ]


def get_vault_by_id(vault_id):

    conn = get_connection()

    vault = conn.execute(
        """
        SELECT
            id,
            name,
            is_admin,
            pin_plain,
            month_start_day,
            vault_type
        FROM vaults
        WHERE id = ?
        """,
        (vault_id,)
    ).fetchone()

    conn.close()

    return vault


def get_all_vaults():

    conn = get_connection()

    vaults = conn.execute(
        """
        SELECT
            id,
            name,
            is_admin,
            pin_plain,
            month_start_day,
            vault_type
        FROM vaults
        ORDER BY name
        """
    ).fetchall()

    conn.close()

    return vaults


def promote_to_admin(vault_name):

    conn = get_connection()

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
    conn.close()

    return affected_rows


def demote_admin(vault_name):

    conn = get_connection()

    conn.execute(
        """
        UPDATE vaults
        SET is_admin = 0
        WHERE name = ?
        """,
        (vault_name,)
    )

    conn.commit()
    conn.close()


def get_admin_count():

    conn = get_connection()

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM vaults
        WHERE is_admin = 1
        """
    ).fetchone()[0]

    conn.close()

    return count


def delete_vault(vault_id):

    conn = get_connection()
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
        DELETE FROM transactions
        WHERE vault_id = ?
        """,
        (vault_id,)
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
    conn.close()

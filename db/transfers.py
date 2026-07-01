import uuid

from db.core import (
    TRANSFER_IN,
    TRANSFER_OUT,
    get_connection
)
from db.cache import cache_data, clear_data_cache


def add_transfer(
    vault_id,
    from_account_id,
    to_account_id,
    transfer_date,
    amount,
    notes=""
):

    conn = get_connection()
    transfer_group_id = str(
        uuid.uuid4()
    )

    conn.execute(
        """
        INSERT INTO transactions
        (
            vault_id,
            account_id,
            date,
            amount,
            transaction_type,
            notes,
            transfer_group_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            vault_id,
            from_account_id,
            transfer_date,
            amount,
            TRANSFER_OUT,
            notes,
            transfer_group_id
        )
    )

    conn.execute(
        """
        INSERT INTO transactions
        (
            vault_id,
            account_id,
            date,
            amount,
            transaction_type,
            notes,
            transfer_group_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            vault_id,
            to_account_id,
            transfer_date,
            amount,
            TRANSFER_IN,
            notes,
            transfer_group_id
        )
    )

    conn.commit()
    conn.close()
    clear_data_cache()

    return transfer_group_id


@cache_data(ttl=60)
def get_transfers(
    vault_id,
    date_from=None,
    date_to=None,
    account_id=None,
    limit=None
):

    conn = get_connection()

    query = """
    SELECT
        out_t.transfer_group_id,
        out_t.date,
        out_t.account_id,
        from_a.name,
        in_t.account_id,
        to_a.name,
        out_t.amount,
        out_t.notes
    FROM transactions out_t
    JOIN transactions in_t
        ON out_t.transfer_group_id = in_t.transfer_group_id
        AND in_t.transaction_type = ?
        AND in_t.is_deleted = 0
    JOIN accounts from_a
        ON out_t.account_id = from_a.id
    JOIN accounts to_a
        ON in_t.account_id = to_a.id
    WHERE out_t.vault_id = ?
    AND out_t.transaction_type = ?
    AND out_t.transfer_group_id IS NOT NULL
    AND out_t.is_deleted = 0
    """

    params = [
        TRANSFER_IN,
        vault_id,
        TRANSFER_OUT
    ]

    if date_from:

        query += """
        AND out_t.date >= ?
        """
        params.append(date_from)

    if date_to:

        query += """
        AND out_t.date <= ?
        """
        params.append(date_to)

    if account_id:

        query += """
        AND (
            out_t.account_id = ?
            OR in_t.account_id = ?
        )
        """
        params.extend([
            account_id,
            account_id
        ])

    query += """
    ORDER BY out_t.date DESC, out_t.id DESC
    """

    if limit:

        query += """
        LIMIT ?
        """
        params.append(limit)

    transfers = conn.execute(
        query,
        params
    ).fetchall()

    conn.close()

    return transfers

@cache_data(ttl=60)
def get_transfer_by_group(
    transfer_group_id
):

    conn = get_connection()

    transfer = conn.execute(
        """
        SELECT
            out_t.transfer_group_id,
            out_t.vault_id,
            out_t.date,
            out_t.account_id,
            in_t.account_id,
            out_t.amount,
            out_t.notes
        FROM transactions out_t
        JOIN transactions in_t
            ON out_t.transfer_group_id = in_t.transfer_group_id
            AND in_t.transaction_type = ?
            AND in_t.is_deleted = 0
        WHERE out_t.transfer_group_id = ?
        AND out_t.transaction_type = ?
        AND out_t.is_deleted = 0
        """,
        (
            TRANSFER_IN,
            transfer_group_id,
            TRANSFER_OUT
        )
    ).fetchone()

    conn.close()

    return transfer


def update_transfer(
    transfer_group_id,
    from_account_id,
    to_account_id,
    transfer_date,
    amount,
    notes=""
):

    conn = get_connection()

    conn.execute(
        """
        UPDATE transactions
        SET
            account_id = ?,
            date = ?,
            amount = ?,
            notes = ?
        WHERE transfer_group_id = ?
        AND transaction_type = ?
        """,
        (
            from_account_id,
            transfer_date,
            amount,
            notes,
            transfer_group_id,
            TRANSFER_OUT
        )
    )

    conn.execute(
        """
        UPDATE transactions
        SET
            account_id = ?,
            date = ?,
            amount = ?,
            notes = ?
        WHERE transfer_group_id = ?
        AND transaction_type = ?
        """,
        (
            to_account_id,
            transfer_date,
            amount,
            notes,
            transfer_group_id,
            TRANSFER_IN
        )
    )

    conn.commit()
    conn.close()
    clear_data_cache()


def delete_transfer(
    transfer_group_id
):

    conn = get_connection()

    conn.execute(
        """
        DELETE FROM transactions
        WHERE transfer_group_id = ?
        """,
        (transfer_group_id,)
    )

    conn.commit()
    conn.close()
    clear_data_cache()

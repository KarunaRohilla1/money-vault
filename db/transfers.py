import uuid

from db.core import (
    TRANSFER_IN,
    TRANSFER_OUT,
    get_connection
)
from db.cache import cache_data, clear_data_cache


class TransferPairIntegrityError(Exception):
    pass


def rollback_connection(conn):
    rollback = getattr(conn, "rollback", None)
    if rollback:
        rollback()


def require_valid_transfer_pair(
    transfer_group_id,
    vault_id=None,
    conn=None
):
    owns_connection = conn is None
    connection = conn or get_connection()
    try:
        rows = connection.execute(
            """
            SELECT id, vault_id, transaction_type
            FROM transactions
            WHERE transfer_group_id = ?
            AND is_deleted = 0
            """,
            (transfer_group_id,)
        ).fetchall()

        if vault_id is not None and any(int(row[1]) != int(vault_id) for row in rows):
            raise TransferPairIntegrityError("Transfer pair is corrupted.")

        transfer_out_rows = [row for row in rows if row[2] == TRANSFER_OUT]
        transfer_in_rows = [row for row in rows if row[2] == TRANSFER_IN]

        if len(rows) != 2 or len(transfer_out_rows) != 1 or len(transfer_in_rows) != 1:
            raise TransferPairIntegrityError("Transfer pair is corrupted.")

        return {
            "in_id": transfer_in_rows[0][0],
            "out_id": transfer_out_rows[0][0]
        }
    finally:
        if owns_connection:
            connection.close()


def add_transfer(
    vault_id,
    from_account_id,
    to_account_id,
    transfer_date,
    amount,
    notes=""
):

    conn = get_connection()
    try:
        transfer_group_id = str(
            uuid.uuid4()
        )

        out_cursor = conn.execute(
            """
            INSERT INTO transactions
            (
                vault_id,
                beneficiary_vault_id,
                account_id,
                date,
                amount,
                transaction_type,
                notes,
                transfer_group_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vault_id,
                vault_id,
                from_account_id,
                transfer_date,
                amount,
                TRANSFER_OUT,
                notes,
                transfer_group_id
            )
            ,
            capture_lastrowid=False
        )

        in_cursor = conn.execute(
            """
            INSERT INTO transactions
            (
                vault_id,
                beneficiary_vault_id,
                account_id,
                date,
                amount,
                transaction_type,
                notes,
                transfer_group_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vault_id,
                vault_id,
                to_account_id,
                transfer_date,
                amount,
                TRANSFER_IN,
                notes,
                transfer_group_id
            )
            ,
            capture_lastrowid=False
        )

        if getattr(out_cursor, "rowcount", 1) != 1 or getattr(in_cursor, "rowcount", 1) != 1:
            raise TransferPairIntegrityError("Transfer pair is corrupted.")

        conn.commit()
        clear_data_cache((
            "transfers",
            "transactions",
            "accounts",
            "dashboard",
            "reports"
        ))

        return transfer_group_id


    except Exception:
        rollback_connection(conn)
        raise

    finally:
        conn.close()
@cache_data(ttl=60)
def get_transfers(
    vault_id,
    date_from=None,
    date_to=None,
    account_id=None,
    source_account_id=None,
    destination_account_id=None,
    limit=None
):

    conn = get_connection()
    try:

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

        if source_account_id:

            query += """
            AND out_t.account_id = ?
            """
            params.append(source_account_id)

        if destination_account_id:

            query += """
            AND in_t.account_id = ?
            """
            params.append(destination_account_id)

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


        return transfers

    finally:
        conn.close()
@cache_data(ttl=60)
def get_transfer_by_group(
    transfer_group_id
):

    conn = get_connection()
    try:

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


        return transfer


    finally:
        conn.close()
def update_transfer(
    transfer_group_id,
    from_account_id,
    to_account_id,
    transfer_date,
    amount,
    notes=""
):

    conn = get_connection()
    try:
        pair = require_valid_transfer_pair(
            transfer_group_id,
            conn=conn
        )

        out_cursor = conn.execute(
            """
            UPDATE transactions
            SET
                account_id = ?,
                date = ?,
                amount = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                from_account_id,
                transfer_date,
                amount,
                notes,
                pair["out_id"]
            )
        )

        in_cursor = conn.execute(
            """
            UPDATE transactions
            SET
                account_id = ?,
                date = ?,
                amount = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                to_account_id,
                transfer_date,
                amount,
                notes,
                pair["in_id"]
            )
        )

        if getattr(out_cursor, "rowcount", 0) != 1 or getattr(in_cursor, "rowcount", 0) != 1:
            raise TransferPairIntegrityError("Transfer pair is corrupted.")

        conn.commit()
        clear_data_cache((
            "transfers",
            "transactions",
            "accounts",
            "dashboard",
            "reports"
        ))


    except Exception:
        rollback_connection(conn)
        raise

    finally:
        conn.close()
def delete_transfer(
    transfer_group_id
):

    conn = get_connection()
    try:
        pair = require_valid_transfer_pair(
            transfer_group_id,
            conn=conn
        )

        cursor = conn.execute(
            """
            DELETE FROM transactions
            WHERE id IN (?, ?)
            """,
            (
                pair["out_id"],
                pair["in_id"]
            )
        )

        if getattr(cursor, "rowcount", 0) != 2:
            raise TransferPairIntegrityError("Transfer pair is corrupted.")

        conn.commit()
        clear_data_cache((
            "transfers",
            "transactions",
            "accounts",
            "dashboard",
            "reports"
        ))

    except Exception:
        rollback_connection(conn)
        raise

    finally:
        conn.close()

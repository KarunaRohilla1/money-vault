from db.cache import cache_data, clear_data_cache
from db.core import get_connection


def add_transaction(
    vault_id,
    account_id,
    date,
    amount,
    category_id,
    transaction_type,
    notes
):

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO transactions
        (
            vault_id,
            account_id,
            date,
            amount,
            category_id,
            transaction_type,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            vault_id,
            account_id,
            date,
            amount,
            category_id,
            transaction_type,
            notes
        )
    )

    conn.commit()
    conn.close()
    clear_data_cache()

@cache_data(ttl=60)
def get_transactions(vault_id):

    conn = get_connection()

    transactions = conn.execute(
        """
        SELECT
            t.id,
            t.date,
            a.name,
            COALESCE(c.emoji || ' ' || c.name, t.transaction_type),
            t.amount,
            t.transaction_type,
            t.notes,
            t.transfer_group_id

        FROM transactions t

        LEFT JOIN accounts a
            ON t.account_id = a.id

        LEFT JOIN categories c
            ON t.category_id = c.id

        WHERE t.vault_id = ?
        AND t.is_deleted = 0

        ORDER BY t.date DESC, t.id DESC
        """,
        (vault_id,)
    ).fetchall()

    conn.close()

    return transactions

@cache_data(ttl=60)
def get_filtered_transactions(
    vault_id,
    month=None,
    category=None,
    account=None,
    search=None,
    sort_by="Newest"
):

    conn = get_connection()

    query = """
    SELECT
        t.id,
        t.date,
        a.name,
        COALESCE(c.emoji || ' ' || c.name, t.transaction_type),
        t.amount,
        t.transaction_type,
        t.notes,
        t.transfer_group_id

    FROM transactions t

    LEFT JOIN accounts a
        ON t.account_id = a.id

    LEFT JOIN categories c
        ON t.category_id = c.id

    WHERE t.vault_id = ?
    AND t.is_deleted = 0
    """

    params = [vault_id]

    if month:
        query += """
        AND to_char(t.date::date, 'YYYY-MM') = ?
        """
        params.append(month)

    if category and category != "All":
        query += """
        AND c.name = ?
        """
        params.append(category)

    if account and account != "All":
        query += """
        AND a.name = ?
        """
        params.append(account)

    if search:
        query += """
        AND (
            LOWER(COALESCE(t.notes,'')) LIKE ?
            OR LOWER(c.name) LIKE ?
            OR LOWER(a.name) LIKE ?
        )
        """

        search_term = f"%{search.lower()}%"

        params.extend([
            search_term,
            search_term,
            search_term
        ])

    if sort_by == "Oldest":
        query += """
        ORDER BY t.date ASC, t.id ASC
        """
    elif sort_by == "Amount High":
        query += """
        ORDER BY t.amount DESC
        """
    elif sort_by == "Amount Low":
        query += """
        ORDER BY t.amount ASC
        """
    else:
        query += """
        ORDER BY t.date DESC, t.id DESC
        """

    transactions = conn.execute(
        query,
        params
    ).fetchall()

    conn.close()

    return transactions


def delete_transaction(transaction_id):

    conn = get_connection()
    cursor = conn.cursor()

    transfer_group = cursor.execute(
        """
        SELECT transfer_group_id
        FROM transactions
        WHERE id = ?
        """,
        (transaction_id,)
    ).fetchone()

    if (
        transfer_group
        and transfer_group[0]
    ):

        cursor.execute(
            """
            DELETE FROM transactions
            WHERE transfer_group_id = ?
            """,
            (transfer_group[0],)
        )

        conn.commit()
        conn.close()
        clear_data_cache()

        return

    cursor.execute(
        """
        DELETE FROM transactions
        WHERE id = ?
        """,
        (transaction_id,)
    )

    cursor.execute(
        """
        UPDATE income_status
        SET
            actual_amount = NULL,
            status = 'PENDING',
            transaction_id = NULL
        WHERE transaction_id = ?
        """,
        (transaction_id,)
    )

    cursor.execute(
        """
        UPDATE obligation_status
        SET
            actual_amount = NULL,
            status = 'PENDING',
            transaction_id = NULL
        WHERE transaction_id = ?
        """,
        (transaction_id,)
    )

    conn.commit()
    conn.close()
    clear_data_cache()

@cache_data(ttl=60)
def get_transaction_by_id(transaction_id):

    conn = get_connection()

    transaction = conn.execute(
        """
        SELECT
            id,
            account_id,
            category_id,
            date,
            amount,
            transaction_type,
            notes
        FROM transactions
        WHERE id = ?
        """,
        (transaction_id,)
    ).fetchone()

    conn.close()

    return transaction


def update_transaction(
    transaction_id,
    account_id,
    category_id,
    date,
    amount,
    notes,
    transaction_type=None
):

    conn = get_connection()

    if transaction_type:

        conn.execute(
            """
            UPDATE transactions
            SET
                account_id = ?,
                category_id = ?,
                date = ?,
                amount = ?,
                transaction_type = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                account_id,
                category_id,
                date,
                amount,
                transaction_type,
                notes,
                transaction_id
            )
        )

    else:

        conn.execute(
            """
            UPDATE transactions
            SET
                account_id = ?,
                category_id = ?,
                date = ?,
                amount = ?,
                notes = ?
            WHERE id = ?
            """,
            (
                account_id,
                category_id,
                date,
                amount,
                notes,
                transaction_id
            )
        )

    conn.commit()
    conn.close()
    clear_data_cache()

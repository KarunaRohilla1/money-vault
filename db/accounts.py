from db.core import (
    ACCOUNT_TYPES,
    EXPENSE,
    INCOME,
    TRANSFER_IN,
    TRANSFER_OUT,
    get_connection
)
from db.cache import cache_data, clear_data_cache


def add_account(
    vault_id,
    name,
    account_type,
    opening_balance,
    is_primary=False
):

    conn = get_connection()
    try:
        cursor = conn.cursor()

        should_be_primary = is_primary or not cursor.execute(
            """
            SELECT 1
            FROM accounts
            WHERE vault_id = ?
            AND is_active = 1
            LIMIT 1
            """,
            (vault_id,)
        ).fetchone()

        if should_be_primary:
            cursor.execute(
                """
                UPDATE accounts
                SET is_primary = 0
                WHERE vault_id = ?
                """,
                (vault_id,)
            )

        cursor.execute(
            """
            INSERT INTO accounts
            (vault_id, name, type, opening_balance, is_primary)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                vault_id,
                name,
                account_type,
                opening_balance,
                1 if should_be_primary else 0
            )
            ,
            capture_lastrowid=False
        )

        conn.commit()
        clear_data_cache((
            "accounts",
            "dashboard",
            "reports",
            "planning",
            "transactions",
            "transfers",
            "shared_expenses",
            "shared_bills"
        ))

    finally:
        conn.close()
@cache_data(ttl=60)
def get_accounts(vault_id):

    conn = get_connection()
    try:

        accounts = conn.execute(
            """
            SELECT id, name, type, opening_balance, is_primary
            FROM accounts
            WHERE vault_id = ?
            AND is_active = 1
            ORDER BY is_primary DESC, type, name
            """,
            (vault_id,)
        ).fetchall()


        return accounts


    finally:
        conn.close()
@cache_data(ttl=60)
def get_accounts_with_balances(vault_id):

    conn = get_connection()
    try:

        accounts = conn.execute(
            """
            SELECT
                a.id,
                a.name,
                a.type,
                a.opening_balance,
                a.is_primary,
                a.opening_balance
                    + COALESCE(SUM(
                        CASE
                            WHEN t.transaction_type IN (?, ?) THEN t.amount
                            WHEN t.transaction_type IN (?, ?) THEN -t.amount
                            ELSE 0
                        END
                    ), 0) AS balance
            FROM accounts a
            LEFT JOIN transactions t
                ON t.account_id = a.id
                AND t.is_deleted = 0
            WHERE a.vault_id = ?
            AND a.is_active = 1
            GROUP BY
                a.id,
                a.name,
                a.type,
                a.opening_balance,
                a.is_primary
            ORDER BY a.is_primary DESC, a.type, a.name
            """,
            (
                INCOME,
                TRANSFER_IN,
                EXPENSE,
                TRANSFER_OUT,
                vault_id
            )
        ).fetchall()


        return accounts


    finally:
        conn.close()
def archive_account(account_id):

    conn = get_connection()
    try:
        cursor = conn.cursor()

        account = cursor.execute(
            """
            SELECT vault_id, is_primary
            FROM accounts
            WHERE id = ?
            """,
            (account_id,)
        ).fetchone()

        cursor.execute(
            """
            UPDATE accounts
            SET
                is_active = 0,
                is_primary = 0
            WHERE id = ?
            """,
            (account_id,)
        )

        if account and account[1]:
            cursor.execute(
                """
                UPDATE accounts
                SET is_primary = 1
                WHERE id = (
                    SELECT MIN(id)
                    FROM accounts
                    WHERE vault_id = ?
                    AND is_active = 1
                )
                """,
                (account[0],)
            )

        conn.commit()
        clear_data_cache((
            "accounts",
            "dashboard",
            "reports",
            "planning",
            "transactions",
            "transfers",
            "shared_expenses",
            "shared_bills"
        ))

    finally:
        conn.close()
@cache_data(ttl=60)
def get_account_balance(account_id):

    conn = get_connection()
    try:

        opening_balance = conn.execute(
            """
            SELECT opening_balance
            FROM accounts
            WHERE id = ?
            """,
            (account_id,)
        ).fetchone()[0]

        credits = conn.execute(
            """
            SELECT
                COALESCE(SUM(amount),0)
            FROM transactions
            WHERE account_id = ?
            AND transaction_type IN (?, ?)
            AND is_deleted = 0
            """,
            (
                account_id,
                INCOME,
                TRANSFER_IN
            )
        ).fetchone()[0]

        debits = conn.execute(
            """
            SELECT
                COALESCE(SUM(amount),0)
            FROM transactions
            WHERE account_id = ?
            AND transaction_type IN (?, ?)
            AND is_deleted = 0
            """,
            (
                account_id,
                EXPENSE,
                TRANSFER_OUT
            )
        ).fetchone()[0]


        return (
            opening_balance
            + credits
            - debits
        )


    finally:
        conn.close()
@cache_data(ttl=60)
def get_account_balances(vault_id):

    conn = get_connection()
    try:

        rows = conn.execute(
            """
            SELECT
                a.id,
                a.opening_balance
                    + COALESCE(SUM(
                        CASE
                            WHEN t.transaction_type IN (?, ?) THEN t.amount
                            WHEN t.transaction_type IN (?, ?) THEN -t.amount
                            ELSE 0
                        END
                    ), 0) AS balance
            FROM accounts a
            LEFT JOIN transactions t
                ON t.account_id = a.id
                AND t.is_deleted = 0
            WHERE a.vault_id = ?
            AND a.is_active = 1
            GROUP BY a.id, a.opening_balance
            """,
            (
                INCOME,
                TRANSFER_IN,
                EXPENSE,
                TRANSFER_OUT,
                vault_id
            )
        ).fetchall()


        return {
            row[0]: row[1]
            for row in rows
        }


    finally:
        conn.close()
def get_credit_card_due(account_id):

    balance = get_account_balance(
        account_id
    )

    if balance < 0:
        return abs(balance)

    return 0


def get_total_credit_card_due(vault_id):

    accounts = get_accounts(
        vault_id
    )
    balances = get_account_balances(
        vault_id
    )

    total_due = 0

    for account in accounts:

        if account[2] == "Credit Card":

            balance = balances.get(
                account[0],
                0
            )

            if balance < 0:
                total_due += abs(balance)

    return total_due


def update_account(
    account_id,
    name,
    account_type,
    opening_balance,
    is_primary=False
):

    conn = get_connection()
    try:
        cursor = conn.cursor()

        if is_primary:
            vault = cursor.execute(
                """
                SELECT vault_id
                FROM accounts
                WHERE id = ?
                """,
                (account_id,)
            ).fetchone()

            if vault:
                cursor.execute(
                    """
                    UPDATE accounts
                    SET is_primary = 0
                    WHERE vault_id = ?
                    """,
                    (vault[0],)
                )

        cursor.execute(
            """
            UPDATE accounts
            SET
                name = ?,
                type = ?,
                opening_balance = ?,
                is_primary = CASE
                    WHEN ? = 1 THEN 1
                    ELSE is_primary
                END
            WHERE id = ?
            """,
            (
                name,
                account_type,
                opening_balance,
                1 if is_primary else 0,
                account_id
            )
        )

        conn.commit()
        clear_data_cache((
            "accounts",
            "dashboard",
            "reports",
            "planning",
            "transactions",
            "transfers",
            "shared_expenses",
            "shared_bills"
        ))

    finally:
        conn.close()
@cache_data(ttl=60)
def get_account_by_id(account_id):

    conn = get_connection()
    try:

        account = conn.execute(
            """
            SELECT
                id,
                name,
                type,
                opening_balance,
                is_primary,
                vault_id
            FROM accounts
            WHERE id = ?
            """,
            (account_id,)
        ).fetchone()


        return account


    finally:
        conn.close()
def set_primary_account(account_id):

    conn = get_connection()
    try:
        cursor = conn.cursor()

        account = cursor.execute(
            """
            SELECT vault_id
            FROM accounts
            WHERE id = ?
            AND is_active = 1
            """,
            (account_id,)
        ).fetchone()

        if not account:
            return

        cursor.execute(
            """
            UPDATE accounts
            SET is_primary = 0
            WHERE vault_id = ?
            """,
            (account[0],)
        )

        cursor.execute(
            """
            UPDATE accounts
            SET is_primary = 1
            WHERE id = ?
            """,
            (account_id,)
        )

        conn.commit()
        clear_data_cache((
            "accounts",
            "dashboard",
            "reports",
            "planning",
            "transactions",
            "transfers",
            "shared_expenses",
            "shared_bills"
        ))

    finally:
        conn.close()
@cache_data(ttl=60)
def get_primary_account(vault_id):

    conn = get_connection()
    try:

        account = conn.execute(
            """
            SELECT id, name, type, opening_balance, is_primary
            FROM accounts
            WHERE vault_id = ?
            AND is_active = 1
            ORDER BY is_primary DESC, type, name
            LIMIT 1
            """,
            (vault_id,)
        ).fetchone()


        return account


    finally:
        conn.close()
def account_exists(
    vault_id,
    name,
    exclude_account_id=None
):

    conn = get_connection()
    try:

        query = """
        SELECT id
        FROM accounts
        WHERE vault_id = ?
        AND LOWER(name) = LOWER(?)
        AND is_active = 1
        """

        params = [
            vault_id,
            name
        ]

        if exclude_account_id:

            query += """
            AND id != ?
            """

            params.append(
                exclude_account_id
            )

        result = conn.execute(
            query,
            params
        ).fetchone()


        return result is not None

    finally:
        conn.close()
@cache_data(ttl=60)
def account_has_transactions(account_id):

    conn = get_connection()
    try:

        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM transactions
            WHERE account_id = ?
            """,
            (account_id,)
        ).fetchone()[0]


        return count > 0

    finally:
        conn.close()

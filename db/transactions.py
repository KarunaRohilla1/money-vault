from db.cache import cache_data, clear_data_cache
from db.core import get_connection
from db.transaction_shares import (
    ALLOCATION_PERCENTAGE,
    calculate_transaction_shares,
    replace_transaction_shares_with_cursor,
    shared_expense_schema_ready,
    validate_transaction_shares
)


def validate_transaction_category_with_cursor(
    cursor,
    category_id,
    origin_vault_id,
    beneficiary_vault_id
):
    row = cursor.execute(
        """
        SELECT
            COALESCE(c.is_system, 0),
            origin.vault_type,
            beneficiary.vault_type
        FROM categories c
        JOIN vaults origin
            ON origin.id = ?
        JOIN vaults beneficiary
            ON beneficiary.id = ?
        WHERE c.id = ?
        """,
        (
            origin_vault_id,
            beneficiary_vault_id,
            category_id
        )
    ).fetchone()

    if not row:
        raise ValueError("Selected category no longer exists.")

    is_system = bool(row[0])
    uses_shared_vault = (
        row[1] == "Shared"
        or row[2] == "Shared"
    )

    if uses_shared_vault and not is_system:
        raise ValueError(
            "Shared transactions can only use system categories."
        )


def add_transaction(
    vault_id,
    account_id,
    date,
    amount,
    category_id,
    transaction_type,
    notes,
    beneficiary_vault_id=None,
    allocation_method=None,
    participant_vaults=None,
    percentage_allocations=None,
    amount_allocations=None
):

    conn = get_connection()
    try:
        cursor = conn.cursor()
        beneficiary_vault_id = beneficiary_vault_id or vault_id
        is_shared = int(beneficiary_vault_id) != int(vault_id)
        shares = []
        schema_ready = shared_expense_schema_ready()

        validate_transaction_category_with_cursor(
            cursor,
            category_id,
            vault_id,
            beneficiary_vault_id
        )

        if is_shared and not schema_ready:
            raise ValueError("Shared expense schema is not installed yet. Run the Supabase schema migration.")

        if is_shared:
            shares = calculate_transaction_shares(
                amount,
                allocation_method,
                participant_vaults or [],
                percentage_allocations,
                amount_allocations
            )
            validate_transaction_shares(
                amount,
                shares,
                allocation_method == ALLOCATION_PERCENTAGE
            )
        else:
            allocation_method = None

        if schema_ready:
            cursor.execute(
                """
                INSERT INTO transactions
                (
                    vault_id,
                    beneficiary_vault_id,
                    account_id,
                    date,
                    amount,
                    category_id,
                    transaction_type,
                    allocation_method,
                    notes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    vault_id,
                    beneficiary_vault_id,
                    account_id,
                    date,
                    amount,
                    category_id,
                    transaction_type,
                    allocation_method,
                    notes
                )
            )
        else:
            cursor.execute(
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

        transaction_id = cursor.lastrowid

        if is_shared:
            replace_transaction_shares_with_cursor(
                cursor,
                transaction_id,
                shares
            )

        conn.commit()
        clear_data_cache()

        return transaction_id

    finally:
        conn.close()

@cache_data(ttl=60)
def get_transactions(vault_id):

    conn = get_connection()
    try:

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


        return transactions


    finally:
        conn.close()
@cache_data(ttl=60)
def get_recent_activity_transactions(vault_id, limit=5):

    conn = get_connection()
    try:

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
            AND t.amount != 0
            AND t.transaction_type NOT IN ('Transfer In', 'Transfer Out')

            ORDER BY t.date DESC, t.id DESC
            LIMIT ?
            """,
            (
                vault_id,
                limit
            )
        ).fetchall()


        return transactions


    finally:
        conn.close()
@cache_data(ttl=60)
def get_filtered_transactions(
    vault_id,
    month=None,
    category=None,
    account=None,
    search=None,
    sort_by="Newest",
    date_from=None,
    date_to=None
):

    conn = get_connection()
    try:

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

        if date_from and date_to:
            query += """
            AND t.date::date BETWEEN ? AND ?
            """
            params.extend([date_from, date_to])

        elif month == "LAST_3_MONTHS":
            query += """
            AND t.date::date >= (CURRENT_DATE - INTERVAL '3 months')::date
            """

        elif month == "THIS_YEAR":
            query += """
            AND EXTRACT(YEAR FROM t.date::date) = EXTRACT(YEAR FROM CURRENT_DATE)
            """

        elif month:
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


        return transactions


    finally:
        conn.close()
def delete_transaction(transaction_id):

    conn = get_connection()
    try:
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
        clear_data_cache()

    finally:
        conn.close()
@cache_data(ttl=60)
def get_transaction_by_id(transaction_id):

    conn = get_connection()
    try:
        if not shared_expense_schema_ready():
            transaction = conn.execute(
                """
                SELECT
                    id,
                    account_id,
                    category_id,
                    date,
                    amount,
                    transaction_type,
                    notes,
                    vault_id,
                    NULL
                FROM transactions
                WHERE id = ?
                """,
                (transaction_id,)
            ).fetchone()

            return transaction

        transaction = conn.execute(
            """
            SELECT
                id,
                account_id,
                category_id,
                date,
                amount,
                transaction_type,
                notes,
                beneficiary_vault_id,
                allocation_method
            FROM transactions
            WHERE id = ?
            """,
            (transaction_id,)
        ).fetchone()


        return transaction


    finally:
        conn.close()
def update_transaction(
    transaction_id,
    account_id,
    category_id,
    date,
    amount,
    notes,
    transaction_type=None,
    vault_id=None,
    beneficiary_vault_id=None,
    allocation_method=None,
    participant_vaults=None,
    percentage_allocations=None,
    amount_allocations=None
):

    conn = get_connection()
    try:
        cursor = conn.cursor()
        existing = cursor.execute(
            """
            SELECT vault_id
            FROM transactions
            WHERE id = ?
            """,
            (transaction_id,)
        ).fetchone()

        if not existing:
            raise ValueError("Transaction not found.")

        origin_vault_id = vault_id or existing[0]
        beneficiary_vault_id = beneficiary_vault_id or origin_vault_id
        is_shared = int(beneficiary_vault_id) != int(origin_vault_id)
        shares = []
        schema_ready = shared_expense_schema_ready()

        validate_transaction_category_with_cursor(
            cursor,
            category_id,
            origin_vault_id,
            beneficiary_vault_id
        )

        if is_shared and not schema_ready:
            raise ValueError("Shared expense schema is not installed yet. Run the Supabase schema migration.")

        if is_shared:
            shares = calculate_transaction_shares(
                amount,
                allocation_method,
                participant_vaults or [],
                percentage_allocations,
                amount_allocations
            )
            validate_transaction_shares(
                amount,
                shares,
                allocation_method == ALLOCATION_PERCENTAGE
            )
        else:
            allocation_method = None

        if not schema_ready:
            if transaction_type:

                cursor.execute(
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

                cursor.execute(
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
            clear_data_cache()
            return

        if transaction_type:

            cursor.execute(
                """
                UPDATE transactions
                SET
                    account_id = ?,
                    category_id = ?,
                    date = ?,
                    amount = ?,
                    beneficiary_vault_id = ?,
                    transaction_type = ?,
                    allocation_method = ?,
                    notes = ?
                WHERE id = ?
                """,
                (
                    account_id,
                    category_id,
                    date,
                    amount,
                    beneficiary_vault_id,
                    transaction_type,
                    allocation_method,
                    notes,
                    transaction_id
                )
            )

        else:

            cursor.execute(
                """
                UPDATE transactions
                SET
                    account_id = ?,
                    category_id = ?,
                    date = ?,
                    amount = ?,
                    beneficiary_vault_id = ?,
                    allocation_method = ?,
                    notes = ?
                WHERE id = ?
                """,
                (
                    account_id,
                    category_id,
                    date,
                    amount,
                    beneficiary_vault_id,
                    allocation_method,
                    notes,
                    transaction_id
                )
            )

        replace_transaction_shares_with_cursor(
            cursor,
            transaction_id,
            shares
        )

        conn.commit()
        clear_data_cache()

    finally:
        conn.close()

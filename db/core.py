import hashlib
import calendar
import uuid

from db.postgres import connect, execute_schema

# ==================================================
# DATABASE SETUP
# ==================================================

ACCOUNT_TYPES = [
    "Salary Account",
    "Savings Account",
    "Credit Card",
    "Cash",
    "Wallet",
    "Other"
]

INCOME = "Income"
EXPENSE = "Expense"
TRANSFER_IN = "Transfer In"
TRANSFER_OUT = "Transfer Out"
DEFAULT_CATEGORY_NAME = "Default"
DEFAULT_CATEGORY_EMOJI = "🏷️"
DEFAULT_CATEGORY_TYPE = EXPENSE

CANONICAL_SYSTEM_CATEGORIES = [
    ("Default", "🏷️", "Miscellaneous"),
    ("Groceries", "🛒", "Household"),
    ("Home", "🏡", "Household"),
    ("Dining Out", "🍽", "Food & Drinks"),
    ("Coffee", "☕", "Food & Drinks"),
    ("Food Delivery", "🛵", "Food & Drinks"),
    ("Fuel", "⛽", "Transport"),
    ("Transport", "🚕", "Transport"),
    ("Medical", "🏥", "Health"),
    ("Fitness", "💪", "Health"),
    ("Shopping", "🛍", "Shopping"),
    ("Entertainment", "🎬", "Lifestyle"),
    ("Subscriptions", "📺", "Lifestyle"),
    ("Travel", "✈️", "Lifestyle"),
    ("Miscellaneous", "📦", "Miscellaneous"),
]

def get_connection():
    return connect()

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()


def initialize_database():
    execute_schema()

def migrate_database():
    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            UPDATE accounts
            SET is_primary = 1
            WHERE id IN (
                SELECT MIN(id)
                FROM accounts
                WHERE is_active = 1
                GROUP BY vault_id
                HAVING SUM(is_primary) = 0
            )
            """
        )

        cursor.execute(
            """
            UPDATE categories
            SET
                vault_id = NULL,
                emoji = ?,
                category_type = ?,
                is_system = 1,
                is_active = 1
            WHERE LOWER(name) = LOWER(?)
            AND is_system = 1
            """,
            (
                DEFAULT_CATEGORY_EMOJI,
                DEFAULT_CATEGORY_TYPE,
                DEFAULT_CATEGORY_NAME,
            )
        )

        cursor.execute("""
        UPDATE transactions
        SET beneficiary_vault_id = vault_id
        WHERE beneficiary_vault_id IS NULL
        """)

        from db.wishlist import ensure_wishlist_schema_with_cursor
        from capture.models import ensure_capture_schema_with_cursor
        from db.settlements import ensure_settlements_schema_with_cursor
        from db.identity import ensure_identity_schema_with_cursor

        ensure_wishlist_schema_with_cursor(cursor)
        ensure_capture_schema_with_cursor(cursor)
        ensure_settlements_schema_with_cursor(cursor)
        ensure_identity_schema_with_cursor(cursor)

        cursor.execute("""
        INSERT INTO wishlist_categories (vault_id, name)
        SELECT DISTINCT vault_id, TRIM(category)
        FROM wishlist_items
        WHERE TRIM(COALESCE(category, '')) != ''
        ON CONFLICT (vault_id, name) DO NOTHING
        """, capture_lastrowid=False)

        cursor.execute(
            """
            UPDATE vaults
            SET financial_cycle_start_day = COALESCE(financial_cycle_start_day, month_start_day, 1)
            """
        )

        ensure_default_categories_with_cursor(
            cursor
        )

        backfill_transfer_groups_with_cursor(
            cursor
        )

        conn.commit()

    finally:
        conn.close()


def setup_application_data():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        ensure_default_categories_with_cursor(
            cursor
        )
        conn.commit()
    finally:
        conn.close()

    from db.financial_cycles import initialize_financial_cycles
    from db.shared_bills import initialize_shared_bill_cycles

    initialize_financial_cycles()
    initialize_shared_bill_cycles()


def backfill_transfer_groups_with_cursor(
    cursor
):

    rows = cursor.execute(
        """
        SELECT
            id,
            vault_id,
            date,
            amount,
            transaction_type,
            COALESCE(notes, '')
        FROM transactions
        WHERE transfer_group_id IS NULL
        AND transaction_type IN (?, ?)
        AND is_deleted = 0
        ORDER BY vault_id, date, amount, notes, id
        """,
        (
            TRANSFER_OUT,
            TRANSFER_IN
        )
    ).fetchall()

    pending_out = {}

    for row in rows:

        row_id = row[0]
        key = (
            row[1],
            row[2],
            row[3],
            row[5]
        )
        transaction_type = row[4]

        if transaction_type == TRANSFER_OUT:

            pending_out.setdefault(
                key,
                []
            ).append(row_id)

        elif (
            transaction_type == TRANSFER_IN
            and pending_out.get(key)
        ):

            out_id = pending_out[key].pop(0)
            group_id = str(
                uuid.uuid4()
            )

            cursor.execute(
                """
                UPDATE transactions
                SET transfer_group_id = ?
                WHERE id IN (?, ?)
                """,
                (
                    group_id,
                    out_id,
                    row_id
                )
            )

def ensure_canonical_system_categories_with_cursor(
    cursor
):
    for name, emoji, parent_category in CANONICAL_SYSTEM_CATEGORIES:
        existing = cursor.execute(
            """
            SELECT id
            FROM categories
            WHERE is_system = 1
            AND LOWER(name) = LOWER(?)
            """,
            (name,)
        ).fetchone()

        if existing:
            cursor.execute(
                """
                UPDATE categories
                SET
                    vault_id = NULL,
                    emoji = ?,
                    parent_category = ?,
                    category_type = ?,
                    is_system = 1,
                    is_active = 1
                WHERE id = ?
                """,
                (
                    emoji,
                    parent_category,
                    EXPENSE,
                    existing[0]
                )
            )
        else:
            cursor.execute(
                """
                INSERT INTO categories
                (
                    vault_id,
                    name,
                    emoji,
                    parent_category,
                    category_type,
                    is_system,
                    is_active
                )
                VALUES (NULL, ?, ?, ?, ?, 1, 1)
                """,
                (
                    name,
                    emoji,
                    parent_category,
                    EXPENSE
                )
            )

def ensure_default_categories_with_cursor(
    cursor
):
    ensure_canonical_system_categories_with_cursor(
        cursor
    )

    vaults = cursor.execute(
        """
        SELECT id
        FROM vaults
        """
    ).fetchall()

    default_category_id = ensure_default_category_with_cursor(
        cursor
    )

    for vault in vaults:
        backfill_planning_default_category_with_cursor(
            cursor,
            vault[0],
            default_category_id
        )

def ensure_default_category_with_cursor(
    cursor,
    vault_id=None
):
    ensure_canonical_system_categories_with_cursor(
        cursor
    )

    row = cursor.execute(
        """
        SELECT id
        FROM categories
        WHERE is_system = 1
        AND LOWER(name) = LOWER(?)
        AND is_active = 1
        """,
        (DEFAULT_CATEGORY_NAME,)
    ).fetchone()

    if row:
        return row[0]

    cursor.execute(
        """
        INSERT INTO categories
        (
            vault_id,
            name,
            emoji,
            parent_category,
            category_type,
            is_system,
            is_active
        )
        VALUES (NULL, ?, ?, 'Miscellaneous', ?, 1, 1)
        """,
        (
            DEFAULT_CATEGORY_NAME,
            DEFAULT_CATEGORY_EMOJI,
            DEFAULT_CATEGORY_TYPE
        )
    )

    return cursor.lastrowid

def ensure_default_category(
    vault_id
):

    conn = get_connection()
    try:
        cursor = conn.cursor()

        category_id = ensure_default_category_with_cursor(
            cursor,
            vault_id
        )

        backfill_planning_default_category_with_cursor(
            cursor,
            vault_id,
            category_id
        )

        conn.commit()

        return category_id

    finally:
        conn.close()
def backfill_planning_default_category_with_cursor(
    cursor,
    vault_id,
    category_id
):

    cursor.execute(
        """
        UPDATE transactions
        SET category_id = ?
        WHERE vault_id = ?
        AND category_id IS NULL
        AND notes LIKE 'Planning%'
        """,
        (
            category_id,
            vault_id
        )
    )

def get_planning_transaction_date(year, month, due_day):

    last_day = calendar.monthrange(
        year,
        month
    )[1]

    safe_day = min(
        int(due_day),
        last_day
    )

    return f"{year:04d}-{month:02d}-{safe_day:02d}"

def upsert_linked_transaction(
    cursor,
    transaction_id,
    vault_id,
    account_id,
    transaction_date,
    amount,
    transaction_type,
    notes
):

    category_id = ensure_default_category_with_cursor(
        cursor,
        vault_id
    )

    if transaction_id:

        existing = cursor.execute(
            """
            SELECT id
            FROM transactions
            WHERE id = ?
            """,
            (transaction_id,)
        ).fetchone()

        if existing:

            cursor.execute(
                """
                UPDATE transactions
                SET
                    vault_id = ?,
                    beneficiary_vault_id = ?,
                    account_id = ?,
                    category_id = ?,
                    date = ?,
                    amount = ?,
                    transaction_type = ?,
                    notes = ?,
                    is_deleted = 0
                WHERE id = ?
                """,
                (
                    vault_id,
                    vault_id,
                    account_id,
                    category_id,
                    transaction_date,
                    amount,
                    transaction_type,
                    notes,
                    transaction_id
                )
            )

            return transaction_id

    cursor.execute(
        """
        INSERT INTO transactions
        (
            vault_id,
            beneficiary_vault_id,
            account_id,
            category_id,
            date,
            amount,
            transaction_type,
            notes,
            is_deleted
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
            vault_id,
            vault_id,
            account_id,
            category_id,
            transaction_date,
            amount,
            transaction_type,
            notes
        )
    )

    return cursor.lastrowid

def delete_linked_transaction(
    cursor,
    transaction_id
):

    if transaction_id:

        cursor.execute(
            """
            DELETE FROM transactions
            WHERE id = ?
            """,
            (transaction_id,)
        )


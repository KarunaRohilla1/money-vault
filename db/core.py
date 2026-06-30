import sqlite3
import hashlib
import calendar
import uuid
from pathlib import Path

# ==================================================
# DATABASE SETUP
# ==================================================

DB_PATH = "data/money.db"

ACCOUNT_TYPES = [
    "Salary Account",
    "Savings Account",
    "Credit Card",
    "Investment",
    "Retirement"
]

INCOME = "Income"
EXPENSE = "Expense"
TRANSFER_IN = "Transfer In"
TRANSFER_OUT = "Transfer Out"
DEFAULT_CATEGORY_NAME = "Default"
DEFAULT_CATEGORY_EMOJI = "\U0001f3f7\ufe0f"
DEFAULT_CATEGORY_TYPE = EXPENSE

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "PRAGMA foreign_keys = ON"
    )
    return conn

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()


def backfill_plain_pins_with_cursor(cursor):
    rows = cursor.execute(
        """
        SELECT id, pin_hash
        FROM vaults
        WHERE pin_plain IS NULL
        OR pin_plain = ''
        """
    ).fetchall()

    pin_lookup = {
        hash_pin(f"{pin:04d}"): f"{pin:04d}"
        for pin in range(10000)
    }

    for vault_id, pin_hash in rows:
        pin = pin_lookup.get(pin_hash)

        if not pin:
            continue

        cursor.execute(
            """
            UPDATE vaults
            SET pin_plain = ?
            WHERE id = ?
            """,
            (
                pin,
                vault_id
            )
        )


def initialize_database():
    Path("data").mkdir(exist_ok=True)
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vaults (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        pin_hash TEXT NOT NULL,
        pin_plain TEXT,
        month_start_day INTEGER NOT NULL DEFAULT 1,
        vault_type TEXT NOT NULL DEFAULT 'Individual',
        is_admin INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vault_shares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vault_id INTEGER NOT NULL,
        shared_vault_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(vault_id, shared_vault_id),
        FOREIGN KEY(vault_id) REFERENCES vaults(id),
        FOREIGN KEY(shared_vault_id) REFERENCES vaults(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    opening_balance REAL NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    is_primary INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(vault_id) REFERENCES vaults(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_id INTEGER NOT NULL,
    account_id INTEGER,
    category_id INTEGER,
    date TEXT NOT NULL,
    amount REAL NOT NULL,
    transaction_type TEXT NOT NULL,
    notes TEXT,
    transfer_group_id TEXT,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY(vault_id) REFERENCES vaults(id),
    FOREIGN KEY(account_id) REFERENCES accounts(id),
    FOREIGN KEY(category_id) REFERENCES categories(id))""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vault_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    emoji TEXT NOT NULL,
    category_type TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(vault_id) REFERENCES vaults(id))""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS income_templates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vault_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        amount REAL NOT NULL,
        due_day INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY(vault_id)
            REFERENCES vaults(id),
        FOREIGN KEY(account_id)
            REFERENCES accounts(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS commitments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vault_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        amount REAL NOT NULL,
        due_day INTEGER NOT NULL,
        account_id INTEGER NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY(vault_id)
            REFERENCES vaults(id),
        FOREIGN KEY(account_id)
            REFERENCES accounts(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS obligation_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        commitment_id INTEGER NOT NULL,
        month INTEGER NOT NULL,
        year INTEGER NOT NULL,
        actual_amount REAL,
        status TEXT DEFAULT 'PENDING',
        notes TEXT,
        UNIQUE(
            commitment_id,
            month,
            year
        ),
        FOREIGN KEY(commitment_id)
            REFERENCES commitments(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS income_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,

        income_template_id INTEGER NOT NULL,

        month INTEGER NOT NULL,

        year INTEGER NOT NULL,

        actual_amount REAL,

        status TEXT DEFAULT 'PENDING',

        notes TEXT,

        UNIQUE(
            income_template_id,
            month,
            year
        ),

        FOREIGN KEY(income_template_id)
            REFERENCES income_templates(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS monthly_cycles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vault_id INTEGER NOT NULL,
        month INTEGER NOT NULL,
        year INTEGER NOT NULL,
        status TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(vault_id, month, year)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wishlist_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vault_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT '',
        estimated_cost REAL NOT NULL DEFAULT 0,
        saved_amount REAL NOT NULL DEFAULT 0,
        target_date TEXT,
        account_id INTEGER,
        image_url TEXT,
        notes TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(vault_id) REFERENCES vaults(id),
        FOREIGN KEY(account_id) REFERENCES accounts(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wishlist_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vault_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(vault_id, name),
        FOREIGN KEY(vault_id) REFERENCES vaults(id)
    )
    """)

    conn.commit()
    conn.close()

def migrate_database():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        ALTER TABLE vaults
        ADD COLUMN pin_plain TEXT
        """)
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("""
        ALTER TABLE vaults
        ADD COLUMN month_start_day INTEGER NOT NULL DEFAULT 1
        """)
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("""
        ALTER TABLE vaults
        ADD COLUMN vault_type TEXT NOT NULL DEFAULT 'Individual'
        """)
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vault_shares (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vault_id INTEGER NOT NULL,
        shared_vault_id INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(vault_id, shared_vault_id),
        FOREIGN KEY(vault_id) REFERENCES vaults(id),
        FOREIGN KEY(shared_vault_id) REFERENCES vaults(id)
    )
    """)

    backfill_plain_pins_with_cursor(
        cursor
    )

    try:
        cursor.execute("""
        ALTER TABLE accounts
        ADD COLUMN opening_balance REAL NOT NULL DEFAULT 0
        """)
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("""
        ALTER TABLE accounts
        ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1
        """)
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("""
        ALTER TABLE accounts
        ADD COLUMN is_primary INTEGER NOT NULL DEFAULT 0
        """)
    except sqlite3.OperationalError:
        pass

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

    try:
        cursor.execute("""
        ALTER TABLE categories
        ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1
        """)
    except sqlite3.OperationalError:
        pass

    cursor.execute(
        """
        UPDATE categories
        SET emoji = ?
        WHERE LOWER(name) = LOWER(?)
        AND emoji != ?
        """,
        (
            DEFAULT_CATEGORY_EMOJI,
            DEFAULT_CATEGORY_NAME,
            DEFAULT_CATEGORY_EMOJI
        )
    )

    try:
        cursor.execute("""
        ALTER TABLE transactions
        ADD COLUMN is_deleted INTEGER NOT NULL DEFAULT 0
        """)
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("""
        ALTER TABLE transactions
        ADD COLUMN transfer_group_id TEXT
        """)
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("""
        ALTER TABLE income_status
        ADD COLUMN transaction_id INTEGER
        """)
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("""
        ALTER TABLE obligation_status
        ADD COLUMN transaction_id INTEGER
        """)
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wishlist_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vault_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        category TEXT NOT NULL DEFAULT '',
        estimated_cost REAL NOT NULL DEFAULT 0,
        saved_amount REAL NOT NULL DEFAULT 0,
        target_date TEXT,
        account_id INTEGER,
        image_url TEXT,
        notes TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(vault_id) REFERENCES vaults(id),
        FOREIGN KEY(account_id) REFERENCES accounts(id)
    )
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS wishlist_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vault_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(vault_id, name),
        FOREIGN KEY(vault_id) REFERENCES vaults(id)
    )
    """)

    cursor.execute("""
    INSERT OR IGNORE INTO wishlist_categories (vault_id, name)
    SELECT DISTINCT vault_id, TRIM(category)
    FROM wishlist_items
    WHERE TRIM(COALESCE(category, '')) != ''
    """)

    ensure_default_categories_with_cursor(
        cursor
    )

    backfill_transfer_groups_with_cursor(
        cursor
    )

    conn.commit()
    conn.close()

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

def ensure_default_categories_with_cursor(
    cursor
):

    vaults = cursor.execute(
        """
        SELECT id
        FROM vaults
        """
    ).fetchall()

    for vault in vaults:

        category_id = ensure_default_category_with_cursor(
            cursor,
            vault[0]
        )

        backfill_planning_default_category_with_cursor(
            cursor,
            vault[0],
            category_id
        )

def ensure_default_category_with_cursor(
    cursor,
    vault_id
):

    existing = cursor.execute(
        """
        SELECT id
        FROM categories
        WHERE vault_id = ?
        AND LOWER(name) = LOWER(?)
        AND is_active = 1
        """,
        (
            vault_id,
            DEFAULT_CATEGORY_NAME
        )
    ).fetchone()

    if existing:
        cursor.execute(
            """
            UPDATE categories
            SET emoji = ?
            WHERE id = ?
            AND emoji != ?
            """,
            (
                DEFAULT_CATEGORY_EMOJI,
                existing[0],
                DEFAULT_CATEGORY_EMOJI
            )
        )
        return existing[0]

    archived = cursor.execute(
        """
        SELECT id
        FROM categories
        WHERE vault_id = ?
        AND LOWER(name) = LOWER(?)
        AND is_active = 0
        """,
        (
            vault_id,
            DEFAULT_CATEGORY_NAME
        )
    ).fetchone()

    if archived:

        cursor.execute(
            """
            UPDATE categories
            SET
                emoji = ?,
                category_type = ?,
                is_active = 1
            WHERE id = ?
            """,
            (
                DEFAULT_CATEGORY_EMOJI,
                DEFAULT_CATEGORY_TYPE,
                archived[0]
            )
        )

        return archived[0]

    cursor.execute(
        """
        INSERT INTO categories
        (
            vault_id,
            name,
            emoji,
            category_type,
            is_active
        )
        VALUES (?, ?, ?, ?, 1)
        """,
        (
            vault_id,
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
    conn.close()

    return category_id

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
            account_id,
            category_id,
            date,
            amount,
            transaction_type,
            notes,
            is_deleted
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
        """,
        (
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

# Lazy compatibility wrappers for domains that have been physically
# extracted. They keep the legacy database facade working without
# creating circular imports when app code imports domain modules directly.

def vault_exists(*args, **kwargs):
    from db.vaults import vault_exists as impl
    return impl(*args, **kwargs)

def verify_pin(*args, **kwargs):
    from db.vaults import verify_pin as impl
    return impl(*args, **kwargs)

def get_vaults(*args, **kwargs):
    from db.vaults import get_vaults as impl
    return impl(*args, **kwargs)

def get_vault_by_id(*args, **kwargs):
    from db.vaults import get_vault_by_id as impl
    return impl(*args, **kwargs)

def create_vault(*args, **kwargs):
    from db.vaults import create_vault as impl
    return impl(*args, **kwargs)

def update_vault(*args, **kwargs):
    from db.vaults import update_vault as impl
    return impl(*args, **kwargs)

def get_all_vaults(*args, **kwargs):
    from db.vaults import get_all_vaults as impl
    return impl(*args, **kwargs)

def get_vault_share_ids(*args, **kwargs):
    from db.vaults import get_vault_share_ids as impl
    return impl(*args, **kwargs)

def promote_to_admin(*args, **kwargs):
    from db.vaults import promote_to_admin as impl
    return impl(*args, **kwargs)

def demote_admin(*args, **kwargs):
    from db.vaults import demote_admin as impl
    return impl(*args, **kwargs)

def get_admin_count(*args, **kwargs):
    from db.vaults import get_admin_count as impl
    return impl(*args, **kwargs)

def delete_vault(*args, **kwargs):
    from db.vaults import delete_vault as impl
    return impl(*args, **kwargs)

def add_account(*args, **kwargs):
    from db.accounts import add_account as impl
    return impl(*args, **kwargs)

def get_accounts(*args, **kwargs):
    from db.accounts import get_accounts as impl
    return impl(*args, **kwargs)

def archive_account(*args, **kwargs):
    from db.accounts import archive_account as impl
    return impl(*args, **kwargs)

def get_account_balance(*args, **kwargs):
    from db.accounts import get_account_balance as impl
    return impl(*args, **kwargs)

def get_credit_card_due(*args, **kwargs):
    from db.accounts import get_credit_card_due as impl
    return impl(*args, **kwargs)

def get_total_credit_card_due(*args, **kwargs):
    from db.accounts import get_total_credit_card_due as impl
    return impl(*args, **kwargs)

def update_account(*args, **kwargs):
    from db.accounts import update_account as impl
    return impl(*args, **kwargs)

def get_account_by_id(*args, **kwargs):
    from db.accounts import get_account_by_id as impl
    return impl(*args, **kwargs)

def set_primary_account(*args, **kwargs):
    from db.accounts import set_primary_account as impl
    return impl(*args, **kwargs)

def get_primary_account(*args, **kwargs):
    from db.accounts import get_primary_account as impl
    return impl(*args, **kwargs)

def account_exists(*args, **kwargs):
    from db.accounts import account_exists as impl
    return impl(*args, **kwargs)

def account_has_transactions(*args, **kwargs):
    from db.accounts import account_has_transactions as impl
    return impl(*args, **kwargs)

def add_category(*args, **kwargs):
    from db.categories import add_category as impl
    return impl(*args, **kwargs)

def get_categories(*args, **kwargs):
    from db.categories import get_categories as impl
    return impl(*args, **kwargs)

def get_category_transaction_count(*args, **kwargs):
    from db.categories import get_category_transaction_count as impl
    return impl(*args, **kwargs)

def move_category_transactions(*args, **kwargs):
    from db.categories import move_category_transactions as impl
    return impl(*args, **kwargs)

def delete_category(*args, **kwargs):
    from db.categories import delete_category as impl
    return impl(*args, **kwargs)

def get_category_dropdown(*args, **kwargs):
    from db.categories import get_category_dropdown as impl
    return impl(*args, **kwargs)

def update_category(*args, **kwargs):
    from db.categories import update_category as impl
    return impl(*args, **kwargs)

def add_transfer(*args, **kwargs):
    from db.transfers import add_transfer as impl
    return impl(*args, **kwargs)

def get_transfers(*args, **kwargs):
    from db.transfers import get_transfers as impl
    return impl(*args, **kwargs)

def get_transfer_by_group(*args, **kwargs):
    from db.transfers import get_transfer_by_group as impl
    return impl(*args, **kwargs)

def update_transfer(*args, **kwargs):
    from db.transfers import update_transfer as impl
    return impl(*args, **kwargs)

def delete_transfer(*args, **kwargs):
    from db.transfers import delete_transfer as impl
    return impl(*args, **kwargs)

def add_transaction(*args, **kwargs):
    from db.transactions import add_transaction as impl
    return impl(*args, **kwargs)

def get_transactions(*args, **kwargs):
    from db.transactions import get_transactions as impl
    return impl(*args, **kwargs)

def get_filtered_transactions(*args, **kwargs):
    from db.transactions import get_filtered_transactions as impl
    return impl(*args, **kwargs)

def delete_transaction(*args, **kwargs):
    from db.transactions import delete_transaction as impl
    return impl(*args, **kwargs)

def get_transaction_by_id(*args, **kwargs):
    from db.transactions import get_transaction_by_id as impl
    return impl(*args, **kwargs)

def update_transaction(*args, **kwargs):
    from db.transactions import update_transaction as impl
    return impl(*args, **kwargs)

def add_commitment(*args, **kwargs):
    from db.planning import add_commitment as impl
    return impl(*args, **kwargs)

def get_commitments(*args, **kwargs):
    from db.planning import get_commitments as impl
    return impl(*args, **kwargs)

def delete_commitment(*args, **kwargs):
    from db.planning import delete_commitment as impl
    return impl(*args, **kwargs)

def update_commitment(*args, **kwargs):
    from db.planning import update_commitment as impl
    return impl(*args, **kwargs)

def get_total_commitments(*args, **kwargs):
    from db.planning import get_total_commitments as impl
    return impl(*args, **kwargs)

def get_obligation_status(*args, **kwargs):
    from db.planning import get_obligation_status as impl
    return impl(*args, **kwargs)

def save_obligation_status_with_cursor(*args, **kwargs):
    from db.planning import save_obligation_status_with_cursor as impl
    return impl(*args, **kwargs)

def save_obligation_status(*args, **kwargs):
    from db.planning import save_obligation_status as impl
    return impl(*args, **kwargs)

def get_income_status(*args, **kwargs):
    from db.planning import get_income_status as impl
    return impl(*args, **kwargs)

def save_income_status_with_cursor(*args, **kwargs):
    from db.planning import save_income_status_with_cursor as impl
    return impl(*args, **kwargs)

def save_income_status(*args, **kwargs):
    from db.planning import save_income_status as impl
    return impl(*args, **kwargs)

def get_cycle(*args, **kwargs):
    from db.planning import get_cycle as impl
    return impl(*args, **kwargs)

def create_cycle(*args, **kwargs):
    from db.planning import create_cycle as impl
    return impl(*args, **kwargs)

def get_next_month(*args, **kwargs):
    from db.planning import get_next_month as impl
    return impl(*args, **kwargs)

def finalize_month(*args, **kwargs):
    from db.planning import finalize_month as impl
    return impl(*args, **kwargs)

def add_income_template(*args, **kwargs):
    from db.planning import add_income_template as impl
    return impl(*args, **kwargs)

def get_income_templates(*args, **kwargs):
    from db.planning import get_income_templates as impl
    return impl(*args, **kwargs)

def update_income_template(*args, **kwargs):
    from db.planning import update_income_template as impl
    return impl(*args, **kwargs)

def delete_income_template(*args, **kwargs):
    from db.planning import delete_income_template as impl
    return impl(*args, **kwargs)

def get_total_income_templates(*args, **kwargs):
    from db.planning import get_total_income_templates as impl
    return impl(*args, **kwargs)

def get_monthly_planning_totals(*args, **kwargs):
    from db.planning import get_monthly_planning_totals as impl
    return impl(*args, **kwargs)

def get_account_count(*args, **kwargs):
    from db.dashboard import get_account_count as impl
    return impl(*args, **kwargs)

def get_transaction_count_this_month(*args, **kwargs):
    from db.dashboard import get_transaction_count_this_month as impl
    return impl(*args, **kwargs)

def get_dashboard_cycle(*args, **kwargs):
    from db.dashboard import get_dashboard_cycle as impl
    return impl(*args, **kwargs)

def get_income_this_month(*args, **kwargs):
    from db.dashboard import get_income_this_month as impl
    return impl(*args, **kwargs)

def get_expense_this_month(*args, **kwargs):
    from db.dashboard import get_expense_this_month as impl
    return impl(*args, **kwargs)

def get_remaining_commitments(*args, **kwargs):
    from db.dashboard import get_remaining_commitments as impl
    return impl(*args, **kwargs)

def get_onboarding_status(*args, **kwargs):
    from db.dashboard import get_onboarding_status as impl
    return impl(*args, **kwargs)

def is_setup_complete(*args, **kwargs):
    from db.dashboard import is_setup_complete as impl
    return impl(*args, **kwargs)

def get_received_income_this_month(*args, **kwargs):
    from db.dashboard import get_received_income_this_month as impl
    return impl(*args, **kwargs)

def get_available_cash(*args, **kwargs):
    from db.dashboard import get_available_cash as impl
    return impl(*args, **kwargs)

def get_dashboard_summary(*args, **kwargs):
    from db.dashboard import get_dashboard_summary as impl
    return impl(*args, **kwargs)

def get_category_spending_this_month(*args, **kwargs):
    from db.dashboard import get_category_spending_this_month as impl
    return impl(*args, **kwargs)

def add_wishlist_item(*args, **kwargs):
    from db.wishlist import add_wishlist_item as impl
    return impl(*args, **kwargs)

def get_wishlist_items(*args, **kwargs):
    from db.wishlist import get_wishlist_items as impl
    return impl(*args, **kwargs)

def get_wishlist_item(*args, **kwargs):
    from db.wishlist import get_wishlist_item as impl
    return impl(*args, **kwargs)

def update_wishlist_item(*args, **kwargs):
    from db.wishlist import update_wishlist_item as impl
    return impl(*args, **kwargs)

def delete_wishlist_item(*args, **kwargs):
    from db.wishlist import delete_wishlist_item as impl
    return impl(*args, **kwargs)

def get_wishlist_summary(*args, **kwargs):
    from db.wishlist import get_wishlist_summary as impl
    return impl(*args, **kwargs)

def add_wishlist_category(*args, **kwargs):
    from db.wishlist import add_wishlist_category as impl
    return impl(*args, **kwargs)

def get_wishlist_categories(*args, **kwargs):
    from db.wishlist import get_wishlist_categories as impl
    return impl(*args, **kwargs)

def get_wishlist_category(*args, **kwargs):
    from db.wishlist import get_wishlist_category as impl
    return impl(*args, **kwargs)

def get_wishlist_category_item_count(*args, **kwargs):
    from db.wishlist import get_wishlist_category_item_count as impl
    return impl(*args, **kwargs)

def update_wishlist_category(*args, **kwargs):
    from db.wishlist import update_wishlist_category as impl
    return impl(*args, **kwargs)

def delete_wishlist_category(*args, **kwargs):
    from db.wishlist import delete_wishlist_category as impl
    return impl(*args, **kwargs)

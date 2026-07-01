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
    return connect()

def hash_pin(pin):
    return hashlib.sha256(pin.encode()).hexdigest()


def initialize_database():
    execute_schema()

def migrate_database():
    conn = get_connection()
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

    cursor.execute("""
    INSERT INTO wishlist_categories (vault_id, name)
    SELECT DISTINCT vault_id, TRIM(category)
    FROM wishlist_items
    WHERE TRIM(COALESCE(category, '')) != ''
    ON CONFLICT (vault_id, name) DO NOTHING
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

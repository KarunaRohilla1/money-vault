import argparse
import sqlite3
import sys
from pathlib import Path

from psycopg2.extras import execute_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(ROOT)
)

from db.postgres import connect, execute_schema, get_supabase_client


TABLES = [
    (
        "vaults",
        [
            "id",
            "name",
            "pin_hash",
            "month_start_day",
            "vault_type",
            "is_admin",
            "created_at"
        ]
    ),
    (
        "accounts",
        [
            "id",
            "vault_id",
            "name",
            "type",
            "opening_balance",
            "is_active",
            "is_primary"
        ]
    ),
    (
        "categories",
        [
            "id",
            "vault_id",
            "name",
            "emoji",
            "category_type",
            "is_active"
        ]
    ),
    (
        "transactions",
        [
            "id",
            "vault_id",
            "beneficiary_vault_id",
            "account_id",
            "category_id",
            "date",
            "amount",
            "transaction_type",
            "allocation_method",
            "notes",
            "transfer_group_id",
            "is_deleted"
        ]
    ),
    (
        "transaction_shares",
        [
            "id",
            "transaction_id",
            "participant_vault_id",
            "share_amount",
            "share_percentage",
            "created_at"
        ]
    ),
    (
        "income_templates",
        [
            "id",
            "vault_id",
            "name",
            "amount",
            "due_day",
            "account_id",
            "is_active"
        ]
    ),
    (
        "commitments",
        [
            "id",
            "vault_id",
            "name",
            "amount",
            "due_day",
            "account_id",
            "is_active"
        ]
    ),
    (
        "income_status",
        [
            "id",
            "income_template_id",
            "month",
            "year",
            "actual_amount",
            "status",
            "notes",
            "transaction_id"
        ]
    ),
    (
        "obligation_status",
        [
            "id",
            "commitment_id",
            "month",
            "year",
            "actual_amount",
            "status",
            "notes",
            "transaction_id"
        ]
    ),
    (
        "monthly_cycles",
        [
            "id",
            "vault_id",
            "month",
            "year",
            "status",
            "created_at"
        ]
    ),
    (
        "wishlist_items",
        [
            "id",
            "vault_id",
            "name",
            "category",
            "estimated_cost",
            "saved_amount",
            "target_date",
            "account_id",
            "image_url",
            "notes",
            "is_active",
            "created_at"
        ]
    ),
    (
        "wishlist_categories",
        [
            "id",
            "vault_id",
            "name",
            "is_active",
            "created_at"
        ]
    ),
    (
        "vault_shares",
        [
            "id",
            "vault_id",
            "shared_vault_id",
            "created_at"
        ]
    )
]


def sqlite_table_columns(connection, table_name):
    return {
        row[1]
        for row in connection.execute(
            f"PRAGMA table_info({table_name})"
        ).fetchall()
    }


def fetch_sqlite_rows(connection, table_name, columns):
    available_columns = sqlite_table_columns(
        connection,
        table_name
    )
    selected_columns = [
        column
        for column in columns
        if column in available_columns
    ]

    if not selected_columns:
        return [], selected_columns

    rows = connection.execute(
        f"""
        SELECT {", ".join(selected_columns)}
        FROM {table_name}
        ORDER BY id
        """
    ).fetchall()

    if table_name == "transactions":
        rows, selected_columns = normalize_transaction_rows(
            rows,
            selected_columns
        )

    return rows, selected_columns


def normalize_transaction_rows(rows, selected_columns):
    normalized_columns = list(
        selected_columns
    )

    if "beneficiary_vault_id" not in normalized_columns:
        normalized_columns.insert(
            normalized_columns.index("vault_id") + 1,
            "beneficiary_vault_id"
        )

    if "allocation_method" not in normalized_columns:
        normalized_columns.insert(
            normalized_columns.index("transaction_type") + 1,
            "allocation_method"
        )

    normalized_rows = []

    for row in rows:
        row_map = dict(
            zip(
                selected_columns,
                row
            )
        )
        row_map.setdefault(
            "beneficiary_vault_id",
            row_map.get("vault_id")
        )
        row_map.setdefault(
            "allocation_method",
            None
        )

        normalized_rows.append(
            tuple(
                row_map.get(column)
                for column in normalized_columns
            )
        )

    return normalized_rows, normalized_columns


def clear_postgres(cursor):
    for table_name, _columns in reversed(TABLES):
        cursor.execute(
            f"DELETE FROM {table_name}"
        )


def insert_rows(cursor, table_name, columns, rows):
    if not rows:
        return

    quoted_columns = ", ".join(columns)
    query = f"INSERT INTO {table_name} ({quoted_columns}) VALUES %s"
    execute_values(
        cursor.raw_cursor,
        query,
        rows
    )


def reset_sequence(cursor, table_name):
    cursor.execute(
        "SELECT pg_get_serial_sequence(%s, 'id')",
        (table_name,)
    )
    sequence = cursor.fetchone()[0]
    if not sequence:
        return

    cursor.execute(
        f"""
        SELECT setval(
            %s,
            COALESCE((SELECT MAX(id) FROM {table_name}), 0) + 1,
            false
        )
        """,
        (sequence,)
    )


def validate_supabase_client():
    try:
        client = get_supabase_client()
    except RuntimeError:
        return

    client.table("vaults").select("id").limit(1).execute()


def migrate(sqlite_path):
    if not sqlite_path.exists():
        raise FileNotFoundError(
            f"SQLite database not found: {sqlite_path}"
        )

    execute_schema()

    sqlite_connection = sqlite3.connect(sqlite_path)
    postgres_connection = connect()
    cursor = postgres_connection.cursor()

    try:
        clear_postgres(cursor)

        for table_name, columns in TABLES:
            rows, selected_columns = fetch_sqlite_rows(
                sqlite_connection,
                table_name,
                columns
            )
            insert_rows(
                cursor,
                table_name,
                selected_columns,
                rows
            )
            print(
                f"{table_name}: {len(rows)} row(s)"
            )

        for table_name, _columns in TABLES:
            reset_sequence(
                cursor,
                table_name
            )

        postgres_connection.commit()
        validate_supabase_client()

    except Exception:
        postgres_connection.rollback()
        raise

    finally:
        sqlite_connection.close()
        postgres_connection.close()


def parse_args():
    parser = argparse.ArgumentParser(
        description="Copy Money Vault data from SQLite into Supabase PostgreSQL."
    )
    parser.add_argument(
        "--sqlite-path",
        default=str(ROOT / "data" / "money.db"),
        help="Path to the existing SQLite money.db file."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    migrate(
        Path(args.sqlite_path)
    )
    print("Migration complete.")

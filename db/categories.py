from db.core import (
    DEFAULT_CATEGORY_NAME,
    ensure_default_category,
    get_connection
)
from db.cache import cache_data, clear_data_cache
from db.postgres import IntegrityError


def add_category(
    vault_id,
    name,
    emoji,
    category_type
):

    name = name.strip().title()

    if not name:

        raise ValueError(
            "Category name cannot be empty."
        )

    conn = get_connection()
    try:
        existing = conn.execute(
            """
            SELECT id
            FROM categories
            WHERE (
                vault_id = ?
                OR is_system = 1
            )
            AND LOWER(name) = LOWER(?)
            AND is_active = 1
            """,
            (
                vault_id,
                name
            )
        ).fetchone()

        if existing:

            raise ValueError(
                "Category already exists."
            )

        conn.execute(
            """
            INSERT INTO categories
            (
                vault_id,
                name,
                emoji,
                category_type
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                vault_id,
                name,
                emoji,
                category_type
            )
        )

        conn.commit()
        clear_data_cache()

        return True

    except IntegrityError:

        return False

    finally:

        conn.close()

@cache_data(ttl=60)
def get_categories(vault_id):

    ensure_default_category(
        vault_id
    )

    conn = get_connection()
    try:

        categories = conn.execute(
            """
            SELECT
                id,
                emoji,
                name,
                category_type,
                parent_category,
                is_system
            FROM categories
            WHERE (
                vault_id = ?
                OR is_system = 1
            )
            AND is_active = 1
            ORDER BY is_system DESC, COALESCE(parent_category, 'Custom'), name
            """,
            (vault_id,)
        ).fetchall()


        return categories

    finally:
        conn.close()
@cache_data(ttl=60)
def get_category_transaction_count(category_id):

    conn = get_connection()
    try:

        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM transactions
            WHERE category_id = ?
            AND is_deleted = 0
            """,
            (category_id,)
        ).fetchone()[0]


        return count


    finally:
        conn.close()
def move_category_transactions(
    old_category_id,
    new_category_id
):

    conn = get_connection()
    try:

        conn.execute(
            """
            UPDATE transactions
            SET category_id = ?
            WHERE category_id = ?
            """,
            (
                new_category_id,
                old_category_id
            )
        )

        conn.commit()
        clear_data_cache()


    finally:
        conn.close()
def delete_category(category_id):

    conn = get_connection()
    try:

        category = conn.execute(
            """
            SELECT name, is_system
            FROM categories
            WHERE id = ?
            """,
            (category_id,)
        ).fetchone()

        if category and category[1]:
            raise ValueError("System categories cannot be deleted.")

        if category and category[0].lower() == DEFAULT_CATEGORY_NAME.lower():
            raise ValueError("Default category cannot be deleted.")

        conn.execute(
            """
            UPDATE categories
            SET is_active = 0
            WHERE id = ?
            """,
            (category_id,)
        )

        conn.commit()
        clear_data_cache()

    finally:
        conn.close()
@cache_data(ttl=60)
def get_category_dropdown(vault_id):

    ensure_default_category(
        vault_id
    )

    conn = get_connection()
    try:

        vault = conn.execute(
            """
            SELECT vault_type
            FROM vaults
            WHERE id = ?
            """,
            (vault_id,)
        ).fetchone()
        shared_only = bool(vault and vault[0] == "Shared")

        if shared_only:
            categories = conn.execute(
                """
                SELECT
                    id,
                    emoji,
                    name,
                    category_type,
                    parent_category,
                    is_system
                FROM categories
                WHERE is_system = 1
                AND is_active = 1
                ORDER BY COALESCE(parent_category, 'Miscellaneous'), name
                """
            ).fetchall()
        else:
            categories = conn.execute(
            """
            SELECT
                id,
                emoji,
                name,
                category_type,
                parent_category,
                is_system
            FROM categories
            WHERE (
                vault_id = ?
                OR is_system = 1
            )
            AND is_active = 1
            ORDER BY is_system DESC, COALESCE(parent_category, 'Custom'), name
            """,
            (vault_id,)
            ).fetchall()


        return categories


    finally:
        conn.close()
def update_category(
    category_id,
    name,
    emoji,
    category_type
):

    conn = get_connection()
    try:
        name = name.strip().title()

        if not name:


            raise ValueError(
                "Category name cannot be empty."
            )

        category = conn.execute(
            """
            SELECT is_system
            FROM categories
            WHERE id = ?
            """,
            (category_id,)
        ).fetchone()

        if category and category[0]:
            raise ValueError("System categories cannot be edited.")

        existing = conn.execute(
            """
            SELECT id
            FROM categories
            WHERE (
                vault_id = (
                    SELECT vault_id
                    FROM categories
                    WHERE id = ?
                )
                OR is_system = 1
            )
            AND LOWER(name) = LOWER(?)
            AND id != ?
            AND is_active = 1
            """,
            (
                category_id,
                name,
                category_id
            )
        ).fetchone()

        if existing:


            raise ValueError(
                "Category already exists."
            )

        conn.execute(
            """
            UPDATE categories
            SET
                name = ?,
                emoji = ?,
                category_type = ?
            WHERE id = ?
            """,
            (
                name,
                emoji,
                category_type,
                category_id
            )
        )

        conn.commit()
        clear_data_cache()

    finally:
        conn.close()

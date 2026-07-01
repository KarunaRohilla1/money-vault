from db.core import (
    DEFAULT_CATEGORY_NAME,
    ensure_default_category,
    get_connection
)
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

    existing = conn.execute(
        """
        SELECT id
        FROM categories
        WHERE vault_id = ?
        AND LOWER(name) = LOWER(?)
        AND is_active = 1
        """,
        (
            vault_id,
            name
        )
    ).fetchone()

    if existing:

        conn.close()

        raise ValueError(
            "Category already exists."
        )

    try:

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

        return True

    except IntegrityError:

        return False

    finally:

        conn.close()


def get_categories(vault_id):

    ensure_default_category(
        vault_id
    )

    conn = get_connection()

    categories = conn.execute(
        """
        SELECT
            id,
            emoji,
            name,
            category_type
        FROM categories
        WHERE vault_id = ?
        AND is_active = 1
        ORDER BY name
        """,
        (vault_id,)
    ).fetchall()

    conn.close()

    return categories


def get_category_transaction_count(category_id):

    conn = get_connection()

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM transactions
        WHERE category_id = ?
        AND is_deleted = 0
        """,
        (category_id,)
    ).fetchone()[0]

    conn.close()

    return count


def move_category_transactions(
    old_category_id,
    new_category_id
):

    conn = get_connection()

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
    conn.close()


def delete_category(category_id):

    conn = get_connection()

    category = conn.execute(
        """
        SELECT name
        FROM categories
        WHERE id = ?
        """,
        (category_id,)
    ).fetchone()

    if (
        category
        and category[0].lower()
        == DEFAULT_CATEGORY_NAME.lower()
    ):

        conn.close()

        return

    conn.execute(
        """
        UPDATE categories
        SET is_active = 0
        WHERE id = ?
        """,
        (category_id,)
    )

    conn.commit()
    conn.close()


def get_category_dropdown(vault_id):

    ensure_default_category(
        vault_id
    )

    conn = get_connection()

    categories = conn.execute(
        """
        SELECT
            id,
            emoji,
            name,
            category_type
        FROM categories
        WHERE vault_id = ?
        AND is_active = 1
        ORDER BY name
        """,
        (vault_id,)
    ).fetchall()

    conn.close()

    return categories


def update_category(
    category_id,
    name,
    emoji,
    category_type
):

    conn = get_connection()
    name = name.strip().title()

    if not name:

        conn.close()

        raise ValueError(
            "Category name cannot be empty."
        )

    existing = conn.execute(
        """
        SELECT id
        FROM categories
        WHERE vault_id = (
            SELECT vault_id
            FROM categories
            WHERE id = ?
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

        conn.close()

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
    conn.close()

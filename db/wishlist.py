from db.core import get_connection


def add_wishlist_category(vault_id, name):

    category_name = name.strip()

    if not category_name:
        return

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO wishlist_categories (
            vault_id,
            name
        )
        VALUES (?, ?)
        ON CONFLICT(vault_id, name) DO UPDATE SET
            is_active = 1
        """,
        (
            vault_id,
            category_name
        )
    )

    conn.commit()
    conn.close()


def get_wishlist_categories(vault_id):

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT
            id,
            vault_id,
            name
        FROM wishlist_categories
        WHERE vault_id = ?
        AND is_active = 1
        ORDER BY LOWER(name)
        """,
        (vault_id,)
    ).fetchall()

    conn.close()

    return rows


def get_wishlist_category(category_id):

    conn = get_connection()

    category = conn.execute(
        """
        SELECT
            id,
            vault_id,
            name
        FROM wishlist_categories
        WHERE id = ?
        AND is_active = 1
        """,
        (category_id,)
    ).fetchone()

    conn.close()

    return category


def get_wishlist_category_item_count(vault_id, name):

    conn = get_connection()

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM wishlist_items
        WHERE vault_id = ?
        AND LOWER(category) = LOWER(?)
        AND is_active = 1
        """,
        (
            vault_id,
            name
        )
    ).fetchone()[0]

    conn.close()

    return count


def update_wishlist_category(category_id, vault_id, old_name, new_name):

    category_name = new_name.strip()

    if not category_name:
        raise ValueError("Category name is required.")

    conn = get_connection()

    existing = conn.execute(
        """
        SELECT id
        FROM wishlist_categories
        WHERE vault_id = ?
        AND LOWER(name) = LOWER(?)
        AND is_active = 1
        AND id != ?
        """,
        (
            vault_id,
            category_name,
            category_id
        )
    ).fetchone()

    if existing:
        conn.close()
        raise ValueError("Wishlist category already exists.")

    conn.execute(
        """
        UPDATE wishlist_categories
        SET name = ?
        WHERE id = ?
        AND vault_id = ?
        """,
        (
            category_name,
            category_id,
            vault_id
        )
    )

    conn.execute(
        """
        UPDATE wishlist_items
        SET category = ?
        WHERE vault_id = ?
        AND LOWER(category) = LOWER(?)
        AND is_active = 1
        """,
        (
            category_name,
            vault_id,
            old_name
        )
    )

    conn.commit()
    conn.close()


def delete_wishlist_category(category_id, vault_id, name, fallback="General"):

    conn = get_connection()

    conn.execute(
        """
        UPDATE wishlist_categories
        SET is_active = 0
        WHERE id = ?
        AND vault_id = ?
        """,
        (
            category_id,
            vault_id
        )
    )

    conn.execute(
        """
        UPDATE wishlist_items
        SET category = ?
        WHERE vault_id = ?
        AND LOWER(category) = LOWER(?)
        AND is_active = 1
        """,
        (
            fallback,
            vault_id,
            name
        )
    )

    conn.execute(
        """
        INSERT INTO wishlist_categories (
            vault_id,
            name
        )
        VALUES (?, ?)
        ON CONFLICT(vault_id, name) DO UPDATE SET
            is_active = 1
        """,
        (
            vault_id,
            fallback
        )
    )

    conn.commit()
    conn.close()


def add_wishlist_item(
    vault_id,
    name,
    category,
    estimated_cost,
    saved_amount=0,
    target_date=None,
    account_id=None,
    image_url="",
    notes=""
):

    conn = get_connection()

    conn.execute(
        """
        INSERT INTO wishlist_items (
            vault_id,
            name,
            category,
            estimated_cost,
            saved_amount,
            target_date,
            account_id,
            image_url,
            notes
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            vault_id,
            name,
            category,
            estimated_cost,
            saved_amount,
            target_date,
            account_id,
            image_url,
            notes
        )
    )

    conn.commit()
    conn.close()


def get_wishlist_items(
    vault_id,
    search=None,
    account_id=None,
    date_filter="All Dates",
    category=None
):

    conn = get_connection()

    query = """
    SELECT
        w.id,
        w.name,
        w.category,
        w.estimated_cost,
        w.saved_amount,
        w.target_date,
        w.account_id,
        COALESCE(a.name, ''),
        w.image_url,
        w.notes
    FROM wishlist_items w
    LEFT JOIN accounts a
        ON w.account_id = a.id
    WHERE w.vault_id = ?
    AND w.is_active = 1
    """

    params = [vault_id]

    if search:
        query += """
        AND (
            LOWER(w.name) LIKE ?
            OR LOWER(w.category) LIKE ?
            OR LOWER(COALESCE(w.notes, '')) LIKE ?
        )
        """
        term = f"%{search.lower()}%"
        params.extend([term, term, term])

    if account_id:
        query += """
        AND w.account_id = ?
        """
        params.append(account_id)

    if category and category != "All Categories":
        query += """
        AND LOWER(w.category) = LOWER(?)
        """
        params.append(category)

    if date_filter == "With Date":
        query += """
        AND w.target_date IS NOT NULL
        AND w.target_date != ''
        """
    elif date_filter == "No Date":
        query += """
        AND (
            w.target_date IS NULL
            OR w.target_date = ''
        )
        """

    query += """
    ORDER BY
        CASE
            WHEN w.target_date IS NULL OR w.target_date = '' THEN 1
            ELSE 0
        END,
        w.target_date,
        w.id DESC
    """

    rows = conn.execute(
        query,
        params
    ).fetchall()

    conn.close()

    return rows


def get_wishlist_item(item_id):

    conn = get_connection()

    item = conn.execute(
        """
        SELECT
            id,
            vault_id,
            name,
            category,
            estimated_cost,
            saved_amount,
            target_date,
            account_id,
            image_url,
            notes
        FROM wishlist_items
        WHERE id = ?
        AND is_active = 1
        """,
        (item_id,)
    ).fetchone()

    conn.close()

    return item


def update_wishlist_item(
    item_id,
    name,
    category,
    estimated_cost,
    saved_amount,
    target_date=None,
    account_id=None,
    image_url="",
    notes=""
):

    conn = get_connection()

    conn.execute(
        """
        UPDATE wishlist_items
        SET
            name = ?,
            category = ?,
            estimated_cost = ?,
            saved_amount = ?,
            target_date = ?,
            account_id = ?,
            image_url = ?,
            notes = ?
        WHERE id = ?
        """,
        (
            name,
            category,
            estimated_cost,
            saved_amount,
            target_date,
            account_id,
            image_url,
            notes,
            item_id
        )
    )

    conn.commit()
    conn.close()


def delete_wishlist_item(item_id):

    conn = get_connection()

    conn.execute(
        """
        DELETE FROM wishlist_items
        WHERE id = ?
        """,
        (item_id,)
    )

    conn.commit()
    conn.close()


def get_wishlist_summary(vault_id):

    conn = get_connection()

    row = conn.execute(
        """
        SELECT
            COUNT(*),
            COALESCE(SUM(estimated_cost), 0),
            COALESCE(SUM(saved_amount), 0)
        FROM wishlist_items
        WHERE vault_id = ?
        AND is_active = 1
        """,
        (vault_id,)
    ).fetchone()

    conn.close()

    total_items = row[0]
    total_cost = row[1]
    total_saved = row[2]
    progress = (
        round((total_saved / total_cost) * 100)
        if total_cost
        else 0
    )

    return {
        "total_items": total_items,
        "total_cost": total_cost,
        "total_saved": total_saved,
        "progress": progress
    }

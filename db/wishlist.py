from db.cache import cache_data, clear_data_cache
from db.core import get_connection


def normalize_priority(priority):
    value = (priority or "MEDIUM").strip().upper()
    return value if value in {"HIGH", "MEDIUM", "LOW"} else "MEDIUM"


def normalize_image_source(image_source):
    value = (image_source or "").strip().lower()
    return value if value in {"camera", "gallery", "url"} else None


def ensure_wishlist_schema_with_cursor(cursor):
    statements = [
        "ALTER TABLE wishlist_categories ADD COLUMN IF NOT EXISTS icon TEXT NOT NULL DEFAULT 'tag-outline'",
        "ALTER TABLE wishlist_categories ADD COLUMN IF NOT EXISTS color TEXT NOT NULL DEFAULT 'purple'",
        "ALTER TABLE wishlist_categories ADD COLUMN IF NOT EXISTS sort_order INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE wishlist_categories ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE wishlist_items ADD COLUMN IF NOT EXISTS category_id BIGINT REFERENCES wishlist_categories(id)",
        "ALTER TABLE wishlist_items ADD COLUMN IF NOT EXISTS priority TEXT NOT NULL DEFAULT 'MEDIUM'",
        "ALTER TABLE wishlist_items ADD COLUMN IF NOT EXISTS purchase_link TEXT",
        "ALTER TABLE wishlist_items ADD COLUMN IF NOT EXISTS image_source TEXT",
        "ALTER TABLE wishlist_items ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP"
    ]
    for statement in statements:
        cursor.execute(statement, capture_lastrowid=False)


def ensure_wishlist_schema():
    conn = get_connection()
    try:
        ensure_wishlist_schema_with_cursor(conn.cursor())
        conn.commit()
    finally:
        conn.close()


def add_wishlist_category(vault_id, name, icon="tag-outline", color="purple", sort_order=None):
    category_name = name.strip()
    if not category_name:
        return

    conn = get_connection()
    try:
        ensure_wishlist_schema_with_cursor(conn.cursor())
        if sort_order is None:
            sort_order = conn.execute(
                """
                SELECT COALESCE(MAX(sort_order), -1) + 1
                FROM wishlist_categories
                WHERE vault_id = ?
                """,
                (vault_id,)
            ).fetchone()[0]

        conn.execute(
            """
            INSERT INTO wishlist_categories (
                vault_id,
                name,
                icon,
                color,
                sort_order
            )
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(vault_id, name) DO UPDATE SET
                is_active = 1,
                icon = EXCLUDED.icon,
                color = EXCLUDED.color,
                sort_order = EXCLUDED.sort_order,
                updated_at = CURRENT_TIMESTAMP
            """,
            (vault_id, category_name, icon, color, sort_order),
            capture_lastrowid=False
        )

        conn.commit()
        clear_data_cache(("wishlist",))
    finally:
        conn.close()


@cache_data(ttl=60)
def get_wishlist_categories(vault_id):
    ensure_wishlist_schema()
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
                c.id,
                c.vault_id,
                c.name,
                COALESCE(c.icon, 'tag-outline'),
                COALESCE(c.color, 'purple'),
                COALESCE(c.sort_order, 0),
                COUNT(w.id)
            FROM wishlist_categories c
            LEFT JOIN wishlist_items w
                ON LOWER(w.category) = LOWER(c.name)
                AND w.vault_id = c.vault_id
                AND w.is_active = 1
            WHERE c.vault_id = ?
            AND c.is_active = 1
            GROUP BY c.id, c.vault_id, c.name, c.icon, c.color, c.sort_order
            ORDER BY COALESCE(c.sort_order, 0), LOWER(c.name)
            """,
            (vault_id,)
        ).fetchall()
        return rows
    finally:
        conn.close()


@cache_data(ttl=60)
def get_wishlist_category(category_id):
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT
                id,
                vault_id,
                name,
                COALESCE(icon, 'tag-outline'),
                COALESCE(color, 'purple'),
                COALESCE(sort_order, 0)
            FROM wishlist_categories
            WHERE id = ?
            AND is_active = 1
            """,
            (category_id,)
        ).fetchone()
    finally:
        conn.close()


@cache_data(ttl=60)
def get_wishlist_category_item_count(vault_id, name):
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT COUNT(*)
            FROM wishlist_items
            WHERE vault_id = ?
            AND LOWER(category) = LOWER(?)
            AND is_active = 1
            """,
            (vault_id, name)
        ).fetchone()[0]
    finally:
        conn.close()


def update_wishlist_category(category_id, vault_id, old_name, new_name, icon="tag-outline", color="purple", sort_order=None):
    category_name = new_name.strip()
    if not category_name:
        raise ValueError("Category name is required.")

    conn = get_connection()
    try:
        existing = conn.execute(
            """
            SELECT id
            FROM wishlist_categories
            WHERE vault_id = ?
            AND LOWER(name) = LOWER(?)
            AND is_active = 1
            AND id != ?
            """,
            (vault_id, category_name, category_id)
        ).fetchone()
        if existing:
            raise ValueError("Wishlist category already exists.")

        if sort_order is None:
            current = conn.execute(
                "SELECT COALESCE(sort_order, 0) FROM wishlist_categories WHERE id = ?",
                (category_id,)
            ).fetchone()
            sort_order = current[0] if current else 0

        conn.execute(
            """
            UPDATE wishlist_categories
            SET name = ?, icon = ?, color = ?, sort_order = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            AND vault_id = ?
            """,
            (category_name, icon, color, sort_order, category_id, vault_id)
        )
        conn.execute(
            """
            UPDATE wishlist_items
            SET category = ?, updated_at = CURRENT_TIMESTAMP
            WHERE vault_id = ?
            AND LOWER(category) = LOWER(?)
            AND is_active = 1
            """,
            (category_name, vault_id, old_name)
        )
        conn.commit()
        clear_data_cache(("wishlist",))
    finally:
        conn.close()


def reorder_wishlist_categories(vault_id, categories):
    conn = get_connection()
    try:
        for entry in categories:
            conn.execute(
                """
                UPDATE wishlist_categories
                SET sort_order = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                AND vault_id = ?
                AND is_active = 1
                """,
                (entry["sort_order"], entry["id"], vault_id)
            )
        conn.commit()
        clear_data_cache(("wishlist",))
    finally:
        conn.close()


def delete_wishlist_category(category_id, vault_id, name, fallback="General"):
    conn = get_connection()
    try:
        conn.execute(
            """
            UPDATE wishlist_categories
            SET is_active = 0, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            AND vault_id = ?
            """,
            (category_id, vault_id)
        )
        conn.execute(
            """
            UPDATE wishlist_items
            SET category = ?, category_id = NULL, updated_at = CURRENT_TIMESTAMP
            WHERE vault_id = ?
            AND LOWER(category) = LOWER(?)
            AND is_active = 1
            """,
            (fallback, vault_id, name)
        )
        conn.execute(
            """
            INSERT INTO wishlist_categories (vault_id, name, icon, color, sort_order)
            VALUES (?, ?, 'tag-outline', 'purple', 999)
            ON CONFLICT(vault_id, name) DO UPDATE SET
                is_active = 1,
                updated_at = CURRENT_TIMESTAMP
            """,
            (vault_id, fallback),
            capture_lastrowid=False
        )
        conn.commit()
        clear_data_cache(("wishlist",))
    finally:
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
    notes="",
    category_id=None,
    priority="MEDIUM",
    purchase_link="",
    image_source=None
):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        ensure_wishlist_schema_with_cursor(cursor)
        category_name = category.strip()
        if category_name and category_id is None:
            sort_order = conn.execute(
                """
                SELECT COALESCE(MAX(sort_order), -1) + 1
                FROM wishlist_categories
                WHERE vault_id = ?
                """,
                (vault_id,)
            ).fetchone()[0]
            conn.execute(
                """
                INSERT INTO wishlist_categories (
                    vault_id,
                    name,
                    icon,
                    color,
                    sort_order
                )
                VALUES (?, ?, 'tag-outline', 'purple', ?)
                ON CONFLICT(vault_id, name) DO UPDATE SET
                    is_active = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (vault_id, category_name, sort_order),
                capture_lastrowid=False
            )
            row = conn.execute(
                """
                SELECT id
                FROM wishlist_categories
                WHERE vault_id = ?
                AND LOWER(name) = LOWER(?)
                AND is_active = 1
                """,
                (vault_id, category_name)
            ).fetchone()
            category_id = row[0] if row else None
        conn.execute(
            """
            INSERT INTO wishlist_items (
                vault_id,
                name,
                category,
                category_id,
                priority,
                estimated_cost,
                saved_amount,
                target_date,
                account_id,
                purchase_link,
                image_url,
                image_source,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                vault_id,
                name,
                category_name,
                category_id,
                normalize_priority(priority),
                estimated_cost,
                saved_amount,
                target_date,
                account_id,
                purchase_link,
                image_url,
                normalize_image_source(image_source),
                notes
            ),
            capture_lastrowid=False
        )
        conn.commit()
        clear_data_cache(("wishlist",))
    finally:
        conn.close()


@cache_data(ttl=60)
def get_wishlist_items(vault_id, search=None, account_id=None, date_filter="All Dates", category=None):
    ensure_wishlist_schema()
    conn = get_connection()
    try:
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
            w.notes,
            w.priority,
            w.purchase_link,
            w.image_source,
            w.created_at,
            w.category_id
        FROM wishlist_items w
        LEFT JOIN accounts a ON w.account_id = a.id
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
            AND (w.target_date IS NULL OR w.target_date = '')
            """
        query += """
        ORDER BY w.created_at DESC, w.id DESC
        """
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


@cache_data(ttl=60)
def get_wishlist_item(item_id):
    ensure_wishlist_schema()
    conn = get_connection()
    try:
        return conn.execute(
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
                notes,
                priority,
                purchase_link,
                image_source,
                created_at,
                category_id
            FROM wishlist_items
            WHERE id = ?
            AND is_active = 1
            """,
            (item_id,)
        ).fetchone()
    finally:
        conn.close()


def update_wishlist_item(
    item_id,
    name,
    category,
    estimated_cost,
    saved_amount,
    target_date=None,
    account_id=None,
    image_url="",
    notes="",
    category_id=None,
    priority="MEDIUM",
    purchase_link="",
    image_source=None
):
    conn = get_connection()
    try:
        ensure_wishlist_schema_with_cursor(conn.cursor())
        conn.execute(
            """
            UPDATE wishlist_items
            SET
                name = ?,
                category = ?,
                category_id = ?,
                priority = ?,
                estimated_cost = ?,
                saved_amount = ?,
                target_date = ?,
                account_id = ?,
                purchase_link = ?,
                image_url = ?,
                image_source = ?,
                notes = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                name,
                category,
                category_id,
                normalize_priority(priority),
                estimated_cost,
                saved_amount,
                target_date,
                account_id,
                purchase_link,
                image_url,
                normalize_image_source(image_source),
                notes,
                item_id
            )
        )
        conn.commit()
        clear_data_cache(("wishlist",))
    finally:
        conn.close()


def delete_wishlist_item(item_id):
    conn = get_connection()
    try:
        conn.execute("DELETE FROM wishlist_items WHERE id = ?", (item_id,))
        conn.commit()
        clear_data_cache(("wishlist",))
    finally:
        conn.close()


@cache_data(ttl=60)
def get_wishlist_summary(vault_id):
    ensure_wishlist_schema()
    conn = get_connection()
    try:
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
        total_items = row[0]
        total_cost = row[1]
        total_saved = row[2]
        progress = round((total_saved / total_cost) * 100) if total_cost else 0
        return {
            "total_items": total_items,
            "total_cost": total_cost,
            "total_saved": total_saved,
            "progress": progress
        }
    finally:
        conn.close()

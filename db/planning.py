from datetime import date, datetime

from db.core import (
    EXPENSE,
    INCOME,
    delete_linked_transaction,
    get_connection,
    get_planning_transaction_date,
    upsert_linked_transaction
)
from db.cache import cache_data, clear_data_cache
from db.financial_cycles import (
    get_cycle_for_date
)


def add_commitment(
    vault_id,
    name,
    amount,
    due_day,
    account_id
):

    conn = get_connection()
    try:
        existing = conn.execute(
            """
            SELECT id
            FROM commitments
            WHERE vault_id = ?
            AND LOWER(name) = LOWER(?)
            AND is_active = 1
            """,
            (
                vault_id,
                name.strip()
            )
        ).fetchone()

        if existing:
            raise ValueError("A recurring commitment with this name already exists.")

        conn.execute(
            """
            INSERT INTO commitments
            (
                vault_id,
                name,
                amount,
                due_day,
                account_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                vault_id,
                name,
                amount,
                due_day,
                account_id
            )
        )

        conn.commit()
        clear_data_cache()

    finally:
        conn.close()
@cache_data(ttl=60)
def get_commitments(vault_id):

    conn = get_connection()
    try:

        commitments = conn.execute(
            """
            SELECT
                c.id,
                c.name,
                c.amount,
                c.due_day,
                a.name,
                c.account_id

            FROM commitments c

            LEFT JOIN accounts a
                ON c.account_id = a.id

            WHERE c.vault_id = ?
            AND c.is_active = 1

            ORDER BY c.due_day
            """,
            (vault_id,)
        ).fetchall()


        return commitments


    finally:
        conn.close()
def delete_commitment(
    commitment_id
):

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM transactions
            WHERE id IN (
                SELECT transaction_id
                FROM obligation_status
                WHERE commitment_id = ?
                AND transaction_id IS NOT NULL
            )
            """,
            (commitment_id,)
        )

        cursor.execute(
            """
            DELETE FROM obligation_status
            WHERE commitment_id = ?
            """,
            (commitment_id,)
        )

        cursor.execute(
            """
            DELETE FROM commitments
            WHERE id = ?
            """,
            (commitment_id,)
        )

        conn.commit()
        clear_data_cache()


    finally:
        conn.close()
def update_commitment(
    commitment_id,
    name,
    amount,
    due_day,
    account_id
):

    conn = get_connection()
    try:
        existing = conn.execute(
            """
            SELECT id
            FROM income_templates
            WHERE vault_id = ?
            AND LOWER(name) = LOWER(?)
            AND is_active = 1
            """,
            (
                vault_id,
                name.strip()
            )
        ).fetchone()

        if existing:
            raise ValueError("A recurring income with this name already exists.")

        conn.execute(
            """
            UPDATE commitments
            SET
                name = ?,
                amount = ?,
                due_day = ?,
                account_id = ?
            WHERE id = ?
            """,
            (
                name,
                amount,
                due_day,
                account_id,
                commitment_id
            )
        )

        conn.commit()
        clear_data_cache()

    finally:
        conn.close()
@cache_data(ttl=60)
def get_total_commitments(vault_id):

    conn = get_connection()
    try:

        total = conn.execute(
            """
            SELECT
                COALESCE(SUM(amount), 0)
            FROM commitments
            WHERE vault_id = ?
            """,
            (vault_id,)
        ).fetchone()[0]


        return total

    finally:
        conn.close()
@cache_data(ttl=60)
def get_obligation_status(
    commitment_id,
    month,
    year
):
    conn = get_connection()
    try:

        row = conn.execute(
            """
            SELECT
                actual_amount,
                status,
                notes
            FROM obligation_status
            WHERE commitment_id = ?
            AND month = ?
            AND year = ?
            """,
            (
                commitment_id,
                month,
                year
            )
        ).fetchone()


        return row


    finally:
        conn.close()
def save_obligation_status_with_cursor(
    cursor,
    commitment_id,
    month,
    year,
    actual_amount,
    status,
    notes=""
):

    commitment = cursor.execute(
        """
        SELECT
            id,
            vault_id,
            name,
            amount,
            due_day,
            account_id
        FROM commitments
        WHERE id = ?
        """,
        (commitment_id,)
    ).fetchone()

    if not commitment:
        raise ValueError(
            "Commitment not found."
        )

    existing = cursor.execute(
        """
        SELECT transaction_id
        FROM obligation_status
        WHERE commitment_id = ?
        AND month = ?
        AND year = ?
        """,
        (
            commitment_id,
            month,
            year
        )
    ).fetchone()

    transaction_id = (
        existing[0]
        if existing
        else None
    )

    if status == "PAID":

        amount = (
            actual_amount
            if actual_amount is not None
            else commitment[3]
        )

        transaction_id = upsert_linked_transaction(
            cursor,
            transaction_id,
            commitment[1],
            commitment[5],
            get_planning_transaction_date(
                year,
                month,
                commitment[4]
            ),
            amount,
            EXPENSE,
            notes or f"Planning commitment: {commitment[2]}"
        )

    else:

        delete_linked_transaction(
            cursor,
            transaction_id
        )

        transaction_id = None

        if status == "CANCELLED":
            actual_amount = 0

    cursor.execute(
        """
        UPDATE obligation_status
        SET
            actual_amount = ?,
            status = ?,
            notes = ?,
            transaction_id = ?
        WHERE commitment_id = ?
        AND month = ?
        AND year = ?
        """,
        (
            actual_amount,
            status,
            notes,
            transaction_id,
            commitment_id,
            month,
            year
        )
    )

    if cursor.rowcount == 0:

        cursor.execute(
            """
            INSERT INTO obligation_status (
            commitment_id,
            month,
            year,
            actual_amount,
            status,
            notes,
            transaction_id

            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                commitment_id,
                month,
                year,
                actual_amount,
                status,
                notes,
                transaction_id
            )
        )


def save_obligation_status(
    commitment_id,
    month,
    year,
    actual_amount,
    status,
    notes=""
):
    conn = get_connection()

    try:

        save_obligation_status_with_cursor(
            conn.cursor(),
            commitment_id,
            month,
            year,
            actual_amount,
            status,
            notes
        )

        conn.commit()
        clear_data_cache()

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()

@cache_data(ttl=60)
def get_income_status(
    income_template_id,
    month,
    year
):

    conn = get_connection()
    try:

        row = conn.execute(
            """
            SELECT
                actual_amount,
                status,
                notes

            FROM income_status

            WHERE income_template_id = ?
            AND month = ?
            AND year = ?
            """,
            (
                income_template_id,
                month,
                year
            )
        ).fetchone()


        return row


    finally:
        conn.close()
@cache_data(ttl=60)
def get_planning_activity_statuses(vault_id, month, year):

    conn = get_connection()
    try:

        rows = conn.execute(
            """
            SELECT
                'income',
                i.id,
                s.actual_amount,
                COALESCE(s.status, 'PENDING'),
                s.notes
            FROM income_templates i
            LEFT JOIN income_status s
                ON s.income_template_id = i.id
                AND s.month = ?
                AND s.year = ?
            WHERE i.vault_id = ?
            AND i.is_active = 1

            UNION ALL

            SELECT
                'commitment',
                c.id,
                s.actual_amount,
                COALESCE(s.status, 'PENDING'),
                s.notes
            FROM commitments c
            LEFT JOIN obligation_status s
                ON s.commitment_id = c.id
                AND s.month = ?
                AND s.year = ?
            WHERE c.vault_id = ?
            AND c.is_active = 1
            """,
            (
                month,
                year,
                vault_id,
                month,
                year,
                vault_id
            )
        ).fetchall()


        return {
            (row[0], row[1]): (
                row[2],
                row[3],
                row[4]
            )
            for row in rows
        }


    finally:
        conn.close()
def save_income_status_with_cursor(
    cursor,
    income_template_id,
    month,
    year,
    actual_amount,
    status,
    notes=""
):

    template = cursor.execute(
        """
        SELECT
            id,
            vault_id,
            name,
            amount,
            due_day,
            account_id
        FROM income_templates
        WHERE id = ?
        """,
        (income_template_id,)
    ).fetchone()

    if not template:
        raise ValueError(
            "Income template not found."
        )

    existing = cursor.execute(
        """
        SELECT transaction_id
        FROM income_status
        WHERE income_template_id = ?
        AND month = ?
        AND year = ?
        """,
        (
            income_template_id,
            month,
            year
        )
    ).fetchone()

    transaction_id = (
        existing[0]
        if existing
        else None
    )

    if status == "RECEIVED":

        amount = (
            actual_amount
            if actual_amount is not None
            else template[3]
        )

        transaction_id = upsert_linked_transaction(
            cursor,
            transaction_id,
            template[1],
            template[5],
            get_planning_transaction_date(
                year,
                month,
                template[4]
            ),
            amount,
            INCOME,
            notes or f"Planning income: {template[2]}"
        )

    else:

        delete_linked_transaction(
            cursor,
            transaction_id
        )

        transaction_id = None

        if status == "CANCELLED":
            actual_amount = 0

    cursor.execute(
        """
        UPDATE income_status
        SET
            actual_amount = ?,
            status = ?,
            notes = ?,
            transaction_id = ?
        WHERE income_template_id = ?
        AND month = ?
        AND year = ?
        """,
        (
            actual_amount,
            status,
            notes,
            transaction_id,
            income_template_id,
            month,
            year
        )
    )

    if cursor.rowcount == 0:

        cursor.execute(
            """
            INSERT INTO income_status (

            income_template_id,
            month,
            year,
            actual_amount,
            status,
            notes,
            transaction_id

            )

            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                income_template_id,
                month,
                year,
                actual_amount,
                status,
                notes,
                transaction_id
            )
        )


def save_income_status(
    income_template_id,
    month,
    year,
    actual_amount,
    status,
    notes=""
):

    conn = get_connection()

    try:

        save_income_status_with_cursor(
            conn.cursor(),
            income_template_id,
            month,
            year,
            actual_amount,
            status,
            notes
        )

        conn.commit()
        clear_data_cache()

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()

@cache_data(ttl=60)
def get_cycle(
    vault_id,
    month,
    year
):
    context = get_cycle_for_date(
        vault_id,
        date(year, month, 1).isoformat()
    )
    return (
        context.id,
        context.vault_id,
        context.start_month,
        context.start_year,
        context.status,
        context.start_iso,
        context.end_iso
    )
def create_cycle(vault_id, month, year):
    context = get_cycle_for_date(
        vault_id,
        date(year, month, 1).isoformat()
    )
    return context.id
def get_next_month(month, year):

    if month == 12:
        return 1, year + 1

    return month + 1, year


@cache_data(ttl=60)
def get_monthly_planning_totals(vault_id, month, year):

    conn = get_connection()
    try:

        row = conn.execute(
            """
            WITH income_total AS (
                SELECT COALESCE(SUM(
                    CASE
                        WHEN s.status = 'CANCELLED' THEN 0
                        ELSE COALESCE(s.actual_amount, i.amount)
                    END
                ), 0) AS amount
                FROM income_templates i
                LEFT JOIN income_status s
                    ON s.income_template_id = i.id
                    AND s.month = ?
                    AND s.year = ?
                WHERE i.vault_id = ?
                AND i.is_active = 1
            ),
            commitment_totals AS (
                SELECT
                    COALESCE(SUM(
                        CASE
                            WHEN s.status = 'CANCELLED' THEN 0
                            ELSE COALESCE(s.actual_amount, c.amount)
                        END
                    ), 0) AS planned,
                    COALESCE(SUM(
                        CASE
                            WHEN COALESCE(s.status, 'PENDING') = 'PENDING'
                                THEN COALESCE(s.actual_amount, c.amount)
                            ELSE 0
                        END
                    ), 0) AS remaining
                FROM commitments c
                LEFT JOIN obligation_status s
                    ON s.commitment_id = c.id
                    AND s.month = ?
                    AND s.year = ?
                WHERE c.vault_id = ?
                AND c.is_active = 1
            )
            SELECT
                income_total.amount,
                commitment_totals.planned,
                commitment_totals.remaining
            FROM income_total
            CROSS JOIN commitment_totals
            """,
            (
                month,
                year,
                vault_id,
                month,
                year,
                vault_id
            )
        ).fetchone()


        return {
            "income": row[0],
            "planned_commitments": row[1],
            "remaining_commitments": row[2]
        }


    finally:
        conn.close()


@cache_data(ttl=60)
def get_cycle_planning_summary(vault_id, month, year, start_date, end_date):

    conn = get_connection()
    try:
        row = conn.execute(
            """
            WITH income_totals AS (
                SELECT
                    COALESCE(SUM(i.amount), 0) AS planned,
                    COALESCE(SUM(
                        CASE
                            WHEN s.status = 'RECEIVED'
                                THEN COALESCE(s.actual_amount, i.amount)
                            ELSE 0
                        END
                    ), 0) AS received
                FROM income_templates i
                LEFT JOIN income_status s
                    ON s.income_template_id = i.id
                    AND s.month = ?
                    AND s.year = ?
                WHERE i.vault_id = ?
                AND i.is_active = 1
            ),
            commitment_totals AS (
                SELECT
                    COALESCE(SUM(c.amount), 0) AS planned,
                    COALESCE(SUM(
                        CASE
                            WHEN s.status = 'PAID'
                                THEN COALESCE(s.actual_amount, c.amount)
                            ELSE 0
                        END
                    ), 0) AS completed,
                    COALESCE(SUM(
                        CASE
                            WHEN COALESCE(s.status, 'PENDING') IN (
                                'PENDING',
                                'CARRIED_FORWARD'
                            )
                                THEN COALESCE(s.actual_amount, c.amount)
                            ELSE 0
                        END
                    ), 0) AS remaining
                FROM commitments c
                LEFT JOIN obligation_status s
                    ON s.commitment_id = c.id
                    AND s.month = ?
                    AND s.year = ?
                WHERE c.vault_id = ?
                AND c.is_active = 1
            ),
            transaction_totals AS (
                SELECT
                    COALESCE(SUM(
                        CASE
                            WHEN transaction_type = 'Expense' THEN amount
                            ELSE 0
                        END
                    ), 0) AS expenses
                FROM transactions
                WHERE vault_id = ?
                AND is_deleted = 0
                AND date::date BETWEEN ?::date AND ?::date
            ),
            settings AS (
                SELECT COALESCE(monthly_savings_goal, 0) AS savings_goal
                FROM vaults
                WHERE id = ?
            )
            SELECT
                income_totals.planned,
                income_totals.received,
                commitment_totals.planned,
                commitment_totals.completed,
                commitment_totals.remaining,
                transaction_totals.expenses,
                settings.savings_goal
            FROM income_totals
            CROSS JOIN commitment_totals
            CROSS JOIN transaction_totals
            CROSS JOIN settings
            """,
            (
                month,
                year,
                vault_id,
                month,
                year,
                vault_id,
                vault_id,
                start_date,
                end_date,
                vault_id
            )
        ).fetchone()

        income_planned = float(row[0] or 0)
        income_received = float(row[1] or 0)
        commitments_planned = float(row[2] or 0)
        commitments_completed = float(row[3] or 0)
        remaining_commitments = float(row[4] or 0)
        expenses = float(row[5] or 0)
        savings_goal = float(row[6] or 0)
        projected_savings = max(
            income_planned
            - expenses
            - commitments_planned,
            0
        )

        return {
            "income_planned": income_planned,
            "income_received": income_received,
            "commitments_planned": commitments_planned,
            "commitments_completed": commitments_completed,
            "remaining_commitments": remaining_commitments,
            "expenses": expenses,
            "savings_goal": savings_goal,
            "projected_savings": projected_savings
        }

    finally:
        conn.close()
def carry_forward_commitment_with_cursor(
    cursor,
    commitment_id,
    month,
    year,
    amount
):

    commitment = cursor.execute(
        """
        SELECT amount
        FROM commitments
        WHERE id = ?
        """,
        (commitment_id,)
    ).fetchone()

    if not commitment:
        raise ValueError(
            "Commitment not found."
        )

    base_amount = commitment[0]
    carry_amount = (
        amount
        if amount is not None
        else base_amount
    )

    existing = cursor.execute(
        """
        SELECT actual_amount, status, notes
        FROM obligation_status
        WHERE commitment_id = ?
        AND month = ?
        AND year = ?
        """,
        (
            commitment_id,
            month,
            year
        )
    ).fetchone()

    if existing and existing[1] == "PAID":
        return

    next_amount = (
        existing[0]
        if existing and existing[0] is not None
        else base_amount
    ) + carry_amount

    notes = "Includes carried forward amount."

    cursor.execute(
        """
        UPDATE obligation_status
        SET
            actual_amount = ?,
            status = 'PENDING',
            notes = ?
        WHERE commitment_id = ?
        AND month = ?
        AND year = ?
        """,
        (
            next_amount,
            notes,
            commitment_id,
            month,
            year
        )
    )

    if cursor.rowcount == 0:

        cursor.execute(
            """
            INSERT INTO obligation_status (
                commitment_id,
                month,
                year,
                actual_amount,
                status,
                notes
            )
            VALUES (?, ?, ?, ?, 'PENDING', ?)
            """,
            (
                commitment_id,
                month,
                year,
                next_amount,
                notes
            )
        )


def carry_forward_income_with_cursor(
    cursor,
    income_template_id,
    month,
    year,
    amount
):

    template = cursor.execute(
        """
        SELECT amount
        FROM income_templates
        WHERE id = ?
        """,
        (income_template_id,)
    ).fetchone()

    if not template:
        raise ValueError(
            "Income template not found."
        )

    base_amount = template[0]
    carry_amount = (
        amount
        if amount is not None
        else base_amount
    )

    existing = cursor.execute(
        """
        SELECT actual_amount, status, notes
        FROM income_status
        WHERE income_template_id = ?
        AND month = ?
        AND year = ?
        """,
        (
            income_template_id,
            month,
            year
        )
    ).fetchone()

    if existing and existing[1] == "RECEIVED":
        return

    next_amount = (
        existing[0]
        if existing and existing[0] is not None
        else base_amount
    ) + carry_amount

    notes = "Includes carried forward amount."

    cursor.execute(
        """
        UPDATE income_status
        SET
            actual_amount = ?,
            status = 'PENDING',
            notes = ?
        WHERE income_template_id = ?
        AND month = ?
        AND year = ?
        """,
        (
            next_amount,
            notes,
            income_template_id,
            month,
            year
        )
    )

    if cursor.rowcount == 0:

        cursor.execute(
            """
            INSERT INTO income_status (
                income_template_id,
                month,
                year,
                actual_amount,
                status,
                notes
            )
            VALUES (?, ?, ?, ?, 'PENDING', ?)
            """,
            (
                income_template_id,
                month,
                year,
                next_amount,
                notes
            )
        )


def finalize_month(
    vault_id,
    month,
    year,
    updated_items
):

    conn = get_connection()
    try:
        cursor = conn.cursor()

        next_month, next_year = get_next_month(
            month,
            year
        )

        for item in updated_items:

            item_id = item["id"]
            item_type = item["type"]
            action = item["action"]
            amount = item["amount"]

            if action == "Paid":
                status = "PAID"

            elif action == "Cancelled":
                status = "CANCELLED"
                amount = 0

            elif action == "Carry Forward":
                status = "CARRIED_FORWARD"

            else:
                status = "CARRIED_FORWARD"

            if item_type == "commitment":

                save_obligation_status_with_cursor(
                    cursor,
                    item_id,
                    month,
                    year,
                    amount,
                    status
                )

                if status == "CARRIED_FORWARD":
                    carry_forward_commitment_with_cursor(
                        cursor,
                        item_id,
                        next_month,
                        next_year,
                        amount
                    )

            else:

                income_status = (
                    "RECEIVED"
                    if status == "PAID"
                    else status
                )

                save_income_status_with_cursor(
                    cursor,
                    item_id,
                    month,
                    year,
                    amount,
                    income_status
                )

                if status == "CARRIED_FORWARD":
                    carry_forward_income_with_cursor(
                        cursor,
                        item_id,
                        next_month,
                        next_year,
                        amount
                    )

        cursor.execute(
            """
            UPDATE monthly_cycles
            SET status='CLOSED'
            WHERE vault_id=?
            AND month=?
            AND year=?
            """,
            (
                vault_id,
                month,
                year
            )
        )

        cursor.execute(
            """
            INSERT INTO monthly_cycles
            (
                vault_id,
                month,
                year,
                status
            )
            VALUES
            (?, ?, ?, 'ACTIVE')
            ON CONFLICT (vault_id, month, year) DO NOTHING
            """,
            (
                vault_id,
                next_month,
                next_year
            )
        )

        cursor.execute(
            """
            UPDATE monthly_cycles
            SET status = 'ACTIVE'
            WHERE vault_id = ?
            AND month = ?
            AND year = ?
            """,
            (
                vault_id,
                next_month,
                next_year
            )
        )

        conn.commit()
        clear_data_cache()

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()


def add_income_template(
    vault_id,
    name,
    amount,
    due_day,
    account_id
):

    conn = get_connection()
    try:

        conn.execute(
            """
            INSERT INTO income_templates
            (
                vault_id,
                name,
                amount,
                due_day,
                account_id
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                vault_id,
                name,
                amount,
                due_day,
                account_id
            )
        )

        conn.commit()
        clear_data_cache()

    finally:
        conn.close()
@cache_data(ttl=60)
def get_income_templates(vault_id):

    conn = get_connection()
    try:

        rows = conn.execute(
            """
            SELECT
                i.id,
                i.name,
                i.amount,
                i.due_day,
                a.name,
                i.account_id

            FROM income_templates i

            LEFT JOIN accounts a
                ON i.account_id = a.id

            WHERE i.vault_id = ?
            AND i.is_active = 1

            ORDER BY i.due_day
            """,
            (vault_id,)
        ).fetchall()


        return rows


    finally:
        conn.close()
def update_income_template(
    template_id,
    name,
    amount,
    due_day,
    account_id
):

    conn = get_connection()
    try:

        conn.execute(
            """
            UPDATE income_templates
            SET
                name = ?,
                amount = ?,
                due_day = ?,
                account_id = ?
            WHERE id = ?
            """,
            (
                name,
                amount,
                due_day,
                account_id,
                template_id
            )
        )

        conn.commit()
        clear_data_cache()


    finally:
        conn.close()
def delete_income_template(
    template_id
):

    conn = get_connection()
    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            DELETE FROM transactions
            WHERE id IN (
                SELECT transaction_id
                FROM income_status
                WHERE income_template_id = ?
                AND transaction_id IS NOT NULL
            )
            """,
            (template_id,)
        )

        cursor.execute(
            """
            DELETE FROM income_status
            WHERE income_template_id = ?
            """,
            (template_id,)
        )

        cursor.execute(
            """
            DELETE FROM income_templates
            WHERE id = ?
            """,
            (template_id,)
        )

        conn.commit()
        clear_data_cache()

    finally:
        conn.close()
@cache_data(ttl=60)
def get_total_income_templates(
    vault_id
):

    conn = get_connection()
    try:

        total = conn.execute(
            """
            SELECT
                COALESCE(SUM(amount),0)
            FROM income_templates
            WHERE vault_id = ?
            AND is_active = 1
            """,
            (vault_id,)
        ).fetchone()[0]


        return total

    finally:
        conn.close()

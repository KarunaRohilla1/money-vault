from datetime import datetime

from db.core import (
    EXPENSE,
    INCOME,
    delete_linked_transaction,
    get_connection,
    get_planning_transaction_date,
    upsert_linked_transaction
)


def add_commitment(
    vault_id,
    name,
    amount,
    due_day,
    account_id
):

    conn = get_connection()

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
    conn.close()


def get_commitments(vault_id):

    conn = get_connection()

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

    conn.close()

    return commitments


def delete_commitment(
    commitment_id
):

    conn = get_connection()
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
    conn.close()


def update_commitment(
    commitment_id,
    name,
    amount,
    due_day,
    account_id
):

    conn = get_connection()

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
    conn.close()


def get_total_commitments(vault_id):

    conn = get_connection()

    total = conn.execute(
        """
        SELECT
            COALESCE(SUM(amount), 0)
        FROM commitments
        WHERE vault_id = ?
        """,
        (vault_id,)
    ).fetchone()[0]

    conn.close()

    return total


def get_obligation_status(
    commitment_id,
    month,
    year
):
    conn = get_connection()

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

    conn.close()

    return row


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

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()


def get_income_status(
    income_template_id,
    month,
    year
):

    conn = get_connection()

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

    conn.close()

    return row


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

    except Exception:

        conn.rollback()

        raise

    finally:

        conn.close()


def get_cycle(
    vault_id,
    month,
    year
):

    conn = get_connection()

    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT *

        FROM monthly_cycles

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

    cycle = cursor.fetchone()

    conn.close()

    return cycle


def create_cycle(vault_id, month, year):

    conn = get_connection()
    cursor = conn.cursor()

    today = datetime.now()

    if year == today.year and month == today.month:
        status = "ACTIVE"
    else:
        status = "PLANNED"

    cursor.execute(
        """
        INSERT INTO monthly_cycles
        (
            vault_id,
            month,
            year,
            status
        )
        VALUES (?, ?, ?, ?)
        ON CONFLICT (vault_id, month, year) DO NOTHING
        """,
        (
            vault_id,
            month,
            year,
            status
        )
    )

    # If this month already existed as PLANNED and it has now
    # become the current month, activate it automatically.

    if status == "ACTIVE":

        cursor.execute(
            """
            UPDATE monthly_cycles
            SET status = 'ACTIVE'
            WHERE vault_id = ?
            AND month = ?
            AND year = ?
            AND status = 'PLANNED'
            """,
            (
                vault_id,
                month,
                year
            )
        )

    conn.commit()
    conn.close()


def get_next_month(month, year):

    if month == 12:
        return 1, year + 1

    return month + 1, year


def get_monthly_planning_totals(vault_id, month, year):

    income = 0

    for template in get_income_templates(vault_id):

        base_amount = template[2]
        status = get_income_status(
            template[0],
            month,
            year
        )

        if status and status[1] == "CANCELLED":
            continue

        income += (
            status[0]
            if status and status[0] is not None
            else base_amount
        )

    planned_commitments = 0
    remaining_commitments = 0

    for commitment in get_commitments(vault_id):

        base_amount = commitment[2]
        status = get_obligation_status(
            commitment[0],
            month,
            year
        )

        if status and status[1] == "CANCELLED":
            continue

        effective_amount = (
            status[0]
            if status and status[0] is not None
            else base_amount
        )

        planned_commitments += effective_amount

        if not status or status[1] == "PENDING":

            remaining_commitments += effective_amount

    return {
        "income": income,
        "planned_commitments": planned_commitments,
        "remaining_commitments": remaining_commitments
    }


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
    cursor = conn.cursor()

    try:
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
    conn.close()


def get_income_templates(vault_id):

    conn = get_connection()

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

    conn.close()

    return rows


def update_income_template(
    template_id,
    name,
    amount,
    due_day,
    account_id
):

    conn = get_connection()

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
    conn.close()


def delete_income_template(
    template_id
):

    conn = get_connection()
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
    conn.close()


def get_total_income_templates(
    vault_id
):

    conn = get_connection()

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

    conn.close()

    return total

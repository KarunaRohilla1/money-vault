from calendar import monthrange
from datetime import date, timedelta

from db.cache import cache_data, clear_data_cache
from db.core import EXPENSE, get_connection
from db.financial_cycles import (
    get_current_cycle,
    get_cycle_context_with_cursor,
    get_cycle_for_date
)
from db.transaction_shares import (
    ALLOCATION_FIXED,
    replace_transaction_shares_with_cursor
)
from db.postgres import errors


BILL_PENDING = "Pending"
BILL_PAID = "Paid"
BILL_SKIPPED = "Skipped"
BILL_CANCELLED = "Cancelled"

CYCLE_ACTIVE = "Active"
CYCLE_CLOSED = "Closed"

FREQUENCIES = [
    "Monthly",
    "Quarterly",
    "Half-Yearly",
    "Yearly"
]


def empty_bills_summary():
    return {
        "total_due_soon": 0,
        "due_soon_count": 0,
        "upcoming_bills": [],
        "total_active_bills": 0
    }


def normalize_due_day(due_day):
    due_day = int(due_day)
    if due_day < 1 or due_day > 31:
        raise ValueError("Due day must be between 1 and 31.")
    return due_day


def normalize_amount(amount):
    if amount is None:
        raise ValueError("Amount is required.")
    amount = float(amount)
    if amount <= 0:
        raise ValueError("Amount must be greater than zero.")
    return round(amount, 2)


def month_bounds(year, month):
    start = date(year, month, 1)
    end = date(year, month, monthrange(year, month)[1])
    return start, end


def next_month(year, month):
    if month == 12:
        return year + 1, 1
    return year, month + 1


def add_months(value, count):
    month = value.month - 1 + count
    year = value.year + month // 12
    month = month % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return date(year, month, day)


def frequency_interval(frequency):
    return {
        "Monthly": 1,
        "Quarterly": 3,
        "Half-Yearly": 6,
        "Yearly": 12
    }.get(frequency, 1)


def bill_applies_to_month(bill, year, month):
    start_date = date.fromisoformat(bill["start_date"])
    cycle_start = date(year, month, 1)
    if cycle_start < date(start_date.year, start_date.month, 1):
        return False

    if bill["end_date"]:
        end_date = date.fromisoformat(bill["end_date"])
        if cycle_start > date(end_date.year, end_date.month, 1):
            return False

    month_delta = (
        (year - start_date.year) * 12
        + month
        - start_date.month
    )
    return month_delta % frequency_interval(bill["frequency"]) == 0


def due_date_for_bill(bill, year, month):
    day = min(
        int(bill["due_day"]),
        monthrange(year, month)[1]
    )
    return date(year, month, day)


def row_to_bill(row):
    return {
        "id": row[0],
        "shared_vault_id": row[1],
        "name": row[2],
        "amount": float(row[3] or 0),
        "due_day": row[4],
        "category_id": row[5],
        "frequency": row[6] or "Monthly",
        "start_date": row[7] or date.today().replace(day=1).isoformat(),
        "end_date": row[8],
        "notes": row[9] or "",
        "is_active": int(row[10] or 0),
        "category_icon": row[11] or "calendar_month",
        "category_name": row[12] or ""
    }


def get_participants_with_cursor(cursor, shared_vault_id):
    return cursor.execute(
        """
        SELECT
            v.id,
            v.name
        FROM vault_shares vs
        JOIN vaults v
            ON vs.shared_vault_id = v.id
        WHERE vs.vault_id = ?
        AND v.vault_type = 'Individual'
        ORDER BY v.name
        """,
        (shared_vault_id,)
    ).fetchall()


def get_income_ratios_with_cursor(cursor, shared_vault_id):
    participants = get_participants_with_cursor(
        cursor,
        shared_vault_id
    )
    if not participants:
        return []

    income_rows = cursor.execute(
        """
        SELECT
            vault_id,
            COALESCE(SUM(amount), 0)
        FROM income_templates
        WHERE vault_id IN ({})
        AND is_active = 1
        GROUP BY vault_id
        """.format(",".join(["?"] * len(participants))),
        tuple(participant[0] for participant in participants)
    ).fetchall()
    income_by_vault = {
        row[0]: float(row[1] or 0)
        for row in income_rows
    }
    total_income = sum(
        income_by_vault.get(participant[0], 0)
        for participant in participants
    )

    ratios = []
    if total_income <= 0:
        equal_ratio = round(100 / len(participants), 6)
        for participant in participants:
            ratios.append({
                "vault_id": participant[0],
                "name": participant[1],
                "income": 0,
                "ratio": equal_ratio
            })
        return ratios

    for participant in participants:
        income = income_by_vault.get(participant[0], 0)
        ratios.append({
            "vault_id": participant[0],
            "name": participant[1],
            "income": income,
            "ratio": round(income / total_income * 100, 6)
        })

    return ratios


def calculate_bill_shares(amount, ratios):
    if not ratios:
        return []

    allocated = 0
    shares = []
    amount_cents = int(round(float(amount) * 100))
    for index, ratio in enumerate(ratios):
        if index == len(ratios) - 1:
            share_cents = amount_cents - allocated
        else:
            share_cents = int(round(amount_cents * ratio["ratio"] / 100))
            allocated += share_cents

        shares.append({
            "participant_vault_id": ratio["vault_id"],
            "participant_name": ratio["name"],
            "expected_amount": round(share_cents / 100, 2),
            "expected_percentage": ratio["ratio"]
        })

    return shares


def get_or_create_cycle_with_cursor(cursor, shared_vault_id, year, month):
    existing = get_existing_cycle_with_cursor(
        cursor,
        shared_vault_id,
        year,
        month
    )

    if existing:
        cycle_id = existing[0]
    else:
        cursor.execute(
            """
            INSERT INTO shared_bill_cycles
            (
                shared_vault_id,
                month,
                year,
                status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                shared_vault_id,
                month,
                year,
                CYCLE_ACTIVE
            )
        )
        cycle_id = cursor.lastrowid

    generate_bill_instances_with_cursor(
        cursor,
        cycle_id,
        shared_vault_id,
        year,
        month
    )
    return cycle_id


def get_existing_cycle_with_cursor(cursor, shared_vault_id, year, month):
    return cursor.execute(
        """
        SELECT
            id,
            shared_vault_id,
            month,
            year,
            status,
            total_amount,
            paid_amount,
            remaining_amount
        FROM shared_bill_cycles
        WHERE shared_vault_id = ?
        AND month = ?
        AND year = ?
        """,
        (
            shared_vault_id,
            month,
            year
        )
    ).fetchone()


def generate_bill_instances_with_cursor(cursor, cycle_id, shared_vault_id, year, month):
    cycle = cursor.execute(
        """
        SELECT status
        FROM shared_bill_cycles
        WHERE id = ?
        """,
        (cycle_id,)
    ).fetchone()

    if cycle and cycle[0] == CYCLE_CLOSED:
        return

    bill_rows = cursor.execute(
        """
        SELECT
            b.id,
            b.shared_vault_id,
            b.name,
            b.amount,
            b.due_day,
            b.category_id,
            b.frequency,
            b.start_date,
            b.end_date,
            COALESCE(b.notes, ''),
            b.is_active,
            COALESCE(c.emoji, 'calendar_month'),
            COALESCE(c.name, '')
        FROM shared_bills b
        LEFT JOIN categories c
            ON b.category_id = c.id
        WHERE b.shared_vault_id = ?
        AND b.is_active = 1
        ORDER BY b.due_day, b.name
        """,
        (shared_vault_id,)
    ).fetchall()
    ratios = get_income_ratios_with_cursor(
        cursor,
        shared_vault_id
    )

    for row in bill_rows:
        bill = row_to_bill(row)
        if not bill_applies_to_month(
            bill,
            year,
            month
        ):
            continue

        due_date = due_date_for_bill(
            bill,
            year,
            month
        )
        cursor.execute(
            """
            INSERT INTO shared_bill_instances
            (
                cycle_id,
                bill_id,
                name,
                amount,
                due_date,
                frequency,
                category_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (cycle_id, bill_id) DO NOTHING
            """,
            (
                cycle_id,
                bill["id"],
                bill["name"],
                bill["amount"],
                due_date.isoformat(),
                bill["frequency"],
                bill["category_id"]
            )
            ,
            capture_lastrowid=False
        )
        instance = cursor.execute(
            """
            SELECT id
            FROM shared_bill_instances
            WHERE cycle_id = ?
            AND bill_id = ?
            """,
            (
                cycle_id,
                bill["id"]
            )
        ).fetchone()
        if not instance:
            continue

        shares = calculate_bill_shares(
            bill["amount"],
            ratios
        )
        for share in shares:
            cursor.execute(
                """
                INSERT INTO shared_bill_instance_shares
                (
                    bill_instance_id,
                    participant_vault_id,
                    expected_amount,
                    expected_percentage
                )
                VALUES (?, ?, ?, ?)
                ON CONFLICT (bill_instance_id, participant_vault_id)
                DO NOTHING
                """,
                (
                    instance[0],
                    share["participant_vault_id"],
                    share["expected_amount"],
                    share["expected_percentage"]
                )
                ,
                capture_lastrowid=False
            )


def get_selected_cycle(shared_vault_id, year=None, month=None):
    today = date.today()
    year = year or today.year
    month = month or today.month

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cycle = get_existing_cycle_with_cursor(
            cursor,
            shared_vault_id,
            year,
            month
        )
        return cycle[0] if cycle else None

    finally:
        conn.close()


def initialize_shared_bill_cycles():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        shared_vaults = cursor.execute(
            """
            SELECT id
            FROM vaults
            WHERE vault_type = 'Shared'
            """
        ).fetchall()

        for row in shared_vaults:
            financial_cycle = get_current_cycle(
                row[0]
            )
            get_or_create_cycle_with_cursor(
                cursor,
                row[0],
                financial_cycle.start_year,
                financial_cycle.start_month
            )

        conn.commit()
    finally:
        conn.close()


def ensure_current_shared_bill_cycle_with_cursor(cursor, shared_vault_id):
    financial_cycle = get_cycle_context_with_cursor(
        cursor,
        shared_vault_id,
        date.today()
    )
    return get_or_create_cycle_with_cursor(
        cursor,
        shared_vault_id,
        financial_cycle.start_year,
        financial_cycle.start_month
    )


def get_shared_bills_page_data(shared_vault_id, year=None, month=None):
    if year and month:
        financial_cycle = get_cycle_for_date(
            shared_vault_id,
            date(year, month, 1).isoformat()
        )
    else:
        financial_cycle = get_current_cycle(
            shared_vault_id
        )
    year = financial_cycle.start_year
    month = financial_cycle.start_month

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cycle = get_existing_cycle_with_cursor(
            cursor,
            shared_vault_id,
            year,
            month
        )
        if cycle:
            cycle_id = cycle[0]
            instances = cursor.execute(
                """
                SELECT
                    i.id,
                    i.bill_id,
                    i.name,
                    i.amount,
                    i.due_date,
                    i.frequency,
                    i.category_id,
                    i.status,
                    i.payer_vault_id,
                    COALESCE(payer.name, ''),
                    i.payment_date,
                    COALESCE(i.payment_notes, ''),
                    i.transaction_id,
                    COALESCE(c.emoji, 'calendar_month'),
                    COALESCE(c.name, '')
                FROM shared_bill_instances i
                LEFT JOIN vaults payer
                    ON i.payer_vault_id = payer.id
                LEFT JOIN categories c
                    ON i.category_id = c.id
                WHERE i.cycle_id = ?
                ORDER BY i.due_date, i.name
                """,
                (cycle_id,)
            ).fetchall()
            share_rows = cursor.execute(
                """
                SELECT
                    s.bill_instance_id,
                    s.participant_vault_id,
                    v.name,
                    s.expected_amount,
                    s.expected_percentage
                FROM shared_bill_instance_shares s
                JOIN vaults v
                    ON s.participant_vault_id = v.id
                WHERE s.bill_instance_id IN (
                    SELECT id
                    FROM shared_bill_instances
                    WHERE cycle_id = ?
                )
                ORDER BY v.name
                """,
                (cycle_id,)
            ).fetchall()
        else:
            instances = []
            share_rows = []
        participants = get_income_ratios_with_cursor(
            cursor,
            shared_vault_id
        )

        shares_by_instance = {}
        for share in share_rows:
            shares_by_instance.setdefault(
                share[0],
                []
            ).append({
                "participant_vault_id": share[1],
                "participant_name": share[2],
                "expected_amount": float(share[3] or 0),
                "expected_percentage": float(share[4] or 0)
            })

        pending = []
        completed = []
        total_amount = 0
        paid_amount = 0
        participant_summary = {
            participant["vault_id"]: {
                **participant,
                "expected": 0,
                "paid": 0,
                "difference": 0,
                "progress": 0
            }
            for participant in participants
        }

        for instance in instances:
            status = instance[7]
            amount = float(instance[3] or 0)
            if status != BILL_CANCELLED:
                total_amount += amount

            if status == BILL_PAID:
                paid_amount += amount
                payer_summary = participant_summary.get(
                    instance[8]
                )
                if payer_summary:
                    payer_summary["paid"] += amount

            for share in shares_by_instance.get(instance[0], []):
                participant = participant_summary.get(
                    share["participant_vault_id"]
                )
                if participant and status != BILL_CANCELLED:
                    participant["expected"] += share["expected_amount"]

            item = {
                "id": instance[0],
                "bill_id": instance[1],
                "name": instance[2],
                "amount": amount,
                "due_date": instance[4],
                "frequency": instance[5],
                "category_id": instance[6],
                "status": status,
                "payer_vault_id": instance[8],
                "payer_name": instance[9],
                "payment_date": instance[10],
                "payment_notes": instance[11],
                "transaction_id": instance[12],
                "icon": instance[13],
                "category_name": instance[14],
                "shares": shares_by_instance.get(instance[0], [])
            }

            if status == BILL_PAID:
                completed.append(item)
            else:
                pending.append(item)

        for participant in participant_summary.values():
            participant["difference"] = round(
                participant["paid"] - participant["expected"],
                2
            )
            participant["progress"] = (
                participant["paid"] / participant["expected"] * 100
                if participant["expected"]
                else 0
            )

        remaining = max(
            total_amount - paid_amount,
            0
        )
        next_due = next(
            (
                item for item in pending
                if item["status"] == BILL_PENDING
            ),
            None
        )

        balance = calculate_cycle_balance(
            list(participant_summary.values())
        )

        return {
            "cycle": {
                "id": cycle[0] if cycle else None,
                "shared_vault_id": cycle[1] if cycle else shared_vault_id,
                "month": cycle[2] if cycle else month,
                "year": cycle[3] if cycle else year,
                "start_date": financial_cycle.start_iso,
                "end_date": financial_cycle.end_iso,
                "display_name": financial_cycle.display_name,
                "status": cycle[4] if cycle else CYCLE_ACTIVE,
                "is_closed": (
                    (cycle[4] if cycle else CYCLE_ACTIVE) == CYCLE_CLOSED
                    or financial_cycle.is_closed
                )
            },
            "participants": list(participant_summary.values()),
            "pending_bills": pending,
            "completed_bills": completed,
            "summary": {
                "total_amount": round(total_amount, 2),
                "paid_amount": round(paid_amount, 2),
                "remaining_amount": round(remaining, 2),
                "total_count": len([
                    item for item in instances
                    if item[7] != BILL_CANCELLED
                ]),
                "paid_count": len(completed),
                "pending_count": len([
                    item for item in pending
                    if item["status"] == BILL_PENDING
                ]),
                "next_due": next_due,
                "balance": balance
            }
        }

    finally:
        conn.close()


def calculate_cycle_balance(participants):
    creditors = [
        participant.copy()
        for participant in participants
        if participant["difference"] > 0
    ]
    debtors = [
        participant.copy()
        for participant in participants
        if participant["difference"] < 0
    ]
    settlements = []

    for debtor in debtors:
        owed = round(
            -debtor["difference"],
            2
        )
        for creditor in creditors:
            if owed <= 0:
                break
            available = max(
                creditor["difference"],
                0
            )
            if available <= 0:
                continue
            amount = round(
                min(owed, available),
                2
            )
            settlements.append({
                "from": debtor["name"],
                "to": creditor["name"],
                "amount": amount
            })
            owed = round(
                owed - amount,
                2
            )
            creditor["difference"] = round(
                creditor["difference"] - amount,
                2
            )

    return settlements


def get_shared_bills_summary(shared_vault_id, today_iso=None, upcoming_days=10):
    today = (
        date.fromisoformat(today_iso)
        if today_iso
        else date.today()
    )
    data = get_shared_bills_page_data(
        shared_vault_id,
        today.year,
        today.month
    )
    due_soon = []
    total_due = 0

    for bill in data["pending_bills"]:
        due_date = date.fromisoformat(
            bill["due_date"]
        )
        days_until_due = (
            due_date - today
        ).days
        if bill["status"] == BILL_PENDING and days_until_due <= upcoming_days:
            due_soon.append({
                **bill,
                "days_until_due": days_until_due
            })
            total_due += bill["amount"]

    return {
        "total_due_soon": round(total_due, 2),
        "due_soon_count": len(due_soon),
        "upcoming_bills": due_soon[:3],
        "total_active_bills": data["summary"]["total_count"]
    }


@cache_data(ttl=60)
def get_shared_bills(shared_vault_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        return cursor.execute(
            """
            SELECT
                b.id,
                b.name,
                b.amount,
                b.due_day,
                b.category_id,
                COALESCE(c.emoji, 'calendar_month') AS category_icon,
                COALESCE(c.name, '') AS category_name,
                COALESCE(b.notes, '') AS notes,
                b.frequency,
                b.start_date,
                b.end_date,
                b.is_active
            FROM shared_bills b
            LEFT JOIN categories c
                ON b.category_id = c.id
            WHERE b.shared_vault_id = ?
            AND b.is_active = 1
            ORDER BY b.due_day, b.name
            """,
            (shared_vault_id,)
        ).fetchall()

    except Exception as error:
        if errors and isinstance(error, errors.UndefinedTable):
            return []
        raise

    finally:
        conn.close()


def add_shared_bill(
    shared_vault_id,
    name,
    amount,
    due_day,
    category_id=None,
    notes="",
    frequency="Monthly",
    start_date=None,
    end_date=None,
    is_active=True
):
    name = name.strip()
    amount = normalize_amount(amount)
    due_day = normalize_due_day(due_day)
    frequency = frequency if frequency in FREQUENCIES else "Monthly"
    start_date = start_date or date.today().replace(day=1).isoformat()

    if not name:
        raise ValueError("Shared bill name cannot be empty.")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO shared_bills
            (
                shared_vault_id,
                name,
                amount,
                due_day,
                category_id,
                notes,
                frequency,
                start_date,
                end_date,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                shared_vault_id,
                name,
                amount,
                due_day,
                category_id,
                notes.strip(),
                frequency,
                start_date,
                end_date,
                1 if is_active else 0
            )
        )
        bill_id = cursor.lastrowid
        ensure_current_shared_bill_cycle_with_cursor(
            cursor,
            shared_vault_id
        )
        conn.commit()
        clear_data_cache((
            "shared_bills",
            "dashboard",
            "reports",
            "transactions",
            "accounts",
            "shared_expenses",
            "transaction_shares"
        ))
        return bill_id

    finally:
        conn.close()


def update_shared_bill(
    bill_id,
    name,
    amount,
    due_day,
    category_id=None,
    notes="",
    frequency="Monthly",
    start_date=None,
    end_date=None,
    is_active=True
):
    name = name.strip()
    amount = normalize_amount(amount)
    due_day = normalize_due_day(due_day)
    frequency = frequency if frequency in FREQUENCIES else "Monthly"

    if not name:
        raise ValueError("Shared bill name cannot be empty.")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        bill = cursor.execute(
            """
            SELECT shared_vault_id
            FROM shared_bills
            WHERE id = ?
            """,
            (bill_id,)
        ).fetchone()
        if not bill:
            raise ValueError("Bill not found.")
        cursor.execute(
            """
            UPDATE shared_bills
            SET
                name = ?,
                amount = ?,
                due_day = ?,
                category_id = ?,
                notes = ?,
                frequency = ?,
                start_date = ?,
                end_date = ?,
                is_active = ?
            WHERE id = ?
            """,
            (
                name,
                amount,
                due_day,
                category_id,
                notes.strip(),
                frequency,
                start_date,
                end_date,
                1 if is_active else 0,
                bill_id
            )
        )
        ensure_current_shared_bill_cycle_with_cursor(
            cursor,
            bill[0]
        )
        conn.commit()
        clear_data_cache((
            "shared_bills",
            "dashboard",
            "reports",
            "transactions",
            "accounts",
            "shared_expenses",
            "transaction_shares"
        ))
        return True

    finally:
        conn.close()


def delete_shared_bill(bill_id):
    return cancel_shared_bill(bill_id)


def cancel_shared_bill(bill_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE shared_bills
            SET is_active = 0
            WHERE id = ?
            """,
            (bill_id,)
        )
        cursor.execute(
            """
            UPDATE shared_bill_instances
            SET status = ?
            WHERE bill_id = ?
            AND status = ?
            """,
            (
                BILL_CANCELLED,
                bill_id,
                BILL_PENDING
            )
        )
        conn.commit()
        clear_data_cache((
            "shared_bills",
            "dashboard",
            "reports",
            "transactions",
            "accounts",
            "shared_expenses",
            "transaction_shares"
        ))
        return True

    finally:
        conn.close()


def duplicate_shared_bill(bill_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        bill = cursor.execute(
            """
            SELECT
                shared_vault_id,
                name,
                amount,
                due_day,
                category_id,
                notes,
                frequency,
                start_date,
                end_date,
                is_active
            FROM shared_bills
            WHERE id = ?
            """,
            (bill_id,)
        ).fetchone()
        if not bill:
            raise ValueError("Bill not found.")
        cursor.execute(
            """
            INSERT INTO shared_bills
            (
                shared_vault_id,
                name,
                amount,
                due_day,
                category_id,
                notes,
                frequency,
                start_date,
                end_date,
                is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                bill[0],
                f"{bill[1]} Copy",
                bill[2],
                bill[3],
                bill[4],
                bill[5],
                bill[6],
                bill[7],
                bill[8],
                bill[9]
            )
        )
        new_bill_id = cursor.lastrowid
        ensure_current_shared_bill_cycle_with_cursor(
            cursor,
            bill[0]
        )
        conn.commit()
        clear_data_cache((
            "shared_bills",
            "dashboard",
            "reports",
            "transactions",
            "accounts",
            "shared_expenses",
            "transaction_shares"
        ))
        return new_bill_id

    finally:
        conn.close()


def skip_bill_instance(instance_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE shared_bill_instances
            SET status = ?
            WHERE id = ?
            AND status = ?
            """,
            (
                BILL_SKIPPED,
                instance_id,
                BILL_PENDING
            )
        )
        conn.commit()
        clear_data_cache((
            "shared_bills",
            "dashboard",
            "reports",
            "transactions",
            "accounts",
            "shared_expenses",
            "transaction_shares"
        ))

    finally:
        conn.close()


def get_primary_account_with_cursor(cursor, vault_id):
    account = cursor.execute(
        """
        SELECT id
        FROM accounts
        WHERE vault_id = ?
        AND is_active = 1
        ORDER BY is_primary DESC, id
        LIMIT 1
        """,
        (vault_id,)
    ).fetchone()

    if not account:
        raise ValueError("The selected payer needs an active account.")

    return account[0]


def mark_bill_paid(instance_id, payer_vault_id, payment_date, notes=""):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        instance = cursor.execute(
            """
            SELECT
                i.id,
                i.cycle_id,
                c.shared_vault_id,
                i.name,
                i.amount,
                i.category_id,
                i.status
            FROM shared_bill_instances i
            JOIN shared_bill_cycles c
                ON i.cycle_id = c.id
            WHERE i.id = ?
            """,
            (instance_id,)
        ).fetchone()
        if not instance:
            raise ValueError("Bill instance not found.")
        if instance[6] != BILL_PENDING:
            raise ValueError("Only pending bills can be marked paid.")

        account_id = get_primary_account_with_cursor(
            cursor,
            payer_vault_id
        )
        shares = cursor.execute(
            """
            SELECT
                participant_vault_id,
                expected_amount,
                expected_percentage
            FROM shared_bill_instance_shares
            WHERE bill_instance_id = ?
            ORDER BY participant_vault_id
            """,
            (instance_id,)
        ).fetchall()
        cursor.execute(
            """
            INSERT INTO transactions
            (
                vault_id,
                beneficiary_vault_id,
                account_id,
                date,
                amount,
                category_id,
                transaction_type,
                allocation_method,
                notes
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                payer_vault_id,
                instance[2],
                account_id,
                payment_date,
                instance[4],
                instance[5],
                EXPENSE,
                ALLOCATION_FIXED,
                notes.strip() or f"Shared bill: {instance[3]}"
            )
        )
        transaction_id = cursor.lastrowid
        replace_transaction_shares_with_cursor(
            cursor,
            transaction_id,
            [
                {
                    "participant_vault_id": share[0],
                    "share_amount": share[1],
                    "share_percentage": share[2]
                }
                for share in shares
            ]
        )
        cursor.execute(
            """
            UPDATE shared_bill_instances
            SET
                status = ?,
                payer_vault_id = ?,
                payment_date = ?,
                payment_notes = ?,
                transaction_id = ?
            WHERE id = ?
            """,
            (
                BILL_PAID,
                payer_vault_id,
                payment_date,
                notes.strip(),
                transaction_id,
                instance_id
            )
        )
        conn.commit()
        clear_data_cache((
            "shared_bills",
            "dashboard",
            "reports",
            "transactions",
            "accounts",
            "shared_expenses",
            "transaction_shares"
        ))
        return transaction_id

    finally:
        conn.close()


def close_cycle(cycle_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cycle = cursor.execute(
            """
            SELECT
                shared_vault_id,
                month,
                year,
                status
            FROM shared_bill_cycles
            WHERE id = ?
            """,
            (cycle_id,)
        ).fetchone()
        if not cycle:
            raise ValueError("Cycle not found.")
        if cycle[3] == CYCLE_CLOSED:
            raise ValueError("Cycle is already closed.")

        totals = cursor.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status != ? THEN amount ELSE 0 END), 0),
                COALESCE(SUM(CASE WHEN status = ? THEN amount ELSE 0 END), 0)
            FROM shared_bill_instances
            WHERE cycle_id = ?
            """,
            (
                BILL_CANCELLED,
                BILL_PAID,
                cycle_id
            )
        ).fetchone()
        total = float(totals[0] or 0)
        paid = float(totals[1] or 0)
        remaining = max(total - paid, 0)
        cursor.execute(
            """
            UPDATE shared_bill_cycles
            SET
                status = ?,
                total_amount = ?,
                paid_amount = ?,
                remaining_amount = ?,
                closed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (
                CYCLE_CLOSED,
                total,
                paid,
                remaining,
                cycle_id
            )
        )
        next_year, next_cycle_month = next_month(
            cycle[2],
            cycle[1]
        )
        get_or_create_cycle_with_cursor(
            cursor,
            cycle[0],
            next_year,
            next_cycle_month
        )
        conn.commit()
        clear_data_cache((
            "shared_bills",
            "dashboard",
            "reports",
            "transactions",
            "accounts",
            "shared_expenses",
            "transaction_shares",
            "cycles"
        ))

    finally:
        conn.close()

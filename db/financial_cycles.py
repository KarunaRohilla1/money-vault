from dataclasses import dataclass
from datetime import date, datetime, timedelta

from db.cache import cache_data, clear_data_cache
from db.core import get_connection


ACTIVE = "ACTIVE"
CLOSED = "CLOSED"
CURRENT = "Current"
UPCOMING = "Upcoming"
COMPLETED = "Completed"


@dataclass(frozen=True)
class CycleContext:
    id: int
    vault_id: int
    start_date: date
    end_date: date
    status: str
    closed_at: object = None

    @property
    def start_iso(self):
        return self.start_date.isoformat()

    @property
    def end_iso(self):
        return self.end_date.isoformat()

    @property
    def start_month(self):
        return self.start_date.month

    @property
    def start_year(self):
        return self.start_date.year

    @property
    def display_name(self):
        return format_cycle_range(
            self.start_date,
            self.end_date,
            include_year=True
        )

    @property
    def days_completed(self):
        today = date.today()
        total_days = self.total_days
        if today < self.start_date:
            return 0
        if today > self.end_date:
            return total_days
        return min(
            max((today - self.start_date).days + 1, 0),
            total_days
        )

    @property
    def days_remaining(self):
        if self.status == COMPLETED:
            return 0
        return max((self.end_date - date.today()).days + 1, 0)

    @property
    def total_days(self):
        return max((self.end_date - self.start_date).days + 1, 1)

    @property
    def progress_percent(self):
        return int(
            self.days_completed / self.total_days * 100
        )

    @property
    def is_active(self):
        return self.status == CURRENT

    @property
    def is_closed(self):
        return self.status == COMPLETED


def normalize_start_day(day):
    day = int(day or 1)
    if day < 1:
        return 1
    if day > 28:
        return 28
    return day


def parse_date(value):
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value)
    if " " in text:
        text = text.split(" ", 1)[0]
    if "T" in text:
        text = text.split("T", 1)[0]
    return date.fromisoformat(text)


def add_months(value, months):
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, 28)
    return date(year, month, day)


def derive_cycle_status(cycle_start, cycle_end, today=None):
    today = today or date.today()
    if today < cycle_start:
        return UPCOMING
    if cycle_start <= today <= cycle_end:
        return CURRENT
    return COMPLETED


def format_cycle_range(cycle_start, cycle_end, include_year=False):
    date_format = "%d %b %Y" if include_year else "%d %b"
    return (
        f"{cycle_start.strftime(date_format)}"
        f" → {cycle_end.strftime(date_format)}"
    )


def get_vault_cycle_settings_with_cursor(cursor, vault_id):
    row = cursor.execute(
        """
        SELECT
            COALESCE(financial_cycle_start_day, month_start_day, 1),
            COALESCE(created_at::date, CURRENT_DATE)
        FROM vaults
        WHERE id = ?
        """,
        (vault_id,)
    ).fetchone()
    if not row:
        return 1, date.today()
    return normalize_start_day(row[0]), parse_date(row[1])


def get_vault_cycle_start_day_with_cursor(cursor, vault_id):
    start_day, _created_at = get_vault_cycle_settings_with_cursor(
        cursor,
        vault_id
    )
    return start_day


def scheduled_cycle_start_for(target_date, start_day):
    start_day = normalize_start_day(start_day)
    current_month_start = date(
        target_date.year,
        target_date.month,
        start_day
    )
    if target_date >= current_month_start:
        return current_month_start
    return add_months(current_month_start, -1)


def first_cycle_start_for(vault_created_at, start_day):
    scheduled_start = scheduled_cycle_start_for(
        vault_created_at,
        start_day
    )
    return max(
        scheduled_start,
        vault_created_at
    )


def cycle_bounds_for(target_date, start_day, vault_created_at=None):
    start_day = normalize_start_day(start_day)
    start = scheduled_cycle_start_for(
        target_date,
        start_day
    )
    if vault_created_at and start < vault_created_at:
        start = vault_created_at
    end = add_months(
        scheduled_cycle_start_for(target_date, start_day),
        1
    ) - timedelta(days=1)
    if end < start:
        end = start
    return start, end


def row_to_context(row):
    if not row:
        return None
    start_date = parse_date(row[2])
    end_date = parse_date(row[3])
    return CycleContext(
        id=row[0],
        vault_id=row[1],
        start_date=start_date,
        end_date=end_date,
        status=derive_cycle_status(start_date, end_date),
        closed_at=row[5] if len(row) > 5 else None
    )


def get_participant_income_ratios_with_cursor(cursor, shared_vault_id):
    participants = cursor.execute(
        """
        SELECT
            v.id,
            v.name
        FROM vault_shares vs
        JOIN vaults v
            ON v.id = vs.shared_vault_id
        WHERE vs.vault_id = ?
        AND v.vault_type = 'Individual'
        ORDER BY v.name
        """,
        (shared_vault_id,)
    ).fetchall()

    if not participants:
        return []

    placeholders = ",".join(["?"] * len(participants))
    income_rows = cursor.execute(
        f"""
        SELECT
            vault_id,
            COALESCE(SUM(amount), 0)
        FROM income_templates
        WHERE vault_id IN ({placeholders})
        AND is_active = 1
        GROUP BY vault_id
        """,
        tuple(row[0] for row in participants)
    ).fetchall()
    income_by_vault = {
        row[0]: float(row[1] or 0)
        for row in income_rows
    }
    total_income = sum(
        income_by_vault.get(row[0], 0)
        for row in participants
    )

    ratios = []
    for index, participant in enumerate(participants):
        income = income_by_vault.get(participant[0], 0)
        if total_income > 0:
            ratio = round(income / total_income * 100, 6)
        else:
            ratio = round(100 / len(participants), 6)
        if index == len(participants) - 1:
            ratio = round(
                100 - sum(item["income_ratio"] for item in ratios),
                6
            )
        ratios.append({
            "participant_vault_id": participant[0],
            "name": participant[1],
            "income": income,
            "income_ratio": ratio
        })

    return ratios


def freeze_cycle_contributions_with_cursor(cursor, cycle_id, vault_id):
    return


def repair_financial_cycles_with_cursor(cursor, vault_id, vault_created_at):
    cursor.execute(
        """
        DELETE FROM financial_cycles
        WHERE vault_id = ?
        AND start_date::date < ?::date
        """,
        (
            vault_id,
            vault_created_at.isoformat()
        )
    )

    cursor.execute(
        """
        DELETE FROM financial_cycles fc
        USING financial_cycles duplicate
        WHERE fc.vault_id = ?
        AND duplicate.vault_id = fc.vault_id
        AND duplicate.start_date = fc.start_date
        AND duplicate.id < fc.id
        """,
        (vault_id,)
    )


def get_or_create_cycle_with_cursor(cursor, vault_id, target_date=None):
    target_date = parse_date(target_date or date.today())
    start_day, vault_created_at = get_vault_cycle_settings_with_cursor(
        cursor,
        vault_id
    )
    start, end = cycle_bounds_for(
        target_date,
        start_day,
        vault_created_at
    )
    repair_financial_cycles_with_cursor(
        cursor,
        vault_id,
        vault_created_at
    )
    existing = cursor.execute(
        """
        SELECT id, vault_id, start_date, end_date, created_at, closed_at
        FROM financial_cycles
        WHERE vault_id = ?
        AND start_date = ?
        """,
        (
            vault_id,
            start.isoformat()
        )
    ).fetchone()
    if existing:
        if parse_date(existing[3]) != end:
            cursor.execute(
                """
                UPDATE financial_cycles
                SET end_date = ?
                WHERE id = ?
                """,
                (
                    end.isoformat(),
                    existing[0]
                )
            )
            existing = cursor.execute(
                """
                SELECT id, vault_id, start_date, end_date, created_at, closed_at
                FROM financial_cycles
                WHERE id = ?
                """,
                (existing[0],)
            ).fetchone()
        return row_to_context(existing)

    cursor.execute(
        """
        INSERT INTO financial_cycles (
            vault_id,
            start_date,
            end_date,
            created_at
        )
        VALUES (?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT (vault_id, start_date) DO NOTHING
        """,
        (
            vault_id,
            start.isoformat(),
            end.isoformat(),
        )
        ,
        capture_lastrowid=False
    )
    row = cursor.execute(
        """
        SELECT id, vault_id, start_date, end_date, created_at, closed_at
        FROM financial_cycles
        WHERE vault_id = ?
        AND start_date = ?
        """,
        (
            vault_id,
            start.isoformat()
        )
    ).fetchone()
    context = row_to_context(row)
    freeze_cycle_contributions_with_cursor(
        cursor,
        context.id,
        vault_id
    )
    return context


def get_cycle_context_with_cursor(cursor, vault_id, target_date=None):
    target_date = parse_date(target_date or date.today())
    start_day, vault_created_at = get_vault_cycle_settings_with_cursor(
        cursor,
        vault_id
    )
    start, end = cycle_bounds_for(
        target_date,
        start_day,
        vault_created_at
    )
    existing = cursor.execute(
        """
        SELECT id, vault_id, start_date, end_date, created_at, closed_at
        FROM financial_cycles
        WHERE vault_id = ?
        AND start_date = ?
        """,
        (
            vault_id,
            start.isoformat()
        )
    ).fetchone()

    if existing:
        return CycleContext(
            id=existing[0],
            vault_id=existing[1],
            start_date=start,
            end_date=end,
            status=derive_cycle_status(start, end),
            closed_at=existing[5] if len(existing) > 5 else None
        )

    return build_cycle_context(
        vault_id,
        start,
        end
    )


def initialize_financial_cycles():
    conn = get_connection()
    try:
        cursor = conn.cursor()
        vaults = cursor.execute(
            """
            SELECT id, COALESCE(created_at::date, CURRENT_DATE)
            FROM vaults
            """
        ).fetchall()

        for vault_id, vault_created_at in vaults:
            repair_financial_cycles_with_cursor(
                cursor,
                vault_id,
                parse_date(vault_created_at)
            )
            get_or_create_cycle_with_cursor(
                cursor,
                vault_id,
                date.today()
            )

        conn.commit()
    finally:
        conn.close()


@cache_data(ttl=60)
def get_current_cycle(vault_id):
    return get_cycle_for_date(
        vault_id,
        date.today().isoformat()
    )


@cache_data(ttl=60)
def get_cycle_for_date(vault_id, target_iso):
    target_date = parse_date(target_iso)
    conn = get_connection()
    try:
        cursor = conn.cursor()
        return get_cycle_context_with_cursor(
            cursor,
            vault_id,
            target_date
        )
    finally:
        conn.close()


@cache_data(ttl=60)
def get_active_cycle(vault_id):
    return get_current_cycle(vault_id)


def build_cycle_context(vault_id, start, end):
    return CycleContext(
        id=0,
        vault_id=vault_id,
        start_date=start,
        end_date=end,
        status=derive_cycle_status(start, end)
    )


@cache_data(ttl=60)
def list_cycles(vault_id, limit=60):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        start_day, vault_created_at = get_vault_cycle_settings_with_cursor(
            cursor,
            vault_id
        )
        current = get_cycle_context_with_cursor(
            cursor,
            vault_id,
            date.today()
        )
        first_start = first_cycle_start_for(
            vault_created_at,
            start_day
        )
        cycle_starts = []
        cursor_start = first_start
        while cursor_start <= add_months(current.start_date, 12):
            cycle_starts.append(cursor_start)
            next_scheduled_start = date(
                add_months(
                    scheduled_cycle_start_for(cursor_start, start_day),
                    1
                ).year,
                add_months(
                    scheduled_cycle_start_for(cursor_start, start_day),
                    1
                ).month,
                start_day
            )
            cursor_start = next_scheduled_start

        rows = cursor.execute(
            """
            SELECT id, vault_id, start_date, end_date, created_at, closed_at
            FROM financial_cycles
            WHERE vault_id = ?
            ORDER BY start_date::date
            """,
            (vault_id,)
        ).fetchall()
        by_start = {
            parse_date(row[2]): row_to_context(row)
            for row in rows
        }
        contexts = []
        for cycle_start in cycle_starts[-limit:]:
            scheduled_start = scheduled_cycle_start_for(
                cycle_start,
                start_day
            )
            cycle_end = add_months(scheduled_start, 1) - timedelta(days=1)
            if cycle_start == first_start:
                cycle_end = max(cycle_end, cycle_start)
            contexts.append(
                by_start.get(
                    cycle_start,
                    build_cycle_context(vault_id, cycle_start, cycle_end)
                )
            )
        return contexts
    finally:
        conn.close()


def build_cycle_navigation_options(vault_id, limit=72):
    cycles = list_cycles(
        vault_id,
        limit=limit
    )
    options = []
    for cycle in cycles:
        icon = {
            CURRENT: "🟢",
            COMPLETED: "✅",
            UPCOMING: "🟣"
        }.get(cycle.status, "•")
        options.append({
            "key": cycle.start_iso,
            "cycle": cycle,
            "label": (
                f"{cycle.start_date.year} · "
                f"{icon} {cycle.status} · "
                f"{format_cycle_range(cycle.start_date, cycle.end_date)}"
            )
        })
    return options


def close_active_cycle(vault_id):
    conn = get_connection()
    try:
        cursor = conn.cursor()
        active = get_or_create_cycle_with_cursor(
            cursor,
            vault_id,
            date.today()
        )
        cursor.execute(
            """
            UPDATE financial_cycles
            SET closed_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (active.id,)
        )
        conn.commit()
        clear_data_cache((
            "cycles",
            "planning",
            "dashboard",
            "reports",
            "shared_bills"
        ))
        return get_cycle_context_with_cursor(
            cursor,
            vault_id,
            date.today()
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

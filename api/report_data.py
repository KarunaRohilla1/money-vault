from db.cache import cache_data
from db.core import EXPENSE, INCOME, TRANSFER_OUT, get_connection
from db.financial_cycles import add_months, get_cycle_for_date, format_cycle_range
from db.shared_expenses import (
    get_actual_category_spending,
    get_personal_spend_summary,
    get_settlement_summary,
    get_shared_vault_summary,
)
from db.vaults import get_vault_by_id

def is_shared_vault(vault_id):
    vault = get_vault_by_id(vault_id)
    return bool(vault and len(vault) > 4 and vault[4] == "Shared")

def build_cycle_windows(vault_id, start_date, end_date):
    cycle = get_cycle_for_date(
        vault_id,
        start_date.isoformat()
    )
    windows = []

    while cycle.start_date <= end_date:
        windows.append((
            cycle.start_iso,
            cycle.end_iso,
            cycle.start_month,
            cycle.start_year
        ))
        cycle = get_cycle_for_date(
            vault_id,
            add_months(cycle.start_date, 1).isoformat()
        )

    return tuple(windows)


def report_period_context(vault_id, selected_cycle):
    return {
        "selected_cycle": selected_cycle,
        "start_date": selected_cycle.start_date,
        "end_date": selected_cycle.end_date,
        "cycle_windows": build_cycle_windows(
            vault_id,
            selected_cycle.start_date,
            selected_cycle.end_date
        )
    }


def cycle_status_filter(alias, cycle_windows):
    if not cycle_windows:
        return "1 = 0", ()

    conditions = []
    params = []
    for _start_iso, _end_iso, month, year in cycle_windows:
        conditions.append(f"({alias}.month = ? AND {alias}.year = ?)")
        params.extend([month, year])

    return " OR ".join(conditions), tuple(params)


@cache_data(ttl=60)
def get_actual_income_total(vault_id, start_date, end_date, cycle_windows):
    status_filter, status_params = cycle_status_filter("s", cycle_windows)
    conn = get_connection()
    try:
        row = conn.execute(
            f"""
            WITH manual_income AS (
                SELECT COALESCE(SUM(t.amount), 0) AS amount
                FROM transactions t
                WHERE t.vault_id = ?
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                AND NOT EXISTS (
                    SELECT 1
                    FROM income_status s
                    WHERE s.transaction_id = t.id
                )
            ),
            received_recurring_income AS (
                SELECT COALESCE(
                    SUM(COALESCE(s.actual_amount, i.amount)),
                    0
                ) AS amount
                FROM income_status s
                JOIN income_templates i
                    ON i.id = s.income_template_id
                WHERE i.vault_id = ?
                AND s.status = 'RECEIVED'
                AND ({status_filter})
            )
            SELECT manual_income.amount + received_recurring_income.amount
            FROM manual_income
            CROSS JOIN received_recurring_income
            """,
            (
                vault_id,
                INCOME,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                *status_params
            )
        ).fetchone()
        return float(row[0] or 0)
    finally:
        conn.close()


@cache_data(ttl=60)
def get_unlinked_paid_commitments_total(vault_id, cycle_windows):
    status_filter, status_params = cycle_status_filter("s", cycle_windows)
    conn = get_connection()
    try:
        row = conn.execute(
            f"""
            SELECT COALESCE(SUM(COALESCE(s.actual_amount, c.amount)), 0)
            FROM obligation_status s
            JOIN commitments c
                ON c.id = s.commitment_id
            LEFT JOIN transactions t
                ON t.id = s.transaction_id
                AND t.is_deleted = 0
            WHERE c.vault_id = ?
            AND s.status = 'PAID'
            AND t.id IS NULL
            AND ({status_filter})
            """,
            (
                vault_id,
                *status_params
            )
        ).fetchone()
        return float(row[0] or 0)
    finally:
        conn.close()


@cache_data(ttl=60)
def get_investment_total(vault_id, start_date, end_date):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(t.amount), 0)
            FROM transactions t
            LEFT JOIN categories c
                ON c.id = t.category_id
            WHERE t.vault_id = ?
            AND t.is_deleted = 0
            AND t.transaction_type = ?
            AND t.date::date BETWEEN ?::date AND ?::date
            AND (
                LOWER(COALESCE(c.name, '')) IN ('investment', 'savings')
                OR LOWER(COALESCE(c.parent_category, '')) = 'financial'
            )
            """,
            (
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat()
            )
        ).fetchone()
        return float(row[0] or 0)
    finally:
        conn.close()


@cache_data(ttl=60)
def get_shared_expenses_received_total(vault_id, start_date, end_date):
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(ts.share_amount), 0)
            FROM transaction_shares ts
            JOIN transactions t
                ON t.id = ts.transaction_id
            WHERE ts.participant_vault_id = ?
            AND t.vault_id != ?
            AND COALESCE(t.beneficiary_vault_id, t.vault_id) != t.vault_id
            AND t.is_deleted = 0
            AND t.transaction_type = ?
            AND t.date::date BETWEEN ?::date AND ?::date
            """,
            (
                vault_id,
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat()
            )
        ).fetchone()
        return float(row[0] or 0)
    finally:
        conn.close()


def get_personal_report_money(vault_id, start_date, end_date, cycle_windows):
    income = get_actual_income_total(
        vault_id,
        start_date,
        end_date,
        cycle_windows
    )
    spend_summary = get_personal_spend_summary(
        vault_id,
        start_date.isoformat(),
        end_date.isoformat()
    )
    unlinked_commitments = get_unlinked_paid_commitments_total(
        vault_id,
        cycle_windows
    )
    cash_outflow = (
        spend_summary["personal_spending"]
        + spend_summary["shared_paid"]
        + unlinked_commitments
    )
    net_personal_cost = (
        spend_summary["personal_spending"]
        + spend_summary["own_shared_share"]
        + unlinked_commitments
    )
    settlement_summary = get_settlement_summary(
        vault_id,
        start_date.isoformat(),
        end_date.isoformat()
    )

    return {
        "income": income,
        "cash_outflow": cash_outflow,
        "net_personal_cost": net_personal_cost,
        "spent": net_personal_cost,
        "saved": max(income - net_personal_cost, 0),
        "investments": get_investment_total(
            vault_id,
            start_date,
            end_date
        ),
        "settlements": settlement_summary["net"],
        "outstanding_receivables": settlement_summary["receivable"],
        "outstanding_payables": settlement_summary["payable"],
        "net_outstanding": settlement_summary["net"],
        "settlements_completed": (
            spend_summary.get("settlement_received", 0)
            + spend_summary.get("settlement_paid", 0)
        ),
        "settlements_pending": settlement_summary["amount"],
        "shared_expenses_paid": spend_summary["shared_paid"],
        "shared_expenses_received": get_shared_expenses_received_total(
            vault_id,
            start_date,
            end_date
        ),
        "net_cash_flow": income - cash_outflow
    }


@cache_data(ttl=60)
def get_report_summary(vault_id, start_date, end_date, cycle_windows):
    if is_shared_vault(vault_id):
        shared_summary = get_shared_vault_summary(
            vault_id,
            start_date.isoformat(),
            end_date.isoformat()
        )
        conn = get_connection()
        try:
            summary_row = conn.execute(
                """
                WITH shared_expenses AS (
                    SELECT
                        t.id,
                        t.amount,
                        t.date::date AS date,
                        COALESCE(NULLIF(t.notes, ''), c.name, 'Expense') AS name,
                        COALESCE(c.emoji || ' ' || c.name, 'Uncategorized') AS category_name,
                        c.id AS category_id,
                        t.vault_id AS payer_vault_id
                    FROM transactions t
                    LEFT JOIN categories c
                        ON t.category_id = c.id
                    WHERE t.beneficiary_vault_id = ?
                    AND t.is_deleted = 0
                    AND t.transaction_type = ?
                    AND t.date::date BETWEEN ?::date AND ?::date
                ),
                largest_expense AS (
                    SELECT name, amount, date
                    FROM shared_expenses
                    ORDER BY amount DESC
                    LIMIT 1
                ),
                most_used_category AS (
                    SELECT category_name, COUNT(*) AS count
                    FROM shared_expenses
                    GROUP BY category_id, category_name
                    ORDER BY COUNT(*) DESC, COALESCE(SUM(amount), 0) DESC
                    LIMIT 1
                ),
                most_used_account AS (
                    SELECT v.name, COUNT(*) AS count
                    FROM shared_expenses se
                    JOIN vaults v
                        ON v.id = se.payer_vault_id
                    GROUP BY v.id, v.name
                    ORDER BY COUNT(*) DESC
                    LIMIT 1
                )
                SELECT
                    (SELECT COUNT(*) FROM shared_expenses),
                    largest_expense.name,
                    largest_expense.amount,
                    largest_expense.date,
                    most_used_category.category_name,
                    most_used_category.count,
                    most_used_account.name,
                    most_used_account.count
                FROM largest_expense
                FULL JOIN most_used_category
                    ON TRUE
                FULL JOIN most_used_account
                    ON TRUE
                """,
                (
                    vault_id,
                    EXPENSE,
                    start_date.isoformat(),
                    end_date.isoformat()
                )
            ).fetchone()
        finally:
            conn.close()

        spent = shared_summary["total_shared_spending"]
        return {
            "income": 0,
            "cash_outflow": spent,
            "net_personal_cost": 0,
            "household_spending": spent,
            "spent": spent,
            "saved": 0,
            "investments": 0,
            "settlements": shared_summary["outstanding_settlement"],
            "outstanding_receivables": 0,
            "outstanding_payables": 0,
            "net_outstanding": 0,
            "settlements_completed": 0,
            "settlements_pending": shared_summary["outstanding_settlement"],
            "shared_expenses_paid": spent,
            "shared_expenses_received": 0,
            "net_cash_flow": -spent,
            "transactions": summary_row[0] if summary_row else 0,
            "transfers": 0,
            "largest_expense": (
                (summary_row[1], summary_row[2], summary_row[3])
                if summary_row and summary_row[1] is not None
                else None
            ),
            "most_used_category": (
                (summary_row[4], summary_row[5])
                if summary_row and summary_row[4] is not None
                else None
            ),
            "most_used_account": (
                (summary_row[6], summary_row[7])
                if summary_row and summary_row[6] is not None
                else None
            )
        }

    conn = get_connection()
    try:
        summary_row = conn.execute(
            """
            WITH transaction_count AS (
                SELECT COUNT(*) AS count
                FROM transactions
                WHERE vault_id = ?
                AND is_deleted = 0
                AND date::date BETWEEN ?::date AND ?::date
            ),
            transfers AS (
                SELECT COUNT(DISTINCT transfer_group_id) AS count
                FROM transactions
                WHERE vault_id = ?
                AND is_deleted = 0
                AND transfer_group_id IS NOT NULL
                AND transaction_type = ?
                AND date::date BETWEEN ?::date AND ?::date
            ),
            largest_expense AS (
                SELECT
                    COALESCE(NULLIF(t.notes, ''), c.name, 'Expense') AS name,
                    t.amount,
                    t.date::date AS date
                FROM transactions t
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE t.vault_id = ?
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                ORDER BY t.amount DESC
                LIMIT 1
            ),
            most_used_category AS (
                SELECT
                    COALESCE(c.emoji || ' ' || c.name, 'Uncategorized') AS name,
                    COUNT(*) AS count
                FROM transactions t
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE t.vault_id = ?
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                GROUP BY c.id, c.name, c.emoji
                ORDER BY COUNT(*) DESC, COALESCE(SUM(t.amount), 0) DESC
                LIMIT 1
            ),
            most_used_account AS (
                SELECT
                    a.name,
                    COUNT(*) AS count
                FROM transactions t
                JOIN accounts a
                    ON t.account_id = a.id
                WHERE t.vault_id = ?
                AND t.is_deleted = 0
                AND t.transaction_type IN (?, ?)
                AND t.date::date BETWEEN ?::date AND ?::date
                GROUP BY a.id, a.name
                ORDER BY COUNT(*) DESC
                LIMIT 1
            )
            SELECT
                transaction_count.count,
                transfers.count,
                largest_expense.name,
                largest_expense.amount,
                largest_expense.date,
                most_used_category.name,
                most_used_category.count,
                most_used_account.name,
                most_used_account.count
            FROM transaction_count
            CROSS JOIN transfers
            LEFT JOIN largest_expense
                ON TRUE
            LEFT JOIN most_used_category
                ON TRUE
            LEFT JOIN most_used_account
                ON TRUE
            """,
            (
                vault_id,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                TRANSFER_OUT,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                INCOME,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat()
            )
        ).fetchone()
    finally:
        conn.close()

    money = get_personal_report_money(
        vault_id,
        start_date,
        end_date,
        cycle_windows
    )

    return {
        **money,
        "transactions": summary_row[0] if summary_row else 0,
        "transfers": summary_row[1] if summary_row else 0,
        "largest_expense": (
            (summary_row[2], summary_row[3], summary_row[4])
            if summary_row and summary_row[2] is not None
            else None
        ),
        "most_used_category": (
            (summary_row[5], summary_row[6])
            if summary_row and summary_row[5] is not None
            else None
        ),
        "most_used_account": (
            (summary_row[7], summary_row[8])
            if summary_row and summary_row[7] is not None
            else None
        )
    }


@cache_data(ttl=60)
def get_category_breakdown(vault_id, start_date, end_date):
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

        if vault and vault[0] == "Shared":
            return conn.execute(
                """
                SELECT
                    COALESCE(MIN(c.emoji), 'label'),
                    COALESCE(c.parent_category, c.name, 'Uncategorized'),
                    COALESCE(SUM(t.amount), 0)
                FROM transactions t
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE t.beneficiary_vault_id = ?
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                GROUP BY COALESCE(c.parent_category, c.name, 'Uncategorized')
                ORDER BY SUM(t.amount) DESC
                """,
                (
                    vault_id,
                    EXPENSE,
                    start_date.isoformat(),
                    end_date.isoformat()
                )
            ).fetchall()
    finally:
        conn.close()

    return get_actual_category_spending(
        vault_id,
        start_date.isoformat(),
        end_date.isoformat()
    )


@cache_data(ttl=60)
def get_cash_outflow_category_breakdown(vault_id, start_date, end_date):
    if is_shared_vault(vault_id):
        return get_category_breakdown(
            vault_id,
            start_date,
            end_date
        )

    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT
                COALESCE(c.emoji, 'label') AS icon,
                COALESCE(c.name, 'Uncategorized') AS name,
                COALESCE(SUM(t.amount), 0) AS amount
            FROM transactions t
            LEFT JOIN categories c
                ON t.category_id = c.id
            WHERE t.vault_id = ?
            AND t.is_deleted = 0
            AND t.transaction_type = ?
            AND t.date::date BETWEEN ?::date AND ?::date
            AND COALESCE(t.notes, '') NOT LIKE 'Shared settlement:%'
            GROUP BY c.id, c.name, c.emoji
            HAVING COALESCE(SUM(t.amount), 0) > 0
            ORDER BY SUM(t.amount) DESC
            """,
            (
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat()
            )
        ).fetchall()
    finally:
        conn.close()


@cache_data(ttl=60)
def get_net_personal_category_breakdown(vault_id, start_date, end_date):
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            WITH personal_categories AS (
                SELECT
                    COALESCE(c.emoji, 'label') AS icon,
                    COALESCE(c.name, 'Uncategorized') AS name,
                    COALESCE(SUM(t.amount), 0) AS amount
                FROM transactions t
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE t.vault_id = ?
                AND COALESCE(t.beneficiary_vault_id, t.vault_id) = t.vault_id
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                GROUP BY c.id, c.name, c.emoji
            ),
            shared_categories AS (
                SELECT
                    COALESCE(c.emoji, 'label') AS icon,
                    COALESCE(c.name, 'Uncategorized') AS name,
                    COALESCE(SUM(ts.share_amount), 0) AS amount
                FROM transaction_shares ts
                JOIN transactions t
                    ON t.id = ts.transaction_id
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE ts.participant_vault_id = ?
                AND COALESCE(t.beneficiary_vault_id, t.vault_id) != t.vault_id
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date::date BETWEEN ?::date AND ?::date
                GROUP BY c.id, c.name, c.emoji
            )
            SELECT icon, name, SUM(amount) AS amount
            FROM (
                SELECT * FROM personal_categories
                UNION ALL
                SELECT * FROM shared_categories
            ) rows
            GROUP BY icon, name
            HAVING SUM(amount) > 0
            ORDER BY SUM(amount) DESC
            """,
            (
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat(),
                vault_id,
                EXPENSE,
                start_date.isoformat(),
                end_date.isoformat()
            )
        ).fetchall()

        return rows
    finally:
        conn.close()


@cache_data(ttl=60)
def get_monthly_trend(vault_id, end_date):
    data = []
    anchor_cycle = get_cycle_for_date(
        vault_id,
        end_date.isoformat()
    )
    shared = is_shared_vault(vault_id)

    for offset in range(5, -1, -1):
        cycle_start = add_months(
            anchor_cycle.start_date,
            -offset
        )
        cycle = get_cycle_for_date(
            vault_id,
            cycle_start.isoformat()
        )
        if shared:
            shared_summary = get_shared_vault_summary(
                vault_id,
                cycle.start_iso,
                cycle.end_iso
            )
            income = 0
            cash_outflow = shared_summary["total_shared_spending"]
            net_personal_cost = 0
            household_spending = shared_summary["total_shared_spending"]
            savings = 0
        else:
            money = get_personal_report_money(
                vault_id,
                cycle.start_date,
                cycle.end_date,
                (
                    (
                        cycle.start_iso,
                        cycle.end_iso,
                        cycle.start_month,
                        cycle.start_year
                    ),
                )
            )
            income = money["income"]
            cash_outflow = money["cash_outflow"]
            net_personal_cost = money["net_personal_cost"]
            household_spending = 0
            savings = money["saved"]
        data.append({
            "Cycle": format_cycle_range(
                cycle.start_date,
                cycle.end_date
            ),
            "Cash Outflow": cash_outflow,
            "Net Personal Cost": net_personal_cost,
            "Household Spending": household_spending,
            "Income": income,
            "Savings": savings
        })

    return data


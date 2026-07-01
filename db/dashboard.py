from datetime import datetime

from db.accounts import (
    get_accounts,
    get_account_balances,
    get_primary_account,
    get_total_credit_card_due
)
from db.cache import cache_data
from db.core import get_connection
from db.planning import (
    get_commitments,
    get_income_templates,
    get_monthly_planning_totals
)


@cache_data(ttl=60)
def get_account_count(vault_id):

    conn = get_connection()

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM accounts
        WHERE vault_id = ?
        AND is_active = 1
        """,
        (vault_id,)
    ).fetchone()[0]

    conn.close()

    return count


@cache_data(ttl=60)
def get_dashboard_cycle(vault_id):

    conn = get_connection()

    row = conn.execute(
        """
        SELECT month, year
        FROM monthly_cycles
        WHERE vault_id = ?
        AND status = 'ACTIVE'
        ORDER BY year DESC, month DESC
        LIMIT 1
        """,
        (vault_id,)
    ).fetchone()

    conn.close()

    if row:
        return row[0], row[1]

    today = datetime.now()
    return today.month, today.year


def get_cycle_filter(vault_id):

    month, year = get_dashboard_cycle(vault_id)

    return f"{year:04d}-{month:02d}"


@cache_data(ttl=60)
def get_transaction_count_this_month(vault_id):

    conn = get_connection()
    cycle_filter = get_cycle_filter(vault_id)

    count = conn.execute(
        """
        SELECT COUNT(*)
        FROM transactions

        WHERE vault_id = ?
        AND is_deleted = 0

        AND to_char(date::date, 'YYYY-MM')
            = ?
        """,
        (
            vault_id,
            cycle_filter
        )
    ).fetchone()[0]

    conn.close()

    return count


@cache_data(ttl=60)
def get_income_this_month(vault_id):

    conn = get_connection()
    cycle_filter = get_cycle_filter(vault_id)

    total = conn.execute(
        """
        SELECT
            COALESCE(SUM(amount), 0)

        FROM transactions

        WHERE vault_id = ?
        AND is_deleted = 0
        AND transaction_type = 'Income'

        AND to_char(date::date, 'YYYY-MM')
            = ?
        """,
        (
            vault_id,
            cycle_filter
        )
    ).fetchone()[0]

    conn.close()

    return total


@cache_data(ttl=60)
def get_expense_this_month(vault_id):

    conn = get_connection()
    cycle_filter = get_cycle_filter(vault_id)

    total = conn.execute(
        """
        SELECT
            COALESCE(SUM(amount), 0)

        FROM transactions

        WHERE vault_id = ?
        AND is_deleted = 0
        AND transaction_type = 'Expense'

        AND to_char(date::date, 'YYYY-MM')
            = ?
        """,
        (
            vault_id,
            cycle_filter
        )
    ).fetchone()[0]

    conn.close()

    return total


@cache_data(ttl=60)
def get_remaining_commitments(vault_id):

    month, year = get_dashboard_cycle(vault_id)
    totals = get_monthly_planning_totals(
        vault_id,
        month,
        year
    )

    return totals["remaining_commitments"]


@cache_data(ttl=60)
def get_onboarding_status(vault_id):

    accounts = len(
        get_accounts(vault_id)
    )

    income_templates = len(
        get_income_templates(vault_id)
    )

    commitments = len(
        get_commitments(vault_id)
    )

    return {

        "accounts": accounts,

        "income_templates": income_templates,

        "commitments": commitments,

        "has_accounts": accounts > 0,

        "has_income_templates":
            income_templates > 0,

        "has_commitments":
            commitments > 0,

        "is_complete": (

            accounts > 0

            and

            income_templates > 0

            and

            commitments > 0

        )

    }


def is_setup_complete(vault_id):

    return get_onboarding_status(
        vault_id
    )["is_complete"]


def get_received_income_this_month(vault_id):

    return get_income_this_month(
        vault_id
    )


@cache_data(ttl=60)
def get_available_cash(vault_id):

    accounts = get_accounts(vault_id)
    balances = get_account_balances(vault_id)

    total = 0

    for account in accounts:

        account_type = account[2]

        if account_type == "Salary Account":

            total += balances.get(
                account[0],
                0
            )

    return total


@cache_data(ttl=60)
def get_dashboard_summary(vault_id):

    conn = get_connection()

    row = conn.execute(
        """
        WITH cycle AS (
            SELECT
                COALESCE(
                    (
                        SELECT month
                        FROM monthly_cycles
                        WHERE vault_id = ?
                        AND status = 'ACTIVE'
                        ORDER BY year DESC, month DESC
                        LIMIT 1
                    ),
                    EXTRACT(MONTH FROM CURRENT_DATE)::int
                ) AS month,
                COALESCE(
                    (
                        SELECT year
                        FROM monthly_cycles
                        WHERE vault_id = ?
                        AND status = 'ACTIVE'
                        ORDER BY year DESC, month DESC
                        LIMIT 1
                    ),
                    EXTRACT(YEAR FROM CURRENT_DATE)::int
                ) AS year
        ),
        account_balances AS (
            SELECT
                a.id,
                a.name,
                a.type,
                a.is_primary,
                a.opening_balance
                    + COALESCE(SUM(
                        CASE
                            WHEN t.transaction_type IN ('Income', 'Transfer In') THEN t.amount
                            WHEN t.transaction_type IN ('Expense', 'Transfer Out') THEN -t.amount
                            ELSE 0
                        END
                    ), 0) AS balance
            FROM accounts a
            LEFT JOIN transactions t
                ON t.account_id = a.id
                AND t.is_deleted = 0
            WHERE a.vault_id = ?
            AND a.is_active = 1
            GROUP BY a.id, a.name, a.type, a.is_primary, a.opening_balance
        ),
        primary_account AS (
            SELECT id, name, balance
            FROM account_balances
            ORDER BY is_primary DESC, type, name
            LIMIT 1
        ),
        transaction_totals AS (
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN transaction_type = 'Income' THEN amount
                        ELSE 0
                    END
                ), 0) AS income,
                COALESCE(SUM(
                    CASE
                        WHEN transaction_type = 'Expense' THEN amount
                        ELSE 0
                    END
                ), 0) AS expenses
            FROM transactions t
            CROSS JOIN cycle c
            WHERE t.vault_id = ?
            AND t.is_deleted = 0
            AND to_char(t.date::date, 'YYYY-MM')
                = CONCAT(c.year::text, '-', LPAD(c.month::text, 2, '0'))
        ),
        commitment_totals AS (
            SELECT COALESCE(SUM(
                CASE
                    WHEN COALESCE(s.status, 'PENDING') = 'PENDING'
                        THEN COALESCE(s.actual_amount, cm.amount)
                    ELSE 0
                END
            ), 0) AS remaining
            FROM commitments cm
            CROSS JOIN cycle c
            LEFT JOIN obligation_status s
                ON s.commitment_id = cm.id
                AND s.month = c.month
                AND s.year = c.year
            WHERE cm.vault_id = ?
            AND cm.is_active = 1
        ),
        cash_totals AS (
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN type = 'Salary Account' THEN balance
                        ELSE 0
                    END
                ), 0) AS available_cash,
                COALESCE(SUM(
                    CASE
                        WHEN type = 'Credit Card' AND balance < 0 THEN ABS(balance)
                        ELSE 0
                    END
                ), 0) AS credit_card_due
            FROM account_balances
        )
        SELECT
            cycle.month,
            cycle.year,
            COALESCE(primary_account.name, 'Primary Account'),
            COALESCE(primary_account.balance, 0),
            transaction_totals.income,
            transaction_totals.expenses,
            commitment_totals.remaining,
            cash_totals.available_cash,
            cash_totals.credit_card_due
        FROM cycle
        CROSS JOIN transaction_totals
        CROSS JOIN commitment_totals
        CROSS JOIN cash_totals
        LEFT JOIN primary_account
            ON TRUE
        """,
        (
            vault_id,
            vault_id,
            vault_id,
            vault_id,
            vault_id
        )
    ).fetchone()

    conn.close()

    month = row[0]
    year = row[1]
    primary_account_name = row[2]
    primary_account_balance = row[3]
    income = row[4]
    expenses = row[5]
    remaining_commitments = row[6]
    available_cash = row[7]
    credit_card_due = row[8]

    safe_to_spend = max(
        available_cash
        - remaining_commitments
        - credit_card_due,
        0
    )

    return {
        "month": month,
        "year": year,
        "income": income,
        "primary_account_name": primary_account_name,
        "primary_account_balance": primary_account_balance,
        "available_cash": available_cash,
        "remaining_commitments": remaining_commitments,
        "expenses": expenses,
        "credit_card_due": credit_card_due,
        "safe_to_spend": safe_to_spend
    }


@cache_data(ttl=60)
def get_category_spending_this_month(vault_id):

    conn = get_connection()
    cycle_filter = get_cycle_filter(vault_id)

    data = conn.execute(
        """
        SELECT
            c.name,
            SUM(t.amount)
        FROM transactions t
        JOIN categories c
            ON t.category_id = c.id
        WHERE t.vault_id = ?
            AND t.transaction_type = 'Expense'
            AND to_char(t.date::date, 'YYYY-MM')
                = ?
        GROUP BY c.name
        ORDER BY SUM(t.amount) DESC
        """,
        (
            vault_id,
            cycle_filter
        )
    ).fetchall()

    conn.close()

    return data

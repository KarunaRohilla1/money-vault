from datetime import datetime

from db.accounts import (
    get_account_balance,
    get_accounts,
    get_primary_account,
    get_total_credit_card_due
)
from db.core import get_connection
from db.planning import (
    get_commitments,
    get_income_templates,
    get_monthly_planning_totals
)


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


def get_remaining_commitments(vault_id):

    month, year = get_dashboard_cycle(vault_id)
    totals = get_monthly_planning_totals(
        vault_id,
        month,
        year
    )

    return totals["remaining_commitments"]


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


def get_available_cash(vault_id):

    accounts = get_accounts(vault_id)

    total = 0

    for account in accounts:

        account_type = account[2]

        if account_type == "Salary Account":

            total += get_account_balance(
                account[0]
            )

    return total


def get_dashboard_summary(vault_id):

    month, year = get_dashboard_cycle(vault_id)
    primary_account = get_primary_account(vault_id)
    primary_account_balance = (
        get_account_balance(primary_account[0])
        if primary_account
        else 0
    )
    primary_account_name = (
        primary_account[1]
        if primary_account
        else "Primary Account"
    )
    income = get_received_income_this_month(vault_id)
    remaining_commitments = get_remaining_commitments(
        vault_id
    )
    expenses = get_expense_this_month(vault_id)
    credit_card_due = get_total_credit_card_due(
        vault_id
    )

    available_cash = get_available_cash(vault_id)

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

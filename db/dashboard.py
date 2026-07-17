from calendar import monthrange
from datetime import datetime

from db.accounts import (
    get_accounts,
    get_account_balances,
    get_primary_account,
    get_total_credit_card_due
)
from db.cache import cache_data
from db.core import get_connection
from db.financial_cycles import get_current_cycle
from db.planning import (
    get_commitments,
    get_income_templates,
    get_monthly_planning_totals
)
from db.shared_expenses import (
    get_actual_category_spending,
    get_personal_spend_summary,
    get_settlement_summary
)


def month_bounds_iso(year, month):
    last_day = monthrange(
        year,
        month
    )[1]

    return (
        f"{year:04d}-{month:02d}-01",
        f"{year:04d}-{month:02d}-{last_day:02d}"
    )


@cache_data(ttl=60)
def get_dashboard_page_data(vault_id):
    active_cycle = get_current_cycle(vault_id)

    conn = get_connection()
    try:

        row = conn.execute(
            """
            WITH cycle AS (
                SELECT
                    ?::date AS start_date,
                    ?::date AS end_date,
                    ?::int AS month,
                    ?::int AS year
            ),
            onboarding AS (
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM vaults
                        WHERE id = ?
                        AND COALESCE(pin_hash, '') != ''
                    ) AS vault_login,
                    (
                        SELECT COUNT(*)
                        FROM vaults
                        WHERE id = ?
                        AND COALESCE(financial_cycle_start_day, month_start_day, 0)
                            BETWEEN 1 AND 31
                    ) AS cycle_setting,
                    (
                        SELECT COUNT(*)
                        FROM vaults
                        WHERE id = ?
                        AND COALESCE(monthly_savings_goal, 0) > 0
                    ) AS savings_goal,
                    (
                        SELECT COUNT(*)
                        FROM accounts
                        WHERE vault_id = ?
                        AND is_active = 1
                    ) AS accounts,
                    (
                        SELECT COUNT(*)
                        FROM income_templates
                        WHERE vault_id = ?
                        AND is_active = 1
                    ) AS income_templates,
                    (
                        SELECT COUNT(*)
                        FROM commitments
                        WHERE vault_id = ?
                        AND is_active = 1
                    ) AS commitments
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
                AND t.date::date BETWEEN c.start_date AND c.end_date
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
                    ), 0) AS credit_card_due,
                    COALESCE(SUM(
                        CASE
                            WHEN balance > 0 THEN balance
                            ELSE 0
                        END
                    ), 0) AS total_assets,
                    COALESCE(SUM(
                        CASE
                            WHEN balance < 0 THEN ABS(balance)
                            ELSE 0
                        END
                    ), 0) AS total_liabilities
                FROM account_balances
            ),
            vault_settings AS (
                SELECT COALESCE(monthly_savings_goal, 0) AS monthly_savings_goal
                FROM vaults
                WHERE id = ?
            ),
            recent_activity AS (
                SELECT COALESCE(
                    json_agg(
                        json_build_array(
                            id,
                            transaction_date,
                            account_name,
                            category_name,
                            amount,
                            transaction_type,
                            notes,
                            transfer_group_id
                        )
                        ORDER BY transaction_date DESC, id DESC
                    ),
                    '[]'::json
                ) AS rows
                FROM (
                    SELECT
                        t.id,
                        t.date::text AS transaction_date,
                        a.name AS account_name,
                        COALESCE(c.emoji || ' ' || c.name, t.transaction_type) AS category_name,
                        t.amount,
                        t.transaction_type,
                        t.notes,
                        t.transfer_group_id
                    FROM transactions t
                    LEFT JOIN accounts a
                        ON t.account_id = a.id
                    LEFT JOIN categories c
                        ON t.category_id = c.id
                    WHERE t.vault_id = ?
                    AND t.is_deleted = 0
                    AND t.amount != 0
                    AND t.transaction_type NOT IN ('Transfer In', 'Transfer Out')
                    ORDER BY t.date DESC, t.id DESC
                    LIMIT 5
                ) data
            )
            SELECT
                onboarding.accounts,
                onboarding.income_templates,
                onboarding.commitments,
                onboarding.vault_login,
                onboarding.cycle_setting,
                onboarding.savings_goal,
                cycle.month,
                cycle.year,
                COALESCE(primary_account.name, 'Primary Account'),
                COALESCE(primary_account.balance, 0),
                transaction_totals.income,
                transaction_totals.expenses,
                commitment_totals.remaining,
                cash_totals.available_cash,
                cash_totals.credit_card_due,
                cash_totals.total_assets,
                cash_totals.total_liabilities,
                vault_settings.monthly_savings_goal,
                recent_activity.rows
            FROM onboarding
            CROSS JOIN cycle
            CROSS JOIN transaction_totals
            CROSS JOIN commitment_totals
            CROSS JOIN cash_totals
            CROSS JOIN vault_settings
            CROSS JOIN recent_activity
            LEFT JOIN primary_account
                ON TRUE
            """,
            (
                active_cycle.start_iso,
                active_cycle.end_iso,
                active_cycle.start_month,
                active_cycle.start_year,
                vault_id,
                vault_id,
                vault_id,
                vault_id,
                vault_id,
                vault_id,
                vault_id,
                vault_id,
                vault_id,
                vault_id,
                vault_id
            )
        ).fetchone()


        accounts = row[0]
        income_templates = row[1]
        commitments = row[2]
        remaining_commitments = row[12]
        available_cash = row[13]
        credit_card_due = row[14]
        total_assets = row[15]
        total_liabilities = row[16]
        monthly_savings_goal = row[17]
        start_date, end_date = active_cycle.start_iso, active_cycle.end_iso
        spend_summary = get_personal_spend_summary(
            vault_id,
            start_date,
            end_date
        )
        settlement_balance = spend_summary[
            "settlement_balance"
        ]
        settlement_summary = get_settlement_summary(
            vault_id,
            start_date,
            end_date
        )
        actual_income = row[10]
        safe_to_spend = max(
            available_cash
            - settlement_summary["payable"]
            - remaining_commitments
            - credit_card_due
            - monthly_savings_goal,
            0
        )
        actual_savings = max(
            actual_income - spend_summary["actual_spending"],
            0
        )
        category_spending = [
            (
                row[1],
                row[2]
            )
            for row in get_actual_category_spending(
                vault_id,
                start_date,
                end_date
            )
        ]

        return {
            "status": {
                "accounts": accounts,
                "income_templates": income_templates,
                "commitments": commitments,
                "has_vault_login": row[3] > 0,
                "has_cycle_setting": row[4] > 0,
                "has_savings_goal": row[5] > 0,
                "has_accounts": accounts > 0,
                "has_income_templates": income_templates > 0,
                "has_commitments": commitments > 0,
                "is_complete": (
                    accounts > 0
                    and row[3] > 0
                    and row[4] > 0
                    and row[5] > 0
                )
            },
            "summary": {
                "month": row[6],
                "year": row[7],
                "income": actual_income,
                "primary_account_name": row[8],
                "primary_account_balance": row[9],
                "available_cash": available_cash,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "net_worth": total_assets - total_liabilities,
                "monthly_savings_goal": monthly_savings_goal,
                "actual_savings": actual_savings,
                "remaining_commitments": remaining_commitments,
                "expenses": spend_summary["actual_spending"],
                "personal_expenses": spend_summary["personal_spending"],
                "shared_paid": spend_summary["shared_paid"],
                "shared_share": spend_summary["own_shared_share"],
                "settlement_balance": settlement_balance,
                "settlement_summary": settlement_summary,
                "credit_card_due": credit_card_due,
                "safe_to_spend": safe_to_spend
            },
            "category_spending": category_spending,
            "recent_activity": row[18] or []
        }


    finally:
        conn.close()
@cache_data(ttl=60)
def get_account_count(vault_id):

    conn = get_connection()
    try:

        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM accounts
            WHERE vault_id = ?
            AND is_active = 1
            """,
            (vault_id,)
        ).fetchone()[0]


        return count


    finally:
        conn.close()
@cache_data(ttl=60)
def get_dashboard_cycle(vault_id):
    cycle = get_current_cycle(vault_id)
    return cycle.start_month, cycle.start_year
def get_cycle_filter(vault_id):

    month, year = get_dashboard_cycle(vault_id)

    return f"{year:04d}-{month:02d}"


def get_cycle_bounds(vault_id):
    cycle = get_current_cycle(vault_id)
    return cycle.start_iso, cycle.end_iso


@cache_data(ttl=60)
def get_transaction_count_this_month(vault_id):

    conn = get_connection()
    try:
        start_date, end_date = get_cycle_bounds(vault_id)

        count = conn.execute(
            """
            SELECT COUNT(*)
            FROM transactions

            WHERE vault_id = ?
            AND is_deleted = 0

            AND date::date BETWEEN ? AND ?
            """,
            (
                vault_id,
                start_date,
                end_date
            )
        ).fetchone()[0]


        return count


    finally:
        conn.close()
@cache_data(ttl=60)
def get_income_this_month(vault_id):

    conn = get_connection()
    try:
        start_date, end_date = get_cycle_bounds(vault_id)

        total = conn.execute(
            """
            SELECT
                COALESCE(SUM(amount), 0)

            FROM transactions

            WHERE vault_id = ?
            AND is_deleted = 0
            AND transaction_type = 'Income'

            AND date::date BETWEEN ? AND ?
            """,
            (
                vault_id,
                start_date,
                end_date
            )
        ).fetchone()[0]


        return total


    finally:
        conn.close()
@cache_data(ttl=60)
def get_expense_this_month(vault_id):

    conn = get_connection()
    try:
        start_date, end_date = get_cycle_bounds(vault_id)

        total = conn.execute(
            """
            SELECT
                COALESCE(SUM(amount), 0)

            FROM transactions

            WHERE vault_id = ?
            AND is_deleted = 0
            AND transaction_type = 'Expense'

            AND date::date BETWEEN ? AND ?
            """,
            (
                vault_id,
                start_date,
                end_date
            )
        ).fetchone()[0]


        return total


    finally:
        conn.close()
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

    conn = get_connection()
    try:
        settings = conn.execute(
            """
            SELECT
                COALESCE(pin_hash, ''),
                COALESCE(financial_cycle_start_day, month_start_day, 0),
                COALESCE(monthly_savings_goal, 0)
            FROM vaults
            WHERE id = ?
            """,
            (vault_id,)
        ).fetchone()
    finally:
        conn.close()

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

        "has_vault_login": bool(settings and settings[0]),

        "has_cycle_setting": bool(
            settings and 1 <= int(settings[1] or 0) <= 31
        ),

        "has_savings_goal": bool(
            settings and float(settings[2] or 0) > 0
        ),

        "has_accounts": accounts > 0,

        "has_income_templates":
            income_templates > 0,

        "has_commitments":
            commitments > 0,

        "is_complete": (

            bool(settings and settings[0])

            and

            bool(settings and 1 <= int(settings[1] or 0) <= 31)

            and

            bool(settings and float(settings[2] or 0) > 0)

            and

            accounts > 0

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
    active_cycle = get_current_cycle(vault_id)

    conn = get_connection()
    try:

        row = conn.execute(
            """
            WITH cycle AS (
                SELECT
                    ?::date AS start_date,
                    ?::date AS end_date,
                    ?::int AS month,
                    ?::int AS year
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
                AND t.date::date BETWEEN c.start_date AND c.end_date
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
                active_cycle.start_iso,
                active_cycle.end_iso,
                active_cycle.start_month,
                active_cycle.start_year,
                vault_id,
                vault_id,
                vault_id
            )
        ).fetchone()


        month = row[0]
        year = row[1]
        primary_account_name = row[2]
        primary_account_balance = row[3]
        income = row[4]
        expenses = row[5]
        remaining_commitments = row[6]
        available_cash = row[7]
        credit_card_due = row[8]
        monthly_savings_goal = conn.execute(
            """
            SELECT COALESCE(monthly_savings_goal, 0)
            FROM vaults
            WHERE id = ?
            """,
            (vault_id,)
        ).fetchone()[0]
        start_date, end_date = active_cycle.start_iso, active_cycle.end_iso
        spend_summary = get_personal_spend_summary(
            vault_id,
            start_date,
            end_date
        )
        settlement_balance = spend_summary[
            "settlement_balance"
        ]
        settlement_summary = get_settlement_summary(
            vault_id,
            start_date,
            end_date
        )
        actual_income = income

        safe_to_spend = max(
            available_cash
            - settlement_summary["payable"]
            - remaining_commitments
            - credit_card_due
            - monthly_savings_goal,
            0
        )

        return {
            "month": month,
            "year": year,
            "income": actual_income,
            "primary_account_name": primary_account_name,
            "primary_account_balance": primary_account_balance,
            "available_cash": available_cash,
            "remaining_commitments": remaining_commitments,
            "expenses": spend_summary["actual_spending"],
            "personal_expenses": spend_summary["personal_spending"],
            "shared_paid": spend_summary["shared_paid"],
            "shared_share": spend_summary["own_shared_share"],
            "settlement_balance": settlement_balance,
            "settlement_summary": settlement_summary,
            "credit_card_due": credit_card_due,
            "monthly_savings_goal": monthly_savings_goal,
            "safe_to_spend": safe_to_spend
        }


    finally:
        conn.close()
@cache_data(ttl=60)
def get_category_spending_this_month(vault_id):

    conn = get_connection()
    try:
        start_date, end_date = get_cycle_bounds(vault_id)
        rows = get_actual_category_spending(
            vault_id,
            start_date,
            end_date
        )
        data = [
            (
                row[1],
                row[2]
            )
            for row in rows
        ]


        return data

    finally:
        conn.close()

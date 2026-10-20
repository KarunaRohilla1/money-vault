from db.accounts import get_accounts
from db.cache import cache_data
from db.core import (
    EXPENSE,
    INCOME,
    TRANSFER_IN,
    TRANSFER_OUT,
    get_connection
)
from db.financial_cycles import get_current_cycle
from db.planning import get_commitments, get_income_templates
from db.identity import (
    get_show_shared_balances_on_dashboard,
    list_connected_shared_vault_preferences,
)
from db.shared_expenses import (
    as_money,
    get_actual_category_spending,
    get_personal_spend_summary,
    get_settlement_summary,
)


def combine_included_settlements(summaries):
    if not summaries:
        return {
            "label": "No shared vaults included in Safe to Spend",
            "amount": 0,
            "direction": "settled",
            "receivable": 0,
            "payable": 0,
            "net": 0,
            "items": []
        }

    receivable = as_money(sum(summary["receivable"] for summary in summaries))
    payable = as_money(sum(summary["payable"] for summary in summaries))
    items = []
    for summary in summaries:
        items.extend(summary.get("items") or [])
    net = as_money(receivable - payable)

    if net > 0:
        label = "Owed to You:"
        amount = net
        direction = "receivable"
    elif net < 0:
        label = "You Owe:"
        amount = abs(net)
        direction = "payable"
    else:
        label = "All Settled"
        amount = 0
        direction = "settled"

    return {
        "label": label,
        "amount": amount,
        "direction": direction,
        "receivable": receivable,
        "payable": payable,
        "net": net,
        "items": items
    }


@cache_data(ttl=60)
def get_cycle_savings_summary(vault_id, start_date, end_date):
    """
    Calculate Net Savings This Cycle as money put into savings (transfers in + direct income)
    minus money taken out of savings (transfers out + direct expenses) during the cycle.
    Transfers from a primary account (or non-savings account) to a savings account count as savings.
    Transfers from a savings account back to primary (or non-savings account) count as withdrawals.
    External income deposited directly into savings counts toward savings.
    Expenses paid directly from savings reduce savings for the cycle.
    Transfers between own accounts are not double-counted as income or expenses.
    """
    start_iso = start_date.isoformat() if hasattr(start_date, "isoformat") else str(start_date)
    end_iso = end_date.isoformat() if hasattr(end_date, "isoformat") else str(end_date)
    conn = get_connection()
    try:
        transfer_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN LOWER(a_to.type) = 'savings account'
                             AND (a_from.is_primary = 1 OR LOWER(a_from.type) != 'savings account')
                             AND a_from.id != a_to.id
                        THEN t_out.amount
                        ELSE 0
                    END
                ), 0) AS savings_transfers_in,
                COALESCE(SUM(
                    CASE
                        WHEN LOWER(a_from.type) = 'savings account'
                             AND (a_to.is_primary = 1 OR LOWER(a_to.type) != 'savings account')
                             AND a_from.id != a_to.id
                        THEN t_out.amount
                        ELSE 0
                    END
                ), 0) AS savings_transfers_out
            FROM transactions t_out
            JOIN transactions t_in
                ON t_out.transfer_group_id = t_in.transfer_group_id
                AND t_in.transaction_type = ?
                AND t_in.is_deleted = 0
            JOIN accounts a_from
                ON t_out.account_id = a_from.id
            JOIN accounts a_to
                ON t_in.account_id = a_to.id
            WHERE t_out.vault_id = ?
            AND t_out.transaction_type = ?
            AND t_out.transfer_group_id IS NOT NULL
            AND t_out.is_deleted = 0
            AND t_out.date BETWEEN ? AND ?
            """,
            (
                TRANSFER_IN,
                vault_id,
                TRANSFER_OUT,
                start_iso,
                end_iso
            )
        ).fetchone()

        savings_transfers_in = as_money(transfer_row[0]) if transfer_row else 0.0
        savings_transfers_out = as_money(transfer_row[1]) if transfer_row else 0.0

        direct_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(
                    CASE
                        WHEN t.transaction_type = ? THEN t.amount
                        ELSE 0
                    END
                ), 0) AS savings_income,
                COALESCE(SUM(
                    CASE
                        WHEN t.transaction_type = ? THEN t.amount
                        ELSE 0
                    END
                ), 0) AS savings_expenses
            FROM transactions t
            JOIN accounts a
                ON t.account_id = a.id
            WHERE t.vault_id = ?
            AND t.is_deleted = 0
            AND LOWER(a.type) = 'savings account'
            AND t.transaction_type IN (?, ?)
            AND t.date BETWEEN ? AND ?
            """,
            (
                INCOME,
                EXPENSE,
                vault_id,
                INCOME,
                EXPENSE,
                start_iso,
                end_iso
            )
        ).fetchone()

        savings_income = as_money(direct_row[0]) if direct_row else 0.0
        savings_expenses = as_money(direct_row[1]) if direct_row else 0.0

        savings_in = as_money(savings_transfers_in + savings_income)
        savings_out = as_money(savings_transfers_out + savings_expenses)
        net_savings = as_money(savings_in - savings_out)

        return {
            "savings_in": savings_in,
            "savings_out": savings_out,
            "net_savings": net_savings,
            "savings_transfers_in": savings_transfers_in,
            "savings_transfers_out": savings_transfers_out,
            "savings_income": savings_income,
            "savings_expenses": savings_expenses
        }
    finally:
        conn.close()


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
                        FROM vault_members vm
                        JOIN profiles p ON p.id = vm.user_id
                        WHERE vm.vault_id = ?
                        AND vm.role = 'owner'
                        AND COALESCE(p.pin_hash, '') != ''
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
    finally:
        conn.close()

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
    shared_vault_prefs = list_connected_shared_vault_preferences(vault_id)
    shared_vault_balances = []
    included_summaries = []
    for shared_vault in shared_vault_prefs:
        settlement_cycle = get_current_cycle(shared_vault["id"])
        vault_summary = get_settlement_summary(
            vault_id,
            settlement_cycle.start_iso,
            settlement_cycle.end_iso,
            shared_vault_id=shared_vault["id"]
        )
        shared_vault_balances.append(
            {
                "id": shared_vault["id"],
                "name": shared_vault["name"],
                "amount": vault_summary["amount"],
                "direction": vault_summary["direction"],
                "label": vault_summary["label"],
                "payable": vault_summary["payable"],
                "receivable": vault_summary["receivable"],
                "show_on_dashboard": bool(shared_vault.get("show_on_dashboard", True))
            }
        )
        if shared_vault["include_in_safe_to_spend"]:
            included_summaries.append(vault_summary)

    settlement_summary = combine_included_settlements(included_summaries)
    settlement_balance = settlement_summary["net"]
    show_shared_balances_on_dashboard = get_show_shared_balances_on_dashboard(vault_id)
    actual_income = row[10]
    savings_summary = get_cycle_savings_summary(
        vault_id,
        start_date,
        end_date
    )
    net_savings_this_cycle = savings_summary["net_savings"]
    actual_savings = net_savings_this_cycle
    savings_goal_remaining = as_money(
        max(monthly_savings_goal - max(net_savings_this_cycle, 0), 0)
    )
    safe_to_spend = max(
        available_cash
        - settlement_summary["payable"]
        + settlement_summary["receivable"]
        - remaining_commitments
        - credit_card_due
        - savings_goal_remaining,
        0
    )
    category_spending = [
        (
            category_row[1],
            category_row[2]
        )
        for category_row in get_actual_category_spending(
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
            "savings_goal_remaining": savings_goal_remaining,
            "actual_savings": actual_savings,
            "net_savings_this_cycle": net_savings_this_cycle,
            "savings_transfers_in": savings_summary["savings_transfers_in"],
            "savings_transfers_out": savings_summary["savings_transfers_out"],
            "savings_income": savings_summary["savings_income"],
            "savings_expenses": savings_summary["savings_expenses"],
            "savings_in": savings_summary["savings_in"],
            "savings_out": savings_summary["savings_out"],
            "remaining_commitments": remaining_commitments,
            "expenses": spend_summary["actual_spending"],
            "personal_expenses": spend_summary["personal_spending"],
            "shared_paid": spend_summary["shared_paid"],
            "shared_share": spend_summary["own_shared_share"],
            "settlement_balance": settlement_balance,
            "settlement_summary": settlement_summary,
            "show_shared_balances_on_dashboard": show_shared_balances_on_dashboard,
            "shared_vault_balances": shared_vault_balances,
            "credit_card_due": credit_card_due,
            "safe_to_spend": safe_to_spend
        },
        "category_spending": category_spending,
        "recent_activity": row[18] or [],
        "cycle": active_cycle
    }


def get_dashboard_summary(vault_id):
    return get_dashboard_page_data(vault_id)["summary"]


@cache_data(ttl=60)
def get_onboarding_status(vault_id):
    conn = get_connection()
    try:
        settings = conn.execute(
            """
            SELECT
                COALESCE((
                    SELECT p.pin_hash
                    FROM vault_members vm
                    JOIN profiles p ON p.id = vm.user_id
                    WHERE vm.vault_id = v.id
                    AND vm.role = 'owner'
                    LIMIT 1
                ), ''),
                COALESCE(v.financial_cycle_start_day, v.month_start_day, 0),
                COALESCE(v.monthly_savings_goal, 0),
                (
                    SELECT COUNT(*)
                    FROM vault_members vm
                    WHERE vm.vault_id = v.id
                )
            FROM vaults v
            WHERE v.id = ?
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
        "has_income_templates": income_templates > 0,
        "has_commitments": commitments > 0,
        # Savings goal is optional in onboarding; do not require it for setup completion.
        "is_complete": (
            bool(settings)
            and bool(settings[3] and int(settings[3]) > 0)
            and bool(settings[0])
            and bool(1 <= int(settings[1] or 0) <= 31)
            and accounts > 0
        )
    }

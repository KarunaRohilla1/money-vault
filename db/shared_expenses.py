import uuid

from db.cache import cache_data, clear_data_cache
from db.core import EXPENSE, TRANSFER_IN, TRANSFER_OUT, get_connection
from db.transaction_shares import cents, money_from_cents


def as_money(value):
    return round(
        float(value or 0),
        2
    )


def get_current_participant_context(participants):
    current = participants[0] if participants else None
    others = participants[1:] if len(participants) > 1 else []
    return current, others


def get_shared_vaults_for_personal_with_cursor(cursor, vault_id):
    return cursor.execute(
        """
        SELECT
            shared.id,
            shared.name
        FROM vault_shares vs
        JOIN vaults shared
            ON vs.vault_id = shared.id
        WHERE vs.shared_vault_id = ?
        AND shared.vault_type = 'Shared'
        ORDER BY shared.name
        """,
        (vault_id,)
    ).fetchall()


def get_shared_participants_with_cursor(cursor, shared_vault_id):
    return cursor.execute(
        """
        SELECT
            participant.id,
            participant.name
        FROM vault_shares vs
        JOIN vaults participant
            ON vs.shared_vault_id = participant.id
        WHERE vs.vault_id = ?
        AND participant.vault_type = 'Individual'
        ORDER BY participant.name
        """,
        (shared_vault_id,)
    ).fetchall()


def split_label_for_shares(transaction_amount, shares):
    if not shares:
        return "Equal"

    percentages = [
        round(float(share.get("percentage") or 0))
        for share in shares
    ]

    if len(percentages) == 2 and percentages[0] == percentages[1]:
        return "50/50"

    if all(percent > 0 for percent in percentages):
        return "/".join(
            str(percent)
            for percent in percentages
        )

    if transaction_amount:
        return "/".join(
            str(
                round(
                    share["amount"] / transaction_amount * 100
                )
            )
            for share in shares
        )

    return "Equal"


def get_settlement_adjustments_with_cursor(
    cursor,
    participant_ids,
    shared_vault_id,
    start_date,
    end_date
):
    adjustments = {
        participant_id: 0
        for participant_id in participant_ids
    }

    rows = cursor.execute(
        """
        SELECT
            vault_id,
            transaction_type,
            amount
        FROM transactions
        WHERE beneficiary_vault_id = ?
        AND is_deleted = 0
        AND transaction_type IN (?, ?)
        AND COALESCE(notes, '') LIKE 'Shared settlement:%'
        AND date BETWEEN ? AND ?
        """,
        (
            shared_vault_id,
            TRANSFER_IN,
            TRANSFER_OUT,
            start_date,
            end_date
        )
    ).fetchall()

    for row in rows:
        participant_id = row[0]
        if participant_id not in adjustments:
            continue

        amount_cents = cents(row[2])

        if row[1] == TRANSFER_IN:
            adjustments[participant_id] -= amount_cents
        elif row[1] == TRANSFER_OUT:
            adjustments[participant_id] += amount_cents

    return adjustments


def get_shared_balances_with_cursor(
    cursor,
    shared_vault_id,
    start_date,
    end_date
):
    participants = get_shared_participants_with_cursor(
        cursor,
        shared_vault_id
    )
    participant_ids = [
        participant[0]
        for participant in participants
    ]
    participant_names = {
        participant[0]: participant[1]
        for participant in participants
    }
    paid_cents = {
        participant_id: 0
        for participant_id in participant_ids
    }
    share_cents = {
        participant_id: 0
        for participant_id in participant_ids
    }

    transaction_rows = cursor.execute(
        """
        SELECT
            id,
            vault_id,
            amount
        FROM transactions
        WHERE beneficiary_vault_id = ?
        AND is_deleted = 0
        AND transaction_type = ?
        AND date BETWEEN ? AND ?
        ORDER BY date DESC, id DESC
        """,
        (
            shared_vault_id,
            EXPENSE,
            start_date,
            end_date
        )
    ).fetchall()

    transaction_ids = [
        row[0]
        for row in transaction_rows
    ]
    shares_by_transaction = {}

    if transaction_ids:
        placeholders = ", ".join(
            ["?"] * len(transaction_ids)
        )
        share_rows = cursor.execute(
            f"""
            SELECT
                transaction_id,
                participant_vault_id,
                share_amount
            FROM transaction_shares
            WHERE transaction_id IN ({placeholders})
            """,
            tuple(transaction_ids)
        ).fetchall()

        for share_row in share_rows:
            shares_by_transaction.setdefault(
                share_row[0],
                []
            ).append(share_row)

    for transaction in transaction_rows:
        transaction_id = transaction[0]
        payer_id = transaction[1]
        amount_cents = cents(transaction[2])

        if payer_id in paid_cents:
            paid_cents[payer_id] += amount_cents

        transaction_shares = shares_by_transaction.get(
            transaction_id,
            []
        )

        if transaction_shares:
            for share in transaction_shares:
                participant_id = share[1]
                if participant_id in share_cents:
                    share_cents[participant_id] += cents(
                        share[2]
                    )
        elif participant_ids:
            base_share = amount_cents // len(participant_ids)
            remainder = amount_cents % len(participant_ids)

            for index, participant_id in enumerate(participant_ids):
                share_cents[participant_id] += base_share
                if index == len(participant_ids) - 1:
                    share_cents[participant_id] += remainder

    settlement_adjustments = get_settlement_adjustments_with_cursor(
        cursor,
        participant_ids,
        shared_vault_id,
        start_date,
        end_date
    )

    balances = []
    for participant in participants:
        participant_id = participant[0]
        balance_cents = (
            paid_cents.get(participant_id, 0)
            - share_cents.get(participant_id, 0)
            + settlement_adjustments.get(participant_id, 0)
        )
        balances.append({
            "vault_id": participant_id,
            "name": participant_names.get(
                participant_id,
                participant[1]
            ),
            "paid": money_from_cents(
                paid_cents.get(participant_id, 0)
            ),
            "share": money_from_cents(
                share_cents.get(participant_id, 0)
            ),
            "balance": money_from_cents(balance_cents)
        })

    return balances


def build_settlements_from_balances(balances):
    creditors = [
        item.copy()
        for item in balances
        if item["balance"] > 0
    ]
    debtors = [
        item.copy()
        for item in balances
        if item["balance"] < 0
    ]
    settlements = []

    for debtor in debtors:
        owed_cents = cents(
            -debtor["balance"]
        )

        for creditor in creditors:
            if owed_cents <= 0:
                break

            available_cents = cents(
                creditor["balance"]
            )
            if available_cents <= 0:
                continue

            settlement_cents = min(
                owed_cents,
                available_cents
            )
            settlements.append({
                "from_vault_id": debtor["vault_id"],
                "from": debtor["name"],
                "to_vault_id": creditor["vault_id"],
                "to": creditor["name"],
                "amount": money_from_cents(settlement_cents)
            })
            owed_cents -= settlement_cents
            creditor["balance"] = money_from_cents(
                available_cents - settlement_cents
            )

    return settlements


@cache_data(ttl=60)
def get_personal_spend_summary(vault_id, start_date, end_date, exclude_linked=False):
    linked_filter = ""
    if exclude_linked:
        linked_filter = """
        AND t.id NOT IN (
            SELECT transaction_id
            FROM obligation_status
            WHERE transaction_id IS NOT NULL
        )
        """

    conn = get_connection()
    try:
        row = conn.execute(
            f"""
            WITH personal_expenses AS (
                SELECT COALESCE(SUM(t.amount), 0) AS amount
                FROM transactions t
                WHERE t.vault_id = ?
                AND COALESCE(t.beneficiary_vault_id, t.vault_id) = t.vault_id
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date BETWEEN ? AND ?
                {linked_filter}
            ),
            shared_paid AS (
                SELECT COALESCE(SUM(t.amount), 0) AS amount
                FROM transactions t
                WHERE t.vault_id = ?
                AND COALESCE(t.beneficiary_vault_id, t.vault_id) != t.vault_id
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date BETWEEN ? AND ?
                {linked_filter}
            ),
            shared_share AS (
                SELECT COALESCE(SUM(ts.share_amount), 0) AS amount
                FROM transaction_shares ts
                JOIN transactions t
                    ON ts.transaction_id = t.id
                WHERE ts.participant_vault_id = ?
                AND COALESCE(t.beneficiary_vault_id, t.vault_id) != t.vault_id
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date BETWEEN ? AND ?
                {linked_filter}
            ),
            settlement_transfers AS (
                SELECT
                    COALESCE(SUM(
                        CASE
                            WHEN t.transaction_type = ? THEN t.amount
                            ELSE 0
                        END
                    ), 0) AS received,
                    COALESCE(SUM(
                        CASE
                            WHEN t.transaction_type = ? THEN t.amount
                            ELSE 0
                        END
                    ), 0) AS paid
                FROM transactions t
                WHERE t.vault_id = ?
                AND COALESCE(t.beneficiary_vault_id, t.vault_id) != t.vault_id
                AND t.is_deleted = 0
                AND t.transaction_type IN (?, ?)
                AND COALESCE(t.notes, '') LIKE 'Shared settlement:%'
                AND t.date BETWEEN ? AND ?
            )
            SELECT
                personal_expenses.amount,
                shared_paid.amount,
                shared_share.amount,
                settlement_transfers.received,
                settlement_transfers.paid
            FROM personal_expenses
            CROSS JOIN shared_paid
            CROSS JOIN shared_share
            CROSS JOIN settlement_transfers
            """,
            (
                vault_id,
                EXPENSE,
                start_date,
                end_date,
                vault_id,
                EXPENSE,
                start_date,
                end_date,
                vault_id,
                EXPENSE,
                start_date,
                end_date,
                TRANSFER_IN,
                TRANSFER_OUT,
                vault_id,
                TRANSFER_IN,
                TRANSFER_OUT,
                start_date,
                end_date
            )
        ).fetchone()

        personal_spending = as_money(row[0])
        shared_paid = as_money(row[1])
        own_shared_share = as_money(row[2])
        settlement_received = as_money(row[3])
        settlement_paid = as_money(row[4])
        settlement_balance = as_money(
            shared_paid - own_shared_share
            - settlement_received
            + settlement_paid
        )

        return {
            "personal_spending": personal_spending,
            "shared_paid": shared_paid,
            "own_shared_share": own_shared_share,
            "settlement_received": settlement_received,
            "settlement_paid": settlement_paid,
            "actual_spending": max(
                as_money(
                    personal_spending
                    + shared_paid
                    + settlement_paid
                    - settlement_received
                ),
                0
            ),
            "settlement_balance": settlement_balance,
            "receivable": max(
                settlement_balance,
                0
            ),
            "payable": max(
                -settlement_balance,
                0
            )
        }

    finally:
        conn.close()


@cache_data(ttl=60)
def get_actual_category_spending(vault_id, start_date, end_date, exclude_linked=False):
    linked_filter = ""
    if exclude_linked:
        linked_filter = """
        AND t.id NOT IN (
            SELECT transaction_id
            FROM obligation_status
            WHERE transaction_id IS NOT NULL
        )
        """

    conn = get_connection()
    try:
        rows = conn.execute(
            f"""
            WITH personal_categories AS (
                SELECT
                    COALESCE(c.emoji, '•') AS icon,
                    COALESCE(c.name, 'Uncategorized') AS name,
                    COALESCE(SUM(t.amount), 0) AS amount
                FROM transactions t
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE t.vault_id = ?
                AND COALESCE(t.beneficiary_vault_id, t.vault_id) = t.vault_id
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date BETWEEN ? AND ?
                {linked_filter}
                GROUP BY c.id, c.name, c.emoji
            ),
            shared_categories AS (
                SELECT
                    COALESCE(c.emoji, '•') AS icon,
                    COALESCE(c.name, 'Uncategorized') AS name,
                    COALESCE(SUM(t.amount), 0) AS amount
                FROM transactions t
                LEFT JOIN categories c
                    ON t.category_id = c.id
                WHERE t.vault_id = ?
                AND COALESCE(t.beneficiary_vault_id, t.vault_id) != t.vault_id
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND t.date BETWEEN ? AND ?
                {linked_filter}
                GROUP BY c.id, c.name, c.emoji
            ),
            settlement_categories AS (
                SELECT
                    '🤝' AS icon,
                    'Shared Settlement' AS name,
                    COALESCE(SUM(t.amount), 0) AS amount
                FROM transactions t
                WHERE t.vault_id = ?
                AND COALESCE(t.beneficiary_vault_id, t.vault_id) != t.vault_id
                AND t.is_deleted = 0
                AND t.transaction_type = ?
                AND COALESCE(t.notes, '') LIKE 'Shared settlement:%'
                AND t.date BETWEEN ? AND ?
            )
            SELECT icon, name, SUM(amount) AS amount
            FROM (
                SELECT * FROM personal_categories
                UNION ALL
                SELECT * FROM shared_categories
                UNION ALL
                SELECT * FROM settlement_categories
            ) rows
            GROUP BY icon, name
            HAVING SUM(amount) > 0
            ORDER BY SUM(amount) DESC
            """,
            (
                vault_id,
                EXPENSE,
                start_date,
                end_date,
                vault_id,
                EXPENSE,
                start_date,
                end_date,
                vault_id,
                TRANSFER_OUT,
                start_date,
                end_date
            )
        ).fetchall()

        return rows

    finally:
        conn.close()


@cache_data(ttl=60)
def get_shared_vault_summary(shared_vault_id, start_date, end_date):
    conn = get_connection()
    try:
        transaction_rows = conn.execute(
            """
            SELECT
                amount
            FROM transactions
            WHERE beneficiary_vault_id = ?
            AND is_deleted = 0
            AND transaction_type = ?
            AND date BETWEEN ? AND ?
            ORDER BY date DESC, id DESC
            """,
            (
                shared_vault_id,
                EXPENSE,
                start_date,
                end_date
            )
        ).fetchall()

        total_shared_cents = sum(
            cents(row[0])
            for row in transaction_rows
        )
        balances = get_shared_balances_with_cursor(
            conn,
            shared_vault_id,
            start_date,
            end_date
        )
        settlements = build_settlements_from_balances(
            balances
        )

        top_payer = max(
            balances,
            key=lambda item: item["paid"],
            default=None
        )

        return {
            "participants": balances,
            "total_shared_spending": money_from_cents(total_shared_cents),
            "settlements": settlements,
            "outstanding_settlement": money_from_cents(
                sum(cents(item["amount"]) for item in settlements)
            ),
            "top_payer": top_payer
        }

    finally:
        conn.close()


@cache_data(ttl=60)
def get_personal_outstanding_settlements(vault_id, start_date, end_date):
    conn = get_connection()
    try:
        shared_vaults = get_shared_vaults_for_personal_with_cursor(
            conn,
            vault_id
        )
        outstanding = []

        for shared_vault in shared_vaults:
            shared_vault_id = shared_vault[0]
            balances = get_shared_balances_with_cursor(
                conn,
                shared_vault_id,
                start_date,
                end_date
            )
            settlements = build_settlements_from_balances(
                balances
            )

            for settlement in settlements:
                if settlement["to_vault_id"] == vault_id:
                    outstanding.append({
                        "shared_vault_id": shared_vault_id,
                        "shared_vault_name": shared_vault[1],
                        "direction": "receivable",
                        "label": "Owed to You:",
                        "counterparty_vault_id": settlement["from_vault_id"],
                        "counterparty_name": settlement["from"],
                        "from_vault_id": settlement["from_vault_id"],
                        "from_name": settlement["from"],
                        "to_vault_id": settlement["to_vault_id"],
                        "to_name": settlement["to"],
                        "amount": settlement["amount"]
                    })
                elif settlement["from_vault_id"] == vault_id:
                    outstanding.append({
                        "shared_vault_id": shared_vault_id,
                        "shared_vault_name": shared_vault[1],
                        "direction": "payable",
                        "label": "You Owe:",
                        "counterparty_vault_id": settlement["to_vault_id"],
                        "counterparty_name": settlement["to"],
                        "from_vault_id": settlement["from_vault_id"],
                        "from_name": settlement["from"],
                        "to_vault_id": settlement["to_vault_id"],
                        "to_name": settlement["to"],
                        "amount": settlement["amount"]
                    })

        return outstanding

    finally:
        conn.close()


def get_settlement_summary(vault_id, start_date, end_date):
    settlements = get_personal_outstanding_settlements(
        vault_id,
        start_date,
        end_date
    )
    receivable = as_money(
        sum(
            settlement["amount"]
            for settlement in settlements
            if settlement["direction"] == "receivable"
        )
    )
    payable = as_money(
        sum(
            settlement["amount"]
            for settlement in settlements
            if settlement["direction"] == "payable"
        )
    )
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
        "items": settlements
    }


def validate_settlement_account_with_cursor(cursor, vault_id, account_id):
    row = cursor.execute(
        """
        SELECT 1
        FROM accounts
        WHERE id = ?
        AND vault_id = ?
        AND is_active = 1
        """,
        (
            account_id,
            vault_id
        )
    ).fetchone()

    if not row:
        raise ValueError("Choose a valid active account for the settlement.")


def settle_outstanding_settlement(
    shared_vault_id,
    from_vault_id,
    from_account_id,
    to_vault_id,
    to_account_id,
    amount,
    settlement_date
):
    amount = as_money(amount)
    if amount <= 0:
        raise ValueError("Settlement amount must be greater than zero.")

    conn = get_connection()
    try:
        cursor = conn.cursor()
        validate_settlement_account_with_cursor(
            cursor,
            from_vault_id,
            from_account_id
        )
        validate_settlement_account_with_cursor(
            cursor,
            to_vault_id,
            to_account_id
        )

        from_name = cursor.execute(
            """
            SELECT name
            FROM vaults
            WHERE id = ?
            """,
            (from_vault_id,)
        ).fetchone()
        to_name = cursor.execute(
            """
            SELECT name
            FROM vaults
            WHERE id = ?
            """,
            (to_vault_id,)
        ).fetchone()

        if not from_name or not to_name:
            raise ValueError("Settlement participant no longer exists.")

        transfer_group_id = str(
            uuid.uuid4()
        )
        notes = (
            "Shared settlement: "
            f"{from_name[0]} paid {to_name[0]}"
        )

        cursor.execute(
            """
            INSERT INTO transactions
            (
                vault_id,
                beneficiary_vault_id,
                account_id,
                date,
                amount,
                transaction_type,
                notes,
                transfer_group_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                from_vault_id,
                shared_vault_id,
                from_account_id,
                settlement_date,
                amount,
                TRANSFER_OUT,
                notes,
                transfer_group_id
            )
            ,
            capture_lastrowid=False
        )
        cursor.execute(
            """
            INSERT INTO transactions
            (
                vault_id,
                beneficiary_vault_id,
                account_id,
                date,
                amount,
                transaction_type,
                notes,
                transfer_group_id
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                to_vault_id,
                shared_vault_id,
                to_account_id,
                settlement_date,
                amount,
                TRANSFER_IN,
                notes,
                transfer_group_id
            )
            ,
            capture_lastrowid=False
        )

        conn.commit()
        clear_data_cache((
            "shared_expenses",
            "transaction_shares",
            "transactions",
            "accounts",
            "dashboard",
            "reports",
            "transfers"
        ))
        return transfer_group_id

    finally:
        conn.close()


@cache_data(ttl=60)
def get_shared_category_spending(shared_vault_id, start_date, end_date):
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT
                COALESCE(c.emoji, '🏷️') AS icon,
                COALESCE(c.name, 'Uncategorized') AS name,
                COALESCE(SUM(t.amount), 0) AS amount
            FROM transactions t
            LEFT JOIN categories c
                ON t.category_id = c.id
            WHERE t.beneficiary_vault_id = ?
            AND t.is_deleted = 0
            AND t.transaction_type = ?
            AND t.date BETWEEN ? AND ?
            GROUP BY c.id, c.name, c.emoji
            HAVING COALESCE(SUM(t.amount), 0) > 0
            ORDER BY SUM(t.amount) DESC
            """,
            (
                shared_vault_id,
                EXPENSE,
                start_date,
                end_date
            )
        ).fetchall()

    finally:
        conn.close()


@cache_data(ttl=60)
def get_shared_recent_activity(shared_vault_id, start_date, end_date, limit=4):
    conn = get_connection()
    try:
        return conn.execute(
            """
            SELECT
                t.id,
                t.date,
                t.amount,
                COALESCE(payer.name, 'Unknown') AS payer_name,
                COALESCE(c.name, 'Uncategorized') AS category_name,
                COALESCE(c.emoji, '🏷️') AS category_icon,
                COALESCE(t.notes, '') AS notes
            FROM transactions t
            LEFT JOIN vaults payer
                ON t.vault_id = payer.id
            LEFT JOIN categories c
                ON t.category_id = c.id
            WHERE t.beneficiary_vault_id = ?
            AND t.is_deleted = 0
            AND t.transaction_type = ?
            AND t.date BETWEEN ? AND ?
            ORDER BY t.date DESC, t.id DESC
            LIMIT ?
            """,
            (
                shared_vault_id,
                EXPENSE,
                start_date,
                end_date,
                limit
            )
        ).fetchall()

    finally:
        conn.close()


@cache_data(ttl=60)
def get_shared_expenses_page_data(
    shared_vault_id,
    start_date,
    end_date,
    category_id=None,
    paid_by_vault_id=None
):
    conn = get_connection()
    try:
        participants = conn.execute(
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
        current_participant, other_participants = get_current_participant_context(
            participants
        )
        current_participant_id = (
            current_participant[0]
            if current_participant
            else None
        )
        other_participant_ids = [
            participant[0]
            for participant in other_participants
        ]

        filters = [
            "t.beneficiary_vault_id = ?",
            "t.is_deleted = 0",
            "t.transaction_type = ?",
            "t.date BETWEEN ? AND ?"
        ]
        params = [
            shared_vault_id,
            EXPENSE,
            start_date,
            end_date
        ]

        if category_id:
            filters.append("t.category_id = ?")
            params.append(category_id)

        if paid_by_vault_id:
            filters.append("t.vault_id = ?")
            params.append(paid_by_vault_id)

        where_clause = " AND ".join(filters)

        transactions = conn.execute(
            f"""
            SELECT
                t.id,
                t.date,
                t.vault_id,
                COALESCE(payer.name, 'Unknown') AS payer_name,
                t.amount,
                t.allocation_method,
                COALESCE(t.notes, '') AS notes,
                COALESCE(c.id, 0) AS category_id,
                COALESCE(c.name, 'Uncategorized') AS category_name,
                COALESCE(c.emoji, '🏷️') AS category_icon
            FROM transactions t
            LEFT JOIN vaults payer
                ON t.vault_id = payer.id
            LEFT JOIN categories c
                ON t.category_id = c.id
            WHERE {where_clause}
            ORDER BY t.date DESC, t.id DESC
            """,
            tuple(params)
        ).fetchall()

        transaction_ids = [
            row[0]
            for row in transactions
        ]
        shares_by_transaction = {}

        if transaction_ids:
            placeholders = ", ".join(
                ["?"] * len(transaction_ids)
            )
            share_rows = conn.execute(
                f"""
                SELECT
                    transaction_id,
                    participant_vault_id,
                    share_amount,
                    share_percentage
                FROM transaction_shares
                WHERE transaction_id IN ({placeholders})
                """,
                tuple(transaction_ids)
            ).fetchall()

            for share in share_rows:
                shares_by_transaction.setdefault(
                    share[0],
                    []
                ).append({
                    "participant_id": share[1],
                    "amount": as_money(share[2]),
                    "percentage": share[3]
                })

        total_spend = 0
        paid_by_current = 0
        paid_by_other = 0
        expense_rows = []

        for transaction in transactions:
            transaction_id = transaction[0]
            payer_id = transaction[2]
            amount = as_money(transaction[4])
            total_spend = as_money(total_spend + amount)

            if payer_id == current_participant_id:
                paid_by_current = as_money(
                    paid_by_current + amount
                )
            elif payer_id in other_participant_ids:
                paid_by_other = as_money(
                    paid_by_other + amount
                )

            shares = shares_by_transaction.get(
                transaction_id,
                []
            )

            if not shares and participants:
                amount_cents = cents(amount)
                base_share = amount_cents // len(participants)
                remainder = amount_cents % len(participants)
                shares = []

                for index, participant in enumerate(participants):
                    share_cents = base_share
                    if index == len(participants) - 1:
                        share_cents += remainder

                    shares.append({
                        "participant_id": participant[0],
                        "amount": money_from_cents(share_cents),
                        "percentage": round(
                            money_from_cents(share_cents) / amount * 100,
                            6
                        ) if amount else 0
                    })

            my_share = as_money(
                sum(
                    share["amount"]
                    for share in shares
                    if share["participant_id"] == current_participant_id
                )
            )
            other_share = as_money(
                amount - my_share
            )

            if payer_id == current_participant_id:
                settlement_amount = other_share
                settlement_label = (
                    "Owes you"
                    if settlement_amount > 0
                    else "Settled"
                )
                settlement_tone = (
                    "positive"
                    if settlement_amount > 0
                    else "neutral"
                )
            else:
                settlement_amount = my_share
                settlement_label = (
                    "You owe"
                    if settlement_amount > 0
                    else "Settled"
                )
                settlement_tone = (
                    "negative"
                    if settlement_amount > 0
                    else "neutral"
                )

            expense_rows.append({
                "id": transaction_id,
                "date": transaction[1],
                "paid_by_id": payer_id,
                "paid_by": transaction[3],
                "amount": amount,
                "allocation_method": transaction[5] or "Equal",
                "notes": transaction[6],
                "merchant": transaction[6] or transaction[8],
                "category_id": transaction[7],
                "category": transaction[8],
                "category_icon": transaction[9],
                "split_label": split_label_for_shares(
                    amount,
                    shares
                ),
                "my_share": my_share,
                "other_share": other_share,
                "settlement_amount": settlement_amount,
                "settlement_label": settlement_label,
                "settlement_tone": settlement_tone
            })

        categories = conn.execute(
            """
            SELECT DISTINCT
                c.id,
                c.name,
                c.emoji
            FROM transactions t
            JOIN categories c
                ON t.category_id = c.id
            WHERE t.beneficiary_vault_id = ?
            AND t.is_deleted = 0
            AND t.transaction_type = ?
            ORDER BY c.name
            """,
            (
                shared_vault_id,
                EXPENSE
            )
        ).fetchall()

        return {
            "participants": participants,
            "current_participant": current_participant,
            "other_participants": other_participants,
            "categories": categories,
            "summary": {
                "total_shared_spend": total_spend,
                "total_transactions": len(expense_rows),
                "paid_by_current": paid_by_current,
                "paid_by_other": paid_by_other
            },
            "expenses": expense_rows
        }

    finally:
        conn.close()

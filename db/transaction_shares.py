from db.cache import cache_data
from db.core import get_connection


ALLOCATION_EQUAL = "Equal"
ALLOCATION_PERCENTAGE = "Percentage"
ALLOCATION_FIXED = "Fixed Amount"
ALLOCATION_METHODS = [
    ALLOCATION_EQUAL,
    ALLOCATION_PERCENTAGE,
    ALLOCATION_FIXED
]

@cache_data(ttl=60)
def shared_expense_schema_ready():
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                EXISTS (
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'transactions'
                    AND column_name = 'beneficiary_vault_id'
                ),
                EXISTS (
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_name = 'transaction_shares'
                )
            """
        ).fetchone()

        return bool(row and row[0] and row[1])

    finally:
        conn.close()


def cents(value):
    return int(
        round(
            float(value or 0) * 100
        )
    )


def money_from_cents(value):
    return round(
        value / 100,
        2
    )


def calculate_equal_shares(amount, participant_vaults):
    participant_count = len(
        participant_vaults
    )

    if participant_count == 0:
        raise ValueError("Shared expenses need at least one participant.")

    total_cents = cents(
        amount
    )
    base_cents = total_cents // participant_count
    remainder = total_cents - (
        base_cents * participant_count
    )
    share_percentage = round(
        100 / participant_count,
        6
    )

    shares = []

    for index, participant in enumerate(participant_vaults):
        share_cents = base_cents
        if index == participant_count - 1:
            share_cents += remainder

        shares.append(
            {
                "participant_vault_id": participant[0],
                "share_amount": money_from_cents(
                    share_cents
                ),
                "share_percentage": share_percentage
            }
        )

    return shares


def calculate_percentage_shares(amount, participant_vaults, percentages):
    total_percentage = sum(
        float(
            percentages.get(
                participant[0],
                0
            )
        )
        for participant in participant_vaults
    )

    if round(total_percentage, 6) != 100:
        raise ValueError("Share percentages must total exactly 100%.")

    total_cents = cents(
        amount
    )
    allocated_cents = 0
    shares = []

    for index, participant in enumerate(participant_vaults):
        percentage = float(
            percentages.get(
                participant[0],
                0
            )
        )

        if percentage < 0:
            raise ValueError("Share percentages cannot be negative.")

        if index == len(participant_vaults) - 1:
            share_cents = total_cents - allocated_cents
        else:
            share_cents = cents(
                float(amount) * percentage / 100
            )
            allocated_cents += share_cents

        shares.append(
            {
                "participant_vault_id": participant[0],
                "share_amount": money_from_cents(
                    share_cents
                ),
                "share_percentage": percentage
            }
        )

    return shares


def calculate_fixed_shares(amount, participant_vaults, fixed_amounts):
    total_share_cents = sum(
        cents(
            fixed_amounts.get(
                participant[0],
                0
            )
        )
        for participant in participant_vaults
    )

    if total_share_cents != cents(amount):
        raise ValueError("Share amounts must total the transaction amount.")

    shares = []

    for participant in participant_vaults:
        share_amount = float(
            fixed_amounts.get(
                participant[0],
                0
            )
        )

        if share_amount < 0:
            raise ValueError("Share amounts cannot be negative.")

        share_percentage = (
            round(
                share_amount / float(amount) * 100,
                6
            )
            if float(amount)
            else None
        )

        shares.append(
            {
                "participant_vault_id": participant[0],
                "share_amount": round(
                    share_amount,
                    2
                ),
                "share_percentage": share_percentage
            }
        )

    return shares


def calculate_transaction_shares(
    amount,
    allocation_method,
    participant_vaults,
    percentage_allocations=None,
    amount_allocations=None
):
    if allocation_method == ALLOCATION_EQUAL:
        return calculate_equal_shares(
            amount,
            participant_vaults
        )

    if allocation_method == ALLOCATION_PERCENTAGE:
        return calculate_percentage_shares(
            amount,
            participant_vaults,
            percentage_allocations or {}
        )

    if allocation_method == ALLOCATION_FIXED:
        return calculate_fixed_shares(
            amount,
            participant_vaults,
            amount_allocations or {}
        )

    raise ValueError("Choose a valid allocation method.")


def validate_transaction_shares(amount, shares, require_percentages=False):
    if not shares:
        raise ValueError("Shared expenses need participant shares.")

    if sum(cents(share["share_amount"]) for share in shares) != cents(amount):
        raise ValueError("Share amounts must total the transaction amount.")

    if require_percentages:
        total_percentage = sum(
            float(
                share.get("share_percentage") or 0
            )
            for share in shares
        )

        if round(total_percentage, 6) != 100:
            raise ValueError("Share percentages must total exactly 100%.")


def replace_transaction_shares_with_cursor(cursor, transaction_id, shares):
    cursor.execute(
        """
        DELETE FROM transaction_shares
        WHERE transaction_id = ?
        """,
        (transaction_id,)
    )

    for share in shares:
        cursor.execute(
            """
            INSERT INTO transaction_shares
            (
                transaction_id,
                participant_vault_id,
                share_amount,
                share_percentage
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                transaction_id,
                share["participant_vault_id"],
                share["share_amount"],
                share.get("share_percentage")
            )
        )


@cache_data(ttl=60)
def get_transaction_shares(transaction_id):
    conn = get_connection()
    try:
        shares = conn.execute(
            """
            SELECT
                ts.id,
                ts.transaction_id,
                ts.participant_vault_id,
                v.name,
                ts.share_amount,
                ts.share_percentage
            FROM transaction_shares ts
            JOIN vaults v
                ON ts.participant_vault_id = v.id
            WHERE ts.transaction_id = ?
            ORDER BY v.name
            """,
            (transaction_id,)
        ).fetchall()

        return shares

    finally:
        conn.close()

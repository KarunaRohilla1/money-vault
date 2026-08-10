from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from db.core import get_connection


def duplicate_window_hours() -> int:
    raw = os.environ.get("CAPTURE_DUPLICATE_WINDOW_HOURS", "24")
    try:
        return max(1, int(raw))
    except ValueError:
        return 24


@dataclass
class DuplicateMatch:
    duplicate: bool
    existing_transaction_id: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "duplicate": self.duplicate,
            "existingTransactionId": self.existing_transaction_id,
        }


class DuplicateDetector:
    """Detect likely duplicate transactions. Never auto-rejects."""

    def find_duplicate(
        self,
        vault_id: int,
        amount: Optional[float],
        merchant: Optional[str],
        transaction_date: Optional[date] = None,
        window_hours: Optional[int] = None,
    ) -> DuplicateMatch:
        if amount is None or not merchant:
            return DuplicateMatch(duplicate=False)

        hours = window_hours if window_hours is not None else duplicate_window_hours()
        center = transaction_date or date.today()
        # Date column is TEXT (YYYY-MM-DD); approximate window with calendar days.
        day_span = max(1, (hours + 23) // 24)
        start = (center - timedelta(days=day_span)).isoformat()
        end = (center + timedelta(days=day_span)).isoformat()
        merchant_key = merchant.strip().lower()

        conn = get_connection()
        try:
            row = conn.execute(
                """
                SELECT t.id
                FROM transactions t
                LEFT JOIN categories c
                    ON c.id = t.category_id
                WHERE t.vault_id = ?
                AND t.is_deleted = 0
                AND ABS(t.amount - ?) < 0.005
                AND t.date >= ?
                AND t.date <= ?
                AND LOWER(
                    COALESCE(
                        NULLIF(TRIM(t.notes), ''),
                        NULLIF(TRIM(c.name), ''),
                        ''
                    )
                ) = ?
                ORDER BY t.id DESC
                LIMIT 1
                """,
                (
                    vault_id,
                    float(amount),
                    start,
                    end,
                    merchant_key,
                ),
            ).fetchone()

            if not row:
                return DuplicateMatch(duplicate=False)

            return DuplicateMatch(
                duplicate=True,
                existing_transaction_id=int(row[0]),
            )
        finally:
            conn.close()

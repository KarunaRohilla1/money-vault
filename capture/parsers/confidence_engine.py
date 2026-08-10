from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from capture.parsers.base import FieldConfidence, ParsedCapture


@dataclass
class ConfidenceResult:
    overall: int
    fields: dict[str, int]

    def as_dict(self) -> dict:
        return {
            "overall": self.overall,
            "fields": self.fields,
        }


class ConfidenceEngine:
    """Derive overall + per-field confidence from parser signals."""

    WEIGHTS = {
        "amount": 0.30,
        "transactionType": 0.20,
        "merchant": 0.20,
        "date": 0.15,
        "account": 0.10,
        "category": 0.05,
    }

    READY_THRESHOLD = 80

    def evaluate(self, parsed: ParsedCapture, field_confidence: Optional[FieldConfidence] = None) -> ConfidenceResult:
        fields = (field_confidence or parsed.field_confidence).as_dict()

        if parsed.parse_failed or parsed.amount is None:
            fields["amount"] = min(fields.get("amount", 0), 10)
            overall = min(35, self._weighted(fields))
            return ConfidenceResult(overall=overall, fields=fields)

        overall = self._weighted(fields)
        return ConfidenceResult(overall=overall, fields=fields)

    def _weighted(self, fields: dict[str, int]) -> int:
        total = 0.0
        weight_sum = 0.0
        for key, weight in self.WEIGHTS.items():
            value = int(fields.get(key, 0) or 0)
            total += value * weight
            weight_sum += weight
        if weight_sum <= 0:
            return 0
        return int(round(total / weight_sum))

    def is_ready(self, confidence: ConfidenceResult, parsed: ParsedCapture) -> bool:
        return (
            not parsed.parse_failed
            and parsed.amount is not None
            and parsed.amount > 0
            and bool(parsed.transaction_type)
            and confidence.overall >= self.READY_THRESHOLD
            and confidence.fields.get("amount", 0) >= 90
        )

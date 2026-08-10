from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional


class ParserSource(str, Enum):
    SMS = "sms"
    EMAIL = "email"
    OCR = "ocr"
    BANK_STATEMENT = "bank_statement"
    CSV = "csv"


@dataclass
class FieldConfidence:
    amount: int = 0
    merchant: int = 0
    transaction_type: int = 0
    date: int = 0
    account: int = 0
    category: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "amount": self.amount,
            "merchant": self.merchant,
            "transactionType": self.transaction_type,
            "date": self.date,
            "account": self.account,
            "category": self.category,
        }


@dataclass
class ParsedCapture:
    """Structured result shared by every parser implementation."""

    raw_text: str
    amount: Optional[float] = None
    currency: str = "INR"
    merchant: Optional[str] = None
    transaction_type: Optional[str] = None
    date: Optional[date] = None
    account_name: Optional[str] = None
    account_hint: Optional[str] = None
    category_name: Optional[str] = None
    notes: Optional[str] = None
    field_confidence: FieldConfidence = field(default_factory=FieldConfidence)
    parse_failed: bool = False
    failure_reason: Optional[str] = None
    source: ParserSource = ParserSource.SMS


class MessageParser(ABC):
    """Contract for future SMS / email / OCR / statement / CSV parsers."""

    source: ParserSource

    @abstractmethod
    def parse(self, raw_text: str) -> ParsedCapture:
        raise NotImplementedError

    def can_handle(self, raw_text: str) -> bool:
        return bool((raw_text or "").strip())

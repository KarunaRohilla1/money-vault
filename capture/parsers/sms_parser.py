from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from db.core import EXPENSE, INCOME, TRANSFER_IN, TRANSFER_OUT

from capture.parsers.base import FieldConfidence, MessageParser, ParsedCapture, ParserSource
from capture.parsers.merchant_parser import (
    extract_merchant,
    looks_like_wallet_funding,
)


AMOUNT_PATTERNS = [
    re.compile(
        r"(?:rs\.?|inr|₹)\s*([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"([0-9]{1,3}(?:,[0-9]{2,3})*(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\s*(?:rs\.?|inr|₹)",
        re.IGNORECASE,
    ),
]

ACCOUNT_PATTERNS = [
    re.compile(
        r"(?:a/?c|account|acct)(?:\s*(?:no\.?|number|#))?\s*(?:ending\s*(?:with|in)\s*)?(?:XX+|X{2,}|\*+)?(\d{3,6})",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:XX+|X{2,}|\*+)(\d{3,4})\b",
        re.IGNORECASE,
    ),
]

BANK_NAME_PATTERN = re.compile(
    r"\b(hdfc|icici|sbi|axis|kotak|yes\s*bank|idfc|bob|pnb|union\s*bank|canara|indusind|federal)\b",
    re.IGNORECASE,
)

DATE_PATTERNS = [
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\b"), "%d/%m/%Y"),
    (re.compile(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{2,4})\b"), "%d-%b-%Y"),
    (re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3})[a-z]*[,\s]+(\d{2,4})\b"), "%d %b %Y"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "%Y-%m-%d"),
]

DEBIT_KEYWORDS = (
    "debited",
    "debit",
    "spent",
    "paid",
    "purchase",
    "withdrawn",
    "withdrawal",
    "sent",
    "payment of",
    "has been paid",
)

CREDIT_KEYWORDS = (
    "credited",
    "credit",
    "received",
    "deposit",
    "deposited",
    "refund",
    "cashback",
)


def _parse_amount(raw: str) -> Optional[float]:
    for pattern in AMOUNT_PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        token = match.group(1).replace(",", "")
        try:
            value = float(token)
        except ValueError:
            continue
        if value > 0:
            return value
    return None


def _parse_date(raw: str) -> tuple[Optional[date], int]:
    for pattern, _fmt in DATE_PATTERNS:
        match = pattern.search(raw)
        if not match:
            continue
        parts = match.groups()
        try:
            if pattern.pattern.startswith(r"\b(\d{4})"):
                parsed = datetime.strptime(f"{parts[0]}-{parts[1]}-{parts[2]}", "%Y-%m-%d").date()
                return parsed, 95
            day, month, year = parts[0], parts[1], parts[2]
            if year.isdigit() and len(year) == 2:
                year = f"20{year}"
            if month.isdigit():
                parsed = datetime.strptime(f"{int(day):02d}/{int(month):02d}/{year}", "%d/%m/%Y").date()
            else:
                parsed = datetime.strptime(f"{int(day):02d}-{month.title()}-{year}", "%d-%b-%Y").date()
            return parsed, 90
        except ValueError:
            continue
    return date.today(), 40


def _detect_transaction_type(raw_text: str, merchant: Optional[str]) -> tuple[str, int]:
    lowered = raw_text.lower()

    # Funding a wallet / UPI transfer between own instruments is Transfer, not Expense.
    if looks_like_wallet_funding(raw_text, merchant):
        if any(token in lowered for token in CREDIT_KEYWORDS):
            return TRANSFER_IN, 90
        return TRANSFER_OUT, 90

    if any(token in lowered for token in ("transfer to", "transferred to", "neft", "imps", "rtgs")):
        if any(token in lowered for token in CREDIT_KEYWORDS):
            return TRANSFER_IN, 85
        return TRANSFER_OUT, 85

    credit_hit = any(token in lowered for token in CREDIT_KEYWORDS)
    debit_hit = any(token in lowered for token in DEBIT_KEYWORDS)

    if credit_hit and not debit_hit:
        return INCOME, 88
    if debit_hit and not credit_hit:
        return EXPENSE, 88
    if credit_hit and debit_hit:
        # Prefer the first occurrence order in the message.
        credit_pos = min(
            (lowered.find(token) for token in CREDIT_KEYWORDS if token in lowered),
            default=10**9,
        )
        debit_pos = min(
            (lowered.find(token) for token in DEBIT_KEYWORDS if token in lowered),
            default=10**9,
        )
        if credit_pos < debit_pos:
            return INCOME, 70
        return EXPENSE, 70

    return EXPENSE, 35


def _extract_account_hint(raw_text: str) -> tuple[Optional[str], Optional[str], int]:
    for pattern in ACCOUNT_PATTERNS:
        match = pattern.search(raw_text)
        if match:
            digits = match.group(1)
            return f"A/c **{digits}", digits, 75

    bank_match = BANK_NAME_PATTERN.search(raw_text)
    if bank_match:
        name = bank_match.group(1).strip()
        pretty = " ".join(part.upper() if len(part) <= 4 else part.title() for part in name.split())
        return pretty, pretty, 55

    return None, None, 0


class SmsParser(MessageParser):
    source = ParserSource.SMS

    def parse(self, raw_text: str) -> ParsedCapture:
        text = (raw_text or "").strip()
        if not text:
            return ParsedCapture(
                raw_text=raw_text or "",
                parse_failed=True,
                failure_reason="Empty message.",
                field_confidence=FieldConfidence(),
                source=self.source,
            )

        amount = _parse_amount(text)
        amount_confidence = 100 if amount is not None else 0

        # Merchant hint before type so wallet-funding rules can apply.
        provisional_merchant, _ = extract_merchant(text)
        transaction_type, type_confidence = _detect_transaction_type(text, provisional_merchant)
        merchant, merchant_confidence = extract_merchant(text, transaction_type)

        # Re-evaluate funding after refined merchant extraction.
        if looks_like_wallet_funding(text, merchant) and transaction_type == EXPENSE:
            transaction_type = TRANSFER_OUT
            type_confidence = max(type_confidence, 90)

        txn_date, date_confidence = _parse_date(text)
        account_name, account_hint, account_confidence = _extract_account_hint(text)

        parse_failed = amount is None
        failure_reason = "Could not extract amount." if parse_failed else None

        notes_parts = []
        if merchant:
            notes_parts.append(merchant)
        notes = " — ".join(notes_parts) if notes_parts else None

        return ParsedCapture(
            raw_text=text,
            amount=amount,
            currency="INR",
            merchant=merchant,
            transaction_type=transaction_type,
            date=txn_date,
            account_name=account_name,
            account_hint=account_hint,
            notes=notes,
            parse_failed=parse_failed,
            failure_reason=failure_reason,
            field_confidence=FieldConfidence(
                amount=amount_confidence,
                merchant=merchant_confidence,
                transaction_type=type_confidence,
                date=date_confidence,
                account=account_confidence,
                category=0,
            ),
            source=self.source,
        )

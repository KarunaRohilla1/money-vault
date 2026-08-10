from __future__ import annotations

import re
from typing import Optional


WALLET_KEYWORDS = (
    "paytm",
    "phonepe",
    "gpay",
    "google pay",
    "amazon pay",
    "mobikwik",
    "freecharge",
    "cred",
    "bhim",
    "wallet",
)

FUNDING_KEYWORDS = (
    "added to",
    "loaded to",
    "funded",
    "funding",
    "transferred to",
    "transfer to",
    "sent to",
    "money added",
    "wallet load",
    "recharged",
)

UPI_VPA_PATTERN = re.compile(
    r"(?:to|towards|at|from)\s+(?:vpa\s+)?([a-zA-Z0-9._-]+@[a-zA-Z0-9]+)",
    re.IGNORECASE,
)

MERCHANT_TOWARDS_PATTERN = re.compile(
    r"(?:towards|to|at|for)\s+([A-Za-z0-9][A-Za-z0-9 &._'-]{1,60}?)(?=\s+(?:on|via|upi|ref|avl|info|not\s+you)|[.!]|$)",
    re.IGNORECASE,
)

MERCHANT_FROM_PATTERN = re.compile(
    r"(?:from|by)\s+([A-Za-z0-9][A-Za-z0-9 &._'-]{1,60}?)(?=\s+(?:on|via|upi|ref|avl|info)|[.!]|$)",
    re.IGNORECASE,
)

NOISE_TOKENS = {
    "a/c",
    "ac",
    "account",
    "bank",
    "upi",
    "ref",
    "no",
    "rs",
    "inr",
    "your",
    "the",
    "vpa",
}


def _clean_merchant(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    cleaned = re.sub(r"\s+", " ", value).strip(" .,;:-_")
    cleaned = re.sub(r"\*+", "", cleaned)
    cleaned = re.sub(r"\bXX+\d*\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bX{2,}\d+\b", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,;:-_")

    if not cleaned:
        return None

    lowered = cleaned.lower()
    if lowered in NOISE_TOKENS or len(cleaned) < 2:
        return None

    if "@" in cleaned:
        handle = cleaned.split("@", 1)[0]
        handle = handle.replace(".", " ").replace("_", " ").replace("-", " ")
        handle = re.sub(r"\s+", " ", handle).strip()
        if handle:
            return handle.title()

    return cleaned.title()


def is_wallet_name(value: Optional[str]) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return any(keyword in lowered for keyword in WALLET_KEYWORDS)


def looks_like_wallet_funding(raw_text: str, merchant: Optional[str]) -> bool:
    lowered = (raw_text or "").lower()
    if any(keyword in lowered for keyword in FUNDING_KEYWORDS) and (
        is_wallet_name(merchant) or any(keyword in lowered for keyword in WALLET_KEYWORDS)
    ):
        return True

    if is_wallet_name(merchant) and any(
        token in lowered for token in ("transfer", "transferred", "sent to", "added")
    ):
        return True

    return False


def extract_merchant(raw_text: str, transaction_type: Optional[str] = None) -> tuple[Optional[str], int]:
    text = raw_text or ""

    vpa_match = UPI_VPA_PATTERN.search(text)
    if vpa_match:
        merchant = _clean_merchant(vpa_match.group(1))
        if merchant:
            return merchant, 92

    if transaction_type == "Income":
        from_match = MERCHANT_FROM_PATTERN.search(text)
        if from_match:
            merchant = _clean_merchant(from_match.group(1))
            if merchant and not merchant.lower().startswith("a/c"):
                return merchant, 80

    towards_match = MERCHANT_TOWARDS_PATTERN.search(text)
    if towards_match:
        merchant = _clean_merchant(towards_match.group(1))
        if merchant and not merchant.lower().startswith("a/c"):
            return merchant, 85

    from_match = MERCHANT_FROM_PATTERN.search(text)
    if from_match:
        merchant = _clean_merchant(from_match.group(1))
        if merchant and not merchant.lower().startswith("a/c"):
            return merchant, 70

    return None, 0

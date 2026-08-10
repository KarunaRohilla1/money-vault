from __future__ import annotations

from typing import Optional


# Rule-based merchant / keyword → category suggestions. No AI.
CATEGORY_RULES: list[tuple[tuple[str, ...], str, str]] = [
    (("swiggy", "zomato", "dominos", "domino", "mcdonald", "burger king", "kfc", "starbucks", "cafe"), "Food & Dining", "Expense"),
    (("bigbasket", "blinkit", "zepto", "instamart", "dmart", "reliance fresh", "grocery"), "Groceries", "Expense"),
    (("uber", "ola", "rapido", "metro", "irctc", "petrol", "fuel", "hpcl", "bpcl", "ioc"), "Transport", "Expense"),
    (("amazon", "flipkart", "myntra", "ajio", "meesho", "nykaa"), "Shopping", "Expense"),
    (("netflix", "spotify", "prime", "hotstar", "disney", "youtube"), "Subscriptions", "Expense"),
    (("electricity", "bescom", "tata power", "gas", "water bill", "broadband", "airtel", "jio", "vi "), "Utilities", "Expense"),
    (("pharmacy", "apollo", "1mg", "pharmeasy", "hospital", "clinic"), "Health", "Expense"),
    (("rent", "maintenance", "society"), "Housing", "Expense"),
    (("salary", "payroll", "credited by employer"), "Income", "Income"),
    (("interest", "dividend"), "Income", "Income"),
]


class CategorySuggester:
    """Basic rule-based category suggestion. Future: ML / user history."""

    def suggest(
        self,
        merchant: Optional[str],
        transaction_type: Optional[str],
        raw_text: str = "",
    ) -> tuple[Optional[str], int]:
        if transaction_type in ("Transfer In", "Transfer Out"):
            return "Transfer", 95

        if transaction_type == "Income":
            return "Income", 80

        haystack = f"{merchant or ''} {raw_text or ''}".lower()

        for keywords, category_name, category_type in CATEGORY_RULES:
            if category_type == "Income" and transaction_type not in (None, "Income"):
                continue
            if any(keyword in haystack for keyword in keywords):
                return category_name, 78

        if merchant:
            return None, 20

        return None, 0

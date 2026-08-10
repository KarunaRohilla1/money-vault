from capture.parsers.sms_parser import SmsParser
from capture.parsers.category_suggester import CategorySuggester
from capture.parsers.confidence_engine import ConfidenceEngine
from capture.parsers.merchant_parser import looks_like_wallet_funding
from db.core import EXPENSE, INCOME, TRANSFER_OUT


def test_sms_parser_extracts_upi_debit():
    raw = (
        "HDFC Bank: Rs.450.00 debited from a/c XX1234 on 08-08-26 "
        "to VPA swiggy@ybl. UPI Ref no 123456789012. Not you? Call 1800."
    )
    parsed = SmsParser().parse(raw)

    assert parsed.amount == 450.0
    assert parsed.currency == "INR"
    assert parsed.transaction_type == EXPENSE
    assert parsed.merchant == "Swiggy"
    assert parsed.date is not None
    assert parsed.account_hint == "1234"
    assert parsed.parse_failed is False
    assert parsed.field_confidence.amount == 100


def test_sms_parser_classifies_wallet_funding_as_transfer_not_expense():
    raw = (
        "INR 500.00 transferred to Paytm Wallet from a/c XX9876 on 08/08/2026. "
        "Available bal INR 12,000.00"
    )
    assert looks_like_wallet_funding(raw, "Paytm") is True

    parsed = SmsParser().parse(raw)
    assert parsed.transaction_type == TRANSFER_OUT
    assert parsed.amount == 500.0
    assert parsed.transaction_type != EXPENSE


def test_sms_parser_income_credit():
    raw = "ICICI Bank: INR 45,000.00 credited to a/c XX4321 on 01-Aug-2026. Info: SALARY."
    parsed = SmsParser().parse(raw)

    assert parsed.amount == 45000.0
    assert parsed.transaction_type == INCOME


def test_sms_parser_failed_without_amount():
    parsed = SmsParser().parse("Something happened on your account today.")
    assert parsed.parse_failed is True
    assert parsed.amount is None


def test_category_suggester_rules():
    suggester = CategorySuggester()
    name, confidence = suggester.suggest("Swiggy", EXPENSE, "paid to swiggy")
    assert name == "Food & Dining"
    assert confidence >= 70

    transfer_name, transfer_confidence = suggester.suggest("Paytm", TRANSFER_OUT, "funded wallet")
    assert transfer_name == "Transfer"
    assert transfer_confidence >= 90


def test_confidence_engine_ready_threshold():
    from capture.parsers.base import FieldConfidence, ParsedCapture
    from datetime import date

    engine = ConfidenceEngine()
    parsed = ParsedCapture(
        raw_text="test",
        amount=100,
        transaction_type=EXPENSE,
        merchant="Swiggy",
        date=date.today(),
        field_confidence=FieldConfidence(
            amount=100,
            merchant=95,
            transaction_type=90,
            date=90,
            account=80,
            category=78,
        ),
    )
    result = engine.evaluate(parsed)
    assert result.overall >= 80
    assert "merchant" in result.fields
    assert engine.is_ready(result, parsed) is True

from datetime import date
from types import SimpleNamespace

from fastapi.testclient import TestClient

from capture.models import DraftStatus, DraftTransactionRecord
from capture.parsers.base import FieldConfidence, ParsedCapture
from capture.parsers.duplicate_detector import DuplicateMatch
from db.core import EXPENSE, TRANSFER_OUT


def build_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    from api.config import get_config

    get_config.cache_clear()

    from api.main import create_app

    return TestClient(create_app())


def auth_header(vault_id="4"):
    from api.security import create_access_token

    token, _expires_at = create_access_token(
        SimpleNamespace(
            id=vault_id,
            name="Karuna",
            vault_type="Individual",
            is_admin=False,
        )
    )
    return {"Authorization": f"Bearer {token}"}


def sample_draft(**overrides):
    base = DraftTransactionRecord(
        id=11,
        vault_id=4,
        raw_text="HDFC Bank: Rs.450.00 debited from a/c XX1234 to VPA swiggy@ybl",
        transaction_type=EXPENSE,
        merchant="Swiggy",
        amount=450.0,
        currency="INR",
        account_name="HDFC Salary",
        account_id=1,
        category_name="Food & Dining",
        category_id=2,
        date="2026-08-08",
        notes="Swiggy",
        confidence={
            "overall": 88,
            "fields": {
                "amount": 100,
                "merchant": 92,
                "transactionType": 88,
                "date": 90,
                "account": 75,
                "category": 78,
            },
        },
        status=DraftStatus.READY_TO_APPROVE.value,
        created_at="2026-08-08T10:00:00+00:00",
        updated_at="2026-08-08T10:00:00+00:00",
        duplicate=False,
        existing_transaction_id=None,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_parse_endpoint_returns_draft_transaction(monkeypatch):
    client = build_client(monkeypatch)

    preview = sample_draft(id=None, status=DraftStatus.NEEDS_REVIEW.value)

    monkeypatch.setattr(
        "capture.capture_router._service.parse",
        lambda vault_id, request: preview,
    )

    response = client.post(
        "/api/capture/parse",
        headers=auth_header(),
        json={
            "rawText": "HDFC Bank: Rs.450.00 debited from a/c XX1234 to VPA swiggy@ybl"
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert "draftTransaction" in body
    draft = body["draftTransaction"]
    assert draft["amount"] == 450.0
    assert draft["merchant"] == "Swiggy"
    assert draft["confidence"]["overall"] == 88
    assert draft["confidence"]["fields"]["amount"] == 100


def test_create_draft_and_inbox(monkeypatch):
    client = build_client(monkeypatch)
    created = sample_draft()

    monkeypatch.setattr(
        "capture.capture_router._service.create_draft",
        lambda vault_id, request: created,
    )
    monkeypatch.setattr(
        "capture.capture_router._service.inbox",
        lambda vault_id: {
            "needs_review": [],
            "ready": [created],
            "failed": [],
        },
    )

    create_response = client.post(
        "/api/capture/drafts",
        headers=auth_header(),
        json={"rawText": created.raw_text},
    )
    assert create_response.status_code == 200
    assert create_response.json()["draftTransaction"]["id"] == 11
    assert create_response.json()["draftTransaction"]["status"] == "READY_TO_APPROVE"

    inbox_response = client.get("/api/capture/inbox", headers=auth_header())
    assert inbox_response.status_code == 200
    inbox = inbox_response.json()
    assert len(inbox["ready"]) == 1
    assert inbox["needsReview"] == []
    assert inbox["failed"] == []


def test_approve_draft_creates_transaction(monkeypatch):
    client = build_client(monkeypatch)
    approved = sample_draft(status=DraftStatus.APPROVED.value, approved_at="2026-08-08T11:00:00+00:00")

    monkeypatch.setattr(
        "capture.capture_router.require_account",
        lambda account_id, vault_id: None,
    )
    monkeypatch.setattr(
        "capture.capture_router.require_category",
        lambda category_id, vault_id: None,
    )
    monkeypatch.setattr(
        "capture.capture_router._service.approve_draft",
        lambda vault_id, draft_id, request: (99, approved),
    )

    response = client.post(
        "/api/capture/drafts/11/approve",
        headers=auth_header(),
        json={"accountId": 1, "categoryId": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["transactionId"] == 99
    assert body["draftTransaction"]["status"] == "APPROVED"


def test_delete_draft_soft_deletes(monkeypatch):
    client = build_client(monkeypatch)
    deleted = sample_draft(status=DraftStatus.DELETED.value)

    monkeypatch.setattr(
        "capture.capture_router._service.delete_draft",
        lambda vault_id, draft_id: deleted,
    )

    response = client.delete("/api/capture/drafts/11", headers=auth_header())
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_duplicate_detection_flags_but_does_not_reject(monkeypatch):
    from capture.capture_service import CaptureService

    service = CaptureService()
    parsed = ParsedCapture(
        raw_text="paid swiggy",
        amount=450.0,
        merchant="Swiggy",
        transaction_type=EXPENSE,
        date=date(2026, 8, 8),
        field_confidence=FieldConfidence(amount=100, merchant=90, transaction_type=88, date=90),
    )

    monkeypatch.setattr(
        service.duplicate_detector,
        "find_duplicate",
        lambda **kwargs: DuplicateMatch(duplicate=True, existing_transaction_id=55),
    )
    monkeypatch.setattr(
        "capture.capture_service.resolve_account_for_vault",
        lambda vault_id, account_name, account_hint: (1, "HDFC", 80),
    )
    monkeypatch.setattr(
        "capture.capture_service.resolve_category_for_vault",
        lambda vault_id, category_name, transaction_type: (2, category_name, 90),
    )
    monkeypatch.setattr(
        service.category_suggester,
        "suggest",
        lambda merchant, transaction_type, raw_text="": ("Food & Dining", 78),
    )

    draft = service._build_draft_preview(4, parsed)
    assert draft.duplicate is True
    assert draft.existing_transaction_id == 55
    assert draft.status != DraftStatus.FAILED.value


def test_wallet_funding_stays_transfer_in_service_preview(monkeypatch):
    from capture.capture_service import CaptureService
    from capture.schemas import CaptureParseRequest

    service = CaptureService()

    monkeypatch.setattr(
        "capture.capture_service.resolve_account_for_vault",
        lambda vault_id, account_name, account_hint: (1, "HDFC", 80),
    )
    monkeypatch.setattr(
        "capture.capture_service.resolve_category_for_vault",
        lambda vault_id, category_name, transaction_type: (3, "Transfer", 95),
    )
    monkeypatch.setattr(
        service.duplicate_detector,
        "find_duplicate",
        lambda **kwargs: DuplicateMatch(duplicate=False),
    )

    draft = service.parse(
        4,
        CaptureParseRequest(
            rawText="INR 500.00 transferred to Paytm Wallet from a/c XX9876 on 08/08/2026."
        ),
    )

    assert draft.transaction_type == TRANSFER_OUT
    assert draft.category_name == "Transfer"

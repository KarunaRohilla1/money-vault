from __future__ import annotations

from datetime import date
from typing import Optional

from db.core import EXPENSE, INCOME, TRANSFER_IN, TRANSFER_OUT
from db.transactions import add_transaction
from capture.models import (
    DraftStatus,
    DraftTransactionRecord,
    default_category_id,
    get_draft_by_id,
    insert_draft,
    list_inbox_drafts,
    mark_draft_approved,
    resolve_account_for_vault,
    resolve_category_for_vault,
    soft_delete_draft,
)
from capture.parsers import get_parser
from capture.parsers.base import ParsedCapture
from capture.parsers.category_suggester import CategorySuggester
from capture.parsers.confidence_engine import ConfidenceEngine
from capture.parsers.duplicate_detector import DuplicateDetector, DuplicateMatch
from capture.schemas import (
    CaptureApproveRequest,
    CaptureDraftCreateRequest,
    CaptureParseRequest,
    DraftTransactionResponse,
)


VALID_TRANSACTION_TYPES = {EXPENSE, INCOME, TRANSFER_IN, TRANSFER_OUT}


class CaptureServiceError(ValueError):
    pass


class CaptureService:
    def __init__(
        self,
        category_suggester: Optional[CategorySuggester] = None,
        confidence_engine: Optional[ConfidenceEngine] = None,
        duplicate_detector: Optional[DuplicateDetector] = None,
    ):
        self.category_suggester = category_suggester or CategorySuggester()
        self.confidence_engine = confidence_engine or ConfidenceEngine()
        self.duplicate_detector = duplicate_detector or DuplicateDetector()

    def parse(
        self,
        vault_id: int,
        request: CaptureParseRequest,
    ) -> DraftTransactionRecord:
        parsed = self._parse_raw(request.raw_text, request.source)
        return self._build_draft_preview(vault_id, parsed)

    def create_draft(
        self,
        vault_id: int,
        request: CaptureDraftCreateRequest,
    ) -> DraftTransactionRecord:
        parsed = self._parse_raw(request.raw_text, request.source)
        preview = self._build_draft_preview(vault_id, parsed)
        preview = self._apply_overrides(preview, request)

        return insert_draft(
            vault_id=vault_id,
            raw_text=preview.raw_text,
            transaction_type=preview.transaction_type,
            merchant=preview.merchant,
            amount=preview.amount,
            currency=preview.currency,
            account_name=preview.account_name,
            account_id=preview.account_id,
            category_name=preview.category_name,
            category_id=preview.category_id,
            txn_date=preview.date,
            notes=preview.notes,
            confidence=preview.confidence,
            status=preview.status,
        )

    def inbox(self, vault_id: int) -> dict[str, list[DraftTransactionRecord]]:
        drafts = list_inbox_drafts(vault_id)
        buckets = {
            "needs_review": [],
            "ready": [],
            "failed": [],
        }
        for draft in drafts:
            if draft.status == DraftStatus.NEEDS_REVIEW.value:
                buckets["needs_review"].append(draft)
            elif draft.status == DraftStatus.READY_TO_APPROVE.value:
                buckets["ready"].append(draft)
            elif draft.status == DraftStatus.FAILED.value:
                buckets["failed"].append(draft)
        return buckets

    def delete_draft(self, vault_id: int, draft_id: int) -> DraftTransactionRecord:
        deleted = soft_delete_draft(draft_id, vault_id)
        if deleted is None:
            raise CaptureServiceError("Draft transaction not found.")
        return deleted

    def approve_draft(
        self,
        vault_id: int,
        draft_id: int,
        request: Optional[CaptureApproveRequest] = None,
    ) -> tuple[int, DraftTransactionRecord]:
        draft = get_draft_by_id(draft_id, vault_id)
        if draft is None or draft.status in (
            DraftStatus.DELETED.value,
            DraftStatus.APPROVED.value,
            DraftStatus.FAILED.value,
        ):
            raise CaptureServiceError("Draft transaction not found or not approvable.")

        request = request or CaptureApproveRequest()

        amount = request.amount if request.amount is not None else draft.amount
        txn_type = request.transaction_type or draft.transaction_type
        txn_date = request.date or draft.date or date.today().isoformat()
        account_id = request.account_id if request.account_id is not None else draft.account_id
        category_id = request.category_id if request.category_id is not None else draft.category_id
        merchant = request.merchant if request.merchant is not None else draft.merchant
        notes = request.notes if request.notes is not None else (draft.notes or merchant or "")

        if amount is None or amount <= 0:
            raise CaptureServiceError("A positive amount is required to approve.")
        if not txn_type or txn_type not in VALID_TRANSACTION_TYPES:
            raise CaptureServiceError("A valid transaction type is required to approve.")
        if account_id is None:
            raise CaptureServiceError("An account is required to approve.")

        if category_id is None:
            category_id = default_category_id(vault_id)
        if category_id is None:
            raise CaptureServiceError("A category is required to approve.")

        try:
            transaction_id = add_transaction(
                vault_id,
                account_id,
                txn_date,
                float(amount),
                category_id,
                txn_type,
                notes or "",
            )
        except ValueError as error:
            raise CaptureServiceError(str(error)) from error

        approved = mark_draft_approved(draft_id, vault_id)
        if approved is None:
            raise CaptureServiceError("Draft could not be marked approved.")

        return int(transaction_id), approved

    def to_response(self, draft: DraftTransactionRecord) -> DraftTransactionResponse:
        return DraftTransactionResponse(
            id=draft.id,
            vaultId=draft.vault_id,
            rawText=draft.raw_text,
            transactionType=draft.transaction_type,
            merchant=draft.merchant,
            amount=draft.amount,
            currency=draft.currency,
            accountName=draft.account_name,
            accountId=draft.account_id,
            categoryName=draft.category_name,
            categoryId=draft.category_id,
            date=draft.date,
            notes=draft.notes,
            confidence=draft.confidence,
            status=draft.status,
            createdAt=draft.created_at,
            updatedAt=draft.updated_at,
            approvedAt=draft.approved_at,
            duplicate=draft.duplicate,
            existingTransactionId=draft.existing_transaction_id,
        )

    def _parse_raw(self, raw_text: str, source: Optional[str]) -> ParsedCapture:
        try:
            parser = get_parser(source)
        except ValueError as error:
            raise CaptureServiceError(str(error)) from error
        return parser.parse(raw_text)

    def _build_draft_preview(
        self,
        vault_id: int,
        parsed: ParsedCapture,
    ) -> DraftTransactionRecord:
        category_name, category_confidence = self.category_suggester.suggest(
            parsed.merchant,
            parsed.transaction_type,
            parsed.raw_text,
        )
        parsed.category_name = category_name
        parsed.field_confidence.category = category_confidence

        account_id, account_name, account_confidence = resolve_account_for_vault(
            vault_id,
            parsed.account_name,
            parsed.account_hint,
        )
        if account_confidence:
            parsed.field_confidence.account = max(
                parsed.field_confidence.account,
                account_confidence,
            )
        if account_name:
            parsed.account_name = account_name

        category_id = None
        if category_name:
            category_id, resolved_category_name, resolved_confidence = resolve_category_for_vault(
                vault_id,
                category_name,
                parsed.transaction_type,
            )
            if resolved_category_name:
                category_name = resolved_category_name
            parsed.field_confidence.category = max(
                parsed.field_confidence.category,
                resolved_confidence,
            )

        confidence = self.confidence_engine.evaluate(parsed)
        duplicate = self._detect_duplicate(vault_id, parsed)
        status = self._status_for(parsed, confidence)

        return DraftTransactionRecord(
            id=None,
            vault_id=vault_id,
            raw_text=parsed.raw_text,
            transaction_type=parsed.transaction_type,
            merchant=parsed.merchant,
            amount=parsed.amount,
            currency=parsed.currency or "INR",
            account_name=parsed.account_name,
            account_id=account_id,
            category_name=category_name,
            category_id=category_id,
            date=parsed.date.isoformat() if parsed.date else None,
            notes=parsed.notes,
            confidence=confidence.as_dict(),
            status=status,
            duplicate=duplicate.duplicate,
            existing_transaction_id=duplicate.existing_transaction_id,
        )

    def _detect_duplicate(self, vault_id: int, parsed: ParsedCapture) -> DuplicateMatch:
        return self.duplicate_detector.find_duplicate(
            vault_id=vault_id,
            amount=parsed.amount,
            merchant=parsed.merchant,
            transaction_date=parsed.date,
        )

    def _status_for(self, parsed: ParsedCapture, confidence) -> str:
        if parsed.parse_failed or parsed.amount is None:
            return DraftStatus.FAILED.value
        if self.confidence_engine.is_ready(confidence, parsed):
            return DraftStatus.READY_TO_APPROVE.value
        return DraftStatus.NEEDS_REVIEW.value

    def _apply_overrides(
        self,
        draft: DraftTransactionRecord,
        request: CaptureDraftCreateRequest,
    ) -> DraftTransactionRecord:
        if request.transaction_type is not None:
            draft.transaction_type = request.transaction_type
        if request.merchant is not None:
            draft.merchant = request.merchant
        if request.amount is not None:
            draft.amount = request.amount
        if request.currency is not None:
            draft.currency = request.currency
        if request.account_name is not None:
            draft.account_name = request.account_name
        if request.account_id is not None:
            draft.account_id = request.account_id
        if request.category_name is not None:
            draft.category_name = request.category_name
        if request.category_id is not None:
            draft.category_id = request.category_id
        if request.date is not None:
            draft.date = request.date
        if request.notes is not None:
            draft.notes = request.notes

        # Recompute status after manual overrides.
        if draft.amount is None:
            draft.status = DraftStatus.FAILED.value
        elif draft.transaction_type and draft.amount > 0:
            overall = int((draft.confidence or {}).get("overall") or 0)
            if overall >= ConfidenceEngine.READY_THRESHOLD and draft.account_id is not None:
                draft.status = DraftStatus.READY_TO_APPROVE.value
            elif draft.status == DraftStatus.FAILED.value:
                draft.status = DraftStatus.NEEDS_REVIEW.value

        return draft

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class CaptureParseRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    raw_text: str = Field(alias="rawText", min_length=1)
    source: Optional[str] = None


class CaptureDraftCreateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    raw_text: str = Field(alias="rawText", min_length=1)
    source: Optional[str] = None
    transaction_type: Optional[str] = Field(default=None, alias="transactionType")
    merchant: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    account_name: Optional[str] = Field(default=None, alias="accountName")
    account_id: Optional[int] = Field(default=None, alias="accountId")
    category_name: Optional[str] = Field(default=None, alias="categoryName")
    category_id: Optional[int] = Field(default=None, alias="categoryId")
    date: Optional[str] = None
    notes: Optional[str] = None


class CaptureApproveRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    account_id: Optional[int] = Field(default=None, alias="accountId")
    category_id: Optional[int] = Field(default=None, alias="categoryId")
    transaction_type: Optional[str] = Field(default=None, alias="transactionType")
    amount: Optional[float] = None
    date: Optional[str] = None
    notes: Optional[str] = None
    merchant: Optional[str] = None


class DraftTransactionResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: Optional[int] = None
    vault_id: int = Field(alias="vaultId")
    raw_text: str = Field(alias="rawText")
    transaction_type: Optional[str] = Field(default=None, alias="transactionType")
    merchant: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "INR"
    account_name: Optional[str] = Field(default=None, alias="accountName")
    account_id: Optional[int] = Field(default=None, alias="accountId")
    category_name: Optional[str] = Field(default=None, alias="categoryName")
    category_id: Optional[int] = Field(default=None, alias="categoryId")
    date: Optional[str] = None
    notes: Optional[str] = None
    confidence: Dict[str, Any]
    status: str
    created_at: Optional[str] = Field(default=None, alias="createdAt")
    updated_at: Optional[str] = Field(default=None, alias="updatedAt")
    approved_at: Optional[str] = Field(default=None, alias="approvedAt")
    duplicate: bool = False
    existing_transaction_id: Optional[int] = Field(default=None, alias="existingTransactionId")


class CaptureParseResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    draft_transaction: DraftTransactionResponse = Field(alias="draftTransaction")


class CaptureDraftResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    draft_transaction: DraftTransactionResponse = Field(alias="draftTransaction")


class CaptureInboxResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    needs_review: List[DraftTransactionResponse] = Field(alias="needsReview")
    ready: List[DraftTransactionResponse] = Field(alias="ready")
    failed: List[DraftTransactionResponse] = Field(alias="failed")


class CaptureApproveResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    transaction_id: int = Field(alias="transactionId")
    draft_transaction: DraftTransactionResponse = Field(alias="draftTransaction")

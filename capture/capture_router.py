from fastapi import APIRouter, Depends

from api.dependencies import get_authenticated_vault
from api.resources import bad_request, int_vault_id, not_found, require_account, require_category
from api.schemas import SuccessResponse, VaultContext

from capture.capture_service import CaptureService, CaptureServiceError
from capture.schemas import (
    CaptureApproveRequest,
    CaptureApproveResponse,
    CaptureDraftCreateRequest,
    CaptureDraftResponse,
    CaptureInboxResponse,
    CaptureParseRequest,
    CaptureParseResponse,
)


router = APIRouter(prefix="/api/capture", tags=["capture"])
_service = CaptureService()


def get_capture_service() -> CaptureService:
    return _service


@router.post("/parse", response_model=CaptureParseResponse, response_model_by_alias=True)
def parse_message(
    request: CaptureParseRequest,
    vault: VaultContext = Depends(get_authenticated_vault),
    service: CaptureService = Depends(get_capture_service),
):
    try:
        draft = service.parse(int_vault_id(vault), request)
    except CaptureServiceError as error:
        raise bad_request(str(error)) from error

    return CaptureParseResponse(draftTransaction=service.to_response(draft))


@router.post("/drafts", response_model=CaptureDraftResponse, response_model_by_alias=True)
def create_draft(
    request: CaptureDraftCreateRequest,
    vault: VaultContext = Depends(get_authenticated_vault),
    service: CaptureService = Depends(get_capture_service),
):
    vault_id = int_vault_id(vault)
    if request.account_id is not None:
        require_account(request.account_id, vault_id)
    if request.category_id is not None:
        require_category(request.category_id, vault_id)

    try:
        draft = service.create_draft(vault_id, request)
    except CaptureServiceError as error:
        raise bad_request(str(error)) from error

    return CaptureDraftResponse(draftTransaction=service.to_response(draft))


@router.get("/inbox", response_model=CaptureInboxResponse, response_model_by_alias=True)
def capture_inbox(
    vault: VaultContext = Depends(get_authenticated_vault),
    service: CaptureService = Depends(get_capture_service),
):
    buckets = service.inbox(int_vault_id(vault))
    return CaptureInboxResponse(
        needsReview=[service.to_response(item) for item in buckets["needs_review"]],
        ready=[service.to_response(item) for item in buckets["ready"]],
        failed=[service.to_response(item) for item in buckets["failed"]],
    )


@router.post(
    "/drafts/{draft_id}/approve",
    response_model=CaptureApproveResponse,
    response_model_by_alias=True,
)
def approve_draft(
    draft_id: int,
    request: CaptureApproveRequest | None = None,
    vault: VaultContext = Depends(get_authenticated_vault),
    service: CaptureService = Depends(get_capture_service),
):
    vault_id = int_vault_id(vault)
    payload = request or CaptureApproveRequest()
    if payload.account_id is not None:
        require_account(payload.account_id, vault_id)
    if payload.category_id is not None:
        require_category(payload.category_id, vault_id)

    try:
        transaction_id, draft = service.approve_draft(vault_id, draft_id, payload)
    except CaptureServiceError as error:
        message = str(error)
        if "not found" in message.lower():
            raise not_found(message) from error
        raise bad_request(message) from error

    return CaptureApproveResponse(
        transactionId=transaction_id,
        draftTransaction=service.to_response(draft),
    )


@router.delete("/drafts/{draft_id}", response_model=SuccessResponse, response_model_by_alias=True)
def delete_draft(
    draft_id: int,
    vault: VaultContext = Depends(get_authenticated_vault),
    service: CaptureService = Depends(get_capture_service),
):
    try:
        service.delete_draft(int_vault_id(vault), draft_id)
    except CaptureServiceError as error:
        raise not_found(str(error)) from error

    return SuccessResponse()

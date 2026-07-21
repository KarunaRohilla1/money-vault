from fastapi import APIRouter, Depends

from api.dependencies import get_authenticated_vault
from api.resources import bad_request, int_vault_id, require_category
from api.schemas import (
    CategoryCreateRequest,
    CategoryResponse,
    CategoryUpdateRequest,
    SuccessResponse,
    VaultContext
)
from db.categories import (
    add_category,
    delete_category,
    get_categories,
    get_category_transaction_count,
    update_category
)


router = APIRouter(prefix="/api/categories", tags=["categories"])


def effective_category_vault_id(vault):
    if vault.vault_type == "Shared" and vault.authenticated_vault_id:
        return int(vault.authenticated_vault_id)
    return int_vault_id(vault)


def adapt_category(row, include_count=False):
    return CategoryResponse(
        id=int(row[0]),
        emoji=row[1] or "",
        name=row[2],
        categoryType=row[3],
        parentCategory=row[4],
        isSystem=bool(row[5]),
        transactionCount=get_category_transaction_count(row[0]) if include_count else None
    )


@router.get("", response_model=list[CategoryResponse], response_model_by_alias=True)
def list_categories(vault: VaultContext = Depends(get_authenticated_vault)):
    return [
        adapt_category(row)
        for row in get_categories(effective_category_vault_id(vault))
    ]


@router.post("", response_model=SuccessResponse, response_model_by_alias=True)
def create_category(request: CategoryCreateRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    try:
        add_category(
            int_vault_id(vault),
            request.name,
            request.emoji,
            request.category_type
        )
    except ValueError as error:
        raise bad_request(str(error)) from error

    return SuccessResponse()


@router.put("/{category_id}", response_model=SuccessResponse, response_model_by_alias=True)
def update_category_route(
    category_id: int,
    request: CategoryUpdateRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    require_category(
        category_id,
        int_vault_id(vault)
    )
    try:
        update_category(
            category_id,
            request.name,
            request.emoji,
            request.category_type
        )
    except ValueError as error:
        raise bad_request(str(error)) from error

    return SuccessResponse()


@router.delete("/{category_id}", response_model=SuccessResponse, response_model_by_alias=True)
def delete_category_route(category_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    require_category(
        category_id,
        int_vault_id(vault)
    )
    if get_category_transaction_count(category_id) > 0:
        raise bad_request("Category has transactions and cannot be deleted.")

    try:
        delete_category(category_id)
    except ValueError as error:
        raise bad_request(str(error)) from error

    return SuccessResponse()

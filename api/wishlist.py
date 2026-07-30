from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.dependencies import get_authenticated_vault
from api.resources import (
    bad_request,
    int_vault_id,
    require_account,
    require_wishlist_category,
    require_wishlist_item
)
from api.schemas import (
    SuccessResponse,
    VaultContext,
    WishlistCategoryRequest,
    WishlistCategoryReorderRequest,
    WishlistCategoryResponse,
    WishlistItemRequest,
    WishlistItemResponse,
    WishlistResponse,
    WishlistSummaryResponse
)
from db.wishlist import (
    add_wishlist_category,
    add_wishlist_item,
    delete_wishlist_category,
    delete_wishlist_item,
    get_wishlist_categories,
    get_wishlist_category,
    get_wishlist_items,
    get_wishlist_summary,
    reorder_wishlist_categories,
    update_wishlist_category,
    update_wishlist_item
)


router = APIRouter(prefix="/api/wishlist", tags=["wishlist"])


def number(value):
    return float(value or 0)


def adapt_category(row):
    return WishlistCategoryResponse(
        id=int(row[0]),
        vaultId=int(row[1]),
        name=row[2],
        icon=row[3] or "tag-outline",
        color=row[4] or "purple",
        sortOrder=int(row[5] or 0),
        itemCount=int(row[6] or 0) if len(row) > 6 else 0
    )


def adapt_item(row):
    estimated_cost = number(row[3])
    saved_amount = number(row[4])
    progress = round(saved_amount / estimated_cost * 100) if estimated_cost else 0
    return WishlistItemResponse(
        id=int(row[0]),
        name=row[1],
        category=row[2],
        estimatedCost=estimated_cost,
        savedAmount=saved_amount,
        targetDate=str(row[5]) if row[5] else None,
        accountId=int(row[6]) if row[6] is not None else None,
        accountName=row[7],
        imageUrl=row[8] or "",
        notes=row[9] or "",
        priority=(row[10] or "MEDIUM"),
        purchaseLink=row[11] or "",
        imageSource=row[12],
        createdAt=str(row[13]) if row[13] else None,
        categoryId=int(row[14]) if row[14] is not None else None,
        progressPercent=progress
    )


@router.get("", response_model=WishlistResponse, response_model_by_alias=True)
def wishlist(
    account_id: Optional[int] = Query(default=None, alias="accountId"),
    category: Optional[str] = None,
    date_filter: str = Query(default="All Dates", alias="dateFilter"),
    search: Optional[str] = None,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    summary = get_wishlist_summary(vault_id)
    return WishlistResponse(
        categories=[
            adapt_category(row)
            for row in get_wishlist_categories(vault_id)
        ],
        items=[
            adapt_item(row)
            for row in get_wishlist_items(
                vault_id,
                search=search,
                account_id=account_id,
                date_filter=date_filter,
                category=category
            )
        ],
        summary=WishlistSummaryResponse(
            totalItems=int(summary["total_items"]),
            totalCost=number(summary["total_cost"]),
            totalSaved=number(summary["total_saved"]),
            progress=int(summary["progress"])
        )
    )


@router.post("/categories", response_model=SuccessResponse, response_model_by_alias=True)
def create_category(request: WishlistCategoryRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    add_wishlist_category(
        int_vault_id(vault),
        request.name,
        icon=request.icon,
        color=request.color,
        sort_order=request.sort_order
    )
    return SuccessResponse()


@router.put("/categories/{category_id}", response_model=SuccessResponse, response_model_by_alias=True)
def update_category(
    category_id: int,
    request: WishlistCategoryRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    require_wishlist_category(
        category_id,
        vault_id
    )
    category = get_wishlist_category(category_id)
    try:
        update_wishlist_category(
            category_id,
            vault_id,
            category[2],
            request.name,
            icon=request.icon,
            color=request.color,
            sort_order=request.sort_order
        )
    except ValueError as error:
        raise bad_request(str(error)) from error
    return SuccessResponse()




@router.put("/categories/reorder", response_model=SuccessResponse, response_model_by_alias=True)
def reorder_categories(request: WishlistCategoryReorderRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = int_vault_id(vault)
    reorder_wishlist_categories(
        vault_id,
        [
            {"id": item.id, "sort_order": item.sort_order}
            for item in request.categories
        ]
    )
    return SuccessResponse()


@router.delete("/categories/{category_id}", response_model=SuccessResponse, response_model_by_alias=True)
def delete_category(
    category_id: int,
    fallback: str = "General",
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    require_wishlist_category(
        category_id,
        vault_id
    )
    category = get_wishlist_category(category_id)
    delete_wishlist_category(
        category_id,
        vault_id,
        category[2],
        fallback=fallback
    )
    return SuccessResponse()


@router.post("/items", response_model=SuccessResponse, response_model_by_alias=True)
def create_item(request: WishlistItemRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = int_vault_id(vault)
    if request.account_id is not None:
        require_account(
            request.account_id,
            vault_id
        )
    add_wishlist_item(
        vault_id,
        request.name,
        request.category,
        request.estimated_cost,
        saved_amount=request.saved_amount,
        target_date=request.target_date,
        account_id=request.account_id,
        image_url=request.image_url,
        notes=request.notes,
        category_id=request.category_id,
        priority=request.priority,
        purchase_link=request.purchase_link,
        image_source=request.image_source
    )
    return SuccessResponse()


@router.put("/items/{item_id}", response_model=SuccessResponse, response_model_by_alias=True)
def update_item(
    item_id: int,
    request: WishlistItemRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    require_wishlist_item(
        item_id,
        vault_id
    )
    if request.account_id is not None:
        require_account(
            request.account_id,
            vault_id
        )
    update_wishlist_item(
        item_id,
        request.name,
        request.category,
        request.estimated_cost,
        saved_amount=request.saved_amount,
        target_date=request.target_date,
        account_id=request.account_id,
        image_url=request.image_url,
        notes=request.notes,
        category_id=request.category_id,
        priority=request.priority,
        purchase_link=request.purchase_link,
        image_source=request.image_source
    )
    return SuccessResponse()


@router.delete("/items/{item_id}", response_model=SuccessResponse, response_model_by_alias=True)
def delete_item(item_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    require_wishlist_item(
        item_id,
        int_vault_id(vault)
    )
    delete_wishlist_item(item_id)
    return SuccessResponse()

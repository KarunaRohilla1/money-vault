from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    vault_name: str = Field(alias="vaultName", min_length=1)
    pin: str = Field(min_length=1)


class VaultContext(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    is_admin: bool = Field(alias="isAdmin")
    vault_type: str = Field(alias="vaultType")


class LoginResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    token: str
    vault: VaultContext
    expires_at: Optional[str] = Field(default=None, alias="expiresAt")


class FinancialCycleResponse(BaseModel):
    id: int
    start_date: str = Field(alias="startDate")
    end_date: str = Field(alias="endDate")
    display_name: str = Field(alias="displayName")
    status: str
    days_completed: int = Field(alias="daysCompleted")
    days_remaining: int = Field(alias="daysRemaining")
    total_days: int = Field(alias="totalDays")
    progress_percent: int = Field(alias="progressPercent")


class PrimaryAccountResponse(BaseModel):
    name: str
    balance: float


class SettlementResponse(BaseModel):
    label: str
    amount: float
    direction: str
    receivable: float
    payable: float
    net: float
    items: List[Dict[str, Any]]


class RecentActivityItem(BaseModel):
    id: int
    date: str
    account_name: Optional[str] = Field(default=None, alias="accountName")
    category_name: str = Field(alias="categoryName")
    amount: float
    transaction_type: str = Field(alias="transactionType")
    notes: Optional[str] = None


class CategorySpendItem(BaseModel):
    name: str
    amount: float


class SetupStatusResponse(BaseModel):
    accounts: int
    income_templates: int = Field(alias="incomeTemplates")
    commitments: int
    has_vault_login: bool = Field(alias="hasVaultLogin")
    has_cycle_setting: bool = Field(alias="hasCycleSetting")
    has_savings_goal: bool = Field(alias="hasSavingsGoal")
    has_accounts: bool = Field(alias="hasAccounts")
    has_income_templates: bool = Field(alias="hasIncomeTemplates")
    has_commitments: bool = Field(alias="hasCommitments")
    is_complete: bool = Field(alias="isComplete")


class DashboardDataResponse(BaseModel):
    cycle: FinancialCycleResponse
    safe_to_spend: float = Field(alias="safeToSpend")
    primary_account: PrimaryAccountResponse = Field(alias="primaryAccount")
    expenses_this_cycle: float = Field(alias="expensesThisCycle")
    remaining_commitments: float = Field(alias="remainingCommitments")
    credit_card_due: float = Field(alias="creditCardDue")
    settlement: SettlementResponse
    recent_activity: List[RecentActivityItem] = Field(alias="recentActivity")
    spending_by_category: List[CategorySpendItem] = Field(alias="spendingByCategory")
    setup: SetupStatusResponse
    summary: Dict[str, Any]


class DashboardResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    generated_at: datetime = Field(alias="generatedAt")
    vault: VaultContext
    data: DashboardDataResponse


class HealthResponse(BaseModel):
    status: str


class AccountResponse(BaseModel):
    id: int
    name: str
    type: str
    opening_balance: float = Field(alias="openingBalance")
    is_primary: bool = Field(alias="isPrimary")
    balance: Optional[float] = None


class AccountCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    opening_balance: float = Field(alias="openingBalance")
    is_primary: bool = Field(default=False, alias="isPrimary")


class AccountUpdateRequest(AccountCreateRequest):
    pass


class CategoryResponse(BaseModel):
    id: int
    emoji: str
    name: str
    category_type: str = Field(alias="categoryType")
    parent_category: Optional[str] = Field(default=None, alias="parentCategory")
    is_system: bool = Field(alias="isSystem")
    transaction_count: Optional[int] = Field(default=None, alias="transactionCount")


class CategoryCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    emoji: str = Field(min_length=1)
    category_type: str = Field(alias="categoryType", min_length=1)


class CategoryUpdateRequest(CategoryCreateRequest):
    pass


class TransactionResponse(BaseModel):
    id: int
    date: str
    account_name: Optional[str] = Field(default=None, alias="accountName")
    category_name: str = Field(alias="categoryName")
    amount: float
    transaction_type: str = Field(alias="transactionType")
    notes: Optional[str] = None
    transfer_group_id: Optional[str] = Field(default=None, alias="transferGroupId")


class TransactionDetailResponse(BaseModel):
    id: int
    account_id: int = Field(alias="accountId")
    category_id: int = Field(alias="categoryId")
    date: str
    amount: float
    transaction_type: str = Field(alias="transactionType")
    notes: Optional[str] = None
    beneficiary_vault_id: Optional[int] = Field(default=None, alias="beneficiaryVaultId")
    allocation_method: Optional[str] = Field(default=None, alias="allocationMethod")


class TransactionCreateRequest(BaseModel):
    account_id: int = Field(alias="accountId")
    category_id: int = Field(alias="categoryId")
    date: str = Field(min_length=1)
    amount: float = Field(gt=0)
    transaction_type: str = Field(alias="transactionType", min_length=1)
    notes: str = ""
    beneficiary_vault_id: Optional[int] = Field(default=None, alias="beneficiaryVaultId")
    allocation_method: Optional[str] = Field(default=None, alias="allocationMethod")
    participant_vaults: Optional[List[int]] = Field(default=None, alias="participantVaults")
    percentage_allocations: Optional[Dict[str, float]] = Field(default=None, alias="percentageAllocations")
    amount_allocations: Optional[Dict[str, float]] = Field(default=None, alias="amountAllocations")


class TransactionUpdateRequest(TransactionCreateRequest):
    pass


class TransferResponse(BaseModel):
    transfer_group_id: str = Field(alias="transferGroupId")
    date: str
    from_account_id: int = Field(alias="fromAccountId")
    from_account_name: str = Field(alias="fromAccountName")
    to_account_id: int = Field(alias="toAccountId")
    to_account_name: str = Field(alias="toAccountName")
    amount: float
    notes: Optional[str] = None


class TransferDetailResponse(BaseModel):
    transfer_group_id: str = Field(alias="transferGroupId")
    vault_id: int = Field(alias="vaultId")
    date: str
    from_account_id: int = Field(alias="fromAccountId")
    to_account_id: int = Field(alias="toAccountId")
    amount: float
    notes: Optional[str] = None


class TransferCreateRequest(BaseModel):
    from_account_id: int = Field(alias="fromAccountId")
    to_account_id: int = Field(alias="toAccountId")
    date: str = Field(min_length=1)
    amount: float = Field(gt=0)
    notes: str = ""


class TransferUpdateRequest(TransferCreateRequest):
    pass


class SuccessResponse(BaseModel):
    status: str = "ok"


class PlanningCycleResponse(BaseModel):
    id: int
    vault_id: int = Field(alias="vaultId")
    start_date: str = Field(alias="startDate")
    end_date: str = Field(alias="endDate")
    start_month: int = Field(alias="startMonth")
    start_year: int = Field(alias="startYear")
    status: str


class PlanningTotalsResponse(BaseModel):
    income: float
    planned_commitments: float = Field(alias="plannedCommitments")
    remaining_commitments: float = Field(alias="remainingCommitments")
    income_planned: float = Field(alias="incomePlanned")
    income_received: float = Field(alias="incomeReceived")
    commitments_planned: float = Field(alias="commitmentsPlanned")
    commitments_completed: float = Field(alias="commitmentsCompleted")
    expenses: float
    savings_goal: float = Field(alias="savingsGoal")
    projected_savings: float = Field(alias="projectedSavings")


class PlanningStatusResponse(BaseModel):
    actual_amount: Optional[float] = Field(default=None, alias="actualAmount")
    status: str
    notes: Optional[str] = None


class CommitmentResponse(BaseModel):
    account_id: Optional[int] = Field(default=None, alias="accountId")
    account_name: Optional[str] = Field(default=None, alias="accountName")
    amount: float
    due_day: int = Field(alias="dueDay")
    id: int
    name: str
    status: PlanningStatusResponse


class IncomeTemplateResponse(BaseModel):
    account_id: Optional[int] = Field(default=None, alias="accountId")
    account_name: Optional[str] = Field(default=None, alias="accountName")
    amount: float
    due_day: int = Field(alias="dueDay")
    id: int
    name: str
    status: PlanningStatusResponse


class PlanningResponse(BaseModel):
    cycle: PlanningCycleResponse
    totals: PlanningTotalsResponse
    commitments: List[CommitmentResponse]
    income_templates: List[IncomeTemplateResponse] = Field(alias="incomeTemplates")


class PlanningItemRequest(BaseModel):
    account_id: int = Field(alias="accountId")
    amount: float = Field(gt=0)
    due_day: int = Field(alias="dueDay", ge=1, le=31)
    name: str = Field(min_length=1)


class PlanningStatusRequest(BaseModel):
    actual_amount: Optional[float] = Field(default=None, alias="actualAmount")
    month: int = Field(ge=1, le=12)
    notes: str = ""
    status: str = Field(min_length=1)
    year: int = Field(ge=2000, le=2100)


class WishlistCategoryResponse(BaseModel):
    id: int
    vault_id: int = Field(alias="vaultId")
    name: str


class WishlistCategoryRequest(BaseModel):
    fallback: str = "General"
    name: str = Field(min_length=1)


class WishlistItemResponse(BaseModel):
    account_id: Optional[int] = Field(default=None, alias="accountId")
    account_name: Optional[str] = Field(default=None, alias="accountName")
    category: str
    estimated_cost: float = Field(alias="estimatedCost")
    id: int
    image_url: str = Field(alias="imageUrl")
    name: str
    notes: str
    progress_percent: int = Field(alias="progressPercent")
    saved_amount: float = Field(alias="savedAmount")
    target_date: Optional[str] = Field(default=None, alias="targetDate")


class WishlistSummaryResponse(BaseModel):
    total_items: int = Field(alias="totalItems")
    total_cost: float = Field(alias="totalCost")
    total_saved: float = Field(alias="totalSaved")
    progress: int


class WishlistResponse(BaseModel):
    categories: List[WishlistCategoryResponse]
    items: List[WishlistItemResponse]
    summary: WishlistSummaryResponse


class WishlistItemRequest(BaseModel):
    account_id: Optional[int] = Field(default=None, alias="accountId")
    category: str = Field(min_length=1)
    estimated_cost: float = Field(alias="estimatedCost", gt=0)
    image_url: str = Field(default="", alias="imageUrl")
    name: str = Field(min_length=1)
    notes: str = ""
    saved_amount: float = Field(default=0, alias="savedAmount", ge=0)
    target_date: Optional[str] = Field(default=None, alias="targetDate")


class ReportsResponse(BaseModel):
    category_breakdown: List[Dict[str, Any]] = Field(alias="categoryBreakdown")
    generated_at: datetime = Field(alias="generatedAt")
    monthly_trend: List[Dict[str, Any]] = Field(alias="monthlyTrend")
    period: Dict[str, Any]
    summary: Dict[str, Any]


class VaultSummaryResponse(BaseModel):
    id: int
    is_admin: bool = Field(alias="isAdmin")
    name: str
    vault_type: str = Field(alias="vaultType")


class SettingsResponse(BaseModel):
    current_vault: VaultSummaryResponse = Field(alias="currentVault")
    accessible_vaults: List[VaultSummaryResponse] = Field(alias="accessibleVaults")
    cycle_start_day: int = Field(alias="cycleStartDay")
    monthly_savings_goal: float = Field(alias="monthlySavingsGoal")


class SettingsUpdateRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    vault_name: Optional[str] = Field(default=None, alias="vaultName")
    cycle_start_day: Optional[int] = Field(default=None, alias="cycleStartDay", ge=1, le=28)
    monthly_savings_goal: Optional[float] = Field(default=None, alias="monthlySavingsGoal", ge=0)


class SharedBillRequest(BaseModel):
    amount: float = Field(gt=0)
    category_id: Optional[int] = Field(default=None, alias="categoryId")
    due_day: int = Field(alias="dueDay", ge=1, le=31)
    end_date: Optional[str] = Field(default=None, alias="endDate")
    frequency: str = "Monthly"
    is_active: bool = Field(default=True, alias="isActive")
    name: str = Field(min_length=1)
    notes: str = ""
    shared_vault_id: int = Field(alias="sharedVaultId")
    start_date: Optional[str] = Field(default=None, alias="startDate")


class SharedBillPaymentRequest(BaseModel):
    notes: str = ""
    payer_vault_id: int = Field(alias="payerVaultId")
    payment_date: str = Field(alias="paymentDate", min_length=1)


class SharedSettlementRequest(BaseModel):
    amount: float = Field(gt=0)
    from_account_id: int = Field(alias="fromAccountId")
    from_vault_id: int = Field(alias="fromVaultId")
    settlement_date: str = Field(alias="settlementDate", min_length=1)
    shared_vault_id: int = Field(alias="sharedVaultId")
    to_account_id: int = Field(alias="toAccountId")
    to_vault_id: int = Field(alias="toVaultId")


class SharedPageResponse(BaseModel):
    data: Dict[str, Any]

from fastapi import APIRouter, Depends

from api.dependencies import get_authenticated_vault
from api.resources import (
    bad_request,
    int_vault_id,
    require_account,
    require_commitment,
    require_income_template
)
from api.schemas import (
    CommitmentResponse,
    IncomeTemplateResponse,
    PlanningCycleResponse,
    PlanningItemRequest,
    PlanningResponse,
    PlanningStatusRequest,
    PlanningStatusResponse,
    PlanningTotalsResponse,
    SuccessResponse,
    VaultContext
)
from db.financial_cycles import close_active_cycle, get_current_cycle
from db.planning import (
    add_commitment,
    add_income_template,
    delete_commitment,
    delete_income_template,
    get_commitments,
    get_cycle_planning_summary,
    get_income_templates,
    get_monthly_planning_totals,
    get_planning_activity_statuses,
    save_income_status,
    save_obligation_status,
    update_commitment,
    update_income_template
)


router = APIRouter(prefix="/api/planning", tags=["planning"])

INCOME_STATUSES = {"PENDING", "RECEIVED", "CANCELLED"}
COMMITMENT_STATUSES = {"PENDING", "PAID", "CANCELLED", "CARRIED_FORWARD"}


def number(value):
    return float(value or 0)


def adapt_cycle(cycle):
    return PlanningCycleResponse(
        id=int(cycle.id),
        vaultId=int(cycle.vault_id),
        startDate=cycle.start_iso,
        endDate=cycle.end_iso,
        startMonth=int(cycle.start_month),
        startYear=int(cycle.start_year),
        status=cycle.status
    )


def adapt_status(status):
    if not status:
        return PlanningStatusResponse(
            actualAmount=None,
            status="PENDING",
            notes=None
        )

    return PlanningStatusResponse(
        actualAmount=number(status[0]) if status[0] is not None else None,
        status=status[1],
        notes=status[2]
    )


def adapt_commitment(row, status):
    return CommitmentResponse(
        id=int(row[0]),
        name=row[1],
        amount=number(row[2]),
        dueDay=int(row[3]),
        accountName=row[4],
        accountId=int(row[5]) if row[5] is not None else None,
        status=adapt_status(status)
    )


def adapt_income_template(row, status):
    return IncomeTemplateResponse(
        id=int(row[0]),
        name=row[1],
        amount=number(row[2]),
        dueDay=int(row[3]),
        accountName=row[4],
        accountId=int(row[5]) if row[5] is not None else None,
        status=adapt_status(status)
    )


def build_planning(vault_id):
    cycle = get_current_cycle(vault_id)
    month = cycle.start_month
    year = cycle.start_year
    statuses = get_planning_activity_statuses(
        vault_id,
        month,
        year
    )
    monthly_totals = get_monthly_planning_totals(
        vault_id,
        month,
        year
    )
    cycle_summary = get_cycle_planning_summary(
        vault_id,
        month,
        year,
        cycle.start_iso,
        cycle.end_iso
    )

    return PlanningResponse(
        cycle=adapt_cycle(cycle),
        totals=PlanningTotalsResponse(
            income=number(monthly_totals["income"]),
            plannedCommitments=number(monthly_totals["planned_commitments"]),
            remainingCommitments=number(monthly_totals["remaining_commitments"]),
            incomePlanned=number(cycle_summary["income_planned"]),
            incomeReceived=number(cycle_summary["income_received"]),
            commitmentsPlanned=number(cycle_summary["commitments_planned"]),
            commitmentsCompleted=number(cycle_summary["commitments_completed"]),
            expenses=number(cycle_summary["expenses"]),
            savingsGoal=number(cycle_summary["savings_goal"]),
            projectedSavings=number(cycle_summary["projected_savings"])
        ),
        commitments=[
            adapt_commitment(
                row,
                statuses.get(("commitment", row[0]))
            )
            for row in get_commitments(vault_id)
        ],
        incomeTemplates=[
            adapt_income_template(
                row,
                statuses.get(("income", row[0]))
            )
            for row in get_income_templates(vault_id)
        ]
    )


@router.get("", response_model=PlanningResponse, response_model_by_alias=True)
def planning(vault: VaultContext = Depends(get_authenticated_vault)):
    return build_planning(int_vault_id(vault))


@router.post("/commitments", response_model=SuccessResponse, response_model_by_alias=True)
def create_commitment(request: PlanningItemRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = int_vault_id(vault)
    require_account(
        request.account_id,
        vault_id
    )
    try:
        add_commitment(
            vault_id,
            request.name.strip(),
            request.amount,
            request.due_day,
            request.account_id
        )
    except ValueError as error:
        raise bad_request(str(error)) from error

    return SuccessResponse()


@router.put("/commitments/{commitment_id}", response_model=SuccessResponse, response_model_by_alias=True)
def update_commitment_route(
    commitment_id: int,
    request: PlanningItemRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    require_commitment(
        commitment_id,
        vault_id
    )
    require_account(
        request.account_id,
        vault_id
    )
    try:
        update_commitment(
            commitment_id,
            request.name.strip(),
            request.amount,
            request.due_day,
            request.account_id
        )
    except ValueError as error:
        raise bad_request(str(error)) from error

    return SuccessResponse()


@router.delete("/commitments/{commitment_id}", response_model=SuccessResponse, response_model_by_alias=True)
def delete_commitment_route(commitment_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    require_commitment(
        commitment_id,
        int_vault_id(vault)
    )
    delete_commitment(commitment_id)
    return SuccessResponse()


@router.post("/commitments/{commitment_id}/status", response_model=SuccessResponse, response_model_by_alias=True)
def set_commitment_status(
    commitment_id: int,
    request: PlanningStatusRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    require_commitment(
        commitment_id,
        int_vault_id(vault)
    )
    status = request.status.upper()
    if status not in COMMITMENT_STATUSES:
        raise bad_request("Unsupported commitment status.")

    save_obligation_status(
        commitment_id,
        request.month,
        request.year,
        request.actual_amount,
        status,
        request.notes
    )
    return SuccessResponse()


@router.post("/income-templates", response_model=SuccessResponse, response_model_by_alias=True)
def create_income_template(request: PlanningItemRequest, vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = int_vault_id(vault)
    require_account(
        request.account_id,
        vault_id
    )
    add_income_template(
        vault_id,
        request.name.strip(),
        request.amount,
        request.due_day,
        request.account_id
    )
    return SuccessResponse()


@router.put("/income-templates/{template_id}", response_model=SuccessResponse, response_model_by_alias=True)
def update_income_template_route(
    template_id: int,
    request: PlanningItemRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    require_income_template(
        template_id,
        vault_id
    )
    require_account(
        request.account_id,
        vault_id
    )
    update_income_template(
        template_id,
        request.name.strip(),
        request.amount,
        request.due_day,
        request.account_id
    )
    return SuccessResponse()


@router.delete("/income-templates/{template_id}", response_model=SuccessResponse, response_model_by_alias=True)
def delete_income_template_route(template_id: int, vault: VaultContext = Depends(get_authenticated_vault)):
    require_income_template(
        template_id,
        int_vault_id(vault)
    )
    delete_income_template(template_id)
    return SuccessResponse()


@router.post("/income-templates/{template_id}/status", response_model=SuccessResponse, response_model_by_alias=True)
def set_income_status(
    template_id: int,
    request: PlanningStatusRequest,
    vault: VaultContext = Depends(get_authenticated_vault)
):
    require_income_template(
        template_id,
        int_vault_id(vault)
    )
    status = request.status.upper()
    if status not in INCOME_STATUSES:
        raise bad_request("Unsupported income status.")

    save_income_status(
        template_id,
        request.month,
        request.year,
        request.actual_amount,
        status,
        request.notes
    )
    return SuccessResponse()


@router.post("/cycles/close-active", response_model=PlanningCycleResponse, response_model_by_alias=True)
def close_cycle(vault: VaultContext = Depends(get_authenticated_vault)):
    return adapt_cycle(close_active_cycle(int_vault_id(vault)))

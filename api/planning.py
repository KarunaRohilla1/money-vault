from datetime import date

from fastapi import APIRouter, Body, Depends, Query

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
    PlanningCycleNavigationResponse,
    PlanningCycleOptionResponse,
    PlanningActivityResponse,
    PlanningCloseReadinessResponse,
    PlanningCloseRequest,
    PlanningCompletionResponse,
    PlanningCycleProgressResponse,
    PlanningItemRequest,
    PlanningResponse,
    PlanningStatusRequest,
    PlanningStatusResponse,
    PlanningTotalsResponse,
    SuccessResponse,
    VaultContext
)
from db.financial_cycles import CURRENT, close_active_cycle, derive_cycle_status, get_current_cycle, get_cycle_for_date
from db.core import get_planning_transaction_date
from db.planning import (
    add_commitment,
    add_income_template,
    delete_commitment,
    delete_income_template,
    get_commitments,
    get_cycle_planning_summary,
    get_income_templates,
    get_monthly_planning_totals,
    finalize_month,
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


def adjacent_cycle(vault_id, cycle, direction):
    if direction == "previous":
        target = cycle.start_date.toordinal() - 1
    elif direction == "next":
        target = cycle.end_date.toordinal() + 1
    else:
        raise bad_request("Choose previous or next cycle.")

    return get_cycle_for_date(
        vault_id,
        date.fromordinal(target).isoformat()
    )


def adapt_cycle(cycle):
    previous_cycle = adjacent_cycle(cycle.vault_id, cycle, "previous")
    next_cycle = adjacent_cycle(cycle.vault_id, cycle, "next")

    return PlanningCycleResponse(
        id=int(cycle.id),
        vaultId=int(cycle.vault_id),
        startDate=cycle.start_iso,
        endDate=cycle.end_iso,
        startMonth=int(cycle.start_month),
        startYear=int(cycle.start_year),
        status=cycle.status,
        displayLabel=cycle.display_name,
        totalDays=int(cycle.total_days),
        daysCompleted=int(cycle.days_completed),
        daysRemaining=int(cycle.days_remaining),
        currentDay=min(int(cycle.days_completed) + 1, int(cycle.total_days)),
        progressPercent=int(cycle.progress_percent),
        isCurrent=cycle.status == "Current",
        isCompleted=cycle.status == "Completed",
        isUpcoming=cycle.status == "Upcoming",
        closedAt=str(cycle.closed_at) if cycle.closed_at else None,
        displayMonth=cycle.start_date.strftime("%B %Y"),
        previousCycleStart=previous_cycle.start_iso,
        nextCycleStart=next_cycle.start_iso
    )


def adapt_cycle_option(cycle):
    return PlanningCycleOptionResponse(
        key=cycle.start_iso,
        label=f"{cycle.start_date.strftime('%b %Y')} - {cycle.status}",
        startDate=cycle.start_iso,
        endDate=cycle.end_iso,
        status=cycle.status,
        year=int(cycle.start_date.year)
    )


def cycles_for_year(vault_id, year, status_filter="all"):
    starts = {}
    for month in range(1, 13):
        for day in (1, 15, 28):
            cycle = get_cycle_for_date(vault_id, date(year, month, day).isoformat())
            if cycle.start_date.year == year:
                starts[cycle.start_iso] = cycle

    current = get_current_cycle(vault_id)
    if current.start_date.year == year:
        starts[current.start_iso] = current

    cycles = sorted(starts.values(), key=lambda cycle: cycle.start_date)
    if status_filter != "all":
        wanted = status_filter.lower()
        cycles = [cycle for cycle in cycles if cycle.status.lower() == wanted]

    return cycles


def build_cycle_navigation(vault_id, year=None, status_filter="all"):
    selected_year = int(year or date.today().year)
    status_value = (status_filter or "all").lower()
    if status_value not in {"all", "current", "completed", "upcoming"}:
        raise bad_request("Choose a valid cycle status filter.")

    return PlanningCycleNavigationResponse(
        currentCycleStart=get_current_cycle(vault_id).start_iso,
        cycles=[adapt_cycle_option(cycle) for cycle in cycles_for_year(vault_id, selected_year, status_value)],
        year=selected_year,
        status=status_value,
        hasPreviousYear=True,
        hasNextYear=True
    )


def build_cycle_navigation_summary(vault_id, cycle):
    return PlanningCycleNavigationResponse(
        currentCycleStart=get_current_cycle(vault_id).start_iso,
        cycles=[],
        year=cycle.start_date.year,
        status="all",
        hasPreviousYear=True,
        hasNextYear=True
    )


def select_cycle(vault_id, cycle_start=None):
    if not cycle_start:
        return get_current_cycle(vault_id)

    cycle = get_cycle_for_date(vault_id, cycle_start)
    if cycle.start_iso != cycle_start:
        raise bad_request("Choose a valid financial cycle start date.")

    return cycle


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




def activity_icon(kind, name):
    if kind == "income":
        return "cash"

    lowered = name.lower()
    if any(word in lowered for word in ["rent", "mortgage", "home", "house"]):
        return "home-outline"
    if any(word in lowered for word in ["electric", "power", "utility", "water", "gas"]):
        return "lightning-bolt-outline"
    if any(word in lowered for word in ["card", "credit"]):
        return "credit-card-outline"
    if any(word in lowered for word in ["loan", "emi", "debt"]):
        return "bank-outline"
    if any(word in lowered for word in ["insurance", "medical", "health"]):
        return "shield-check-outline"
    if any(word in lowered for word in ["sip", "mutual", "fund"]):
        return "chart-line"
    return "calendar-check-outline"


def timeline_label(due_iso, status):
    due_date = date.fromisoformat(due_iso)
    today = date.today()
    diff = (due_date - today).days

    if diff < 0 and status in {"PENDING", "CARRIED_FORWARD"}:
        return "Overdue"
    if diff == 0:
        return "Today"
    if diff == 1:
        return "Tomorrow"
    if diff > 1:
        return f"in {diff} days"
    return f"Due day {due_date.day}"


def status_label(status, kind):
    if kind == "income" and status == "RECEIVED":
        return "Completed"
    if kind == "commitment" and status == "PAID":
        return "Completed"
    if status == "CANCELLED":
        return "Skipped"
    if status == "CARRIED_FORWARD":
        return "Carried Forward"
    return "Pending"


def build_activity(kind, row, status, month, year):
    status_response = adapt_status(status)
    complete_status = "RECEIVED" if kind == "income" else "PAID"
    activity_status = status_response.status
    expected = row[2]
    effective_expected = (
        status_response.actual_amount
        if status_response.actual_amount is not None and activity_status != "CANCELLED"
        else expected
    )
    actual = (
        status_response.actual_amount
        if activity_status == complete_status and status_response.actual_amount is not None
        else effective_expected
    )
    due_iso = get_planning_transaction_date(year, month, row[3])

    return PlanningActivityResponse(
        accountId=int(row[5]) if row[5] is not None else None,
        accountName=row[4],
        actualAmount=number(actual),
        amount=number(expected),
        completeLabel="Received" if kind == "income" else "Paid",
        completeStatus=complete_status,
        dueDate=due_iso,
        dueDay=int(row[3]),
        effectiveExpectedAmount=number(effective_expected),
        icon=activity_icon(kind, row[1]),
        id=int(row[0]),
        kind=kind,
        name=row[1],
        status=status_response,
        statusLabel=status_label(activity_status, kind),
        timelineLabel=timeline_label(due_iso, activity_status)
    )


def build_cycle_progress(cycle):
    cycle_start = date.fromisoformat(cycle.start_iso)
    cycle_end = date.fromisoformat(cycle.end_iso)
    today = date.today()
    total_days = max((cycle_end - cycle_start).days + 1, 1)

    if cycle_start <= today <= cycle_end:
        days_remaining = max((cycle_end - today).days + 1, 0)
        days_completed = min(max((today - cycle_start).days, 0), total_days)
    elif today > cycle_end:
        days_remaining = 0
        days_completed = total_days
    else:
        days_remaining = total_days
        days_completed = 0

    progress_percent = int(days_completed / total_days * 100)

    return PlanningCycleProgressResponse(
        currentDay=min(days_completed + 1, total_days),
        daysCompleted=days_completed,
        daysRemaining=days_remaining,
        progressPercent=progress_percent,
        startLabel=cycle_start.strftime("%d %b %Y"),
        status=derive_cycle_status(cycle_start, cycle_end, today),
        totalDays=total_days
    )


def build_completion(totals, activities):
    income_percent = int((totals["income_received"] / totals["income_planned"] * 100) if totals["income_planned"] else 0)
    commitment_percent = int((totals["commitments_completed"] / totals["commitments_planned"] * 100) if totals["commitments_planned"] else 0)
    attention_count = len([activity for activity in activities if activity.status.status in {"PENDING", "CARRIED_FORWARD"} and activity.timeline_label in {"Overdue", "Today", "Tomorrow"}])
    status = "on_track" if attention_count == 0 else "warning"

    return PlanningCompletionResponse(
        attentionCount=attention_count,
        commitmentCompletionPercent=min(commitment_percent, 100),
        incomeCompletionPercent=min(income_percent, 100),
        status=status,
        statusLabel="On Track" if status == "on_track" else "Needs Attention",
        subtitle=f"Income received {min(income_percent, 100)}% - Commitments completed {min(commitment_percent, 100)}%"
    )


def build_close_readiness(cycle, activities):
    pending = [activity for activity in activities if activity.status.status in {"PENDING", "CARRIED_FORWARD"}]
    total = len(activities)

    return PlanningCloseReadinessResponse(
        canClose=cycle.status == "Current",
        completedCount=max(total - len(pending), 0),
        pendingCount=len(pending),
        reviewRequired=len(pending) > 0,
        totalCount=total
    )
def build_planning(vault_id, cycle_start=None):
    cycle = select_cycle(vault_id, cycle_start)
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
    commitment_rows = get_commitments(vault_id)
    income_rows = get_income_templates(vault_id)
    activities = [
        build_activity("income", row, statuses.get(("income", row[0])), month, year)
        for row in income_rows
    ] + [
        build_activity("commitment", row, statuses.get(("commitment", row[0])), month, year)
        for row in commitment_rows
    ]
    activities.sort(key=lambda activity: (activity.due_day, activity.kind, activity.id))
    timeline = [
        activity
        for activity in activities
        if activity.status.status in {"PENDING", "CARRIED_FORWARD"}
    ]
    timeline.sort(key=lambda activity: (activity.due_date, activity.due_day, activity.id))

    return PlanningResponse(
        cycle=adapt_cycle(cycle),
        totals=PlanningTotalsResponse(
            income=number(monthly_totals["income"]),
            plannedCommitments=number(monthly_totals["planned_commitments"]),
            remainingCommitments=number(cycle_summary["remaining_commitments"]),
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
            for row in commitment_rows
        ],
        incomeTemplates=[
            adapt_income_template(
                row,
                statuses.get(("income", row[0]))
            )
            for row in income_rows
        ],
        activities=activities,
        timeline=timeline[:5],
        cycleProgress=build_cycle_progress(cycle),
        completion=build_completion(cycle_summary, activities),
        closeReadiness=build_close_readiness(cycle, activities),
        cycleNavigation=build_cycle_navigation_summary(vault_id, cycle)
    )


@router.get("", response_model=PlanningResponse, response_model_by_alias=True)
def planning(
    cycle_start: str | None = Query(default=None, alias="cycleStart"),
    vault: VaultContext = Depends(get_authenticated_vault)
):
    return build_planning(int_vault_id(vault), cycle_start)


@router.get("/cycles", response_model=PlanningCycleNavigationResponse, response_model_by_alias=True)
def planning_cycles(
    year: int | None = Query(default=None),
    status: str = Query(default="all"),
    vault: VaultContext = Depends(get_authenticated_vault)
):
    return build_cycle_navigation(int_vault_id(vault), year, status)


@router.get("/cycles/adjacent", response_model=PlanningCycleResponse, response_model_by_alias=True)
def adjacent_planning_cycle(
    cycle_start: str = Query(alias="cycleStart"),
    direction: str = Query(default="next"),
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    cycle = select_cycle(vault_id, cycle_start)
    return adapt_cycle(adjacent_cycle(vault_id, cycle, direction))


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


def validate_close_request(vault_id, request):
    if not request or not request.items:
        return []

    items = []
    for item in request.items:
        item_type = item.type
        if item_type == "income":
            require_income_template(item.id, vault_id)
        elif item_type == "commitment":
            require_commitment(item.id, vault_id)
        else:
            raise bad_request("Choose a valid planning item type.")

        if item.action not in {"Paid", "Cancelled", "Carry Forward"}:
            raise bad_request("Choose a valid close action.")
        if item.action in {"Paid", "Carry Forward"} and item.amount <= 0:
            raise bad_request("Enter an amount greater than zero for paid or carried forward items.")

        items.append(item.dict())

    return items


def close_selected_cycle(vault_id, cycle_start, request):
    cycle = select_cycle(vault_id, cycle_start)
    if cycle.status != CURRENT:
        raise bad_request("Only the current financial cycle can be closed.")

    close_items = validate_close_request(vault_id, request)
    if close_items:
        finalize_month(
            vault_id,
            cycle.start_month,
            cycle.start_year,
            close_items
        )

    return adapt_cycle(close_active_cycle(vault_id))


@router.post("/cycles/{cycle_start}/close", response_model=PlanningCycleResponse, response_model_by_alias=True)
def close_cycle_by_start(
    cycle_start: str,
    request: PlanningCloseRequest | None = Body(default=None),
    vault: VaultContext = Depends(get_authenticated_vault)
):
    return close_selected_cycle(int_vault_id(vault), cycle_start, request)


@router.post("/cycles/close-active", response_model=PlanningCycleResponse, response_model_by_alias=True)
def close_cycle(
    request: PlanningCloseRequest | None = Body(default=None),
    vault: VaultContext = Depends(get_authenticated_vault)
):
    vault_id = int_vault_id(vault)
    return close_selected_cycle(vault_id, get_current_cycle(vault_id).start_iso, request)

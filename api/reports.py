from datetime import datetime, timezone

from fastapi import APIRouter, Depends

from api.dashboard import to_json_safe
from api.dependencies import get_authenticated_vault
from api.resources import int_vault_id
from api.schemas import ReportsResponse, VaultContext
from db.financial_cycles import get_current_cycle
from views.reports import (
    get_category_breakdown,
    get_monthly_trend,
    get_report_summary,
    report_period_context
)


router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("", response_model=ReportsResponse, response_model_by_alias=True)
def reports(vault: VaultContext = Depends(get_authenticated_vault)):
    vault_id = int_vault_id(vault)
    cycle = get_current_cycle(vault_id)
    context = report_period_context(
        vault_id,
        cycle
    )
    summary = get_report_summary(
        vault_id,
        context["start_date"],
        context["end_date"],
        context["cycle_windows"]
    )
    return ReportsResponse(
        generatedAt=datetime.now(timezone.utc),
        period=to_json_safe({
            "startDate": cycle.start_iso,
            "endDate": cycle.end_iso,
            "status": cycle.status
        }),
        summary=to_json_safe(summary),
        categoryBreakdown=to_json_safe(
            get_category_breakdown(
                vault_id,
                context["start_date"],
                context["end_date"]
            )
        ),
        monthlyTrend=to_json_safe(get_monthly_trend(vault_id, context["end_date"]))
    )

from datetime import date, datetime
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

from db.financial_cycles import (
    COMPLETED,
    CURRENT,
    UPCOMING,
    CycleContext,
    derive_cycle_status,
    get_current_cycle_with_cursor,
)


def build_client(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-value-with-at-least-32-bytes")
    from api.config import get_config

    get_config.cache_clear()

    from api.main import create_app

    return TestClient(create_app())


def auth_header(monkeypatch, vault_id="1"):
    build_client(monkeypatch)
    from api.security import create_access_token

    token, _expires_at = create_access_token(
        SimpleNamespace(
            id=vault_id,
            name="Karuna",
            vault_type="Individual",
            is_admin=False
        )
    )
    return {"Authorization": f"Bearer {token}"}


def sample_cycle(start="2026-07-10", end="2026-08-09", status="Current", closed_at=None):
    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    return CycleContext(
        id=1,
        vault_id=1,
        start_date=start_d,
        end_date=end_d,
        status=status,
        closed_at=closed_at
    )


def test_derive_cycle_status_with_closed_at():
    # If closed_at is set, cycle is COMPLETED even if today is within bounds
    start = date(2026, 7, 10)
    end = date(2026, 8, 9)
    today = date(2026, 7, 20)

    assert derive_cycle_status(start, end, today=today, closed_at=None) == CURRENT
    assert derive_cycle_status(start, end, today=today, closed_at="2026-07-20T10:00:00") == COMPLETED
    assert derive_cycle_status(start, end, today=today, closed_at=datetime(2026, 7, 20)) == COMPLETED


def test_get_current_cycle_advances_when_closed(monkeypatch):
    # When current calendar cycle is closed, get_current_cycle_with_cursor advances to next cycle
    cycle1 = sample_cycle(start="2026-07-10", end="2026-08-09", status="Completed", closed_at="2026-08-05T12:00:00")
    cycle2 = sample_cycle(start="2026-08-10", end="2026-09-09", status="Current", closed_at=None)

    def mock_get_context(cursor, vault_id, target_date):
        t_date = target_date if isinstance(target_date, date) else date.fromisoformat(str(target_date))
        if t_date <= date(2026, 8, 9):
            return cycle1
        return cycle2

    monkeypatch.setattr("db.financial_cycles.get_cycle_context_with_cursor", mock_get_context)

    active = get_current_cycle_with_cursor(None, 1)
    assert active.start_iso == "2026-08-10"
    assert active.closed_at is None


def test_build_close_readiness_carried_forward_not_pending():
    from api.planning import build_close_readiness

    cycle_open = sample_cycle(status="Current", closed_at=None)
    cycle_closed = sample_cycle(status="Completed", closed_at="2026-07-20T10:00:00")

    carried_activity = SimpleNamespace(
        id=1,
        kind="commitment",
        name="Rent",
        status=SimpleNamespace(status="CARRIED_FORWARD")
    )

    pending_activity = SimpleNamespace(
        id=2,
        kind="commitment",
        name="Internet",
        status=SimpleNamespace(status="PENDING")
    )

    readiness_open = build_close_readiness(cycle_open, [carried_activity, pending_activity])
    assert readiness_open.can_close is True
    assert readiness_open.pending_count == 1  # only pending_activity is pending, carried is resolved
    assert readiness_open.completed_count == 1

    readiness_closed = build_close_readiness(cycle_closed, [carried_activity, pending_activity])
    assert readiness_closed.can_close is False
    assert readiness_closed.review_required is False
    assert readiness_closed.pending_count == 0


def test_close_cycle_success(monkeypatch):
    client = build_client(monkeypatch)
    headers = auth_header(monkeypatch)

    open_cycle = sample_cycle(start="2026-07-10", end="2026-08-09", status="Current", closed_at=None)
    closed_cycle = sample_cycle(start="2026-07-10", end="2026-08-09", status="Completed", closed_at="2026-08-05T12:00:00")

    monkeypatch.setattr("api.planning.select_cycle", lambda vault_id, start: open_cycle)
    monkeypatch.setattr("api.planning.validate_close_request", lambda vault_id, req: [{"id": 1, "type": "commitment", "action": "Carry Forward", "amount": 2000}])
    monkeypatch.setattr("api.planning.finalize_month", lambda vault_id, month, year, items: None)
    monkeypatch.setattr("api.planning.close_active_cycle", lambda vault_id: closed_cycle)
    monkeypatch.setattr("api.planning.adjacent_cycle", lambda vault_id, c, direction: sample_cycle(start="2026-06-10", end="2026-07-09"))

    res = client.post(
        "/api/planning/cycles/2026-07-10/close",
        headers=headers,
        json={"items": [{"id": 1, "type": "commitment", "action": "Carry Forward", "amount": 2000}]}
    )
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "Completed"
    assert data["isCompleted"] is True
    assert data["isCurrent"] is False


def test_close_already_closed_cycle_raises_400(monkeypatch):
    client = build_client(monkeypatch)
    headers = auth_header(monkeypatch)

    closed_cycle = sample_cycle(start="2026-07-10", end="2026-08-09", status="Completed", closed_at="2026-08-05T12:00:00")
    monkeypatch.setattr("api.planning.select_cycle", lambda vault_id, start: closed_cycle)

    res = client.post(
        "/api/planning/cycles/2026-07-10/close",
        headers=headers,
        json={"items": []}
    )
    assert res.status_code == 400
    assert res.json() == {
        "code": "VALIDATION_ERROR",
        "message": "Only the current financial cycle can be closed."
    }


def test_build_activity_month_crossing_cycle():
    from api.planning import build_activity

    cycle = sample_cycle(start="2026-09-10", end="2026-10-09", status="Current")

    # Commitment due Sep 25 (due_day >= cycle.start_date.day) -> 2026-09-25
    row_sep = (1, "Rent", 25000.0, 25, "HDFC", 1)
    act_sep = build_activity("commitment", row_sep, None, cycle)
    assert act_sep.due_date == "2026-09-25"

    # Commitment due Oct 5 (due_day < cycle.start_date.day) -> 2026-10-05
    row_oct = (2, "Electricity", 1500.0, 5, "HDFC", 1)
    act_oct = build_activity("commitment", row_oct, None, cycle)
    assert act_oct.due_date == "2026-10-05"


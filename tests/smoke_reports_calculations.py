from datetime import date
from pathlib import Path
import sys
import types


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

streamlit_stub = types.ModuleType("streamlit")
streamlit_stub.cache_data = lambda **_kwargs: (lambda wrapped: wrapped)
streamlit_stub.cache_resource = lambda **_kwargs: (lambda wrapped: wrapped)
sys.modules.setdefault("pandas", types.ModuleType("pandas"))
sys.modules.setdefault("streamlit", streamlit_stub)
sys.modules.setdefault("plotly", types.ModuleType("plotly"))
sys.modules.setdefault("plotly.express", types.ModuleType("plotly.express"))
sys.modules.setdefault(
    "plotly.graph_objects",
    types.ModuleType("plotly.graph_objects")
)

from views import reports


class FakeRow:
    def __init__(self, value):
        self.value = value

    def fetchone(self):
        return (self.value,)


class FakeConnection:
    def __init__(self):
        self.closed = False

    def execute(self, query, params=()):
        assert "manual_income" in query
        assert "received_recurring_income" in query
        assert params == (
            1,
            "Income",
            "2026-06-24",
            "2026-07-23",
            1,
            6,
            2026
        )
        return FakeRow(12500)

    def close(self):
        self.closed = True


def main():
    original_get_connection = reports.get_connection
    try:
        if hasattr(reports.get_actual_income_total, "clear"):
            reports.get_actual_income_total.clear()
        reports.get_connection = lambda: FakeConnection()
        total = reports.get_actual_income_total(
            1,
            date(2026, 6, 24),
            date(2026, 7, 23),
            (("2026-06-24", "2026-07-23", 6, 2026),)
        )
        assert total == 12500
    finally:
        reports.get_connection = original_get_connection
        if hasattr(reports.get_actual_income_total, "clear"):
            reports.get_actual_income_total.clear()

    print("reports calculation checks passed")


if __name__ == "__main__":
    main()

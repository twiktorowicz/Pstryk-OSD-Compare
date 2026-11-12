"""FV form helpers (no Home Assistant)."""

from __future__ import annotations

from datetime import datetime

from pstryk_osd_compare.calc import TZ
from pstryk_osd_compare.fv import (
    FvDraft,
    closed_months,
    default_month,
    draft_to_row,
    prefill,
)

TODAY = datetime(2026, 11, 2, 10, 0, tzinfo=TZ)
ROWS = [
    {"month": "2026-08", "status": "fv"},
    {"month": "2026-09", "status": "fv"},
    {"month": "2026-10", "status": "open"},
    {"month": "2026-11", "status": "open"},
]


def test_closed_months_excludes_current_month() -> None:
    assert closed_months(ROWS, TODAY) == ["2026-08", "2026-09", "2026-10"]


def test_default_month_is_first_without_fv() -> None:
    assert default_month(ROWS, TODAY) == "2026-10"


def test_default_month_falls_back_to_last_closed() -> None:
    rows = [{"month": "2026-09", "status": "fv"}, {"month": "2026-10", "status": "fv"}]
    assert default_month(rows, TODAY) == "2026-10"
    assert default_month([], TODAY) is None


def test_prefill_from_saved_fv() -> None:
    official = {"2026-09": {"invoice": 120.5, "deposit_used": 90.0, "bonus": 30.5, "number": "SE/1"}}
    values, number = prefill("2026-09", official, {})
    assert values == {
        "invoice": 120.5,
        "deposit_used": 90.0,
        "bonus": 30.5,
        "shield": None,
        "wallet": None,
        "inflow": None,
    }
    assert number == "SE/1"


def test_prefill_from_model_adds_monthly_fee() -> None:
    model = {"2026-10": {"p_invoice": 100.004, "p_inflow": 250.126}}
    values, number = prefill("2026-10", {}, model, monthly_fee=9.99)
    assert values == {
        "invoice": 109.99,
        "deposit_used": None,
        "bonus": None,
        "shield": 0.0,
        "wallet": None,
        "inflow": 250.13,
    }
    assert number == ""


def test_prefill_from_model_subtracts_shield() -> None:
    model = {"2026-11": {"p_invoice": 400.0, "p_shield": 55.554, "p_inflow": 10.0}}
    values, _ = prefill("2026-11", {}, model)
    assert values["invoice"] == 344.45
    assert values["shield"] == 55.55


def test_draft_to_row_skips_empty_fields() -> None:
    row = draft_to_row(
        {"invoice": 120.499, "deposit_used": None, "bonus": 0.0, "inflow": 300.0}, "  SE/P/1  "
    )
    assert row == {"invoice": 120.5, "bonus": 0.0, "inflow": 300.0, "number": "SE/P/1"}
    assert draft_to_row({"invoice": 1.0}, " ") == {"invoice": 1.0}


def test_draft_notifies_listeners_until_removed() -> None:
    draft = FvDraft()
    calls: list[str] = []
    remove = draft.add_listener(lambda: calls.append(draft.month or ""))
    draft.load("2026-10", {"invoice": 1.0}, "X")
    remove()
    draft.load("2026-09", {}, "")
    assert calls == ["2026-10"]

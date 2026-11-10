"""Unit tests for pstryk_osd_compare.calc (no Home Assistant)."""

from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from pstryk_osd_compare.calc import (
    DepositConfig,
    build_corrections,
    compute_fixed,
    cumulative_series,
    deposit_ledger,
    filter_hours_by_contract,
    hour_metrics,
    hourly_breakdown,
    is_matched,
    ledger_balance_through,
    month_model_totals,
    monthly_rows,
    parse_official_months,
    period_bounds,
    settled_through_month,
    summarize,
)
from pstryk_osd_compare.const import BASIS_BALANCED, BASIS_GROSS, TZ

FIXTURE = Path(__file__).parent / "fixtures" / "october_2026_hourly.csv"
UTC = timezone.utc


def _f(v: str) -> float | None:
    if v is None or v == "":
        return None
    return float(v)


def load_october_hours() -> dict[int, dict]:
    hours: dict[int, dict] = {}
    with FIXTURE.open(newline="") as fh:
        for row in csv.DictReader(fh):
            local = datetime.fromisoformat(row["hour_local"])
            ts = int(local.astimezone(UTC).timestamp())
            p_imp = _f(row["p_imp_kwh"])
            buy = _f(row["buy_pln_kwh"])
            api_cost = _f(row["api_import_cost"])
            rec = {
                "p_imp": p_imp if row["has_pstryk"] == "1" else None,
                "p_exp": _f(row["p_exp_kwh"]) if row["has_pstryk"] == "1" else None,
                "buy": buy if row["has_pstryk"] == "1" else None,
                "sell": _f(row["sell_pln_kwh"]) if row["has_pstryk"] == "1" else None,
                "api_cost": api_cost if row["has_pstryk"] == "1" else None,
                "api_sold": _f(row["api_sold_value"]) if row["has_pstryk"] == "1" else None,
                "fixed": compute_fixed(api_cost, p_imp, buy) if row["has_pstryk"] == "1" else None,
                "t_imp": _f(row["t_imp_kwh"]) if row["has_tauron"] == "1" else None,
                "t_exp": _f(row["t_exp_kwh"]) if row["has_tauron"] == "1" else None,
                "tb_imp": _f(row["t_bal_imp_kwh"]) if row["has_tauron"] == "1" else None,
                "tb_exp": _f(row["t_bal_exp_kwh"]) if row["has_tauron"] == "1" else None,
            }
            # Empty CSV cells for tauron on unmatched days become None via has_tauron
            hours[ts] = rec
    return hours


def test_is_matched():
    assert is_matched({"p_imp": 1.0, "buy": 1.2, "t_imp": 0.5}) is True
    assert is_matched({"p_imp": 1.0, "buy": None, "t_imp": 0.5}) is False
    assert is_matched({"p_imp": 1.0, "buy": 1.2, "t_imp": None}) is False
    assert is_matched({"p_imp": None, "buy": 1.2, "t_imp": 0.5}) is False


def test_hour_metrics_both_directions():
    rec = {
        "p_imp": 0.048,
        "p_exp": 0.21,
        "buy": 1.27297,
        "sell": 1.0678,
        "api_cost": 0.1139,
        "fixed": 0.1139 - 0.048 * 1.27297,
        "t_imp": 0.04,
        "t_exp": 0.20,
        "tb_imp": 0.0,
        "tb_exp": 0.162,
    }
    m = hour_metrics(rec, BASIS_GROSS)
    assert m["pstryk_import"] == pytest.approx(0.048)
    assert m["pstryk_export"] == pytest.approx(0.21)
    assert m["osd_import"] == pytest.approx(0.04)
    assert m["diff_import"] == pytest.approx(0.008)
    assert m["pstryk_buy_value"] == pytest.approx(0.048 * 1.27297)
    assert m["pstryk_sell_value"] == pytest.approx(0.21 * 1.0678)
    m_bal = hour_metrics(rec, BASIS_BALANCED)
    assert m_bal["osd_import"] == pytest.approx(0.0)
    assert m_bal["osd_export"] == pytest.approx(0.162)


def test_cumulative_series_skips_unmatched():
    hours = {
        100: {"p_imp": 1.0, "p_exp": 0.0, "buy": 1.0, "sell": 0.5, "t_imp": 0.5, "t_exp": 0.0, "tb_imp": 0.5, "tb_exp": 0.0, "api_cost": 1.0, "fixed": 0.0},
        200: {"p_imp": 2.0, "p_exp": 0.0, "buy": 1.0, "sell": 0.5, "t_imp": None, "t_exp": None},  # unmatched
        300: {"p_imp": 3.0, "p_exp": 0.0, "buy": 1.0, "sell": 0.5, "t_imp": 1.0, "t_exp": 0.0, "tb_imp": 1.0, "tb_exp": 0.0, "api_cost": 3.0, "fixed": 0.0},
    }
    series = cumulative_series(hours, BASIS_GROSS)
    states = series["pstryk_import"]
    assert len(states) == 2
    assert states[0] == (100, 1.0, 1.0)
    assert states[1] == (300, 3.0, 4.0)


def test_period_bounds_october_2026_dst():
    ref = datetime(2026, 10, 15, 12, 0, tzinfo=TZ)
    start_ts, end_ts = period_bounds("month", ref)
    assert datetime.fromtimestamp(start_ts, tz=UTC).isoformat() == "2026-09-30T22:00:00+00:00"
    assert datetime.fromtimestamp(end_ts, tz=UTC).isoformat() == "2026-10-31T23:00:00+00:00"
    assert (end_ts - start_ts) // 3600 == 745


def test_hourly_breakdown_dst_25_hours():
    # Empty store still yields 25 slots on 2026-10-25
    rows = hourly_breakdown({}, BASIS_GROSS, date(2026, 10, 25))
    assert len(rows) == 25
    two_am = [r for r in rows if r["hour"] == "02:00"]
    assert len(two_am) == 2
    offsets = {r["utc_offset"] for r in two_am}
    assert offsets == {"+02:00", "+01:00"}


def test_october_fixture_gross_matches_reference():
    hours = load_october_hours()
    start_ts, end_ts = period_bounds("month", datetime(2026, 10, 15, tzinfo=TZ))
    s = summarize(hours, BASIS_GROSS, start_ts, end_ts)
    assert s["hours_matched"] == 721
    assert s["pstryk_import"] == pytest.approx(523.869, abs=0.01)
    assert s["osd_import"] == pytest.approx(517.966, abs=0.01)
    assert s["pstryk_export"] == pytest.approx(530.403, abs=0.01)
    assert s["osd_export"] == pytest.approx(375.643, abs=0.01)
    assert s["pstryk_buy_value"] == pytest.approx(344.39, abs=0.05)
    assert s["osd_buy_value"] == pytest.approx(353.06, abs=0.05)
    assert s["pstryk_sell_value"] == pytest.approx(773.48, abs=0.05)
    assert s["osd_sell_value"] == pytest.approx(604.04, abs=0.05)


def test_october_fixture_balanced():
    hours = load_october_hours()
    start_ts, end_ts = period_bounds("month", datetime(2026, 10, 15, tzinfo=TZ))
    s = summarize(hours, BASIS_BALANCED, start_ts, end_ts)
    assert s["osd_import"] == pytest.approx(509.510, abs=0.01)
    assert s["osd_export"] == pytest.approx(367.187, abs=0.01)
    assert s["osd_buy_value"] == pytest.approx(344.27, abs=0.05)
    assert s["osd_sell_value"] == pytest.approx(597.63, abs=0.05)


def _model_month(
    p_inflow: float = 0.0,
    p_invoice: float = 0.0,
    t_inflow: float | None = None,
    t_invoice: float | None = None,
    **kwh: float,
) -> dict:
    return {
        "p_inflow": p_inflow,
        "p_invoice": p_invoice,
        "t_inflow": p_inflow if t_inflow is None else t_inflow,
        "t_invoice": p_invoice if t_invoice is None else t_invoice,
        "p_imp": kwh.get("p_imp", 0.0),
        "t_imp": kwh.get("t_imp", 0.0),
        "p_exp": kwh.get("p_exp", 0.0),
        "t_exp": kwh.get("t_exp", 0.0),
        "hours_matched": 1,
        "hours_expected": 1,
    }


FV_V_IX = {
    "2026-05": {"invoice": 160.12, "deposit_used": 0.0, "bonus": 0.0, "inflow": 547.70},
    "2026-06": {"invoice": 138.98, "deposit_used": 64.04, "bonus": 74.94, "inflow": 1043.15},
    "2026-07": {"invoice": 106.85, "deposit_used": 39.82, "bonus": 67.03, "inflow": 1012.84},
    "2026-08": {"invoice": 66.21, "deposit_used": 8.90, "bonus": 57.31, "inflow": 1514.63},
    "2026-09": {"invoice": 138.43, "deposit_used": 70.53, "bonus": 67.90, "inflow": 1215.83},
}


def test_month_model_totals_matched_only():
    base = {"buy": 1.0, "sell": 2.0, "tb_imp": 0.5, "tb_exp": 1.0}
    t1 = int(datetime(2026, 1, 15, 12, tzinfo=TZ).astimezone(UTC).timestamp())
    t2 = t1 + 3600
    hours = {
        t1: {**base, "p_imp": 1.0, "p_exp": 2.0, "api_cost": 1.5, "fixed": 0.5, "t_imp": 0.5, "t_exp": 1.0},
        t2: {**base, "p_imp": 1.0, "p_exp": 2.0, "api_cost": 1.5, "fixed": 0.5, "t_imp": None, "t_exp": None},
    }
    model = month_model_totals(hours, BASIS_GROSS, t2, date(2026, 1, 1))
    m = model["2026-01"]
    assert m["hours_matched"] == 1
    assert m["p_inflow"] == pytest.approx(4.0)
    assert m["t_inflow"] == pytest.approx(2.0)
    assert m["p_invoice"] == pytest.approx(1.5)
    assert m["t_invoice"] == pytest.approx(0.5 + 0.5)


def test_invoice_paid_from_previous_balance():
    model = {
        "2026-01": _model_month(p_inflow=100.0, p_invoice=30.0),
        "2026-02": _model_month(p_inflow=0.0, p_invoice=50.0),
    }
    corr = build_corrections(model, {})
    ledger = deposit_ledger(model, corr, source="pstryk", cfg=DepositConfig())
    assert ledger[0]["used"] == 0.0
    assert ledger[0]["to_pay"] == 30.0
    assert ledger[0]["balance"] == 100.0
    assert ledger[1]["used"] == 50.0
    assert ledger[1]["to_pay"] == 0.0
    assert ledger[1]["balance"] == 50.0


def test_bonus_is_part_of_deposit_use():
    """FV June: deposit 64.04 + bonus 74.94 = full invoice 138.98 taken from deposit."""
    model = {
        "2026-05": _model_month(p_inflow=547.70, p_invoice=160.12),
        "2026-06": _model_month(p_inflow=0.0, p_invoice=138.98),
    }
    fv = {"2026-06": {"invoice": 138.98, "deposit_used": 64.04, "bonus": 74.94}}
    corr = build_corrections(model, fv)
    assert corr["2026-06"].deposit_used == pytest.approx(138.98)
    for source in ("pstryk", "tauron"):
        ledger = deposit_ledger(model, corr, source=source, cfg=DepositConfig())
        assert ledger[1]["used"] == 138.98
        assert ledger[1]["bonus"] == 74.94
        assert ledger[1]["to_pay"] == 0.0
        assert ledger[1]["balance"] == pytest.approx(547.70 - 138.98)


def test_fv_not_applied_to_tauron_measurements():
    model = {
        "2026-05": _model_month(p_inflow=500.0, p_invoice=100.0, t_inflow=400.0, t_invoice=110.0),
        "2026-06": _model_month(p_inflow=600.0, p_invoice=90.0, t_inflow=450.0, t_invoice=95.0),
    }
    fv = {
        "2026-06": {"invoice": 100.0, "deposit_used": 40.0, "bonus": 60.0, "inflow": 600.0},
    }
    corr = build_corrections(model, fv)
    assert corr["2026-06"].extra_invoice == pytest.approx(10.0)
    lp = deposit_ledger(model, corr, source="pstryk", cfg=DepositConfig())
    lt = deposit_ledger(model, corr, source="tauron", cfg=DepositConfig())
    assert lp[1]["used"] == 100.0
    assert lp[1]["invoice"] == 100.0
    assert lt[1]["inflow"] == 450.0
    assert lt[1]["invoice"] == 105.0  # 95 + extra 10
    assert lt[1]["used"] == 105.0  # computed from Tauron invoice, not FV
    assert lt[1]["balance"] == pytest.approx(400.0 - 105.0 + 450.0)


def test_month_without_fv_takes_full_invoice():
    model = {m: _model_month(p_inflow=1000.0, p_invoice=100.0) for m in FV_V_IX}
    model["2026-10"] = _model_month(p_inflow=500.0, p_invoice=411.38)
    corr = build_corrections(model, FV_V_IX)
    assert corr["2026-10"].status == "estimate"
    ledger = deposit_ledger(model, corr, source="pstryk", cfg=DepositConfig())
    assert ledger[-1]["bonus"] == 0.0
    assert ledger[-1]["used"] == 411.38


def test_pstryk_fv_reconciliation_v_ix():
    """App on 2026-11-01 (FV through IX): 4883.68 zł."""
    model = {
        m: _model_month(p_inflow=fv["inflow"], p_invoice=fv["invoice"])
        for m, fv in FV_V_IX.items()
    }
    corr = build_corrections(model, FV_V_IX)
    lp = deposit_ledger(model, corr, source="pstryk", cfg=DepositConfig())
    lt = deposit_ledger(model, corr, source="tauron", cfg=DepositConfig())
    assert lp[-1]["balance"] == 4883.68
    assert lp[0]["used"] == 0.0 and lp[0]["to_pay"] == 160.12  # May paid in cash
    # Same measurements → computed deposit use matches FV facts
    assert [r["used"] for r in lt] == [
        round(fv["deposit_used"] + fv["bonus"], 2) for fv in FV_V_IX.values()
    ]
    assert lt[-1]["balance"] == 4883.68
    rows, totals = monthly_rows(model, lp, lt, "2026-09")
    assert all(r["status"] == "fv" for r in rows)
    assert totals["d_dep"] == 0.0


def test_adjustment_and_monthly_rows_status():
    model = {
        "2026-09": _model_month(p_inflow=100.0, t_inflow=80.0, p_exp=100.0, t_exp=80.0),
        "2026-10": _model_month(p_inflow=50.0, t_inflow=40.0, p_exp=50.0, t_exp=40.0),
        "2026-11": _model_month(p_inflow=10.0, t_inflow=10.0),
    }
    cfg = DepositConfig(monthly_adjustments={"2026-09": 25.0})
    corr = build_corrections(model, {})
    lp = deposit_ledger(model, corr, source="pstryk", cfg=cfg)
    lt = deposit_ledger(model, corr, source="tauron", cfg=cfg)
    assert lp[0]["balance"] == 125.0
    assert ledger_balance_through(lp, "2026-10") == 175.0
    assert ledger_balance_through(lp, "2026-12") is None
    rows, totals = monthly_rows(model, lp, lt, "2026-10")
    assert [r["status"] for r in rows] == ["estimate", "estimate", "open"]
    assert rows[0]["d_exp"] == 20.0
    assert rows[0]["d_exp_pct"] == 25.0
    assert rows[1]["d_dep"] == 30.0
    assert rows[1]["d_dep_month"] == 10.0
    assert totals["d_exp"] == 30.0
    assert totals["d_dep"] == 30.0

def test_settled_through_month():
    assert settled_through_month(date(2026, 11, 1), settlement_day=10) == "2026-09"
    assert settled_through_month(date(2026, 11, 9), settlement_day=10) == "2026-09"
    assert settled_through_month(date(2026, 11, 10), settlement_day=10) == "2026-10"
    assert settled_through_month(date(2026, 1, 5), settlement_day=10) == "2025-11"
    assert settled_through_month(date(2026, 1, 15), settlement_day=10) == "2025-12"
    assert settled_through_month(date(2026, 11, 5)) == "2026-09"
    assert settled_through_month(date(2026, 11, 6)) == "2026-10"


def test_settled_through_month_entered_fv_settles_early():
    fv = ["2026-09", "2026-10"]
    assert settled_through_month(date(2026, 11, 4), fv_months=fv) == "2026-10"
    assert settled_through_month(date(2026, 11, 4), fv_months=["2026-09"]) == "2026-09"
    assert settled_through_month(date(2026, 1, 3), fv_months=["2025-12"]) == "2025-12"


def test_parse_official_months():
    parsed = parse_official_months(
        '{"2026-05": {"invoice": 160.12, "deposit_used": 0, "number": "SE/P/1"}}'
    )
    assert parsed["2026-05"]["invoice"] == 160.12
    assert parsed["2026-05"]["number"] == "SE/P/1"
    assert parse_official_months({}) == {}


def test_fixed_fee_and_tauron_invoice_oct31():
    # Verified frame 2026-10-31 00:00 UTC → local 01:00 CET
    p_imp = 1.043
    buy = 1.3121209999999999
    api_cost = 1.4262563159032258
    fixed = compute_fixed(api_cost, p_imp, buy)
    assert fixed == pytest.approx(0.0577, abs=0.0005)
    rec = {
        "p_imp": p_imp,
        "p_exp": 0.0,
        "buy": buy,
        "sell": 0.0,
        "api_cost": api_cost,
        "fixed": fixed,
        "t_imp": 1.0,
        "t_exp": 0.0,
        "tb_imp": 1.0,
        "tb_exp": 0.0,
    }
    m = hour_metrics(rec, BASIS_GROSS)
    assert m["osd_invoice_cost"] == pytest.approx(fixed + 1.0 * buy, abs=1e-9)
    assert m["pstryk_invoice_cost"] == pytest.approx(api_cost, abs=1e-9)


def test_filter_hours_by_contract():
    hours = {
        int(datetime(2026, 4, 30, 22, 0, tzinfo=UTC).timestamp()): {"p_imp": 1.0},
        int(datetime(2026, 4, 30, 23, 0, tzinfo=UTC).timestamp()): {"p_imp": 2.0},  # 2026-05-01 01:00 CEST
        int(datetime(2026, 5, 1, 0, 0, tzinfo=UTC).timestamp()): {"p_imp": 3.0},
    }
    # contract_start 2026-05-01 local = 2026-04-30 22:00 UTC
    filtered = filter_hours_by_contract(hours, date(2026, 5, 1))
    assert int(datetime(2026, 4, 30, 22, 0, tzinfo=UTC).timestamp()) in filtered
    # hour before contract
    before = int(datetime(2026, 4, 30, 21, 0, tzinfo=UTC).timestamp())
    hours[before] = {"p_imp": 0.0}
    filtered = filter_hours_by_contract(hours, date(2026, 5, 1))
    assert before not in filtered
    assert len(filtered) == 3

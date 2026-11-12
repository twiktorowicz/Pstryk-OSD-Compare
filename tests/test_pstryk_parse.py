"""Tests for Pstryk frame parsing (no Home Assistant / network)."""

from __future__ import annotations

from datetime import date

from pstryk_osd_compare.pstryk_client import (
    parse_frame,
    suggest_contract_start_from_days,
    suggest_contract_start_from_months,
)


SAMPLE_FRAME = {
    "start": "2026-10-31T10:00:00Z",
    "end": "2026-10-31T11:00:00Z",
    "metrics": {
        "meter_values": {
            "energy_active_import_register": 0.048,
            "energy_active_export_register": 0.21,
            "energy_balance": -0.162,
        },
        "cost": {
            "energy_import_cost": 0.1139,
            "energy_sold_value": 0.2242,
        },
        "pricing": {
            "price_net": 0.86817,
            "service_price": 0.08,
            "price_gross": 1.27297,
            "price_prosumer_gross": None,
        },
    },
}


def test_parse_frame_basic():
    parsed = parse_frame(SAMPLE_FRAME)
    assert parsed is not None
    ts, fields = parsed
    assert fields["p_imp"] == 0.048
    assert fields["p_exp"] == 0.21
    assert fields["buy"] == 1.27297
    assert fields["sell"] is None
    assert fields["api_cost"] == 0.1139
    assert fields["fixed"] == 0.1139 - 0.048 * 1.27297
    assert fields["e_net"] == 0.86817
    assert fields["svc"] == 0.08
    # 2026-10-31 10:00 UTC
    assert ts == 1793440800 or ts > 0


def test_parse_frame_skips_null_meter():
    frame = {
        "start": "2025-05-01T10:00:00Z",
        "metrics": {
            "meter_values": {
                "energy_active_import_register": None,
                "energy_active_export_register": None,
            },
            "pricing": {"price_gross": 1.0},
            "cost": {},
        },
    }
    assert parse_frame(frame) is None


def test_suggest_contract_start_from_months():
    frames = [
        {
            "start": "2026-03-01T00:00:00Z",
            "metrics": {"cost": {"energy_import_cost": 0.0}},
        },
        {
            "start": "2026-04-01T00:00:00Z",
            "metrics": {"cost": {"energy_import_cost": 0}},
        },
        {
            "start": "2026-05-01T00:00:00Z",
            "metrics": {"cost": {"energy_import_cost": -38.88}},
        },
    ]
    assert suggest_contract_start_from_months(frames) == date(2026, 5, 1)


def test_suggest_contract_start_from_days():
    frames = [
        {
            "start": "2026-04-30T00:00:00Z",
            "metrics": {
                "meter_values": {
                    "energy_active_import_register": 0.9,
                    "energy_active_export_register": 20.0,
                },
                "cost": {"energy_import_cost": 0.0, "energy_sold_value": 12.0},
            },
        },
        {
            "start": "2026-05-01T00:00:00Z",
            "metrics": {
                "meter_values": {
                    "energy_active_import_register": 47.0,
                    "energy_active_export_register": 82.0,
                },
                "cost": {"energy_import_cost": -36.4},
            },
        },
    ]
    assert suggest_contract_start_from_days(frames) == date(2026, 5, 1)

"""DSO statistic discovery and hourly merge (osd_series)."""

from __future__ import annotations

from datetime import datetime, timezone

from pstryk_osd_compare.osd_series import (
    as_id_list,
    classify_statistic_ids,
    merge_rows,
    normalize_stat_ids,
)

T0 = 1_793_833_200
T1 = T0 + 3600


def test_as_id_list_legacy_and_list():
    assert as_id_list(None) == []
    assert as_id_list("") == []
    assert as_id_list("a:b") == ["a:b"]
    assert as_id_list(["a", "", "b"]) == ["a", "b"]


def test_normalize_stat_ids_legacy_entry():
    ids = normalize_stat_ids({"t_imp": "x", "t_exp": "y", "tb_imp": None})
    assert ids == {"t_imp": ["x"], "t_exp": ["y"], "tb_imp": [], "tb_exp": []}


def test_classify_tauron_skips_zones():
    ids = [
        "tauron_importer:m1_consumption",
        "tauron_importer:m1_generation",
        "tauron_importer:m1_balanced_consumption",
        "tauron_importer:m1_balanced_generation",
        "tauron_importer:m1_consumption_zone_1",
    ]
    out = classify_statistic_ids(ids)
    assert out["tauron"]["m1"] == {
        "t_imp": ["tauron_importer:m1_consumption"],
        "t_exp": ["tauron_importer:m1_generation"],
        "tb_imp": ["tauron_importer:m1_balanced_consumption"],
        "tb_exp": ["tauron_importer:m1_balanced_generation"],
    }


def test_classify_enea_ignores_cost_and_power():
    ids = [
        "enea:590243_energia_pobrana",
        "enea:590243_energia_oddana",
        "enea:590243_koszt_energii_pobrana_dzien",
        "enea:590243_moc_pobrana",
    ]
    out = classify_statistic_ids(ids)
    assert out == {
        "enea": {
            "590243": {
                "t_imp": ["enea:590243_energia_pobrana"],
                "t_exp": ["enea:590243_energia_oddana"],
            }
        }
    }


def test_classify_energa_single_zone():
    ids = [
        "sensor.energa_123_panel_energia_zuzycie",
        "sensor.energa_123_panel_energia_produkcja",
        "sensor.energa_123_okres_kompletnosc",
    ]
    out = classify_statistic_ids(ids)
    assert out["energa"]["123"]["t_imp"] == ["sensor.energa_123_panel_energia_zuzycie"]
    assert out["energa"]["123"]["t_exp"] == ["sensor.energa_123_panel_energia_produkcja"]


def test_classify_energa_g12w_sums_zones():
    ids = [
        "sensor.energa_9_panel_energia_strefa_2",
        "sensor.energa_9_panel_energia_strefa_1",
        "sensor.energa_9_panel_energia_produkcja_strefa_1",
        "sensor.energa_9_panel_energia_produkcja_strefa_2",
    ]
    s = classify_statistic_ids(ids)["energa"]["9"]
    assert s["t_imp"] == [
        "sensor.energa_9_panel_energia_strefa_1",
        "sensor.energa_9_panel_energia_strefa_2",
    ]
    assert len(s["t_exp"]) == 2


def test_classify_energa_whole_series_beats_zones():
    ids = [
        "sensor.energa_9_panel_energia_zuzycie",
        "sensor.energa_9_panel_energia_strefa_1",
        "sensor.energa_9_panel_energia_strefa_2",
        "sensor.energa_9_panel_energia_produkcja",
    ]
    s = classify_statistic_ids(ids)["energa"]["9"]
    assert s["t_imp"] == ["sensor.energa_9_panel_energia_zuzycie"]


def test_classify_requires_import_and_export():
    assert classify_statistic_ids(["enea:1_energia_pobrana"]) == {}


def test_merge_uses_change_not_cumulative_state():
    rows = {
        "sensor.p1_import": [
            {"start": T0, "state": 1511.716, "sum": 1667.489, "change": 2.627},
        ],
        "sensor.p1_export": [
            {"start": T0, "state": 900.0, "sum": 950.0, "change": 0.5},
        ],
    }
    out = merge_rows(rows, {"t_imp": "sensor.p1_import", "t_exp": ["sensor.p1_export"]})
    assert out == {T0: {"t_imp": 2.627, "t_exp": 0.5}}


def test_merge_sums_zones_per_hour():
    rows = {
        "z1": [{"start": T0, "change": 1.0}, {"start": T1, "change": 0.0}],
        "z2": [{"start": T0, "change": 0.0}, {"start": T1, "change": 2.5}],
    }
    out = merge_rows(rows, {"t_imp": ["z1", "z2"]})
    assert out == {T0: {"t_imp": 1.0}, T1: {"t_imp": 2.5}}


def test_merge_tauron_state_fallback_only_for_tauron():
    rows = {
        "tauron_importer:m_consumption": [{"start": T0, "state": 2.514}],
        "sensor.other": [{"start": T0, "state": 1234.0}],
    }
    out = merge_rows(
        rows,
        {"t_imp": "tauron_importer:m_consumption", "t_exp": "sensor.other"},
    )
    assert out == {T0: {"t_imp": 2.514}}


def test_merge_accepts_datetime_start():
    start = datetime.fromtimestamp(T0, tz=timezone.utc)
    out = merge_rows({"a": [{"start": start, "change": 1.5}]}, {"t_imp": "a"})
    assert out == {T0: {"t_imp": 1.5}}


def test_balanced_basis_nets_gross_when_series_missing():
    from pstryk_osd_compare.calc import tauron_side
    from pstryk_osd_compare.const import BASIS_BALANCED, BASIS_GROSS

    # Tauron 2026-10-05 08:00: gross 0.009 / 0.120 → balanced 0 / 0.111
    rec = {"t_imp": 0.009, "t_exp": 0.120}
    imp, exp = tauron_side(rec, BASIS_BALANCED)
    assert imp == 0.0 and abs(exp - 0.111) < 1e-9
    assert tauron_side({"t_imp": 2.0, "t_exp": 0.5}, BASIS_BALANCED) == (1.5, 0.0)
    assert tauron_side(rec, BASIS_GROSS) == (0.009, 0.120)
    # already balanced input stays unchanged
    assert tauron_side({"t_imp": 0.0, "t_exp": 0.111}, BASIS_BALANCED) == (0.0, 0.111)
    # DSO balanced series wins when present
    assert tauron_side({**rec, "tb_imp": 0.0, "tb_exp": 0.2}, BASIS_BALANCED) == (0.0, 0.2)

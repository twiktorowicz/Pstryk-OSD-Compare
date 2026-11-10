"""Config entry migration 1.1 → 1.2 (pure helpers)."""

from __future__ import annotations

from pstryk_osd_compare.const import METRICS
from pstryk_osd_compare.migration import (
    RENAMED_ENTITIES,
    RENAMED_METRICS,
    new_entity_id_for,
    old_statistic_ids,
)


def test_renamed_metrics_exist_and_old_are_gone():
    for old, new in RENAMED_METRICS.items():
        assert new in METRICS
        assert old not in METRICS
    assert not any(k.startswith("tauron") for k in METRICS)


def test_old_statistic_ids():
    ids = old_statistic_ids("1902099_60181589_1902099")
    assert "pstryk_osd_compare:1902099_60181589_1902099_tauron_import" in ids
    assert "pstryk_osd_compare:1902099_60181589_1902099_tauron_invoice_cost" in ids
    assert len(ids) == 5


def test_entity_rename_default_and_suffix():
    old, new = RENAMED_ENTITIES["deposit_tauron"]
    assert new_entity_id_for(old, old, new) == "sensor.osd_depozyt_osd"
    assert new_entity_id_for(old + "_2", old, new) == "sensor.osd_depozyt_osd_2"


def test_entity_rename_keeps_user_choice():
    old, new = RENAMED_ENTITIES["deposit_tauron"]
    assert new_entity_id_for("sensor.my_deposit", old, new) is None
    # settled sensor must not be mistaken for a suffixed plain one
    assert new_entity_id_for("sensor.osd_depozyt_tauron_rozliczony", old, new) is None
    o2, n2 = RENAMED_ENTITIES["deposit_tauron_settled"]
    assert new_entity_id_for(o2, o2, n2) == "sensor.osd_depozyt_osd_rozliczony"

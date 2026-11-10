"""Pure helpers: recognise DSO statistic series and turn Recorder rows into hourly kWh.

No Home Assistant imports — unit-testable.

Hourly value = ``change`` of a ``has_sum`` statistic. For ``tauron_importer:*`` the
``state`` column also holds the hourly value (non-standard), but for regular sensors
(Energa „Panel Energia”, P1 / wM-Bus meters) ``state`` is the cumulative meter reading.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .const import DOMAIN

PROVIDER_TAURON = "tauron"
PROVIDER_ENEA = "enea"
PROVIDER_ENERGA = "energa"

KEYS = ("t_imp", "t_exp", "tb_imp", "tb_exp")

_TAURON_SUFFIXES = (
    ("_balanced_consumption", "tb_imp"),
    ("_balanced_generation", "tb_exp"),
    ("_consumption", "t_imp"),
    ("_generation", "t_exp"),
)
_ENEA_SUFFIXES = (
    ("_energia_pobrana", "t_imp"),
    ("_energia_oddana", "t_exp"),
)
# Energa (ergo5/hass-energa-my-meter-api and lkusinski fork): sensor.energa_{serial}_panel_energia_*
# G12/G12w split into two zones — both are summed into one series.
_ENERGA_RE = re.compile(
    r"^sensor\.energa_(?P<meter>.+?)_panel_energia_"
    r"(?P<kind>zuzycie|produkcja|strefa_[12]|produkcja_strefa_[12])$"
)
_ENERGA_KEY = {
    "zuzycie": "t_imp",
    "strefa_1": "t_imp",
    "strefa_2": "t_imp",
    "produkcja": "t_exp",
    "produkcja_strefa_1": "t_exp",
    "produkcja_strefa_2": "t_exp",
}

UTC = timezone.utc


def statistic_id_for(meter_slug: str, metric: str) -> str:
    slug = "".join(c if c.isalnum() or c == "_" else "_" for c in meter_slug.lower())
    return f"{DOMAIN}:{slug}_{metric}"


def as_id_list(value: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Config value (legacy str or list) → list of statistic ids."""
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [v for v in value if v]


def normalize_stat_ids(stat_ids: dict[str, Any] | None) -> dict[str, list[str]]:
    return {k: as_id_list((stat_ids or {}).get(k)) for k in KEYS}


def classify_statistic_ids(ids: list[str]) -> dict[str, dict[str, dict[str, list[str]]]]:
    """Group known DSO series: {provider: {meter_id: {key: [statistic_id, …]}}}."""
    out: dict[str, dict[str, dict[str, list[str]]]] = {}

    def add(provider: str, meter: str, key: str, sid: str) -> None:
        series = out.setdefault(provider, {}).setdefault(meter, {}).setdefault(key, [])
        if sid not in series:
            series.append(sid)

    for sid in ids:
        if sid.startswith("tauron_importer:"):
            if "_zone_" in sid:
                continue
            body = sid.split(":", 1)[1]
            for suffix, key in _TAURON_SUFFIXES:
                if body.endswith(suffix):
                    add(PROVIDER_TAURON, body[: -len(suffix)], key, sid)
                    break
        elif sid.startswith("enea:"):
            body = sid.split(":", 1)[1]
            for suffix, key in _ENEA_SUFFIXES:
                if body.endswith(suffix):
                    add(PROVIDER_ENEA, body[: -len(suffix)], key, sid)
                    break
        else:
            m = _ENERGA_RE.match(sid)
            if m:
                add(PROVIDER_ENERGA, m.group("meter"), _ENERGA_KEY[m.group("kind")], sid)

    # Energa: single-zone series win over zone series if both exist (tariff change)
    for series in out.get(PROVIDER_ENERGA, {}).values():
        for key, single in (("t_imp", "_panel_energia_zuzycie"), ("t_exp", "_panel_energia_produkcja")):
            ids_k = series.get(key) or []
            whole = [s for s in ids_k if s.endswith(single)]
            if whole and len(ids_k) > 1:
                series[key] = whole
        for key in KEYS:
            if key in series:
                series[key].sort()

    # usable = has import and export
    for provider in list(out):
        out[provider] = {
            m: s for m, s in out[provider].items() if s.get("t_imp") and s.get("t_exp")
        }
        if not out[provider]:
            del out[provider]
    return out


def normalize_start(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp())
    return None


def row_hourly_value(statistic_id: str, row: dict[str, Any]) -> float | None:
    change = row.get("change")
    if change is not None:
        return float(change)
    if statistic_id.startswith("tauron_importer:"):
        state = row.get("state")
        return float(state) if state is not None else None
    return None


def merge_rows(
    rows: dict[str, list[dict[str, Any]]], stat_ids: dict[str, Any]
) -> dict[int, dict[str, float]]:
    """{statistic_id: rows} → {ts: {key: kWh}}; several ids per key are summed (zones)."""
    ids = normalize_stat_ids(stat_ids)
    out: dict[int, dict[str, float]] = {}
    for key, sids in ids.items():
        for sid in sids:
            for row in rows.get(sid) or []:
                ts = normalize_start(row.get("start"))
                val = row_hourly_value(sid, row)
                if ts is None or val is None:
                    continue
                rec = out.setdefault(ts, {})
                rec[key] = rec.get(key, 0.0) + val
    return out

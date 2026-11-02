"""Diagnostics for Pstryk OSD Compare (no secrets)."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import CONF_API_KEY, CONF_METER_ID, CONF_STAT_IDS, DOMAIN


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    data = hass.data.get(DOMAIN, {}).get(entry.entry_id) or {}
    coordinator = data.get("coordinator")
    store = data.get("store")
    safe_data = {k: v for k, v in entry.data.items() if k != CONF_API_KEY}
    out: dict[str, Any] = {
        "data": safe_data,
        "options": dict(entry.options),
        "stat_ids": entry.data.get(CONF_STAT_IDS),
        "meter_id": entry.data.get(CONF_METER_ID),
    }
    if store is not None:
        out["store"] = {
            "hours": len(store.hours),
            "last_pstryk_hour": store.data.get("last_pstryk_hour"),
            "last_tauron_hour": store.data.get("last_tauron_hour"),
            "last_sync": store.data.get("last_sync"),
            "tauron_backfill_requested": store.data.get("tauron_backfill_requested"),
        }
    if coordinator is not None and coordinator.data is not None:
        d = coordinator.data
        out["coordinator"] = {
            "hours_pstryk": d.hours_pstryk,
            "hours_tauron": d.hours_tauron,
            "hours_matched": d.hours_matched,
            "errors": d.errors,
            "analysis_day": d.analysis_day.isoformat() if d.analysis_day else None,
            "coverage_percent": (d.coverage or {}).get("percent"),
            "deposit_pstryk": d.deposit_pstryk,
            "deposit_tauron": d.deposit_tauron,
            "deposit_diff": (
                round(d.deposit_pstryk - d.deposit_tauron, 2)
                if d.deposit_pstryk is not None and d.deposit_tauron is not None
                else None
            ),
            "deposit_settled_through": d.deposit_settled_through,
            "deposit_pstryk_settled": d.deposit_pstryk_settled,
            "deposit_tauron_settled": d.deposit_tauron_settled,
            "deposit_months": len(d.deposit_pstryk_ledger),
        }
    return out

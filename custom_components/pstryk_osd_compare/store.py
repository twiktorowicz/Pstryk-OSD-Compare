"""Persistent hour store for Pstryk OSD Compare."""

from __future__ import annotations

import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc
STORAGE_VERSION = 1


def _empty_data() -> dict[str, Any]:
    return {
        "hours": {},
        "last_pstryk_hour": None,
        "last_tauron_hour": None,
        "last_sync": None,
        "tauron_backfill_requested": None,
        "tauron_backfill_at": None,
    }


class CompareStore:
    """Load / merge / save hour records keyed by UTC hour timestamp (str in JSON)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}_{entry_id}"
        )
        self.data: dict[str, Any] = _empty_data()

    async def async_load(self) -> None:
        raw = await self._store.async_load()
        if not raw:
            self.data = _empty_data()
            return
        hours_raw = raw.get("hours") or {}
        hours: dict[int, dict[str, Any]] = {}
        for key, rec in hours_raw.items():
            hours[int(key)] = dict(rec)
        self.data = {
            "hours": hours,
            "last_pstryk_hour": raw.get("last_pstryk_hour"),
            "last_tauron_hour": raw.get("last_tauron_hour"),
            "last_sync": raw.get("last_sync"),
            "tauron_backfill_requested": raw.get("tauron_backfill_requested"),
            "tauron_backfill_at": raw.get("tauron_backfill_at"),
        }

    def _serializable(self) -> dict[str, Any]:
        hours = {str(ts): rec for ts, rec in sorted(self.data["hours"].items())}
        return {
            "hours": hours,
            "last_pstryk_hour": self.data.get("last_pstryk_hour"),
            "last_tauron_hour": self.data.get("last_tauron_hour"),
            "last_sync": self.data.get("last_sync"),
            "tauron_backfill_requested": self.data.get("tauron_backfill_requested"),
            "tauron_backfill_at": self.data.get("tauron_backfill_at"),
        }

    def async_schedule_save(self) -> None:
        self._store.async_delay_save(self._serializable, 10)

    async def async_save(self) -> None:
        await self._store.async_save(self._serializable())

    @property
    def hours(self) -> dict[int, dict[str, Any]]:
        return self.data["hours"]

    def merge_pstryk(self, updates: dict[int, dict[str, Any]]) -> set[int]:
        """Merge Pstryk fields; return timestamps that changed."""
        changed: set[int] = set()
        hours = self.data["hours"]
        for ts, fields in updates.items():
            existing = hours.get(ts)
            if existing is None:
                hours[ts] = dict(fields)
                changed.add(ts)
            else:
                before = deepcopy(existing)
                existing.update(fields)
                if existing != before:
                    changed.add(ts)
            lp = self.data.get("last_pstryk_hour")
            if lp is None or ts > lp:
                self.data["last_pstryk_hour"] = ts
        return changed

    def merge_tauron(self, updates: dict[int, dict[str, Any]]) -> set[int]:
        """Merge OSD/Tauron fields (t_imp/t_exp/tb_*); return changed timestamps."""
        changed: set[int] = set()
        hours = self.data["hours"]
        for ts, fields in updates.items():
            existing = hours.get(ts)
            if existing is None:
                # OSD-only hour — keep for coverage; not matched until Pstryk arrives
                hours[ts] = dict(fields)
                changed.add(ts)
            else:
                before = deepcopy(existing)
                for key, value in fields.items():
                    if value is None:
                        continue
                    old = existing.get(key)
                    if old is None or abs(float(old) - float(value)) > 1e-6:
                        existing[key] = value
                if existing != before:
                    changed.add(ts)
            lt = self.data.get("last_tauron_hour")
            if lt is None or ts > lt:
                self.data["last_tauron_hour"] = ts
        return changed

    def mark_synced(self) -> None:
        self.data["last_sync"] = datetime.now(tz=UTC).isoformat()

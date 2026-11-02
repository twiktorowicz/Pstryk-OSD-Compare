"""Read / discover OSD statistics from the Home Assistant Recorder."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.statistics import (
    list_statistic_ids,
    statistics_during_period,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import TAURON_STAT_PREFIX

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc

SUFFIX_CONSUMPTION = "_consumption"
SUFFIX_GENERATION = "_generation"
SUFFIX_BAL_CONSUMPTION = "_balanced_consumption"
SUFFIX_BAL_GENERATION = "_balanced_generation"


@dataclass(frozen=True)
class TauronMeterInfo:
    """Discovered Tauron importer meter."""

    meter_id: str
    meter_name: str | None
    entry_id: str | None
    title: str | None
    has_balanced: bool
    last_data: datetime | None
    stat_ids: dict[str, str | None]


def default_stat_ids(meter_id: str) -> dict[str, str | None]:
    mid = meter_id.lower()
    return {
        "t_imp": f"{TAURON_STAT_PREFIX}:{mid}{SUFFIX_CONSUMPTION}",
        "t_exp": f"{TAURON_STAT_PREFIX}:{mid}{SUFFIX_GENERATION}",
        "tb_imp": f"{TAURON_STAT_PREFIX}:{mid}{SUFFIX_BAL_CONSUMPTION}",
        "tb_exp": f"{TAURON_STAT_PREFIX}:{mid}{SUFFIX_BAL_GENERATION}",
    }


def _normalize_start(value: Any) -> int | None:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return int(value.timestamp())
    return None


async def async_list_statistic_ids(hass: HomeAssistant) -> list[dict[str, Any]]:
    return await get_instance(hass).async_add_executor_job(
        list_statistic_ids, hass, None, "sum"
    )


async def async_discover_tauron_meters(hass: HomeAssistant) -> list[TauronMeterInfo]:
    """Group tauron_importer:* series by meter_id (skip zone series)."""
    ids = await async_list_statistic_ids(hass)
    by_meter: dict[str, dict[str, str]] = {}
    for item in ids:
        sid = item.get("statistic_id") or ""
        if not sid.startswith(f"{TAURON_STAT_PREFIX}:"):
            continue
        if "_zone_" in sid:
            continue
        body = sid.split(":", 1)[1]
        for suffix, key in (
            (SUFFIX_BAL_CONSUMPTION, "tb_imp"),
            (SUFFIX_BAL_GENERATION, "tb_exp"),
            (SUFFIX_CONSUMPTION, "t_imp"),
            (SUFFIX_GENERATION, "t_exp"),
        ):
            if body.endswith(suffix):
                meter_id = body[: -len(suffix)]
                by_meter.setdefault(meter_id, {})[key] = sid
                break

    # Map config entries for labels / options
    entries = {
        (e.data.get("energy_meter_id") or "").lower(): e
        for e in hass.config_entries.async_entries("tauron_amiplus")
    }

    meters: list[TauronMeterInfo] = []
    now = datetime.now(tz=UTC)
    for meter_id, stats in sorted(by_meter.items()):
        if "t_imp" not in stats or "t_exp" not in stats:
            continue
        entry = entries.get(meter_id)
        last = await async_last_statistic_time(hass, stats["t_imp"])
        # Prefer meters with recent data
        meters.append(
            TauronMeterInfo(
                meter_id=meter_id,
                meter_name=(entry.data.get("energy_meter_name") if entry else None),
                entry_id=entry.entry_id if entry else None,
                title=entry.title if entry else None,
                has_balanced="tb_imp" in stats and "tb_exp" in stats,
                last_data=last,
                stat_ids={
                    "t_imp": stats.get("t_imp"),
                    "t_exp": stats.get("t_exp"),
                    "tb_imp": stats.get("tb_imp"),
                    "tb_exp": stats.get("tb_exp"),
                },
            )
        )

    # Sort: freshest first; drop ancient PPE series to the end
    def _sort_key(m: TauronMeterInfo) -> tuple:
        stale = 0 if (m.last_data and (now - m.last_data).days < 14) else 1
        return (stale, -(m.last_data.timestamp() if m.last_data else 0))

    meters.sort(key=_sort_key)
    return meters


async def async_last_statistic_time(
    hass: HomeAssistant, statistic_id: str
) -> datetime | None:
    end = datetime.now(tz=UTC)
    start = end - timedelta(days=14)
    rows = await async_fetch_statistic_rows(hass, [statistic_id], start, end)
    series = rows.get(statistic_id) or []
    if not series:
        # Try longer lookback for discovery label only
        start = end - timedelta(days=400)
        rows = await async_fetch_statistic_rows(hass, [statistic_id], start, end)
        series = rows.get(statistic_id) or []
    if not series:
        return None
    ts = _normalize_start(series[-1].get("start"))
    return datetime.fromtimestamp(ts, tz=UTC) if ts is not None else None


async def async_fetch_statistic_rows(
    hass: HomeAssistant,
    statistic_ids: list[str],
    start: datetime,
    end: datetime,
) -> dict[str, list[dict[str, Any]]]:
    ids = {s for s in statistic_ids if s}
    if not ids:
        return {}
    return await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        start,
        end,
        ids,
        "hour",
        None,
        {"state", "sum"},
    )


async def async_read_osd_hours(
    hass: HomeAssistant,
    stat_ids: dict[str, str | None],
    start: datetime,
    end: datetime,
) -> dict[int, dict[str, Any]]:
    """Return {ts: {t_imp, t_exp, tb_imp, tb_exp}} from Recorder LTS."""
    id_list = [v for v in stat_ids.values() if v]
    rows = await async_fetch_statistic_rows(hass, id_list, start, end)
    by_ts: dict[int, dict[str, Any]] = {}

    key_by_id = {v: k for k, v in stat_ids.items() if v}
    for sid, series in rows.items():
        field = key_by_id.get(sid)
        if not field:
            continue
        for row in series:
            ts = _normalize_start(row.get("start"))
            if ts is None:
                continue
            state = row.get("state")
            if state is None:
                continue
            by_ts.setdefault(ts, {})[field] = float(state)

    return by_ts


async def async_find_tauron_device_id(
    hass: HomeAssistant, meter_id: str
) -> str | None:
    """Device id for tauron_amiplus.download_statistics."""
    entry = async_find_tauron_entry(hass, meter_id)
    if entry is None:
        return None
    registry = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(registry, entry.entry_id)
    if not devices:
        return None
    return devices[0].id


def async_find_tauron_entry(hass: HomeAssistant, meter_id: str) -> ConfigEntry | None:
    mid = meter_id.lower()
    for entry in hass.config_entries.async_entries("tauron_amiplus"):
        if (entry.data.get("energy_meter_id") or "").lower() == mid:
            return entry
    return None


async def async_request_tauron_backfill(
    hass: HomeAssistant, meter_id: str, start_date: date
) -> bool:
    """Call tauron_amiplus.download_statistics. Returns True if service was called."""
    device_id = await async_find_tauron_device_id(hass, meter_id)
    if device_id is None:
        _LOGGER.warning(
            "Cannot backfill Tauron for %s — no device for config entry", meter_id
        )
        return False
    await hass.services.async_call(
        "tauron_amiplus",
        "download_statistics",
        {"device_id": device_id, "start_date": start_date.isoformat()},
        blocking=True,
    )
    _LOGGER.info(
        "Requested Tauron download_statistics from %s (device %s)",
        start_date,
        device_id,
    )
    return True

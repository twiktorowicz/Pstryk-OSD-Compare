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
from .osd_series import (
    KEYS,
    PROVIDER_ENEA,
    PROVIDER_TAURON,
    classify_statistic_ids,
    merge_rows,
    normalize_start,
    normalize_stat_ids,
)

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc

SUFFIX_CONSUMPTION = "_consumption"
SUFFIX_GENERATION = "_generation"
SUFFIX_BAL_CONSUMPTION = "_balanced_consumption"
SUFFIX_BAL_GENERATION = "_balanced_generation"

_PROVIDER_ENTRY_DOMAIN = {
    PROVIDER_TAURON: "tauron_amiplus",
    PROVIDER_ENEA: "enea",
}


@dataclass(frozen=True)
class OsdMeterInfo:
    """Discovered DSO meter (Tauron importer, Enea, Energa)."""

    provider: str
    meter_id: str
    meter_name: str | None
    entry_id: str | None
    title: str | None
    has_balanced: bool
    last_data: datetime | None
    stat_ids: dict[str, list[str]]


TauronMeterInfo = OsdMeterInfo


def default_stat_ids(meter_id: str) -> dict[str, str | None]:
    mid = meter_id.lower()
    return {
        "t_imp": f"{TAURON_STAT_PREFIX}:{mid}{SUFFIX_CONSUMPTION}",
        "t_exp": f"{TAURON_STAT_PREFIX}:{mid}{SUFFIX_GENERATION}",
        "tb_imp": f"{TAURON_STAT_PREFIX}:{mid}{SUFFIX_BAL_CONSUMPTION}",
        "tb_exp": f"{TAURON_STAT_PREFIX}:{mid}{SUFFIX_BAL_GENERATION}",
    }


async def async_list_statistic_ids(hass: HomeAssistant) -> list[dict[str, Any]]:
    return await get_instance(hass).async_add_executor_job(
        list_statistic_ids, hass, None, "sum"
    )


def _entry_for(hass: HomeAssistant, provider: str, meter_id: str) -> ConfigEntry | None:
    domain = _PROVIDER_ENTRY_DOMAIN.get(provider)
    if domain is None:
        return None
    mid = meter_id.lower()
    for entry in hass.config_entries.async_entries(domain):
        if provider == PROVIDER_TAURON:
            key = entry.data.get("energy_meter_id")
        else:
            key = entry.data.get("meter_code") or entry.unique_id
        if (str(key or "")).lower() == mid:
            return entry
    return None


async def async_discover_osd_meters(hass: HomeAssistant) -> list[OsdMeterInfo]:
    """Known DSO series in the Recorder, freshest meters first."""
    ids = [i.get("statistic_id") or "" for i in await async_list_statistic_ids(hass)]
    grouped = classify_statistic_ids(ids)

    meters: list[OsdMeterInfo] = []
    now = datetime.now(tz=UTC)
    for provider, by_meter in grouped.items():
        for meter_id, stats in sorted(by_meter.items()):
            entry = _entry_for(hass, provider, meter_id)
            last = await async_last_statistic_time(hass, stats["t_imp"][0])
            name = None
            if entry is not None and provider == PROVIDER_TAURON:
                name = entry.data.get("energy_meter_name")
            meters.append(
                OsdMeterInfo(
                    provider=provider,
                    meter_id=meter_id,
                    meter_name=name,
                    entry_id=entry.entry_id if entry else None,
                    title=entry.title if entry else None,
                    has_balanced=bool(stats.get("tb_imp") and stats.get("tb_exp")),
                    last_data=last,
                    stat_ids={k: list(stats.get(k) or []) for k in KEYS},
                )
            )

    def _sort_key(m: OsdMeterInfo) -> tuple:
        stale = 0 if (m.last_data and (now - m.last_data).days < 14) else 1
        return (stale, -(m.last_data.timestamp() if m.last_data else 0))

    meters.sort(key=_sort_key)
    return meters


async def async_discover_tauron_meters(hass: HomeAssistant) -> list[OsdMeterInfo]:
    return [
        m for m in await async_discover_osd_meters(hass) if m.provider == PROVIDER_TAURON
    ]


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
    ts = normalize_start(series[-1].get("start"))
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
        {"state", "sum", "change"},
    )


async def async_read_osd_hours(
    hass: HomeAssistant,
    stat_ids: dict[str, Any],
    start: datetime,
    end: datetime,
) -> dict[int, dict[str, Any]]:
    """Return {ts: {t_imp, t_exp, tb_imp, tb_exp}} (kWh per hour) from Recorder LTS."""
    ids = normalize_stat_ids(stat_ids)
    id_list = sorted({sid for sids in ids.values() for sid in sids})
    rows = await async_fetch_statistic_rows(hass, id_list, start, end)
    return merge_rows(rows, ids)


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

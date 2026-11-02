"""The Pstryk OSD Compare integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "date", "select", "number", "text", "button"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up from a config entry."""
    from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady

    from .coordinator import CompareCoordinator
    from .fv import FvDraft
    from .services import async_setup_services
    from .store import CompareStore

    store = CompareStore(hass, entry.entry_id)
    await store.async_load()

    coordinator = CompareCoordinator(hass, entry, store)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
        "store": store,
        "fv_draft": FvDraft(),
    }

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await async_setup_services(hass)

    if store.hours:
        try:
            await coordinator.async_config_entry_first_refresh()
        except ConfigEntryAuthFailed:
            raise
        except Exception as err:  # noqa: BLE001
            raise ConfigEntryNotReady(str(err)) from err
    else:
        entry.async_create_background_task(
            hass, _initial_backfill(coordinator), "pstryk_osd_compare_initial_backfill"
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _initial_backfill(coordinator: Any) -> None:
    from homeassistant.exceptions import ConfigEntryAuthFailed

    try:
        await coordinator.async_refresh()
    except ConfigEntryAuthFailed:
        _LOGGER.error("Pstryk auth failed during initial backfill")
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Initial backfill failed")


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if data and "store" in data:
            await data["store"].async_save()
    return unload_ok

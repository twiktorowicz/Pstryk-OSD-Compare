"""Config entry migration 1.1 → 1.2: operator-neutral names (tauron_* → osd_*).

External statistics cannot be renamed (Recorder renames only its own ``recorder``
source), but they are derived data: every sync rewrites the full series from the
Store. Old series are cleared and the first sync after migration writes them under
the new statistic_id.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .osd_series import statistic_id_for

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

RENAMED_METRICS = {
    "tauron_import": "osd_import",
    "tauron_export": "osd_export",
    "tauron_buy_value": "osd_buy_value",
    "tauron_sell_value": "osd_sell_value",
    "tauron_invoice_cost": "osd_invoice_cost",
}

# unique_id suffix → (old default entity_id, new entity_id)
RENAMED_ENTITIES = {
    "deposit_tauron": ("sensor.osd_depozyt_tauron", "sensor.osd_depozyt_osd"),
    "deposit_tauron_settled": (
        "sensor.osd_depozyt_tauron_rozliczony",
        "sensor.osd_depozyt_osd_rozliczony",
    ),
}


def old_statistic_ids(meter_slug: str) -> list[str]:
    return [statistic_id_for(meter_slug, m) for m in RENAMED_METRICS]


def new_entity_id_for(current: str, old_default: str, new_default: str) -> str | None:
    """New entity_id if ``current`` is still the default (optionally with ``_N`` suffix)."""
    if current == old_default:
        return new_default
    m = re.fullmatch(re.escape(old_default) + r"(_\d+)", current)
    if m:
        return new_default + m.group(1)
    return None


async def async_migrate_v1_2(hass: HomeAssistant, entry: ConfigEntry) -> None:
    from homeassistant.components.recorder import get_instance
    from homeassistant.helpers import entity_registry as er

    from .const import CONF_METER_ID

    registry = er.async_get(hass)
    for suffix, (old_default, new_default) in RENAMED_ENTITIES.items():
        entity_id = registry.async_get_entity_id(
            "sensor", entry.domain, f"{entry.entry_id}_{suffix}"
        )
        if entity_id is None:
            continue
        target = new_entity_id_for(entity_id, old_default, new_default)
        if target is None:
            _LOGGER.info("Keeping user-defined entity_id %s", entity_id)
            continue
        if registry.async_get(target) is not None:
            _LOGGER.warning("Cannot rename %s → %s: target exists", entity_id, target)
            continue
        registry.async_update_entity(entity_id, new_entity_id=target)
        _LOGGER.info("Renamed %s → %s", entity_id, target)

    meter = entry.data.get(CONF_METER_ID) or "meter"
    old_ids = old_statistic_ids(meter)
    get_instance(hass).async_clear_statistics(old_ids)
    _LOGGER.info("Cleared legacy statistics %s (rewritten as osd_* on next sync)", old_ids)

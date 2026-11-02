"""FV form: invoice number."""

from __future__ import annotations

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .fv import FvDraft, get_draft
from .sensor import _device_info, osd_entity_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([FvNumberText(entry, get_draft(hass, entry.entry_id))])


class FvNumberText(TextEntity):
    """Invoice number of the FV draft, e.g. SE/P/1234/09/2026."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:pound"
    _attr_native_max = 64

    def __init__(self, entry: ConfigEntry, draft: FvDraft) -> None:
        self._draft = draft
        self._attr_unique_id = f"{entry.entry_id}_fv_number"
        self._attr_name = "FV numer"
        self.entity_id = osd_entity_id("text", "FV numer")
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._draft.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> str:
        return self._draft.number

    async def async_set_value(self, value: str) -> None:
        self._draft.number = value
        self.async_write_ha_state()

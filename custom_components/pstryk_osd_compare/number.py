"""FV form: invoice amounts."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .fv import FvDraft, get_draft
from .sensor import _device_info, osd_entity_id

FIELDS = (
    ("invoice", "FV faktura", "mdi:file-document"),
    ("deposit_used", "FV z depozytu", "mdi:piggy-bank-outline"),
    ("bonus", "FV bonus", "mdi:gift-outline"),
    ("shield", "FV tarcza", "mdi:shield-check-outline"),
    ("wallet", "FV portfel", "mdi:wallet-outline"),
    ("inflow", "FV oddana energia", "mdi:transmission-tower-export"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    draft = get_draft(hass, entry.entry_id)
    async_add_entities(
        FvAmountNumber(entry, draft, key, name, icon) for key, name, icon in FIELDS
    )


class FvAmountNumber(NumberEntity):
    """One PLN field of the FV draft (not persisted until Save)."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = 0.0
    _attr_native_max_value = 1_000_000.0
    _attr_native_step = 0.01
    _attr_native_unit_of_measurement = "PLN"

    def __init__(
        self, entry: ConfigEntry, draft: FvDraft, key: str, name: str, icon: str
    ) -> None:
        self._draft = draft
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_fv_{key}"
        self._attr_name = name
        self.entity_id = osd_entity_id("number", name)
        self._attr_icon = icon
        self._attr_device_info = _device_info(entry)

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._draft.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> float | None:
        return self._draft.values.get(self._key)

    async def async_set_native_value(self, value: float) -> None:
        self._draft.values[self._key] = round(float(value), 2)
        self.async_write_ha_state()

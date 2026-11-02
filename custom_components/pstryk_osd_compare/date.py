"""Date entity selecting the analysis day for hourly breakdown."""

from __future__ import annotations

from datetime import date, timedelta

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .calc import find_previous_complete_day
from .const import DOMAIN
from .coordinator import CompareCoordinator
from .sensor import _device_info, osd_entity_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CompareCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([AnalysisDayEntity(coordinator, entry)])


class AnalysisDayEntity(CoordinatorEntity[CompareCoordinator], RestoreEntity, DateEntity):
    """Pick which local day to show in selected_day_hourly."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: CompareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_analysis_day"
        self._attr_name = "Dzień analizy"
        self.entity_id = osd_entity_id("date", "Dzień analizy")
        self._attr_device_info = _device_info(entry)
        self._value: date | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last and last.state not in (None, "unknown", "unavailable"):
            try:
                self._value = date.fromisoformat(last.state)
            except ValueError:
                self._value = None
        if self._value is None:
            self._value = self._default_day()
        await self.coordinator.async_set_analysis_day(self._value)

    def _default_day(self) -> date:
        hours = self.coordinator.store.hours
        found = find_previous_complete_day(hours, date.today())
        return found or (date.today() - timedelta(days=2))

    @property
    def native_value(self) -> date | None:
        return self._value

    async def async_set_value(self, value: date) -> None:
        self._value = value
        await self.coordinator.async_set_analysis_day(value)
        self.async_write_ha_state()

"""FV form: month picker."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import CompareCoordinator
from .fv import (
    closed_months,
    default_month,
    get_draft,
    model_invoice,
    official_months_of,
    prefill,
)
from .sensor import _device_info, osd_entity_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: CompareCoordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([FvMonthSelect(coordinator, entry)])


class FvMonthSelect(CoordinatorEntity[CompareCoordinator], SelectEntity):
    """Choosing a month loads its saved FV (or model values) into the form."""

    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-month"

    def __init__(self, coordinator: CompareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_fv_month"
        self._attr_name = "FV miesiąc"
        self.entity_id = osd_entity_id("select", "FV miesiąc")
        self._attr_device_info = _device_info(entry)
        self._draft = get_draft(coordinator.hass, entry.entry_id)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._draft.add_listener(self.async_write_ha_state))
        self._ensure_month()

    @callback
    def _handle_coordinator_update(self) -> None:
        self._ensure_month()
        super()._handle_coordinator_update()

    def _rows(self) -> list[dict[str, Any]]:
        d = self.coordinator.data
        return d.monthly_rows if d else []

    def _ensure_month(self) -> None:
        if self._draft.month is None or self._draft.month not in self.options:
            month = default_month(self._rows())
            if month:
                self._load(month)

    def _load(self, month: str) -> None:
        d = self.coordinator.data
        values, number = prefill(
            month,
            official_months_of(self._entry),
            d.month_model if d else {},
            d.monthly_fee if d else 0.0,
        )
        self._draft.load(month, values, number)

    @property
    def options(self) -> list[str]:
        return closed_months(self._rows())

    @property
    def current_option(self) -> str | None:
        return self._draft.month

    async def async_select_option(self, option: str) -> None:
        self._load(option)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        month = self._draft.month
        official = official_months_of(self._entry)
        rows = {r["month"]: r for r in self._rows()}
        model = (d.month_model.get(month) if d and month else None) or {}
        fee = d.monthly_fee if d else 0.0
        shield_avg = model.get("p_shield_avg")
        return {
            "saved_fv": official.get(month) if month else None,
            "model_invoice": model_invoice(model, fee) if model else None,
            "model_shield": round(model.get("p_shield", 0.0), 2) if model else None,
            "model_shield_avg": round(shield_avg, 4) if shield_avg is not None else None,
            "model_inflow": round(model["p_inflow"], 2) if model else None,
            "missing_fv": [
                m for m in self.options if rows.get(m, {}).get("status") != "fv"
            ],
        }

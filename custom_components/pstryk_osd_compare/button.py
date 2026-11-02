"""FV form: save / delete buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .fv import FvDraft, draft_to_row, get_draft, official_months_of, save_official_month
from .sensor import _device_info, osd_entity_id


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    draft = get_draft(hass, entry.entry_id)
    async_add_entities([FvSaveButton(entry, draft), FvDeleteButton(entry, draft)])


class FvButtonBase(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry: ConfigEntry, draft: FvDraft, key: str, name: str) -> None:
        self._entry = entry
        self._draft = draft
        self._attr_unique_id = f"{entry.entry_id}_fv_{key}"
        self._attr_name = name
        self.entity_id = osd_entity_id("button", name)
        self._attr_device_info = _device_info(entry)

    def _month(self) -> str:
        if not self._draft.month:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="fv_no_month"
            )
        return self._draft.month


class FvSaveButton(FvButtonBase):
    _attr_icon = "mdi:content-save"

    def __init__(self, entry: ConfigEntry, draft: FvDraft) -> None:
        super().__init__(entry, draft, "save", "FV zapisz")

    async def async_press(self) -> None:
        month = self._month()
        if self._draft.values.get("invoice") is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="fv_no_invoice"
            )
        save_official_month(
            self.hass,
            self._entry,
            month,
            draft_to_row(self._draft.values, self._draft.number),
        )


class FvDeleteButton(FvButtonBase):
    _attr_icon = "mdi:delete-outline"

    def __init__(self, entry: ConfigEntry, draft: FvDraft) -> None:
        super().__init__(entry, draft, "delete", "FV usuń")

    async def async_press(self) -> None:
        month = self._month()
        if month not in official_months_of(self._entry):
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="fv_not_saved",
                translation_placeholders={"month": month},
            )
        save_official_month(self.hass, self._entry, month, None)

"""Pstryk invoice (FV) overrides: shared save logic + dashboard form draft."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Any

from .calc import TZ, parse_official_months
from .const import CONF_OFFICIAL_MONTHS, DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

FV_AMOUNT_KEYS = ("invoice", "deposit_used", "bonus", "shield", "wallet", "inflow")


def model_invoice(m: dict[str, Any], monthly_fee: float = 0.0) -> float:
    """Model invoice after the Tarcza Pstryk discount (comparable with FV gross total)."""
    return round(float(m["p_invoice"]) - float(m.get("p_shield", 0.0)) + monthly_fee, 2)


def official_months_of(entry: ConfigEntry) -> dict[str, dict[str, Any]]:
    try:
        return parse_official_months(entry.options.get(CONF_OFFICIAL_MONTHS) or {})
    except ValueError:
        return {}


def save_official_month(
    hass: HomeAssistant,
    entry: ConfigEntry,
    month: str,
    row: dict[str, Any] | None,
) -> dict[str, dict[str, Any]]:
    """Set (row) or remove (None) one FV month in options; options update reloads the entry."""
    official = official_months_of(entry)
    if row:
        official[month] = row
    else:
        official.pop(month, None)
    opts = dict(entry.options)
    opts[CONF_OFFICIAL_MONTHS] = official
    hass.config_entries.async_update_entry(entry, options=opts)
    return official


def closed_months(rows: list[dict[str, Any]], today: datetime | None = None) -> list[str]:
    """Months before the current calendar month (an FV can exist for them)."""
    now = today or datetime.now(tz=TZ)
    current = f"{now.year:04d}-{now.month:02d}"
    return [r["month"] for r in rows if r["month"] < current]


def default_month(rows: list[dict[str, Any]], today: datetime | None = None) -> str | None:
    """First closed month without FV, else the last closed month."""
    months = closed_months(rows, today)
    by_month = {r["month"]: r for r in rows}
    for month in months:
        if by_month[month].get("status") != "fv":
            return month
    return months[-1] if months else None


def prefill(
    month: str,
    official: dict[str, dict[str, Any]],
    model: dict[str, dict[str, Any]],
    monthly_fee: float = 0.0,
) -> tuple[dict[str, float | None], str]:
    """Draft values for a month: saved FV if any, else model invoice/Tarcza/inflow
    (bonus/deposit/wallet empty)."""
    fv = official.get(month)
    if fv:
        values = {k: fv.get(k) for k in FV_AMOUNT_KEYS}
        return values, str(fv.get("number") or "")
    m = model.get(month) or {}
    values: dict[str, float | None] = {k: None for k in FV_AMOUNT_KEYS}
    if m:
        values["invoice"] = model_invoice(m, monthly_fee)
        values["shield"] = round(float(m.get("p_shield", 0.0)), 2)
        values["inflow"] = round(float(m["p_inflow"]), 2)
    return values, ""


def draft_to_row(values: dict[str, float | None], number: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        k: round(float(v), 2) for k, v in values.items() if v is not None
    }
    if number.strip():
        row["number"] = number.strip()
    return row


class FvDraft:
    """In-memory form state shared by the FV select/number/text/button entities."""

    def __init__(self) -> None:
        self.month: str | None = None
        self.values: dict[str, float | None] = {k: None for k in FV_AMOUNT_KEYS}
        self.number: str = ""
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, cb: Callable[[], None]) -> Callable[[], None]:
        self._listeners.append(cb)

        def _remove() -> None:
            if cb in self._listeners:
                self._listeners.remove(cb)

        return _remove

    def notify(self) -> None:
        for cb in list(self._listeners):
            cb()

    def load(self, month: str, values: dict[str, float | None], number: str) -> None:
        self.month = month
        self.values = dict(values)
        self.number = number
        self.notify()


def get_draft(hass: HomeAssistant, entry_id: str) -> FvDraft:
    return hass.data[DOMAIN][entry_id]["fv_draft"]

"""Sensors for Pstryk OSD Compare."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .calc import is_matched
from .const import (
    CONF_CONTRACT_END,
    CONF_CONTRACT_START,
    CONF_METER_ID,
    CONF_METER_NAME,
    DOMAIN,
    METRICS,
    PERIODS,
    SUMMARY_SENSORS,
)
from .coordinator import CompareCoordinator
from .statistics import statistic_id_for

UTC = timezone.utc

PERIOD_LABELS = {
    "current_month": "Bieżący miesiąc",
    "previous_month": "Poprzedni miesiąc",
    "current_year": "Bieżący rok",
    "previous_day": "Poprzedni dzień",
}

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: CompareCoordinator = data["coordinator"]
    entities: list[SensorEntity] = []

    for period in PERIODS:
        for key in SUMMARY_SENSORS:
            entities.append(
                PeriodSummarySensor(coordinator, entry, period, key)
            )

    entities.extend(
        [
            LastSyncSensor(coordinator, entry),
            TauronDataUntilSensor(coordinator, entry),
            CoverageSensor(coordinator, entry),
            DailyBreakdownSensor(coordinator, entry),
            SelectedDayHourlySensor(coordinator, entry),
            DepositSensor(coordinator, entry, "deposit_pstryk", "Depozyt Pstryk"),
            DepositSensor(coordinator, entry, "deposit_tauron", "Depozyt OSD"),
            DepositDiffSensor(coordinator, entry),
            DepositSettledSensor(
                coordinator, entry, "deposit_pstryk_settled", "Depozyt Pstryk rozliczony"
            ),
            DepositSettledSensor(
                coordinator, entry, "deposit_tauron_settled", "Depozyt OSD rozliczony"
            ),
            DepositSettledDiffSensor(coordinator, entry),
            MonthlySensor(coordinator, entry),
        ]
    )
    async_add_entities(entities)


def osd_entity_id(platform: str, name: str) -> str:
    """Fixed short IDs (sensor.osd_miesiace …) so the example dashboard works as-is."""
    return f"{platform}.{slugify(f'osd {name}')}"


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    name = entry.data.get(CONF_METER_NAME) or entry.data.get(CONF_METER_ID) or entry.title
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Pstryk OSD Compare",
        manufacturer="Pstryk OSD Compare",
        model=f"Licznik {name}",
        entry_type=DeviceEntryType.SERVICE,
    )


class CompareSensorBase(CoordinatorEntity[CompareCoordinator], SensorEntity):
    """Base sensor."""

    # Every subclass sets an explicit name: with has_entity_name and no name,
    # ENERGY/MONETARY sensors would all be called "Energia"/"Monetary balance".
    _attr_has_entity_name = True

    def __init__(self, coordinator: CompareCoordinator, entry: ConfigEntry, key: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._key = key
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = _device_info(entry)

    def _set_name(self, name: str) -> None:
        self._attr_name = name
        self.entity_id = osd_entity_id("sensor", name)

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None


class PeriodSummarySensor(CompareSensorBase):
    """Period diff_* summary sensor."""

    def __init__(
        self,
        coordinator: CompareCoordinator,
        entry: ConfigEntry,
        period: str,
        metric: str,
    ) -> None:
        key = f"{period}_{metric}"
        super().__init__(coordinator, entry, key)
        self._period = period
        self._metric = metric
        metric_label = METRICS.get(metric, (None, metric))[1]
        period_label = PERIOD_LABELS.get(period, period)
        self._attr_name = f"{period_label} {metric_label}"
        self.entity_id = f"sensor.osd_{key}"
        if metric.endswith("_value") or "buy" in metric or "sell" in metric or "net" in metric:
            self._attr_native_unit_of_measurement = "PLN"
            self._attr_device_class = SensorDeviceClass.MONETARY
        else:
            self._attr_native_unit_of_measurement = "kWh"
            self._attr_device_class = SensorDeviceClass.ENERGY
        # Values can go down → no state_class
        self._attr_state_class = None

    def _summary(self) -> dict[str, Any]:
        data = self.coordinator.data
        if data and self._period in data.periods:
            return data.periods[self._period]
        return {}

    @property
    def native_value(self) -> float | None:
        s = self._summary()
        if not s or not s.get("hours_matched"):
            return None
        val = s.get(self._metric)
        return float(val) if val is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = dict(self._summary())
        s["basis"] = self.coordinator.basis
        return s


class LastSyncSensor(CompareSensorBase):
    def __init__(self, coordinator: CompareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "last_sync")
        self._set_name("Ostatni sync")
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        raw = (self.coordinator.data.last_sync if self.coordinator.data else None) or (
            self.coordinator.store.data.get("last_sync")
        )
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        if not d:
            return {}
        return {
            "pstryk_hours": d.hours_pstryk,
            "osd_hours": d.hours_tauron,
            "matched_hours": d.hours_matched,
            "errors": d.errors,
        }


class TauronDataUntilSensor(CompareSensorBase):
    def __init__(self, coordinator: CompareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "tauron_data_until")
        self._set_name("Dane do")
        self._attr_device_class = SensorDeviceClass.TIMESTAMP

    @property
    def native_value(self) -> datetime | None:
        hours = self.coordinator.store.hours
        matched_ts = [ts for ts, r in hours.items() if is_matched(r)]
        if not matched_ts:
            return None
        # End of last matched hour
        return datetime.fromtimestamp(max(matched_ts) + 3600, tz=UTC)


class CoverageSensor(CompareSensorBase):
    _unrecorded_attributes = frozenset({"months"})

    def __init__(self, coordinator: CompareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "coverage")
        self._set_name("Pokrycie")
        self._attr_native_unit_of_measurement = "%"

    @property
    def native_value(self) -> float | None:
        d = self.coordinator.data
        if not d or not d.coverage:
            return None
        return d.coverage.get("percent")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        if not d:
            return {}
        return {
            "months": d.coverage.get("months", []),
            "contract_start": self._entry.data.get(CONF_CONTRACT_START),
            "contract_end": self._entry.data.get(CONF_CONTRACT_END),
            "tauron_backfill_requested": self.coordinator.store.data.get(
                "tauron_backfill_requested"
            ),
        }


class DailyBreakdownSensor(CompareSensorBase):
    _unrecorded_attributes = frozenset({"days"})

    def __init__(self, coordinator: CompareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "daily_breakdown")
        self._set_name("Rozbicie dzienne")

    @property
    def native_value(self) -> int | None:
        d = self.coordinator.data
        if not d:
            return None
        return len(d.daily_days)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        return {"days": d.daily_days if d else []}


class SelectedDayHourlySensor(CompareSensorBase):
    _unrecorded_attributes = frozenset({"hours", "summary", "day"})

    def __init__(self, coordinator: CompareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "selected_day_hourly")
        self._set_name("Wybrany dzień")
        self._attr_native_unit_of_measurement = "PLN"
        self._attr_device_class = SensorDeviceClass.MONETARY

    @property
    def native_value(self) -> float | None:
        d = self.coordinator.data
        if not d or not d.selected_day_summary:
            return None
        return d.selected_day_summary.get("diff_net_value")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        if not d:
            return {}
        return {
            "day": d.analysis_day.isoformat() if d.analysis_day else None,
            "hours": d.selected_day_hours,
            "summary": d.selected_day_summary,
        }


class DepositSensor(CompareSensorBase):
    """Running deposit balance through last matched hour (Pstryk or Tauron-valued)."""

    _unrecorded_attributes = frozenset({"ledger"})

    def __init__(
        self,
        coordinator: CompareCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._set_name(name)
        self._attr_native_unit_of_measurement = "PLN"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:piggy-bank"

    @property
    def native_value(self) -> float | None:
        d = self.coordinator.data
        if not d:
            return None
        if self._key == "deposit_pstryk":
            return d.deposit_pstryk
        return d.deposit_tauron

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        if not d:
            return {}
        ledger = (
            d.deposit_pstryk_ledger
            if self._key == "deposit_pstryk"
            else d.deposit_tauron_ledger
        )
        return {
            "ledger": ledger,
            "months": len(ledger),
            "settled_through": d.deposit_settled_through,
            "settled_balance": (
                d.deposit_pstryk_settled
                if self._key == "deposit_pstryk"
                else d.deposit_tauron_settled
            ),
        }


class DepositDiffSensor(CompareSensorBase):
    """deposit_pstryk − deposit_tauron (running)."""

    def __init__(self, coordinator: CompareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "deposit_diff")
        self._set_name("Depozyt różnica")
        self._attr_native_unit_of_measurement = "PLN"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:scale-balance"

    @property
    def native_value(self) -> float | None:
        d = self.coordinator.data
        if not d or d.deposit_pstryk is None or d.deposit_tauron is None:
            return None
        return round(d.deposit_pstryk - d.deposit_tauron, 2)


class DepositSettledSensor(CompareSensorBase):
    """Deposit as shown in Pstryk app until the next invoice (~settlement_day)."""

    def __init__(
        self,
        coordinator: CompareCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
    ) -> None:
        super().__init__(coordinator, entry, key)
        self._set_name(name)
        self._attr_native_unit_of_measurement = "PLN"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:calendar-check"

    @property
    def native_value(self) -> float | None:
        d = self.coordinator.data
        if not d:
            return None
        if self._key == "deposit_pstryk_settled":
            return d.deposit_pstryk_settled
        return d.deposit_tauron_settled

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        if not d:
            return {}
        return {"settled_through": d.deposit_settled_through}


class DepositSettledDiffSensor(CompareSensorBase):
    """Settled deposit_pstryk − deposit_tauron."""

    def __init__(self, coordinator: CompareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "deposit_settled_diff")
        self._set_name("Depozyt różnica rozliczona")
        self._attr_native_unit_of_measurement = "PLN"
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_icon = "mdi:scale-balance"

    @property
    def native_value(self) -> float | None:
        d = self.coordinator.data
        if (
            not d
            or d.deposit_pstryk_settled is None
            or d.deposit_tauron_settled is None
        ):
            return None
        return round(d.deposit_pstryk_settled - d.deposit_tauron_settled, 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        if not d:
            return {}
        return {"settled_through": d.deposit_settled_through}


class MonthlySensor(CompareSensorBase):
    """Per-month measurements + both deposit ledgers (single dashboard source)."""

    _unrecorded_attributes = frozenset({"rows", "totals"})

    def __init__(self, coordinator: CompareCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "monthly")
        self._set_name("Miesiące")
        self._attr_icon = "mdi:calendar-month"

    @property
    def native_value(self) -> int | None:
        d = self.coordinator.data
        if not d:
            return None
        return len(d.monthly_rows)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data
        if not d:
            return {}
        meter = self._entry.data.get(CONF_METER_ID) or "meter"
        return {
            "rows": d.monthly_rows,
            "totals": d.monthly_totals,
            "settled_through": d.deposit_settled_through,
            "basis": self.coordinator.basis,
            "shield_years": d.shield_years,
            "statistics": {
                metric: statistic_id_for(meter, metric)
                for metric in (
                    "pstryk_import",
                    "osd_import",
                    "pstryk_export",
                    "osd_export",
                )
            },
        }

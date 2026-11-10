"""Config flow for Pstryk OSD Compare."""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigEntry, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .calc import parse_official_months
from .const import (
    CONF_API_KEY,
    CONF_BACKFILL_TAURON,
    CONF_CONTRACT_END,
    CONF_CONTRACT_START,
    CONF_DEPOSIT_OPENING_BALANCE,
    CONF_METER_ID,
    CONF_METER_NAME,
    CONF_MONTHLY_ADJUSTMENTS,
    CONF_MONTHLY_FEE,
    CONF_OFFICIAL_MONTHS,
    CONF_SETTLEMENT_DAY,
    CONF_SOURCE_TYPE,
    CONF_STAT_IDS,
    CONF_SYNC_INTERVAL_HOURS,
    CONF_TAURON_BASIS,
    DEFAULT_BACKFILL_TAURON,
    DEFAULT_DEPOSIT_OPENING_BALANCE,
    DEFAULT_MONTHLY_FEE,
    DEFAULT_SETTLEMENT_DAY,
    DEFAULT_SYNC_INTERVAL_HOURS,
    DEFAULT_TAURON_BASIS,
    DOMAIN,
    SOURCE_CUSTOM,
    SOURCE_TAURON,
)
from .pstryk_client import PstrykApiError, PstrykAuthError, PstrykClient
from .osd_series import as_id_list
from .tauron_reader import OsdMeterInfo, async_discover_osd_meters

_LOGGER = logging.getLogger(__name__)

TAURON_HACS_URL = (
    "https://github.com/skoczo/Home-Assistant-custom-components-Tauron-AMIplus"
)
DOCS_URL = "https://github.com/twiktorowicz/Pstryk-OSD-Compare#obsługiwani-operatorzy-osd"
PROVIDER_LABELS = {"tauron": "Tauron", "enea": "Enea", "energa": "Energa"}


class PstrykOsdCompareConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._api_key: str | None = None
        self._meters: list[OsdMeterInfo] = []
        self._source_type: str | None = None
        self._meter_id: str | None = None
        self._meter_name: str | None = None
        self._stat_ids: dict[str, list[str]] = {}
        self._suggested_contract: date | None = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            session = async_get_clientsession(self.hass)
            client = PstrykClient(session, api_key)
            try:
                await client.test_auth()
                self._suggested_contract = await client.detect_contract_start()
            except PstrykAuthError:
                errors["base"] = "invalid_auth"
            except PstrykApiError:
                errors["base"] = "cannot_connect"
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Unexpected error testing Pstryk API")
                errors["base"] = "cannot_connect"
            if not errors:
                self._api_key = api_key
                return await self.async_step_source()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                }
            ),
            errors=errors,
        )

    async def async_step_source(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        self._meters = await async_discover_osd_meters(self.hass)
        errors: dict[str, str] = {}

        if user_input is not None:
            choice = user_input.get("source")
            if choice == "retry":
                self._meters = await async_discover_osd_meters(self.hass)
            elif choice in ("custom", SOURCE_CUSTOM):
                return await self.async_step_custom_stats()
            elif choice and ":" in str(choice):
                provider, meter_id = str(choice).split(":", 1)
                meter = next(
                    (
                        m
                        for m in self._meters
                        if m.provider == provider and m.meter_id == meter_id
                    ),
                    None,
                )
                if meter is None:
                    errors["base"] = "no_tauron_stats"
                else:
                    self._source_type = meter.provider
                    self._meter_id = meter.meter_id
                    self._meter_name = meter.meter_name or meter.title or meter.meter_id
                    self._stat_ids = dict(meter.stat_ids)
                    return await self.async_step_contract()
            else:
                errors["base"] = "no_tauron_stats"

        if not self._meters:
            return self.async_show_form(
                step_id="source",
                data_schema=vol.Schema(
                    {
                        vol.Required("source", default="retry"): selector.SelectSelector(
                            selector.SelectSelectorConfig(
                                options=[
                                    selector.SelectOptionDict(
                                        value="retry",
                                        label="Sprawdź ponownie (po instalacji integracji OSD)",
                                    ),
                                    selector.SelectOptionDict(
                                        value="custom",
                                        label="Wskaż statystyki godzinowe ręcznie",
                                    ),
                                ],
                                mode=selector.SelectSelectorMode.LIST,
                            )
                        )
                    }
                ),
                description_placeholders={"tauron_url": TAURON_HACS_URL, "docs_url": DOCS_URL},
                errors=errors,
            )

        options = [
            selector.SelectOptionDict(
                value=f"{m.provider}:{m.meter_id}",
                label=_meter_label(m),
            )
            for m in self._meters
        ]
        options.append(
            selector.SelectOptionDict(
                value="custom", label="Wskaż statystyki godzinowe ręcznie"
            )
        )
        return self.async_show_form(
            step_id="source",
            data_schema=vol.Schema(
                {
                    vol.Required("source", default=options[0]["value"]): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=options,
                            mode=selector.SelectSelectorMode.LIST,
                        )
                    )
                }
            ),
            description_placeholders={"tauron_url": TAURON_HACS_URL, "docs_url": DOCS_URL},
            errors=errors,
        )

    async def async_step_custom_stats(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            imp = as_id_list(user_input.get("import_stat"))
            exp = as_id_list(user_input.get("export_stat"))
            tb_imp = as_id_list(user_input.get("balanced_import_stat"))
            tb_exp = as_id_list(user_input.get("balanced_export_stat"))
            if not imp or not exp or bool(tb_imp) != bool(tb_exp):
                errors["base"] = "invalid_custom_stats"
            else:
                self._source_type = SOURCE_CUSTOM
                self._meter_id = imp[0].replace(":", "_").lower()
                self._meter_name = "custom"
                self._stat_ids = {
                    "t_imp": imp,
                    "t_exp": exp,
                    "tb_imp": tb_imp,
                    "tb_exp": tb_exp,
                }
                return await self.async_step_contract()

        multi = selector.StatisticSelectorConfig(multiple=True)

        return self.async_show_form(
            step_id="custom_stats",
            data_schema=vol.Schema(
                {
                    vol.Required("import_stat"): selector.StatisticSelector(multi),
                    vol.Required("export_stat"): selector.StatisticSelector(multi),
                    vol.Optional("balanced_import_stat"): selector.StatisticSelector(multi),
                    vol.Optional("balanced_export_stat"): selector.StatisticSelector(multi),
                }
            ),
            description_placeholders={"docs_url": DOCS_URL},
            errors=errors,
        )

    async def async_step_contract(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        suggested = self._suggested_contract or date(datetime.now().year, 1, 1)
        show_backfill = self._source_type == SOURCE_TAURON and any(
            m.entry_id for m in self._meters if m.meter_id == self._meter_id
        )

        if user_input is not None:
            start: date = user_input[CONF_CONTRACT_START]
            end = user_input.get(CONF_CONTRACT_END)
            if isinstance(start, str):
                start = date.fromisoformat(start)
            if isinstance(end, str):
                end = date.fromisoformat(end)
            if end and end <= start:
                errors["base"] = "invalid_contract_dates"
            elif start > date.today():
                errors["base"] = "invalid_contract_dates"
            else:
                unique = f"{self._source_type}:{self._meter_id}"
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured()
                backfill = (
                    bool(user_input.get(CONF_BACKFILL_TAURON, DEFAULT_BACKFILL_TAURON))
                    if show_backfill
                    else False
                )
                data = {
                    CONF_API_KEY: self._api_key,
                    CONF_SOURCE_TYPE: self._source_type,
                    CONF_METER_ID: self._meter_id,
                    CONF_METER_NAME: self._meter_name,
                    CONF_STAT_IDS: self._stat_ids,
                    CONF_CONTRACT_START: start.isoformat(),
                    CONF_CONTRACT_END: end.isoformat() if end else None,
                    CONF_BACKFILL_TAURON: backfill,
                }
                return self.async_create_entry(
                    title=f"Pstryk OSD Compare ({self._meter_name})",
                    data=data,
                    options={
                        CONF_TAURON_BASIS: DEFAULT_TAURON_BASIS,
                        CONF_SYNC_INTERVAL_HOURS: DEFAULT_SYNC_INTERVAL_HOURS,
                        CONF_DEPOSIT_OPENING_BALANCE: DEFAULT_DEPOSIT_OPENING_BALANCE,
                        CONF_MONTHLY_FEE: DEFAULT_MONTHLY_FEE,
                        CONF_SETTLEMENT_DAY: DEFAULT_SETTLEMENT_DAY,
                        CONF_MONTHLY_ADJUSTMENTS: {},
                        CONF_OFFICIAL_MONTHS: {},
                        CONF_BACKFILL_TAURON: backfill,
                    },
                )

        schema_dict: dict[Any, Any] = {
            vol.Required(CONF_CONTRACT_START, default=suggested): selector.DateSelector(),
            vol.Optional(CONF_CONTRACT_END): selector.DateSelector(),
        }
        if show_backfill:
            schema_dict[vol.Required(CONF_BACKFILL_TAURON, default=True)] = (
                selector.BooleanSelector()
            )

        return self.async_show_form(
            step_id="contract",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={"suggested": suggested.isoformat()},
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> FlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        entry_id = self.context.get("entry_id")
        entry = self.hass.config_entries.async_get_entry(entry_id) if entry_id else None
        if entry is None:
            return self.async_abort(reason="reauth_successful")

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            client = PstrykClient(async_get_clientsession(self.hass), api_key)
            try:
                await client.test_auth()
            except PstrykAuthError:
                errors["base"] = "invalid_auth"
            except PstrykApiError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: api_key}
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PstrykOsdCompareOptionsFlow()


class PstrykOsdCompareOptionsFlow(OptionsFlow):
    """Handle options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parsed_adj = _parse_adjustments(
                    user_input.get(CONF_MONTHLY_ADJUSTMENTS, "{}")
                )
                parsed_official = parse_official_months(
                    user_input.get(CONF_OFFICIAL_MONTHS, "{}")
                )
            except ValueError:
                errors["base"] = "invalid_adjustments"
            else:
                out = dict(user_input)
                out[CONF_MONTHLY_ADJUSTMENTS] = parsed_adj
                out[CONF_OFFICIAL_MONTHS] = parsed_official
                out[CONF_SETTLEMENT_DAY] = int(
                    out.get(CONF_SETTLEMENT_DAY, DEFAULT_SETTLEMENT_DAY)
                )
                return self.async_create_entry(title="", data=out)

        opts = self.config_entry.options
        basis_options = ["balanced", "gross"]
        adj_text = _json_default(opts.get(CONF_MONTHLY_ADJUSTMENTS))
        official_text = _json_default(opts.get(CONF_OFFICIAL_MONTHS))
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_TAURON_BASIS,
                        default=opts.get(CONF_TAURON_BASIS, DEFAULT_TAURON_BASIS),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=basis_options,
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                    vol.Required(
                        CONF_SYNC_INTERVAL_HOURS,
                        default=opts.get(
                            CONF_SYNC_INTERVAL_HOURS, DEFAULT_SYNC_INTERVAL_HOURS
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=24, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_BACKFILL_TAURON,
                        default=opts.get(CONF_BACKFILL_TAURON, DEFAULT_BACKFILL_TAURON),
                    ): selector.BooleanSelector(),
                    vol.Required(
                        CONF_DEPOSIT_OPENING_BALANCE,
                        default=opts.get(
                            CONF_DEPOSIT_OPENING_BALANCE,
                            DEFAULT_DEPOSIT_OPENING_BALANCE,
                        ),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, step=0.01, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_MONTHLY_FEE,
                        default=opts.get(CONF_MONTHLY_FEE, DEFAULT_MONTHLY_FEE),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, step=0.01, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Required(
                        CONF_SETTLEMENT_DAY,
                        default=opts.get(CONF_SETTLEMENT_DAY, DEFAULT_SETTLEMENT_DAY),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=28, mode=selector.NumberSelectorMode.BOX
                        )
                    ),
                    vol.Optional(
                        CONF_MONTHLY_ADJUSTMENTS,
                        default=adj_text,
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            multiline=True, type=selector.TextSelectorType.TEXT
                        )
                    ),
                    vol.Optional(
                        CONF_OFFICIAL_MONTHS,
                        default=official_text,
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(
                            multiline=True, type=selector.TextSelectorType.TEXT
                        )
                    ),
                }
            ),
            errors=errors,
        )


def _json_default(value: Any) -> str:
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, indent=2) if value else "{}"
    return str(value) if value else "{}"


def _parse_adjustments(raw: Any) -> dict[str, float]:
    """Parse YYYY-MM → PLN map from dict or JSON string."""
    if raw is None or raw == "":
        return {}
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return {}
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as err:
            raise ValueError("invalid JSON") from err
    if not isinstance(raw, dict):
        raise ValueError("not a mapping")
    out: dict[str, float] = {}
    month_re = re.compile(r"^\d{4}-\d{2}$")
    for key, val in raw.items():
        k = str(key)
        if not month_re.match(k):
            raise ValueError(f"bad month key: {k}")
        if val is None or val == "":
            continue
        out[k] = float(val)
    return out


def _meter_label(meter: OsdMeterInfo) -> str:
    provider = PROVIDER_LABELS.get(meter.provider, meter.provider)
    name = f"{provider}: {meter.meter_name or meter.title or meter.meter_id}"
    if meter.last_data:
        last = meter.last_data.date().isoformat()
        return f"{name} (ostatnie dane: {last})"
    return f"{name} (brak świeżych danych)"

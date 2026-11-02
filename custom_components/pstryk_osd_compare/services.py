"""Service handlers."""

from __future__ import annotations

import csv
import logging
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.helpers import config_validation as cv

from .calc import TZ, is_matched, parse_official_months, tauron_side
from .const import CONF_MONTHLY_ADJUSTMENTS, CONF_OFFICIAL_MONTHS, DOMAIN
from .fv import official_months_of, save_official_month

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc

SERVICE_RESYNC = "resync"
SERVICE_EXPORT_CSV = "export_csv"
SERVICE_SET_MONTHLY_ADJUSTMENT = "set_monthly_adjustment"
SERVICE_SET_OFFICIAL_MONTH = "set_official_month"

RESYNC_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Optional("start_date"): cv.date,
    }
)
EXPORT_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required("start_date"): cv.date,
        vol.Required("end_date"): cv.date,
    }
)
ADJUST_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Required("month"): vol.Match(r"^\d{4}-\d{2}$"),
        vol.Required("amount"): vol.Coerce(float),
    }
)
OFFICIAL_SCHEMA = vol.Schema(
    {
        vol.Required("config_entry_id"): cv.string,
        vol.Optional("month"): vol.Match(r"^\d{4}-\d{2}$"),
        vol.Optional("clear", default=False): cv.boolean,
        vol.Optional("invoice"): vol.Coerce(float),
        vol.Optional("deposit_used"): vol.Coerce(float),
        vol.Optional("bonus"): vol.Coerce(float),
        vol.Optional("to_pay"): vol.Coerce(float),
        vol.Optional("inflow"): vol.Coerce(float),
        vol.Optional("number"): cv.string,
        # Merge many months in one reload (JSON object YYYY-MM → fields)
        vol.Optional("months_json"): cv.string,
    }
)


async def async_setup_services(hass: HomeAssistant) -> None:
    async def _resync(call: ServiceCall) -> None:
        entry_id = call.data["config_entry_id"]
        data = hass.data.get(DOMAIN, {}).get(entry_id)
        if not data:
            _LOGGER.error("Unknown config entry %s", entry_id)
            return
        start = call.data.get("start_date")
        await data["coordinator"].async_resync(start)

    async def _export(call: ServiceCall) -> dict[str, Any]:
        entry_id = call.data["config_entry_id"]
        data = hass.data.get(DOMAIN, {}).get(entry_id)
        if not data:
            return {"error": f"unknown entry {entry_id}"}
        start: date = call.data["start_date"]
        end: date = call.data["end_date"]
        coordinator = data["coordinator"]
        hours = data["store"].hours
        basis = coordinator.basis
        path = await hass.async_add_executor_job(
            _write_csv, hass.config.path("www/pstryk_osd_compare"), hours, basis, start, end
        )
        return {"path": path}

    async def _set_adjustment(call: ServiceCall) -> dict[str, Any]:
        entry_id = call.data["config_entry_id"]
        month = call.data["month"]
        amount = float(call.data["amount"])
        if not re.match(r"^\d{4}-\d{2}$", month):
            return {"error": "month must be YYYY-MM"}
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            return {"error": f"unknown entry {entry_id}"}
        opts = dict(entry.options)
        adj = dict(opts.get(CONF_MONTHLY_ADJUSTMENTS) or {})
        if not isinstance(adj, dict):
            adj = {}
        if amount == 0.0:
            adj.pop(month, None)
        else:
            adj[month] = amount
        opts[CONF_MONTHLY_ADJUSTMENTS] = adj
        hass.config_entries.async_update_entry(entry, options=opts)
        return {"month": month, "amount": amount, "adjustments": adj}

    async def _set_official_month(call: ServiceCall) -> dict[str, Any]:
        entry_id = call.data["config_entry_id"]
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain != DOMAIN:
            return {"error": f"unknown entry {entry_id}"}
        official = official_months_of(entry)

        months_json = call.data.get("months_json")
        if months_json:
            try:
                batch = parse_official_months(months_json)
            except ValueError as err:
                return {"error": f"months_json: {err}"}
            official.update(batch)
            opts = dict(entry.options)
            opts[CONF_OFFICIAL_MONTHS] = official
            hass.config_entries.async_update_entry(entry, options=opts)
            return {"merged": list(batch.keys()), "official_months": official}

        month = call.data.get("month")
        if not month:
            return {"error": "month or months_json required"}
        if call.data.get("clear"):
            official = save_official_month(hass, entry, month, None)
            return {"month": month, "cleared": True, "official_months": official}

        row: dict[str, Any] = dict(official.get(month) or {})
        for key in ("invoice", "deposit_used", "bonus", "to_pay", "inflow"):
            if key in call.data and call.data[key] is not None:
                row[key] = float(call.data[key])
        if call.data.get("number"):
            row["number"] = str(call.data["number"])
        if not row:
            return {"error": "provide at least one FV field or clear=true"}
        official = save_official_month(hass, entry, month, row)
        return {"month": month, "entry": row, "official_months": official}

    if not hass.services.has_service(DOMAIN, SERVICE_RESYNC):
        hass.services.async_register(
            DOMAIN, SERVICE_RESYNC, _resync, schema=RESYNC_SCHEMA
        )
    if not hass.services.has_service(DOMAIN, SERVICE_EXPORT_CSV):
        hass.services.async_register(
            DOMAIN,
            SERVICE_EXPORT_CSV,
            _export,
            schema=EXPORT_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_MONTHLY_ADJUSTMENT):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_MONTHLY_ADJUSTMENT,
            _set_adjustment,
            schema=ADJUST_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )
    if not hass.services.has_service(DOMAIN, SERVICE_SET_OFFICIAL_MONTH):
        hass.services.async_register(
            DOMAIN,
            SERVICE_SET_OFFICIAL_MONTH,
            _set_official_month,
            schema=OFFICIAL_SCHEMA,
            supports_response=SupportsResponse.OPTIONAL,
        )


def _write_csv(
    www_dir: str,
    hours: dict[int, dict],
    basis: str,
    start: date,
    end: date,
) -> str:
    out_dir = Path(www_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"compare_{start.isoformat()}_{end.isoformat()}.csv"
    start_ts = int(
        datetime(start.year, start.month, start.day, tzinfo=TZ).astimezone(UTC).timestamp()
    )
    end_ts = int(
        datetime(end.year, end.month, end.day, tzinfo=TZ).astimezone(UTC).timestamp()
    )
    fieldnames = [
        "hour_local",
        "p_imp_kwh",
        "p_exp_kwh",
        "t_imp_kwh",
        "t_exp_kwh",
        "buy_pln_kwh",
        "sell_pln_kwh",
        "matched",
    ]
    with path.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for ts in range(start_ts, end_ts, 3600):
            rec = hours.get(ts) or {}
            t_imp, t_exp = (None, None)
            if rec.get("t_imp") is not None:
                t_imp, t_exp = tauron_side(rec, basis)
            local = datetime.fromtimestamp(ts, tz=UTC).astimezone(TZ)
            w.writerow(
                {
                    "hour_local": local.isoformat(),
                    "p_imp_kwh": rec.get("p_imp", ""),
                    "p_exp_kwh": rec.get("p_exp", ""),
                    "t_imp_kwh": "" if t_imp is None else t_imp,
                    "t_exp_kwh": "" if t_exp is None else t_exp,
                    "buy_pln_kwh": rec.get("buy", ""),
                    "sell_pln_kwh": rec.get("sell", ""),
                    "matched": int(is_matched(rec)),
                }
            )
    return str(path)

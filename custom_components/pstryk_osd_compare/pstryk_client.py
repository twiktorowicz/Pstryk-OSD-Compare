"""Async Pstryk unified-metrics client (own API key; no pstryk_aio dependency)."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import aiohttp

from .calc import TZ, compute_fixed
from .const import PSTRYK_API_BASE, PSTRYK_API_PATH, PSTRYK_CHUNK_DAYS

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


class PstrykAuthError(Exception):
    """Invalid API key (401/403)."""


class PstrykApiError(Exception):
    """Other API / network errors."""


def parse_frame(frame: dict[str, Any]) -> tuple[int, dict[str, Any]] | None:
    """Parse one unified-metrics hour frame → (utc_ts, hour fields).

    Returns None when the frame has no usable meter values (pre-install nulls).
    Prices alone without meter data are skipped for Store (not contract hours).
    """
    start_raw = frame.get("start")
    if not start_raw:
        return None
    if isinstance(start_raw, str) and start_raw.endswith("Z"):
        utc = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
    else:
        utc = datetime.fromisoformat(str(start_raw))
        if utc.tzinfo is None:
            utc = utc.replace(tzinfo=UTC)
    ts = int(utc.astimezone(UTC).replace(minute=0, second=0, microsecond=0).timestamp())

    metrics = frame.get("metrics") or {}
    meter = metrics.get("meter_values") or {}
    pricing = metrics.get("pricing") or {}
    cost = metrics.get("cost") or {}

    p_imp = meter.get("energy_active_import_register")
    p_exp = meter.get("energy_active_export_register")
    # Pre-meter-install: both null → skip
    if p_imp is None and p_exp is None:
        return None

    buy = pricing.get("price_gross")
    sell = pricing.get("price_prosumer_gross")
    api_cost = cost.get("energy_import_cost")
    api_sold = cost.get("energy_sold_value")

    p_imp_f = float(p_imp or 0.0)
    p_exp_f = float(p_exp or 0.0)
    buy_f = float(buy) if buy is not None else None
    sell_f = float(sell) if sell is not None else None
    api_cost_f = float(api_cost) if api_cost is not None else None
    api_sold_f = float(api_sold) if api_sold is not None else None
    e_net = pricing.get("price_net")
    svc = pricing.get("service_price")

    return ts, {
        "p_imp": p_imp_f,
        "p_exp": p_exp_f,
        "buy": buy_f,
        "sell": sell_f,
        "api_cost": api_cost_f,
        "api_sold": api_sold_f,
        "fixed": compute_fixed(api_cost_f, p_imp_f, buy_f),
        # Tarcza Pstryk basis: energy price net and service fee net (zł/kWh)
        "e_net": float(e_net) if e_net is not None else None,
        "svc": float(svc) if svc is not None else None,
    }


def suggest_contract_start_from_months(frames: list[dict[str, Any]]) -> date | None:
    """First month with non-zero energy_import_cost → return month start date."""
    for frame in frames:
        cost = (frame.get("metrics") or {}).get("cost") or {}
        val = cost.get("energy_import_cost")
        if val is None:
            continue
        try:
            if float(val) == 0.0:
                continue
        except (TypeError, ValueError):
            continue
        start_raw = frame.get("start", "")
        if not start_raw:
            continue
        utc = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        local = utc.astimezone(TZ)
        return date(local.year, local.month, 1)
    return None


def suggest_contract_start_from_days(frames: list[dict[str, Any]]) -> date | None:
    """First day with non-zero energy_import_cost."""
    for frame in frames:
        cost = (frame.get("metrics") or {}).get("cost") or {}
        val = cost.get("energy_import_cost")
        if val is None:
            continue
        try:
            if float(val) == 0.0:
                continue
        except (TypeError, ValueError):
            continue
        start_raw = frame.get("start", "")
        if not start_raw:
            continue
        utc = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        return utc.astimezone(TZ).date()
    # Fallback: first day with any meter values
    for frame in frames:
        meter = (frame.get("metrics") or {}).get("meter_values") or {}
        if meter.get("energy_active_import_register") is None and meter.get(
            "energy_active_export_register"
        ) is None:
            continue
        start_raw = frame.get("start", "")
        if not start_raw:
            continue
        utc = datetime.fromisoformat(str(start_raw).replace("Z", "+00:00"))
        return utc.astimezone(TZ).date()
    return None


class PstrykClient:
    """Thin async client for Pstryk unified-metrics."""

    def __init__(self, session: aiohttp.ClientSession, api_key: str) -> None:
        self._session = session
        self._api_key = api_key

    async def _request(
        self,
        *,
        metrics: str,
        resolution: str,
        window_start: datetime,
        window_end: datetime,
    ) -> dict[str, Any]:
        start_utc = window_start.astimezone(UTC)
        end_utc = window_end.astimezone(UTC)
        params = {
            "metrics": metrics,
            "resolution": resolution,
            "window_start": start_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "window_end": end_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        headers = {"Authorization": self._api_key, "Accept": "application/json"}
        url = f"{PSTRYK_API_BASE}{PSTRYK_API_PATH}"

        for attempt in range(5):
            try:
                timeout = aiohttp.ClientTimeout(total=60)
                async with self._session.get(
                    url, params=params, headers=headers, timeout=timeout
                ) as resp:
                    text = await resp.text()
                    if resp.status in (401, 403):
                        raise PstrykAuthError(f"HTTP {resp.status}")
                    if resp.status == 429:
                        wait = 30 * (attempt + 1)
                        _LOGGER.warning("Pstryk API 429 — waiting %ss", wait)
                        await asyncio.sleep(wait)
                        continue
                    if resp.status >= 400:
                        raise PstrykApiError(f"HTTP {resp.status}: {text[:200]}")
                    return await resp.json(content_type=None)
            except (PstrykAuthError, PstrykApiError):
                raise
            except aiohttp.ClientError as err:
                raise PstrykApiError(str(err)) from err
            except asyncio.TimeoutError as err:
                raise PstrykApiError("timeout") from err
        raise PstrykApiError("too many 429 responses")

    async def fetch_hours(
        self, window_start: datetime, window_end: datetime
    ) -> dict[int, dict[str, Any]]:
        """Fetch hour frames in ≤5-day chunks; return {ts: pstryk fields}."""
        out: dict[int, dict[str, Any]] = {}
        cursor = window_start
        chunk = timedelta(days=PSTRYK_CHUNK_DAYS)
        while cursor < window_end:
            chunk_end = min(cursor + chunk, window_end)
            payload = await self._request(
                metrics="meter_values,pricing,cost",
                resolution="hour",
                window_start=cursor,
                window_end=chunk_end,
            )
            frames = payload.get("frames") or []
            _LOGGER.debug(
                "Pstryk hours %s…%s → %s frames",
                cursor.date(),
                chunk_end.date(),
                len(frames),
            )
            for frame in frames:
                parsed = parse_frame(frame)
                if parsed is None:
                    continue
                ts, fields = parsed
                # Clip to requested window (API may return exclusive-end edges)
                if ts < int(window_start.astimezone(UTC).timestamp()):
                    continue
                if ts >= int(window_end.astimezone(UTC).timestamp()):
                    continue
                out[ts] = fields
            cursor = chunk_end
            await asyncio.sleep(0.5)
        return out

    async def detect_contract_start(self) -> date | None:
        """Suggest contract_start from monthly then daily API data (§1.4)."""
        now = datetime.now(tz=UTC)
        start = now - timedelta(days=36 * 31)
        payload = await self._request(
            metrics="meter_values,cost",
            resolution="month",
            window_start=start,
            window_end=now,
        )
        month_hint = suggest_contract_start_from_months(payload.get("frames") or [])
        if month_hint is None:
            return suggest_contract_start_from_days(payload.get("frames") or [])

        # Refine with daily data for hint month ± 1
        if month_hint.month == 1:
            day_from = date(month_hint.year - 1, 12, 1)
        else:
            day_from = date(month_hint.year, month_hint.month - 1, 1)
        if month_hint.month == 12:
            day_to = date(month_hint.year + 1, 2, 1)
        elif month_hint.month == 11:
            day_to = date(month_hint.year + 1, 1, 1)
        else:
            day_to = date(month_hint.year, month_hint.month + 2, 1)

        day_start = datetime(day_from.year, day_from.month, day_from.day, tzinfo=TZ)
        day_end = datetime(day_to.year, day_to.month, day_to.day, tzinfo=TZ)
        await asyncio.sleep(0.5)
        daily = await self._request(
            metrics="meter_values,cost",
            resolution="day",
            window_start=day_start.astimezone(UTC),
            window_end=day_end.astimezone(UTC),
        )
        return suggest_contract_start_from_days(daily.get("frames") or []) or month_hint

    async def test_auth(self) -> None:
        """Raise PstrykAuthError / PstrykApiError if key or API fails."""
        end = datetime.now(tz=UTC).replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(hours=24)
        await self._request(
            metrics="meter_values,pricing,cost",
            resolution="hour",
            window_start=start,
            window_end=end,
        )

"""DataUpdateCoordinator — sync Pstryk API + OSD statistics into Store."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .calc import (
    TZ,
    DepositConfig,
    daily_breakdown,
    deposit_ledger,
    filter_hours_by_contract,
    hourly_breakdown,
    build_corrections,
    is_matched,
    ledger_balance_through,
    month_model_totals,
    monthly_rows,
    parse_official_months,
    period_bounds,
    settled_through_month,
    summarize,
)
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
    DEFAULT_DEPOSIT_OPENING_BALANCE,
    DEFAULT_MONTHLY_ADJUSTMENTS,
    DEFAULT_MONTHLY_FEE,
    DEFAULT_OFFICIAL_MONTHS,
    DEFAULT_SETTLEMENT_DAY,
    DEFAULT_SYNC_INTERVAL_HOURS,
    DEFAULT_TAURON_BASIS,
    DOMAIN,
    DSO_STALE_DAYS,
    PSTRYK_REFRESH_BACK_HOURS,
    SOURCE_TAURON,
    TAURON_REFRESH_BACK_DAYS,
)
from .pstryk_client import PstrykApiError, PstrykAuthError, PstrykClient
from .statistics import async_write_statistics
from .store import CompareStore
from .tauron_reader import async_read_osd_hours, async_request_tauron_backfill

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


@dataclass
class CompareData:
    """Snapshot exposed to entities."""

    last_sync: str | None = None
    hours_pstryk: int = 0
    hours_tauron: int = 0
    hours_matched: int = 0
    errors: list[str] = field(default_factory=list)
    periods: dict[str, dict[str, Any]] = field(default_factory=dict)
    coverage: dict[str, Any] = field(default_factory=dict)
    daily_days: list[dict[str, Any]] = field(default_factory=list)
    analysis_day: date | None = None
    selected_day_hours: list[dict[str, Any]] = field(default_factory=list)
    selected_day_summary: dict[str, Any] = field(default_factory=dict)
    deposit_pstryk: float | None = None
    deposit_tauron: float | None = None
    deposit_pstryk_ledger: list[dict[str, Any]] = field(default_factory=list)
    deposit_tauron_ledger: list[dict[str, Any]] = field(default_factory=list)
    deposit_settled_through: str | None = None
    deposit_pstryk_settled: float | None = None
    deposit_tauron_settled: float | None = None
    monthly_rows: list[dict[str, Any]] = field(default_factory=list)
    monthly_totals: dict[str, Any] = field(default_factory=dict)
    month_model: dict[str, dict[str, Any]] = field(default_factory=dict)
    monthly_fee: float = 0.0


class CompareCoordinator(DataUpdateCoordinator[CompareData]):
    """Periodic sync coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        store: CompareStore,
    ) -> None:
        interval_h = entry.options.get(
            CONF_SYNC_INTERVAL_HOURS, DEFAULT_SYNC_INTERVAL_HOURS
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(hours=interval_h),
        )
        self.entry = entry
        self.store = store
        self._lock = asyncio.Lock()
        self._analysis_day: date | None = None
        self._stats_basis: str | None = None

    @property
    def api_key(self) -> str:
        return self.entry.data[CONF_API_KEY]

    @property
    def contract_start(self) -> date:
        return date.fromisoformat(self.entry.data[CONF_CONTRACT_START])

    @property
    def contract_end(self) -> date | None:
        raw = self.entry.data.get(CONF_CONTRACT_END)
        return date.fromisoformat(raw) if raw else None

    @property
    def basis(self) -> str:
        return self.entry.options.get(CONF_TAURON_BASIS, DEFAULT_TAURON_BASIS)

    @property
    def stat_ids(self) -> dict[str, str | list[str] | None]:
        return dict(self.entry.data.get(CONF_STAT_IDS) or {})

    def _window_end(self) -> datetime:
        now = datetime.now(tz=UTC).replace(minute=0, second=0, microsecond=0)
        if self.contract_end is None:
            return now
        end_local = datetime(
            self.contract_end.year,
            self.contract_end.month,
            self.contract_end.day,
            tzinfo=TZ,
        )
        return min(now, end_local.astimezone(UTC))

    def _contract_start_utc(self) -> datetime:
        start_local = datetime(
            self.contract_start.year,
            self.contract_start.month,
            self.contract_start.day,
            tzinfo=TZ,
        )
        return start_local.astimezone(UTC)

    async def _async_update_data(self) -> CompareData:
        async with self._lock:
            return await self._sync()

    async def async_resync(self, start: date | None = None) -> CompareData:
        async with self._lock:
            return await self._sync(force_from=start or self.contract_start)

    async def _sync(self, force_from: date | None = None) -> CompareData:
        errors: list[str] = []
        session = async_get_clientsession(self.hass)
        client = PstrykClient(session, self.api_key)
        window_end = self._window_end()
        contract_start_utc = self._contract_start_utc()

        # --- Pstryk ---
        if force_from is not None:
            p_start = datetime(
                force_from.year, force_from.month, force_from.day, tzinfo=TZ
            ).astimezone(UTC)
        elif not self.store.hours:
            p_start = contract_start_utc
        else:
            last = self.store.data.get("last_pstryk_hour")
            if last is None:
                p_start = contract_start_utc
            else:
                p_start = datetime.fromtimestamp(last, tz=UTC) - timedelta(
                    hours=PSTRYK_REFRESH_BACK_HOURS
                )
                if p_start < contract_start_utc:
                    p_start = contract_start_utc

        try:
            pstryk_hours = await client.fetch_hours(p_start, window_end)
            # Enforce contract bounds
            bounded = filter_hours_by_contract(
                pstryk_hours, self.contract_start, self.contract_end
            )
            self.store.merge_pstryk(bounded)
        except PstrykAuthError as err:
            raise ConfigEntryAuthFailed(f"Pstryk auth failed: {err}") from err
        except PstrykApiError as err:
            errors.append(f"Pstryk API: {err}")
            _LOGGER.warning("Pstryk sync error: %s", err)

        # --- OSD / Tauron ---
        if force_from is not None:
            t_start = datetime(
                force_from.year, force_from.month, force_from.day, tzinfo=TZ
            ).astimezone(UTC)
        elif not any(
            rec.get("t_imp") is not None for rec in self.store.hours.values()
        ):
            t_start = contract_start_utc
        else:
            last_t = self.store.data.get("last_tauron_hour")
            if last_t is None:
                t_start = contract_start_utc
            else:
                t_start = datetime.fromtimestamp(last_t, tz=UTC) - timedelta(
                    days=TAURON_REFRESH_BACK_DAYS
                )
                if t_start < contract_start_utc:
                    t_start = contract_start_utc

        try:
            osd = await async_read_osd_hours(
                self.hass, self.stat_ids, t_start, window_end
            )
            self.store.merge_tauron(osd)
        except Exception as err:  # noqa: BLE001 — keep sync resilient
            errors.append(f"OSD stats: {err}")
            _LOGGER.warning("OSD sync error: %s", err)

        # Optional Tauron backfill
        if (
            self.entry.data.get(CONF_SOURCE_TYPE) == SOURCE_TAURON
            and self.entry.options.get(
                CONF_BACKFILL_TAURON,
                self.entry.data.get(CONF_BACKFILL_TAURON, True),
            )
        ):
            try:
                await self._maybe_backfill_tauron(errors)
            except Exception as err:  # noqa: BLE001
                errors.append(f"Tauron backfill: {err}")
                _LOGGER.warning("Tauron backfill error: %s", err)

        self.store.mark_synced()
        self.store.async_schedule_save()
        self._update_stale_issue(window_end)

        # External statistics (full rewrite when basis changed)
        rewrite_from = None
        if self._stats_basis is not None and self._stats_basis != self.basis:
            rewrite_from = min(self.store.hours) if self.store.hours else None
        try:
            await async_write_statistics(
                self.hass,
                hours=self.store.hours,
                basis=self.basis,
                meter_slug=self.entry.data.get(CONF_METER_ID) or "meter",
                meter_name=self.entry.data.get(CONF_METER_NAME)
                or self.entry.data.get(CONF_METER_ID)
                or "meter",
                rewrite_from_ts=rewrite_from,
            )
            self._stats_basis = self.basis
        except Exception as err:  # noqa: BLE001
            errors.append(f"statistics: {err}")
            _LOGGER.warning("Statistics write failed: %s", err)

        return self._build_compare_data(errors)

    def _update_stale_issue(self, window_end: datetime) -> None:
        """Raise a repair issue while DSO statistics lag more than DSO_STALE_DAYS."""
        issue_id = f"dso_stale_{self.entry.entry_id}"
        last_t = self.store.data.get("last_tauron_hour")
        end = window_end
        if self.contract_end is not None:
            end = min(
                end,
                datetime(
                    self.contract_end.year,
                    self.contract_end.month,
                    self.contract_end.day,
                    tzinfo=TZ,
                ).astimezone(UTC),
            )
        last = datetime.fromtimestamp(last_t, tz=UTC) if last_t else None
        if last is not None and end - last <= timedelta(days=DSO_STALE_DAYS):
            ir.async_delete_issue(self.hass, DOMAIN, issue_id)
            return
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="dso_stale",
            translation_placeholders={
                "meter": str(
                    self.entry.data.get(CONF_METER_NAME)
                    or self.entry.data.get(CONF_METER_ID)
                    or "?"
                ),
                "last": last.astimezone(TZ).strftime("%Y-%m-%d %H:%M")
                if last
                else "—",
                "days": str(DSO_STALE_DAYS),
            },
        )

    async def async_set_analysis_day(self, day: date) -> None:
        """Update selected-day hourly view without API fetch."""
        self._analysis_day = day
        if self.data is None:
            self.async_set_updated_data(self._build_compare_data([]))
            return
        data = self._build_compare_data(list(self.data.errors))
        self.async_set_updated_data(data)

    def _build_compare_data(self, errors: list[str]) -> CompareData:
        hours = self.store.hours
        hours_p = sum(
            1
            for r in hours.values()
            if r.get("p_imp") is not None and r.get("buy") is not None
        )
        hours_t = sum(1 for r in hours.values() if r.get("t_imp") is not None)
        hours_m = sum(1 for r in hours.values() if is_matched(r))

        now_local = datetime.now(tz=TZ)
        periods: dict[str, dict[str, Any]] = {}
        for name, kind in (
            ("current_month", "month"),
            ("previous_month", "prev_month"),
            ("current_year", "year"),
        ):
            s_ts, e_ts = period_bounds(kind, now_local)
            summary = summarize(hours, self.basis, s_ts, e_ts)
            summary["period_start"] = datetime.fromtimestamp(s_ts, tz=UTC).astimezone(
                TZ
            ).isoformat()
            summary["period_end"] = datetime.fromtimestamp(e_ts, tz=UTC).astimezone(
                TZ
            ).isoformat()
            periods[name] = summary

        from .calc import find_previous_complete_day

        prev_day = find_previous_complete_day(hours, now_local.date())
        if prev_day is not None:
            day_start = datetime(prev_day.year, prev_day.month, prev_day.day, tzinfo=TZ)
            day_end = day_start + timedelta(days=1)
            s_ts = int(day_start.astimezone(UTC).timestamp())
            e_ts = int(day_end.astimezone(UTC).timestamp())
            summary = summarize(hours, self.basis, s_ts, e_ts)
            summary["period_start"] = day_start.isoformat()
            summary["period_end"] = day_end.isoformat()
            periods["previous_day"] = summary
        else:
            periods["previous_day"] = summarize(hours, self.basis, 0, 0)

        # Coverage until yesterday
        coverage = self._coverage_until(now_local.date() - timedelta(days=1))

        # Daily breakdown: previous + current month
        prev_s, _ = period_bounds("prev_month", now_local)
        _, cur_e = period_bounds("month", now_local)
        daily_days = daily_breakdown(hours, self.basis, prev_s, cur_e)

        analysis = self._analysis_day or prev_day or (now_local.date() - timedelta(days=2))
        sel_hours = hourly_breakdown(hours, self.basis, analysis)
        a_start = datetime(analysis.year, analysis.month, analysis.day, tzinfo=TZ)
        a_end = a_start + timedelta(days=1)
        sel_summary = summarize(
            hours,
            self.basis,
            int(a_start.astimezone(UTC).timestamp()),
            int(a_end.astimezone(UTC).timestamp()),
        )

        # Deposit ledgers (matched hours only; through last matched hour)
        raw_adj = self.entry.options.get(
            CONF_MONTHLY_ADJUSTMENTS, DEFAULT_MONTHLY_ADJUSTMENTS
        )
        if isinstance(raw_adj, str):
            try:
                raw_adj = json.loads(raw_adj) if raw_adj.strip() else {}
            except json.JSONDecodeError:
                raw_adj = {}
                errors.append("monthly_adjustments: invalid JSON")
        if not isinstance(raw_adj, dict):
            raw_adj = {}
        adjustments = {
            str(k): float(v) for k, v in raw_adj.items() if v is not None and str(k)
        }
        raw_official = self.entry.options.get(
            CONF_OFFICIAL_MONTHS, DEFAULT_OFFICIAL_MONTHS
        )
        try:
            official_months = parse_official_months(raw_official)
        except ValueError:
            official_months = {}
            errors.append("official_months: invalid JSON/shape")
        deposit_cfg = DepositConfig(
            deposit_opening_balance=float(
                self.entry.options.get(
                    CONF_DEPOSIT_OPENING_BALANCE, DEFAULT_DEPOSIT_OPENING_BALANCE
                )
            ),
            monthly_fee=float(
                self.entry.options.get(CONF_MONTHLY_FEE, DEFAULT_MONTHLY_FEE)
            ),
            monthly_adjustments=adjustments,
        )
        matched_ts = [ts for ts, r in hours.items() if is_matched(r)]
        until_ts = max(matched_ts) if matched_ts else int(now_local.astimezone(UTC).timestamp())
        model = month_model_totals(hours, self.basis, until_ts, self.contract_start)
        corrections = build_corrections(
            model, official_months, monthly_fee=deposit_cfg.monthly_fee
        )
        ledger_p = deposit_ledger(model, corrections, source="pstryk", cfg=deposit_cfg)
        ledger_t = deposit_ledger(model, corrections, source="tauron", cfg=deposit_cfg)
        bal_p = ledger_p[-1]["balance"] if ledger_p else None
        bal_t = ledger_t[-1]["balance"] if ledger_t else None
        settlement_day = int(
            self.entry.options.get(CONF_SETTLEMENT_DAY, DEFAULT_SETTLEMENT_DAY)
        )
        settled_m = settled_through_month(
            now_local.date(),
            settlement_day=settlement_day,
            fv_months=official_months.keys(),
        )
        bal_p_s = ledger_balance_through(ledger_p, settled_m)
        bal_t_s = ledger_balance_through(ledger_t, settled_m)
        m_rows, m_totals = monthly_rows(model, ledger_p, ledger_t, settled_m)

        _LOGGER.info(
            "Sync done: Pstryk=%s OSD=%s matched=%s errors=%s deposit_p=%s deposit_t=%s settled=%s/%s",
            hours_p,
            hours_t,
            hours_m,
            len(errors),
            bal_p,
            bal_t,
            settled_m,
            bal_p_s,
        )
        return CompareData(
            last_sync=self.store.data.get("last_sync"),
            hours_pstryk=hours_p,
            hours_tauron=hours_t,
            hours_matched=hours_m,
            errors=errors,
            periods=periods,
            coverage=coverage,
            daily_days=daily_days,
            analysis_day=analysis,
            selected_day_hours=sel_hours,
            selected_day_summary=sel_summary,
            deposit_pstryk=bal_p,
            deposit_tauron=bal_t,
            deposit_pstryk_ledger=ledger_p,
            deposit_tauron_ledger=ledger_t,
            deposit_settled_through=settled_m,
            deposit_pstryk_settled=bal_p_s,
            deposit_tauron_settled=bal_t_s,
            monthly_rows=m_rows,
            monthly_totals=m_totals,
            month_model=model,
            monthly_fee=deposit_cfg.monthly_fee,
        )

    def _coverage_until(self, until_day: date) -> dict[str, Any]:
        hours = self.store.hours
        start = self.contract_start
        if until_day < start:
            return {"percent": 0.0, "months": []}
        months: list[dict[str, Any]] = []
        total_h = matched_h = 0
        y, m = start.year, start.month
        end_y, end_m = until_day.year, until_day.month
        while (y, m) <= (end_y, end_m):
            m_start = datetime(y, m, 1, tzinfo=TZ)
            if m == 12:
                m_end = datetime(y + 1, 1, 1, tzinfo=TZ)
            else:
                m_end = datetime(y, m + 1, 1, tzinfo=TZ)
            # Clip to contract / until_day
            clip_start = max(
                m_start,
                datetime(start.year, start.month, start.day, tzinfo=TZ),
            )
            clip_end = min(
                m_end,
                datetime(until_day.year, until_day.month, until_day.day, tzinfo=TZ)
                + timedelta(days=1),
            )
            s_ts = int(clip_start.astimezone(UTC).timestamp())
            e_ts = int(clip_end.astimezone(UTC).timestamp())
            ht = pe = te = me = 0
            for ts in range(s_ts, e_ts, 3600):
                ht += 1
                rec = hours.get(ts) or {}
                if rec.get("p_imp") is not None and rec.get("buy") is not None:
                    pe += 1
                if rec.get("t_imp") is not None:
                    te += 1
                if is_matched(rec):
                    me += 1
            months.append(
                {
                    "month": f"{y:04d}-{m:02d}",
                    "hours_total": ht,
                    "pstryk_hours": pe,
                    "tauron_hours": te,
                    "matched_hours": me,
                }
            )
            total_h += ht
            matched_h += me
            if m == 12:
                y += 1
                m = 1
            else:
                m += 1
        pct = round(100.0 * matched_h / total_h, 1) if total_h else 0.0
        return {"percent": pct, "months": months}

    async def _maybe_backfill_tauron(self, errors: list[str]) -> None:
        meter_id = self.entry.data.get(CONF_METER_ID)
        if not meter_id:
            return
        # Find earliest incomplete day in contract range (skip last 2 days)
        today = datetime.now(tz=TZ).date()
        skip_after = today - timedelta(days=2)
        start = self.contract_start
        # Quick scan: day with any hour missing t_imp while within contract
        cursor = start
        missing: date | None = None
        while cursor <= skip_after:
            day_start = datetime(cursor.year, cursor.month, cursor.day, tzinfo=TZ)
            day_end = day_start + timedelta(days=1)
            s_ts = int(day_start.astimezone(UTC).timestamp())
            e_ts = int(day_end.astimezone(UTC).timestamp())
            expected = (e_ts - s_ts) // 3600
            have = sum(
                1
                for ts in range(s_ts, e_ts, 3600)
                if (self.store.hours.get(ts) or {}).get("t_imp") is not None
            )
            if have < expected:
                missing = cursor
                break
            cursor += timedelta(days=1)

        if missing is None:
            return

        floor = today - timedelta(days=365)
        effective = max(missing, floor)
        prev = self.store.data.get("tauron_backfill_requested")
        prev_at = self.store.data.get("tauron_backfill_at")
        if prev == effective.isoformat() and prev_at:
            try:
                when = datetime.fromisoformat(prev_at)
                if datetime.now(tz=UTC) - when < timedelta(hours=24):
                    return
            except ValueError:
                pass

        if effective > missing:
            errors.append(
                f"Brak danych Tauron przed {floor.isoformat()} — "
                "integracja Tauron pobiera max 365 dni"
            )

        ok = await async_request_tauron_backfill(self.hass, meter_id, effective)
        if ok:
            self.store.data["tauron_backfill_requested"] = effective.isoformat()
            self.store.data["tauron_backfill_at"] = datetime.now(tz=UTC).isoformat()
            # Re-read after backfill
            t_start = datetime(
                effective.year, effective.month, effective.day, tzinfo=TZ
            ).astimezone(UTC)
            osd = await async_read_osd_hours(
                self.hass, self.stat_ids, t_start, self._window_end()
            )
            self.store.merge_tauron(osd)

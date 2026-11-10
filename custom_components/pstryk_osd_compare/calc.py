"""Pure calculation helpers for Pstryk OSD Compare (no Home Assistant imports)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from .const import BASIS_BALANCED, BASIS_GROSS, DEFAULT_SETTLEMENT_DAY, METRICS, TZ

UTC = timezone.utc


@dataclass(frozen=True)
class DepositConfig:
    """Deposit model parameters (current Pstryk rules: no expiry, full invoice)."""

    deposit_opening_balance: float = 0.0
    monthly_fee: float = 0.0
    # YYYY-MM → PLN added to balance after that month settles (referral credits, etc.)
    monthly_adjustments: Mapping[str, float] = field(default_factory=dict)


def is_matched(rec: dict[str, Any]) -> bool:
    """Hour is comparable when Pstryk kWh+price and OSD import are present."""
    return (
        rec.get("p_imp") is not None
        and rec.get("buy") is not None
        and rec.get("t_imp") is not None
    )


def has_pstryk(rec: dict[str, Any]) -> bool:
    return rec.get("p_imp") is not None and rec.get("buy") is not None


def has_tauron(rec: dict[str, Any]) -> bool:
    return rec.get("t_imp") is not None


def tauron_side(rec: dict[str, Any], basis: str) -> tuple[float, float]:
    """Return (T_imp, T_exp) for the chosen OSD basis."""
    if basis == BASIS_BALANCED:
        t_imp = rec.get("tb_imp")
        t_exp = rec.get("tb_exp")
        if t_imp is None or t_exp is None:
            # No DSO balanced series: hourly netting of gross registers (identical to
            # Tauron *_balanced_*; idempotent for data the DSO already balanced)
            net = float(rec.get("t_imp") or 0.0) - float(rec.get("t_exp") or 0.0)
            return max(net, 0.0), max(-net, 0.0)
        return float(t_imp), float(t_exp)
    if basis == BASIS_GROSS:
        return float(rec.get("t_imp") or 0.0), float(rec.get("t_exp") or 0.0)
    raise ValueError(f"Unknown basis: {basis}")


def _sell_price(rec: dict[str, Any]) -> float:
    sell = rec.get("sell")
    return float(sell) if sell is not None else 0.0


def _fixed_fee(rec: dict[str, Any]) -> float:
    fixed = rec.get("fixed")
    if fixed is not None:
        return float(fixed)
    api_cost = rec.get("api_cost")
    buy = rec.get("buy")
    p_imp = rec.get("p_imp")
    if api_cost is None or buy is None or p_imp is None:
        return 0.0
    return float(api_cost) - float(p_imp) * float(buy)


def hour_metrics(rec: dict[str, Any], basis: str) -> dict[str, float]:
    """All §3 metrics for one matched hour."""
    p_imp = float(rec.get("p_imp") or 0.0)
    p_exp = float(rec.get("p_exp") or 0.0)
    buy = float(rec["buy"])
    sell = _sell_price(rec)
    t_imp, t_exp = tauron_side(rec, basis)
    fixed = _fixed_fee(rec)
    api_cost = rec.get("api_cost")
    pstryk_invoice = float(api_cost) if api_cost is not None else fixed + p_imp * buy

    pstryk_buy = p_imp * buy
    pstryk_sell = p_exp * sell
    tauron_buy = t_imp * buy
    tauron_sell = t_exp * sell
    tauron_invoice = fixed + t_imp * buy

    return {
        "pstryk_import": p_imp,
        "pstryk_export": p_exp,
        "osd_import": t_imp,
        "osd_export": t_exp,
        "diff_import": p_imp - t_imp,
        "diff_export": p_exp - t_exp,
        "pstryk_buy_value": pstryk_buy,
        "pstryk_sell_value": pstryk_sell,
        "osd_buy_value": tauron_buy,
        "osd_sell_value": tauron_sell,
        "diff_buy_value": pstryk_buy - tauron_buy,
        "diff_sell_value": pstryk_sell - tauron_sell,
        "diff_net_value": (pstryk_sell - tauron_sell) - (pstryk_buy - tauron_buy),
        "pstryk_invoice_cost": pstryk_invoice,
        "osd_invoice_cost": tauron_invoice,
        "diff_invoice_cost": pstryk_invoice - tauron_invoice,
    }


def cumulative_series(
    hours: dict[int, dict[str, Any]], basis: str
) -> dict[str, list[tuple[int, float, float]]]:
    """metric -> [(ts, state, sum)] for matched hours only, ascending."""
    series: dict[str, list[tuple[int, float, float]]] = {m: [] for m in METRICS}
    running: dict[str, float] = {m: 0.0 for m in METRICS}
    for ts in sorted(hours):
        rec = hours[ts]
        if not is_matched(rec):
            continue
        metrics = hour_metrics(rec, basis)
        for metric, value in metrics.items():
            running[metric] += value
            series[metric].append((ts, value, running[metric]))
    return series


def period_bounds(kind: str, ref: datetime) -> tuple[int, int]:
    """Return (start_ts, end_ts) UTC for a period in Europe/Warsaw.

    end_ts is exclusive. Kind: day | month | year | prev_month | prev_day.
    """
    local = ref.astimezone(TZ)
    if kind == "day":
        start_local = local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local = start_local + timedelta(days=1)
    elif kind == "prev_day":
        start_local = (local - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end_local = start_local + timedelta(days=1)
    elif kind == "month":
        start_local = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        if start_local.month == 12:
            end_local = start_local.replace(year=start_local.year + 1, month=1)
        else:
            end_local = start_local.replace(month=start_local.month + 1)
    elif kind == "prev_month":
        first = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end_local = first
        if first.month == 1:
            start_local = first.replace(year=first.year - 1, month=12)
        else:
            start_local = first.replace(month=first.month - 1)
    elif kind == "year":
        start_local = local.replace(
            month=1, day=1, hour=0, minute=0, second=0, microsecond=0
        )
        end_local = start_local.replace(year=start_local.year + 1)
    else:
        raise ValueError(f"Unknown period kind: {kind}")

    start_ts = int(start_local.astimezone(UTC).timestamp())
    end_ts = int(end_local.astimezone(UTC).timestamp())
    return start_ts, end_ts


def _round_kwh(v: float) -> float:
    return round(v, 3)


def _round_pln(v: float) -> float:
    return round(v, 2)


def _pct(diff: float, base: float) -> float | None:
    if abs(base) <= 0.01:
        return None
    return round(diff / base * 100.0, 2)


def _iter_hour_starts(start_ts: int, end_ts: int) -> Iterable[int]:
    ts = start_ts
    while ts < end_ts:
        yield ts
        ts += 3600


def summarize(
    hours: dict[int, dict[str, Any]],
    basis: str,
    start_ts: int,
    end_ts: int,
) -> dict[str, Any]:
    """Aggregate matched/pstryk/tauron hours in [start_ts, end_ts)."""
    hours_total = 0
    hours_matched = 0
    hours_pstryk_only = 0
    hours_osd_only = 0
    totals = {m: 0.0 for m in METRICS}

    for ts in _iter_hour_starts(start_ts, end_ts):
        hours_total += 1
        rec = hours.get(ts)
        if rec is None:
            continue
        p = has_pstryk(rec)
        t = has_tauron(rec)
        if p and t:
            hours_matched += 1
            metrics = hour_metrics(rec, basis)
            for key, value in metrics.items():
                totals[key] += value
        elif p:
            hours_pstryk_only += 1
        elif t:
            hours_osd_only += 1

    return {
        "hours_total": hours_total,
        "hours_matched": hours_matched,
        "hours_pstryk_only": hours_pstryk_only,
        "hours_osd_only": hours_osd_only,
        "pstryk_import": _round_kwh(totals["pstryk_import"]),
        "osd_import": _round_kwh(totals["osd_import"]),
        "diff_import": _round_kwh(totals["diff_import"]),
        "diff_import_pct": _pct(totals["diff_import"], totals["osd_import"]),
        "pstryk_export": _round_kwh(totals["pstryk_export"]),
        "osd_export": _round_kwh(totals["osd_export"]),
        "diff_export": _round_kwh(totals["diff_export"]),
        "diff_export_pct": _pct(totals["diff_export"], totals["osd_export"]),
        "pstryk_buy_value": _round_pln(totals["pstryk_buy_value"]),
        "osd_buy_value": _round_pln(totals["osd_buy_value"]),
        "diff_buy_value": _round_pln(totals["diff_buy_value"]),
        "pstryk_sell_value": _round_pln(totals["pstryk_sell_value"]),
        "osd_sell_value": _round_pln(totals["osd_sell_value"]),
        "diff_sell_value": _round_pln(totals["diff_sell_value"]),
        "diff_net_value": _round_pln(totals["diff_net_value"]),
        "pstryk_invoice_cost": _round_pln(totals["pstryk_invoice_cost"]),
        "osd_invoice_cost": _round_pln(totals["osd_invoice_cost"]),
        "diff_invoice_cost": _round_pln(totals["diff_invoice_cost"]),
        "complete": hours_matched == hours_total and hours_total > 0,
    }


def daily_breakdown(
    hours: dict[int, dict[str, Any]],
    basis: str,
    start_ts: int,
    end_ts: int,
) -> list[dict[str, Any]]:
    """One summary row per local calendar day intersecting [start_ts, end_ts)."""
    if start_ts >= end_ts:
        return []
    first_local = datetime.fromtimestamp(start_ts, tz=UTC).astimezone(TZ).date()
    last_local = datetime.fromtimestamp(end_ts - 1, tz=UTC).astimezone(TZ).date()
    rows: list[dict[str, Any]] = []
    day = first_local
    while day <= last_local:
        day_start = datetime(day.year, day.month, day.day, tzinfo=TZ)
        day_end = day_start + timedelta(days=1)
        d_start = max(start_ts, int(day_start.astimezone(UTC).timestamp()))
        d_end = min(end_ts, int(day_end.astimezone(UTC).timestamp()))
        s = summarize(hours, basis, d_start, d_end)
        rows.append(
            {
                "date": day.isoformat(),
                "hours_matched": s["hours_matched"],
                "pstryk_import": s["pstryk_import"],
                "osd_import": s["osd_import"],
                "diff_import": s["diff_import"],
                "pstryk_export": s["pstryk_export"],
                "osd_export": s["osd_export"],
                "diff_export": s["diff_export"],
                "diff_buy_value": s["diff_buy_value"],
                "diff_sell_value": s["diff_sell_value"],
                "diff_net_value": s["diff_net_value"],
            }
        )
        day += timedelta(days=1)
    return rows


def hourly_breakdown(
    hours: dict[int, dict[str, Any]],
    basis: str,
    day: date,
) -> list[dict[str, Any]]:
    """Local-hour rows for one calendar day (25 rows on autumn DST day)."""
    start_local = datetime(day.year, day.month, day.day, tzinfo=TZ)
    end_local = start_local + timedelta(days=1)
    start_ts = int(start_local.astimezone(UTC).timestamp())
    end_ts = int(end_local.astimezone(UTC).timestamp())
    rows: list[dict[str, Any]] = []
    for ts in _iter_hour_starts(start_ts, end_ts):
        local = datetime.fromtimestamp(ts, tz=UTC).astimezone(TZ)
        offset = local.utcoffset() or timedelta(0)
        hours_off = int(offset.total_seconds() // 3600)
        utc_offset = f"{hours_off:+03d}:00"
        rec = hours.get(ts, {})
        matched = is_matched(rec) if rec else False
        if matched:
            m = hour_metrics(rec, basis)
            rows.append(
                {
                    "hour": local.strftime("%H:00"),
                    "ts": ts,
                    "matched": True,
                    "utc_offset": utc_offset,
                    "p_imp": _round_kwh(m["pstryk_import"]),
                    "T_imp": _round_kwh(m["osd_import"]),
                    "d_imp": _round_kwh(m["diff_import"]),
                    "p_exp": _round_kwh(m["pstryk_export"]),
                    "T_exp": _round_kwh(m["osd_export"]),
                    "d_exp": _round_kwh(m["diff_export"]),
                    "buy": rec.get("buy"),
                    "sell": rec.get("sell"),
                    "d_buy_value": _round_pln(m["diff_buy_value"]),
                    "d_sell_value": _round_pln(m["diff_sell_value"]),
                }
            )
        else:
            rows.append(
                {
                    "hour": local.strftime("%H:00"),
                    "ts": ts,
                    "matched": False,
                    "utc_offset": utc_offset,
                    "p_imp": None,
                    "T_imp": None,
                    "d_imp": None,
                    "p_exp": None,
                    "T_exp": None,
                    "d_exp": None,
                    "buy": rec.get("buy") if rec else None,
                    "sell": rec.get("sell") if rec else None,
                    "d_buy_value": None,
                    "d_sell_value": None,
                }
            )
    return rows


def find_previous_complete_day(
    hours: dict[int, dict[str, Any]], before: date, max_lookback: int = 10
) -> date | None:
    """Last local calendar day with hours_matched == hours_total."""
    day = before
    for _ in range(max_lookback):
        day = day - timedelta(days=1)
        start_local = datetime(day.year, day.month, day.day, tzinfo=TZ)
        end_local = start_local + timedelta(days=1)
        s_ts = int(start_local.astimezone(UTC).timestamp())
        e_ts = int(end_local.astimezone(UTC).timestamp())
        total = (e_ts - s_ts) // 3600
        matched = sum(
            1 for ts in range(s_ts, e_ts, 3600) if is_matched(hours.get(ts) or {})
        )
        if matched == total and total > 0:
            return day
    return None


def filter_hours_by_contract(
    hours: dict[int, dict[str, Any]],
    contract_start: date,
    contract_end: date | None = None,
) -> dict[int, dict[str, Any]]:
    """Keep only hours in [contract_start, contract_end) local midnight bounds."""
    start_local = datetime(
        contract_start.year, contract_start.month, contract_start.day, tzinfo=TZ
    )
    start_ts = int(start_local.astimezone(UTC).timestamp())
    if contract_end is None:
        end_ts = None
    else:
        end_local = datetime(
            contract_end.year, contract_end.month, contract_end.day, tzinfo=TZ
        )
        end_ts = int(end_local.astimezone(UTC).timestamp())
    out: dict[int, dict[str, Any]] = {}
    for ts, rec in hours.items():
        if ts < start_ts:
            continue
        if end_ts is not None and ts >= end_ts:
            continue
        out[ts] = rec
    return out


def _month_key(ts: int) -> str:
    local = datetime.fromtimestamp(ts, tz=UTC).astimezone(TZ)
    return f"{local.year:04d}-{local.month:02d}"


def _month_start_end(year: int, month: int) -> tuple[int, int]:
    start_local = datetime(year, month, 1, tzinfo=TZ)
    if month == 12:
        end_local = datetime(year + 1, 1, 1, tzinfo=TZ)
    else:
        end_local = datetime(year, month + 1, 1, tzinfo=TZ)
    return (
        int(start_local.astimezone(UTC).timestamp()),
        int(end_local.astimezone(UTC).timestamp()),
    )


@dataclass(frozen=True)
class MonthCorrection:
    """Non-measurement items for one month, applied equally to both sides."""

    extra_invoice: float = 0.0  # FV.invoice - (pstryk_model_invoice + monthly_fee)
    extra_inflow: float = 0.0  # FV.inflow - pstryk_model_inflow (usually ~0)
    bonus: float = 0.0  # FV loyalty bonus (distribution + excise); informational, part of deposit_used
    # FV fact: "Rozliczenie depozytu" + "bonus lojalnościowy" (both drain the deposit);
    # used only for source="pstryk"
    deposit_used: float | None = None
    status: str = "estimate"  # "fv" | "estimate"
    fv_number: str | None = None


def month_model_totals(
    hours: dict[int, dict[str, Any]],
    basis: str,
    until_ts: int,
    contract_start: date | None = None,
) -> dict[str, dict[str, Any]]:
    """YYYY-MM → hourly-model sums over matched hours up to until_ts (inclusive)."""
    if not hours:
        return {}
    if contract_start is None:
        first_ts = min(hours)
        contract_start = datetime.fromtimestamp(first_ts, tz=UTC).astimezone(TZ).date()

    end_local = datetime.fromtimestamp(until_ts, tz=UTC).astimezone(TZ)
    last_year, last_month = end_local.year, end_local.month
    year, month = contract_start.year, contract_start.month
    out: dict[str, dict[str, Any]] = {}

    while (year, month) <= (last_year, last_month):
        m_start, m_end = _month_start_end(year, month)
        tot = {
            "p_inflow": 0.0,
            "p_invoice": 0.0,
            "t_inflow": 0.0,
            "t_invoice": 0.0,
            "p_imp": 0.0,
            "t_imp": 0.0,
            "p_exp": 0.0,
            "t_exp": 0.0,
            "hours_matched": 0,
            "hours_expected": 0,
            "month_end_ts": m_end,
        }
        for ts in _iter_hour_starts(m_start, m_end):
            if ts > until_ts:
                break
            tot["hours_expected"] += 1
            rec = hours.get(ts)
            if rec is None or not is_matched(rec):
                continue
            tot["hours_matched"] += 1
            m = hour_metrics(rec, basis)
            tot["p_inflow"] += m["pstryk_sell_value"]
            tot["p_invoice"] += m["pstryk_invoice_cost"]
            tot["t_inflow"] += m["osd_sell_value"]
            tot["t_invoice"] += m["osd_invoice_cost"]
            tot["p_imp"] += m["pstryk_import"]
            tot["t_imp"] += m["osd_import"]
            tot["p_exp"] += m["pstryk_export"]
            tot["t_exp"] += m["osd_export"]
        out[f"{year:04d}-{month:02d}"] = tot
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return out


def build_corrections(
    model: Mapping[str, Mapping[str, Any]],
    official_months: Mapping[str, Mapping[str, Any]],
    monthly_fee: float = 0.0,
) -> dict[str, MonthCorrection]:
    """FV months → corrections; other months are pure model estimates."""
    out: dict[str, MonthCorrection] = {}
    for month in sorted(model):
        m = model[month]
        fv = official_months.get(month) or {}
        if fv:
            extra_invoice = 0.0
            if fv.get("invoice") is not None:
                extra_invoice = float(fv["invoice"]) - (m["p_invoice"] + monthly_fee)
            extra_inflow = 0.0
            if fv.get("inflow") is not None:
                extra_inflow = float(fv["inflow"]) - m["p_inflow"]
            bonus = float(fv.get("bonus") or 0.0)
            used = None
            if fv.get("deposit_used") is not None or bonus:
                used = float(fv.get("deposit_used") or 0.0) + bonus
            out[month] = MonthCorrection(
                extra_invoice=extra_invoice,
                extra_inflow=extra_inflow,
                bonus=bonus,
                deposit_used=used,
                status="fv",
                fv_number=str(fv["number"]) if fv.get("number") else None,
            )
        else:
            out[month] = MonthCorrection(status="estimate")
    return out


def deposit_ledger(
    model: Mapping[str, Mapping[str, Any]],
    corrections: Mapping[str, MonthCorrection],
    *,
    source: str,
    cfg: DepositConfig,
) -> list[dict[str, Any]]:
    """Monthly deposit ledger. Invoice for M is paid from the balance at end of M-1.

    source: "pstryk" | "tauron"
    """
    if source == "pstryk":
        src = "p"
    elif source == "tauron":
        src = "t"
    else:
        raise ValueError(f"Unknown deposit source: {source}")

    balance = float(cfg.deposit_opening_balance)
    rows: list[dict[str, Any]] = []
    for month in sorted(model):
        m = model[month]
        c = corrections.get(month) or MonthCorrection()
        inflow = m[f"{src}_inflow"] + c.extra_inflow
        invoice = m[f"{src}_invoice"] + float(cfg.monthly_fee) + c.extra_invoice
        if source == "pstryk" and c.deposit_used is not None:
            used = c.deposit_used
        else:
            used = min(max(invoice, 0.0), max(balance, 0.0))
        to_pay = max(invoice, 0.0) - used
        adjustment = float(cfg.monthly_adjustments.get(month, 0.0) or 0.0)
        balance = balance - used + inflow + adjustment
        rows.append(
            {
                "month": month,
                "status": c.status,
                "fv_number": c.fv_number,
                "inflow": _round_pln(inflow),
                "invoice": _round_pln(invoice),
                "bonus": _round_pln(c.bonus),
                "used": _round_pln(used),
                "to_pay": _round_pln(to_pay),
                "adjustment": _round_pln(adjustment),
                "balance": _round_pln(balance),
                "hours_matched": m["hours_matched"],
                "hours_expected": m["hours_expected"],
            }
        )
    return rows


def monthly_rows(
    model: Mapping[str, Mapping[str, Any]],
    ledger_p: list[dict[str, Any]],
    ledger_t: list[dict[str, Any]],
    settled_through: str | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """One row per month combining measurements and both deposit ledgers."""
    by_p = {r["month"]: r for r in ledger_p}
    by_t = {r["month"]: r for r in ledger_t}
    rows: list[dict[str, Any]] = []
    prev_d_dep = 0.0
    sums = {k: 0.0 for k in ("imp_p", "imp_t", "exp_p", "exp_t")}
    for month in sorted(model):
        m = model[month]
        rp, rt = by_p.get(month), by_t.get(month)
        if rp is None or rt is None:
            continue
        if rp["status"] == "fv":
            status = "fv"
        elif settled_through is not None and month > settled_through:
            status = "open"
        else:
            status = "estimate"
        d_imp = m["p_imp"] - m["t_imp"]
        d_exp = m["p_exp"] - m["t_exp"]
        d_dep = rp["balance"] - rt["balance"]
        rows.append(
            {
                "month": month,
                "status": status,
                "fv_number": rp["fv_number"],
                "hours": f"{m['hours_matched']}/{m['hours_expected']}",
                "imp_p": _round_kwh(m["p_imp"]),
                "imp_t": _round_kwh(m["t_imp"]),
                "d_imp": _round_kwh(d_imp),
                "d_imp_pct": _pct(d_imp, m["t_imp"]),
                "exp_p": _round_kwh(m["p_exp"]),
                "exp_t": _round_kwh(m["t_exp"]),
                "d_exp": _round_kwh(d_exp),
                "d_exp_pct": _pct(d_exp, m["t_exp"]),
                "inflow_p": rp["inflow"],
                "inflow_t": rt["inflow"],
                "invoice_p": rp["invoice"],
                "used_p": rp["used"],
                "used_t": rt["used"],
                "bonus": rp["bonus"],
                "dep_p": rp["balance"],
                "dep_t": rt["balance"],
                "d_dep": _round_pln(d_dep),
                "d_dep_month": _round_pln(d_dep - prev_d_dep),
            }
        )
        prev_d_dep = d_dep
        sums["imp_p"] += m["p_imp"]
        sums["imp_t"] += m["t_imp"]
        sums["exp_p"] += m["p_exp"]
        sums["exp_t"] += m["t_exp"]

    d_imp_tot = sums["imp_p"] - sums["imp_t"]
    d_exp_tot = sums["exp_p"] - sums["exp_t"]
    last = rows[-1] if rows else {}
    totals = {
        "imp_p": _round_kwh(sums["imp_p"]),
        "imp_t": _round_kwh(sums["imp_t"]),
        "d_imp": _round_kwh(d_imp_tot),
        "d_imp_pct": _pct(d_imp_tot, sums["imp_t"]),
        "exp_p": _round_kwh(sums["exp_p"]),
        "exp_t": _round_kwh(sums["exp_t"]),
        "d_exp": _round_kwh(d_exp_tot),
        "d_exp_pct": _pct(d_exp_tot, sums["exp_t"]),
        "dep_p": last.get("dep_p"),
        "dep_t": last.get("dep_t"),
        "d_dep": last.get("d_dep"),
    }
    return rows, totals


_OFFICIAL_FLOAT_KEYS = ("invoice", "deposit_used", "bonus", "to_pay", "inflow")


def parse_official_months(raw: Any) -> dict[str, dict[str, Any]]:
    """Parse YYYY-MM → FV override map from dict or JSON string."""
    if raw is None or raw == "" or raw == {}:
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
    month_re = re.compile(r"^\d{4}-\d{2}$")
    out: dict[str, dict[str, Any]] = {}
    for key, val in raw.items():
        k = str(key)
        if not month_re.match(k):
            raise ValueError(f"bad month key: {k}")
        if val is None:
            continue
        if not isinstance(val, dict):
            raise ValueError(f"month {k} must be an object")
        entry: dict[str, Any] = {}
        for fk in _OFFICIAL_FLOAT_KEYS:
            if fk in val and val[fk] is not None and val[fk] != "":
                entry[fk] = float(val[fk])
        if val.get("number") is not None and val.get("number") != "":
            entry["number"] = str(val["number"])
        if entry:
            out[k] = entry
    return out


def compute_fixed(api_cost: float | None, p_imp: float | None, buy: float | None) -> float | None:
    """Derive fixed fee from API invoice formula."""
    if api_cost is None or p_imp is None or buy is None:
        return None
    return float(api_cost) - float(p_imp) * float(buy)


def settled_through_month(
    today: date | None = None,
    *,
    settlement_day: int = DEFAULT_SETTLEMENT_DAY,
    fv_months: Iterable[str] = (),
) -> str | None:
    """Last YYYY-MM whose invoice is visible in the Pstryk app deposit screen.

    Until ``settlement_day`` of month M, the app still shows deposit through M-2.
    From ``settlement_day`` onward it includes M-1. An entered FV for M-1
    (``fv_months``) settles it earlier.
    """
    today = today or datetime.now(tz=TZ).date()
    prev = f"{today.year - 1:04d}-12" if today.month == 1 else f"{today.year:04d}-{today.month - 1:02d}"
    # Months back from current calendar month
    back = 2 if today.day < settlement_day and prev not in set(fv_months) else 1
    y, m = today.year, today.month
    for _ in range(back):
        if m == 1:
            y -= 1
            m = 12
        else:
            m -= 1
    return f"{y:04d}-{m:02d}"


def ledger_balance_through(
    ledger: list[dict[str, Any]], through_month: str | None
) -> float | None:
    """Balance at end of ``through_month`` (inclusive), or None if missing."""
    if not ledger or not through_month:
        return None
    for row in ledger:
        if row.get("month") == through_month:
            bal = row.get("balance")
            return float(bal) if bal is not None else None
    return None

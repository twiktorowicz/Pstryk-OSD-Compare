"""Write external long-term statistics for Energy / statistics-graph."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from homeassistant.components.recorder.models import StatisticMeanType, StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.core import HomeAssistant

from .calc import cumulative_series
from .const import DOMAIN, METRICS, STATS_BATCH

_LOGGER = logging.getLogger(__name__)
UTC = timezone.utc


def statistic_id_for(meter_slug: str, metric: str) -> str:
    slug = "".join(c if c.isalnum() or c == "_" else "_" for c in meter_slug.lower())
    return f"{DOMAIN}:{slug}_{metric}"


async def async_write_statistics(
    hass: HomeAssistant,
    *,
    hours: dict[int, dict[str, Any]],
    basis: str,
    meter_slug: str,
    meter_name: str,
    rewrite_from_ts: int | None = None,
) -> int:
    """Rebuild cumulative series and push to Recorder. Returns row count written."""
    series = cumulative_series(hours, basis)
    total = 0
    for metric, rows in series.items():
        unit, label = METRICS[metric]
        if rewrite_from_ts is not None:
            rows = [(ts, state, sm) for ts, state, sm in rows if ts >= rewrite_from_ts]
        if not rows:
            continue
        sid = statistic_id_for(meter_slug, metric)
        metadata: StatisticMetaData = {
            "has_mean": False,
            "has_sum": True,
            "mean_type": StatisticMeanType.NONE,
            "name": f"Pstryk↔OSD {meter_name} {label}",
            "source": DOMAIN,
            "statistic_id": sid,
            "unit_of_measurement": unit,
            "unit_class": "energy" if unit == "kWh" else None,
        }
        # Recompute sum within the rewritten slice so HA gets continuous sums
        # from the first rewritten hour; for full rewrite use full cumulative.
        if rewrite_from_ts is not None and rows:
            # Prefer full-series sums already in `series` (third tuple element).
            # When filtering, those sums remain absolute from start — correct for overwrite.
            pass

        for i in range(0, len(rows), STATS_BATCH):
            batch = rows[i : i + STATS_BATCH]
            stats = [
                {
                    "start": datetime.fromtimestamp(ts, tz=UTC),
                    "state": state,
                    "sum": cum,
                }
                for ts, state, cum in batch
            ]
            async_add_external_statistics(hass, metadata, stats)
            total += len(stats)

    _LOGGER.info(
        "Wrote %s statistic rows for %s (basis=%s, from=%s)",
        total,
        meter_slug,
        basis,
        rewrite_from_ts,
    )
    return total

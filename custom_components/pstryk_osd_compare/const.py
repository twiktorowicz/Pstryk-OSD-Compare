"""Constants for Pstryk OSD Compare."""

from __future__ import annotations

from zoneinfo import ZoneInfo

DOMAIN = "pstryk_osd_compare"
TZ = ZoneInfo("Europe/Warsaw")

PSTRYK_API_BASE = "https://api.pstryk.pl"
PSTRYK_API_PATH = "/integrations/meter-data/unified-metrics/"
PSTRYK_CHUNK_DAYS = 5
PSTRYK_REFRESH_BACK_HOURS = 72
TAURON_REFRESH_BACK_DAYS = 7
DSO_STALE_DAYS = 4
TAURON_STAT_PREFIX = "tauron_importer"
STATS_BATCH = 2000

CONF_API_KEY = "api_key"
CONF_SOURCE_TYPE = "source_type"
CONF_METER_ID = "meter_id"
CONF_METER_NAME = "meter_name"
CONF_STAT_IDS = "stat_ids"
CONF_CONTRACT_START = "contract_start"
CONF_CONTRACT_END = "contract_end"
CONF_BACKFILL_TAURON = "backfill_tauron"
CONF_TAURON_BASIS = "tauron_basis"
CONF_SYNC_INTERVAL_HOURS = "sync_interval_hours"
CONF_DEPOSIT_OPENING_BALANCE = "deposit_opening_balance"
CONF_MONTHLY_FEE = "monthly_fee"
CONF_MONTHLY_ADJUSTMENTS = "monthly_adjustments"
CONF_OFFICIAL_MONTHS = "official_months"
CONF_SETTLEMENT_DAY = "settlement_day"

SOURCE_TAURON = "tauron"
SOURCE_CUSTOM = "custom"
BASIS_BALANCED = "balanced"
BASIS_GROSS = "gross"

DEFAULT_TAURON_BASIS = BASIS_BALANCED
DEFAULT_SYNC_INTERVAL_HOURS = 3
DEFAULT_BACKFILL_TAURON = True
DEFAULT_DEPOSIT_OPENING_BALANCE = 0.0
DEFAULT_MONTHLY_FEE = 0.0
DEFAULT_MONTHLY_ADJUSTMENTS: dict[str, float] = {}
DEFAULT_OFFICIAL_MONTHS: dict[str, dict] = {}
DEFAULT_SETTLEMENT_DAY = 6  # Pstryk issues invoices ~4th–6th; app shows M-2 until then

# Keys accepted inside official_months[YYYY-MM]
OFFICIAL_MONTH_FIELDS = (
    "invoice",
    "deposit_used",
    "bonus",
    "to_pay",
    "inflow",
    "number",
)

PERIODS = ("current_month", "previous_month", "current_year", "previous_day")
SUMMARY_SENSORS = (
    "diff_import",
    "diff_export",
    "diff_buy_value",
    "diff_sell_value",
    "diff_net_value",
)

# metric -> (unit, display name PL)
METRICS: dict[str, tuple[str, str]] = {
    "pstryk_import": ("kWh", "Pstryk import"),
    "pstryk_export": ("kWh", "Pstryk eksport"),
    "tauron_import": ("kWh", "OSD import"),
    "tauron_export": ("kWh", "OSD eksport"),
    "diff_import": ("kWh", "Δ import"),
    "diff_export": ("kWh", "Δ eksport"),
    "pstryk_buy_value": ("PLN", "Pstryk wartość zakupu"),
    "pstryk_sell_value": ("PLN", "Pstryk wartość sprzedaży"),
    "tauron_buy_value": ("PLN", "OSD wartość zakupu"),
    "tauron_sell_value": ("PLN", "OSD wartość sprzedaży"),
    "diff_buy_value": ("PLN", "Δ wartość zakupu"),
    "diff_sell_value": ("PLN", "Δ wartość sprzedaży"),
    "diff_net_value": ("PLN", "Δ netto"),
    "pstryk_invoice_cost": ("PLN", "Pstryk koszt faktury"),
    "tauron_invoice_cost": ("PLN", "OSD koszt faktury"),
    "diff_invoice_cost": ("PLN", "Δ koszt faktury"),
}

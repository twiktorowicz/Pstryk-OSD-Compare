# Changelog

## v1.3.0

### Tarcza Pstryk

- Integracja liczy miesięczny **„Rabat – Tarcza Pstryk”** z cen godzinowych API (energia netto + opłata za obsługę) i odejmuje go od faktury w modelu depozytu — również w **bieżącym miesiącu** (szacunek na dziś).
- Zasady: 2025 — 0,62 zł/kWh brutto (energia + obsługa), 2026 — 0,61 zł/kWh brutto (energia + obsługa), 2027 — 0,50 zł/kWh netto (sama energia, umowy podpisane do 31.12.2026).
- Nowa opcja **Lata z Tarczą Pstryk** (Konfiguruj) — domyślnie lata od startu umowy; odznacz rok, w którym nie masz tarczy.
- Strona OSD dostaje rabat policzony z kWh OSD, więc Δ depozytu dalej wynika tylko z pomiarów.
- Po aktualizacji integracja **jednorazowo pobiera ponownie** historię z API Pstryk (ceny netto) — pierwsza synchronizacja może potrwać kilka minut.

### Formularz FV

- Nowe pola **FV tarcza** (`number.osd_fv_tarcza`, podpowiadane z modelu) i **FV portfel** (`number.osd_fv_portfel`, np. 61,50 zł za polecenie). Obie kwoty informacyjne — **FV faktura** to wartość brutto faktury już po rabatach.
- Usługa `set_official_month` przyjmuje `shield` i `wallet`.
- `sensor.osd_miesiace`: kolumny `shield_p`, `shield_t`, `wallet`, `invoice_t`, atrybut `shield_years`; `select.osd_fv_miesiac`: `model_shield`, `model_shield_avg`.
- Przykładowy dashboard: kolumny Tarcza / Portfel w „Korekty z FV”, nowe pola formularza.

---

## v1.2.0

### Zmiana nazw — sprawdź swój dashboard

Nazwy nie wskazują już Taurona — strona OSD nazywa się tak samo dla każdego operatora. **Integracja przenosi wszystko sama** przy pierwszym starcie po aktualizacji (historia encji zostaje; statystyki wykresów są odtwarzane w całości z danych integracji w ciągu kilku minut po restarcie).

| Było | Jest |
|---|---|
| `sensor.osd_depozyt_tauron` | `sensor.osd_depozyt_osd` |
| `sensor.osd_depozyt_tauron_rozliczony` | `sensor.osd_depozyt_osd_rozliczony` |
| `pstryk_osd_compare:…_tauron_import` | `pstryk_osd_compare:…_osd_import` |
| `pstryk_osd_compare:…_tauron_export` | `pstryk_osd_compare:…_osd_export` |
| `…_tauron_buy_value` / `_sell_value` / `_invoice_cost` | `…_osd_buy_value` / `_sell_value` / `_invoice_cost` |
| atrybuty `tauron_import`, `tauron_export`, … `hours_tauron_only`, `tauron_hours` | `osd_import`, `osd_export`, … `hours_osd_only`, `osd_hours` |

**Co zrobić:** dashboardu wklejonego ręcznie HA nie poprawi sam. Otwórz pulpit → ⋮ → Edytuj → ⋮ → **Edytor surowej konfiguracji** i zamień:
- `osd_depozyt_tauron` → `osd_depozyt_osd`,
- `_tauron_import` → `_osd_import`, `_tauron_export` → `_osd_export` (i inne `_tauron_` w identyfikatorach statystyk),
- w szablonach markdown: `tauron_import` → `osd_import` itd.

Jeśli samodzielnie zmieniłeś `entity_id` tych sensorów, integracja go nie rusza. Aktualny przykład: [`dashboards/compare_dashboard.yaml`](https://github.com/twiktorowicz/Pstryk-OSD-Compare/blob/main/dashboards/compare_dashboard.yaml).

### Inne

- Etykiety: „Depozyt OSD”, „Depozyt OSD rozliczony”; w statystykach i dashboardzie „OSD” zamiast „Tauron”.

---

**EN:** Operator-neutral names: `tauron_*` entity IDs, statistic IDs and attributes are now `osd_*` (table above). Migration runs automatically on first start (entity history kept; chart statistics are rebuilt from the integration's data within minutes). Manually pasted dashboards must be updated: replace `osd_depozyt_tauron` → `osd_depozyt_osd` and `_tauron_` → `_osd_` in statistic IDs and templates.

## v1.1.0

### Nowe

- **Enea i Energa wykrywane automatycznie** w kreatorze — obok Taurona. Wystarczy zainstalowana integracja operatora ([Enea Licznik](https://github.com/PanSzelescik/home-assistant-enea), [Energa My Meter](https://github.com/ergo5/hass-energa-my-meter-api) lub fork [.NET](https://github.com/lkusinski/hass-energa-my-meter-api-net)).
- **Taryfy strefowe Energi (G12 / G12w)**: strefa 1 + strefa 2 sumowane automatycznie.
- **Własne statystyki: kilka serii w jednym polu** (sumowane) — strefy, wymiana licznika w trakcie umowy.
- **Podstawa „po bilansowaniu” dla każdego źródła**: gdy OSD nie publikuje osobnych serii, integracja liczy saldo godzinowe sama (dokładnie tak, jak robi to Tauron; dla danych już zbilansowanych wynik się nie zmienia).
- README: sekcja [Obsługiwani operatorzy (OSD)](https://github.com/twiktorowicz/Pstryk-OSD-Compare#obsługiwani-operatorzy-osd) — instrukcja dla Tauron, Enea, Energa, PGE (wM-Bus / MojeIRE), Stoen (P1) i własnych czytników.

### Poprawki

- Własne statystyki (sensory licznika, P1, wM-Bus, Energa) były czytane jako stan licznika zamiast zużycia godzinowego. Teraz energia godzinowa liczona jest ze zmiany sumy statystyki. Dane Taurona bez zmian.

### Aktualizacja

Po aktualizacji zrestartuj Home Assistant. Istniejąca konfiguracja działa bez zmian; wyniki dla Taurona są identyczne jak w v1.0.0.

---

**EN:** Enea and Energa meters are now auto-discovered; Energa G12/G12w zones are summed; custom statistics accept several series per field; the balanced basis works for every source (hourly netting computed when the DSO has no balanced series). Fix: custom statistics are read from the hourly sum change instead of the cumulative state. Restart HA after updating; existing Tauron setups are unchanged.

## v1.0.0

Pierwsze publiczne wydanie: porównanie godzinowych danych Pstryk z danymi Tauron AMIplus, wycena cenami Pstryka, depozyt prosumencki, formularz FV, dashboard.

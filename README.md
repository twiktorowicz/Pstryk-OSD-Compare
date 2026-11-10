# Pstryk OSD Compare

[![Validate](https://github.com/twiktorowicz/Pstryk-OSD-Compare/actions/workflows/validate.yaml/badge.svg)](https://github.com/twiktorowicz/Pstryk-OSD-Compare/actions/workflows/validate.yaml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)

Integracja Home Assistant (HACS), która porównuje **godzinowe dane licznika Pstryk** z **oficjalnymi danymi OSD** (Tauron, Enea, Energa — wykrywane automatycznie; PGE, Stoen i inni — przez statystyki godzinowe z czytnika licznika) i wycenia obie strony **cenami Pstryka**. Pokazuje, ile kWh i złotych dzieli oba pomiary oraz jak różnica przekłada się na **depozyt prosumencki**.

> English summary at the bottom.

## Do czego to służy

- Pstryk rozlicza Cię na podstawie własnego licznika (BleBox), OSD (np. Tauron) — na podstawie licznika operatora. Wartości różnią się, zwykle na eksporcie.
- Integracja dopasowuje godzina do godziny oba źródła, wycenia je tymi samymi cenami Pstryka i liczy depozyt „tak, jak gdyby rozliczać z danych OSD”.
- Wynik: Δ = **Pstryk − OSD** w kWh i PLN, miesiąc po miesiącu, plus wpływ na saldo depozytu (rozliczone jak w aplikacji Pstryk oraz „na dziś”).

## Wymagania

| Co | Uwagi |
|---|---|
| Home Assistant **2025.1+** | testowane na 2026.x |
| **Klucz API Pstryk** | aplikacja Pstryk → Ustawienia → API. Można użyć tego samego klucza co w Pstryk AiO (integracja nie czyta cudzych sekretów). |
| **Godzinowe statystyki OSD** w Recorderze | z integracji Twojego operatora (Tauron / Enea / Energa) albo z lokalnego czytnika licznika — patrz [Obsługiwani operatorzy](#obsługiwani-operatorzy-osd). Wystarczą dowolne statystyki long-term z sumą (kWh) poboru i oddania. |

Pstryk AiO **nie jest wymagany**.

## Obsługiwani operatorzy (OSD)

Integracja nie łączy się z portalami OSD sama — czyta **godzinowe statystyki** zapisane w Home Assistant przez integrację operatora albo przez lokalny czytnik licznika. Dlatego działa z każdym źródłem, które daje kWh godzina po godzinie.

| OSD | Źródło danych | Wykrywanie | Uwagi |
|---|---|---|---|
| **Tauron Dystrybucja** | [Tauron AMIplus](https://github.com/skoczo/Home-Assistant-custom-components-Tauron-AMIplus) (HACS) | automatyczne | serie surowe i po bilansowaniu; uzupełnianie historii do 365 dni |
| **Enea Operator** | [Enea Licznik](https://github.com/PanSzelescik/home-assistant-enea) (HACS) | automatyczne | statystyki `enea:{PPE}_energia_pobrana` / `_energia_oddana` |
| **Energa-Operator** | [Energa My Meter API](https://github.com/ergo5/hass-energa-my-meter-api) lub fork [.NET](https://github.com/lkusinski/hass-energa-my-meter-api-net) (HACS) | automatyczne | `sensor.energa_{nr}_panel_energia_*`; strefy G12/G12w sumowane |
| **PGE Dystrybucja** | czytnik wM-Bus (jeśli licznik nadaje) / usługa płatna PGE / [MojeIRE](https://mojeire.pl) (tylko CSV) | ręczne | brak publicznego API |
| **Stoen Operator** | czytnik P1 (liczniki Gama 350 / 150) przez ESPHome | ręczne | potrzebny klucz szyfrowania z BOK Stoen |
| inni / własny licznik | dowolny sensor energii `total_increasing` (kWh) | ręczne | |

**Podstawa porównania** (Konfiguruj → *Podstawa OSD*): `balanced` = saldo godzinowe poboru i oddania — tak OSD rozlicza prosumentów net-billing. Gdy źródło nie ma osobnych serii po bilansowaniu (Enea, Energa, czytniki), integracja liczy saldo sama: `max(pobór − oddanie, 0)` i odwrotnie dla oddania. To jest dokładnie to, co publikuje Tauron (sprawdzone na danych), a dla danych już zbilansowanych przez OSD wynik się nie zmienia.

### Tauron

1. HACS → **Tauron AMIplus** → zainstaluj, restart HA.
2. Dodaj integrację, zaloguj się danymi z eLicznika, włącz **generation**, **balanced** i **store statistics**.
3. Poczekaj na pierwszy import (statystyki `tauron_importer:…`), potem dodaj *Pstryk OSD Compare* — licznik pojawi się na liście.

### Enea

1. Konto na [portalodbiorcy.operator.enea.pl](https://portalodbiorcy.operator.enea.pl/) z przypisanym licznikiem AMI.
2. HACS → **Enea Licznik** → zainstaluj, restart HA, dodaj integrację (e-mail + hasło portalu).
3. Dane za poprzedni dzień pojawiają się zwykle rano (integracja Enei odświeża co ~3,5 h). Historię wstecz pobierzesz usługą `enea.backfill`.
4. Dodaj *Pstryk OSD Compare* → wybierz „Enea: {PPE}”.

> Jeśli portal Enei nie opublikuje danych za dzień, integracja Enei po 3 dniach wpisuje zero. Taki dzień pokaże się jako duża różnica — po pojawieniu się danych uruchom `enea.backfill` dla tego dnia, a potem `pstryk_osd_compare.resync`.

### Energa

1. Konto w [Mój Licznik](https://mojlicznik.energa-operator.pl/) z przypisanym licznikiem.
2. HACS → **Energa My Meter** (ergo5) lub fork .NET → zainstaluj, restart HA, dodaj integrację.
3. Zaimportuj historię usługą `energa_mobile.fetch_history` (w UI: *Download History*) — statystyki `sensor.energa_{nr}_panel_energia_zuzycie` / `_produkcja` (taryfy strefowe: `_strefa_1` + `_strefa_2`).
4. Dodaj *Pstryk OSD Compare* → wybierz „Energa: {nr}”. Przy taryfie G12/G12w obie strefy są sumowane automatycznie.

### PGE

PGE Dystrybucja nie udostępnia danych godzinowych przez API. Możliwości:

- **Czytnik wM-Bus** (np. [wmbusmeters](https://github.com/wmbusmeters/wmbusmeters) + odbiornik 868 MHz albo ESPHome `wmbus`) — tylko jeśli licznik nadaje wM-Bus i masz klucz od OSD.
- **Usługa płatna PGE** (dane profilowe) albo **MojeIRE / CSIRE** — eksport CSV. Do HA trzeba je zaimportować jako statystyki zewnętrzne (np. [Home Assistant Statistics Import](https://github.com/klausj1/homeassistant-statistics)).

Potem: *Pstryk OSD Compare* → „Wskaż statystyki godzinowe ręcznie” → pobór / oddanie.

### Stoen (Warszawa)

1. Złóż w BOK Stoen Operator wniosek o aktywację portu **P1** i **klucz szyfrowania** (liczniki Gama 350 / 150).
2. Czytnik na ESP32 z ESPHome (komponent `dlms_meter`, port P1: 115200 8N1, sygnał odwrócony) + `decryption_key`.
3. Utwórz sensory energii poboru (A+) i oddania (A−) w kWh, `state_class: total_increasing`.
4. *Pstryk OSD Compare* → „Wskaż statystyki godzinowe ręcznie”.

### Własne statystyki (P1, wM-Bus, inne)

- W każdym polu można wybrać **kilka statystyk** — są sumowane (np. strefy taryfy albo licznik wymieniony w trakcie umowy).
- Godzinowe kWh liczone są ze **zmiany sumy**, więc pasują zwykłe sensory licznika (`total_increasing`) i statystyki zewnętrzne.
- Serie po bilansowaniu są opcjonalne (tylko parami) — bez nich saldo liczone jest automatycznie.
- Lokalny czytnik mierzy ten sam licznik co OSD, ale bez korekt i uzupełnień OSD — różnice rzędu dziesiątych procenta są normalne.

## Instalacja

Najprościej przyciskiem (otwiera repozytorium w HACS albo w Marketplace, zależnie od wersji HA):

[![Otwórz w Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=twiktorowicz&repository=Pstryk-OSD-Compare&category=integration)

Ręcznie:

1. Dodaj repozytorium `https://github.com/twiktorowicz/Pstryk-OSD-Compare` jako własne, kategoria **Integration**:
   - **HA 2026.11 i nowsze:** Ustawienia → **Marketplace** → ⋮ → *Custom repositories* (wymaga połączenia z GitHubem, kreator to zaproponuje),
   - **HA do 2026.10:** HACS → ⋮ → *Custom repositories*.
2. Pobierz **Pstryk OSD Compare** i zrestartuj Home Assistant.
3. Ustawienia → Urządzenia i usługi → **Dodaj integrację** → *Pstryk OSD Compare*:
   1. klucz API Pstryk,
   2. wybór wykrytego licznika (Tauron / Enea / Energa) lub „własne statystyki” (PGE, Stoen, czytnik P1 / wM-Bus),
   3. okres umowy Pstryk (start podpowiadany z API) i — tylko dla Taurona — opcja uzupełniania brakującej historii (do 365 dni).

Pierwsza synchronizacja pobiera dane od początku umowy (API Pstryk w paczkach po 5 dni) — może potrwać kilka minut. Kolejne co 3 h (opcja).

Instalacja ręczna: skopiuj `custom_components/pstryk_osd_compare/` do `/config/custom_components/` i zrestartuj HA.

## Opcje (Konfiguruj)

| Opcja | Domyślnie | Znaczenie |
|---|---|---|
| Podstawa OSD | `balanced` | `balanced` = dane po bilansowaniu godzinowym (tak liczy OSD); `gross` = surowe rejestry |
| Interwał synchronizacji | 3 h | |
| Saldo początkowe depozytu | 0 zł | gdy umowa zaczęła się z niezerowym depozytem |
| Dodatkowa opłata miesięczna | 0 zł | opłaty spoza API doliczane do modelu faktury |
| Dzień rozliczenia | 6 | Pstryk wystawia FV zwykle 4.–6. dnia; do tego dnia depozyt „rozliczony” liczony jest do M−2, potem do M−1. Wpisanie FV za M−1 przesuwa to od razu. |
| Korekty miesięczne (JSON) | `{}` | `{"YYYY-MM": ±PLN}` — np. bonus za polecenie |
| Oficjalne FV (JSON) | `{}` | wygodniej: formularz FV (niżej) |

## Encje

Jedno urządzenie **Pstryk OSD Compare**. Identyfikatory są stałe (niezależne od nazwy licznika):

| Encja | Opis |
|---|---|
| `sensor.osd_ostatni_sync`, `sensor.osd_dane_do`, `sensor.osd_pokrycie` | stan danych: ostatnia synchronizacja, ostatnia godzina z OSD, % dopasowanych godzin |
| `sensor.osd_miesiace` | wiersz na miesiąc (kWh P/T, depozyty, Δ, status `FV` / `szacunek` / `otwarty`) + `totals`; atrybut `statistics` zawiera ID statystyk do wykresów |
| `sensor.osd_depozyt_pstryk` / `_osd` / `_roznica` | saldo depozytu na dziś (z bieżącym miesiącem) |
| `sensor.osd_depozyt_pstryk_rozliczony` / `_osd_rozliczony` / `_roznica_rozliczona` | saldo do ostatniej rozliczonej faktury (jak w aplikacji) |
| `sensor.osd_{okres}_diff_{import,export,buy_value,sell_value,net_value}` | Δ dla `current_month`, `previous_month`, `current_year`, `previous_day` |
| `sensor.osd_rozbicie_dzienne`, `date.osd_dzien_analizy`, `sensor.osd_wybrany_dzien` | rozbicie dzienne i godzinowe wybranego dnia |
| `select.osd_fv_miesiac`, `number.osd_fv_*`, `text.osd_fv_numer`, `button.osd_fv_zapisz` / `_usun` | formularz FV (kategoria *Konfiguracja*) |

Statystyki zewnętrzne `pstryk_osd_compare:<licznik>_<metryka>` (godzinowe, z sumą) — do kart `statistics-graph` i panelu Energia: `pstryk_import`, `osd_import`, `pstryk_export`, `osd_export`, wartości PLN i Δ.

Przy drugim wpisie (drugi licznik) HA doda do identyfikatorów sufiks `_2`.

## Faktury (FV) — formularz

API Pstryka nie udostępnia faktur ani salda depozytu, a FV zawierają pozycje, których nie widać w danych godzinowych (opłaty, bonus lojalnościowy). Po opublikowaniu FV w aplikacji Pstryk:

1. Na dashboardzie kliknij **Dodaj / popraw FV** (lub użyj encji `*_osd_fv_*` z urządzenia).
2. Wybierz miesiąc — domyślnie pierwszy zamknięty miesiąc bez FV. Pola wypełniają się modelem z API (faktura, oddana energia) albo zapisaną wcześniej FV.
3. Przepisz z FV:

   | Pole | Pozycja na FV |
   |---|---|
   | FV faktura | Wartość brutto faktury |
   | FV z depozytu | Rozliczenie depozytu prosumenta |
   | FV bonus | Rozliczenie bonusu lojalnościowego |
   | FV oddana energia | Oddana energia (zasilenie depozytu) |
   | FV numer | numer faktury, np. `SE/P/1234/09/2026` |

4. **FV zapisz** — integracja przeładuje się (kilka sekund). **FV usuń** kasuje wpis dla wybranego miesiąca.

Jak FV wpływa na wyliczenia: różnica `FV − model z API` traktowana jest jako wspólna korekta **obu stron** (Pstryk i OSD), więc Δ depozytu wynika wyłącznie z różnic pomiarowych. Ta sama operacja jest dostępna jako usługa `pstryk_osd_compare.set_official_month` (także masowo przez `months_json`).

### Model depozytu

Dla każdej dopasowanej godziny, osobno dla kWh Pstryka i kWh OSD (te same ceny Pstryka):

- **wpływ** miesiąca = Σ eksport × cena sprzedaży,
- **faktura** miesiąca = Σ koszt poboru (+ opcjonalna opłata miesięczna),
- faktura za miesiąc M pokrywana jest z salda na koniec M−1, potem dochodzi wpływ za M,
- depozyt pokrywa **całą** fakturę — na FV rozbitą na „Rozliczenie depozytu prosumenta” i „Rozliczenie bonusu lojalnościowego”; obie pozycje zmniejszają depozyt,
- depozyt nie wygasa; reszta przechodzi na kolejny miesiąc.

## Usługi

| Usługa | Działanie |
|---|---|
| `pstryk_osd_compare.resync` | ponowne pobranie danych od daty i przepisanie statystyk |
| `pstryk_osd_compare.export_csv` | CSV godzinowy do `/config/www/pstryk_osd_compare/` |
| `pstryk_osd_compare.set_official_month` | zapis/usunięcie FV dla miesiąca (lub wielu przez JSON) |
| `pstryk_osd_compare.set_monthly_adjustment` | korekta PLN dla miesiąca (0 usuwa) |

## Dashboard

Przykład: [`dashboards/compare_dashboard.yaml`](dashboards/compare_dashboard.yaml) — wyłącznie wbudowane karty, dwa widoki:

- **OSD** — stan danych, wpływ na depozyt, tabela miesięczna, wykresy miesięczne import/eksport, szczegóły dnia, lista FV z przyciskiem **Dodaj / popraw FV**;
- **osd-fv** (podwidok) — formularz FV z podpowiedzią „model vs zapisana FV”.

Instalacja:

1. Ustawienia → Pulpity → **Dodaj pulpit** → „Nowy pulpit od zera”, otwórz go → ⋮ → Edytuj → ⋮ → **Edytor surowej konfiguracji**.
2. Wklej zawartość pliku i zamień każde `YOUR_METER_ID` na identyfikator licznika. Gotowe ID statystyk znajdziesz w Narzędzia deweloperskie → Stany → `sensor.osd_miesiace` → atrybut `statistics` (np. `pstryk_osd_compare:1234567_89012345_1234567_pstryk_import` → `YOUR_METER_ID` = `1234567_89012345_1234567`).
3. Jeśli wklejasz widoki do istniejącego pulpitu, zachowaj `path: osd-fv` — przycisk formularza nawiguje do tej ścieżki.

## Jak czytać różnice

- **Import** zwykle zgadza się z dokładnością ~1–2%.
- **Eksport** Pstryka bywa wyższy: stały „szum” rzędu kilkuset W na licznikach CT w okresach bez przepływu (licznik Pstryka widzi wtedy niewielki eksport, OSD — zero) plus kilka procent przy dużym eksporcie. Na kilka kWh dziennie to wystarcza, żeby po pół roku różnica depozytu sięgała setek złotych.
- **Δ depozytu** narasta miesiąc po miesiącu — tabela miesięczna pokazuje, gdzie powstaje.
- Godziny bez danych OSD (zwykle ostatnie 1–2 dni) są pomijane po obu stronach; kolumna „Godz.” pokazuje dopasowane / wszystkie.

Gdy OSD przestanie dostarczać dane na dłużej niż 4 dni, w **Ustawienia → Naprawy** pojawi się ostrzeżenie (znika samo po powrocie danych).

## Rozwój

```bash
pip install pytest ruff
ruff check custom_components tests
python3 -m pytest tests -q
```

Struktura `custom_components/pstryk_osd_compare/`:

| Plik | Rola |
|---|---|
| `pstryk_client.py` | API Pstryk (`unified-metrics`, godzinowo, paczki po 5 dni) |
| `tauron_reader.py` | odczyt statystyk OSD z Recordera, wykrywanie liczników (Tauron / Enea / Energa), backfill Tauron |
| `osd_series.py` | czyste funkcje: rozpoznawanie serii OSD, godzinowe kWh ze zmiany sumy, sumowanie stref |
| `store.py` | lokalny magazyn godzin (Pstryk + OSD) |
| `calc.py` | czyste obliczenia: dopasowanie godzin, wyceny, okresy, księga depozytu (bez importów HA — testowane w `tests/`) |
| `coordinator.py` | synchronizacja, statystyki zewnętrzne, ostrzeżenie `dso_stale` |
| `fv.py` + `select/number/text/button.py` | formularz FV |
| `sensor.py`, `date.py`, `services.py` | encje i usługi |

Wydanie: podbij `version` w `manifest.json`, dopisz sekcję `## vX.Y.Z` w [`CHANGELOG.md`](CHANGELOG.md), utwórz tag `vX.Y.Z` — workflow `release.yaml` zbuduje release z opisem z changeloga (widocznym też w HA przy aktualizacji). Tag musi zgadzać się z wersją, a sekcja changeloga musi istnieć.

---

## English summary

Home Assistant custom integration (HACS) that compares hourly **Pstryk** meter data (Polish dynamic-tariff supplier) with official **DSO** statistics (auto-discovered: Tauron AMIplus, Enea, Energa; or any hourly long-term statistics, e.g. P1 / wM-Bus readers for PGE and Stoen), values both at Pstryk prices and tracks the impact on the prosumer **deposit**.

- **Requirements:** HA 2025.1+, Pstryk API key, hourly DSO statistics from the DSO integration (Tauron AMIplus, Enea Licznik, Energa My Meter) or a local meter reader. See *Obsługiwani operatorzy* for per-DSO setup.
- **Install:** use the My Home Assistant button above, or add this repo as a custom repository (Integration) in HACS (HA ≤ 2026.10) or Settings → Marketplace (HA 2026.11+) → restart → add *Pstryk OSD Compare*.
- **Entities:** fixed IDs `sensor.osd_*`, `date.osd_dzien_analizy`, invoice (FV) form entities `select.osd_fv_miesiac`, `number.osd_fv_*`, `text.osd_fv_numer`, `button.osd_fv_zapisz|usun`; external statistics `pstryk_osd_compare:<meter>_<metric>`.
- **Invoices:** enter monthly invoice values via the dashboard form or `pstryk_osd_compare.set_official_month`; corrections apply equally to both sides, so the deposit delta reflects metering differences only.
- **Dashboard:** [`dashboards/compare_dashboard.yaml`](dashboards/compare_dashboard.yaml) (built-in cards; replace `YOUR_METER_ID`).
- UI texts are Polish and English; entity names are Polish.

## Licencja

[MIT](LICENSE)

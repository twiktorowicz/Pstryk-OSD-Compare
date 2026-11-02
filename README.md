# Pstryk OSD Compare

[![Validate](https://github.com/twiktorowicz/Pstryk-OSD-Compare/actions/workflows/validate.yaml/badge.svg)](https://github.com/twiktorowicz/Pstryk-OSD-Compare/actions/workflows/validate.yaml)
[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz/docs/faq/custom_repositories)

Integracja Home Assistant (HACS), która porównuje **godzinowe dane licznika Pstryk** z **oficjalnymi danymi OSD** (Tauron AMIplus; inni operatorzy przez własne statystyki godzinowe) i wycenia obie strony **cenami Pstryka**. Pokazuje, ile kWh i złotych dzieli oba pomiary oraz jak różnica przekłada się na **depozyt prosumencki**.

> English summary at the bottom.

## Do czego to służy

- Pstryk rozlicza Cię na podstawie własnego licznika (BleBox), OSD (np. Tauron) — na podstawie licznika operatora. Wartości różnią się, zwykle na eksporcie.
- Integracja dopasowuje godzina do godziny oba źródła, wycenia je tymi samymi cenami Pstryka i liczy depozyt „tak, jak gdyby rozliczać z danych OSD”.
- Wynik: Δ = **Pstryk − Tauron** w kWh i PLN, miesiąc po miesiącu, plus wpływ na saldo depozytu (rozliczone jak w aplikacji Pstryk oraz „na dziś”).

## Wymagania

| Co | Uwagi |
|---|---|
| Home Assistant **2025.1+** | testowane na 2026.x |
| **Klucz API Pstryk** | aplikacja Pstryk → Ustawienia → API. Można użyć tego samego klucza co w Pstryk AiO (integracja nie czyta cudzych sekretów). |
| **Godzinowe statystyki OSD** w Recorderze | zalecane: [Tauron AMIplus](https://github.com/skoczo/Home-Assistant-custom-components-Tauron-AMIplus) (HACS) z włączonymi opcjami **generation**, **balanced** i **store statistics**. Alternatywnie dowolne statystyki long-term (`sum`, kWh) poboru i oddania. |

Pstryk AiO **nie jest wymagany**.

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
   2. wybór wykrytego licznika Tauron (lub „własne statystyki”) — gdy lista jest pusta, kreator pokaże instrukcję instalacji Tauron AMIplus,
   3. okres umowy Pstryk (start podpowiadany z API) i opcja uzupełniania brakującej historii Tauron (do 365 dni).

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
| `sensor.osd_depozyt_pstryk` / `_tauron` / `_roznica` | saldo depozytu na dziś (z bieżącym miesiącem) |
| `sensor.osd_depozyt_pstryk_rozliczony` / `_tauron_rozliczony` / `_roznica_rozliczona` | saldo do ostatniej rozliczonej faktury (jak w aplikacji) |
| `sensor.osd_{okres}_diff_{import,export,buy_value,sell_value,net_value}` | Δ dla `current_month`, `previous_month`, `current_year`, `previous_day` |
| `sensor.osd_rozbicie_dzienne`, `date.osd_dzien_analizy`, `sensor.osd_wybrany_dzien` | rozbicie dzienne i godzinowe wybranego dnia |
| `select.osd_fv_miesiac`, `number.osd_fv_*`, `text.osd_fv_numer`, `button.osd_fv_zapisz` / `_usun` | formularz FV (kategoria *Konfiguracja*) |

Statystyki zewnętrzne `pstryk_osd_compare:<licznik>_<metryka>` (godzinowe, z sumą) — do kart `statistics-graph` i panelu Energia: `pstryk_import`, `tauron_import`, `pstryk_export`, `tauron_export`, wartości PLN i Δ.

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

Jak FV wpływa na wyliczenia: różnica `FV − model z API` traktowana jest jako wspólna korekta **obu stron** (Pstryk i Tauron), więc Δ depozytu wynika wyłącznie z różnic pomiarowych. Ta sama operacja jest dostępna jako usługa `pstryk_osd_compare.set_official_month` (także masowo przez `months_json`).

### Model depozytu

Dla każdej dopasowanej godziny, osobno dla kWh Pstryka i kWh Tauronu (te same ceny Pstryka):

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
| `tauron_reader.py` | odczyt statystyk OSD z Recordera, wykrywanie liczników Tauron, backfill |
| `store.py` | lokalny magazyn godzin (Pstryk + OSD) |
| `calc.py` | czyste obliczenia: dopasowanie godzin, wyceny, okresy, księga depozytu (bez importów HA — testowane w `tests/`) |
| `coordinator.py` | synchronizacja, statystyki zewnętrzne, ostrzeżenie `dso_stale` |
| `fv.py` + `select/number/text/button.py` | formularz FV |
| `sensor.py`, `date.py`, `services.py` | encje i usługi |

Wydanie: podbij `version` w `manifest.json`, utwórz tag `vX.Y.Z` — workflow `release.yaml` zbuduje release (tag musi zgadzać się z wersją).

---

## English summary

Home Assistant custom integration (HACS) that compares hourly **Pstryk** meter data (Polish dynamic-tariff supplier) with official **DSO** statistics (Tauron AMIplus or any hourly long-term statistics), values both at Pstryk prices and tracks the impact on the prosumer **deposit**.

- **Requirements:** HA 2025.1+, Pstryk API key, hourly DSO statistics (Tauron AMIplus with *generation*, *balanced* and *store statistics* enabled).
- **Install:** use the My Home Assistant button above, or add this repo as a custom repository (Integration) in HACS (HA ≤ 2026.10) or Settings → Marketplace (HA 2026.11+) → restart → add *Pstryk OSD Compare*.
- **Entities:** fixed IDs `sensor.osd_*`, `date.osd_dzien_analizy`, invoice (FV) form entities `select.osd_fv_miesiac`, `number.osd_fv_*`, `text.osd_fv_numer`, `button.osd_fv_zapisz|usun`; external statistics `pstryk_osd_compare:<meter>_<metric>`.
- **Invoices:** enter monthly invoice values via the dashboard form or `pstryk_osd_compare.set_official_month`; corrections apply equally to both sides, so the deposit delta reflects metering differences only.
- **Dashboard:** [`dashboards/compare_dashboard.yaml`](dashboards/compare_dashboard.yaml) (built-in cards; replace `YOUR_METER_ID`).
- UI texts are Polish and English; entity names are Polish.

## Licencja

[MIT](LICENSE)

# Changelog

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

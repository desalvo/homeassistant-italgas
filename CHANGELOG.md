# Changelog

## 0.3.7

- Replaced the Energy Dashboard external gas statistic with the real **Consumo gas** sensor (`device_class: gas`, `state_class: total_increasing`).
- This restores Home Assistant's native gas-cost choices: **current price entity** or **fixed price**.
- The one-month MyItalgas historical seed is now imported into the entity's Recorder statistics with `async_import_statistics`, so historical consumption remains available without using an external statistic.
- Existing entries are migrated automatically and the historical seed is re-run once after upgrade.
- The obsolete `italgas:<PDR>_gas_consumption` external statistic is removed after a successful migration to avoid duplicate Energy sources.
- No cost is calculated by the integration itself: Home Assistant handles costs from the selected price entity or fixed €/m³ value.

## 0.3.6

- Simplified Energy Dashboard integration: only the external statistic `<Nome utenza> - Consumo gas` is advertised as the gas source.
- Renamed the live cumulative entity from **Consumo gas** to **Lettura contatore** and removed Energy-compatible metadata from that entity, avoiding duplicate Energy source choices.
- On the first load of a config entry, MyItalgas is queried for real readings from one calendar month before the current date through today.
- The one-month historical seed is persisted with `history_seeded` and is not repeated on every Home Assistant restart.
- Regular live refreshes continue importing newly published readings into the same external statistic.

All notable changes to this project are documented in this file.

## 0.3.5

- Fixed first-configuration startup so live sensor values are fetched before historical backfill.
- Historical 400-day synchronization now runs separately and cannot block entity creation.
- Historical synchronization uses an isolated MyItalgas HTTP session.
- Added clean cancellation/HTTP-session shutdown on integration unload.

## 0.3.4

- Importa le letture storiche MyItalgas come statistiche esterne di Home Assistant.
- Backfill fino a 400 giorni a ogni avvio dell'integrazione, senza scrivere direttamente nel database Recorder.
- Le statistiche usano solo differenze tra letture reali: nessuna interpolazione dei giorni mancanti.
- Aggiunto lo statistic ID stabile `italgas:<PDR>_gas_consumption` per la Dashboard Energia.
- Gli aggiornamenti successivi importano automaticamente le nuove letture pubblicate da MyItalgas.

## 0.3.3

- Added **Consumo gas giornaliero**, calculated only from two real MyItalgas meter readings exactly one calendar day apart.
- The client now always checks at least the current and previous month, allowing daily readings to be detected across month boundaries.
- Daily consumption is never interpolated from monthly readings, preventing fabricated Energy Dashboard statistics.
- The cumulative **Consumo gas** sensor remains the source to select in Home Assistant Energy → Gas.

## [0.3.2] - 2026-09-06

- Fixed gas entities that could remain without a state when MyItalgas returned no rows for a large 400-day query.
- Readings are now fetched using calendar-month ranges, matching the MyItalgas web portal behaviour.
- The Energy Dashboard source is now clearly named **Consumo gas** and remains `gas` / `m³` / `total_increasing`.
- The integration now fails the update explicitly when no readings can be found instead of silently exposing a state-less Energy entity.
- Added `strings.json` for Home Assistant custom-integration metadata completeness.

## [0.3.1] - 2026-09-06

### Fixed
- Isolated MyItalgas cookies per client using a dedicated `aiohttp.CookieJar`.
- Fixed the first setup after adding an account sometimes failing with `Struts token not found`, while working after a Home Assistant restart.
- Closed temporary config-flow HTTP sessions immediately after PDR discovery.
- Closed the runtime HTTP session when the config entry is unloaded or initial setup fails.
- Prevented authenticated cookies from one Italgas account from leaking into another account or the runtime client.

## [0.3.0] - 2026-09-06

### Added
- HACS repository metadata.
- HACS and Hassfest GitHub Actions.
- Home Assistant local brand directory.
- EUPL licensing and author notices.
- GitHub-ready README and repository metadata recommendations.

### Changed
- Public integration name to `Italgas`.
- Integration domain from `gas_portal` to `italgas`.
- Device identifiers and entity unique IDs now use the `italgas` namespace.

### Existing functionality
- MyItalgas automatic login and session handling.
- PDR discovery and friendly supply name.
- Energy Dashboard-compatible cumulative gas meter sensor.

## 0.3.8

- Fix entity-backed historical statistics import: Home Assistant `async_import_statistics` now uses the required Recorder source.
- Existing entries are migrated and the one-month history seed is retried automatically.
- Add `Prezzo gas medio nazionale (ARERA)` in `EUR/m³`, sourced from the latest official ARERA CMEM,m monthly value (PSV day-ahead average).
- ARERA price failures do not block MyItalgas consumption updates; the last valid price is retained during transient failures.

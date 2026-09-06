# Italgas for Home Assistant

Custom integration for **Home Assistant** that reads gas meter readings and consumption data from the **MyItalgas** customer portal and exposes them as Home Assistant sensors.

> **Unofficial project.** This integration is not affiliated with, endorsed by, or sponsored by Italgas S.p.A. It uses the user's own MyItalgas account and the web interfaces made available to that account.

## Features

- Home Assistant UI configuration through `config_flow`.
- Automatic login to MyItalgas.
- Automatic management of HTTP session cookies and Struts tokens.
- Discovery of the PDRs associated with the account.
- Friendly **supply name** associated with each configured PDR.
- Retrieval of remote meter readings.
- Automatic re-authentication when the session expires.
- Gas meter sensor suitable for Home Assistant long-term statistics and the **Energy Dashboard**.
- Italian and English translations.
- Native local branding for Home Assistant 2026.3+.
- HACS-compatible repository structure.

## Home Assistant Energy Dashboard

The main entity, **Lettura contatore**, represents the cumulative gas meter reading and exposes:

```text
device_class: gas
state_class: total_increasing
unit_of_measurement: m³
```

This makes the sensor eligible as a gas source in **Settings → Dashboards → Energy → Gas consumption**.

The **Consumo ultimo intervallo** sensor is the difference between the two most recent cumulative readings. It is intentionally not marked as `total_increasing`, because doing so would generate incorrect long-term energy statistics.

## Requirements

- Home Assistant **2026.3.0 or later**.
- A working MyItalgas account.
- At least one PDR visible in that account.
- Internet access from Home Assistant to `clienti.italgas.it`.

An energy supply contract does not need to be sold directly by Italgas. For example, a contract with Estra can be read when its PDR is distributed by Italgas and is associated with the user's MyItalgas account.

## Installation with HACS

Until the repository is included in the default HACS catalog, add it as a custom repository:

1. Open **HACS** in Home Assistant.
2. Open the menu and choose **Custom repositories**.
3. Add `https://github.com/braket71/homeassistant-italgas`.
4. Select category **Integration**.
5. Search for **Italgas** and install it.
6. Restart Home Assistant.
7. Go to **Settings → Devices & services → Add integration**.
8. Search for **Italgas**.

## Manual installation

Copy:

```text
custom_components/italgas
```

to:

```text
/config/custom_components/italgas
```

Restart Home Assistant and add **Italgas** from **Settings → Devices & services**.

## Configuration

The configuration flow first asks for the MyItalgas credentials. The integration then discovers the available PDRs and asks you to select one and assign a friendly name, for example:

```text
PDR:          01234567890123
Nome utenza:  Casa
```

The friendly name is used as the Home Assistant device name. Multiple PDRs can be configured as separate integration entries.

## Entities

### Consumo gas

Cumulative gas meter reading in cubic metres. This is the entity intended for the Energy Dashboard.

When available, entity attributes include:

- PDR;
- reading timestamp;
- reading source/type, e.g. `Telelettura`;
- meter serial number;
- previous reading timestamp and value.

### Consumo ultimo intervallo

Difference in cubic metres between the two most recent cumulative readings returned by MyItalgas.

## How it works

The integration reproduces the authenticated web flow used by the MyItalgas portal. The currently implemented sequence includes actions such as:

```text
GET  /clienti/login.action
POST /clienti/login.action
GET  /clienti/home.action
GET  /clienti/elencoForniture.action
GET  /clienti/elencoLettForn.action
GET  /clienti/elencoLetture.action?id=<opaque-id>
POST /clienti/ricercaLetture.action
```

It extracts the Struts anti-CSRF token from the relevant pages, maintains the authenticated HTTP session and parses the readings returned by the portal.

Because this is based on an undocumented web interface, changes made by Italgas to the portal can temporarily break the integration.

## Security and privacy

Credentials are stored in the Home Assistant config entry. Do not publish Home Assistant `.storage` files, backups, debug logs, HAR captures, cookies, PDRs or meter serial numbers.

No credentials, cookies, tokens, PDRs or HAR data used during development are included in this repository.

## Troubleshooting

Enable debug logging if necessary:

```yaml
logger:
  default: info
  logs:
    custom_components.italgas: debug
```

After reproducing the issue, remove or redact personal information before attaching logs to a GitHub issue.

## HACS / repository metadata

Repository name recommendation: `homeassistant-italgas`

Suggested GitHub description:

> Unofficial Home Assistant integration for Italgas/MyItalgas gas meter readings and Energy Dashboard consumption statistics.

Suggested GitHub topics:

`home-assistant`, `homeassistant`, `hacs`, `italgas`, `myitalgas`, `gas`, `energy-dashboard`, `italy`

## Versioning

The project follows semantic versioning.

### 0.3.0

- Integration renamed to **Italgas**.
- Domain changed from `gas_portal` to `italgas`.
- Added HACS repository metadata and validation workflows.
- Added local Home Assistant brand assets.
- Added project author and copyright metadata.
- Licensed under **EUPL-1.2-or-later**.
- Retains Energy Dashboard-compatible cumulative gas sensor.
- Retains configurable friendly name per PDR.

> Upgrading from the experimental `gas_portal` builds is a breaking change because the integration domain changed. Remove the previous test integration and configure **Italgas** again.

## Author

**Alessandro De Salvo**  
Email: `braket71@gmail.com`

## License

Copyright © 2026 Alessandro De Salvo.

Licensed under the **European Union Public Licence, EUPL-1.2-or-later**. See [`LICENSE`](LICENSE).

## Trademark notice

Italgas and the Italgas logo are trademarks of their respective owner. Their use in this project is solely to identify the service with which this independent integration interoperates.

### Misure giornaliere

L'integrazione espone anche **Consumo gas giornaliero** quando MyItalgas restituisce due letture reali del contatore a distanza di un giorno. Il valore e' la differenza tra le due letture cumulative.

Non vengono create stime giornaliere a partire da letture mensili: se il portale del PDR espone solo letture mensili, il sensore giornaliero resta non disponibile. Per la Dashboard Energia va selezionata la sola statistica esterna **<Nome utenza> - Consumo gas**.

## Statistiche storiche e consumi giornalieri

L'integrazione importa nel Recorder di Home Assistant le letture reali disponibili su MyItalgas come statistica esterna. Dalla versione 0.3.6, al primo caricamento della configurazione il seed storico copre un mese di calendario prima della data corrente fino a oggi:

```text
italgas:<PDR>_gas_consumption
```

La statistica appare con il nome **<Nome utenza> - Consumo gas** ed è quella consigliata in **Impostazioni → Dashboard → Energia → Gas → Consumo di gas** quando si desidera anche lo storico precedente all'installazione dell'integrazione.

Se MyItalgas espone letture quotidiane, Home Assistant può quindi visualizzare consumi giornalieri reali anche per i giorni già trascorsi. Se il portale espone soltanto letture mensili o sparse, l'integrazione non interpola né inventa valori giornalieri: il consumo resta attribuito agli intervalli realmente misurati.

Il normale sensore **Lettura contatore** continua a mostrare la lettura cumulativa corrente del contatore; la statistica esterna è invece pensata per il backfill e la Dashboard Energia.


### Sorgente Gas per la Dashboard Energia

Per evitare sorgenti duplicate, dalla versione 0.3.6 **una sola voce** è destinata a Home Assistant Energy → Gas:

- **`<Nome utenza> - Consumo gas`** — statistica esterna `italgas:<PDR>_gas_consumption`.

Il sensore **Lettura contatore** mostra la lettura cumulativa live del contatore in m³, ma non è più marcato come sorgente Energy. I sensori **Consumo ultimo intervallo** e **Consumo gas giornaliero** restano informativi.

Alla prima configurazione l'integrazione interroga MyItalgas per le letture reali comprese tra **un mese di calendario prima della data corrente e oggi** e le importa nella statistica esterna. Non vengono interpolate letture mancanti. Dopo il primo seed, gli aggiornamenti ordinari importano solo i nuovi dati pubblicati dal portale.

## Dashboard Energia e costi gas

La sorgente da selezionare in **Impostazioni → Dashboard → Energia → Gas → Consumo di gas** è l'entità **Consumo gas** dell'utenza Italgas. È un sensore cumulativo in m³ con `device_class: gas` e `state_class: total_increasing`.

Dalla versione **0.3.7** la sorgente Energia è una normale entità Home Assistant, non una statistica esterna. Questo permette di usare direttamente le opzioni native della Dashboard Energia per il costo:

- **Usa un'entità con il prezzo corrente**: seleziona un sensore o `input_number` che rappresenti il prezzo del gas, ad esempio un'entità con il costo nazionale medio espresso in **€/m³**.
- **Usa un prezzo fisso**: inserisci direttamente il prezzo contrattuale in **€/m³**.
- In alternativa puoi non configurare alcun costo.

Il prezzo non viene memorizzato nelle credenziali Italgas e l'integrazione non impone una fonte economica specifica: il calcolo viene eseguito dal componente Energia di Home Assistant.

Al primo caricamento l'integrazione richiede a MyItalgas le letture reali da **un mese di calendario prima della data corrente fino a oggi** e le importa nelle statistiche Recorder della stessa entità `Consumo gas`. Non vengono interpolate letture mancanti.

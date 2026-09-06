from __future__ import annotations

from datetime import timedelta

DOMAIN = "italgas"
PLATFORMS = ["sensor"]

CONF_USERNAME = "username"
CONF_PASSWORD = "password"
CONF_PDR = "pdr"
CONF_NAME = "name"
CONF_VERIFY_SSL = "verify_ssl"
CONF_HISTORY_SEEDED = "history_seeded"

BASE_URL = "https://clienti.italgas.it/clienti"
DEFAULT_UPDATE_INTERVAL = timedelta(hours=6)
DEFAULT_LOOKBACK_DAYS = 400
PROVIDER_NAME = "Italgas"

from __future__ import annotations

from aiohttp import CookieJar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import MyItalgasClient
from .const import CONF_PASSWORD, CONF_PDR, CONF_USERNAME, CONF_VERIFY_SSL, PLATFORMS
from .coordinator import GasPortalCoordinator


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate existing entries to the entity-backed Energy statistic model."""
    if entry.version < 5:
        data = dict(entry.data)
        # Versions <= 0.3.7 either seeded an external statistic or attempted
        # an entity statistic with the wrong Recorder source. Re-run the
        # one-month seed so the real gas entity gets valid long-term statistics.
        data["history_seeded"] = False
        hass.config_entries.async_update_entry(entry, data=data, version=5)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Keep MyItalgas cookies isolated from Home Assistant's shared HTTP
    # session. This prevents config-flow/runtime contamination and keeps
    # multiple Italgas accounts independent.
    session = async_create_clientsession(hass, cookie_jar=CookieJar())
    client = MyItalgasClient(
        session,
        username=entry.data[CONF_USERNAME],
        password=entry.data[CONF_PASSWORD],
        pdr=entry.data[CONF_PDR],
        verify_ssl=entry.data.get(CONF_VERIFY_SSL, True),
    )
    coordinator = GasPortalCoordinator(hass, entry, client)
    try:
        # First refresh fetches RECENT data only, so entities get their state
        # before any optional historical backfill is attempted.
        await coordinator.async_config_entry_first_refresh()
    except Exception:
        await coordinator.async_shutdown()
        raise

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Historical Recorder backfill is intentionally decoupled from first setup.
    coordinator.start_history_sync()
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        await entry.runtime_data.async_shutdown()
    return unload_ok

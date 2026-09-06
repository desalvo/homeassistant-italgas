from __future__ import annotations

import asyncio
import logging
from dataclasses import replace

from aiohttp import CookieJar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_create_clientsession, async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import GasPortalAuthError, GasPortalError, MyItalgasClient
from .arera import async_fetch_arera_gas_price
from .const import (
    CONF_HISTORY_SEEDED,
    CONF_PASSWORD,
    CONF_PDR,
    CONF_USERNAME,
    CONF_VERIFY_SSL,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)
from .models import GasPortalData
from .statistics import (
    async_import_consumption_statistics,
    async_remove_legacy_external_statistics,
)

_LOGGER = logging.getLogger(__name__)


class GasPortalCoordinator(DataUpdateCoordinator[GasPortalData]):
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: MyItalgasClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=DEFAULT_UPDATE_INTERVAL,
            always_update=False,
        )
        self.client = client
        self._history_sync_task: asyncio.Task[None] | None = None

    async def _async_update_data(self) -> GasPortalData:
        """Fetch recent readings for entity state.

        Keep the live refresh deliberately lightweight.  Historical backfill is
        performed by a separate client after the entities already have a valid
        state, so a slow or failed historical seed can never block first setup.
        """
        try:
            data = await self.client.async_fetch()
        except GasPortalAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except GasPortalError as err:
            raise UpdateFailed(str(err)) from err

        # ARERA price is auxiliary: failure must never make gas readings
        # unavailable. Keep the previous valid price when ARERA is temporarily
        # unreachable.
        price_value = None
        price_period = None
        try:
            price = await async_fetch_arera_gas_price(async_get_clientsession(self.hass))
            price_value = price.value_eur_smc
            price_period = price.period
        except ValueError as err:
            _LOGGER.warning("Unable to refresh ARERA gas reference price: %s", err)
            if self.data is not None:
                price_value = self.data.national_price_eur_m3
                price_period = self.data.national_price_period

        return replace(
            data,
            national_price_eur_m3=price_value,
            national_price_period=price_period,
        )

    def start_history_sync(self) -> None:
        """Schedule the one-month historical seed once for this config entry."""
        if self.config_entry.data.get(CONF_HISTORY_SEEDED, False):
            return
        if self._history_sync_task is not None and not self._history_sync_task.done():
            return
        self._history_sync_task = self.hass.async_create_task(
            self._async_sync_history(),
            "Italgas historical statistics sync",
        )

    async def _async_sync_history(self) -> None:
        """Backfill history without sharing the live client's cookies/session."""
        # Give entity setup and Recorder startup a chance to settle first.  This
        # also avoids two immediate MyItalgas logins against the same account.
        await asyncio.sleep(15)

        session = async_create_clientsession(self.hass, cookie_jar=CookieJar())
        history_client = MyItalgasClient(
            session,
            username=self.config_entry.data[CONF_USERNAME],
            password=self.config_entry.data[CONF_PASSWORD],
            pdr=self.config_entry.data[CONF_PDR],
            verify_ssl=self.config_entry.data.get(CONF_VERIFY_SSL, True),
        )
        try:
            data = await history_client.async_fetch_initial_history()
            count = async_import_consumption_statistics(
                self.hass, self.config_entry, data
            )
            if count:
                async_remove_legacy_external_statistics(self.hass, data.pdr)
                updated_data = dict(self.config_entry.data)
                updated_data[CONF_HISTORY_SEEDED] = True
                self.hass.config_entries.async_update_entry(
                    self.config_entry, data=updated_data
                )
                _LOGGER.debug(
                    "Italgas one-month historical seed completed for PDR %s: %d statistics",
                    data.pdr,
                    count,
                )
            else:
                _LOGGER.warning(
                    "Italgas historical seed produced no importable rows for PDR %s; "
                    "it will be retried on the next integration load",
                    data.pdr,
                )
        except asyncio.CancelledError:
            raise
        except GasPortalAuthError as err:
            _LOGGER.warning("Italgas historical sync authentication failed: %s", err)
        except GasPortalError as err:
            # Historical import is optional. Live entities remain usable if
            # MyItalgas temporarily rejects the one-month seed query.
            _LOGGER.warning("Italgas historical sync failed: %s", err)
        finally:
            await history_client.async_close()

    async def async_shutdown(self) -> None:
        """Cancel optional backfill and close the live HTTP client."""
        if self._history_sync_task is not None and not self._history_sync_task.done():
            self._history_sync_task.cancel()
            try:
                await self._history_sync_task
            except asyncio.CancelledError:
                pass
        await self.client.async_close()

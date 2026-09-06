from __future__ import annotations

import voluptuous as vol
from aiohttp import CookieJar

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import GasPortalAuthError, GasPortalError, GasPortalProtocolError, MyItalgasClient
from .const import CONF_NAME, CONF_PASSWORD, CONF_PDR, CONF_USERNAME, CONF_VERIFY_SSL, DOMAIN


STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
        vol.Optional(CONF_VERIFY_SSL, default=True): bool,
    }
)


async def _discover(hass: HomeAssistant, data: dict) -> list[str]:
    # MyItalgas authentication is cookie based. Use a dedicated cookie jar for
    # every discovery attempt so the config flow cannot leak an authenticated
    # session into the runtime client (or into another Italgas account).
    session = async_create_clientsession(hass, cookie_jar=CookieJar())
    client = MyItalgasClient(
        session,
        username=data[CONF_USERNAME],
        password=data[CONF_PASSWORD],
        verify_ssl=data.get(CONF_VERIFY_SSL, True),
    )
    try:
        await client.async_login()
        supplies = await client.async_list_supplies()
        return [item.pdr for item in supplies]
    finally:
        await client.async_close()


class ItalgasConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 4

    def __init__(self) -> None:
        self._credentials: dict | None = None
        self._pdrs: list[str] = []

    async def async_step_user(self, user_input=None):
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_USERNAME] = user_input[CONF_USERNAME].strip()
            try:
                pdrs = await _discover(self.hass, user_input)
            except GasPortalAuthError:
                errors["base"] = "invalid_auth"
            except (GasPortalError, GasPortalProtocolError):
                errors["base"] = "cannot_connect"
            else:
                self._credentials = dict(user_input)
                self._pdrs = pdrs
                return await self.async_step_pdr()

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors)

    async def async_step_pdr(self, user_input=None):
        if self._credentials is None or not self._pdrs:
            return self.async_abort(reason="cannot_connect")

        errors: dict[str, str] = {}
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            if not name:
                errors[CONF_NAME] = "name_required"
            else:
                return await self._create_for_pdr(user_input[CONF_PDR], name)

        default_name = "Utenza gas" if len(self._pdrs) == 1 else "Utenza gas Italgas"
        schema = vol.Schema(
            {
                vol.Required(CONF_PDR, default=self._pdrs[0]): vol.In(self._pdrs),
                vol.Required(CONF_NAME, default=default_name): str,
            }
        )
        return self.async_show_form(step_id="pdr", data_schema=schema, errors=errors)

    async def _create_for_pdr(self, pdr: str, name: str):
        assert self._credentials is not None
        await self.async_set_unique_id(f"italgas:{pdr}")
        self._abort_if_unique_id_configured()
        data = {**self._credentials, CONF_PDR: pdr, CONF_NAME: name}
        return self.async_create_entry(title=name, data=data)

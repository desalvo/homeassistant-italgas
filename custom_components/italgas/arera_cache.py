from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .arera import AreraGasPrice
from .const import DOMAIN

_STORAGE_VERSION = 1
_STORAGE_KEY = f"{DOMAIN}.arera_gas_price"


class AreraPriceCache:
    """Persist the last valid ARERA gas price across Home Assistant restarts."""

    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, str]] = Store(
            hass,
            _STORAGE_VERSION,
            _STORAGE_KEY,
        )

    async def async_load(self) -> AreraGasPrice | None:
        data = await self._store.async_load()
        if not data:
            return None
        try:
            value = Decimal(data["value_eur_smc"])
            period = data["period"]
        except (KeyError, InvalidOperation, TypeError, ValueError):
            return None
        if value <= 0 or not period:
            return None
        return AreraGasPrice(value_eur_smc=value, period=period)

    async def async_save(self, price: AreraGasPrice) -> None:
        await self._store.async_save(
            {
                "value_eur_smc": str(price.value_eur_smc),
                "period": price.period,
                "source_url": price.source_url,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
        )

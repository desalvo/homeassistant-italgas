from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Callable

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_NAME, DOMAIN
from .coordinator import GasPortalCoordinator
from .models import GasPortalData
from .statistics import gas_sensor_unique_id


@dataclass(frozen=True, kw_only=True)
class GasSensorDescription(SensorEntityDescription):
    value_fn: Callable[[GasPortalData], Decimal | None]


SENSORS = (
    # The single source intended for Home Assistant Energy -> Gas.  Keeping the
    # historic unique id avoids creating a duplicate entity on upgrade.
    GasSensorDescription(
        key="meter_reading",
        name="Consumo gas",
        device_class=SensorDeviceClass.GAS,
        state_class=SensorStateClass.TOTAL_INCREASING,
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=lambda data: data.latest_reading.value_m3 if data.latest_reading else None,
    ),
    GasSensorDescription(
        key="latest_interval_consumption",
        name="Consumo ultimo intervallo",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=lambda data: data.latest_interval_consumption_m3,
    ),
    GasSensorDescription(
        key="daily_consumption",
        name="Consumo gas giornaliero",
        native_unit_of_measurement=UnitOfVolume.CUBIC_METERS,
        value_fn=lambda data: data.latest_daily_consumption_m3,
    ),
    GasSensorDescription(
        key="national_gas_price",
        name="Prezzo gas medio nazionale (ARERA)",
        native_unit_of_measurement="EUR/m³",
        value_fn=lambda data: data.national_price_eur_m3,
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: GasPortalCoordinator = entry.runtime_data
    async_add_entities(GasPortalSensor(coordinator, entry, description) for description in SENSORS)


class GasPortalSensor(CoordinatorEntity[GasPortalCoordinator], SensorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator: GasPortalCoordinator, entry: ConfigEntry, description: GasSensorDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        pdr = coordinator.data.pdr
        account_name = entry.data.get(CONF_NAME) or entry.title or f"Italgas {pdr}"
        self._attr_unique_id = (
            gas_sensor_unique_id(pdr)
            if description.key == "meter_reading"
            else f"italgas_{pdr}_{description.key}"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, f"italgas:{pdr}")},
            "name": account_name,
            "manufacturer": "Italgas",
            "model": "Contatore gas via MyItalgas",
        }

    @property
    def native_value(self):
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self):
        latest = self.coordinator.data.latest_reading
        attrs = {
            "pdr": self.coordinator.data.pdr,
            "energy_dashboard_source": self.entity_description.key == "meter_reading",
        }
        if self.entity_description.key == "national_gas_price":
            attrs.update(
                {
                    "price_period": self.coordinator.data.national_price_period,
                    "price_basis": "ARERA CMEM,m - media mensile PSV day-ahead",
                    "source": "https://www.arera.it/area-operatori/prezzi-e-tariffe/valore-cmemm-vulnerabili",
                    "note": "Prezzo della sola materia prima gas; non include trasporto, oneri, imposte o quota fissa.",
                }
            )
            return attrs
        if latest is None:
            return attrs
        attrs.update(
            {
                "reading_timestamp": latest.timestamp.isoformat(),
                "reading_source": latest.source,
                "meter_serial": latest.meter_serial,
            }
        )
        previous = self.coordinator.data.previous_reading
        if previous is not None:
            attrs["previous_reading_timestamp"] = previous.timestamp.isoformat()
            attrs["previous_reading_m3"] = str(previous.value_m3)
        if self.entity_description.key == "daily_consumption":
            pair = self.coordinator.data.latest_daily_pair
            attrs["daily_data_available"] = pair is not None
            if pair is not None:
                daily_previous, daily_latest = pair
                attrs["period_start"] = daily_previous.timestamp.isoformat()
                attrs["period_end"] = daily_latest.timestamp.isoformat()
        return attrs

from __future__ import annotations

import logging
from decimal import Decimal

from homeassistant.components.recorder.const import DOMAIN as RECORDER_DOMAIN
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_import_statistics
from homeassistant.components.recorder.util import get_instance
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.unit_conversion import VolumeConverter

from .const import DOMAIN
from .models import GasPortalData

_LOGGER = logging.getLogger(__name__)

GAS_SENSOR_KEY = "meter_reading"


def gas_sensor_unique_id(pdr: str) -> str:
    """Return the stable unique id of the Energy Dashboard gas sensor."""
    return f"italgas_{pdr}_{GAS_SENSOR_KEY}"


def legacy_consumption_statistic_id(pdr: str) -> str:
    """Return the pre-0.3.7 external statistic id."""
    return f"{DOMAIN}:{pdr}_gas_consumption"


def gas_entity_id(hass: HomeAssistant, pdr: str) -> str | None:
    """Resolve the entity id assigned by Home Assistant to the gas sensor."""
    registry = er.async_get(hass)
    return registry.async_get_entity_id("sensor", DOMAIN, gas_sensor_unique_id(pdr))


def _build_entity_statistics(data: GasPortalData) -> list[StatisticData]:
    """Build total-increasing statistics matching the live gas sensor.

    ``state`` is the physical cumulative meter reading. ``sum`` is the
    accumulated positive consumption since the oldest imported reading, which
    matches Home Assistant's total_increasing semantics and gives the Energy
    Dashboard a clean baseline for the historical seed.
    """
    if not data.readings:
        return []

    readings = sorted(data.readings, key=lambda item: item.timestamp)
    stats: list[StatisticData] = []
    running_sum = Decimal("0")
    previous = None

    for reading in readings:
        if previous is not None:
            delta = reading.value_m3 - previous.value_m3
            if delta < 0:
                # Meter replacement/reset: start a new monotonic segment.
                _LOGGER.warning(
                    "Italgas meter reading decreased at %s (%s -> %s m3); "
                    "keeping the historical sum unchanged across the reset",
                    reading.timestamp,
                    previous.value_m3,
                    reading.value_m3,
                )
            else:
                running_sum += delta

        stats.append(
            StatisticData(
                start=reading.timestamp,
                state=float(reading.value_m3),
                sum=float(running_sum),
            )
        )
        previous = reading

    return stats


def async_import_consumption_statistics(
    hass: HomeAssistant,
    entry: ConfigEntry,
    data: GasPortalData,
) -> int:
    """Backfill MyItalgas readings into the live sensor's statistics."""
    entity_id = gas_entity_id(hass, data.pdr)
    if entity_id is None:
        _LOGGER.debug(
            "Italgas gas sensor is not registered yet; delaying historical import"
        )
        return 0

    stats = _build_entity_statistics(data)
    if not stats:
        return 0

    metadata = StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=None,
        source=RECORDER_DOMAIN,
        statistic_id=entity_id,
        unit_class=VolumeConverter.UNIT_CLASS,
        unit_of_measurement=UnitOfVolume.CUBIC_METERS,
    )
    try:
        async_import_statistics(hass, metadata, stats)
    except HomeAssistantError as err:
        _LOGGER.warning("Unable to import Italgas historical statistics: %s", err)
        return 0

    _LOGGER.debug(
        "Imported %d Italgas historical rows into %s for PDR %s",
        len(stats),
        entity_id,
        data.pdr,
    )
    return len(stats)


def async_remove_legacy_external_statistics(hass: HomeAssistant, pdr: str) -> None:
    """Remove the obsolete external statistic created by versions <= 0.3.6."""
    get_instance(hass).async_clear_statistics([legacy_consumption_statistic_id(pdr)])

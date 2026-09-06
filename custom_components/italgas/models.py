from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class GasReading:
    timestamp: datetime
    value_m3: Decimal
    source: str | None = None
    meter_serial: str | None = None


@dataclass(frozen=True, slots=True)
class GasSupply:
    opaque_id: str
    pdr: str
    meter_serial: str | None = None


@dataclass(frozen=True, slots=True)
class GasPortalData:
    pdr: str
    readings: tuple[GasReading, ...]
    national_price_eur_m3: Decimal | None = None
    national_price_period: str | None = None

    @property
    def latest_reading(self) -> GasReading | None:
        return self.readings[-1] if self.readings else None

    @property
    def previous_reading(self) -> GasReading | None:
        return self.readings[-2] if len(self.readings) >= 2 else None

    @property
    def latest_interval_consumption_m3(self) -> Decimal | None:
        latest = self.latest_reading
        previous = self.previous_reading
        if latest is None or previous is None:
            return None
        delta = latest.value_m3 - previous.value_m3
        return delta if delta >= 0 else None

    @property
    def latest_daily_pair(self) -> tuple[GasReading, GasReading] | None:
        """Return the newest pair of readings exactly one calendar day apart."""
        for previous, latest in zip(reversed(self.readings[:-1]), reversed(self.readings[1:])):
            if (latest.timestamp.date() - previous.timestamp.date()).days != 1:
                continue
            if latest.value_m3 < previous.value_m3:
                continue
            return previous, latest
        return None

    @property
    def latest_daily_consumption_m3(self) -> Decimal | None:
        """Return actual one-day consumption when MyItalgas exposes daily readings."""
        pair = self.latest_daily_pair
        if pair is None:
            return None
        previous, latest = pair
        return latest.value_m3 - previous.value_m3

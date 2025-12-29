"""Coordinators for the Enever integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, time, timedelta
import logging
from typing import Any

from httpx import ConnectError

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
import homeassistant.util.dt as dt_util
from homeassistant.util.dt import as_local, get_default_time_zone

from .const import CONF_RESOLUTION, DOMAIN
from .enever_api import (
    EneverAPI,
    EneverCannotConnect,
    EneverData,
    EneverInvalidToken,
    EneverResponse,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

# If fetching fails, or the data is still old at the start of the refresh cycle,
# try again later. The lower the faster prices will update, but the more API
# tokens will be used up so lower it with caution.
MIN_TIME_BETWEEN_REQUESTS_GAS = timedelta(minutes=15)

# The retry interval is set higher for electricity since it can simply use
# yesterday's "tomorrow" prices in the meantime.
MIN_TIME_BETWEEN_REQUESTS_ELECTRICITY = timedelta(minutes=60)

# The maximum number of attempts on a day. Does not differentiate between connectivity
# issues and stale data or other issues, as we can not be sure if the request counted
# towards the token limit. With 2 attempts for each coordinator that is a maximum of
# 6 requests per day (electricity today, tomorrow and gas today). This keeps us within
# the free tier limit of 250 requests per month.
MAX_ATTEMPTS_COUNT = 2


def _data_from_dict(
    data: list[Mapping[str, Any]] | None,
) -> list[EneverData] | None:
    if data is None:
        return None

    return [
        EneverData(
            datum=dt,
            prijs=value["prijs"],
        )
        for value in data
        if (dt := _str_to_datetime(value["datum"])) is not None
    ]


def _data_to_dict(data: list[EneverData] | None) -> list[Mapping[str, Any]] | None:
    if data is None:
        return None

    return [
        {
            "datum": _datetime_to_str(value.datum),
            "prijs": value.prijs,
        }
        for value in data
    ]


def _datetime_to_str(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _str_to_datetime(value: str | None) -> datetime | None:
    return as_local(datetime.fromisoformat(value)) if value is not None else None


@dataclass
class EneverCoordinatorData:
    """The data as cached by an EneverUpdateCoordinator."""

    today: list[EneverData] | None
    today_lastrequest: datetime | None
    tomorrow: list[EneverData] | None
    tomorrow_lastrequest: datetime | None
    attempt: int

    @staticmethod
    def from_dict(data: Mapping[str, Any] | None) -> EneverCoordinatorData:
        """Initialize from a dictionary for serialization."""
        if data is None:
            return EneverCoordinatorData(
                today=None,
                today_lastrequest=None,
                tomorrow=None,
                tomorrow_lastrequest=None,
                attempt=0,
            )

        return EneverCoordinatorData(
            today=_data_from_dict(data["today"]),
            today_lastrequest=_str_to_datetime(data["today_lastrequest"]),
            tomorrow=_data_from_dict(data["tomorrow"]),
            tomorrow_lastrequest=_str_to_datetime(data["tomorrow_lastrequest"]),
            attempt=data.get("attempt", 0),
        )

    def to_dict(self) -> Mapping[str, Any]:
        """Return the data as a dictionary for serialization."""
        return {
            "today": _data_to_dict(self.today),
            "today_lastrequest": _datetime_to_str(self.today_lastrequest),
            "tomorrow": _data_to_dict(self.tomorrow),
            "tomorrow_lastrequest": _datetime_to_str(self.tomorrow_lastrequest),
            "attempt": self.attempt,
        }


class EneverCoordinatorObserver:
    """Implemented by observers."""

    def count_api_request(self) -> None:
        """Call before an API request is made."""


class EneverUpdateCoordinator(DataUpdateCoordinator[EneverCoordinatorData], ABC):
    """Update coordinator for Enever feeds."""

    _observers: list[EneverCoordinatorObserver]

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, api: EneverAPI
    ) -> None:
        """Initialize the update coordinator."""
        self.api = api

        self.store = Store[Mapping[str, Any]](
            hass, STORAGE_VERSION, f"{DOMAIN}.{self._get_storage_key(config_entry)}"
        )

        self._observers = []

        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=self._get_update_interval(None),
            always_update=True,
        )

    def attach(self, observer: EneverCoordinatorObserver) -> None:
        """Attach an observer."""
        self._observers.append(observer)

    def detach(self, observer: EneverCoordinatorObserver) -> None:
        """Detach a previously attached observer."""
        self._observers.remove(observer)

    async def _async_update_data(self) -> EneverCoordinatorData:
        """Update the data."""
        if self.data is None:
            # First run after setup / HA restart, don't perform API calls yet
            # but keep the refresh interval short to start fetching data soon.
            return EneverCoordinatorData.from_dict(await self.store.async_load())

        now = dt_util.now()
        new_data = EneverCoordinatorData(
            today=self.data.today,
            today_lastrequest=self.data.today_lastrequest,
            tomorrow=self.data.tomorrow,
            tomorrow_lastrequest=self.data.tomorrow_lastrequest,
            attempt=self.data.attempt,
        )

        counted_attempt = False

        def count_request():
            nonlocal counted_attempt

            if not counted_attempt:
                new_data.attempt = new_data.attempt + 1
                counted_attempt = True

            self._count_api_request()

        try:
            if self._allow_request_today(now, new_data) and self._should_update_today(
                now, new_data
            ):
                count_request()

                response = await self._fetch_today()
                if response is not None:
                    new_data.today = response.data
                    new_data.today_lastrequest = now

            if self._allow_request_tomorrow(
                now, new_data
            ) and self._should_update_tomorrow(now, new_data):
                count_request()

                response = await self._fetch_tomorrow()
                if response is not None:
                    new_data.tomorrow = response.data
                    new_data.tomorrow_lastrequest = now

            self.update_interval = self._get_update_interval(new_data)
        except EneverInvalidToken:
            _LOGGER.error("API token was denied")
        except (TimeoutError, ConnectError, EneverCannotConnect):
            _LOGGER.error("Connection timed out")
        except Exception:
            _LOGGER.exception("Error while fetching data")
        finally:
            await self.store.async_save(new_data.to_dict())

        return new_data

    @abstractmethod
    async def _fetch_today(self) -> EneverResponse:
        """Fetch the actual data for today."""
        raise NotImplementedError

    @abstractmethod
    async def _fetch_tomorrow(self) -> EneverResponse:
        """Fetch the actual data for tomorrow."""
        raise NotImplementedError

    @abstractmethod
    def _get_storage_key(self, config_entry: ConfigEntry) -> str:
        """Return the storage key postfix."""
        raise NotImplementedError

    @abstractmethod
    def _get_request_interval(self) -> timedelta:
        raise NotImplementedError

    def _allow_request_today(self, now: datetime, data: EneverCoordinatorData) -> bool:
        if data.attempt >= MAX_ATTEMPTS_COUNT:
            return False

        # Throttle
        return (
            data.today_lastrequest is None
            or (now - data.today_lastrequest) >= self._get_request_interval()
        )

    def _allow_request_tomorrow(
        self, now: datetime, data: EneverCoordinatorData
    ) -> bool:
        if data.attempt >= MAX_ATTEMPTS_COUNT:
            return False

        # Throttle
        return (
            data.tomorrow_lastrequest is None
            or (now - data.tomorrow_lastrequest) >= self._get_request_interval()
        )

    @abstractmethod
    def _should_update_today(self, now: datetime, data: EneverCoordinatorData) -> bool:
        """Determine if the data for today needs updating."""
        raise NotImplementedError

    @abstractmethod
    def _should_update_tomorrow(
        self, now: datetime, data: EneverCoordinatorData
    ) -> bool:
        """Determine if the data for tomorrow needs updating."""
        raise NotImplementedError

    def _count_api_request(self):
        for observer in self._observers:
            observer.count_api_request()

    def _get_update_interval(self, data: EneverCoordinatorData | None) -> timedelta:
        """Get new update interval."""
        if data is None:
            return timedelta(seconds=5)

        # TODO determine update time based on next expected change, last data and last request?
        # The _should_update methods limit the actual request rate and it's not like we're hammering
        # HA to call us every few milliseconds, but it's still nice to reduce cycles as much as possible.
        return timedelta(minutes=1)


class GasPricesCoordinator(EneverUpdateCoordinator):
    """Gas prices update coordinator."""

    async def _fetch_today(self) -> EneverResponse:
        return await self.api.gasprijs_vandaag()

    async def _fetch_tomorrow(self) -> EneverResponse | None:
        return None

    def _get_storage_key(self, config_entry: ConfigEntry) -> str:
        return "gas"

    def _get_request_interval(self) -> timedelta:
        return MIN_TIME_BETWEEN_REQUESTS_GAS

    def _should_update_today(self, now: datetime, data: EneverCoordinatorData) -> bool:
        if data.today is None or len(data.today) == 0:
            return True

        # Try to update as soon as the prices expire, new ones should be available right away or within the hour
        data_validto = data.today[0].datum + timedelta(days=1)
        return now >= data_validto

    def _should_update_tomorrow(
        self, now: datetime, data: EneverCoordinatorData
    ) -> bool:
        return False


class ElectricityPricesCoordinator(EneverUpdateCoordinator):
    """Electricity prices update coordinator."""

    async def _fetch_today(self) -> EneverResponse:
        return await self.api.stroomprijs_vandaag()

    async def _fetch_tomorrow(self) -> EneverResponse:
        return await self.api.stroomprijs_morgen()

    def _get_storage_key(self, config_entry: ConfigEntry) -> str:
        return f"electricity.{config_entry.data[CONF_RESOLUTION]}"

    def _get_request_interval(self) -> timedelta:
        return MIN_TIME_BETWEEN_REQUESTS_ELECTRICITY

    def _should_update_today(self, now: datetime, data: EneverCoordinatorData) -> bool:
        if data.today is None or len(data.today) == 0:
            return True

        # Try to update immediately at midnight, new prices should be available right away
        return now.date() != data.today[0].datum.date()

    def _should_update_tomorrow(
        self, now: datetime, data: EneverCoordinatorData
    ) -> bool:
        if data.tomorrow is None or len(data.tomorrow) == 0:
            return now.hour >= 15

        # Prices for tomorrow will usually be available from 15:00, at most 16:00
        data_validto = datetime.combine(
            data.tomorrow[0].datum.date(),
            time(hour=15),
            get_default_time_zone(),
        )
        return now >= data_validto

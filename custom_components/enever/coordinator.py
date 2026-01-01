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
    today_attempt: int
    tomorrow: list[EneverData] | None
    tomorrow_lastrequest: datetime | None
    tomorrow_attempt: int

    @staticmethod
    def from_dict(data: Mapping[str, Any] | None) -> EneverCoordinatorData:
        """Initialize from a dictionary for serialization."""
        if data is None:
            return EneverCoordinatorData(
                today=None,
                today_lastrequest=None,
                today_attempt=0,
                tomorrow=None,
                tomorrow_lastrequest=None,
                tomorrow_attempt=0,
            )

        return EneverCoordinatorData(
            today=_data_from_dict(data["today"]),
            today_lastrequest=_str_to_datetime(data["today_lastrequest"]),
            today_attempt=data.get("today_attempt", 0),
            tomorrow=_data_from_dict(data["tomorrow"]),
            tomorrow_lastrequest=_str_to_datetime(data["tomorrow_lastrequest"]),
            tomorrow_attempt=data.get("tomorrow_attempt", 0),
        )

    def to_dict(self) -> Mapping[str, Any]:
        """Return the data as a dictionary for serialization."""
        return {
            "today": _data_to_dict(self.today),
            "today_lastrequest": _datetime_to_str(self.today_lastrequest),
            "today_attempt": self.today_attempt,
            "tomorrow": _data_to_dict(self.tomorrow),
            "tomorrow_lastrequest": _datetime_to_str(self.tomorrow_lastrequest),
            "tomorrow_attempt": self.tomorrow_attempt,
        }


class EneverCoordinatorObserver:
    """Implemented by observers."""

    def count_api_request(self) -> None:
        """Call before an API request is made."""


class EneverUpdateCoordinator(DataUpdateCoordinator[EneverCoordinatorData], ABC):
    """Update coordinator for Enever feeds."""

    _observers: list[EneverCoordinatorObserver]
    logger: logging.Logger

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api: EneverAPI,
        logger: logging.Logger,
    ) -> None:
        """Initialize the update coordinator."""
        self.api = api

        self.store = Store[Mapping[str, Any]](
            hass, STORAGE_VERSION, f"{DOMAIN}.{self._get_storage_key(config_entry)}"
        )

        self._observers = []
        self.logger = logger

        super().__init__(
            hass,
            logger,
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
            self.logger.debug("Loading previously fetched data from storage")
            # First run after setup / HA restart, don't perform API calls yet
            # but keep the refresh interval short to start fetching data soon.
            return EneverCoordinatorData.from_dict(await self.store.async_load())

        self.logger.debug("Checking for updates")
        now = dt_util.now()
        store = False

        def was_today(value: datetime | None) -> bool:
            return value is None or value.date() == now.date()

        new_data = EneverCoordinatorData(
            today=self.data.today,
            today_lastrequest=self.data.today_lastrequest,
            today_attempt=self.data.today_attempt,
            tomorrow=self.data.tomorrow,
            tomorrow_lastrequest=self.data.tomorrow_lastrequest,
            tomorrow_attempt=self.data.tomorrow_attempt,
        )

        if not was_today(self.data.today_lastrequest):
            self.logger.debug("Resetting today's attempts counter")
            new_data.today_attempt = 0
            store = True

        if not was_today(self.data.tomorrow_lastrequest):
            self.logger.debug("Resetting tomorrow's attempts counter")
            new_data.tomorrow_attempt = 0
            store = True

        try:
            if self._allow_request_today(now, new_data) and self._should_update_today(
                now, new_data
            ):
                new_data.today_attempt = new_data.today_attempt + 1
                self._count_api_request()
                store = True

                self.logger.info(
                    "Fetching today's data (attempt %d)", new_data.today_attempt
                )

                response = await self._fetch_today()
                if response is not None:
                    new_data.today = response.data
                    new_data.today_lastrequest = now

            if self._allow_request_tomorrow(
                now, new_data
            ) and self._should_update_tomorrow(now, new_data):
                new_data.tomorrow_attempt = new_data.tomorrow_attempt + 1
                self._count_api_request()
                store = True

                self.logger.info(
                    "Fetching tomorrow's data (attempt %d)", new_data.tomorrow_attempt
                )

                response = await self._fetch_tomorrow()
                if response is not None:
                    new_data.tomorrow = response.data
                    new_data.tomorrow_lastrequest = now

            self.update_interval = self._get_update_interval(new_data)
        except EneverInvalidToken:
            self.logger.error("API token was denied")
        except (TimeoutError, ConnectError, EneverCannotConnect):
            self.logger.error("Connection timed out")
        except Exception:
            self.logger.exception("Error while fetching data")
        finally:
            if store:
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
        return self._allow_request(
            now, data.today_lastrequest, data.today_attempt, "today"
        )

    def _allow_request_tomorrow(
        self, now: datetime, data: EneverCoordinatorData
    ) -> bool:
        return self._allow_request(
            now, data.tomorrow_lastrequest, data.tomorrow_attempt, "tomorrow"
        )

    def _allow_request(
        self, now: datetime, lastrequest: datetime | None, attempt: int, feed: str
    ) -> bool:
        if lastrequest is None:
            return True

        # Throttle
        if (now - lastrequest) < self._get_request_interval():
            self.logger.debug(
                "Last request for %s was within minimum interval, skipping", feed
            )
            return False

        # Limit requests per day (note: attempt is reset each day before this call)
        if attempt >= MAX_ATTEMPTS_COUNT:
            self.logger.debug(
                "Maximum number of daily attempts for %s reached, skipping", feed
            )
            return False

        return True

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

        return timedelta(minutes=1)


class GasPricesCoordinator(EneverUpdateCoordinator):
    """Gas prices update coordinator."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, api: EneverAPI
    ) -> None:
        """Initialize the update coordinator."""
        # pylint: disable=hass-logger-capital # incorrect lint warning, it's not a log message but a suffix
        super().__init__(hass, config_entry, api, _LOGGER.getChild("gas"))

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
        if now >= data_validto:
            return True

        self.logger.debug(
            "Waiting until %s before fetching today's data, skipping",
            data_validto.strftime("%Y-%m-%d %H:%M:%S"),
        )
        return False

    def _should_update_tomorrow(
        self, now: datetime, data: EneverCoordinatorData
    ) -> bool:
        return False


class ElectricityPricesCoordinator(EneverUpdateCoordinator):
    """Electricity prices update coordinator."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, api: EneverAPI
    ) -> None:
        """Initialize the update coordinator."""
        # pylint: disable=hass-logger-capital # incorrect lint warning, it's not a log message but a suffix
        super().__init__(hass, config_entry, api, _LOGGER.getChild("electricity"))

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
        if now.date() != data.today[0].datum.date():
            return True

        self.logger.debug(
            "Waiting until midnight before fetching today's data, skipping"
        )
        return False

    def _should_update_tomorrow(
        self, now: datetime, data: EneverCoordinatorData
    ) -> bool:
        if data.tomorrow is None or len(data.tomorrow) == 0:
            if now.hour >= 15:
                return True

            self.logger.debug(
                "Waiting until 15:00 before fetching tomorrow's data, skipping"
            )
            return False

        # Prices for tomorrow will usually be available from 15:00, at most 16:00
        data_validto = datetime.combine(
            data.tomorrow[0].datum.date(),
            time(hour=15),
            get_default_time_zone(),
        )

        if now >= data_validto:
            return True

        self.logger.debug(
            "Waiting until 15:00 before fetching tomorrow's data, skipping"
        )
        return False

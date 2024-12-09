"""Coordinators for the Enever integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging

import homeassistant
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util.dt import as_local

from .const import DOMAIN
from .enever_api import EneverAPI, EneverData, EneverResponse

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


def _data_from_dict(data: dict[str, any] | None) -> list[EneverData] | None:
    if data is None:
        return None

    return [
        EneverData(
            datum=_str_to_datetime(value["datum"]),
            prijs=value["prijs"],
        )
        for value in data
    ]


def _data_to_dict(data: list[EneverData] | None) -> dict[str, any] | None:
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

    today: list[EneverData] | None = None
    today_lastrequest: datetime | None = None
    tomorrow: list[EneverData] | None = None
    tomorrow_lastrequest: datetime | None = None

    @staticmethod
    def from_dict(data: dict[str, any] | None) -> EneverCoordinatorData:
        """Initialize from a dictionary for serialization."""
        if data is None:
            return EneverCoordinatorData()

        return EneverCoordinatorData(
            today=_data_from_dict(data["today"]),
            today_lastrequest=_str_to_datetime(data["today_lastrequest"]),
            tomorrow=_data_from_dict(data["tomorrow"]),
            tomorrow_lastrequest=_str_to_datetime(data["tomorrow_lastrequest"]),
        )

    def to_dict(self) -> dict[str, any]:
        """Return the data as a dictionary for serialization."""
        return {
            "today": _data_to_dict(self.today),
            "today_lastrequest": _datetime_to_str(self.today_lastrequest),
            "tomorrow": _data_to_dict(self.tomorrow),
            "tomorrow_lastrequest": _datetime_to_str(self.tomorrow_lastrequest),
        }


class EneverUpdateCoordinator(DataUpdateCoordinator[EneverCoordinatorData], ABC):
    """Update coordinator for Enever feeds."""

    cached_data: EneverCoordinatorData | None

    def __init__(self, hass: HomeAssistant, api: EneverAPI) -> None:
        """Initialize the update coordinator."""
        self.api = api
        self.cached_data = None

        self.store = Store[EneverCoordinatorData](
            hass, STORAGE_VERSION, f"{DOMAIN}.{self._get_storage_key()}"
        )

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=self._get_update_interval(None),
            always_update=False,
        )

    async def _async_update_data(self) -> EneverCoordinatorData:
        """Update the data."""
        if self.cached_data is None:
            self.cached_data = EneverCoordinatorData.from_dict(
                await self.store.async_load()
            )

            # First run after setup / HA restart, don't perform API calls yet
            return self.cached_data

        # TODO check if required
        now = homeassistant.util.dt.now()
        store = False

        response = await self._fetch_today()
        if response is not None:
            self.cached_data.today = response.data
            self.cached_data.today_lastrequest = now
            store = True

        response = await self._fetch_tomorrow()
        if response is not None:
            self.cached_data.tomorrow = response.data
            self.cached_data.tomorrow_lastrequest = now
            store = True

        if store:
            await self.store.async_save(self.cached_data.to_dict())

        return self.cached_data

    # try:
    #    async with asyncio.timeout(5):
    #        data = await self._fetch_data()
    # data = await self._fetch_data()
    # except InvalidAuth:
    #    raise UpdateFailed("Invalid authentication") from None
    # except PrusaLinkError as err:
    #    raise UpdateFailed(str(err)) from err
    # except (TimeoutError, ConnectError) as err:
    #    raise UpdateFailed("Cannot connect") from err

    # self.update_interval = self._get_update_interval(data)
    # return data

    @abstractmethod
    async def _fetch_today(self) -> EneverResponse:
        """Fetch the actual data for today."""
        raise NotImplementedError

    @abstractmethod
    async def _fetch_tomorrow(self) -> EneverResponse:
        """Fetch the actual data for tomorrow."""
        raise NotImplementedError

    @abstractmethod
    def _get_storage_key(self) -> str:
        """Return the storage key postfix."""
        raise NotImplementedError

    def _get_update_interval(self, data: EneverCoordinatorData) -> timedelta:
        """Get new update interval."""
        return timedelta(seconds=30)


class GasPricesCoordinator(EneverUpdateCoordinator):
    """Gas prices update coordinator."""

    async def _fetch_today(self) -> EneverResponse:
        return await self.api.gasprijs_vandaag()

    async def _fetch_tomorrow(self) -> EneverResponse:
        return None

    def _get_storage_key(self) -> str:
        return "gas"


class ElectricityPricesCoordinator(EneverUpdateCoordinator):
    """Electricity prices update coordinator."""

    async def _fetch_today(self) -> EneverResponse:
        return await self.api.stroomprijs_vandaag()

    async def _fetch_tomorrow(self) -> EneverResponse:
        return await self.api.stroomprijs_morgen()

    def _get_storage_key(self) -> str:
        return "electricity"

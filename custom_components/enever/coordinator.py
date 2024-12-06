"""Coordinators for the Enever integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import logging
from time import monotonic

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .enever_api import EneverAPI, EneverData

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


class EneverCoordinatorData:
    """The data as cached by an EneverUpdateCoordinator."""

    today: EneverData | None
    today_lastrequest: datetime | None
    tomorrow: EneverData | None
    tomorrow_lastrequest: datetime | None


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
            self.cached_data = await self.store.async_load()

            if self.cached_data is None:
                self.cached_data = EneverCoordinatorData()

        # TODO check if required
        # TODO exception handling
        # self.cached_data.today = await self._fetch_today()
        # self.cached_data.tomorrow = await self._fetch_tomorrow()

        self.store.async_save(self.cached_data)

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
    async def _fetch_today(self) -> EneverData:
        """Fetch the actual data for today."""
        raise NotImplementedError

    @abstractmethod
    async def _fetch_tomorrow(self) -> EneverData:
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

    async def _fetch_today(self) -> EneverData:
        return await self.api.gasprijs_vandaag()

    async def _fetch_tomorrow(self) -> EneverData:
        return None

    def _get_storage_key(self) -> str:
        return "gas"


class ElectricityPricesCoordinator(EneverUpdateCoordinator):
    """Electricity prices update coordinator."""

    async def _fetch_today(self) -> EneverData:
        return await self.api.stroomprijs_vandaag()

    async def _fetch_tomorrow(self) -> EneverData:
        return await self.api.stroomprijs_morgen()

    def _get_storage_key(self) -> str:
        return "electricity"

"""Coordinators for the Enever integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta
import logging
from time import monotonic

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback

# from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DOMAIN
from .enever_api import EneverAPI, EneverData

_LOGGER = logging.getLogger(__name__)


class EneverUpdateCoordinator(DataUpdateCoordinator[EneverData], ABC):
    """Update coordinator for Enever feeds."""

    config_entry: ConfigEntry
    expect_change_until = 0.0

    def __init__(self, hass: HomeAssistant, api: EneverAPI) -> None:
        """Initialize the update coordinator."""
        self.api = api
        # self.store = Store[dict[str,EneverDataCache]](hass, STORAGE_VERSION, STORAGE_KEY)

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=self._get_update_interval(None),
            always_update=False,
        )

    async def _async_update_data(self) -> EneverData:
        """Update the data."""
        # try:
        #    async with asyncio.timeout(5):
        #        data = await self._fetch_data()
        # except InvalidAuth:
        #    raise UpdateFailed("Invalid authentication") from None
        # except PrusaLinkError as err:
        #    raise UpdateFailed(str(err)) from err
        # except (TimeoutError, ConnectError) as err:
        #    raise UpdateFailed("Cannot connect") from err

        # self.update_interval = self._get_update_interval(data)
        # return data

    @abstractmethod
    async def _fetch_data(self) -> EneverData:
        """Fetch the actual data."""
        raise NotImplementedError

    @callback
    def expect_change(self) -> None:
        """Expect a change."""
        self.expect_change_until = monotonic() + 30

    def _get_update_interval(self, data: EneverData) -> timedelta:
        """Get new update interval."""
        # TODO base on expected time for new data, last request, and date of last data
        if self.expect_change_until > monotonic():
            return timedelta(seconds=5)

        return timedelta(seconds=30)


class GasPricesCoordinator(EneverUpdateCoordinator):
    """Gas prices update coordinator."""

    async def _fetch_data(self) -> EneverData:
        """Fetch the price data."""
        # TODO cache this data, in helpers.storage?
        return await self.api.gasprijs_vandaag()


class ElectricityPricesCoordinator(EneverUpdateCoordinator):
    """Electricity prices update coordinator."""

    async def _fetch_data(self) -> EneverData:
        """Fetch the price data."""
        # TODO fetch today/tomorrow when relevant
        # TODO cache this data, in helpers.storage?
        return await self.api.stroomprijs_vandaag()

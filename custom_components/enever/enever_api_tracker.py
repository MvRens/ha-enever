"""Tracks API usage and limits."""

from collections.abc import Mapping
from dataclasses import dataclass
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
import homeassistant.util.dt as dt_util

from .const import DOMAIN

STORAGE_VERSION = 1
DEFAULT_REQUEST_LIMIT = 200


@dataclass
class EneverAPITrackerData:
    """The data as cached by an EneverAPITracker."""

    request_count: int
    request_limit: int
    month: str
    token_limit_reached: bool

    @staticmethod
    def from_dict(data: Mapping[str, Any] | None) -> EneverAPITrackerData:
        """Initialize from a dictionary for serialization."""
        if data is None:
            return EneverAPITrackerData(
                request_count=0,
                request_limit=DEFAULT_REQUEST_LIMIT,
                month="",
                token_limit_reached=False,
            )

        return EneverAPITrackerData(
            request_count=data.get("request_count", 0),
            request_limit=data.get("request_limit", 0),
            month=data.get("month", ""),
            token_limit_reached=data.get("token_limit_reached", False),
        )

    def to_dict(self) -> Mapping[str, Any]:
        """Return the data as a dictionary for serialization."""
        return {
            "request_count": self.request_count,
            "request_limit": self.request_limit,
            "month": self.month,
            "token_limit_reached": self.token_limit_reached,
        }


class EneverAPITrackerObserver:
    """Implemented by observers."""

    def apitracker_update(self, data: EneverAPITrackerData) -> None:
        """Called when the state of the API tracker changes."""


class EneverAPITracker:
    """Tracks API usage and limits."""

    _observers: list[EneverAPITrackerObserver]
    _logger: logging.Logger
    _data: EneverAPITrackerData | None
    _store: Store[Mapping[str, Any]]

    def __init__(self, hass: HomeAssistant, logger: logging.Logger) -> None:
        """Initialize the API tracker."""
        self._observers = []
        self._logger = logger
        self._data = None
        self._store = Store[Mapping[str, Any]](
            hass, STORAGE_VERSION, f"{DOMAIN}.shared"
        )

    async def load(self) -> None:
        """Loads the tracker data from the store."""
        if self._data is None:
            self._data = EneverAPITrackerData.from_dict(await self._store.async_load())
            self._update_observers()

    def attach(self, observer: EneverAPITrackerObserver, immediate: bool) -> None:
        """Attach an observer."""
        self._observers.append(observer)

        if immediate and self._data is not None:
            observer.apitracker_update(self._data)

    def detach(self, observer: EneverAPITrackerObserver) -> None:
        """Detach a previously attached observer."""
        self._observers.remove(observer)

    async def allow_request(self) -> bool:
        """Checks if the request limit has not been reached this month."""
        if self._data is None:
            return False

        month = dt_util.now().strftime("%Y%m")
        if month != self._data.month:
            self._logger.debug(
                "Month changed from '%s' to '%s', resetting API counter and token limits",
                self._data.month,
                month,
            )

            self._data.month = month
            self._data.request_count = 0
            self._data.request_limit = DEFAULT_REQUEST_LIMIT
            self._data.token_limit_reached = False
            await self._save_store()

        return (
            self._data.request_count < self._data.request_limit
            and not self._data.token_limit_reached
        )

    async def count_request(self) -> None:
        """Counts a request to the API."""
        if self._data is None:
            return

        self._data.request_count = self._data.request_count + 1

        if self._data.request_count == self._data.request_limit:
            self._logger.warning(
                "The internal request limit of %d has been reached, API requests will be blocked until next month. If this is due to testing and/or you are sure your Enever API token still has requests available, call the enever.set_request_limit service to increase the internal limit for this month.",
                self._data.request_limit,
            )

        await self._save_store()

    async def token_limit_reached(self) -> None:
        """Sets a flag that the token limit has been reached for this month."""
        if self._data is None:
            return

        if self._data.token_limit_reached:
            return

        self._logger.warning(
            "Enever responded that the token limit has been reached, API requests will be blocked until next month. Call the enever.reset service to unblock calls earlier, for example after becoming a Supporter of Enever which increases token limits."
        )
        self._data.token_limit_reached = True
        await self._save_store()

    async def set_limit(self, value: int | None, increase: int | None) -> None:
        """Backend method for enever.set_request_limit action."""
        if self._data is None:
            return

        if value is not None:
            self._data.request_limit = value
            await self._save_store()

        elif increase is not None:
            self._data.request_limit = self._data.request_limit + increase
            await self._save_store()

    async def reset(self, request_count: bool, token_limit_reached: bool) -> None:
        """Backend method for enever.reset action."""
        if self._data is None:
            return

        if not request_count and not token_limit_reached:
            return

        if request_count:
            self._data.request_count = 0

        if token_limit_reached:
            self._data.token_limit_reached = False

        await self._save_store()

    async def _save_store(self) -> None:
        if self._data is None:
            return

        await self._store.async_save(self._data.to_dict())
        self._update_observers()

    def _update_observers(self):
        if self._data is None:
            return

        for observer in self._observers:
            observer.apitracker_update(self._data)

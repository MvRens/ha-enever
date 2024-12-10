"""The Enever integration."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

import homeassistant
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import EneverCoordinatorData, EneverUpdateCoordinator


class EneverEntity(CoordinatorEntity[EneverUpdateCoordinator], ABC):
    """Defines a base Enever entity."""

    provider: str

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: EneverUpdateCoordinator,
        provider: str,
        default_enabled: bool,
    ) -> None:
        """Initialize a Enever sensor entity."""
        super().__init__(coordinator=coordinator)

        self.provider = provider
        self._attr_entity_registry_enabled_default = default_enabled

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this Enever device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self.coordinator.config_entry.entry_id)},
            name=self.coordinator.config_entry.title,
            manufacturer="Enever",
        )

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self._handle_coordinator_update()
        self.async_write_ha_state()

        await super().async_added_to_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        now = homeassistant.util.dt.now()

        self._attr_extra_state_attributes = {}
        self._handle_enever_coordinator_update(self.coordinator.data, now)
        super()._handle_coordinator_update()

    @abstractmethod
    def _handle_enever_coordinator_update(
        self, data: EneverCoordinatorData, now: datetime
    ) -> None:
        raise NotImplementedError


class EneverHourlyEntity(EneverEntity):
    """Defines a base Enever entity which updates every hour."""

    _hourly_timer = None

    async def async_added_to_hass(self) -> None:
        """Run when entity about to be added to hass."""
        self._hourly_timer = async_track_time_change(
            self.hass, self._handle_hour_change, None, 0, 0
        )
        await super().async_added_to_hass()

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""
        if self._hourly_timer is not None:
            self._hourly_timer()
            self._hourly_timer = None

        await super().async_will_remove_from_hass()

    @callback
    def _handle_hour_change(self, now: datetime) -> None:
        self._attr_extra_state_attributes = {}
        self._handle_enever_coordinator_update(self.coordinator.data, now)
        self.async_write_ha_state()

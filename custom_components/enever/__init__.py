"""The Enever integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_API_VERSION, CONF_ENTITY_APICOUNTER_ENABLED, DOMAIN
from .coordinator import (
    ElectricityPricesCoordinator,
    EneverUpdateCoordinator,
    GasPricesCoordinator,
)
from .enever_api_factory import get_enever_api

PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Enever from a config entry."""

    api = get_enever_api(hass, entry.data)

    coordinators = {
        "gas": await _async_init_coordinator(GasPricesCoordinator(hass, api)),
        "electricity": await _async_init_coordinator(
            ElectricityPricesCoordinator(hass, api)
        ),
    }

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinators

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug(
        "Migrating configuration from version %s.%s",
        entry.version,
        entry.minor_version,
    )

    changed = False
    new_data = {**entry.data}

    if entry.version == 1:
        # 1.1 -> 1.2: Added API counter config
        if entry.minor_version < 2:
            new_data = {**new_data, CONF_ENTITY_APICOUNTER_ENABLED: False}
            changed = True

        # 1.2 -> 1.3: Added API version
        if entry.minor_version < 3:
            new_data = {**new_data, CONF_API_VERSION: "v1"}
            changed = True

    if changed:
        hass.config_entries.async_update_entry(
            entry, data=new_data, minor_version=3, version=1
        )

    _LOGGER.debug(
        "Migration to configuration version %s.%s successful",
        entry.version,
        entry.minor_version,
    )
    return True


async def _async_init_coordinator(
    coordinator: EneverUpdateCoordinator,
) -> EneverUpdateCoordinator:
    await coordinator.async_config_entry_first_refresh()
    return coordinator

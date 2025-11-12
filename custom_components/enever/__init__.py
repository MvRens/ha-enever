"""The Enever integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ENTITY_APICOUNTER_ENABLED,
    CONF_OBSOLETE_API_VERSION,
    CONF_RESOLUTION,
    DOMAIN,
)
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
        "gas": await _async_init_coordinator(GasPricesCoordinator(hass, entry, api)),
        "electricity": await _async_init_coordinator(
            ElectricityPricesCoordinator(hass, entry, api)
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

        # 1.3 -> 1.4: Moved to V3 API with resolution parameter instead of different APIs
        if entry.minor_version < 4:
            new_data = {
                **new_data,
                # In 1.2 API version was added, but only in develop, never included in release version.
                # If set however, support a conversion.
                CONF_RESOLUTION: "15"
                if CONF_OBSOLETE_API_VERSION in new_data
                and new_data[CONF_OBSOLETE_API_VERSION] == "v2"
                else "60",
            }
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

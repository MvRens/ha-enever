"""The Enever integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, cast

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv, entity_registry as er
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from .config_entry import EneverRuntimeData
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
from .enever_api_tracker import EneverAPITracker

PLATFORMS: list[Platform] = [Platform.SENSOR]

_LOGGER = logging.getLogger(__name__)

_DATA_ENEVER: HassKey[HassEneverData] = HassKey(DOMAIN)

FORCE_REFRESH_SCHEMA = vol.Schema(
    {
        vol.Optional("entity_id"): cv.entity_ids,
    }
)


@dataclass
class HassEneverData:
    """Contains shared runtime data for the Enever integration."""

    api_tracker: EneverAPITracker


def get_enever_coordinators(
    hass: HomeAssistant, entity_ids: Any | None
) -> list[EneverUpdateCoordinator]:
    """Returns a list of coordinators for the specified entity IDs, or all active coordinators."""
    if entity_ids is None:
        return [
            coordinator
            for entry in hass.config_entries.async_loaded_entries(DOMAIN)
            for coordinator in [
                cast(EneverRuntimeData, entry.runtime_data).electricity_coordinator,
                cast(EneverRuntimeData, entry.runtime_data).gas_coordinator,
            ]
        ]

    entity_registry = er.async_get(hass)

    registry_entries = {
        entry
        for entity_id in entity_ids
        if (entry := entity_registry.async_get(entity_id)) and entry.domain == DOMAIN
    }

    return [
        cast(EneverRuntimeData, entry.runtime_data).electricity_coordinator
        if "_electricity_" in entry.unique_id
        else cast(EneverRuntimeData, entry.runtime_data).gas_coordinator
        for registry_entry in registry_entries
        if registry_entry.config_entry_id is not None
        and (
            entry := hass.config_entries.async_get_entry(registry_entry.config_entry_id)
        )
        and entry.unique_id is not None
    ]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up is called when Home Assistant is loading our component."""

    # pylint: disable=hass-logger-capital # incorrect lint warning, it's not a log message but a suffix
    api_tracker = EneverAPITracker(hass, _LOGGER.getChild("api_tracker"))
    await api_tracker.load()

    hass.data.setdefault(_DATA_ENEVER, HassEneverData(api_tracker=api_tracker))

    async def handle_set_request_limit(call: ServiceCall) -> None:
        """Handle the service action call."""
        value = call.data.get("value")
        increase = call.data.get("increase")

        await api_tracker.set_limit(value, increase)

    async def handle_reset(call: ServiceCall) -> None:
        """Handle the service action call."""
        request_count = call.data.get("request_count", False)
        token_limit_reached = call.data.get("token_limit_reached", False)

        await api_tracker.reset(request_count, token_limit_reached)

    async def handle_force_refresh(call: ServiceCall) -> None:
        """Handle the service action call."""
        entity_ids = call.data.get("entity_id")
        for coordinator in get_enever_coordinators(hass, entity_ids):
            # TODO call force_refresh
            await coordinator.async_request_refresh()

    hass.services.async_register(DOMAIN, "set_request_limit", handle_set_request_limit)
    hass.services.async_register(DOMAIN, "reset", handle_reset)
    hass.services.async_register(
        DOMAIN, "force_refresh", handle_force_refresh, schema=FORCE_REFRESH_SCHEMA
    )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Enever from a config entry."""

    api = get_enever_api(hass, entry.data)
    if (hass_data := hass.data.get(_DATA_ENEVER)) is None:
        _LOGGER.error("Missing runtime data set by async_setup")
        return False

    entry.runtime_data = EneverRuntimeData(
        api_tracker=hass_data.api_tracker,
        electricity_coordinator=await _async_init_coordinator(
            ElectricityPricesCoordinator(hass, entry, api, hass_data.api_tracker)
        ),
        gas_coordinator=await _async_init_coordinator(
            GasPricesCoordinator(hass, entry, api, hass_data.api_tracker)
        ),
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


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

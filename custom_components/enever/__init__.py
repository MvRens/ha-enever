"""The Enever integration."""

from __future__ import annotations

from dataclasses import dataclass
import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, callback
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


@dataclass
class HassEneverData:
    """Contains shared runtime data for the Enever integration."""

    api_tracker: EneverAPITracker


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

    hass.services.async_register(DOMAIN, "set_request_limit", handle_set_request_limit)
    hass.services.async_register(DOMAIN, "reset", handle_reset)

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

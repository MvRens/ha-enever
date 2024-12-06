"""The Enever integration."""

from __future__ import annotations

from coordinator import ElectricityPricesCoordinator, GasPricesCoordinator

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_TOKEN, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

from .const import DOMAIN
from .enever_api import EneverAPI

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Enever from a config entry."""

    api = EneverAPI(get_async_client(hass), entry.data[CONF_API_TOKEN])

    coordinators = {
        "gas": GasPricesCoordinator(hass, api),
        "electricity": ElectricityPricesCoordinator(hass, api),
    }

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinators

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok

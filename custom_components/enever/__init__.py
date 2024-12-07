"""The Enever integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import ElectricityPricesCoordinator, GasPricesCoordinator
from .enever_api_factory import get_enever_api

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Enever from a config entry."""

    api = get_enever_api(hass, entry.data)

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

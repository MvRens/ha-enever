"""Defines the runtime data for the Enever integration."""

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry

from .coordinator import EneverUpdateCoordinator
from .enever_api_tracker import EneverAPITracker

type EneverConfigEntry = ConfigEntry[EneverRuntimeData]


@dataclass
class EneverRuntimeData:
    """Contains the runtime data for the Enever integration."""

    api_tracker: EneverAPITracker
    electricity_coordinator: EneverUpdateCoordinator
    gas_coordinator: EneverUpdateCoordinator

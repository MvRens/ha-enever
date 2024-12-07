"""Enever sensors."""

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import CONF_ENTITIES_DEFAULT_ENABLED, DOMAIN
from .coordinator import EneverUpdateCoordinator
from .enever_api import Providers
from .entity import EneverEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Enever sensor based on a config entry."""
    coordinators: dict[str, EneverUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]

    gasCoordinator = coordinators["gas"]
    electricityCoordinator = coordinators["electricity"]
    entitiesEnabled = entry.data[CONF_ENTITIES_DEFAULT_ENABLED]

    entities: list[EneverEntity] = [
        EneverGasSensorEntity(gasCoordinator, provider, entitiesEnabled)
        for provider in Providers.gas_keys()
    ] + [
        EneverElectricitySensorEntity(electricityCoordinator, provider, entitiesEnabled)
        for provider in Providers.electricity_keys()
    ]

    async_add_entities(entities)


class Unit:
    """Convenience constants for used units."""

    EUR_KWH = f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}"
    EUR_M3 = f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}"


class EneverGasSensorEntity(EneverEntity, SensorEntity):
    """Defines a Enever gas price sensor."""

    def __init__(
        self,
        coordinator: EneverUpdateCoordinator,
        provider: str,
        entities_enabled: bool,
    ) -> None:
        """Initialize a Enever sensor entity."""
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_gas_{provider}"
        self._attr_name = f"gasprijs {Providers.get_display_name(provider)}"
        self._attr_icon = "mdi:gas-burner"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = Unit.EUR_M3
        self._attr_entity_registry_enabled_default = entities_enabled

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        # TODO return value
        # self.coordinator.data
        return None


class EneverElectricitySensorEntity(EneverEntity, SensorEntity):
    """Defines a Enever electricity price sensor."""

    def __init__(
        self,
        coordinator: EneverUpdateCoordinator,
        provider: str,
        entities_enabled: bool,
    ) -> None:
        """Initialize a Enever sensor entity."""
        super().__init__(coordinator=coordinator)
        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_electricity_{provider}"
        )
        self._attr_name = f"stroomprijs {Providers.get_display_name(provider)}"
        self._attr_icon = "mdi:lightning-bolt"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = Unit.EUR_KWH
        self._attr_entity_registry_enabled_default = entities_enabled

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        # TODO return value
        # self.coordinator.data
        return None

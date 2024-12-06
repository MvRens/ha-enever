"""Enever sensors."""

from homeassistant.components.sensor import SensorEntity, SensorEntityDescription
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.typing import StateType

from .const import DOMAIN
from .coordinator import EneverUpdateCoordinator
from .entity import EneverEntity

SENSORS: dict[str, tuple[SensorEntityDescription, ...]] = {
    "gas": (SensorEntityDescription()),
    "electricity": (),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Enever sensor based on a config entry."""
    coordinators: dict[str, EneverUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]

    entities: list[EneverEntity] = []

    for coordinator_type, sensors in SENSORS.items():
        coordinator = coordinators[coordinator_type]
        entities.extend(
            EneverSensorEntity(coordinator, sensor_description)
            for sensor_description in sensors
        )

    async_add_entities(entities)


class EneverSensorEntity(EneverEntity, SensorEntity):
    """Defines a Enever sensor."""

    entity_description: SensorEntityDescription

    def __init__(
        self,
        coordinator: EneverUpdateCoordinator,
        description: SensorEntityDescription,
    ) -> None:
        """Initialize a Enever sensor entity."""
        super().__init__(coordinator=coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_{description.key}"

    @property
    def native_value(self) -> StateType:
        """Return the state of the sensor."""
        # TODO return value
        # return self.entity_description.value_fn(self.coordinator.data)
        return None

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return super().available and self.entity_description.available_fn(
            self.coordinator.data
        )

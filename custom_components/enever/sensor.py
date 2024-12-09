"""Enever sensors."""

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CURRENCY_EURO, UnitOfEnergy, UnitOfVolume
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CONF_ENTITIES_DEFAULT_ENABLED,
    CONF_ENTITIES_PROVIDERS_ELECTRICITY_ENABLED,
    CONF_ENTITIES_PROVIDERS_GAS_ENABLED,
    DOMAIN,
)
from .coordinator import EneverCoordinatorData, EneverUpdateCoordinator
from .enever_api import Providers
from .entity import EneverEntity, EneverHourlyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Enever sensor based on a config entry."""
    coordinators: dict[str, EneverUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]

    gasCoordinator = coordinators["gas"]
    electricityCoordinator = coordinators["electricity"]

    allEnabled = entry.data[CONF_ENTITIES_DEFAULT_ENABLED]
    electricityEnabled = entry.data[CONF_ENTITIES_PROVIDERS_ELECTRICITY_ENABLED]
    gasEnabled = entry.data[CONF_ENTITIES_PROVIDERS_GAS_ENABLED]

    enabledElectricityProviders = (
        Providers.electricity_keys() if allEnabled else electricityEnabled
    )
    enabledGasProviders = Providers.electricity_keys() if allEnabled else gasEnabled

    entities: list[EneverEntity] = [
        EneverGasSensorEntity(
            gasCoordinator, provider, provider in enabledElectricityProviders
        )
        for provider in Providers.gas_keys()
    ] + [
        EneverElectricitySensorEntity(
            electricityCoordinator, provider, provider in enabledGasProviders
        )
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
        default_enabled: bool,
    ) -> None:
        """Initialize a Enever sensor entity."""
        super().__init__(coordinator, provider, default_enabled)

        self._attr_unique_id = f"{coordinator.config_entry.entry_id}_gas_{provider}"
        self._attr_name = f"gasprijs {Providers.get_display_name(provider)}"
        self._attr_icon = "mdi:gas-burner"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = Unit.EUR_M3
        self._attr_suggested_display_precision = 6

    def _handle_enever_coordinator_update(
        self, data: EneverCoordinatorData, now: datetime
    ) -> None:
        if data.today is None or data.today.count == 0:
            return

        self._attr_native_value = data.today[0].prijs.get(self.provider)


class EneverElectricitySensorEntity(EneverHourlyEntity, SensorEntity):
    """Defines a Enever electricity price sensor."""

    provider: str

    def __init__(
        self,
        coordinator: EneverUpdateCoordinator,
        provider: str,
        default_enabled: bool,
    ) -> None:
        """Initialize a Enever sensor entity."""
        super().__init__(coordinator, provider, default_enabled)

        self._attr_unique_id = (
            f"{coordinator.config_entry.entry_id}_electricity_{provider}"
        )

        self._attr_name = f"stroomprijs {Providers.get_display_name(provider)}"
        self._attr_icon = "mdi:lightning-bolt"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = Unit.EUR_KWH
        self._attr_suggested_display_precision = 6

    def _handle_enever_coordinator_update(
        self, data: EneverCoordinatorData, now: datetime
    ) -> None:
        # TODO check date for today, or use tomorrow if required
        today = data.today

        if today is None:
            return

        self._attr_native_value = next(
            (
                data_item.prijs.get(self.provider)
                for data_item in today
                if data_item.datum.hour == now.hour
            ),
            None,
        )

        self._attr_extra_state_attributes["today"] = [
            {"datum": data_item.datum, "prijs": data_item.prijs.get(self.provider)}
            for data_item in today
        ]
        self._attr_extra_state_attributes["tomorrow"] = (
            [
                {"datum": data_item.datum, "prijs": data_item.prijs.get(self.provider)}
                for data_item in data.tomorrow
            ]
            if data.tomorrow is not None
            else None
        )

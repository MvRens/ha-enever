"""Enever sensors."""

from datetime import datetime, timedelta

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

    # TODO add sensors for raw API data? -> maybe later, personally I have no usecase for it except debugging / insight

    async_add_entities(entities)


class Unit:
    """Convenience constants for used units."""

    EUR_KWH = f"{CURRENCY_EURO}/{UnitOfEnergy.KILO_WATT_HOUR}"
    EUR_M3 = f"{CURRENCY_EURO}/{UnitOfVolume.CUBIC_METERS}"


class EneverGasSensorEntity(EneverHourlyEntity, SensorEntity):
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
        self._attr_name = f"Gasprijs {Providers.get_display_name(provider)}"
        self._attr_icon = "mdi:gas-burner"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = Unit.EUR_M3
        self._attr_suggested_display_precision = 6

    def _handle_enever_coordinator_update(
        self, data: EneverCoordinatorData, now: datetime
    ) -> None:
        if data.today is None or len(data.today) == 0:
            return

        # Since gas prices are not known upfront and immediately effective,
        # allow yesterday's data to be "valid" for a bit longer while the coordinator
        # attempts to update the data as soon as possible. A slightly incorrect price is
        # still better than a missing price for the Energy Dashboard.
        data_datetime = data.today[0].datum
        data_validfrom = data_datetime - timedelta(hours=2)
        data_validto = data_validfrom + timedelta(hours=26)

        self._attr_native_value = (
            data.today[0].prijs.get(self.provider)
            if data_validfrom <= now <= data_validto
            else None
        )

        self._attr_extra_state_attributes["lastrequest"] = data.today_lastrequest


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

        self._attr_name = f"Stroomprijs {Providers.get_display_name(provider)}"
        self._attr_icon = "mdi:lightning-bolt"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_device_class = SensorDeviceClass.MONETARY
        self._attr_native_unit_of_measurement = Unit.EUR_KWH
        self._attr_suggested_display_precision = 6

    def _handle_enever_coordinator_update(
        self, data: EneverCoordinatorData, now: datetime
    ) -> None:
        date_today = now.date()
        date_tomorrow = date_today + timedelta(days=1)

        # Figure out if the 'today' feed is indeed still for today, otherwise
        # try to use yesterday's tomorrow feed. This ensures we don't need to update
        # exactly at 12 o'clock midnight for accurate data.
        today = (
            data.today
            if data.today is not None
            and len(data.today) > 0
            and data.today[0].datum.date() == date_today
            else data.tomorrow
            if data.tomorrow is not None
            and len(data.tomorrow) > 0
            and data.tomorrow[0].datum.date() == date_today
            else None
        )

        tomorrow = (
            data.tomorrow
            if data.tomorrow is not None
            and len(data.tomorrow) > 0
            and data.tomorrow[0].datum.date() == date_tomorrow
            else None
        )

        # Set the entity value to the price for the current hour for use in the Energy Dashboard
        self._attr_native_value = (
            next(
                (
                    data_item.prijs.get(self.provider)
                    for data_item in today
                    if data_item.datum.hour == now.hour
                ),
                None,
            )
            if today is not None
            else None
        )

        # Expose the full data for today and tomorrow as attributes (if yet known) for use in graphs
        self._attr_extra_state_attributes["today"] = (
            [
                {"datum": data_item.datum, "prijs": data_item.prijs.get(self.provider)}
                for data_item in today
            ]
            if today is not None
            else None
        )
        self._attr_extra_state_attributes["tomorrow"] = (
            [
                {"datum": data_item.datum, "prijs": data_item.prijs.get(self.provider)}
                for data_item in tomorrow
            ]
            if tomorrow is not None
            else None
        )

        self._attr_extra_state_attributes["today_lastrequest"] = data.today_lastrequest
        self._attr_extra_state_attributes["tomorrow_lastrequest"] = (
            data.tomorrow_lastrequest
        )

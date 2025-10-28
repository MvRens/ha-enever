"""Enever sensors."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from typing import cast

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfVolume
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
import homeassistant.util.dt as dt_util

from .const import (
    CONF_ENTITIES_DEFAULT_ENABLED,
    CONF_ENTITIES_PROVIDERS_ELECTRICITY_ENABLED,
    CONF_ENTITIES_PROVIDERS_GAS_ENABLED,
    CONF_ENTITY_APICOUNTER_ENABLED,
    DOMAIN,
)
from .coordinator import (
    EneverCoordinatorData,
    EneverCoordinatorObserver,
    EneverUpdateCoordinator,
)
from .enever_api import EneverData, Providers
from .entity import EneverHourlyEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Enever sensor based on a config entry."""
    coordinators: dict[str, EneverUpdateCoordinator] = hass.data[DOMAIN][entry.entry_id]

    gasCoordinator = coordinators["gas"]
    electricityCoordinator = coordinators["electricity"]

    allEnabled = entry.data[CONF_ENTITIES_DEFAULT_ENABLED]
    electricityEnabled = entry.data[CONF_ENTITIES_PROVIDERS_ELECTRICITY_ENABLED]
    gasEnabled = entry.data[CONF_ENTITIES_PROVIDERS_GAS_ENABLED]
    apiCounterEnabled = entry.data[CONF_ENTITY_APICOUNTER_ENABLED]

    enabledElectricityProviders = (
        Providers.electricity_keys() if allEnabled else electricityEnabled
    )
    enabledGasProviders = Providers.gas_keys() if allEnabled else gasEnabled

    entities: Sequence[Entity] = (
        [
            EneverGasSensorEntity(
                gasCoordinator, provider, provider in enabledGasProviders
            )
            for provider in Providers.gas_keys()
        ]
        + [
            EneverElectricitySensorEntity(
                electricityCoordinator,
                provider,
                provider in enabledElectricityProviders,
            )
            for provider in Providers.electricity_keys()
        ]
        + [
            EneverRequestCountSensorEntity(
                entry, [gasCoordinator, electricityCoordinator], apiCounterEnabled
            )
        ]
    )

    async_add_entities(entities)


class Unit:
    """Convenience constants for used units."""

    EUR_KWH = f"EUR/{UnitOfEnergy.KILO_WATT_HOUR}"
    EUR_M3 = f"EUR/{UnitOfVolume.CUBIC_METERS}"


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

        if coordinator.config_entry is None:
            raise ValueError("coordinator.config_entry must not be None")

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
        provider_price = data.today[0].prijs.get(self.provider)

        # There have been days where Enever mistakenly reports a negative gas price. Since this
        # should never happen and wrecks the energy dashboard calculations, use yesterday's price.
        # Not correct, but still better.
        # TODO log warning
        if provider_price is not None and provider_price < 0:
            provider_price = self._attr_native_value

        self._attr_native_value = (
            provider_price if data_validfrom <= now <= data_validto else None
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

        if coordinator.config_entry is None:
            raise ValueError("coordinator.config_entry must not be None")

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

        data_today = self._get_provider_data(today)
        data_tomorrow = self._get_provider_data(tomorrow)

        # Set the entity value to the price for the current time slot for use in the Energy Dashboard
        current_item = (
            max(
                (item for item in data_today if cast(datetime, item["time"]) <= now),
                key=lambda x: cast(datetime, x["time"]),
                default=None,
            )
            if data_today
            else None
        )

        self._attr_native_value = current_item["price"] if current_item else None

        # Calculate averages
        self._attr_extra_state_attributes["today_average"] = (
            self._calculate_average_price(data_today)
        )
        self._attr_extra_state_attributes["tomorrow_average"] = (
            self._calculate_average_price(data_tomorrow)
        )

        # Expose the full data for today and tomorrow as attributes (if yet known) for use in graphs
        self._attr_extra_state_attributes["prices_today"] = data_today
        self._attr_extra_state_attributes["prices_tomorrow"] = data_tomorrow

        self._attr_extra_state_attributes["today_lastrequest"] = data.today_lastrequest
        self._attr_extra_state_attributes["tomorrow_lastrequest"] = (
            data.tomorrow_lastrequest
        )

    def _get_provider_data(
        self, data: list[EneverData] | None
    ) -> list[dict[str, datetime | float | None]] | None:
        return (
            [
                {"time": data_item.datum, "price": data_item.prijs.get(self.provider)}
                for data_item in data
            ]
            if data is not None
            else None
        )

    def _calculate_average_price(
        self, data: list[dict[str, datetime | float | None]] | None
    ) -> float | None:
        if data is None or len(data) == 0:
            return None

        valid_prices = [
            cast(float, data_item["price"])
            for data_item in data
            if data_item["price"] is not None
        ]

        return sum(valid_prices) / len(valid_prices) if valid_prices else 0


class EneverRequestCountSensorEntity(RestoreSensor, EneverCoordinatorObserver):
    """Defines a sensor which monitors the amount of Enever API requests."""

    _entry: ConfigEntry
    _coordinators: list[EneverUpdateCoordinator]
    _monthly_timer: CALLBACK_TYPE | None

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: ConfigEntry,
        coordinators: list[EneverUpdateCoordinator],
        default_enabled: bool,
    ) -> None:
        """Initialize a Enever sensor entity."""
        self._entry = entry
        self._coordinators = coordinators
        self._monthly_timer = None

        self._attr_unique_id = f"{entry.entry_id}_api_requests"

        self._attr_name = "API requests"
        self._attr_icon = "mdi:api"
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_entity_registry_enabled_default = default_enabled

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information about this Enever device."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name=self._entry.title,
            manufacturer="Enever",
        )

    async def async_added_to_hass(self) -> None:
        """Handle addition to hass: restore state and register to dispatch."""
        await super().async_added_to_hass()

        state = await self.async_get_last_state()
        if state and state.state is not None:
            try:
                self._attr_native_value = int(state.state)
            except ValueError:
                self._attr_native_value = 0

            self._attr_extra_state_attributes = state.attributes
            self.async_write_ha_state()

        for coordinator in self._coordinators:
            coordinator.attach(self)

        self._monthly_timer = async_track_time_change(
            self.hass, self._handle_day_change, 0, 0, 0
        )

        if self._reset_month(dt_util.now()):
            self._async_write_ha_state()

    async def async_will_remove_from_hass(self) -> None:
        """Unregister signal dispatch listeners when being removed."""
        for coordinator in self._coordinators:
            coordinator.detach(self)

        if self._monthly_timer is not None:
            self._monthly_timer()
            self._monthly_timer = None

        await super().async_will_remove_from_hass()

    def count_api_request(self) -> None:
        """Call before an API request is made."""
        self._reset_month(dt_util.now())

        self._attr_native_value = (
            cast(int, self._attr_native_value) + 1
            if self._attr_native_value is not None
            else 1
        )

        self.async_write_ha_state()

    @callback
    def _handle_day_change(self, now: datetime) -> None:
        if self._reset_month(now):
            self.async_write_ha_state()

    def _reset_month(self, now: datetime) -> bool:
        start_of_month = now.date().replace(day=1)
        counter_month_attr = (
            self._attr_extra_state_attributes.get("month")
            if hasattr(self, "_attr_extra_state_attributes")
            else None
        )
        counter_month = (
            counter_month_attr
            if type(counter_month_attr) is date
            else date.fromisoformat(counter_month_attr)
            if type(counter_month_attr) is str
            else None
        )

        if counter_month != start_of_month:
            # New month, reset counter
            self._attr_native_value = 0
            self._attr_extra_state_attributes = {"month": start_of_month}
            return True

        return False

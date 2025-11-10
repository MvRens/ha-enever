"""Config flow for Enever integration."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import selector

from .const import (
    CONF_ENTITIES_DEFAULT_ENABLED,
    CONF_ENTITIES_PROVIDERS_ELECTRICITY_ENABLED,
    CONF_ENTITIES_PROVIDERS_GAS_ENABLED,
    CONF_ENTITY_APICOUNTER_ENABLED,
    CONF_RESOLUTION,
    DOMAIN,
)
from .enever_api import EneverCannotConnect, EneverInvalidToken, Providers
from .enever_api_factory import get_enever_api

_LOGGER = logging.getLogger(__name__)


SELECTOR_RESOLUTION = selector(
    {
        "select": {
            "options": [
                {"value": "60", "label": "1 hour"},
                {"value": "15", "label": "15 minutes"},
            ]
        }
    }
)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_TOKEN): cv.string,
        vol.Required(CONF_RESOLUTION): SELECTOR_RESOLUTION,
        vol.Required(CONF_ENTITIES_DEFAULT_ENABLED): cv.boolean,
        vol.Optional(
            CONF_ENTITIES_PROVIDERS_ELECTRICITY_ENABLED, default=[]
        ): cv.multi_select(
            dict(sorted(Providers.electricity().items(), key=lambda item: item[1]))
        ),
        vol.Optional(CONF_ENTITIES_PROVIDERS_GAS_ENABLED, default=[]): cv.multi_select(
            dict(sorted(Providers.gas().items(), key=lambda item: item[1]))
        ),
        vol.Required(CONF_ENTITY_APICOUNTER_ENABLED): cv.boolean,
    }
)

STEP_RECONFIGURE_SCHEMA = vol.Schema(
    {vol.Required(CONF_RESOLUTION): SELECTOR_RESOLUTION}
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]):
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
    api = get_enever_api(hass, data)
    await api.validate_token()


class EneverConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Enever."""

    VERSION = 1
    MINOR_VERSION = 4

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                await validate_input(self.hass, user_input)
            except EneverCannotConnect:
                errors["base"] = "cannot_connect"
            except EneverInvalidToken:
                errors["base"] = "invalid_auth"
            except Exception:
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_create_entry(title="Enever", data=user_input)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the reconfigure step."""
        reconfig_entry = self._get_reconfigure_entry()
        if user_input is not None:
            # self.async_set_unique_id(user_id)
            # self._abort_if_unique_id_mismatch()

            # TODO if resolution changed, invalidate cache
            return self.async_update_reload_and_abort(
                reconfig_entry, data_updates=user_input
            )

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                STEP_RECONFIGURE_SCHEMA, user_input or reconfig_entry.data
            ),
        )

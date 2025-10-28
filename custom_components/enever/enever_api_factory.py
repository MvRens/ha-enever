"""Wrapper for initializing an Enever API instance."""

from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_API_TOKEN, CONF_API_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

from .enever_api import EneverAPI, MockEneverAPI, ProductionEneverAPI

MOCK = False


def get_enever_api(hass: HomeAssistant, data: Mapping[str, Any]) -> EneverAPI:
    """Construct an Enever API instance."""
    if MOCK:
        return MockEneverAPI()

    return ProductionEneverAPI(
        get_async_client(hass), data[CONF_API_TOKEN], data[CONF_API_VERSION]
    )

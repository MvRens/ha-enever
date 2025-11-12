"""Wrapper for initializing an Enever API instance."""

from collections.abc import Mapping
from typing import Any

from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

from .const import CONF_RESOLUTION
from .enever_api import EneverAPI, MockEneverAPI, ProductionEneverAPI

MOCK = False


def get_enever_api(hass: HomeAssistant, data: Mapping[str, Any]) -> EneverAPI:
    """Construct an Enever API instance."""
    if MOCK:
        return MockEneverAPI()

    try:
        resolution = int(data[CONF_RESOLUTION])
    except ValueError:
        resolution = 60

    return ProductionEneverAPI(get_async_client(hass), data[CONF_API_TOKEN], resolution)

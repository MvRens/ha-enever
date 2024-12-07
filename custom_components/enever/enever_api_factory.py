"""Wrapper for initializing an Enever API instance."""

from homeassistant.const import CONF_API_TOKEN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.httpx_client import get_async_client

from .enever_api import EneverAPI, MockEneverAPI, ProductionEneverAPI

MOCK = True


def get_enever_api(hass: HomeAssistant, data: dict[str, any]) -> EneverAPI:
    """Construct an Enever API instance."""
    if MOCK:
        return MockEneverAPI()

    return ProductionEneverAPI(get_async_client(hass), data[CONF_API_TOKEN])

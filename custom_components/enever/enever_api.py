"""Wrapper for the Enever prijzenfeeds."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TypedDict

import anyio
from httpx import AsyncClient, Response

from homeassistant.util.dt import as_local, parse_datetime


class EneverError(Exception):
    """Error calling the Enever API."""


class EneverTokenLimitReached(EneverError):
    """Error to indicate the token has reached it's monthly limit."""


class EneverInvalidToken(EneverError):
    """Error to indicate the token is invalid."""


BASE_URL = "https://enever.nl/apiv3/"


class ProviderInfo(TypedDict):
    """Contains information about a provider."""

    name: str
    gas: bool
    electricity: bool


PROVIDERS: dict[str, ProviderInfo] = {
    "": {"name": "Beursprijs", "electricity": True, "gas": False},
    "EGSI": {"name": "Beursprijs EGSI", "electricity": False, "gas": True},
    "EOD": {"name": "Beursprijs EOD", "electricity": False, "gas": True},
    "ANWB": {"name": "ANWB Energie", "electricity": True, "gas": True},
    "BE": {"name": "Budget Energie", "electricity": True, "gas": True},
    "CB": {"name": "Coolblue Energie", "electricity": True, "gas": False},
    "ED": {"name": "Energiedirect", "electricity": True, "gas": True},
    "EE": {"name": "EasyEnergy", "electricity": True, "gas": True},
    "EG": {"name": "Energiek", "electricity": True, "gas": True},
    "EN": {"name": "Eneco", "electricity": True, "gas": True},
    "ES": {"name": "Essent", "electricity": True, "gas": True},
    "EVO": {"name": "Energie VanOns", "electricity": True, "gas": True},
    "EZ": {"name": "EnergyZero", "electricity": True, "gas": True},
    "FR": {"name": "Frank Energie", "electricity": True, "gas": True},
    "GSL": {"name": "Groenestroom Lokaal", "electricity": True, "gas": True},
    "HE": {"name": "Hegg Energy", "electricity": True, "gas": True},
    "IN": {"name": "Innova Energie", "electricity": True, "gas": True},
    "MDE": {"name": "Mijndomein Energie", "electricity": True, "gas": True},
    "NE": {"name": "NextEnergy", "electricity": True, "gas": True},
    "PE": {"name": "Pure Energie", "electricity": True, "gas": True},
    "QU": {"name": "Quatt", "electricity": True, "gas": True},
    "SS": {"name": "SamSam", "electricity": True, "gas": True},
    "TI": {"name": "Tibber", "electricity": True, "gas": True},
    "VDB": {"name": "Vandebron", "electricity": True, "gas": True},
    "VF": {"name": "Vattenfall", "electricity": True, "gas": True},
    "VON": {"name": "Vrij op naam", "electricity": True, "gas": True},
    "WE": {"name": "Wout Energie", "electricity": True, "gas": True},
    "ZP": {"name": "Zonneplan", "electricity": True, "gas": True},
}


class Providers:
    """Helper methods for providers."""

    @staticmethod
    def electricity() -> dict[str, str]:
        """Return a dictionary for all providers of electricity price data."""
        return {
            pair[0]: pair[1]["name"]
            for pair in PROVIDERS.items()
            if Providers.supports_electricity(pair[0])
        }

    @staticmethod
    def electricity_keys() -> list[str]:
        """Return the keys for all providers of electricity price data."""
        return [key for key in PROVIDERS if Providers.supports_electricity(key)]

    @staticmethod
    def gas() -> dict[str, str]:
        """Return a dictionary for all providers of gas price data."""
        return {
            pair[0]: pair[1]["name"]
            for pair in PROVIDERS.items()
            if Providers.supports_gas(pair[0])
        }

    @staticmethod
    def gas_keys() -> list[str]:
        """Return the keys for all providers of gas price data."""
        return [key for key in PROVIDERS if Providers.supports_gas(key)]

    @staticmethod
    def supports_electricity(provider: str) -> bool:
        """Check if a provider is valid and supports electricity price data."""
        if provider not in PROVIDERS:
            return False

        return PROVIDERS[provider]["electricity"]

    @staticmethod
    def supports_gas(provider: str) -> bool:
        """Check if a provider is valid and supports gas price data."""
        if provider not in PROVIDERS:
            return False

        return PROVIDERS[provider]["gas"]

    @staticmethod
    def get_display_name(provider: str) -> str:
        """Return the display name for the provider, or the input value if not valid."""
        return PROVIDERS[provider]["name"] if provider in PROVIDERS else provider


@dataclass
class EneverData:
    """Parsed data from an Enever endpoint."""

    datum: datetime
    prijs: dict[str, float | None]

    @staticmethod
    def from_dict(item: dict):
        """Parse a data item in a JSON response from an API call."""
        dt = parse_datetime(item["datum"])
        if dt is None:
            raise ValueError("datum could not be parsed as a datetime")

        return EneverData(
            datum=as_local(dt),
            prijs={
                key: float(value) if value is not None else None
                for key in PROVIDERS
                if (value := item.get("prijs" + key)) is not None
            },
        )


@dataclass
class EneverResponse:
    """Parsed data for a specific date from an Enever endpoint."""

    data: list[EneverData]

    @staticmethod
    def from_dict(data: list[dict]):
        """Parse the data value in a JSON response from an API call."""
        return EneverResponse(data=[EneverData.from_dict(item) for item in data])


class EneverAPI(ABC):
    """Wrapper class for the Enever prijzenfeeds."""

    ENDPOINT_STROOMPRIJS_VANDAAG = "stroomprijs_vandaag.php"
    ENDPOINT_STROOMPRIJS_MORGEN = "stroomprijs_morgen.php"
    ENDPOINT_GASPRIJS_VANDAAG = "gasprijs_vandaag.php"

    async def validate_token(self):
        """Test if the token is valid.

        Note: counts towards request limit!
        """
        response = await self._fetch_raw(self.ENDPOINT_GASPRIJS_VANDAAG)

        match response.status_code:
            case 200:
                response_payload = response.json()
                if response_payload["code"] == "2":
                    raise EneverInvalidToken
            case _:
                raise EneverError(response.status_code)

    async def stroomprijs_vandaag(self) -> EneverResponse:
        """Return the electricity prices for today."""
        return await self._fetch_parsed(self.ENDPOINT_STROOMPRIJS_VANDAAG)

    async def stroomprijs_morgen(self) -> EneverResponse:
        """Return the electricity prices for tomorrow."""
        return await self._fetch_parsed(self.ENDPOINT_STROOMPRIJS_MORGEN)

    async def gasprijs_vandaag(self) -> EneverResponse:
        """Return the gas prices for today."""
        return await self._fetch_parsed(self.ENDPOINT_GASPRIJS_VANDAAG)

    async def _fetch_parsed(self, endpoint: str):
        response = await self._fetch_raw(endpoint)

        match response.status_code:
            case 200:
                response_payload = response.json()

                if "data" not in response_payload:
                    raise EneverError("No data element in response")

                if not isinstance(response_payload["data"], list):
                    if response_payload["code"] == "2":
                        raise EneverInvalidToken

                    if response_payload["code"] == "6":
                        raise EneverTokenLimitReached

                    raise EneverError(
                        "Invalid data element in response: " + response_payload["data"]
                    )

                return EneverResponse.from_dict(response_payload["data"])
            case _:
                raise EneverError("HTTP status " + str(response.status_code))

    @abstractmethod
    async def _fetch_raw(self, endpoint: str) -> Response:
        raise NotImplementedError


class ProductionEneverAPI(EneverAPI):
    """Wrapper class for the Enever prijzenfeeds."""

    def __init__(self, client: AsyncClient, token: str, resolution: int) -> None:
        """Initialize."""
        self.client = client
        self.token = token
        self.resolution = resolution

    async def _fetch_raw(self, endpoint: str) -> Response:
        params = {"token": self.token, "resolution": self.resolution}
        return await self.client.get(BASE_URL + endpoint, params=params)


class MockEneverAPI(EneverAPI):
    """Mock wrapper class for the Enever prijzenfeeds.

    To use it, mount the 'mockdata' folder in the devcontainer to /mock.
    It's not a proper mock for automated testing, but good enough for quick manual tests
    without using up too many API tokens.
    """

    async def _fetch_raw(self, endpoint: str) -> Response:
        async with await anyio.open_file(f"/mock/{endpoint}.json") as f:
            return Response(status_code=200, content=await f.read())

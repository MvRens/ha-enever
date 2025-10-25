"""Wrapper for the Enever prijzenfeeds."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

import anyio
from httpx import AsyncClient, Response, TimeoutException

from homeassistant.util.dt import as_local, parse_datetime


class EneverError(Exception):
    """Error calling the Enever API."""


class EneverCannotConnect(EneverError):
    """Error to indicate we cannot connect."""


class EneverInvalidToken(EneverError):
    """Error to indicate the token is invalid."""


BASE_URL = "https://enever.nl/apiv2/"


PROVIDERS: dict[str, str] = {
    "": "Beurprijs",
    "AA": "Atoom Alliantie",
    "AIP": "All in power",
    "ANWB": "ANWB Energie",
    "BE": "Budget Energie",
    "EE": "EasyEnergy",
    "EN": "Eneco",
    "EVO": "Energie VanOns",
    "EZ": "EnergyZero",
    "FR": "Frank Energie",
    "GSL": "Groenestroom Lokaal",
    "MDE": "Mijndomein Energie",
    "NE": "NextEnergy",
    "TI": "Tibber",
    "VDB": "Vandebron",
    "VON": "Vrij op naam",
    "WE": "Wout Energie",
    "ZG": "ZonderGas",
    "ZP": "Zonneplan",
    "EGSI": "Beursprijs EGSI",
    "EOD": "Beursprijs EOD",
}


class Providers:
    """Helper methods for providers."""

    @staticmethod
    def electricity() -> dict[str, str]:
        """Return a dictionary for all providers of electricity price data."""
        return {
            pair[0]: pair[1]
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
            pair[0]: pair[1]
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

        return provider not in ["EGSI", "EOD"]

    @staticmethod
    def supports_gas(provider: str) -> bool:
        """Check if a provider is valid and supports gas price data."""
        if provider not in PROVIDERS:
            return False

        return provider not in ["", "TI"]

    @staticmethod
    def get_display_name(provider: str) -> str:
        """Return the display name for the provider, or the input value if not valid."""
        return PROVIDERS.get(provider, provider)


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
        try:
            response = await self._fetch_raw(self.ENDPOINT_GASPRIJS_VANDAAG)

            match response.status_code:
                case 200:
                    response_payload = response.json()
                    if response_payload["code"] == "2":
                        raise EneverInvalidToken
                case _:
                    raise EneverError(response.status_code)
        except TimeoutException as e:
            raise EneverCannotConnect from e

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
        try:
            response = await self._fetch_raw(endpoint)

            match response.status_code:
                case 200:
                    response_payload = response.json()

                    if "data" not in response_payload:
                        raise EneverError("No data element in response")

                    if not isinstance(response_payload["data"], list):
                        if response_payload["code"] == "2":
                            raise EneverInvalidToken

                        raise EneverError(
                            "Invalid data element in response: "
                            + response_payload["data"]
                        )

                    return EneverResponse.from_dict(response_payload["data"])
                case _:
                    raise EneverError("HTTP status " + str(response.status_code))
        except TimeoutException as e:
            raise EneverCannotConnect from e

    @abstractmethod
    async def _fetch_raw(self, endpoint: str) -> Response:
        raise NotImplementedError


class ProductionEneverAPI(EneverAPI):
    """Wrapper class for the Enever prijzenfeeds."""

    def __init__(self, client: AsyncClient, token: str) -> None:
        """Initialize."""
        self.client = client
        self.token = token

    async def _fetch_raw(self, endpoint: str) -> Response:
        params = {"token": self.token}
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

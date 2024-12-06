"""Wrapper for the Enever prijzenfeeds."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from httpx import AsyncClient, TimeoutException


class EneverError(Exception):
    """Error calling the Enever API."""


class EneverCannotConnect(EneverError):
    """Error to indicate we cannot connect."""


class EneverInvalidToken(EneverError):
    """Error to indicate the token is invalid."""


BASE_URL = "https://enever.nl/api/"


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
    def electricity_keys() -> list[str]:
        """Return the keys for all providers of electricity price data."""
        return [key for key in PROVIDERS if Providers.supports_electricity(key)]

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

    datum: date
    prijs: dict[str, Decimal]

    @staticmethod
    def from_dict(item: dict):
        """Parse a data item in a JSON response from an API call."""
        return EneverData(
            datum=item["datum"],
            prijs={
                key: item.get("prijs" + key, None) for key in PROVIDERS if key in item
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


class EneverAPI:
    """Wrapper class for the Enever prijzenfeeds."""

    ENDPOINT_STROOMPRIJS_VANDAAG = "stroomprijs_vandaag.php"
    ENDPOINT_STROOMPRIJS_MORGEN = "stroomprijs_morgen.php"
    ENDPOINT_GASPRIJS_VANDAAG = "gasprijs_vandaag.php"

    def __init__(self, client: AsyncClient, token: str) -> None:
        """Initialize."""
        self.client = client
        self.token = token

    async def validate_token(self):
        """Test if the token is valid.

        Note: counts towards request limit!
        """
        try:
            params = {"token": self.token}
            response = await self.client.get(
                BASE_URL + self.ENDPOINT_GASPRIJS_VANDAAG, params=params
            )

            match response.status_code:
                case 200:
                    response_payload = response.json()
                    if response_payload["code"] == "2":
                        raise EneverInvalidToken
                case _:
                    raise EneverError(response.status_code)
        except TimeoutException as e:
            raise EneverCannotConnect from e

    async def stroomprijs_vandaag(self) -> EneverData:
        """Return the electricity prices for today."""
        return await self.__fetch(self.ENDPOINT_STROOMPRIJS_VANDAAG)

    async def stroomprijs_morgen(self) -> EneverData:
        """Return the electricity prices for tomorrow."""
        return await self.__fetch(self.ENDPOINT_STROOMPRIJS_MORGEN)

    async def gasprijs_vandaag(self) -> EneverData:
        """Return the gas prices for today."""
        return await self.__fetch(self.ENDPOINT_GASPRIJS_VANDAAG)

    async def __fetch(self, endpoint: str):
        params = {"token": self.token}

        try:
            response = self.client.get(BASE_URL + endpoint, params=params)

            match response.status_code:
                case 200:
                    response_payload = response.json()
                    if response_payload["code"] != "5":
                        raise EneverError(
                            "Unexpected code in response: " + response_payload["code"]
                        )

                    return EneverResponse.from_dict(response_payload["data"])
                case _:
                    raise EneverError("HTTP status " + response.status_code)
        except TimeoutException as e:
            raise EneverCannotConnect from e

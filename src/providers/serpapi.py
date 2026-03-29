from __future__ import annotations

import logging
from datetime import datetime

import httpx

from src.cache.manager import TTLCache
from src.config import get_settings
from src.models.flight import Airport, FlightResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://serpapi.com/search.json"


class RateLimitError(Exception):
    pass


class SerpApiProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.serpapi_api_key
        self._cache: TTLCache[list[FlightResult]] = TTLCache(
            default_ttl_seconds=settings.flights_ttl
        )

    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None = None,
        adults: int = 1,
        cabin_class: str = "economy",
    ) -> list[FlightResult]:
        cache_key = f"serpapi:{origin}:{destination}:{departure_date}:{return_date}:{adults}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        params: dict[str, str | int] = {
            "engine": "google_flights",
            "departure_id": origin,
            "arrival_id": destination,
            "outbound_date": departure_date,
            "currency": "EUR",
            "hl": "es",
            "api_key": self._api_key,
            "adults": adults,
        }

        if return_date:
            params["type"] = 1  # round trip
            params["return_date"] = return_date
        else:
            params["type"] = 2  # one-way

        travel_class = _map_cabin_class(cabin_class)
        if travel_class:
            params["travel_class"] = travel_class

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(_BASE_URL, params=params)

        if response.status_code == 429:
            raise RateLimitError("SerpApi rate limit exceeded (250/month free tier)")

        if response.status_code != 200:
            raise RuntimeError(
                f"SerpApi returned HTTP {response.status_code}: {response.text[:200]}"
            )

        data = response.json()

        if "error" in data:
            raise RuntimeError(f"SerpApi error: {data['error']}")

        results = _parse_flights(data)
        self._cache.set(cache_key, results)
        return results


def _map_cabin_class(cabin_class: str) -> int | None:
    mapping = {"economy": 1, "premium_economy": 2, "business": 3, "first": 4}
    return mapping.get(cabin_class.lower())


def _parse_flights(data: dict) -> list[FlightResult]:
    results: list[FlightResult] = []

    for group in data.get("best_flights", []) + data.get("other_flights", []):
        try:
            results.append(_map_flight_group(group))
        except Exception as exc:
            logger.warning("Skipping malformed SerpApi flight: %s", exc)

    return results


def _map_flight_group(group: dict) -> FlightResult:
    flights = group["flights"]
    first_leg = flights[0]
    last_leg = flights[-1]

    dep_airport = first_leg["departure_airport"]
    arr_airport = last_leg["arrival_airport"]

    dep_time = datetime.strptime(dep_airport["time"], "%Y-%m-%d %H:%M")
    arr_time = datetime.strptime(arr_airport["time"], "%Y-%m-%d %H:%M")

    total_duration = group.get("total_duration", 0)
    if not total_duration:
        total_duration = int((arr_time - dep_time).total_seconds() / 60)

    price = group.get("price", 0)

    airlines = [f.get("airline", "Unknown") for f in flights]
    airline_display = airlines[0] if len(set(airlines)) == 1 else " + ".join(airlines)

    flight_number = first_leg.get("flight_number", "")
    stops = len(flights) - 1

    cabin = first_leg.get("travel_class", "Economy")

    return FlightResult(
        airline=airline_display,
        flight_number=flight_number,
        origin_airport=Airport(
            iata_code=dep_airport.get("id", "???"),
            name=dep_airport.get("name", "Unknown"),
            city=dep_airport.get("id", "Unknown"),
        ),
        destination_airport=Airport(
            iata_code=arr_airport.get("id", "???"),
            name=arr_airport.get("name", "Unknown"),
            city=arr_airport.get("id", "Unknown"),
        ),
        departure_time=dep_time,
        arrival_time=arr_time,
        duration_minutes=max(total_duration, 0),
        price_eur=float(price),
        currency="EUR",
        stops=stops,
        cabin_class=cabin,
        booking_url=None,
    )

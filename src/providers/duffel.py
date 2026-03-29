from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from src.cache.manager import TTLCache
from src.config import get_settings
from src.models.flight import Airport, FlightResult

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    pass


class DuffelProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self._access_token = settings.duffel_access_token
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
        cache_key = (
            f"duffel:{origin}:{destination}:{departure_date}:{return_date}:{adults}:{cabin_class}"
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        results = await asyncio.get_event_loop().run_in_executor(
            None,
            _blocking_search,
            self._access_token,
            origin,
            destination,
            departure_date,
            return_date,
            adults,
            cabin_class.lower(),
        )
        self._cache.set(cache_key, results)
        return results


_CABIN_MAP = {
    "economy": "economy",
    "premium_economy": "premium_economy",
    "business": "business",
    "first": "first",
}


def _blocking_search(
    access_token: str,
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
    adults: int,
    cabin_class: str,
) -> list[FlightResult]:
    try:
        from duffel_api import Duffel
    except ImportError as exc:
        logger.error("duffel-api package not installed: %s", exc)
        raise

    client = Duffel(access_token=access_token)

    slices = [{"origin": origin, "destination": destination, "departure_date": departure_date}]
    if return_date:
        slices.append(
            {"origin": destination, "destination": origin, "departure_date": return_date}
        )

    passengers = [{"type": "adult"} for _ in range(adults)]
    duffel_cabin = _CABIN_MAP.get(cabin_class, "economy")

    try:
        offer_request = client.offer_requests.create(
            slices=slices,
            passengers=passengers,
            cabin_class=duffel_cabin,
            return_offers=True,
            max_connections=1,
        )
    except Exception as exc:
        exc_str = str(exc)
        if "429" in exc_str or "rate" in exc_str.lower():
            raise RateLimitError("Duffel API rate limit exceeded") from exc
        raise

    offers = getattr(offer_request, "offers", None) or []
    results = []
    for offer in offers[:20]:
        try:
            results.append(_map_offer(offer))
        except Exception as exc:
            logger.warning("Skipping malformed Duffel offer: %s", exc)

    return results


def _map_offer(offer: object) -> FlightResult:
    slices = getattr(offer, "slices", [])
    first_slice = slices[0]
    segments = getattr(first_slice, "segments", [])
    first_seg = segments[0]
    last_seg = segments[-1]

    origin_airport = getattr(first_seg, "origin", None)
    dest_airport = getattr(last_seg, "destination", None)

    dep_time = datetime.fromisoformat(str(getattr(first_seg, "departing_at", "")))
    arr_time = datetime.fromisoformat(str(getattr(last_seg, "arriving_at", "")))
    duration_minutes = int((arr_time - dep_time).total_seconds() / 60)

    owner = getattr(offer, "owner", None)
    airline_name = getattr(owner, "name", "Unknown") if owner else "Unknown"
    airline_iata = getattr(owner, "iata_code", "??") if owner else "??"

    operating_carrier = getattr(first_seg, "operating_carrier", None)
    flight_number = ""
    if operating_carrier:
        carrier_code = getattr(operating_carrier, "iata_code", "")
        seg_number = getattr(first_seg, "operating_carrier_flight_number", "")
        flight_number = f"{carrier_code}{seg_number}"

    total_amount = float(getattr(offer, "total_amount", 0))
    total_currency = getattr(offer, "total_currency", "EUR")

    stops = len(segments) - 1

    cabin = "economy"
    passengers_data = getattr(offer, "passengers", [])
    if passengers_data:
        first_pax = passengers_data[0]
        cabin_class_info = getattr(first_pax, "cabin_class_marketing_name", None)
        if cabin_class_info:
            cabin = str(cabin_class_info).upper()

    return FlightResult(
        airline=airline_name,
        flight_number=flight_number,
        origin_airport=Airport(
            iata_code=getattr(origin_airport, "iata_code", "???"),
            name=getattr(origin_airport, "name", "Unknown"),
            city=getattr(origin_airport, "city_name", "Unknown"),
        ),
        destination_airport=Airport(
            iata_code=getattr(dest_airport, "iata_code", "???"),
            name=getattr(dest_airport, "name", "Unknown"),
            city=getattr(dest_airport, "city_name", "Unknown"),
        ),
        departure_time=dep_time,
        arrival_time=arr_time,
        duration_minutes=max(duration_minutes, 0),
        price_eur=total_amount,
        currency=total_currency,
        stops=stops,
        cabin_class=cabin,
        booking_url=None,
    )

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime

from src.cache.manager import TTLCache
from src.config import get_settings
from src.models.flight import Airport, FlightResult

logger = logging.getLogger(__name__)


class RateLimitError(Exception):
    pass


class AmadeusProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self._client_id = settings.amadeus_client_id
        self._client_secret = settings.amadeus_client_secret
        self._cache: TTLCache[list[FlightResult]] = TTLCache(
            default_ttl_seconds=settings.amadeus_ttl
        )

    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None = None,
        adults: int = 1,
        cabin_class: str = "ECONOMY",
    ) -> list[FlightResult]:
        cache_key = (
            f"amadeus:{origin}:{destination}:{departure_date}:{return_date}:{adults}:{cabin_class}"
        )
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        results = await asyncio.get_event_loop().run_in_executor(
            None,
            _blocking_search,
            self._client_id,
            self._client_secret,
            origin,
            destination,
            departure_date,
            return_date,
            adults,
            cabin_class,
        )
        self._cache.set(cache_key, results)
        return results


def _blocking_search(
    client_id: str,
    client_secret: str,
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None,
    adults: int,
    cabin_class: str,
) -> list[FlightResult]:
    try:
        import amadeus  # type: ignore[import-untyped]
    except ImportError as exc:
        logger.error("Amadeus SDK not installed: %s", exc)
        raise

    client = amadeus.Client(
        client_id=client_id,
        client_secret=client_secret,
        log_level="silent",
    )

    params: dict[str, str | int] = {
        "originLocationCode": origin,
        "destinationLocationCode": destination,
        "departureDate": departure_date,
        "adults": adults,
        "max": 20,
    }
    if cabin_class:
        params["travelClass"] = cabin_class
    if return_date:
        params["returnDate"] = return_date

    try:
        response = client.shopping.flight_offers_search.get(**params)
    except amadeus.ClientError as exc:
        status = getattr(exc.response, "status_code", None)
        if status == 429:
            raise RateLimitError("Amadeus API rate limit exceeded") from exc
        raise

    return [_map_offer(offer) for offer in (response.data or []) if offer]


def _map_offer(offer: dict) -> FlightResult:
    itinerary = offer["itineraries"][0]
    segments = itinerary["segments"]
    first_seg = segments[0]
    last_seg = segments[-1]

    dep_time = datetime.fromisoformat(first_seg["departure"]["at"])
    arr_time = datetime.fromisoformat(last_seg["arrival"]["at"])
    duration_minutes = _parse_duration_minutes(itinerary.get("duration", "PT0M"))

    airline = (offer.get("validatingAirlineCodes") or [first_seg.get("carrierCode", "?")])[0]
    flight_number = f"{first_seg.get('carrierCode', '')}{first_seg.get('number', '')}"

    price_info = offer.get("price", {})
    price = float(price_info.get("grandTotal") or price_info.get("total") or 0)
    currency = price_info.get("currency", "EUR")

    origin_iata = first_seg["departure"]["iataCode"]
    dest_iata = last_seg["arrival"]["iataCode"]

    stops = len(segments) - 1

    cabin = _extract_cabin(offer)

    return FlightResult(
        airline=airline,
        flight_number=flight_number,
        origin_airport=Airport(iata_code=origin_iata, name=origin_iata, city=origin_iata),
        destination_airport=Airport(iata_code=dest_iata, name=dest_iata, city=dest_iata),
        departure_time=dep_time,
        arrival_time=arr_time,
        duration_minutes=duration_minutes,
        price_eur=price,
        currency=currency,
        stops=stops,
        cabin_class=cabin,
        booking_url=None,
    )


def _parse_duration_minutes(duration: str) -> int:
    match = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?", duration)
    if not match:
        return 0
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    return hours * 60 + minutes


def _extract_cabin(offer: dict) -> str:
    try:
        pricings = offer.get("travelerPricings", [])
        if pricings:
            fare_details = pricings[0].get("fareDetailsBySegment", [])
            if fare_details:
                return fare_details[0].get("cabin", "ECONOMY")
    except (KeyError, IndexError):
        pass
    return "ECONOMY"

from __future__ import annotations

import logging

import httpx

from src.cache.manager import TTLCache
from src.config import get_settings
from src.models.accommodation import AccommodationResult

logger = logging.getLogger(__name__)

_BASE_URL = "https://serpapi.com/search.json"


class RateLimitError(Exception):
    pass


class GoogleHotelsProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.serpapi_api_key
        self._cache: TTLCache[list[AccommodationResult]] = TTLCache(
            default_ttl_seconds=settings.hotels_ttl
        )

    async def search_hotels(
        self,
        destination: str,
        check_in: str,
        check_out: str,
        adults: int = 2,
    ) -> list[AccommodationResult]:
        cache_key = f"hotels:{destination}:{check_in}:{check_out}:{adults}"
        cached = self._cache.get(cache_key)
        if cached is not None:
            return cached

        params: dict[str, str | int] = {
            "engine": "google_hotels",
            "q": destination,
            "check_in_date": check_in,
            "check_out_date": check_out,
            "currency": "EUR",
            "hl": "es",
            "adults": adults,
            "api_key": self._api_key,
        }

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

        results = _parse_hotels(data)
        self._cache.set(cache_key, results)
        return results


def _parse_price(price_str: str | None) -> float | None:
    if not price_str:
        return None
    stripped = price_str.strip()
    if stripped.startswith("EUR "):
        stripped = stripped[4:]
    stripped = stripped.replace(".", "").replace(",", ".")
    try:
        return float(stripped)
    except ValueError:
        return None


def _parse_hotels(data: dict) -> list[AccommodationResult]:
    results: list[AccommodationResult] = []
    for prop in data.get("properties", []):
        try:
            results.append(_map_property(prop))
        except Exception as exc:
            logger.warning("Skipping malformed hotel property: %s", exc)
    return results


def _map_property(prop: dict) -> AccommodationResult:
    coords = prop.get("gps_coordinates", {})
    rate = prop.get("rate_per_night", {})
    total = prop.get("total_rate", {})

    return AccommodationResult(
        name=prop["name"],
        hotel_class=prop.get("hotel_class"),
        rating=prop.get("overall_rating"),
        price_per_night_eur=_parse_price(rate.get("lowest")),
        total_price_eur=_parse_price(total.get("lowest")),
        accommodation_type=prop.get("type"),
        check_in_time=prop.get("check_in_time"),
        check_out_time=prop.get("check_out_time"),
        latitude=coords.get("latitude"),
        longitude=coords.get("longitude"),
        link=prop.get("link"),
        amenities=prop.get("amenities", []),
    )

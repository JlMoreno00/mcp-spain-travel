from __future__ import annotations

import logging
from datetime import datetime

import httpx

from src.cache.manager import TTLCache
from src.config import get_settings
from src.models.bus import BusResult, BusStation

logger = logging.getLogger(__name__)

_RAPIDAPI_HOST = "flixbus2.p.rapidapi.com"
_BASE_URL = "https://flixbus2.p.rapidapi.com"


def _convert_date(date_iso: str) -> str:
    dt = datetime.strptime(date_iso, "%Y-%m-%d")
    return dt.strftime("%d.%m.%Y")


def _parse_duration_minutes(duration: str) -> int:
    parts = duration.split(":")
    if len(parts) != 2:
        return 0
    try:
        return int(parts[0]) * 60 + int(parts[1])
    except ValueError:
        return 0


def _parse_offset_datetime(s: str) -> datetime:
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.fromisoformat(s[:19])


def _map_station(raw: dict) -> BusStation:
    city = raw.get("city") or {}
    loc = raw.get("location") or {}
    return BusStation(
        name=raw.get("name", ""),
        station_id=str(raw.get("id", "")),
        city_id=str(city.get("id", "")),
        city=city.get("name", ""),
        latitude=loc.get("lat"),
        longitude=loc.get("lon"),
    )


def _map_journey(raw: dict) -> BusResult | None:
    try:
        dep_time = _parse_offset_datetime(raw["dep_offset"])
        arr_time = _parse_offset_datetime(raw["arr_offset"])
        fares = raw.get("fares") or []
        price = float(fares[0]["price"]) if fares else None
        return BusResult(
            operator="FlixBus",
            departure_station=raw.get("dep_name", ""),
            arrival_station=raw.get("arr_name", ""),
            departure_time=dep_time,
            arrival_time=arr_time,
            duration_minutes=_parse_duration_minutes(raw.get("duration", "")),
            price_eur=price,
            currency="EUR",
            changeovers=raw.get("changeovers", 0),
            booking_url=raw.get("deeplink"),
        )
    except Exception as exc:
        logger.warning("Failed to map FlixBus journey: %s", exc)
        return None


class FlixBusProvider:
    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.flixbus_api_key
        self._autocomplete_cache: TTLCache[list[BusStation]] = TTLCache(default_ttl_seconds=86_400)
        self._trips_cache: TTLCache[list[BusResult]] = TTLCache(default_ttl_seconds=1_800)

    def _headers(self) -> dict[str, str]:
        return {
            "x-rapidapi-host": _RAPIDAPI_HOST,
            "x-rapidapi-key": self._api_key,
        }

    async def autocomplete(self, query: str) -> list[BusStation]:
        cache_key = f"flixbus:autocomplete:{query.lower()}"
        cached = self._autocomplete_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{_BASE_URL}/autocomplete",
                    params={"query": query},
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning("FlixBus autocomplete HTTP error (query=%s): %s", query, exc)
            return []
        except Exception as exc:
            logger.warning("FlixBus autocomplete failed (query=%s): %s", query, exc)
            return []

        stations = [_map_station(s) for s in data if isinstance(s, dict)]
        self._autocomplete_cache.set(cache_key, stations)
        return stations

    async def search_trips(
        self,
        from_city_id: str,
        to_city_id: str,
        date: str,
        passengers: int = 1,
    ) -> list[BusResult]:
        flixbus_date = _convert_date(date)
        cache_key = f"flixbus:trips:{from_city_id}:{to_city_id}:{flixbus_date}:{passengers}"
        cached = self._trips_cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"{_BASE_URL}/trips",
                    params={
                        "from_id": from_city_id,
                        "to_id": to_city_id,
                        "date": flixbus_date,
                        "adult": passengers,
                        "currency": "EUR",
                    },
                    headers=self._headers(),
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "FlixBus trips HTTP error (%s→%s %s): %s",
                from_city_id,
                to_city_id,
                flixbus_date,
                exc,
            )
            return []
        except Exception as exc:
            logger.warning(
                "FlixBus trips failed (%s→%s %s): %s",
                from_city_id,
                to_city_id,
                flixbus_date,
                exc,
            )
            return []

        journeys = data.get("journeys", []) if isinstance(data, dict) else []
        results = [r for j in journeys if isinstance(j, dict) for r in [_map_journey(j)] if r]
        self._trips_cache.set(cache_key, results)
        return results

    async def _resolve_city_id(self, city_name: str) -> str | None:
        stations = await self.autocomplete(city_name)
        if not stations:
            return None
        city_lower = city_name.lower()
        for s in stations:
            if s.city.lower() == city_lower:
                return s.city_id
        return stations[0].city_id

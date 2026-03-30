from __future__ import annotations

import logging
from datetime import date as _Date
from typing import Any

from src.providers.flixbus import FlixBusProvider

logger = logging.getLogger(__name__)


async def search_buses(
    origin: str,
    destination: str,
    date: str,
    passengers: int = 1,
) -> dict[str, Any]:
    try:
        travel_date = _Date.fromisoformat(date)
    except ValueError:
        return {
            "error": {
                "code": "INVALID_DATE",
                "message": f"Invalid date format: {date!r}. Use YYYY-MM-DD.",
            }
        }

    if travel_date < _Date.today():
        return {
            "error": {
                "code": "INVALID_DATE",
                "message": "Date must be today or in the future.",
            }
        }

    provider = FlixBusProvider()

    from_city_id = await provider._resolve_city_id(origin)
    if not from_city_id:
        return {
            "error": {
                "code": "UNKNOWN_CITY",
                "message": f"City not found in FlixBus network: {origin!r}",
            }
        }

    to_city_id = await provider._resolve_city_id(destination)
    if not to_city_id:
        return {
            "error": {
                "code": "UNKNOWN_CITY",
                "message": f"City not found in FlixBus network: {destination!r}",
            }
        }

    results = await provider.search_trips(from_city_id, to_city_id, date, passengers)
    return {
        "results": [r.model_dump(mode="json") for r in results],
        "count": len(results),
    }


async def list_bus_stations(city: str) -> dict[str, Any]:
    provider = FlixBusProvider()
    stations = await provider.autocomplete(city)
    return {
        "stations": [s.model_dump() for s in stations],
        "count": len(stations),
    }

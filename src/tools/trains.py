from __future__ import annotations

import asyncio
import logging
from datetime import date as _Date
from typing import Any

from src.providers.ouigo import OUIGOProvider
from src.providers.renfe.ckan import RenfeCKANProvider
from src.providers.renfe.connections import ConnectionFinder
from src.providers.renfe.scraper import search_with_prices as dwr_search

logger = logging.getLogger(__name__)


async def search_trains(
    origin: str,
    destination: str,
    date: str,
    passengers: int = 1,
) -> dict[str, Any]:
    """Combine Renfe GTFS and OUIGO results for a given train route.

    Validates the date, runs both providers concurrently, and gracefully
    degrades if one provider fails (partial=True in the response).

    Returns:
        {"results": [...], "count": int, "partial": bool, "provider_errors": [...]}
        or {"error": {"code": "...", "message": "..."}}
    """
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

    renfe_ckan = RenfeCKANProvider()
    ouigo = OUIGOProvider()

    ouigo_result, dwr_result = await asyncio.gather(
        ouigo.search_trains(origin, destination, date, passengers),
        dwr_search(origin, destination, date),
        return_exceptions=True,
    )

    provider_errors: list[str] = []
    results = []

    if isinstance(ouigo_result, Exception):
        logger.warning(
            "OUIGO search failed (origin=%s, dest=%s): %s", origin, destination, ouigo_result
        )
        provider_errors.append(f"OUIGO: {ouigo_result}")
    elif isinstance(ouigo_result, list):
        results.extend(ouigo_result)

    if isinstance(dwr_result, Exception):
        logger.warning(
            "Renfe DWR scraper failed (origin=%s, dest=%s): %s — falling back to GTFS",
            origin,
            destination,
            dwr_result,
        )
        try:
            gtfs_result = await renfe_ckan.search_trains(origin, destination, date, passengers)
            results.extend(gtfs_result)
            if gtfs_result:
                provider_errors.append(
                    f"Renfe DWR (price scraper unavailable, using GTFS schedules): {dwr_result}"
                )
        except Exception as exc:
            provider_errors.append(f"Renfe: {exc}")
    elif isinstance(dwr_result, list):
        results.extend(dwr_result)
        if not dwr_result:
            try:
                gtfs_result = await renfe_ckan.search_trains(origin, destination, date, passengers)
                results.extend(gtfs_result)
            except Exception as exc:
                provider_errors.append(f"Renfe: {exc}")

    if not results and len(provider_errors) == 2:
        return {
            "error": {
                "code": "ALL_PROVIDERS_DOWN",
                "message": "All train providers are unavailable. Please try again later.",
            }
        }

    connections: list = []
    connections_count = 0
    if len(results) < 3:
        try:
            finder = ConnectionFinder()
            raw_connections = await finder.find_connections(origin, destination, date)
            connections = [c.model_dump(mode="json") for c in raw_connections]
            connections_count = len(connections)
        except Exception as exc:
            logger.warning("Connection search failed for %s→%s: %s", origin, destination, exc)

    if not results and not provider_errors:
        try:
            stations = await renfe_ckan.list_stations()
            origin_lower = origin.lower()
            dest_lower = destination.lower()

            origin_found = any(
                origin_lower in s.code.lower()
                or origin_lower in s.city.lower()
                or origin_lower in s.name.lower()
                for s in stations
            )
            dest_found = any(
                dest_lower in s.code.lower()
                or dest_lower in s.city.lower()
                or dest_lower in s.name.lower()
                for s in stations
            )

            if not origin_found:
                return {
                    "error": {
                        "code": "UNKNOWN_STATION",
                        "message": (
                            f"Station not found: {origin!r}. "
                            "Use a Spanish city name or Renfe station code."
                        ),
                    }
                }
            if not dest_found:
                return {
                    "error": {
                        "code": "UNKNOWN_STATION",
                        "message": (
                            f"Station not found: {destination!r}. "
                            "Use a Spanish city name or Renfe station code."
                        ),
                    }
                }
        except Exception as exc:
            logger.warning("Station validation lookup failed: %s", exc)

    results.sort(key=lambda r: r.departure_time)

    return {
        "results": [r.model_dump(mode="json") for r in results],
        "connections": connections,
        "count": len(results),
        "connections_count": connections_count,
        "partial": len(provider_errors) > 0,
        "provider_errors": provider_errors,
    }


async def list_train_stations(
    city: str | None = None,
    station_type: str = "all",
) -> dict[str, Any]:
    """Return Renfe station catalog filtered by city name and/or service type.

    Stations are cached for 24 hours (file-based).

    Returns:
        {"stations": [...], "count": int}
        or {"error": {"code": "PROVIDER_ERROR", "message": "..."}}
    """
    renfe_ckan = RenfeCKANProvider()
    try:
        stations = await renfe_ckan.list_stations(city=city, station_type=station_type)
    except Exception as exc:
        logger.error("Failed to list stations: %s", exc)
        return {
            "error": {
                "code": "PROVIDER_ERROR",
                "message": f"Failed to fetch stations: {exc}",
            }
        }

    return {
        "stations": [s.model_dump() for s in stations],
        "count": len(stations),
    }

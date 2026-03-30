from __future__ import annotations

import logging
from typing import Any

from fastmcp import FastMCP

from src.config import get_settings
from src.tools.buses import list_bus_stations as _list_bus_stations
from src.tools.buses import search_buses as _search_buses
from src.tools.flights import search_flights as _search_flights
from src.tools.multimodal import compare_travel_options as _compare_travel_options
from src.tools.trains import list_train_stations as _list_train_stations
from src.tools.trains import search_trains as _search_trains

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "Spain Travel Planner",
    instructions=(
        "Multimodal travel search for Spain. "
        "Search trains (Renfe GTFS + OUIGO) and flights (Amadeus GDS) for any Spanish route. "
        "Compare options by price, duration, and CO2 emissions."
    ),
)


@mcp.tool()
async def search_trains(
    origin: str,
    destination: str,
    date: str,
    passengers: int = 1,
) -> dict[str, Any]:
    """Search for train options between two Spanish cities or Renfe station codes.

    Aggregates Renfe GTFS schedules (free, no pricing) and OUIGO prices concurrently.
    Degrades gracefully: if one provider fails, returns the other with partial=true.

    Args:
        origin: Spanish city name or Renfe station code (e.g. "Madrid", "Barcelona", "60000")
        destination: Spanish city name or Renfe station code (e.g. "Sevilla", "Valencia")
        date: Travel date in YYYY-MM-DD format — must be today or a future date
        passengers: Number of passengers (default 1)
    """
    return await _search_trains(origin, destination, date, passengers)


@mcp.tool()
async def search_flights(
    origin: str,
    destination: str,
    departure_date: str,
    return_date: str | None = None,
    adults: int = 1,
    cabin_class: str = "ECONOMY",
) -> dict[str, Any]:
    """Search for flight offers between two Spanish airports via Amadeus GDS.

    Requires SPAIN_TRAVEL_AMADEUS_CLIENT_ID and SPAIN_TRAVEL_AMADEUS_CLIENT_SECRET env vars.

    Args:
        origin: IATA airport code (e.g. "MAD" Madrid, "BCN" Barcelona, "SVQ" Sevilla, "VLC" Valencia)
        destination: IATA airport code (e.g. "AGP" Malaga, "BIO" Bilbao, "GRX" Granada)
        departure_date: Departure date in YYYY-MM-DD format — must be today or future
        return_date: Return date in YYYY-MM-DD for round-trip (optional)
        adults: Number of adult passengers (default 1)
        cabin_class: ECONOMY (default), PREMIUM_ECONOMY, BUSINESS, or FIRST
    """
    return await _search_flights(
        origin, destination, departure_date, return_date, adults, cabin_class
    )


@mcp.tool()
async def compare_travel_options(
    origin: str,
    destination: str,
    date: str,
    passengers: int = 1,
) -> dict[str, Any]:
    """Compare train and flight options side-by-side for a Spanish origin-destination pair.

    Runs train and flight searches concurrently. Includes CO2 estimates per passenger
    (train: 14 g/km, flight: 255 g/km). Highlights cheapest, fastest, and greenest options.
    Accepts city names or IATA codes — auto-converts known cities (e.g. "Madrid" → "MAD").

    Args:
        origin: City name (e.g. "Madrid", "Barcelona") or IATA code (e.g. "MAD", "BCN")
        destination: City name or IATA code for the destination
        date: Travel date in YYYY-MM-DD format — must be today or future
        passengers: Number of passengers (default 1)
    """
    return await _compare_travel_options(origin, destination, date, passengers)


@mcp.tool()
async def search_buses(
    origin: str,
    destination: str,
    date: str,
    passengers: int = 1,
) -> dict[str, Any]:
    """Search for bus routes in Spain via FlixBus.

    Requires SPAIN_TRAVEL_FLIXBUS_API_KEY env var (RapidAPI key for flixbus2.p.rapidapi.com).

    Args:
        origin: Spanish city name (e.g. "Madrid", "Barcelona", "Sevilla")
        destination: Spanish city name
        date: Travel date in YYYY-MM-DD format — must be today or future
        passengers: Number of passengers (default 1)
    """
    return await _search_buses(origin, destination, date, passengers)


@mcp.tool()
async def list_bus_stations(city: str) -> dict[str, Any]:
    """Find FlixBus bus stations in a Spanish city.

    Args:
        city: Spanish city name to search for bus stations (e.g. "Madrid", "Barcelona")
    """
    return await _list_bus_stations(city)


@mcp.tool()
async def list_train_stations(
    city: str | None = None,
    station_type: str = "all",
) -> dict[str, Any]:
    """List Spanish Renfe train stations, optionally filtered by city name or service type.

    Results are cached for 24 hours. Use this to discover valid station names and codes
    before calling search_trains.

    Args:
        city: Optional city name filter — case-insensitive partial match (e.g. "Madrid", "Seville")
        station_type: Service filter — "all" (default), "cercanias", "feve", or "ld"
    """
    return await _list_train_stations(city, station_type)


def main() -> None:
    settings = get_settings()
    logger.info(
        "Starting Spain Travel Planner MCP (%s on %s:%s)",
        settings.transport,
        settings.host,
        settings.port,
    )
    if settings.transport == "stdio":
        mcp.run()
    else:
        mcp.run(transport=settings.transport, host=settings.host, port=settings.port)

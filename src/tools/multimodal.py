from __future__ import annotations

import asyncio
import logging
import re
from datetime import date as _Date
from datetime import datetime
from typing import Any

from src.models.common import TravelComparison, TravelMode, TravelOption
from src.tools.buses import search_buses
from src.tools.flights import search_flights
from src.tools.trains import search_trains

logger = logging.getLogger(__name__)

_CO2_TRAIN_KG_PER_KM = 0.014
_CO2_FLIGHT_KG_PER_KM = 0.255
_CO2_BUS_KG_PER_KM = 0.027

_DISTANCES_KM: dict[frozenset[str], int] = {
    frozenset({"madrid", "barcelona"}): 620,
    frozenset({"madrid", "valencia"}): 355,
    frozenset({"madrid", "sevilla"}): 530,
    frozenset({"madrid", "bilbao"}): 395,
    frozenset({"madrid", "malaga"}): 528,
    frozenset({"madrid", "zaragoza"}): 322,
    frozenset({"madrid", "alicante"}): 420,
    frozenset({"madrid", "granada"}): 430,
    frozenset({"madrid", "valladolid"}): 190,
    frozenset({"madrid", "burgos"}): 240,
    frozenset({"madrid", "oviedo"}): 440,
    frozenset({"madrid", "cordoba"}): 400,
    frozenset({"madrid", "pamplona"}): 405,
    frozenset({"madrid", "san sebastian"}): 470,
    frozenset({"madrid", "santiago"}): 630,
    frozenset({"madrid", "santander"}): 390,
    frozenset({"barcelona", "valencia"}): 350,
    frozenset({"barcelona", "zaragoza"}): 296,
    frozenset({"barcelona", "bilbao"}): 620,
    frozenset({"barcelona", "malaga"}): 1080,
    frozenset({"barcelona", "sevilla"}): 1000,
    frozenset({"barcelona", "granada"}): 1000,
    frozenset({"sevilla", "malaga"}): 210,
    frozenset({"sevilla", "cordoba"}): 145,
    frozenset({"sevilla", "granada"}): 250,
    frozenset({"valencia", "alicante"}): 165,
    frozenset({"valencia", "zaragoza"}): 320,
}
_DEFAULT_DISTANCE_KM = 500

_CITY_TO_IATA: dict[str, str] = {
    "madrid": "MAD",
    "barcelona": "BCN",
    "sevilla": "SVQ",
    "seville": "SVQ",
    "valencia": "VLC",
    "bilbao": "BIO",
    "malaga": "AGP",
    "granada": "GRX",
    "alicante": "ALC",
    "palma": "PMI",
    "tenerife": "TFN",
    "gran canaria": "LPA",
    "las palmas": "LPA",
    "ibiza": "IBZ",
    "menorca": "MAH",
    "fuerteventura": "FUE",
    "lanzarote": "ACE",
    "santiago": "SCQ",
    "santiago de compostela": "SCQ",
    "valladolid": "VLL",
    "san sebastian": "EAS",
    "donostia": "EAS",
    "oviedo": "OVD",
    "asturias": "OVD",
    "vigo": "VGO",
    "almeria": "LEI",
    "murcia": "RMU",
    "pamplona": "PNA",
    "santander": "SDR",
    "zaragoza": "ZAZ",
    "cordoba": "ODB",
}

_IATA_RE = re.compile(r"^[A-Z]{3}$")


def _to_iata(location: str) -> str:
    if _IATA_RE.match(location):
        return location
    return _CITY_TO_IATA.get(location.lower(), location.upper()[:3])


def _get_distance_km(origin: str, destination: str) -> int:
    key = frozenset({origin.lower(), destination.lower()})
    return _DISTANCES_KM.get(key, _DEFAULT_DISTANCE_KM)


def _co2_kg(mode: str, distance_km: int, passengers: int) -> float:
    if mode == "flight":
        factor = _CO2_FLIGHT_KG_PER_KM
    elif mode == "bus":
        factor = _CO2_BUS_KG_PER_KM
    else:
        factor = _CO2_TRAIN_KG_PER_KM
    return round(factor * distance_km * passengers, 2)


async def compare_travel_options(
    origin: str,
    destination: str,
    date: str,
    passengers: int = 1,
) -> dict[str, Any]:
    """Compare trains and flights side-by-side for a Spanish city pair.

    Accepts city names (e.g. "Madrid") or IATA codes (e.g. "MAD").
    Adds CO2 estimates: train=14g/km/pax, flight=255g/km/pax.

    Returns:
        TravelComparison dict with options[], cheapest, fastest, greenest, partial
        or {"error": {"code": "INVALID_DATE|ALL_PROVIDERS_DOWN", "message": "..."}}
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

    distance_km = _get_distance_km(origin, destination)
    origin_iata = _to_iata(origin)
    dest_iata = _to_iata(destination)

    train_resp, flight_resp, bus_resp = await asyncio.gather(
        search_trains(origin, destination, date, passengers),
        search_flights(origin_iata, dest_iata, date, adults=passengers),
        search_buses(origin, destination, date, passengers),
        return_exceptions=True,
    )

    options: list[TravelOption] = []
    missing_modes: list[str] = []
    provider_errors: list[dict[str, str]] = []

    if isinstance(train_resp, Exception):
        logger.warning("Train search raised exception in compare: %s", train_resp)
        missing_modes.append("train")
        provider_errors.append({"mode": "train", "code": "EXCEPTION", "message": str(train_resp)})
    elif isinstance(train_resp, dict) and "error" in train_resp:
        err = train_resp["error"]
        logger.info("Train search returned error in compare: %s", err.get("code"))
        missing_modes.append("train")
        provider_errors.append(
            {
                "mode": "train",
                "code": err.get("code", "UNKNOWN"),
                "message": err.get("message", ""),
            }
        )
    elif isinstance(train_resp, dict):
        co2 = _co2_kg("train", distance_km, passengers)
        for r in train_resp.get("results", []):
            try:
                options.append(
                    TravelOption(
                        mode=TravelMode.TRAIN,
                        operator=r["operator"],
                        departure_time=datetime.fromisoformat(r["departure_time"]),
                        arrival_time=datetime.fromisoformat(r["arrival_time"]),
                        duration_minutes=r["duration_minutes"],
                        price_eur=r.get("price_eur"),
                        co2_kg=co2,
                        booking_url=r.get("booking_url"),
                    )
                )
            except Exception as exc:
                logger.warning("Skipping malformed train result: %s", exc)

    if isinstance(flight_resp, Exception):
        logger.warning("Flight search raised exception in compare: %s", flight_resp)
        missing_modes.append("flight")
        provider_errors.append(
            {"mode": "flight", "code": "EXCEPTION", "message": str(flight_resp)}
        )
    elif isinstance(flight_resp, dict) and "error" in flight_resp:
        err = flight_resp["error"]
        logger.info("Flight search returned error in compare: %s", err.get("code"))
        missing_modes.append("flight")
        provider_errors.append(
            {
                "mode": "flight",
                "code": err.get("code", "UNKNOWN"),
                "message": err.get("message", ""),
            }
        )
    elif isinstance(flight_resp, dict):
        co2 = _co2_kg("flight", distance_km, passengers)
        for r in flight_resp.get("results", []):
            try:
                options.append(
                    TravelOption(
                        mode=TravelMode.FLIGHT,
                        operator=r["airline"],
                        departure_time=datetime.fromisoformat(r["departure_time"]),
                        arrival_time=datetime.fromisoformat(r["arrival_time"]),
                        duration_minutes=r["duration_minutes"],
                        price_eur=r.get("price_eur"),
                        co2_kg=co2,
                        booking_url=r.get("booking_url"),
                    )
                )
            except Exception as exc:
                logger.warning("Skipping malformed flight result: %s", exc)

    if isinstance(bus_resp, Exception):
        logger.warning("Bus search raised exception in compare: %s", bus_resp)
        missing_modes.append("bus")
        provider_errors.append({"mode": "bus", "code": "EXCEPTION", "message": str(bus_resp)})
    elif isinstance(bus_resp, dict) and "error" in bus_resp:
        err = bus_resp["error"]
        logger.info("Bus search returned error in compare: %s", err.get("code"))
        missing_modes.append("bus")
        provider_errors.append(
            {
                "mode": "bus",
                "code": err.get("code", "UNKNOWN"),
                "message": err.get("message", ""),
            }
        )
    elif isinstance(bus_resp, dict):
        co2 = _co2_kg("bus", distance_km, passengers)
        for r in bus_resp.get("results", []):
            try:
                options.append(
                    TravelOption(
                        mode=TravelMode.BUS,
                        operator=r["operator"],
                        departure_time=datetime.fromisoformat(r["departure_time"]),
                        arrival_time=datetime.fromisoformat(r["arrival_time"]),
                        duration_minutes=r["duration_minutes"],
                        price_eur=r.get("price_eur"),
                        co2_kg=co2,
                        booking_url=r.get("booking_url"),
                    )
                )
            except Exception as exc:
                logger.warning("Skipping malformed bus result: %s", exc)

    if not options and len(missing_modes) == 3:
        return {
            "error": {
                "code": "ALL_PROVIDERS_DOWN",
                "message": "All travel providers are unavailable. Please try again later.",
            }
        }

    comparison = TravelComparison(
        origin=origin,
        destination=destination,
        date=date,
        options=options,
        partial=len(missing_modes) > 0,
        missing_modes=missing_modes,
    )
    result = comparison.model_dump(mode="json")
    if provider_errors:
        result["provider_errors"] = provider_errors
    return result

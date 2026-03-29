from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response

from src.providers.serpapi import (
    RateLimitError,
    SerpApiProvider,
    _map_flight_group,
    _parse_flights,
)


def _make_flight_group(
    dep_iata="MAD",
    arr_iata="BCN",
    dep_time="2099-06-15 09:00",
    arr_time="2099-06-15 10:15",
    price=103,
    airline="Iberia",
    flight_number="IB 1234",
    duration=75,
    stops=0,
):
    flights = [
        {
            "departure_airport": {"name": f"{dep_iata} Airport", "id": dep_iata, "time": dep_time},
            "arrival_airport": {"name": f"{arr_iata} Airport", "id": arr_iata, "time": arr_time},
            "airline": airline,
            "flight_number": flight_number,
            "travel_class": "Economy",
            "duration": duration,
        }
    ]
    if stops > 0:
        flights.append(
            {
                "departure_airport": {"name": "Madrid", "id": "MAD", "time": "2099-06-15 12:00"},
                "arrival_airport": {
                    "name": f"{arr_iata} Airport",
                    "id": arr_iata,
                    "time": arr_time,
                },
                "airline": airline,
                "flight_number": "IB 9999",
                "travel_class": "Economy",
                "duration": 60,
            }
        )
    return {"flights": flights, "price": price, "total_duration": duration}


def _make_serpapi_response(best=None, other=None):
    return {
        "search_metadata": {"status": "Success"},
        "best_flights": best or [],
        "other_flights": other or [],
    }


class TestMapFlightGroup:
    def test_maps_basic_flight(self):
        group = _make_flight_group()
        result = _map_flight_group(group)
        assert result.airline == "Iberia"
        assert result.origin_airport.iata_code == "MAD"
        assert result.destination_airport.iata_code == "BCN"
        assert result.duration_minutes == 75
        assert result.price_eur == pytest.approx(103.0)
        assert result.stops == 0

    def test_maps_flight_with_stops(self):
        group = _make_flight_group(stops=1, duration=180)
        result = _map_flight_group(group)
        assert result.stops == 1


class TestParseFlights:
    def test_parses_best_and_other_flights(self):
        data = _make_serpapi_response(
            best=[_make_flight_group(price=90)],
            other=[_make_flight_group(price=150), _make_flight_group(price=200)],
        )
        results = _parse_flights(data)
        assert len(results) == 3
        assert results[0].price_eur == pytest.approx(90.0)

    def test_empty_response_returns_empty(self):
        data = _make_serpapi_response()
        assert _parse_flights(data) == []

    def test_skips_malformed_entries(self):
        data = _make_serpapi_response(best=[{"flights": []}])
        results = _parse_flights(data)
        assert len(results) == 0


class TestSerpApiProvider:
    @respx.mock
    async def test_successful_search(self, mock_env):
        respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(200, json=_make_serpapi_response(best=[_make_flight_group()]))
        )
        provider = SerpApiProvider()
        results = await provider.search_flights("MAD", "BCN", "2099-06-15")
        assert len(results) == 1
        assert results[0].airline == "Iberia"

    @respx.mock
    async def test_rate_limit_429_raises(self, mock_env):
        respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(429, text="Rate limit")
        )
        provider = SerpApiProvider()
        with pytest.raises(RateLimitError):
            await provider.search_flights("MAD", "BCN", "2099-06-15")

    @respx.mock
    async def test_api_error_raises_runtime(self, mock_env):
        respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(200, json={"error": "Invalid API key"})
        )
        provider = SerpApiProvider()
        with pytest.raises(RuntimeError, match="Invalid API key"):
            await provider.search_flights("MAD", "BCN", "2099-06-15")

    @respx.mock
    async def test_caches_on_second_call(self, mock_env):
        route = respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(200, json=_make_serpapi_response(best=[_make_flight_group()]))
        )
        provider = SerpApiProvider()
        await provider.search_flights("MAD", "BCN", "2099-06-15")
        await provider.search_flights("MAD", "BCN", "2099-06-15")
        assert route.call_count == 1

    @respx.mock
    async def test_round_trip_uses_type_1(self, mock_env):
        route = respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(200, json=_make_serpapi_response())
        )
        provider = SerpApiProvider()
        await provider.search_flights("MAD", "BCN", "2099-06-15", return_date="2099-06-22")
        request = route.calls[0].request
        assert "type=1" in str(request.url)
        assert "return_date=2099-06-22" in str(request.url)

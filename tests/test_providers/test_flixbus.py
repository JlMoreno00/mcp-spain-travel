from __future__ import annotations

import pytest
import respx
from httpx import Response

from src.providers.flixbus import (
    FlixBusProvider,
    _convert_date,
    _map_journey,
    _map_station,
    _parse_duration_minutes,
)


def _autocomplete_payload():
    return [
        {
            "name": "Madrid Atocha Train Station",
            "id": "station-1",
            "city": {"name": "Madrid", "id": "city-40", "slug": "madrid"},
            "location": {"lat": 40.4065, "lon": -3.6892},
            "is_train": False,
        },
        {
            "name": "Madrid Airport",
            "id": "station-2",
            "city": {"name": "Madrid", "id": "city-40", "slug": "madrid"},
            "location": {"lat": 40.472, "lon": -3.562},
            "is_train": False,
        },
    ]


def _trips_payload():
    return {
        "journeys": [
            {
                "dep_offset": "2099-06-15T06:09:00.000",
                "arr_offset": "2099-06-15T09:25:00.000",
                "dep_name": "Madrid Atocha Train Station",
                "arr_name": "Barcelona (Sants)",
                "duration": "03:16",
                "changeovers": 0,
                "deeplink": "https://shop.flixbus.com/search",
                "fares": [{"price": 56.35, "currency": "EUR"}],
            }
        ]
    }


class TestParseDurationMinutes:
    def test_standard_duration(self):
        assert _parse_duration_minutes("03:16") == 196

    def test_zero_duration(self):
        assert _parse_duration_minutes("00:00") == 0

    def test_single_digit_hours(self):
        assert _parse_duration_minutes("1:30") == 90

    def test_malformed_returns_zero(self):
        assert _parse_duration_minutes("invalid") == 0

    def test_empty_returns_zero(self):
        assert _parse_duration_minutes("") == 0


class TestConvertDate:
    def test_converts_iso_to_flixbus_format(self):
        assert _convert_date("2026-05-14") == "14.05.2026"

    def test_converts_another_date(self):
        assert _convert_date("2099-06-15") == "15.06.2099"


class TestMapStation:
    def test_maps_all_fields(self):
        raw = _autocomplete_payload()[0]
        station = _map_station(raw)
        assert station.name == "Madrid Atocha Train Station"
        assert station.station_id == "station-1"
        assert station.city_id == "city-40"
        assert station.city == "Madrid"
        assert station.latitude == pytest.approx(40.4065)
        assert station.longitude == pytest.approx(-3.6892)

    def test_missing_location_uses_none(self):
        raw = {"name": "Bus Stop", "id": "s1", "city": {"name": "X", "id": "c1"}}
        station = _map_station(raw)
        assert station.latitude is None
        assert station.longitude is None


class TestMapJourney:
    def test_maps_all_fields(self):
        raw = _trips_payload()["journeys"][0]
        result = _map_journey(raw)
        assert result is not None
        assert result.operator == "FlixBus"
        assert result.departure_station == "Madrid Atocha Train Station"
        assert result.arrival_station == "Barcelona (Sants)"
        assert result.duration_minutes == 196
        assert result.price_eur == pytest.approx(56.35)
        assert result.changeovers == 0
        assert result.booking_url == "https://shop.flixbus.com/search"

    def test_departure_time_parsed(self):
        raw = _trips_payload()["journeys"][0]
        result = _map_journey(raw)
        assert result is not None
        assert result.departure_time.hour == 6
        assert result.departure_time.minute == 9

    def test_arrival_time_parsed(self):
        raw = _trips_payload()["journeys"][0]
        result = _map_journey(raw)
        assert result is not None
        assert result.arrival_time.hour == 9
        assert result.arrival_time.minute == 25

    def test_no_fares_gives_none_price(self):
        raw = {**_trips_payload()["journeys"][0], "fares": []}
        result = _map_journey(raw)
        assert result is not None
        assert result.price_eur is None

    def test_malformed_returns_none(self):
        result = _map_journey({"dep_offset": "bad-date"})
        assert result is None


class TestFlixBusProviderAutocomplete:
    @respx.mock
    async def test_returns_stations_on_success(self, mock_env):
        respx.get("https://flixbus2.p.rapidapi.com/autocomplete").mock(
            return_value=Response(200, json=_autocomplete_payload())
        )
        provider = FlixBusProvider()
        stations = await provider.autocomplete("Madrid")
        assert len(stations) == 2
        assert stations[0].city == "Madrid"

    @respx.mock
    async def test_caches_on_second_call(self, mock_env):
        route = respx.get("https://flixbus2.p.rapidapi.com/autocomplete").mock(
            return_value=Response(200, json=_autocomplete_payload())
        )
        provider = FlixBusProvider()
        await provider.autocomplete("Madrid")
        await provider.autocomplete("Madrid")
        assert route.call_count == 1

    @respx.mock
    async def test_http_error_returns_empty(self, mock_env):
        respx.get("https://flixbus2.p.rapidapi.com/autocomplete").mock(
            return_value=Response(429, text="Rate limit")
        )
        provider = FlixBusProvider()
        result = await provider.autocomplete("Madrid")
        assert result == []

    @respx.mock
    async def test_network_error_returns_empty(self, mock_env):
        import httpx

        respx.get("https://flixbus2.p.rapidapi.com/autocomplete").mock(
            side_effect=httpx.ConnectError("connection failed")
        )
        provider = FlixBusProvider()
        result = await provider.autocomplete("Madrid")
        assert result == []


class TestFlixBusProviderSearchTrips:
    @respx.mock
    async def test_returns_results_on_success(self, mock_env):
        respx.get("https://flixbus2.p.rapidapi.com/trips").mock(
            return_value=Response(200, json=_trips_payload())
        )
        provider = FlixBusProvider()
        results = await provider.search_trips("city-40", "city-71", "2099-06-15", 1)
        assert len(results) == 1
        assert results[0].operator == "FlixBus"
        assert results[0].duration_minutes == 196

    @respx.mock
    async def test_caches_on_second_call(self, mock_env):
        route = respx.get("https://flixbus2.p.rapidapi.com/trips").mock(
            return_value=Response(200, json=_trips_payload())
        )
        provider = FlixBusProvider()
        await provider.search_trips("city-40", "city-71", "2099-06-15")
        await provider.search_trips("city-40", "city-71", "2099-06-15")
        assert route.call_count == 1

    @respx.mock
    async def test_http_error_returns_empty(self, mock_env):
        respx.get("https://flixbus2.p.rapidapi.com/trips").mock(
            return_value=Response(503, text="Service Unavailable")
        )
        provider = FlixBusProvider()
        result = await provider.search_trips("city-40", "city-71", "2099-06-15")
        assert result == []

    @respx.mock
    async def test_date_converted_to_flixbus_format(self, mock_env):
        route = respx.get("https://flixbus2.p.rapidapi.com/trips").mock(
            return_value=Response(200, json=_trips_payload())
        )
        provider = FlixBusProvider()
        await provider.search_trips("city-40", "city-71", "2099-06-15")
        request = route.calls[0].request
        assert "15.06.2099" in str(request.url)


class TestFlixBusProviderResolveCityId:
    @respx.mock
    async def test_returns_exact_city_match(self, mock_env):
        respx.get("https://flixbus2.p.rapidapi.com/autocomplete").mock(
            return_value=Response(200, json=_autocomplete_payload())
        )
        provider = FlixBusProvider()
        city_id = await provider._resolve_city_id("Madrid")
        assert city_id == "city-40"

    @respx.mock
    async def test_returns_first_result_when_no_exact_match(self, mock_env):
        respx.get("https://flixbus2.p.rapidapi.com/autocomplete").mock(
            return_value=Response(200, json=_autocomplete_payload())
        )
        provider = FlixBusProvider()
        city_id = await provider._resolve_city_id("Madri")
        assert city_id == "city-40"

    @respx.mock
    async def test_returns_none_when_no_stations(self, mock_env):
        respx.get("https://flixbus2.p.rapidapi.com/autocomplete").mock(
            return_value=Response(200, json=[])
        )
        provider = FlixBusProvider()
        city_id = await provider._resolve_city_id("Nowhere")
        assert city_id is None

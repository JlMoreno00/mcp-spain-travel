from __future__ import annotations

import pytest
import respx
from httpx import Response

from src.providers.google_hotels import (
    RateLimitError,
    GoogleHotelsProvider,
    _parse_price,
    _parse_hotels,
    _map_property,
)


def _make_property(
    name="Hotel Dorsett Madrid",
    hotel_class="Hotel de 4 estrellas",
    rating=4.2,
    price_per_night="EUR 64",
    total_price="EUR 128",
    accommodation_type="Hotel",
    check_in_time="3:00 PM",
    check_out_time="12:00 PM",
    latitude=40.42,
    longitude=-3.70,
    link="https://www.google.com/travel/hotels/entity/example",
    amenities=None,
):
    return {
        "name": name,
        "hotel_class": hotel_class,
        "overall_rating": rating,
        "rate_per_night": {"lowest": price_per_night},
        "total_rate": {"lowest": total_price},
        "type": accommodation_type,
        "check_in_time": check_in_time,
        "check_out_time": check_out_time,
        "gps_coordinates": {"latitude": latitude, "longitude": longitude},
        "link": link,
        "amenities": amenities or ["WiFi", "Pool"],
    }


def _make_hotels_response(properties=None):
    return {
        "search_metadata": {"status": "Success"},
        "properties": properties or [],
    }


class TestParsePrice:
    def test_simple_price(self):
        assert _parse_price("EUR 64") == pytest.approx(64.0)

    def test_spanish_thousands_separator(self):
        assert _parse_price("EUR 1.050") == pytest.approx(1050.0)

    def test_none_input(self):
        assert _parse_price(None) is None

    def test_empty_string(self):
        assert _parse_price("") is None

    def test_price_without_eur_prefix(self):
        assert _parse_price("128") == pytest.approx(128.0)

    def test_price_with_decimal_comma(self):
        assert _parse_price("EUR 64,50") == pytest.approx(64.50)


class TestMapProperty:
    def test_maps_full_property(self):
        prop = _make_property()
        result = _map_property(prop)
        assert result.name == "Hotel Dorsett Madrid"
        assert result.hotel_class == "Hotel de 4 estrellas"
        assert result.rating == pytest.approx(4.2)
        assert result.price_per_night_eur == pytest.approx(64.0)
        assert result.total_price_eur == pytest.approx(128.0)
        assert result.accommodation_type == "Hotel"
        assert result.check_in_time == "3:00 PM"
        assert result.check_out_time == "12:00 PM"
        assert result.latitude == pytest.approx(40.42)
        assert result.longitude == pytest.approx(-3.70)
        assert result.link == "https://www.google.com/travel/hotels/entity/example"
        assert "WiFi" in result.amenities

    def test_maps_missing_optional_fields(self):
        prop = {"name": "Minimal Hotel"}
        result = _map_property(prop)
        assert result.name == "Minimal Hotel"
        assert result.hotel_class is None
        assert result.rating is None
        assert result.price_per_night_eur is None
        assert result.total_price_eur is None
        assert result.latitude is None
        assert result.longitude is None
        assert result.amenities == []

    def test_maps_missing_rate_per_night(self):
        prop = _make_property()
        del prop["rate_per_night"]
        result = _map_property(prop)
        assert result.price_per_night_eur is None


class TestParseHotels:
    def test_parses_multiple_properties(self):
        data = _make_hotels_response(
            [
                _make_property(name="Hotel A", price_per_night="EUR 80"),
                _make_property(name="Hotel B", price_per_night="EUR 120"),
            ]
        )
        results = _parse_hotels(data)
        assert len(results) == 2
        assert results[0].name == "Hotel A"
        assert results[1].name == "Hotel B"

    def test_empty_response_returns_empty(self):
        data = _make_hotels_response()
        assert _parse_hotels(data) == []

    def test_skips_malformed_entries(self):
        data = _make_hotels_response([{}, _make_property(name="Good Hotel")])
        results = _parse_hotels(data)
        assert len(results) == 1
        assert results[0].name == "Good Hotel"


class TestGoogleHotelsProvider:
    @respx.mock
    async def test_successful_search(self, mock_env):
        respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(200, json=_make_hotels_response([_make_property()]))
        )
        provider = GoogleHotelsProvider()
        results = await provider.search_hotels("Madrid", "2099-06-15", "2099-06-17")
        assert len(results) == 1
        assert results[0].name == "Hotel Dorsett Madrid"
        assert results[0].price_per_night_eur == pytest.approx(64.0)

    @respx.mock
    async def test_rate_limit_429_raises(self, mock_env):
        respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(429, text="Rate limit")
        )
        provider = GoogleHotelsProvider()
        with pytest.raises(RateLimitError):
            await provider.search_hotels("Madrid", "2099-06-15", "2099-06-17")

    @respx.mock
    async def test_api_error_raises_runtime(self, mock_env):
        respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(200, json={"error": "Invalid API key"})
        )
        provider = GoogleHotelsProvider()
        with pytest.raises(RuntimeError, match="Invalid API key"):
            await provider.search_hotels("Madrid", "2099-06-15", "2099-06-17")

    @respx.mock
    async def test_non_200_status_raises_runtime(self, mock_env):
        respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(500, text="Internal Server Error")
        )
        provider = GoogleHotelsProvider()
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await provider.search_hotels("Madrid", "2099-06-15", "2099-06-17")

    @respx.mock
    async def test_caches_on_second_call(self, mock_env):
        route = respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(200, json=_make_hotels_response([_make_property()]))
        )
        provider = GoogleHotelsProvider()
        await provider.search_hotels("Madrid", "2099-06-15", "2099-06-17")
        await provider.search_hotels("Madrid", "2099-06-15", "2099-06-17")
        assert route.call_count == 1

    @respx.mock
    async def test_different_params_not_cached(self, mock_env):
        route = respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(200, json=_make_hotels_response([_make_property()]))
        )
        provider = GoogleHotelsProvider()
        await provider.search_hotels("Madrid", "2099-06-15", "2099-06-17")
        await provider.search_hotels("Barcelona", "2099-06-15", "2099-06-17")
        assert route.call_count == 2

    @respx.mock
    async def test_passes_adults_param(self, mock_env):
        route = respx.get("https://serpapi.com/search.json").mock(
            return_value=Response(200, json=_make_hotels_response())
        )
        provider = GoogleHotelsProvider()
        await provider.search_hotels("Madrid", "2099-06-15", "2099-06-17", adults=3)
        request = route.calls[0].request
        assert "adults=3" in str(request.url)

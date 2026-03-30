from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.tools.buses import list_bus_stations, search_buses


def _future_date() -> str:
    return "2099-06-15"


def _mock_city_id(city_id: str) -> AsyncMock:
    return AsyncMock(return_value=city_id)


class TestSearchBusesValidation:
    async def test_past_date_returns_invalid_date_error(self):
        result = await search_buses("Madrid", "Barcelona", "2020-01-01")
        assert result["error"]["code"] == "INVALID_DATE"

    async def test_bad_date_format_returns_invalid_date_error(self):
        result = await search_buses("Madrid", "Barcelona", "not-a-date")
        assert result["error"]["code"] == "INVALID_DATE"


class TestSearchBusesHappyPath:
    async def test_returns_results_on_success(self, sample_bus_result):
        with patch("src.tools.buses.FlixBusProvider") as MockProvider:
            instance = MockProvider.return_value
            instance._resolve_city_id = AsyncMock(side_effect=["city-40", "city-71"])
            instance.search_trips = AsyncMock(return_value=[sample_bus_result])

            result = await search_buses("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        assert result["count"] == 1
        assert result["results"][0]["operator"] == "FlixBus"
        assert result["results"][0]["duration_minutes"] == 196

    async def test_returns_empty_results_when_no_trips(self):
        with patch("src.tools.buses.FlixBusProvider") as MockProvider:
            instance = MockProvider.return_value
            instance._resolve_city_id = AsyncMock(side_effect=["city-40", "city-71"])
            instance.search_trips = AsyncMock(return_value=[])

            result = await search_buses("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        assert result["count"] == 0
        assert result["results"] == []


class TestSearchBusesUnknownCity:
    async def test_unknown_origin_returns_error(self):
        with patch("src.tools.buses.FlixBusProvider") as MockProvider:
            instance = MockProvider.return_value
            instance._resolve_city_id = AsyncMock(return_value=None)

            result = await search_buses("NonExistentCity", "Barcelona", _future_date())

        assert result["error"]["code"] == "UNKNOWN_CITY"
        assert "NonExistentCity" in result["error"]["message"]

    async def test_unknown_destination_returns_error(self):
        with patch("src.tools.buses.FlixBusProvider") as MockProvider:
            instance = MockProvider.return_value
            instance._resolve_city_id = AsyncMock(side_effect=["city-40", None])

            result = await search_buses("Madrid", "NonExistentCity", _future_date())

        assert result["error"]["code"] == "UNKNOWN_CITY"
        assert "NonExistentCity" in result["error"]["message"]


class TestListBusStations:
    async def test_returns_stations_list(self):
        from src.models.bus import BusStation

        station = BusStation(
            name="Madrid Atocha",
            city_id="city-40",
            station_id="station-1",
            city="Madrid",
            latitude=40.4065,
            longitude=-3.6892,
        )
        with patch("src.tools.buses.FlixBusProvider") as MockProvider:
            instance = MockProvider.return_value
            instance.autocomplete = AsyncMock(return_value=[station])

            result = await list_bus_stations("Madrid")

        assert result["count"] == 1
        assert result["stations"][0]["city"] == "Madrid"

    async def test_returns_empty_for_unknown_city(self):
        with patch("src.tools.buses.FlixBusProvider") as MockProvider:
            instance = MockProvider.return_value
            instance.autocomplete = AsyncMock(return_value=[])

            result = await list_bus_stations("Nowhere")

        assert result["count"] == 0
        assert result["stations"] == []

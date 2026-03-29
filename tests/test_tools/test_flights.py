from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.providers.serpapi import RateLimitError
from src.tools.flights import search_flights


def _future_date() -> str:
    return "2099-06-15"


class TestSearchFlightsValidation:
    async def test_invalid_iata_origin_returns_error(self):
        result = await search_flights("MADRID", "BCN", _future_date())
        assert result["error"]["code"] == "INVALID_IATA"
        assert "MADRID" in result["error"]["message"]

    async def test_invalid_iata_destination_returns_error(self):
        result = await search_flights("MAD", "BARCELONA", _future_date())
        assert result["error"]["code"] == "INVALID_IATA"

    async def test_lowercase_iata_is_normalized(self, sample_flight_result):
        mock_provider = AsyncMock()
        mock_provider.search_flights.return_value = [sample_flight_result]

        with patch("src.tools.flights.SerpApiProvider", return_value=mock_provider):
            result = await search_flights("mad", "bcn", _future_date())

        assert "error" not in result
        mock_provider.search_flights.assert_called_once()
        call_kwargs = mock_provider.search_flights.call_args.kwargs
        assert call_kwargs["origin"] == "MAD"
        assert call_kwargs["destination"] == "BCN"

    async def test_past_departure_date_returns_invalid_date_error(self):
        result = await search_flights("MAD", "BCN", "2020-01-01")
        assert result["error"]["code"] == "INVALID_DATE"

    async def test_bad_date_format_returns_invalid_date_error(self):
        result = await search_flights("MAD", "BCN", "15/06/2099")
        assert result["error"]["code"] == "INVALID_DATE"

    async def test_single_char_iata_is_invalid(self):
        result = await search_flights("M", "BCN", _future_date())
        assert result["error"]["code"] == "INVALID_IATA"

    async def test_four_char_iata_is_invalid(self):
        result = await search_flights("MADR", "BCN", _future_date())
        assert result["error"]["code"] == "INVALID_IATA"


class TestSearchFlightsHappyPath:
    async def test_returns_flight_results(self, sample_flight_result):
        mock_provider = AsyncMock()
        mock_provider.search_flights.return_value = [sample_flight_result]

        with patch("src.tools.flights.SerpApiProvider", return_value=mock_provider):
            result = await search_flights("MAD", "BCN", _future_date())

        assert "error" not in result
        assert result["count"] == 1
        assert result["results"][0]["airline"] == "IB"
        assert result["results"][0]["duration_minutes"] == 75

    async def test_passes_return_date_to_provider(self, sample_flight_result):
        mock_provider = AsyncMock()
        mock_provider.search_flights.return_value = [sample_flight_result]

        with patch("src.tools.flights.SerpApiProvider", return_value=mock_provider):
            await search_flights("MAD", "BCN", _future_date(), return_date="2099-06-22")

        call_kwargs = mock_provider.search_flights.call_args.kwargs
        assert call_kwargs["return_date"] == "2099-06-22"

    async def test_passes_adults_and_cabin_to_provider(self, sample_flight_result):
        mock_provider = AsyncMock()
        mock_provider.search_flights.return_value = [sample_flight_result]

        with patch("src.tools.flights.SerpApiProvider", return_value=mock_provider):
            await search_flights("MAD", "BCN", _future_date(), adults=2, cabin_class="BUSINESS")

        call_kwargs = mock_provider.search_flights.call_args.kwargs
        assert call_kwargs["adults"] == 2
        assert call_kwargs["cabin_class"] == "BUSINESS"

    async def test_empty_results_returns_empty_list(self):
        mock_provider = AsyncMock()
        mock_provider.search_flights.return_value = []

        with patch("src.tools.flights.SerpApiProvider", return_value=mock_provider):
            result = await search_flights("MAD", "BCN", _future_date())

        assert result["count"] == 0
        assert result["results"] == []


class TestSearchFlightsErrorHandling:
    async def test_rate_limit_returns_rate_limit_error(self):
        mock_provider = AsyncMock()
        mock_provider.search_flights.side_effect = RateLimitError("quota exceeded")

        with patch("src.tools.flights.SerpApiProvider", return_value=mock_provider):
            result = await search_flights("MAD", "BCN", _future_date())

        assert result["error"]["code"] == "RATE_LIMIT"
        assert "quota" in result["error"]["message"].lower()

    async def test_generic_provider_error_returns_provider_error(self):
        mock_provider = AsyncMock()
        mock_provider.search_flights.side_effect = RuntimeError("unexpected crash")

        with patch("src.tools.flights.SerpApiProvider", return_value=mock_provider):
            result = await search_flights("MAD", "BCN", _future_date())

        assert result["error"]["code"] == "PROVIDER_ERROR"

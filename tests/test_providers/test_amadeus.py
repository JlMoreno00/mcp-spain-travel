from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.models.flight import Airport, FlightResult
from src.providers.amadeus import (
    AmadeusProvider,
    RateLimitError,
    _blocking_search,
    _parse_duration_minutes,
)


def _make_amadeus_offer(
    dep_iata: str = "MAD",
    arr_iata: str = "BCN",
    dep_time: str = "2099-06-15T09:00:00",
    arr_time: str = "2099-06-15T10:15:00",
    duration: str = "PT1H15M",
    price: str = "89.50",
    airline: str = "IB",
    flight_num: str = "1234",
    stops: int = 0,
) -> dict:
    segments = [
        {
            "departure": {"iataCode": dep_iata, "at": dep_time},
            "arrival": {"iataCode": arr_iata, "at": arr_time},
            "carrierCode": airline,
            "number": flight_num,
        }
    ]
    if stops > 0:
        segments.append(
            {
                "departure": {"iataCode": arr_iata, "at": arr_time},
                "arrival": {"iataCode": "VLC", "at": "2099-06-15T11:00:00"},
                "carrierCode": airline,
                "number": "9999",
            }
        )
    return {
        "itineraries": [{"segments": segments, "duration": duration}],
        "price": {"grandTotal": price, "currency": "EUR"},
        "validatingAirlineCodes": [airline],
        "travelerPricings": [{"fareDetailsBySegment": [{"cabin": "ECONOMY"}]}],
    }


class TestParseDurationMinutes:
    def test_parses_hours_and_minutes(self):
        assert _parse_duration_minutes("PT1H15M") == 75

    def test_parses_hours_only(self):
        assert _parse_duration_minutes("PT2H") == 120

    def test_parses_minutes_only(self):
        assert _parse_duration_minutes("PT45M") == 45

    def test_returns_zero_for_invalid(self):
        assert _parse_duration_minutes("INVALID") == 0


class TestBlockingSearch:
    def _make_mock_client(self, data):
        mock_response = MagicMock()
        mock_response.data = data
        mock_client = MagicMock()
        mock_client.shopping.flight_offers_search.get.return_value = mock_response
        return mock_client

    def test_successful_search_returns_flight_results(self):
        offer = _make_amadeus_offer()
        mock_client = self._make_mock_client([offer])
        mock_amadeus = MagicMock()
        mock_amadeus.Client.return_value = mock_client

        with patch.dict("sys.modules", {"amadeus": mock_amadeus}):
            results = _blocking_search(
                "test_id", "test_secret", "MAD", "BCN", "2099-06-15", None, 1, "ECONOMY"
            )

        assert len(results) == 1
        assert results[0].airline == "IB"
        assert results[0].duration_minutes == 75
        assert results[0].price_eur == pytest.approx(89.50)
        assert results[0].stops == 0

    def test_rate_limit_429_raises_rate_limit_error(self):
        mock_client_error = MagicMock()
        mock_client_error.response.status_code = 429

        mock_amadeus = MagicMock()
        mock_amadeus.ClientError = type("ClientError", (Exception,), {})
        exc = mock_amadeus.ClientError("rate limit")
        exc.response = MagicMock(status_code=429)

        mock_amadeus_client = MagicMock()
        mock_amadeus_client.shopping.flight_offers_search.get.side_effect = exc
        mock_amadeus.Client.return_value = mock_amadeus_client

        with patch.dict("sys.modules", {"amadeus": mock_amadeus}):
            with pytest.raises(RateLimitError):
                _blocking_search("id", "secret", "MAD", "BCN", "2099-06-15", None, 1, "ECONOMY")

    def test_bad_request_400_raises_client_error(self):
        mock_amadeus = MagicMock()
        mock_amadeus.ClientError = type("ClientError", (Exception,), {})
        exc = mock_amadeus.ClientError("bad request")
        exc.response = MagicMock(status_code=400)

        mock_client = MagicMock()
        mock_client.shopping.flight_offers_search.get.side_effect = exc
        mock_amadeus.Client.return_value = mock_client

        with patch.dict("sys.modules", {"amadeus": mock_amadeus}):
            with pytest.raises(mock_amadeus.ClientError):
                _blocking_search("id", "secret", "MAD", "BCN", "2099-06-15", None, 1, "ECONOMY")

    def test_empty_response_returns_empty_list(self):
        mock_client = self._make_mock_client([])
        mock_amadeus = MagicMock()
        mock_amadeus.Client.return_value = mock_client

        with patch.dict("sys.modules", {"amadeus": mock_amadeus}):
            results = _blocking_search(
                "id", "secret", "MAD", "BCN", "2099-06-15", None, 1, "ECONOMY"
            )
        assert results == []

    def test_return_date_is_passed_to_client(self):
        offer = _make_amadeus_offer()
        mock_client = self._make_mock_client([offer])
        mock_amadeus = MagicMock()
        mock_amadeus.Client.return_value = mock_client

        with patch.dict("sys.modules", {"amadeus": mock_amadeus}):
            _blocking_search(
                "id", "secret", "MAD", "BCN", "2099-06-15", "2099-06-22", 2, "BUSINESS"
            )

        call_kwargs = mock_client.shopping.flight_offers_search.get.call_args.kwargs
        assert call_kwargs.get("returnDate") == "2099-06-22"
        assert call_kwargs.get("adults") == 2


class TestAmadeusProvider:
    async def test_search_returns_results(self, mock_env, sample_flight_result):
        provider = AmadeusProvider()
        with patch("src.providers.amadeus._blocking_search", return_value=[sample_flight_result]):
            results = await provider.search_flights("MAD", "BCN", "2099-06-15")
        assert len(results) == 1
        assert results[0].airline == "IB"

    async def test_rate_limit_error_propagates(self, mock_env):
        provider = AmadeusProvider()
        with patch("src.providers.amadeus._blocking_search", side_effect=RateLimitError("quota")):
            with pytest.raises(RateLimitError):
                await provider.search_flights("MAD", "BCN", "2099-06-15")

    async def test_caches_results_on_second_call(self, mock_env, sample_flight_result):
        provider = AmadeusProvider()
        with patch(
            "src.providers.amadeus._blocking_search", return_value=[sample_flight_result]
        ) as mock_fn:
            await provider.search_flights("MAD", "BCN", "2099-06-15")
            await provider.search_flights("MAD", "BCN", "2099-06-15")
        mock_fn.assert_called_once()

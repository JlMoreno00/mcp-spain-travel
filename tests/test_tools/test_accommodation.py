from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.providers.google_hotels import RateLimitError
from src.tools.accommodation import search_accommodation


def _future_checkin() -> str:
    return "2099-06-15"


def _future_checkout() -> str:
    return "2099-06-17"


class TestSearchAccommodationValidation:
    async def test_past_checkin_returns_invalid_date_error(self):
        result = await search_accommodation("Madrid", "2020-01-01", "2020-01-03")
        assert result["error"]["code"] == "INVALID_DATE"
        assert "future" in result["error"]["message"].lower()

    async def test_checkout_before_checkin_returns_invalid_date_error(self):
        result = await search_accommodation("Madrid", _future_checkin(), "2099-06-10")
        assert result["error"]["code"] == "INVALID_DATE"
        assert "after" in result["error"]["message"].lower()

    async def test_checkout_same_as_checkin_returns_invalid_date_error(self):
        result = await search_accommodation("Madrid", _future_checkin(), _future_checkin())
        assert result["error"]["code"] == "INVALID_DATE"

    async def test_bad_checkin_format_returns_invalid_date_error(self):
        result = await search_accommodation("Madrid", "15/06/2099", _future_checkout())
        assert result["error"]["code"] == "INVALID_DATE"
        assert "check_in_date" in result["error"]["message"]

    async def test_bad_checkout_format_returns_invalid_date_error(self):
        result = await search_accommodation("Madrid", _future_checkin(), "17/06/2099")
        assert result["error"]["code"] == "INVALID_DATE"
        assert "check_out_date" in result["error"]["message"]


class TestSearchAccommodationHappyPath:
    async def test_returns_results_with_nights(self, sample_accommodation_result):
        mock_provider = AsyncMock()
        mock_provider.search_hotels.return_value = [sample_accommodation_result]

        with patch("src.tools.accommodation.GoogleHotelsProvider", return_value=mock_provider):
            result = await search_accommodation("Madrid", _future_checkin(), _future_checkout())

        assert "error" not in result
        assert result["count"] == 1
        assert result["nights"] == 2
        assert result["results"][0]["name"] == "Hotel Dorsett Madrid"

    async def test_nights_calculated_correctly(self, sample_accommodation_result):
        mock_provider = AsyncMock()
        mock_provider.search_hotels.return_value = [sample_accommodation_result]

        with patch("src.tools.accommodation.GoogleHotelsProvider", return_value=mock_provider):
            result = await search_accommodation("Barcelona", "2099-07-01", "2099-07-05")

        assert result["nights"] == 4

    async def test_results_sorted_by_price_ascending(self, sample_accommodation_result):
        from src.models.accommodation import AccommodationResult

        cheap = AccommodationResult(name="Cheap", price_per_night_eur=40.0)
        expensive = AccommodationResult(name="Expensive", price_per_night_eur=200.0)
        mid = AccommodationResult(name="Mid", price_per_night_eur=90.0)

        mock_provider = AsyncMock()
        mock_provider.search_hotels.return_value = [expensive, cheap, mid]

        with patch("src.tools.accommodation.GoogleHotelsProvider", return_value=mock_provider):
            result = await search_accommodation("Sevilla", _future_checkin(), _future_checkout())

        prices = [r["price_per_night_eur"] for r in result["results"]]
        assert prices == [40.0, 90.0, 200.0]

    async def test_null_price_sorted_last(self):
        from src.models.accommodation import AccommodationResult

        priced = AccommodationResult(name="Has Price", price_per_night_eur=50.0)
        no_price = AccommodationResult(name="No Price", price_per_night_eur=None)

        mock_provider = AsyncMock()
        mock_provider.search_hotels.return_value = [no_price, priced]

        with patch("src.tools.accommodation.GoogleHotelsProvider", return_value=mock_provider):
            result = await search_accommodation("Valencia", _future_checkin(), _future_checkout())

        assert result["results"][0]["name"] == "Has Price"
        assert result["results"][1]["name"] == "No Price"

    async def test_empty_results_returns_zero_count(self):
        mock_provider = AsyncMock()
        mock_provider.search_hotels.return_value = []

        with patch("src.tools.accommodation.GoogleHotelsProvider", return_value=mock_provider):
            result = await search_accommodation("Madrid", _future_checkin(), _future_checkout())

        assert result["count"] == 0
        assert result["results"] == []


class TestSearchAccommodationMaxPriceFilter:
    async def test_max_price_filters_expensive_hotels(self):
        from src.models.accommodation import AccommodationResult

        cheap = AccommodationResult(name="Cheap", price_per_night_eur=40.0)
        expensive = AccommodationResult(name="Expensive", price_per_night_eur=200.0)

        mock_provider = AsyncMock()
        mock_provider.search_hotels.return_value = [cheap, expensive]

        with patch("src.tools.accommodation.GoogleHotelsProvider", return_value=mock_provider):
            result = await search_accommodation(
                "Madrid", _future_checkin(), _future_checkout(), max_price=100.0
            )

        assert result["count"] == 1
        assert result["results"][0]["name"] == "Cheap"

    async def test_max_price_includes_exactly_at_limit(self):
        from src.models.accommodation import AccommodationResult

        at_limit = AccommodationResult(name="At Limit", price_per_night_eur=100.0)

        mock_provider = AsyncMock()
        mock_provider.search_hotels.return_value = [at_limit]

        with patch("src.tools.accommodation.GoogleHotelsProvider", return_value=mock_provider):
            result = await search_accommodation(
                "Madrid", _future_checkin(), _future_checkout(), max_price=100.0
            )

        assert result["count"] == 1

    async def test_max_price_excludes_null_price_hotels(self):
        from src.models.accommodation import AccommodationResult

        no_price = AccommodationResult(name="No Price", price_per_night_eur=None)

        mock_provider = AsyncMock()
        mock_provider.search_hotels.return_value = [no_price]

        with patch("src.tools.accommodation.GoogleHotelsProvider", return_value=mock_provider):
            result = await search_accommodation(
                "Madrid", _future_checkin(), _future_checkout(), max_price=100.0
            )

        assert result["count"] == 0

    async def test_no_max_price_returns_all(self):
        from src.models.accommodation import AccommodationResult

        hotels = [
            AccommodationResult(name=f"Hotel {i}", price_per_night_eur=float(i * 50))
            for i in range(1, 6)
        ]
        mock_provider = AsyncMock()
        mock_provider.search_hotels.return_value = hotels

        with patch("src.tools.accommodation.GoogleHotelsProvider", return_value=mock_provider):
            result = await search_accommodation("Madrid", _future_checkin(), _future_checkout())

        assert result["count"] == 5


class TestSearchAccommodationErrorHandling:
    async def test_rate_limit_returns_rate_limit_error(self):
        mock_provider = AsyncMock()
        mock_provider.search_hotels.side_effect = RateLimitError("quota exceeded")

        with patch("src.tools.accommodation.GoogleHotelsProvider", return_value=mock_provider):
            result = await search_accommodation("Madrid", _future_checkin(), _future_checkout())

        assert result["error"]["code"] == "RATE_LIMIT"
        assert "quota" in result["error"]["message"].lower()

    async def test_generic_provider_error_returns_provider_error(self):
        mock_provider = AsyncMock()
        mock_provider.search_hotels.side_effect = RuntimeError("unexpected crash")

        with patch("src.tools.accommodation.GoogleHotelsProvider", return_value=mock_provider):
            result = await search_accommodation("Madrid", _future_checkin(), _future_checkout())

        assert result["error"]["code"] == "PROVIDER_ERROR"
        assert "unexpected crash" in result["error"]["message"]

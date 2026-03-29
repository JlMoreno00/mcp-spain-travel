from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.providers.duffel import DuffelProvider, RateLimitError, _blocking_search, _map_offer


def _make_simple_obj(**kwargs):
    """Create a simple namespace object — avoids MagicMock intercepting .name"""
    from types import SimpleNamespace

    return SimpleNamespace(**kwargs)


def _make_mock_segment(
    origin_iata="MAD",
    dest_iata="BCN",
    dep_at="2099-06-15T09:00:00",
    arr_at="2099-06-15T10:15:00",
    carrier_code="IB",
    flight_num="1234",
):
    seg = _make_simple_obj(
        origin=_make_simple_obj(
            iata_code=origin_iata, name=f"{origin_iata} Airport", city_name=origin_iata
        ),
        destination=_make_simple_obj(
            iata_code=dest_iata, name=f"{dest_iata} Airport", city_name=dest_iata
        ),
        departing_at=dep_at,
        arriving_at=arr_at,
        operating_carrier=_make_simple_obj(iata_code=carrier_code),
        operating_carrier_flight_number=flight_num,
    )
    return seg


def _make_mock_offer(
    origin_iata="MAD",
    dest_iata="BCN",
    dep_at="2099-06-15T09:00:00",
    arr_at="2099-06-15T10:15:00",
    price="89.50",
    currency="EUR",
    airline_name="Iberia",
    airline_iata="IB",
    stops=0,
):
    segments = [_make_mock_segment(origin_iata, dest_iata, dep_at, arr_at, airline_iata, "1234")]
    if stops > 0:
        segments.append(
            _make_mock_segment(
                dest_iata, "VLC", arr_at, "2099-06-15T12:00:00", airline_iata, "5678"
            )
        )

    first_slice = _make_simple_obj(segments=segments)
    offer = _make_simple_obj(
        slices=[first_slice],
        total_amount=price,
        total_currency=currency,
        owner=_make_simple_obj(name=airline_name, iata_code=airline_iata),
        passengers=[],
    )
    return offer


class TestMapOffer:
    def test_maps_basic_offer(self):
        offer = _make_mock_offer()
        result = _map_offer(offer)
        assert result.airline == "Iberia"
        assert result.origin_airport.iata_code == "MAD"
        assert result.destination_airport.iata_code == "BCN"
        assert result.duration_minutes == 75
        assert result.price_eur == pytest.approx(89.50)
        assert result.stops == 0

    def test_maps_offer_with_stops(self):
        offer = _make_mock_offer(stops=1)
        result = _map_offer(offer)
        assert result.stops == 1


class TestBlockingSearch:
    def test_successful_search_returns_results(self):
        mock_offer = _make_mock_offer()
        mock_request = MagicMock()
        mock_request.offers = [mock_offer]

        mock_duffel_module = MagicMock()
        mock_client = MagicMock()
        mock_client.offer_requests.create.return_value = mock_request
        mock_duffel_module.Duffel.return_value = mock_client

        with patch.dict("sys.modules", {"duffel_api": mock_duffel_module}):
            results = _blocking_search(
                "test_token", "MAD", "BCN", "2099-06-15", None, 1, "economy"
            )

        assert len(results) == 1
        assert results[0].airline == "Iberia"

    def test_rate_limit_raises_error(self):
        mock_duffel_module = MagicMock()
        mock_client = MagicMock()
        mock_client.offer_requests.create.side_effect = Exception("429 rate limit")
        mock_duffel_module.Duffel.return_value = mock_client

        with patch.dict("sys.modules", {"duffel_api": mock_duffel_module}):
            with pytest.raises(RateLimitError):
                _blocking_search("token", "MAD", "BCN", "2099-06-15", None, 1, "economy")

    def test_empty_offers_returns_empty_list(self):
        mock_request = MagicMock()
        mock_request.offers = []

        mock_duffel_module = MagicMock()
        mock_client = MagicMock()
        mock_client.offer_requests.create.return_value = mock_request
        mock_duffel_module.Duffel.return_value = mock_client

        with patch.dict("sys.modules", {"duffel_api": mock_duffel_module}):
            results = _blocking_search("token", "MAD", "BCN", "2099-06-15", None, 1, "economy")
        assert results == []

    def test_return_date_creates_two_slices(self):
        mock_request = MagicMock()
        mock_request.offers = []

        mock_duffel_module = MagicMock()
        mock_client = MagicMock()
        mock_client.offer_requests.create.return_value = mock_request
        mock_duffel_module.Duffel.return_value = mock_client

        with patch.dict("sys.modules", {"duffel_api": mock_duffel_module}):
            _blocking_search("token", "MAD", "BCN", "2099-06-15", "2099-06-22", 2, "business")

        call_kwargs = mock_client.offer_requests.create.call_args.kwargs
        assert len(call_kwargs["slices"]) == 2
        assert call_kwargs["slices"][1]["departure_date"] == "2099-06-22"
        assert len(call_kwargs["passengers"]) == 2


class TestDuffelProvider:
    async def test_search_returns_results(self, mock_env, sample_flight_result):
        provider = DuffelProvider()
        with patch("src.providers.duffel._blocking_search", return_value=[sample_flight_result]):
            results = await provider.search_flights("MAD", "BCN", "2099-06-15")
        assert len(results) == 1

    async def test_rate_limit_propagates(self, mock_env):
        provider = DuffelProvider()
        with patch("src.providers.duffel._blocking_search", side_effect=RateLimitError("quota")):
            with pytest.raises(RateLimitError):
                await provider.search_flights("MAD", "BCN", "2099-06-15")

    async def test_caches_on_second_call(self, mock_env, sample_flight_result):
        provider = DuffelProvider()
        with patch(
            "src.providers.duffel._blocking_search", return_value=[sample_flight_result]
        ) as mock_fn:
            await provider.search_flights("MAD", "BCN", "2099-06-15")
            await provider.search_flights("MAD", "BCN", "2099-06-15")
        mock_fn.assert_called_once()

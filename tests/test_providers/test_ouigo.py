from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.models.train import TrainResult
from src.providers.ouigo import OUIGOProvider, _blocking_search, _map_trip


class TestBlockingSearch:
    def test_import_failure_returns_empty_list(self):
        with patch("builtins.__import__", side_effect=ImportError("no module")):
            result = _blocking_search("Madrid", "Barcelona", "2099-06-15")
        assert result == []

    def test_ouigo_exception_returns_empty_list(self):
        mock_trip = MagicMock()
        mock_trip.departure_timestamp = datetime(2099, 6, 15, 8, 0, 0)
        mock_trip.price = 9.99
        mock_trip._u_i_c_station_code = "60000"
        mock_trip.name = "OUIGO-100"
        mock_trip.outbound = "2099-06-15"

        mock_client = MagicMock()
        mock_client.journal_search.side_effect = RuntimeError("API down")
        mock_ouigo_class = MagicMock(return_value=mock_client)

        with patch.dict(
            "sys.modules", {"ouigo": MagicMock(), "ouigo.ouigo": MagicMock(Ouigo=mock_ouigo_class)}
        ):
            result = _blocking_search("Madrid", "Barcelona", "2099-06-15")
        assert result == []

    def test_successful_search_maps_results(self):
        mock_trip = MagicMock()
        mock_trip.departure_timestamp = datetime(2099, 6, 15, 8, 0, 0)
        mock_trip.price = 9.99
        mock_trip._u_i_c_station_code = "60000"
        mock_trip.name = "OUIGO-100"
        mock_trip.outbound = "2099-06-15"

        mock_client = MagicMock()
        mock_client.journal_search.return_value = [mock_trip]
        mock_ouigo_class = MagicMock(return_value=mock_client)
        mock_ouigo_module = MagicMock()
        mock_ouigo_module.Ouigo = mock_ouigo_class

        with patch.dict("sys.modules", {"ouigo": MagicMock(), "ouigo.ouigo": mock_ouigo_module}):
            result = _blocking_search("Madrid", "Barcelona", "2099-06-15")

        assert len(result) == 1
        assert result[0].operator == "OUIGO"
        assert result[0].price_eur == pytest.approx(9.99)

    def test_empty_trips_returns_empty_list(self):
        mock_client = MagicMock()
        mock_client.journal_search.return_value = []
        mock_ouigo_class = MagicMock(return_value=mock_client)
        mock_ouigo_module = MagicMock()
        mock_ouigo_module.Ouigo = mock_ouigo_class

        with patch.dict("sys.modules", {"ouigo": MagicMock(), "ouigo.ouigo": mock_ouigo_module}):
            result = _blocking_search("Madrid", "Barcelona", "2099-06-15")
        assert result == []


class TestMapTrip:
    def test_maps_trip_attributes(self):
        mock_trip = MagicMock()
        mock_trip.departure_timestamp = datetime(2099, 6, 15, 10, 0, 0)
        mock_trip.price = 19.99
        mock_trip._u_i_c_station_code = "71801"
        mock_trip.name = "OUIGO-500"
        mock_trip.outbound = "2099-06-15"

        result = _map_trip(mock_trip, "Madrid", "Barcelona")

        assert isinstance(result, TrainResult)
        assert result.operator == "OUIGO"
        assert result.price_eur == pytest.approx(19.99)
        assert result.booking_url == "https://www.ouigo.com/es/"


class TestOUIGOProvider:
    async def test_search_returns_empty_when_disabled(self, monkeypatch):
        monkeypatch.setenv("SPAIN_TRAVEL_OUIGO_ENABLED", "false")
        from src.config import get_settings

        get_settings.cache_clear()

        provider = OUIGOProvider()
        result = await provider.search_trains("Madrid", "Barcelona", "2099-06-15")
        assert result == []

    async def test_search_returns_empty_on_executor_exception(self, mock_env):
        provider = OUIGOProvider()
        with patch("src.providers.ouigo._blocking_search", side_effect=RuntimeError("crash")):
            result = await provider.search_trains("Madrid", "Barcelona", "2099-06-15")
        assert result == []

    async def test_search_returns_results_on_success(self, mock_env, sample_train_result):
        provider = OUIGOProvider()
        expected = [sample_train_result]
        with patch("src.providers.ouigo._blocking_search", return_value=expected):
            result = await provider.search_trains("Madrid", "Barcelona", "2099-06-15")
        assert result == expected

    async def test_search_caches_results(self, mock_env, sample_train_result):
        provider = OUIGOProvider()
        expected = [sample_train_result]
        with patch("src.providers.ouigo._blocking_search", return_value=expected) as mock_fn:
            await provider.search_trains("Madrid", "Barcelona", "2099-06-15")
            await provider.search_trains("Madrid", "Barcelona", "2099-06-15")
        mock_fn.assert_called_once()

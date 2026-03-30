from __future__ import annotations

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.models.connection import MultiLegResult, TrainLeg
from src.models.train import Station, TrainResult
from src.tools.trains import list_train_stations, search_trains


def _future_date() -> str:
    return "2099-06-15"


def _madrid_station() -> Station:
    return Station(
        name="Madrid Atocha", code="60000", city="Madrid", province="Madrid", station_types=["ld"]
    )


def _barcelona_station() -> Station:
    return Station(
        name="Barcelona Sants",
        code="71801",
        city="Barcelona",
        province="Barcelona",
        station_types=["ld"],
    )


def _no_connections():
    mock = MagicMock()
    mock.find_connections = AsyncMock(return_value=[])
    return mock


class TestSearchTrainsValidation:
    async def test_past_date_returns_invalid_date_error(self):
        result = await search_trains("Madrid", "Barcelona", "2020-01-01")
        assert result["error"]["code"] == "INVALID_DATE"
        assert "future" in result["error"]["message"].lower()

    async def test_invalid_date_format_returns_error(self):
        result = await search_trains("Madrid", "Barcelona", "not-a-date")
        assert result["error"]["code"] == "INVALID_DATE"

    async def test_today_is_accepted(self):
        today = date.today().isoformat()
        mock_renfe = AsyncMock()
        mock_renfe.search_trains.return_value = []
        mock_renfe.list_stations.return_value = [_madrid_station(), _barcelona_station()]
        mock_ouigo = AsyncMock()
        mock_ouigo.search_trains.return_value = []

        with (
            patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe),
            patch("src.tools.trains.OUIGOProvider", return_value=mock_ouigo),
            patch("src.tools.trains.ConnectionFinder", return_value=_no_connections()),
        ):
            result = await search_trains("Madrid", "Barcelona", today)

        assert "error" not in result or result.get("error", {}).get("code") != "INVALID_DATE"


class TestSearchTrainsHappyPath:
    async def test_both_providers_return_results(
        self, sample_train_result, sample_ouigo_train_result
    ):
        mock_renfe = AsyncMock()
        mock_renfe.search_trains.return_value = [sample_train_result]
        mock_ouigo = AsyncMock()
        mock_ouigo.search_trains.return_value = [sample_ouigo_train_result]

        with (
            patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe),
            patch("src.tools.trains.OUIGOProvider", return_value=mock_ouigo),
            patch("src.tools.trains.ConnectionFinder", return_value=_no_connections()),
        ):
            result = await search_trains("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        assert result["count"] == 2
        assert result["partial"] is False
        assert result["provider_errors"] == []
        operators = {r["operator"] for r in result["results"]}
        assert "Renfe AVE" in operators
        assert "OUIGO" in operators

    async def test_results_sorted_by_departure_time(
        self, sample_train_result, sample_ouigo_train_result
    ):
        mock_renfe = AsyncMock()
        mock_renfe.search_trains.return_value = [sample_train_result]
        mock_ouigo = AsyncMock()
        mock_ouigo.search_trains.return_value = [sample_ouigo_train_result]

        with (
            patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe),
            patch("src.tools.trains.OUIGOProvider", return_value=mock_ouigo),
            patch("src.tools.trains.ConnectionFinder", return_value=_no_connections()),
        ):
            result = await search_trains("Madrid", "Barcelona", _future_date())

        times = [r["departure_time"] for r in result["results"]]
        assert times == sorted(times)


class TestSearchTrainsDegradation:
    async def test_ouigo_fails_returns_partial_renfe_results(self, sample_train_result):
        mock_renfe = AsyncMock()
        mock_renfe.search_trains.return_value = [sample_train_result]
        mock_ouigo = AsyncMock()
        mock_ouigo.search_trains.side_effect = RuntimeError("OUIGO unavailable")

        with (
            patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe),
            patch("src.tools.trains.OUIGOProvider", return_value=mock_ouigo),
            patch("src.tools.trains.ConnectionFinder", return_value=_no_connections()),
        ):
            result = await search_trains("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        assert result["partial"] is True
        assert result["count"] == 1
        assert result["results"][0]["operator"] == "Renfe AVE"
        assert len(result["provider_errors"]) == 1

    async def test_renfe_fails_returns_partial_ouigo_results(self, sample_ouigo_train_result):
        mock_renfe = AsyncMock()
        mock_renfe.search_trains.side_effect = RuntimeError("Renfe GTFS down")
        mock_ouigo = AsyncMock()
        mock_ouigo.search_trains.return_value = [sample_ouigo_train_result]

        with (
            patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe),
            patch("src.tools.trains.OUIGOProvider", return_value=mock_ouigo),
            patch("src.tools.trains.ConnectionFinder", return_value=_no_connections()),
        ):
            result = await search_trains("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        assert result["partial"] is True
        assert result["count"] == 1
        assert result["results"][0]["operator"] == "OUIGO"

    async def test_both_providers_fail_returns_all_providers_down(self):
        mock_renfe = AsyncMock()
        mock_renfe.search_trains.side_effect = RuntimeError("Renfe down")
        mock_ouigo = AsyncMock()
        mock_ouigo.search_trains.side_effect = RuntimeError("OUIGO down")

        with (
            patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe),
            patch("src.tools.trains.OUIGOProvider", return_value=mock_ouigo),
        ):
            result = await search_trains("Madrid", "Barcelona", _future_date())

        assert result["error"]["code"] == "ALL_PROVIDERS_DOWN"


class TestSearchTrainsUnknownStation:
    async def test_unknown_origin_returns_unknown_station_error(self):
        mock_renfe = AsyncMock()
        mock_renfe.search_trains.return_value = []
        mock_renfe.list_stations.return_value = [_madrid_station(), _barcelona_station()]
        mock_ouigo = AsyncMock()
        mock_ouigo.search_trains.return_value = []

        with (
            patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe),
            patch("src.tools.trains.OUIGOProvider", return_value=mock_ouigo),
            patch("src.tools.trains.ConnectionFinder", return_value=_no_connections()),
        ):
            result = await search_trains("XYZ_INVALID", "Barcelona", _future_date())

        assert result["error"]["code"] == "UNKNOWN_STATION"
        assert "XYZ_INVALID" in result["error"]["message"]

    async def test_unknown_destination_returns_unknown_station_error(self):
        mock_renfe = AsyncMock()
        mock_renfe.search_trains.return_value = []
        mock_renfe.list_stations.return_value = [_madrid_station(), _barcelona_station()]
        mock_ouigo = AsyncMock()
        mock_ouigo.search_trains.return_value = []

        with (
            patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe),
            patch("src.tools.trains.OUIGOProvider", return_value=mock_ouigo),
            patch("src.tools.trains.ConnectionFinder", return_value=_no_connections()),
        ):
            result = await search_trains("Madrid", "INVALID_DEST", _future_date())

        assert result["error"]["code"] == "UNKNOWN_STATION"


class TestListTrainStations:
    async def test_returns_all_stations(self, sample_station, sample_barcelona_station):
        mock_renfe = AsyncMock()
        mock_renfe.list_stations.return_value = [sample_station, sample_barcelona_station]

        with patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe):
            result = await list_train_stations()

        assert result["count"] == 2
        assert len(result["stations"]) == 2

    async def test_city_filter_forwarded_to_provider(self, sample_station):
        mock_renfe = AsyncMock()
        mock_renfe.list_stations.return_value = [sample_station]

        with patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe):
            result = await list_train_stations(city="Madrid")

        mock_renfe.list_stations.assert_called_once_with(city="Madrid", station_type="all")
        assert result["count"] == 1

    async def test_provider_error_returns_error_dict(self):
        mock_renfe = AsyncMock()
        mock_renfe.list_stations.side_effect = RuntimeError("network error")

        with patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe):
            result = await list_train_stations()

        assert result["error"]["code"] == "PROVIDER_ERROR"

    async def test_no_match_returns_empty_list(self):
        mock_renfe = AsyncMock()
        mock_renfe.list_stations.return_value = []

        with patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe):
            result = await list_train_stations(city="NonexistentCity")

        assert result["count"] == 0
        assert result["stations"] == []


class TestSearchTrainsConnections:
    def _make_multi_leg_result(self) -> MultiLegResult:
        base = datetime(2099, 6, 15)
        return MultiLegResult(
            legs=[
                TrainLeg(
                    operator="Renfe AVE",
                    origin="Madrid",
                    destination="ZARAGOZA DELICIAS",
                    departure_time=base.replace(hour=9, minute=0),
                    arrival_time=base.replace(hour=10, minute=30),
                    duration_minutes=90,
                    price_eur=20.0,
                ),
                TrainLeg(
                    operator="Renfe AVE",
                    origin="ZARAGOZA DELICIAS",
                    destination="Barcelona",
                    departure_time=base.replace(hour=12, minute=0),
                    arrival_time=base.replace(hour=13, minute=30),
                    duration_minutes=90,
                    price_eur=25.0,
                ),
            ],
            total_duration_minutes=270,
            total_price_eur=45.0,
            connection_station="ZARAGOZA DELICIAS",
            connection_wait_minutes=90,
        )

    async def test_connections_field_always_present(
        self, sample_train_result, sample_ouigo_train_result
    ):
        mock_renfe = AsyncMock()
        mock_renfe.search_trains.return_value = [sample_train_result]
        mock_ouigo = AsyncMock()
        mock_ouigo.search_trains.return_value = [sample_ouigo_train_result]

        with (
            patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe),
            patch("src.tools.trains.OUIGOProvider", return_value=mock_ouigo),
            patch("src.tools.trains.ConnectionFinder", return_value=_no_connections()),
        ):
            result = await search_trains("Madrid", "Barcelona", _future_date())

        assert "connections" in result
        assert "connections_count" in result
        assert result["connections_count"] == 0

    async def test_connections_attempted_when_direct_results_empty(self):
        mock_renfe = AsyncMock()
        mock_renfe.search_trains.return_value = []
        mock_renfe.list_stations.return_value = [_madrid_station(), _barcelona_station()]
        mock_ouigo = AsyncMock()
        mock_ouigo.search_trains.return_value = []

        mock_finder = MagicMock()
        mock_finder.find_connections = AsyncMock(return_value=[self._make_multi_leg_result()])

        with (
            patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe),
            patch("src.tools.trains.OUIGOProvider", return_value=mock_ouigo),
            patch("src.tools.trains.ConnectionFinder", return_value=mock_finder),
        ):
            result = await search_trains("Madrid", "Barcelona", _future_date())

        mock_finder.find_connections.assert_called_once()
        assert result["connections_count"] == 1
        assert len(result["connections"]) == 1

    async def test_connections_not_attempted_when_three_or_more_direct_results(self):
        train = TrainResult(
            operator="Renfe AVE",
            origin_code="60000",
            destination_code="71801",
            departure_time=datetime(2099, 6, 15, 10, 0),
            arrival_time=datetime(2099, 6, 15, 12, 30),
            duration_minutes=150,
            price_eur=45.0,
        )
        mock_renfe = AsyncMock()
        mock_renfe.search_trains.return_value = [train, train, train]
        mock_ouigo = AsyncMock()
        mock_ouigo.search_trains.return_value = []

        mock_finder = MagicMock()
        mock_finder.find_connections = AsyncMock(return_value=[])

        with (
            patch("src.tools.trains.RenfeCKANProvider", return_value=mock_renfe),
            patch("src.tools.trains.OUIGOProvider", return_value=mock_ouigo),
            patch("src.tools.trains.ConnectionFinder", return_value=mock_finder),
        ):
            result = await search_trains("Madrid", "Barcelona", _future_date())

        mock_finder.find_connections.assert_not_called()
        assert result["count"] == 3

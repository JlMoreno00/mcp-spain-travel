from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.models.train import TrainResult
from src.providers.renfe.connections import ConnectionFinder, HUB_STATIONS

_PATCH = "src.providers.renfe.connections.search_with_prices"
_ORIGIN = "Sevilla"
_DEST = "Santander"
_DATE = "2099-06-15"


def _make_train(
    dep_hour: int,
    dep_min: int,
    arr_hour: int,
    arr_min: int,
    price: float | None = 30.0,
) -> TrainResult:
    base = datetime(2099, 6, 15)
    return TrainResult(
        operator="Renfe AVE",
        train_number="AVE-001",
        origin_code="60000",
        destination_code="71801",
        departure_time=base.replace(hour=dep_hour, minute=dep_min),
        arrival_time=base.replace(hour=arr_hour, minute=arr_min),
        duration_minutes=(arr_hour * 60 + arr_min) - (dep_hour * 60 + dep_min),
        price_eur=price,
        booking_url="https://www.renfe.com",
    )


def _leg_side_effect(leg1: TrainResult, leg2: TrainResult):
    async def _fn(origin_name: str, dest_name: str, date: str) -> list[TrainResult]:
        if origin_name == _ORIGIN:
            return [leg1]
        return [leg2]

    return _fn


class TestHubFiltering:
    async def test_skips_hub_matching_origin_city(self):
        finder = ConnectionFinder()
        with patch(_PATCH, new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            await finder.find_connections("Madrid", "Sevilla", _DATE)

        all_args = [arg for c in mock_search.call_args_list for arg in c.args]
        assert "MADRID (TODAS)" not in all_args

    async def test_skips_hub_matching_destination_city(self):
        finder = ConnectionFinder()
        with patch(_PATCH, new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            await finder.find_connections("Sevilla", "Barcelona", _DATE)

        all_args = [arg for c in mock_search.call_args_list for arg in c.args]
        assert "BARCELONA (TODAS)" not in all_args

    async def test_skips_both_origin_and_destination_hubs(self):
        finder = ConnectionFinder()
        with patch(_PATCH, new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            await finder.find_connections("Madrid", "Barcelona", _DATE)

        all_args = [arg for c in mock_search.call_args_list for arg in c.args]
        assert "MADRID (TODAS)" not in all_args
        assert "BARCELONA (TODAS)" not in all_args

    async def test_does_not_skip_unrelated_hub(self):
        finder = ConnectionFinder()
        with patch(_PATCH, new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            await finder.find_connections(_ORIGIN, _DEST, _DATE)

        all_args = [arg for c in mock_search.call_args_list for arg in c.args]
        assert "MADRID (TODAS)" in all_args


class TestConnectionTimeWindow:
    async def test_valid_connection_included(self):
        leg1 = _make_train(9, 0, 11, 0)
        leg2 = _make_train(12, 0, 14, 0)

        finder = ConnectionFinder()
        with patch(_PATCH, side_effect=_leg_side_effect(leg1, leg2)):
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert len(results) > 0
        assert all(45 <= r.connection_wait_minutes <= 180 for r in results)

    async def test_too_short_connection_excluded(self):
        leg1 = _make_train(9, 0, 11, 0)
        leg2 = _make_train(11, 20, 13, 0)

        finder = ConnectionFinder()
        with patch(_PATCH, side_effect=_leg_side_effect(leg1, leg2)):
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert results == []

    async def test_too_long_connection_excluded(self):
        leg1 = _make_train(9, 0, 11, 0)
        leg2 = _make_train(15, 10, 17, 0)

        finder = ConnectionFinder()
        with patch(_PATCH, side_effect=_leg_side_effect(leg1, leg2)):
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert results == []

    async def test_exactly_at_min_boundary_included(self):
        leg1 = _make_train(9, 0, 11, 0)
        leg2 = _make_train(11, 45, 13, 30)

        finder = ConnectionFinder()
        with patch(_PATCH, side_effect=_leg_side_effect(leg1, leg2)):
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert len(results) > 0
        assert results[0].connection_wait_minutes == 45

    async def test_exactly_at_max_boundary_included(self):
        leg1 = _make_train(9, 0, 11, 0)
        leg2 = _make_train(14, 0, 16, 0)

        finder = ConnectionFinder()
        with patch(_PATCH, side_effect=_leg_side_effect(leg1, leg2)):
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert len(results) > 0
        assert results[0].connection_wait_minutes == 180


class TestParallelHubSearch:
    async def test_all_eligible_hubs_are_searched(self):
        finder = ConnectionFinder()
        eligible_hub_names = {
            hub["name"]
            for hub in HUB_STATIONS
            if not finder._matches_city(_ORIGIN, hub["city"])
            and not finder._matches_city(_DEST, hub["city"])
        }

        with patch(_PATCH, new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            await finder.find_connections(_ORIGIN, _DEST, _DATE)

        searched_args = {arg for c in mock_search.call_args_list for arg in c.args}
        assert eligible_hub_names.issubset(searched_args)

    async def test_each_hub_searches_two_legs(self):
        finder = ConnectionFinder()
        eligible_count = sum(
            1
            for hub in HUB_STATIONS
            if not finder._matches_city(_ORIGIN, hub["city"])
            and not finder._matches_city(_DEST, hub["city"])
        )

        with patch(_PATCH, new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert mock_search.call_count == eligible_count * 2


class TestSortingAndLimiting:
    async def test_results_sorted_by_total_duration(self):
        leg1_early = _make_train(9, 0, 10, 0)
        leg2_short = _make_train(11, 0, 12, 0)
        leg1_late = _make_train(10, 0, 12, 0)
        leg2_long = _make_train(13, 0, 16, 0)

        async def _fn(origin_name: str, dest_name: str, date: str) -> list[TrainResult]:
            if origin_name == _ORIGIN:
                return [leg1_early, leg1_late]
            return [leg2_short, leg2_long]

        finder = ConnectionFinder()
        with patch(_PATCH, side_effect=_fn):
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert len(results) > 0
        durations = [r.total_duration_minutes for r in results]
        assert durations == sorted(durations)

    async def test_returns_at_most_10_results(self):
        leg1_trains = [_make_train(9, 0, 11, 0)] * 3
        leg2_trains = [_make_train(12, 0, 14, 0)] * 4

        async def _fn(origin_name: str, dest_name: str, date: str) -> list[TrainResult]:
            if origin_name == _ORIGIN:
                return leg1_trains
            return leg2_trains

        finder = ConnectionFinder()
        with patch(_PATCH, side_effect=_fn):
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert len(results) <= 10


class TestNoConnections:
    async def test_no_trains_on_either_leg_returns_empty(self):
        finder = ConnectionFinder()
        with patch(_PATCH, new_callable=AsyncMock) as mock_search:
            mock_search.return_value = []
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert results == []

    async def test_no_compatible_times_returns_empty(self):
        leg1 = _make_train(9, 0, 11, 0)
        leg2 = _make_train(9, 30, 11, 30)

        finder = ConnectionFinder()
        with patch(_PATCH, side_effect=_leg_side_effect(leg1, leg2)):
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert results == []


class TestErrorTolerance:
    async def test_hub_failure_does_not_stop_other_hubs(self):
        leg1 = _make_train(9, 0, 11, 0)
        leg2 = _make_train(12, 0, 14, 0)

        async def _fn(origin_name: str, dest_name: str, date: str) -> list[TrainResult]:
            if "MADRID" in origin_name or "MADRID" in dest_name:
                raise RuntimeError("Madrid hub unavailable")
            if origin_name == _ORIGIN:
                return [leg1]
            return [leg2]

        finder = ConnectionFinder()
        with patch(_PATCH, side_effect=_fn):
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert len(results) > 0

    async def test_all_hubs_fail_returns_empty(self):
        finder = ConnectionFinder()
        with patch(_PATCH, new_callable=AsyncMock) as mock_search:
            mock_search.side_effect = RuntimeError("Network error")
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert results == []


class TestPriceCalculation:
    async def test_total_price_is_sum_of_legs(self):
        leg1 = _make_train(9, 0, 11, 0, price=25.0)
        leg2 = _make_train(12, 0, 14, 0, price=35.0)

        finder = ConnectionFinder()
        with patch(_PATCH, side_effect=_leg_side_effect(leg1, leg2)):
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert len(results) > 0
        assert results[0].total_price_eur == pytest.approx(60.0)

    async def test_total_price_none_when_any_leg_missing_price(self):
        leg1 = _make_train(9, 0, 11, 0, price=None)
        leg2 = _make_train(12, 0, 14, 0, price=35.0)

        finder = ConnectionFinder()
        with patch(_PATCH, side_effect=_leg_side_effect(leg1, leg2)):
            results = await finder.find_connections(_ORIGIN, _DEST, _DATE)

        assert len(results) > 0
        assert results[0].total_price_eur is None

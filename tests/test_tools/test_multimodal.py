from __future__ import annotations

from unittest.mock import patch

import pytest

from src.tools.multimodal import compare_travel_options


def _future_date() -> str:
    return "2099-06-15"


def _train_response(sample_train_result) -> dict:
    return {
        "results": [sample_train_result.model_dump(mode="json")],
        "count": 1,
        "partial": False,
        "provider_errors": [],
    }


def _flight_response(sample_flight_result) -> dict:
    data = sample_flight_result.model_dump(mode="json")
    data["airline"] = data["airline"]
    data["duration_minutes"] = data["duration_minutes"]
    return {
        "results": [data],
        "count": 1,
    }


def _bus_response(sample_bus_result) -> dict:
    return {
        "results": [sample_bus_result.model_dump(mode="json")],
        "count": 1,
    }


_NO_BUS = {"results": [], "count": 0}
_BUS_ERROR = {"error": {"code": "UNKNOWN_CITY", "message": "city not found"}}


class TestCompareTravelOptionsValidation:
    async def test_past_date_returns_invalid_date_error(self):
        result = await compare_travel_options("Madrid", "Barcelona", "2020-01-01")
        assert result["error"]["code"] == "INVALID_DATE"

    async def test_bad_date_format_returns_invalid_date_error(self):
        result = await compare_travel_options("Madrid", "Barcelona", "not-a-date")
        assert result["error"]["code"] == "INVALID_DATE"


class TestCompareTravelOptionsBothModes:
    async def test_both_trains_and_flights_returned(
        self, sample_train_result, sample_flight_result
    ):
        train_resp = _train_response(sample_train_result)
        flight_resp = _flight_response(sample_flight_result)

        with (
            patch("src.tools.multimodal.search_trains", return_value=train_resp),
            patch("src.tools.multimodal.search_flights", return_value=flight_resp),
            patch("src.tools.multimodal.search_buses", return_value=_NO_BUS),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        modes = {opt["mode"] for opt in result["options"]}
        assert "train" in modes
        assert "flight" in modes
        assert result["partial"] is False

    async def test_cheapest_fastest_greenest_are_computed(
        self, sample_train_result, sample_flight_result
    ):
        train_resp = _train_response(sample_train_result)
        flight_resp = _flight_response(sample_flight_result)

        with (
            patch("src.tools.multimodal.search_trains", return_value=train_resp),
            patch("src.tools.multimodal.search_flights", return_value=flight_resp),
            patch("src.tools.multimodal.search_buses", return_value=_NO_BUS),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        assert result["cheapest"] is not None
        assert result["fastest"] is not None
        assert result["greenest"] is not None

    async def test_co2_estimate_is_included(self, sample_train_result, sample_flight_result):
        train_resp = _train_response(sample_train_result)
        flight_resp = _flight_response(sample_flight_result)

        with (
            patch("src.tools.multimodal.search_trains", return_value=train_resp),
            patch("src.tools.multimodal.search_flights", return_value=flight_resp),
            patch("src.tools.multimodal.search_buses", return_value=_NO_BUS),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        for opt in result["options"]:
            assert opt["co2_kg"] is not None
            assert opt["co2_kg"] > 0

    async def test_flight_co2_higher_than_train(self, sample_train_result, sample_flight_result):
        train_resp = _train_response(sample_train_result)
        flight_resp = _flight_response(sample_flight_result)

        with (
            patch("src.tools.multimodal.search_trains", return_value=train_resp),
            patch("src.tools.multimodal.search_flights", return_value=flight_resp),
            patch("src.tools.multimodal.search_buses", return_value=_NO_BUS),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        train_options = [o for o in result["options"] if o["mode"] == "train"]
        flight_options = [o for o in result["options"] if o["mode"] == "flight"]
        assert train_options[0]["co2_kg"] < flight_options[0]["co2_kg"]

    async def test_city_names_are_converted_to_iata_for_flights(
        self, sample_train_result, sample_flight_result
    ):
        train_resp = _train_response(sample_train_result)
        flight_resp = _flight_response(sample_flight_result)

        with (
            patch("src.tools.multimodal.search_trains", return_value=train_resp) as mock_trains,
            patch("src.tools.multimodal.search_flights", return_value=flight_resp) as mock_flights,
            patch("src.tools.multimodal.search_buses", return_value=_NO_BUS),
        ):
            await compare_travel_options("Madrid", "Barcelona", _future_date())

        flight_call_args = mock_flights.call_args
        assert flight_call_args.args[0] == "MAD"
        assert flight_call_args.args[1] == "BCN"


class TestCompareTravelOptionsBusMode:
    async def test_bus_results_included_when_available(
        self, sample_train_result, sample_flight_result, sample_bus_result
    ):
        with (
            patch(
                "src.tools.multimodal.search_trains",
                return_value=_train_response(sample_train_result),
            ),
            patch(
                "src.tools.multimodal.search_flights",
                return_value=_flight_response(sample_flight_result),
            ),
            patch(
                "src.tools.multimodal.search_buses",
                return_value=_bus_response(sample_bus_result),
            ),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        modes = {opt["mode"] for opt in result["options"]}
        assert "bus" in modes
        assert result["partial"] is False

    async def test_bus_co2_between_train_and_flight(
        self, sample_train_result, sample_flight_result, sample_bus_result
    ):
        with (
            patch(
                "src.tools.multimodal.search_trains",
                return_value=_train_response(sample_train_result),
            ),
            patch(
                "src.tools.multimodal.search_flights",
                return_value=_flight_response(sample_flight_result),
            ),
            patch(
                "src.tools.multimodal.search_buses",
                return_value=_bus_response(sample_bus_result),
            ),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        train_co2 = next(o["co2_kg"] for o in result["options"] if o["mode"] == "train")
        bus_co2 = next(o["co2_kg"] for o in result["options"] if o["mode"] == "bus")
        flight_co2 = next(o["co2_kg"] for o in result["options"] if o["mode"] == "flight")
        assert train_co2 < bus_co2 < flight_co2

    async def test_bus_error_still_returns_trains_and_flights(
        self, sample_train_result, sample_flight_result
    ):
        with (
            patch(
                "src.tools.multimodal.search_trains",
                return_value=_train_response(sample_train_result),
            ),
            patch(
                "src.tools.multimodal.search_flights",
                return_value=_flight_response(sample_flight_result),
            ),
            patch("src.tools.multimodal.search_buses", return_value=_BUS_ERROR),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        assert result["partial"] is True
        assert "bus" in result["missing_modes"]
        modes = {opt["mode"] for opt in result["options"]}
        assert "train" in modes
        assert "flight" in modes

    async def test_bus_exception_still_returns_trains_and_flights(
        self, sample_train_result, sample_flight_result
    ):
        with (
            patch(
                "src.tools.multimodal.search_trains",
                return_value=_train_response(sample_train_result),
            ),
            patch(
                "src.tools.multimodal.search_flights",
                return_value=_flight_response(sample_flight_result),
            ),
            patch("src.tools.multimodal.search_buses", side_effect=RuntimeError("bus crash")),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        assert result["partial"] is True


class TestCompareTravelOptionsPartial:
    async def test_only_trains_when_flights_error(self, sample_train_result):
        train_resp = _train_response(sample_train_result)
        flight_resp = {"error": {"code": "INVALID_IATA", "message": "bad code"}}

        with (
            patch("src.tools.multimodal.search_trains", return_value=train_resp),
            patch("src.tools.multimodal.search_flights", return_value=flight_resp),
            patch("src.tools.multimodal.search_buses", return_value=_BUS_ERROR),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        assert result["partial"] is True
        assert "flight" in result["missing_modes"]
        modes = {opt["mode"] for opt in result["options"]}
        assert modes == {"train"}

    async def test_only_flights_when_trains_error(self, sample_flight_result):
        train_resp = {"error": {"code": "ALL_PROVIDERS_DOWN", "message": "down"}}
        flight_resp = _flight_response(sample_flight_result)

        with (
            patch("src.tools.multimodal.search_trains", return_value=train_resp),
            patch("src.tools.multimodal.search_flights", return_value=flight_resp),
            patch("src.tools.multimodal.search_buses", return_value=_BUS_ERROR),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        assert result["partial"] is True
        assert "train" in result["missing_modes"]

    async def test_exception_in_train_search_treated_as_partial(self, sample_flight_result):
        flight_resp = _flight_response(sample_flight_result)

        with (
            patch("src.tools.multimodal.search_trains", side_effect=RuntimeError("crash")),
            patch("src.tools.multimodal.search_flights", return_value=flight_resp),
            patch("src.tools.multimodal.search_buses", return_value=_BUS_ERROR),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        assert "error" not in result
        assert result["partial"] is True


class TestCompareTravelOptionsAllDown:
    async def test_all_providers_down_returns_error(self):
        train_resp = {"error": {"code": "ALL_PROVIDERS_DOWN", "message": "down"}}
        flight_resp = {"error": {"code": "PROVIDER_ERROR", "message": "crash"}}

        with (
            patch("src.tools.multimodal.search_trains", return_value=train_resp),
            patch("src.tools.multimodal.search_flights", return_value=flight_resp),
            patch("src.tools.multimodal.search_buses", return_value=_BUS_ERROR),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        assert result["error"]["code"] == "ALL_PROVIDERS_DOWN"

    async def test_both_raise_exceptions_returns_error(self):
        with (
            patch("src.tools.multimodal.search_trains", side_effect=RuntimeError("train crash")),
            patch("src.tools.multimodal.search_flights", side_effect=RuntimeError("flight crash")),
            patch("src.tools.multimodal.search_buses", side_effect=RuntimeError("bus crash")),
        ):
            result = await compare_travel_options("Madrid", "Barcelona", _future_date())

        assert result["error"]["code"] == "ALL_PROVIDERS_DOWN"

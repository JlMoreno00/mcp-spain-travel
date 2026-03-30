from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
import respx
from httpx import Response

from src.providers.renfe import dwr
from src.providers.renfe.scraper import (
    _extract_dwr_token,
    _extract_train_list,
    _parse_trains_from_data,
    find_station_code,
    search_with_prices,
)


SAMPLE_DWR_TOKEN_RESPONSE = (
    '//#DWR-INSERT\n//#DWR-REPLY\nr.handleCallback("1","0","ABC123XYZ456TOKEN");\n'
)

SAMPLE_TRAIN_LIST_RESPONSE = (
    "//#DWR-INSERT\n"
    "//#DWR-REPLY\n"
    'r.handleCallback("3","0",'
    '{"listadoTrenes":[{"listviajeViewEnlaceBean":[{'
    '"tipoTrenUno":"AVE",'
    '"horaSalida":"10:00",'
    '"horaLlegada":"12:30",'
    '"duracionViajeTotalEnMinutos":150,'
    '"tarifaMinima":"45,50",'
    '"completo":false,'
    '"razonNoDisponible":"",'
    '"soloPlazaH":false,'
    '"numeroTren":"02251"'
    "}]}]});"
)

SAMPLE_TRAIN_LIST_RESPONSE_UNAVAILABLE = (
    "//#DWR-INSERT\n"
    "//#DWR-REPLY\n"
    'r.handleCallback("3","0",'
    '{"listadoTrenes":[{"listviajeViewEnlaceBean":[{'
    '"tipoTrenUno":"AVE",'
    '"horaSalida":"10:00",'
    '"horaLlegada":"12:30",'
    '"duracionViajeTotalEnMinutos":150,'
    '"tarifaMinima":null,'
    '"completo":true,'
    '"razonNoDisponible":"5",'
    '"soloPlazaH":false'
    "}]}]});"
)

SEARCH_URL = "https://venta.renfe.com/vol/buscarTren.do"
SYSTEM_ID_URL = "https://venta.renfe.com/vol/dwr/call/plaincall/__System.generateId.dwr"
UPDATE_SESSION_URL = (
    "https://venta.renfe.com/vol/dwr/call/plaincall/buyEnlacesManager.actualizaObjetosSesion.dwr"
)
TRAIN_LIST_URL = (
    "https://venta.renfe.com/vol/dwr/call/plaincall/trainEnlacesManager.getTrainsList.dwr"
)


class TestDWRUtils:
    def test_create_search_id_format(self):
        sid = dwr.create_search_id()
        assert sid.startswith("_")
        assert len(sid) == 5
        assert sid[1:].isalnum()

    def test_tokenify_zero_returns_empty(self):
        assert dwr.tokenify(0) == ""

    def test_tokenify_known_value(self):
        assert dwr.tokenify(1) == "2"
        assert dwr.tokenify(63) == "$"

    def test_tokenify_large_number(self):
        result = dwr.tokenify(64)
        assert len(result) == 2

    def test_batch_id_generator_sequential(self):
        gen = dwr.get_batch_id_generator()
        assert next(gen) == 0
        assert next(gen) == 1
        assert next(gen) == 2

    def test_create_session_script_id_format(self):
        token = "ABC123"
        sid = dwr.create_session_script_id(token)
        assert sid.startswith("ABC123/")
        assert "-" in sid

    def test_build_generate_id_payload_no_search_id(self):
        payload = dwr.build_generate_id_payload(0)
        assert "batchId=0" in payload
        assert "generateId" in payload
        assert "scriptSessionId=\n" in payload
        assert "buscarTrenEnlaces.do\n" in payload

    def test_build_generate_id_payload_with_search_id(self):
        payload = dwr.build_generate_id_payload(1, "_Ab3x")
        assert "batchId=1" in payload
        assert "_Ab3x" in payload

    def test_build_update_session_payload(self):
        payload = dwr.build_update_session_payload(2, "_Ab3x", "TOKEN/abc-def")
        assert "batchId=2" in payload
        assert "actualizaObjetosSesion" in payload
        assert "_Ab3x" in payload
        assert "TOKEN/abc-def" in payload

    def test_build_train_list_payload_one_way(self):
        payload = dwr.build_train_list_payload(3, "_Ab3x", "TOKEN/abc-def", "15/06/2099")
        assert "getTrainsList" in payload
        assert "15%2F06%2F2099" in payload
        assert "c0-e13=string:I\n" in payload

    def test_build_train_list_payload_round_trip(self):
        payload = dwr.build_train_list_payload(
            3, "_Ab3x", "TOKEN/abc-def", "15/06/2099", "22/06/2099"
        )
        assert "c0-e13=string:IV\n" in payload
        assert "22%2F06%2F2099" in payload


class TestTokenExtraction:
    def test_extract_dwr_token_success(self):
        token = _extract_dwr_token(SAMPLE_DWR_TOKEN_RESPONSE)
        assert token == "ABC123XYZ456TOKEN"

    def test_extract_dwr_token_missing_raises(self):
        with pytest.raises(ValueError, match="DWR token not found"):
            _extract_dwr_token("some garbage response without token")

    def test_extract_train_list_success(self):
        data = _extract_train_list(SAMPLE_TRAIN_LIST_RESPONSE)
        assert "listadoTrenes" in data
        assert len(data["listadoTrenes"]) == 1

    def test_extract_train_list_missing_raises(self):
        with pytest.raises(ValueError, match="Train list JSON not found"):
            _extract_train_list("no json here")


class TestTrainParsing:
    def test_parse_available_train(self):
        data = {
            "listadoTrenes": [
                {
                    "listviajeViewEnlaceBean": [
                        {
                            "tipoTrenUno": "AVE",
                            "horaSalida": "10:00",
                            "horaLlegada": "12:30",
                            "duracionViajeTotalEnMinutos": 150,
                            "tarifaMinima": "45,50",
                            "completo": False,
                            "razonNoDisponible": "",
                            "soloPlazaH": False,
                            "numeroTren": "02251",
                        }
                    ]
                }
            ]
        }
        departure_dt = datetime(2099, 6, 15, 0, 0)
        trains = _parse_trains_from_data(data, "60000", "71801", departure_dt)

        assert len(trains) == 1
        t = trains[0]
        assert t["operator"] == "AVE"
        assert t["price_eur"] == pytest.approx(45.50)
        assert t["duration_minutes"] == 150
        assert t["departure_time"] == datetime(2099, 6, 15, 10, 0)
        assert t["arrival_time"] == datetime(2099, 6, 15, 12, 30)
        assert t["origin_code"] == "60000"
        assert t["destination_code"] == "71801"
        assert t["train_number"] == "02251"

    def test_parse_unavailable_train_skipped(self):
        data = {
            "listadoTrenes": [
                {
                    "listviajeViewEnlaceBean": [
                        {
                            "tipoTrenUno": "AVE",
                            "horaSalida": "10:00",
                            "horaLlegada": "12:30",
                            "duracionViajeTotalEnMinutos": 150,
                            "tarifaMinima": None,
                            "completo": True,
                            "razonNoDisponible": "5",
                            "soloPlazaH": False,
                        }
                    ]
                }
            ]
        }
        trains = _parse_trains_from_data(data, "60000", "71801", datetime(2099, 6, 15))
        assert trains == []

    def test_parse_empty_listado(self):
        trains = _parse_trains_from_data(
            {"listadoTrenes": []}, "60000", "71801", datetime(2099, 6, 15)
        )
        assert trains == []

    def test_parse_price_with_comma_decimal(self):
        data = {
            "listadoTrenes": [
                {
                    "listviajeViewEnlaceBean": [
                        {
                            "tipoTrenUno": "ALVIA",
                            "horaSalida": "08:00",
                            "horaLlegada": "11:15",
                            "duracionViajeTotalEnMinutos": 195,
                            "tarifaMinima": "123,90",
                            "completo": False,
                            "razonNoDisponible": "8",
                            "soloPlazaH": False,
                        }
                    ]
                }
            ]
        }
        trains = _parse_trains_from_data(data, "60000", "71801", datetime(2099, 6, 15))
        assert len(trains) == 1
        assert trains[0]["price_eur"] == pytest.approx(123.90)

    def test_parse_zero_price_becomes_none(self):
        data = {
            "listadoTrenes": [
                {
                    "listviajeViewEnlaceBean": [
                        {
                            "tipoTrenUno": "AVE",
                            "horaSalida": "10:00",
                            "horaLlegada": "12:30",
                            "duracionViajeTotalEnMinutos": 150,
                            "tarifaMinima": "0",
                            "completo": False,
                            "razonNoDisponible": "",
                            "soloPlazaH": False,
                        }
                    ]
                }
            ]
        }
        trains = _parse_trains_from_data(data, "60000", "71801", datetime(2099, 6, 15))
        assert len(trains) == 1
        assert trains[0]["price_eur"] is None

    def test_parse_skips_malformed_entry(self):
        data = {
            "listadoTrenes": [
                {
                    "listviajeViewEnlaceBean": [
                        {"tipoTrenUno": "AVE"},
                        {
                            "tipoTrenUno": "ALVIA",
                            "horaSalida": "09:00",
                            "horaLlegada": "11:30",
                            "duracionViajeTotalEnMinutos": 150,
                            "tarifaMinima": "30,00",
                            "completo": False,
                            "razonNoDisponible": "",
                            "soloPlazaH": False,
                        },
                    ]
                }
            ]
        }
        trains = _parse_trains_from_data(data, "60000", "71801", datetime(2099, 6, 15))
        assert len(trains) == 1
        assert trains[0]["operator"] == "ALVIA"


class TestFindStationCode:
    def test_finds_known_station(self):
        result = find_station_code("MADRID")
        assert result is not None
        name, code = result
        assert code

    def test_case_insensitive_lookup(self):
        lower = find_station_code("madrid")
        upper = find_station_code("MADRID")
        assert lower is not None
        assert upper is not None
        assert lower[1] == upper[1]

    def test_unknown_station_returns_none(self):
        result = find_station_code("XXXXXXNONEXISTENTXXXXXX")
        assert result is None


class TestSearchWithPrices:
    @respx.mock
    async def test_returns_train_results_on_success(self):
        respx.post(SEARCH_URL).mock(return_value=Response(200, text="ok"))
        respx.post(SYSTEM_ID_URL).mock(
            side_effect=[
                Response(200, text='//#DWR\nr.handleCallback("0","0","PRIMING");\n'),
                Response(200, text=SAMPLE_DWR_TOKEN_RESPONSE),
            ]
        )
        respx.post(UPDATE_SESSION_URL).mock(return_value=Response(200, text="ok"))
        respx.post(TRAIN_LIST_URL).mock(
            return_value=Response(200, text=SAMPLE_TRAIN_LIST_RESPONSE)
        )

        results = await search_with_prices("MADRID", "BARCELONA", "2099-06-15")
        assert len(results) == 1
        assert results[0].operator == "AVE"
        assert results[0].price_eur == pytest.approx(45.50)
        assert results[0].departure_time == datetime(2099, 6, 15, 10, 0)

    @respx.mock
    async def test_unknown_origin_returns_empty(self):
        results = await search_with_prices("XXXXXXNONEXISTENTXXXXXX", "MADRID", "2099-06-15")
        assert results == []

    @respx.mock
    async def test_unknown_destination_returns_empty(self):
        results = await search_with_prices("MADRID", "XXXXXXNONEXISTENTXXXXXX", "2099-06-15")
        assert results == []

    @respx.mock
    async def test_network_failure_raises(self):
        respx.post(SEARCH_URL).mock(return_value=Response(503))

        with pytest.raises(Exception):
            await search_with_prices("MADRID", "BARCELONA", "2099-06-15")

    @respx.mock
    async def test_skips_unavailable_trains(self):
        respx.post(SEARCH_URL).mock(return_value=Response(200, text="ok"))
        respx.post(SYSTEM_ID_URL).mock(
            side_effect=[
                Response(200, text='//#DWR\nr.handleCallback("0","0","PRIMING");\n'),
                Response(200, text=SAMPLE_DWR_TOKEN_RESPONSE),
            ]
        )
        respx.post(UPDATE_SESSION_URL).mock(return_value=Response(200, text="ok"))
        respx.post(TRAIN_LIST_URL).mock(
            return_value=Response(200, text=SAMPLE_TRAIN_LIST_RESPONSE_UNAVAILABLE)
        )

        results = await search_with_prices("MADRID", "BARCELONA", "2099-06-15")
        assert results == []

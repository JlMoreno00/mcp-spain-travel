from __future__ import annotations

from unittest.mock import patch

import pytest
import respx
from httpx import Response

from src.providers.renfe.ckan import RenfeCKANProvider, _parse_stations_csv


SAMPLE_CSV = (
    "CODIGO;DESCRIPCION;POBLACION;PROVINCIA;CERCANIAS;FEVE;LATITUD;LONGITUD\n"
    "60000;MADRID ATOCHA;MADRID;MADRID;NO;NO;40.4065;-3.6892\n"
    "71801;BARCELONA SANTS;BARCELONA;BARCELONA;NO;NO;41.3791;2.1402\n"
    "00001;VALENCIA NORTE;VALENCIA;VALENCIA;SI;NO;39.4699;-0.3763\n"
)

STATIONS_CSV_URL = "https://ssl.renfe.com/ftransit/Fichero_estaciones/estaciones.csv"


class TestParsStationsCSV:
    def test_parses_basic_fields(self):
        stations = _parse_stations_csv(SAMPLE_CSV)
        assert len(stations) == 3

        madrid = next(s for s in stations if s.code == "60000")
        assert madrid.name == "MADRID ATOCHA"
        assert madrid.city == "MADRID"
        assert madrid.province == "MADRID"
        assert madrid.latitude == pytest.approx(40.4065)
        assert madrid.longitude == pytest.approx(-3.6892)

    def test_cercanias_station_gets_correct_type(self):
        stations = _parse_stations_csv(SAMPLE_CSV)
        valencia = next(s for s in stations if s.code == "00001")
        assert "cercanias" in valencia.station_types

    def test_non_cercanias_non_feve_gets_ld_type(self):
        stations = _parse_stations_csv(SAMPLE_CSV)
        madrid = next(s for s in stations if s.code == "60000")
        assert madrid.station_types == ["ld"]

    def test_skips_rows_with_missing_code(self):
        csv_with_empty = (
            "CODIGO;DESCRIPCION;POBLACION;PROVINCIA;CERCANIAS;FEVE;LATITUD;LONGITUD\n"
            ";UNNAMED;CITY;PROV;NO;NO;;\n"
            "60000;MADRID ATOCHA;MADRID;MADRID;NO;NO;40.4065;-3.6892\n"
        )
        stations = _parse_stations_csv(csv_with_empty)
        assert len(stations) == 1
        assert stations[0].code == "60000"

    def test_handles_missing_lat_lon(self):
        csv_no_coords = (
            "CODIGO;DESCRIPCION;POBLACION;PROVINCIA;CERCANIAS;FEVE;LATITUD;LONGITUD\n"
            "99999;SIN COORDS;CIUDAD;PROV;NO;NO;;\n"
        )
        stations = _parse_stations_csv(csv_no_coords)
        assert len(stations) == 1
        assert stations[0].latitude is None
        assert stations[0].longitude is None


class TestRenfeCKANProviderHTTP:
    @respx.mock
    async def test_list_stations_fetches_csv(self, mock_env, tmp_path, monkeypatch):
        monkeypatch.setenv("SPAIN_TRAVEL_CACHE_DIR", str(tmp_path))
        from src.config import get_settings

        get_settings.cache_clear()

        respx.get(STATIONS_CSV_URL).mock(
            return_value=Response(200, content=SAMPLE_CSV.encode("latin-1"))
        )
        provider = RenfeCKANProvider()
        stations = await provider.list_stations()
        assert len(stations) == 3

    @respx.mock
    async def test_list_stations_filters_by_city(self, mock_env, tmp_path, monkeypatch):
        monkeypatch.setenv("SPAIN_TRAVEL_CACHE_DIR", str(tmp_path))
        from src.config import get_settings

        get_settings.cache_clear()

        respx.get(STATIONS_CSV_URL).mock(
            return_value=Response(200, content=SAMPLE_CSV.encode("latin-1"))
        )
        provider = RenfeCKANProvider()
        stations = await provider.list_stations(city="Madrid")
        assert len(stations) == 1
        assert stations[0].city == "MADRID"

    @respx.mock
    async def test_list_stations_city_no_match_returns_empty(
        self, mock_env, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("SPAIN_TRAVEL_CACHE_DIR", str(tmp_path))
        from src.config import get_settings

        get_settings.cache_clear()

        respx.get(STATIONS_CSV_URL).mock(
            return_value=Response(200, content=SAMPLE_CSV.encode("latin-1"))
        )
        provider = RenfeCKANProvider()
        stations = await provider.list_stations(city="NonexistentCity")
        assert stations == []

    @respx.mock
    async def test_list_stations_filters_by_type(self, mock_env, tmp_path, monkeypatch):
        monkeypatch.setenv("SPAIN_TRAVEL_CACHE_DIR", str(tmp_path))
        from src.config import get_settings

        get_settings.cache_clear()

        respx.get(STATIONS_CSV_URL).mock(
            return_value=Response(200, content=SAMPLE_CSV.encode("latin-1"))
        )
        provider = RenfeCKANProvider()
        stations = await provider.list_stations(station_type="cercanias")
        assert len(stations) == 1
        assert stations[0].code == "00001"

    @respx.mock
    async def test_list_stations_raises_on_http_error(self, mock_env, tmp_path, monkeypatch):
        monkeypatch.setenv("SPAIN_TRAVEL_CACHE_DIR", str(tmp_path))
        from src.config import get_settings

        get_settings.cache_clear()

        respx.get(STATIONS_CSV_URL).mock(return_value=Response(503))
        provider = RenfeCKANProvider()
        with pytest.raises(Exception):
            await provider.list_stations()

    @respx.mock
    async def test_list_stations_uses_cache_on_second_call(self, mock_env, tmp_path, monkeypatch):
        monkeypatch.setenv("SPAIN_TRAVEL_CACHE_DIR", str(tmp_path))
        from src.config import get_settings

        get_settings.cache_clear()

        respx.get(STATIONS_CSV_URL).mock(
            return_value=Response(200, content=SAMPLE_CSV.encode("latin-1"))
        )
        provider = RenfeCKANProvider()
        await provider.list_stations()
        await provider.list_stations()
        assert respx.calls.call_count == 1

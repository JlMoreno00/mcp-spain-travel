from __future__ import annotations

from datetime import datetime

import pytest

from src.config import get_settings
from src.models.flight import Airport, FlightResult
from src.models.train import Station, TrainResult


@pytest.fixture(autouse=True)
def clear_settings_cache():
    # lru_cache on get_settings persists across tests; clear so monkeypatch env vars take effect
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setenv("SPAIN_TRAVEL_SERPAPI_API_KEY", "test_serpapi_key_fake")
    monkeypatch.setenv("SPAIN_TRAVEL_OUIGO_ENABLED", "true")
    monkeypatch.setenv("SPAIN_TRAVEL_CACHE_DIR", "/tmp/test_spain_travel_cache")
    get_settings.cache_clear()


@pytest.fixture
def sample_station() -> Station:
    return Station(
        name="Madrid Atocha",
        code="60000",
        city="Madrid",
        province="Madrid",
        station_types=["ld", "ave"],
        latitude=40.4065,
        longitude=-3.6892,
    )


@pytest.fixture
def sample_barcelona_station() -> Station:
    return Station(
        name="Barcelona Sants",
        code="71801",
        city="Barcelona",
        province="Barcelona",
        station_types=["ld", "ave"],
        latitude=41.3791,
        longitude=2.1402,
    )


@pytest.fixture
def sample_train_result() -> TrainResult:
    return TrainResult(
        operator="Renfe AVE",
        train_number="AVE-100",
        origin_code="60000",
        destination_code="71801",
        departure_time=datetime(2099, 6, 15, 10, 0, 0),
        arrival_time=datetime(2099, 6, 15, 12, 30, 0),
        duration_minutes=150,
        price_eur=45.0,
        currency="EUR",
        booking_url="https://www.renfe.com",
    )


@pytest.fixture
def sample_ouigo_train_result() -> TrainResult:
    return TrainResult(
        operator="OUIGO",
        train_number="OUIGO-200",
        origin_code="60000",
        destination_code="71801",
        departure_time=datetime(2099, 6, 15, 8, 0, 0),
        arrival_time=datetime(2099, 6, 15, 10, 30, 0),
        duration_minutes=150,
        price_eur=9.99,
        currency="EUR",
        booking_url="https://www.ouigo.com/es/",
    )


@pytest.fixture
def sample_flight_result() -> FlightResult:
    return FlightResult(
        airline="IB",
        flight_number="IB1234",
        origin_airport=Airport(iata_code="MAD", name="Madrid Barajas", city="Madrid"),
        destination_airport=Airport(iata_code="BCN", name="Barcelona El Prat", city="Barcelona"),
        departure_time=datetime(2099, 6, 15, 9, 0, 0),
        arrival_time=datetime(2099, 6, 15, 10, 15, 0),
        duration_minutes=75,
        price_eur=89.50,
        currency="EUR",
        stops=0,
        cabin_class="ECONOMY",
    )

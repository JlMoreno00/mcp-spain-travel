from __future__ import annotations

from typing import Protocol, runtime_checkable

from src.models.flight import FlightResult
from src.models.train import Station, TrainResult


@runtime_checkable
class TrainProvider(Protocol):
    async def search_trains(
        self,
        origin: str,
        destination: str,
        date: str,
        passengers: int = 1,
    ) -> list[TrainResult]: ...


@runtime_checkable
class FlightProvider(Protocol):
    async def search_flights(
        self,
        origin: str,
        destination: str,
        departure_date: str,
        return_date: str | None = None,
        adults: int = 1,
        cabin_class: str = "ECONOMY",
    ) -> list[FlightResult]: ...


@runtime_checkable
class StationProvider(Protocol):
    async def list_stations(
        self,
        city: str | None = None,
        station_type: str = "all",
    ) -> list[Station]: ...
